"""POST-A-467: an export door is not a way round a per-person block on what the file holds.

POST-A-205's second slice found the client books export asking only `firm:admin` and the Partner role, so a Partner blocked
on the Team screen from the books, TDS or the bank was handed those files anyway. This item checked the other doors that
hand out a file of a client's figures:

  * the report exports (`routers/report_exports.py`) ask `accounting` read through `rbac()`, the pair every report screen
    they copy asks, and `rbac()` resolves the person's own grid, so a block reaches them; pinned below;
  * the year-end pack (`routers/year_end_exports.py`) asks `year_end` write to make a file and `year_end` read to list or
    open one, the pairs the year-end statements, notes and adjustments screens ask; pinned below;
  * THE SHARED REPORT'S LINK asked `report` read alone, which every staff role holds, for a file that is the client's Profit
    & Loss, Balance Sheet or Trial Balance. A member blocked from the books, and a Reviewer, whose role does not reach them,
    could open the books there. It now asks `accounting` read as well, before it reads a row.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import routers.report_exports as report_exports
import routers.shared_reports as sr
import routers.year_end_exports as year_end_exports
from core.permissions import can_user

FIRM = "firm-001"
CLIENT = "11111111-2222-3333-4444-555555555555"


def _user(role: str, overrides: dict | None = None) -> dict:
    return {"firm_id": FIRM, "id": "internal-user-id", "auth_user_id": "auth-id", "email": "m@f.test", "role": role,
            "permission_overrides": overrides or {}}


class _Reads:
    """A database that records whether anything was read and hands back one shared report."""

    def __init__(self):
        self.reads: list[str] = []

    def table(self, name):
        self.reads.append(name)
        reads = self

        class _Q:
            def select(self, *_a, **_k): return self
            def eq(self, *_a, **_k): return self
            def execute(self):
                return type("R", (), {"data": [{"id": "r1", "firm_id": FIRM, "client_id": CLIENT,
                                                "storage_path": f"shared_reports/{CLIENT}/pl.xlsx"}]})()
        assert reads
        return _Q()


class _Store:
    def __init__(self):
        self.signed: list[str] = []

    def from_(self, _bucket):
        return self

    def create_signed_url(self, path, *_a, **_k):
        self.signed.append(path)
        return {"signedURL": f"https://signed/{path}"}


@pytest.fixture
def world(monkeypatch):
    db, store = _Reads(), _Store()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: type("S", (), {"table": db.table, "storage": store})())
    monkeypatch.setattr(sc, "get_service_supabase", lambda: type("S", (), {"storage": store})())
    monkeypatch.setattr(sr, "_USE_MOCK", False)
    monkeypatch.setattr(sr, "can_access_client", lambda *_a: True)
    return db, store


@pytest.mark.parametrize("who", [
    _user("Manager", {"accounting:read": False}),
    _user("Partner", {"accounting:read": False}),
    _user("Reviewer"),
], ids=["manager-blocked-from-the-books", "partner-blocked-from-the-books", "reviewer"])
def test_a_shared_report_is_not_opened_by_someone_the_books_are_closed_to(world, who):
    db, store = world
    assert can_user(who, "report", "read"), "the premise: the old pair admitted them"
    with pytest.raises(HTTPException) as caught:
        sr.shared_report_link("r1", current_user=who)
    assert caught.value.status_code == 403
    assert "Accounting" in caught.value.detail and "Team screen" in caught.value.detail
    # asked before any row is read, so the refusal is no oracle on whether the report exists
    assert db.reads == [] and store.signed == []


@pytest.mark.parametrize("who", [_user("Manager"), _user("Executive"), _user("Partner")])
def test_someone_the_books_are_open_to_still_gets_the_link(world, who):
    out = sr.shared_report_link("r1", current_user=who)
    assert out["success"] and out["data"]["download_url"].startswith("https://signed/")


def test_a_reviewer_granted_the_books_by_name_gets_the_link(world):
    out = sr.shared_report_link("r1", current_user=_user("Reviewer", {"accounting:read": True}))
    assert out["success"]


def _gate(fn) -> str:
    return inspect.signature(fn).parameters["current_user"].default.dependency.__name__


@pytest.mark.parametrize("fn, gate", [
    (report_exports.export_report, "rbac_accounting_read"),
    (year_end_exports.export_financial_statements, "rbac_year_end_write"),
    (year_end_exports.export_notes, "rbac_year_end_write"),
    (year_end_exports.export_complete_pack, "rbac_year_end_write"),
    (year_end_exports.list_exports, "rbac_year_end_read"),
    (year_end_exports.get_download_url, "rbac_year_end_read"),
    (sr.shared_report_link, "rbac_report_read"),
])
def test_the_report_exports_and_the_year_end_pack_ask_the_pair_their_screens_ask(fn, gate):
    assert _gate(fn) == gate


def test_rbac_resolves_the_persons_own_grid_so_a_block_reaches_those_doors():
    from core.permissions import rbac
    blocked = _user("Partner", {"accounting:read": False, "year_end:write": False})
    for resource, action in (("accounting", "read"), ("year_end", "write")):
        with pytest.raises(HTTPException) as caught:
            rbac(resource, action)(current_user=blocked)
        assert caught.value.status_code == 403

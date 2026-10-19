"""What a bank taught the importer is a window a CA can read and forget (POST-A-117).

WHAT WAS WRONG
    When a bank's export is not a layout the importer recognises, a CA maps its columns once and the mapping is saved for that
    account and that exact header row. `GET /api/banking/statements/column-mappings` ("so a CA can see and correct what a bank
    taught us") and its DELETE had no screen, so a mapping that had gone wrong could be neither seen nor taken back. The list was
    also unbounded, returned every column, and answered a failed read as an EMPTY list, which a screen showing "what has been
    taught" would have drawn as "nothing".

WHAT IS HELD
    * the route answers a window of the newest layouts, newest first, with `has_more` taken from the read (one row more than the
      window is asked for, never returned), `limit` and the server's ceiling; a tie on `created_at` is broken by `id`;
    * only this firm's rows, narrowed to one client or account when asked, and only the columns a person reads;
    * a caller's client scope is checked before the read and applied to a firm-wide read;
    * a FAILED read raises; it is not an empty list;
    * `limit` is bounded at the door;
    * the browser's field list is the normalizer's MAPPING_KEYS, in order, so a field added on the server cannot vanish from the screen;
    * the panel sits in the accounts panel beside the import, and the two endpoints left the frozen list and the budget.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI

import routers.banking as banking
from core.list_window import MAX_LIST_LIMIT
from domain.banking.normalizer import MAPPING_KEYS
from services import bank_column_mapping_service as svc
from tests.e2e_harness import FakeDB

FIRM, CLIENT, ACCOUNT = "firm-1", "client-1", "acct-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "partner"}
API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"


def _row(n, *, firm=FIRM, client=CLIENT, account=ACCOUNT, created=None):
    return {"id": f"m{n:02d}", "firm_id": firm, "client_id": client, "bank_account_id": account,
            "header_fingerprint": f"fp{n}", "header_labels": ["Txn Date", "Narration"], "mapping": {"date": 0, "desc": 1},
            "created_by": "u1", "created_at": created or f"2026-10-{n:02d}T10:00:00Z", "updated_at": f"2026-10-{n:02d}T10:00:00Z"}


@pytest.fixture
def served(monkeypatch):
    db = FakeDB()
    checked = []
    monkeypatch.setattr(banking, "_db", lambda: db)
    monkeypatch.setattr(banking, "assert_client_access", lambda user, client_id, **kw: checked.append(client_id))
    monkeypatch.setattr(banking, "filter_by_client", lambda _user, rows: rows)
    return db, checked


def _ask(limit=100, client=CLIENT, account=None):
    return banking.list_column_mappings(client_id=client, bank_account_id=account, limit=limit, current_user=USER)["data"]


def test_the_newest_come_first_and_the_window_says_older_ones_exist(served):
    db, _ = served
    for n in (1, 2, 3):
        db.seed("bank_statement_column_mappings", _row(n))
    out = _ask(limit=2)
    assert [m["id"] for m in out["mappings"]] == ["m03", "m02"]
    assert out["returned"] == 2 and out["has_more"] is True and out["limit"] == 2 and out["max_limit"] == MAX_LIST_LIMIT
    whole = _ask(limit=3)
    assert [m["id"] for m in whole["mappings"]] == ["m03", "m02", "m01"] and whole["has_more"] is False


def test_a_tie_on_the_timestamp_is_broken_by_id(served):
    db, _ = served
    same = "2026-10-09T10:00:00Z"
    for n in (4, 5, 6):
        db.seed("bank_statement_column_mappings", _row(n, created=same))
    assert [m["id"] for m in _ask(limit=2)["mappings"]] == ["m06", "m05"] == [m["id"] for m in _ask(limit=3)["mappings"]][:2]


def test_only_this_firms_rows_narrowed_by_client_and_account(served):
    db, _ = served
    db.seed("bank_statement_column_mappings", _row(1))
    db.seed("bank_statement_column_mappings", _row(2, client="client-2"))
    db.seed("bank_statement_column_mappings", _row(3, firm="firm-2"))
    db.seed("bank_statement_column_mappings", _row(4, account="acct-2"))
    assert sorted(m["id"] for m in _ask()["mappings"]) == ["m01", "m04"]
    assert [m["id"] for m in _ask(account="acct-2")["mappings"]] == ["m04"]


def test_no_column_the_screen_has_no_use_for_is_sent(served):
    db, _ = served
    db.seed("bank_statement_column_mappings", _row(1))
    [row] = _ask()["mappings"]
    assert set(row) == {"id", "client_id", "bank_account_id", "header_labels", "mapping", "created_at", "updated_at"}


def test_the_scope_check_is_made_for_a_named_client(served):
    _, checked = served
    _ask()
    assert CLIENT in checked


def test_a_failed_read_raises_and_is_not_an_empty_list():
    class Broken:
        def table(self, *_a):
            raise RuntimeError("the table is unreachable")
    with pytest.raises(RuntimeError):
        svc.list_mappings(Broken(), FIRM, CLIENT, limit=10)
    # and the lookup an import depends on still tolerates a failure, on purpose
    assert svc.find_mapping(Broken(), FIRM, ACCOUNT, "fp") is None


def test_no_database_is_an_empty_window_of_the_same_shape(monkeypatch):
    monkeypatch.setattr(banking, "_db", lambda: None)
    monkeypatch.setattr(banking, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(banking, "filter_by_client", lambda _u, rows: rows)
    out = _ask(limit=10)
    assert out == {"mappings": [], "returned": 0, "has_more": False, "limit": 10, "max_limit": MAX_LIST_LIMIT}


def test_limit_is_bounded_at_the_door():
    app = FastAPI()
    app.include_router(banking.router)
    params = {p["name"]: p for p in app.openapi()["paths"]["/api/banking/statements/column-mappings"]["get"]["parameters"]}
    schema = params["limit"]["schema"]
    assert schema["minimum"] == 1 and schema["maximum"] == MAX_LIST_LIMIT and schema["default"] == 100


def test_the_browsers_field_list_is_the_normalizers_in_order():
    src = (WEB / "lib/banking/savedColumnMappings.ts").read_text(encoding="utf-8")
    block = src[src.index("export const MAPPING_FIELDS"):src.index("export interface DescribedField")]
    assert tuple(re.findall(r'key: "(\w+)"', block)) == MAPPING_KEYS


def test_the_panel_is_mounted_beside_the_import_and_its_endpoints_left_the_ratchets():
    panel = (WEB / "components/banking/AccountsPanel.tsx").read_text(encoding="utf-8")
    assert "<SavedColumnMappings clientId={clientId} accounts={accounts}" in panel
    from tests import test_a_computed_answer_nobody_can_open_is_named as frozen
    assert "/api/banking/statements/column-mappings" not in frozen.UNREACHED_COMPUTED_ANSWERS
    comp = (WEB / "components/banking/SavedColumnMappings.tsx").read_text(encoding="utf-8")
    assert "api.banking.listColumnMappings" in comp and "api.banking.deleteColumnMapping" in comp

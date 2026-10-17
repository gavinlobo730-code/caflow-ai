"""Recording the Form 3CD checklist as `finalised` is an approver's act (ledger POST-A-233).

THE RULE
    `PUT /api/income-tax/form-3cd` writes the clauses with `income_tax:write` (Executive and above: fieldwork), but
    giving the checklist the status `finalised`, or changing one that already has it, asks `income_tax:approve` (Manager
    and above), per PERSON, so a Partner's grid decision is the answer at the route and in the service. The same pair is
    what recording a tax audit as completed (migration 496) and an MCA filing as filed (493) ask.

WHAT IS HELD (no database: the real-Postgres half, the privilege on the table, is in test_500_*_pg.py)
    * an Executive saving `finalised` is refused (403 at the route, `FinalisedNeedsApprover` in the service) and
      nothing is written, for a new checklist and for an existing one;
    * an Executive saving ANY status over a checklist that already is `finalised` is refused: it cannot be reopened or
      rewritten from below the approver tier;
    * a Manager, or an Executive with an `income_tax:approve` grant, saves `finalised` and reopens it;
    * the service DEFAULTS to refusing: a caller that forgets to say whether the caller may approve is not trusted;
    * an Executive still saves `draft` and `review` clauses, new and existing (the fieldwork the tier exists for);
    * a Partner's grid BLOCK on `income_tax:approve` makes a Partner refused too (the per-person answer, not the role's);
    * a save that sends NO status leaves the status where it is (a new checklist starts as `draft`), so saving a clause
      never silently reopens a finalised checklist;
    * the write of a non-approver is ONE statement conditional on the checklist not being finalised: an approver who
      finalises it between the service's read and its write is not overwritten;
    * the premise of migration 500: nothing in `apps/web` references the table, under any spelling.

THE MOCK-MODE BRANCH of the route (no database: it echoes the request) refuses a non-approver's `finalised` like the
real one, but the other half of the rule, changing an already-finalised checklist, needs a stored row to read and is
enforced only where one exists.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from tests.e2e_harness import FakeDB

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontend_select_parser import browser_tables  # noqa: E402

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())
FY = "2025-26"
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _user(role: str, overrides: dict | None = None) -> dict:
    return {"id": str(uuid.uuid4()), "firm_id": FIRM, "role": role, "permission_overrides": overrides or {}}


def _stored(db: FakeDB) -> list[dict]:
    return [r for r in db.rows("tax_audit_checklists") if r["client_id"] == CLIENT]


@pytest.fixture()
def route(monkeypatch):
    """The route function with a FakeDB behind it and the client-access check out of the way."""
    import routers.income_tax as it
    db = FakeDB()
    monkeypatch.setattr(it, "_db", lambda: db)
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)

    def call(user: dict, status: str, clauses: dict | None = None):
        return it.save_form_3cd_manual_clauses(
            client_id=CLIENT, fy=FY, req=it.Form3cdManualClauses(clauses=clauses or {"31": "note"}, status=status),
            current_user=user)

    call.db = db
    return call


def test_an_executive_cannot_record_a_new_checklist_as_finalised(route):
    with pytest.raises(HTTPException) as e:
        route(_user("Executive"), "finalised")
    assert e.value.status_code == 403 and "approve" in e.value.detail
    assert _stored(route.db) == []


def test_an_executive_cannot_finalise_an_existing_draft(route):
    route(_user("Executive"), "draft", {"31": "first"})
    with pytest.raises(HTTPException) as e:
        route(_user("Executive"), "finalised", {"31": "second"})
    assert e.value.status_code == 403
    [row] = _stored(route.db)
    assert row["status"] == "draft" and row["clauses_json"] == {"31": "first"}


@pytest.mark.parametrize("status", ["draft", "review", "finalised"])
def test_an_executive_cannot_rewrite_or_reopen_a_finalised_checklist(route, status):
    route(_user("Manager"), "finalised", {"31": "signed"})
    with pytest.raises(HTTPException) as e:
        route(_user("Executive"), status, {"31": "changed"})
    assert e.value.status_code == 403
    [row] = _stored(route.db)
    assert row["status"] == "finalised" and row["clauses_json"] == {"31": "signed"}


def test_an_executive_still_records_fieldwork(route):
    route(_user("Executive"), "draft", {"31": "first"})
    route(_user("Executive"), "review", {"31": "second"})
    [row] = _stored(route.db)
    assert row["status"] == "review" and row["clauses_json"] == {"31": "second"}


@pytest.mark.parametrize("who", [_user("Manager"), _user("Partner"),
                                 _user("Executive", {"income_tax:approve": True})],
                         ids=["manager", "partner", "executive-with-a-grant"])
def test_someone_who_may_approve_finalises_and_reopens(route, who):
    route(who, "finalised", {"31": "signed"})
    assert _stored(route.db)[0]["status"] == "finalised"
    route(who, "draft", {"31": "reopened"})
    [row] = _stored(route.db)
    assert row["status"] == "draft" and row["clauses_json"] == {"31": "reopened"}


def test_a_partner_blocked_from_approving_is_refused_like_anyone_else(route):
    with pytest.raises(HTTPException) as e:
        route(_user("Partner", {"income_tax:approve": False}), "finalised")
    assert e.value.status_code == 403
    assert _stored(route.db) == []


def test_the_service_refuses_by_default_and_a_caller_that_forgets_is_not_trusted():
    from services.form_3cd_service import FinalisedNeedsApprover, save_manual_clauses
    db = FakeDB()
    with pytest.raises(FinalisedNeedsApprover):
        save_manual_clauses(db, FIRM, CLIENT, FY, {"31": "x"}, "finalised")
    assert _stored(db) == []
    save_manual_clauses(db, FIRM, CLIENT, FY, {"31": "x"}, "finalised", may_approve=True)
    with pytest.raises(FinalisedNeedsApprover):
        save_manual_clauses(db, FIRM, CLIENT, FY, {"31": "y"}, "draft")
    assert _stored(db)[0]["clauses_json"] == {"31": "x"}


def test_the_premise_of_migration_500_nothing_in_the_browser_names_the_table():
    """The privilege is revoked from signed-in sessions because nothing reaches the table from `apps/web`. A screen
    that starts to must decide, here, how it reads or writes the table, instead of finding the privilege gone."""
    if not WEB.is_dir():
        pytest.skip("frontend not in this checkout")
    tables = browser_tables(WEB)
    assert len(tables) > 50, "the browser-table scan found almost nothing: it has probably stopped working"
    assert "tax_audit_checklists" not in tables


def test_a_save_that_sends_no_status_leaves_the_status_where_it_is(route):
    route(_user("Manager"), "finalised", {"31": "signed"})
    # an approver saves a clause and says nothing about the status: still finalised
    out = route(_user("Manager"), None, {"31": "amended"})
    assert out["data"]["status"] == "finalised"
    [row] = _stored(route.db)
    assert row["status"] == "finalised" and row["clauses_json"] == {"31": "amended"}


def test_a_new_checklist_with_no_status_starts_as_a_draft_and_review_is_kept(route):
    out = route(_user("Executive"), None, {"31": "first"})
    assert out["data"]["status"] == "draft"
    route(_user("Executive"), "review", {"31": "second"})
    assert route(_user("Executive"), None, {"31": "third"})["data"]["status"] == "review"
    assert _stored(route.db)[0]["status"] == "review"


def test_an_approver_who_finalises_between_the_read_and_the_write_is_not_overwritten():
    """The service reads the checklist (draft), an approver finalises it, then the Executive's write arrives. The write is
    `UPDATE ... WHERE status <> 'finalised'`, so it changes nothing and is refused."""
    from services.form_3cd_service import FinalisedNeedsApprover, save_manual_clauses
    db = FakeDB()
    db.seed("tax_audit_checklists", {"firm_id": FIRM, "client_id": CLIENT, "financial_year": FY,
                                     "status": "draft", "clauses_json": {"31": "mine"}})
    real_table, calls = db.table, {"n": 0}

    def table(name):
        q = real_table(name)
        if name == "tax_audit_checklists":
            calls["n"] += 1
            if calls["n"] == 2:                       # the write's turn: the approver got there first
                for r in db.rows("tax_audit_checklists"):
                    r["status"], r["clauses_json"] = "finalised", {"31": "signed"}
        return q

    db.table = table
    with pytest.raises(FinalisedNeedsApprover):
        save_manual_clauses(db, FIRM, CLIENT, FY, {"31": "overwrite"}, "draft")
    [row] = _stored(db)
    assert row["status"] == "finalised" and row["clauses_json"] == {"31": "signed"}


def test_nothing_in_the_browser_names_the_table_under_any_spelling():
    """`browser_tables` recognises `.from("x")` with double quotes; a constant, a single-quoted name or a template literal
    would slip past it, so the premise of migration 500 is also held by a plain scan of every source file."""
    if not WEB.is_dir():
        pytest.skip("frontend not in this checkout")
    hits = []
    for path in WEB.rglob("*"):
        if (not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".mjs", ".json"}
                or set(path.parts) & {"node_modules", ".next", "out", ".vercel"}):
            continue
        try:
            if "tax_audit_checklists" in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(WEB).as_posix())
        except (UnicodeDecodeError, OSError):
            continue
    assert not hits, f"the browser now names tax_audit_checklists in {hits}: migration 500 took its privileges away"

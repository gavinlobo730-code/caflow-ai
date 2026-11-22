"""The firm's OWN payroll has its dates, on the practice's own record, and no list across the firm's clients carries them (POST-A-534).

WHAT WAS WRONG
    The firm runs its own staff's payroll on its practice record since POST-A-532, and nothing put that payroll's dates on any
    calendar. Obligations are generated from a client's engagements (the practice has none with itself) or by the fallback over the
    firm's clients (which the practice is not: guardrail G2). So a practice paying its own staff was reminded of every client's EPF,
    ESI and salary-TDS deposit, and of none of its own.

WHAT IS ASSERTED
    * with an active employee on its own payroll the practice gets, for a year, the three monthly deposits and the quarterly
      salary statement (40 rows), once: a second run adds nothing; with no such employee, or no practice, it gets none;
    * the firm-wide run generates them only for somebody firm-wide (a Partner, the nightly scheduler); a run confined to a member's
      clients does not, a run that names another client does not, a run that names the practice does;
    * THE ONE READ every list passes through leaves the practice's rows out when no client is named (the list, the count, the
      calendar, the dashboard and its "by client", the risks derived from an overdue row), and returns them when the practice is
      named, or when a caller says `include_practice=True`;
    * the nightly sweep still covers them (it reminds the people named, and tells only those who can open the practice) and My Work
      still shows a Partner the practice row that names them, while the practice's unassigned rows are not counted among the
      clients' unassigned work;
    * the firm hub's compliance tile leaves the practice out, like the worklist tiles beside it.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest

import mock_data
import services.compliance_obligation_service as cos
import services.internal_client_service as ics
from repositories.compliance_records_repository import compliance_records_repo

API = pathlib.Path(__file__).resolve().parents[1]
FIRM = "firm-own-payroll"
PRACTICE = "client-the-practice"
A_CLIENT = "client-acme"
FY = "2026-27"


@pytest.fixture
def practice(monkeypatch):
    """A firm whose practice is PRACTICE and has staff on its own payroll, with the compliance store put back afterwards."""
    kept = list(mock_data.MOCK_COMPLIANCE_RECORDS)
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(cos, "_the_practice_with_staff_on_its_payroll", lambda firm_id: PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(cos, "_audit_timeline_generate", lambda *a, **k: None)
    yield
    mock_data.MOCK_COMPLIANCE_RECORDS[:] = kept


def _row(client_id, due, status="Not Started", **more):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client_id, "compliance_type": "Payroll", "obligation_type": "EPF_DEPOSIT",
        "period_label": f"EPF {due}", "period_start": due[:8] + "01", "period_end": due, "due_date": due, "status": status,
        "priority": "medium", **more})


# ── generation ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_practice_gets_its_deposits_and_its_salary_statement_once(practice):
    first = cos.generate_for_the_practice(FIRM, FY)
    rows = compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["obligation_type"]] = by_type.get(r["obligation_type"], 0) + 1
    assert by_type == {"EPF_DEPOSIT": 12, "ESI_DEPOSIT": 12, "TDS_SALARY_DEPOSIT": 12, "TDS24Q": 4}, by_type
    assert first["generated"] == 40 and first["skipped"] == 0
    assert {r["client_id"] for r in rows} == {PRACTICE} and all(r.get("engagement_id") is None for r in rows)
    # The dates are the ones a client's payroll and TDS engagements get: the same builders, not a second copy.
    expected = {(s["obligation_type"], s["period_start"]): s["due_date"]
                for s in cos._payroll_obligations(FY) + [x for x in cos._tds_obligations(FY) if x["obligation_type"] == "TDS24Q"]}
    assert {(r["obligation_type"], str(r["period_start"])[:10]): str(r["due_date"])[:10] for r in rows} == expected
    again = cos.generate_for_the_practice(FIRM, FY)
    assert again["generated"] == 0 and again["skipped"] == 40
    assert len(compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE)) == 40


def test_a_practice_with_nobody_on_its_payroll_gets_nothing(practice, monkeypatch):
    monkeypatch.setattr(cos, "_the_practice_with_staff_on_its_payroll", lambda firm_id: None)
    assert cos.generate_for_the_practice(FIRM, FY) == {"generated": 0, "skipped": 0, "generated_ids": []}
    assert compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE) == []


def test_only_a_firm_wide_run_or_one_that_names_the_practice_generates_them(practice):
    confined = cos.generate_due(FIRM, financial_year=FY, allowed_client_ids={A_CLIENT})
    assert "practice" not in confined and compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE) == []
    other = cos.generate_due(FIRM, client_id=A_CLIENT, financial_year=FY)
    assert "practice" not in other and compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE) == []
    named = cos.generate_due(FIRM, client_id=PRACTICE, financial_year=FY)
    assert named["practice"] == {"generated": 40, "skipped": 0}
    whole = cos.generate_due(FIRM, financial_year=FY)
    assert whole["practice"] == {"generated": 0, "skipped": 40}, "the firm-wide run generated the practice's year a second time"


# ── the one read ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_read_that_names_no_client_leaves_the_practice_out_and_one_that_names_it_does_not(practice):
    late = (date.today() - timedelta(days=40)).isoformat()
    theirs = _row(A_CLIENT, late)
    ours = _row(PRACTICE, late)
    across = {r["id"] for r in compliance_records_repo.find_all(firm_id=FIRM)}
    assert theirs["id"] in across and ours["id"] not in across
    assert compliance_records_repo.count_all(firm_id=FIRM) == len(across)
    assert {r["id"] for r in compliance_records_repo.find_all(firm_id=FIRM, client_id=PRACTICE)} == {ours["id"]}
    assert ours["id"] in {r["id"] for r in compliance_records_repo.find_all(firm_id=FIRM, include_practice=True)}

    # The readers above it, each asked across the firm and then for the practice.
    cal = cos.calendar(FIRM)
    seen = {r["id"] for bucket in cal.values() for r in bucket}
    assert theirs["id"] in seen and ours["id"] not in seen
    named = cos.calendar(FIRM, client_id=PRACTICE)
    assert {r["id"] for bucket in named.values() for r in bucket} == {ours["id"]}

    board = cos.dashboard(FIRM)
    assert PRACTICE not in {str(c.get("client_id")) for c in board.get("by_client", [])}, "the practice is listed as a client"
    assert ours["id"] not in {str(q.get("id")) for q in board.get("queue", [])}

    from domain.risk_engine import _derive_compliance_risks
    derived = _derive_compliance_risks(firm_id=FIRM, client_id=None)
    assert PRACTICE not in {r.get("client_id") for r in derived}, "an overdue deposit of the practice became a client's risk"
    assert A_CLIENT in {r.get("client_id") for r in derived}, "premise: the client's overdue row is still a risk"


def test_no_firm_and_a_firm_with_no_practice_are_untouched(practice):
    row = _row(PRACTICE, "2026-05-15")
    other_firm = compliance_records_repo.create({**row, "id": None, "firm_id": "firm-with-no-practice"})
    assert other_firm["id"] in {r["id"] for r in compliance_records_repo.find_all(firm_id="firm-with-no-practice")}


# ── the sweep and My Work ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_nightly_sweep_covers_the_practice_and_a_members_own_run_does_not(practice, monkeypatch):
    today = date(2026, 6, 14)                      # one day before the 15th: the due-in-1 tier
    ours = _row(PRACTICE, "2026-06-15")
    told = []
    monkeypatch.setattr(cos, "_notify_internal", lambda firm_id, rec, tier, actor, reach_cache=None: told.append((rec["id"], tier)) or set())
    monkeypatch.setattr(cos.compliance_records_repo, "update", lambda *a, **k: None)
    cos.escalate(FIRM, today=today)
    assert (ours["id"], "due_1") in told, "the nightly sweep no longer reminds anybody of the practice's own deposit"
    told.clear()
    cos.escalate(FIRM, today=today, allowed_client_ids={A_CLIENT})
    assert told == [], "a run confined to a member's clients reached the practice"


def test_my_work_shows_a_partner_the_practice_row_that_names_them_and_counts_no_practice_row_as_unassigned(practice):
    named = _row(PRACTICE, "2026-06-15", preparer_id="u-partner")
    _row(PRACTICE, "2026-07-15")                   # nobody named: the practice's, not a client's unassigned work
    _row(A_CLIENT, "2026-06-15")                   # nobody named: a client's unassigned work
    mine = cos.my_obligations(FIRM, "u-partner")
    assert [o["id"] for o in mine["obligations"]] == [named["id"]]
    assert mine["unassigned_in_scope"] == 1, mine["unassigned_in_scope"]


# ── the hub ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_hubs_compliance_tile_leaves_the_practice_out_like_the_tiles_beside_it():
    tree = ast.parse((API / "services" / "hub_service.py").read_text(encoding="utf-8"))
    found = False
    for call in ast.walk(tree):
        if (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_count" and call.args
                and isinstance(call.args[0], ast.Constant) and call.args[0].value == "compliance_records"):
            found = True
            kw = {k.arg: k.value for k in call.keywords}
            assert "not_clients" in kw, "the compliance tile counts the practice's own obligations"
            assert isinstance(kw["not_clients"], ast.Call) and getattr(kw["not_clients"].func, "id", None) == "_not_practice"
    assert found, "the scan no longer finds the compliance tile's count"

"""An advance-tax obligation the client does not owe can be recorded as NOT REQUIRED, with a written reason (POST-A-267, item 4).

WHAT WAS WRONG
    The compliance calendar generates all four advance-tax instalments for every client with the engagement. A §44AD or §44ADA
    assessee pays the whole amount by 15 March (§211(1) proviso), so three of the four are not owed, and there was no state to put
    them in: Filed would state a payment never made, and an open row turns overdue on Deadlines, the Compliance tab, the health
    score and the dashboard. The advance-tax closer could only say "they were left as they are".

WHAT THIS HOLDS
    * one module names the settled and the filed states, and no other backend module spells the pair again, so a new state cannot
      be added in one place and forgotten in thirty;
    * "Not Required" is settled and is not a filing: never overdue, never counted as filed, never in an on-time coverage figure,
      in the calendar's completed bucket, not outstanding on the hub;
    * the door records it with the reason on the row and in the audit log, on ADVANCE_TAX only, from an open state only, for
      compliance.approve only; it is taken back with a reason to Not Started; no ordinary move reaches or leaves it; a record is
      not created in it; it cannot be marked filed while in it;
    * the advance-tax closer does not close or name a not-required instalment;
    * the database's status CHECK accepts it (the lifecycle and the constraint name the same states: the sibling test).
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.exceptions import ValidationError
from domain import compliance_record_service as crs
from domain.practice import compliance_overdue as co
from domain.practice.executive_dashboard import compliance_coverage
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_obligation_service as obligations
from services import hub_service
from tests.e2e_harness import FakeDB

API = Path(__file__).resolve().parents[1]


def _user(role="Partner", **extra):
    return {"id": "u1", "firm_id": "F1", "role": role, "email": f"{role.lower()}@f1.test",
            "auth_user_id": f"auth-{role.lower()}", **extra}


@pytest.fixture
def world(monkeypatch):
    import routers.compliance_ops as ops
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    db.seed("firms", {"id": "F1", "name": "F1", "locked_financial_years": []})
    monkeypatch.setattr(crs, "_filing_db", lambda: db)
    audited: list = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audited.append((a, k)))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(ops.router)
    state = {"user": _user()}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    yield TestClient(app, raise_server_exceptions=False), state, audited
    MOCK_COMPLIANCE_RECORDS.clear()


def _obl(obligation_type="ADVANCE_TAX", status="Not Started", due="2026-06-15", firm="F1", **extra):
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": "C1", "compliance_type": "Income Tax", "obligation_type": obligation_type,
        "period_label": f"Advance tax {due}", "period_start": due, "period_end": due, "due_date": due,
        "status": status, "filed_date": "2026-06-10" if status in co.FILED else None, **extra})


def _post(client, rec, door="not-required", reason="Presumptive under section 44AD: pays the whole amount by 15 March"):
    return client.post(f"/api/compliance/obligations/{rec['id']}/{door}", json={"reason": reason})


def _row(rec):
    return compliance_records_repo.find_by_id(rec["id"])


# ── one place names the states ───────────────────────────────────────────────

def test_no_backend_module_spells_the_filed_pair_outside_the_one_that_names_it():
    """Every reader asks `SETTLED` (is it still open?) or `FILED` (was it filed?): a literal pair answers neither on purpose, and a
    state added later would be missed by it. A collection naming every state of the CHECK (the hub's) is not the pair."""
    offenders = []
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", ".venv", "venv")) or rel == "domain/practice/compliance_overdue.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                words = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                # Exactly the pair: a full list of every state (the hub's copy of the CHECK) names them among the others.
                if set(words) == {"Filed", "Completed"}:
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders


def test_not_required_is_settled_and_is_not_a_filing():
    assert co.is_settled("Not Required") and not co.is_filed("Not Required")
    assert set(co.FILED) < set(co.SETTLED)
    late = {"status": "Not Required", "due_date": "2020-06-15"}
    assert co.is_overdue(late, date(2026, 11, 16)) is False


def test_the_coverage_figure_leaves_a_not_required_obligation_out_of_what_was_due():
    rows = [{"status": "Filed", "due_date": "2026-06-15"}, {"status": "Not Required", "due_date": "2026-09-15"}]
    got = compliance_coverage(rows, fy_start="2026-04-01", today="2026-11-16")
    assert (got["due"], got["filed"], got["percent"]) == (1, 1, 100)


def test_the_hub_does_not_count_it_outstanding():
    assert "Not Required" in hub_service._ALL["compliance_records"]
    assert "Not Required" not in hub_service._outstanding("compliance_records", hub_service._COMPLIANCE_DONE)


def test_the_calendar_puts_it_with_the_settled_ones(world):
    _obl(status="Not Required", due="2025-06-15")
    got = obligations.calendar("F1", today=date(2026, 11, 16))
    assert [r["status"] for r in got["completed"]] == ["Not Required"] and got["overdue"] == []


def test_the_spreadsheet_never_calls_a_not_required_instalment_filed(world):
    """The calendar's settled bucket holds filings and instalments recorded as not owed. The spreadsheet's "On the calendar" column
    used to call the whole bucket "Filed", so a file passed to a partner said a payment nobody made had been made."""
    import csv
    import io
    from domain.practice import obligation_csv
    _obl(status="Not Required", due="2025-06-15")
    _obl(status="Filed", due="2025-09-15")
    got = obligations.calendar("F1", today=date(2026, 11, 16))
    body = obligation_csv.from_rows([("completed", r) for r in got["completed"]], {})
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))[1:]
    assert {(r[0], r[4], r[5]) for r in rows} == {("2025-06-15", "Not Required", "Not required"), ("2025-09-15", "Filed", "Filed")}


# ── the door ─────────────────────────────────────────────────────────────────

def test_an_open_instalment_is_recorded_not_required_with_the_reason_kept(world):
    client, _state, audited = world
    rec = _obl(due="2025-06-15", notes="Client is presumptive")

    r = _post(client, rec)

    assert r.status_code == 200, r.text
    row = _row(rec)
    assert row["status"] == "Not Required" and row["filed_date"] is None
    assert row["notes"].startswith("Client is presumptive\n") and "section 44AD" in row["notes"]
    (args, kwargs), = audited
    assert args[1:4] == ("compliance_record", rec["id"], "not_required")
    assert kwargs["actor_id"] == "auth-partner" and kwargs["new_data"]["reason"].startswith("Presumptive")
    assert "not recorded as filed" in r.json()["data"]["message"]
    assert r.json()["data"]["obligation"]["risk_score"] == 0


@pytest.mark.parametrize("reason", ["", "   ", "x" * (crs.MAX_REOPEN_REASON_CHARS + 1)])
def test_a_reason_is_required_and_bounded(world, reason):
    client, _state, _audited = world
    rec = _obl()
    r = _post(client, rec, reason=reason)
    assert r.status_code == 422 and _row(rec)["status"] == "Not Started"


@pytest.mark.parametrize("otype", ["GSTR3B", "ITR", "TDS_NON_SALARY_DEPOSIT", "ESI_DEPOSIT", "AOC4"])
def test_only_an_advance_tax_instalment_can_be_recorded_not_required(world, otype):
    client, _state, _audited = world
    rec = _obl(obligation_type=otype)
    r = _post(client, rec)
    assert r.status_code == 422 and "advance-tax instalment" in r.json()["detail"]
    assert _row(rec)["status"] == "Not Started"


@pytest.mark.parametrize("status", ["Filed", "Completed", "Not Required"])
def test_a_filed_or_already_not_required_one_is_refused(world, status):
    client, _state, _audited = world
    rec = _obl(status=status)
    r = _post(client, rec)
    assert r.status_code == 422 and _row(rec)["status"] == status


@pytest.mark.parametrize("role,allowed", [("Partner", True), ("Manager", True), ("Executive", False), ("Reviewer", False)])
def test_the_door_is_compliance_approve(world, role, allowed):
    client, state, _audited = world
    state["user"] = _user(role)
    rec = _obl()
    r = _post(client, rec)
    assert (r.status_code == 200) is allowed, (role, r.status_code)
    assert _row(rec)["status"] == ("Not Required" if allowed else "Not Started")


def test_another_firms_obligation_is_not_found(world):
    client, _state, _audited = world
    rec = _obl(firm="F2")
    assert _post(client, rec).status_code == 404
    assert _row(rec)["status"] == "Not Started"


def test_it_is_taken_back_with_a_reason_to_not_started(world):
    client, _state, audited = world
    rec = _obl(status="Not Required", due="2025-06-15")

    r = _post(client, rec, door="required-again", reason="Business income is not presumptive this year")

    assert r.status_code == 200, r.text
    row = _row(rec)
    assert row["status"] == "Not Started" and "not presumptive this year" in row["notes"]
    assert audited[-1][0][3] == "required_again"
    assert co.is_overdue(row, date(2026, 11, 16))           # its date says it is late again
    assert _post(client, _obl(), door="required-again").status_code == 422   # nothing to take back


def test_no_ordinary_move_reaches_or_leaves_it_and_it_cannot_be_filed_or_born():
    assert crs.VALID_TRANSITIONS["Not Required"] == []
    assert all("Not Required" not in targets for targets in crs.VALID_TRANSITIONS.values())
    MOCK_COMPLIANCE_RECORDS.clear()
    rec = _obl(status="Not Required")
    with pytest.raises(ValidationError):
        crs.compliance_record_service.update_record(rec["id"], {"status": "In Progress"}, firm_id="F1")
    with pytest.raises(ValidationError, match="not required"):
        crs.compliance_record_service.mark_filed(rec["id"], firm_id="F1", filed_date="2026-06-10")
    with pytest.raises(ValidationError):
        crs.compliance_record_service.create_record(
            {"client_id": "C1", "compliance_type": "Income Tax", "period_start": "2026-06-15", "period_end": "2026-06-15",
             "due_date": "2026-06-15", "status": "Not Required"}, firm_id="F1")
    MOCK_COMPLIANCE_RECORDS.clear()


def test_the_screen_is_told_which_types_the_door_accepts(world):
    client, state, _audited = world
    state["user"] = _user("Executive")
    body = client.get("/api/compliance/reopenable-types").json()["data"]
    assert body["not_requirable_types"] == ["ADVANCE_TAX"]


# ── the advance-tax closer ───────────────────────────────────────────────────

def test_the_closer_neither_closes_nor_names_a_not_required_instalment(monkeypatch):
    from services import advance_tax_closes_obligation as at
    MOCK_COMPLIANCE_RECORDS.clear()
    for due in ("2026-06-15", "2026-09-15", "2026-12-15"):
        _obl(status="Not Required", due=due)
    march = _obl(due="2027-03-15")
    monkeypatch.setattr(at, "ist_today", lambda: date(2027, 3, 20))
    closed: list = []
    monkeypatch.setattr(at, "mark_filed_and_answer", lambda record, **k: closed.append(record["id"]) or {"closed": True,
                                                                                                         "message": "Closed."})
    out = at.close_for_saved_register(
        firm_id="F1", client_id="C1", financial_year="2026-27", actor=None, may_write_compliance=True,
        rows=[{"installment_number": 4, "estimated_tax_paise": 1_000_000, "paid_amount_paise": 1_000_000,
               "paid_date": "2027-03-10", "challan_number": "12345"}])
    assert closed == [march["id"]]
    assert not any("earlier advance-tax obligation" in (a.get("message") or "") for a in out)
    MOCK_COMPLIANCE_RECORDS.clear()

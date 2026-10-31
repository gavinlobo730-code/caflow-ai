"""A TDS challan recorded in error can be retracted, with a reason, and the record of it is kept (POST-A-362).

WHAT WAS WRONG
    The challan register had list, create and read-by-id and nothing else. A challan keyed under the wrong quarter, amount or date
    stayed in the register for good: it counted toward the deposit worksheet, Form 3CD clause 34 and the 24Q/26Q build, and the
    TDS deposit closer, which reads the register on every save, could close a reopened monthly obligation again from it. A
    deduction could be deleted; the record of money that left the bank could not.

WHAT THIS HOLDS
    * `POST /api/tds-workspace/challans/{id}/retract` removes the challan, at tds:write (Manager and above, the tier migration 345
      gives DELETE on this table), and no reader sees it afterwards;
    * the reason is required (empty, blank and over-long are refused in words) and the challan is left where it was;
    * the whole row and the reason are in `audit_log` BEFORE the row goes, under the AUTH id the log takes, and a failure to
      write that entry REFUSES the retraction (503) and leaves the row: the entry is the only copy once the row is gone;
    * a challan of another firm, or of a client the caller may not reach, is "not found" and is not touched;
    * a year the firm has locked refuses the retraction as it refuses the recording;
    * two requests for one challan retract it once and the second is told it is gone;
    * a month of the challan's quarter that still reads filed on the calendar is NAMED in the answer, with who can reopen it, and
      nothing is reopened by the retraction; a salary challan, a quarter with nothing filed and a calendar that cannot be read
      each produce no sentence and never fail the retraction.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import get_current_user
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_challan_retraction_service as service
from services import tds_deposit_closes_obligation as closer
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
CLIENT = "C1"


def _user(role="Manager", firm=FIRM):
    return {"id": "u1", "firm_id": firm, "role": role, "email": f"{role.lower()}@f1.test", "auth_user_id": f"auth-{role.lower()}"}


def _challan(db, *, firm=FIRM, client=CLIENT, quarter="Q2", fy="2025-26", section="194C", no="0001", paid_on="2025-08-05"):
    return db.seed("tds_challans", {
        "firm_id": firm, "client_id": client, "section": section, "challan_no": no, "bsr_code": "0510001", "financial_year": fy,
        "quarter": quarter, "tds_paise": 10_000_00, "surcharge_paise": 0, "interest_paise": 0, "penalty_paise": 0,
        "total_paise": 10_000_00, "payment_date": paid_on, "minor_head": "200", "status": "deposited"})


def _obligation(month, *, status="Filed", firm=FIRM, client=CLIENT):
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": closer.COMPLIANCE_TYPE, "obligation_type": closer.OBLIGATION_TYPE,
        "period_label": f"TDS deposit {month}", "period_start": f"2025-{month:02d}-01", "period_end": f"2025-{month:02d}-28",
        "due_date": f"2025-{month + 1:02d}-07", "status": status})


@pytest.fixture
def world(monkeypatch):
    """The REAL branch of the router (not the in-memory mock) over the fake database, with a signed-in user the test chooses."""
    import routers.tds_workspace as tw
    import core.supabase_client as sc
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    monkeypatch.setattr(tw.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    state = {"user": _user()}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    yield TestClient(app, raise_server_exceptions=False), db, state, tw, monkeypatch
    MOCK_COMPLIANCE_RECORDS.clear()


def _retract(client, challan, reason="Keyed under the wrong quarter"):
    return client.post(f"/api/tds-workspace/challans/{challan['id']}/retract", json={"reason": reason})


# ── the retraction ───────────────────────────────────────────────────────────

def test_a_manager_retracts_a_challan_and_the_register_no_longer_holds_it(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db)
    other = _challan(db, no="0002")

    r = _retract(client, row)

    assert r.status_code == 200 and r.json()["success"], r.text
    assert r.json()["data"]["retracted"] == row["id"] and r.json()["data"]["challan_no"] == "0001"
    assert [c["id"] for c in db.rows("tds_challans")] == [other["id"]]


def test_the_whole_row_and_the_reason_are_in_the_audit_log_under_the_auth_id(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db)

    _retract(client, row, reason="  Keyed under the wrong quarter  ")

    entry, = db.rows("audit_log")
    assert (entry["entity_type"], entry["action"], entry["entity_id"], entry["firm_id"]) == ("tds_challan", "retract", row["id"], FIRM)
    assert entry["actor_id"] == "auth-manager" and entry["actor_email"] == "manager@f1.test"
    assert entry["old_data"]["challan_no"] == "0001" and entry["old_data"]["total_paise"] == 10_000_00 and entry["old_data"]["quarter"] == "Q2"
    assert entry["new_data"] == {"retracted": True, "reason": "Keyed under the wrong quarter"}


def test_the_audit_entry_is_written_before_the_row_goes(world):
    client, db, _state, tw, mp = world
    row = _challan(db)
    order: list = []
    real_delete = service.delete_row
    real_audit = service.write_audit_or_refuse
    mp.setattr(service, "write_audit_or_refuse", lambda **k: (order.append("audit"), real_audit(**k))[1])
    mp.setattr(service, "delete_row", lambda *a, **k: (order.append("delete"), real_delete(*a, **k))[1])

    _retract(client, row)

    assert order == ["audit", "delete"]


# ── the reason ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["", "   ", "\n"])
def test_a_retraction_without_a_reason_is_refused_in_words_and_changes_nothing(world, reason):
    client, db, _state, _tw, _mp = world
    row = _challan(db)

    r = _retract(client, row, reason=reason)

    assert r.status_code == 422 and "Say why" in r.json()["detail"]
    assert len(db.rows("tds_challans")) == 1 and db.rows("audit_log") == []


def test_an_over_long_reason_is_refused(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db)
    r = _retract(client, row, reason="x" * (service.MAX_REASON_CHARS + 1))
    assert r.status_code == 422 and "too long" in r.json()["detail"] and len(db.rows("tds_challans")) == 1


# ── who, and whose ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,allowed", [("Partner", True), ("Manager", True), ("Executive", False), ("Reviewer", False)])
def test_the_door_is_tds_write_the_tier_the_database_gives_delete(world, role, allowed):
    client, db, state, _tw, _mp = world
    state["user"] = _user(role)
    row = _challan(db)

    r = _retract(client, row)

    assert (r.status_code == 200) is allowed, r.text
    assert (len(db.rows("tds_challans")) == 0) is allowed
    if not allowed:
        assert r.status_code == 403 and db.rows("audit_log") == []


def test_a_challan_of_another_firm_is_not_found_and_is_not_touched(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db, firm=OTHER_FIRM)

    r = _retract(client, row)

    assert r.status_code == 200 and r.json()["success"] is False and r.json()["error"] == "Not found"
    assert len(db.rows("tds_challans")) == 1 and db.rows("audit_log") == []


def test_a_challan_that_does_not_exist_is_not_found(world):
    client, _db, _state, _tw, _mp = world
    r = client.post("/api/tds-workspace/challans/nope/retract", json={"reason": "x"})
    assert r.json()["success"] is False and r.json()["error"] == "Not found"


# ── the lock, the audit refusal and the race ─────────────────────────────────

def test_a_year_the_firm_has_locked_refuses_the_retraction_as_it_refuses_the_recording(world):
    client, db, _state, tw, mp = world
    row = _challan(db)

    def locked(*_a, **_k):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked.")
    mp.setattr(tw.period_validation_service, "validate_posting_date", locked)

    r = _retract(client, row)

    assert r.status_code == 422 and "locked" in r.json()["detail"]
    assert len(db.rows("tds_challans")) == 1 and db.rows("audit_log") == []


def test_when_the_audit_entry_cannot_be_written_the_row_stays_and_the_answer_says_why(world):
    client, db, _state, _tw, mp = world
    row = _challan(db)

    class _Broken:
        def table(self, _name):
            raise RuntimeError("audit_log is unavailable")
    import core.supabase_client as sc
    mp.setattr(sc, "get_service_supabase", lambda: _Broken())

    r = _retract(client, row)

    assert r.status_code == 503 and "audit log" in r.json()["detail"] and "Nothing changed" in r.json()["detail"]
    assert len(db.rows("tds_challans")) == 1


def test_a_second_request_for_a_challan_already_retracted_is_told_it_is_not_there(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db)

    assert _retract(client, row).json()["success"] is True
    second = _retract(client, row)

    assert second.json()["success"] is False and second.json()["error"] == "Not found"
    assert len(db.rows("audit_log")) == 1, "the second request must not add a second 'retract' entry"


def test_when_the_delete_finds_nothing_left_the_service_says_it_is_gone(world):
    _client, db, _state, _tw, _mp = world
    with pytest.raises(service.RetractionRefused) as refused:
        service.retract(db, firm_id=FIRM, client_id=CLIENT, challan={"id": "gone", "client_id": CLIENT}, reason="x", actor=_user())
    assert refused.value.status == 404 and "no longer in the register" in refused.value.sentence


def test_the_delete_is_confined_to_the_challans_own_firm_and_client(world):
    _client, db, _state, _tw, _mp = world
    row = _challan(db)
    assert service.delete_row(db, firm_id=OTHER_FIRM, client_id=CLIENT, challan_id=row["id"]) is False
    assert service.delete_row(db, firm_id=FIRM, client_id="C2", challan_id=row["id"]) is False
    assert len(db.rows("tds_challans")) == 1
    assert service.delete_row(db, firm_id=FIRM, client_id=CLIENT, challan_id=row["id"]) is True


# ── what becomes of the calendar ─────────────────────────────────────────────

def test_a_month_of_the_quarter_that_still_reads_filed_is_named_with_who_can_reopen_it(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db, quarter="Q2")                       # Q2 2025-26 is July, August, September
    _obligation(7, status="Filed")
    _obligation(8, status="Completed")
    still_open = _obligation(9, status="Ready To File")

    note = _retract(client, row).json()["data"]["calendar_note"]

    assert note and "July 2025" in note and "August 2025" in note and "September" not in note
    assert "does not reopen it" in note and "Manager or Partner can reopen" in note
    assert compliance_records_repo.find_by_id(still_open["id"])["status"] == "Ready To File"        # nothing was touched


def test_the_retraction_reopens_nothing(world):
    client, db, _state, _tw, _mp = world
    row = _challan(db)
    filed = _obligation(7, status="Filed")

    _retract(client, row)

    assert compliance_records_repo.find_by_id(filed["id"])["status"] == "Filed"


def test_no_sentence_when_nothing_in_the_quarter_reads_filed_or_the_challan_is_salary_or_another_client(world):
    client, db, _state, _tw, _mp = world
    assert service.calendar_note(firm_id=FIRM, client_id=CLIENT, challan={"financial_year": "2025-26", "quarter": "Q2", "section": "194C"}) is None
    _obligation(7, status="Filed")
    assert service.calendar_note(firm_id=FIRM, client_id=CLIENT, challan={"financial_year": "2025-26", "quarter": "Q2", "section": "192"}) is None
    assert service.calendar_note(firm_id=FIRM, client_id="C2", challan={"financial_year": "2025-26", "quarter": "Q2", "section": "194C"}) is None
    assert service.calendar_note(firm_id=OTHER_FIRM, client_id=CLIENT, challan={"financial_year": "2025-26", "quarter": "Q2", "section": "194C"}) is None
    assert service.calendar_note(firm_id=FIRM, client_id=CLIENT, challan={"financial_year": "2025-26", "quarter": "Q3", "section": "194C"}) is None


def test_a_calendar_that_cannot_be_read_never_fails_the_retraction(world):
    client, db, _state, _tw, mp = world
    row = _challan(db)

    def broken(**_k):
        raise RuntimeError("calendar unavailable")
    mp.setattr(compliance_records_repo, "find_all", broken)

    r = _retract(client, row)

    assert r.status_code == 200 and r.json()["data"]["calendar_note"] is None and db.rows("tds_challans") == []


# ── a statement already recorded as filed ───────────────────────────────────

def _statement(db, *, return_type="26Q", status="filed", quarter="Q2", fy="2025-26", client=CLIENT, firm=FIRM):
    return db.seed("tds_returns", {"firm_id": firm, "client_id": client, "return_type": return_type, "financial_year": fy,
                                   "quarter": quarter, "status": status})


@pytest.mark.parametrize("status", ["filed", "revised"])
def test_a_statement_recorded_as_filed_for_the_quarter_is_named_and_not_touched(world, status):
    client, db, _state, _tw, _mp = world
    row = _challan(db, quarter="Q2")
    statement = _statement(db, status=status)

    answer = _retract(client, row).json()["data"]

    assert answer["statement_note"] and "recorded as filed" in answer["statement_note"] and "now disagree" in answer["statement_note"]
    assert "if this challan was reported in it" in answer["statement_note"]            # the register cannot say whether it was
    assert db.rows("tds_returns") == [statement]                                        # the statement is the CA's record: untouched


def test_no_statement_sentence_when_the_statement_is_not_filed_or_is_another_quarter_client_or_kind(world):
    client, db, _state, _tw, _mp = world
    challan = {"financial_year": "2025-26", "quarter": "Q2", "section": "194C"}
    _statement(db, status="prepared")
    _statement(db, status="ca_approved")
    _statement(db, quarter="Q3")
    _statement(db, client="C2")
    _statement(db, firm=OTHER_FIRM)
    _statement(db, return_type="24Q")                                                   # the salary statement does not report a 194C deposit
    assert service.statement_note(db, firm_id=FIRM, client_id=CLIENT, challan=challan) is None
    _statement(db, return_type="27Q")                                                   # a non-resident statement does
    assert service.statement_note(db, firm_id=FIRM, client_id=CLIENT, challan=challan)


def test_a_salary_challan_is_judged_against_the_salary_statement_only(world):
    client, db, _state, _tw, _mp = world
    salary = {"financial_year": "2025-26", "quarter": "Q2", "section": "192"}
    _statement(db, return_type="26Q")
    assert service.statement_note(db, firm_id=FIRM, client_id=CLIENT, challan=salary) is None
    _statement(db, return_type="24Q")
    assert service.statement_note(db, firm_id=FIRM, client_id=CLIENT, challan=salary)


def test_a_statement_that_cannot_be_read_never_fails_the_retraction(world):
    client, db, _state, _tw, mp = world
    row = _challan(db)
    real_table = db.table

    def table(name):
        if name == "tds_returns":
            raise RuntimeError("statements unavailable")
        return real_table(name)
    mp.setattr(db, "table", table)

    r = _retract(client, row)

    assert r.status_code == 200 and r.json()["data"]["statement_note"] is None and db.rows("tds_challans") == []


# ── the in-memory mock mode ──────────────────────────────────────────────────

def test_in_mock_mode_the_challan_goes_from_the_in_memory_store(monkeypatch):
    import routers.tds_workspace as tw
    monkeypatch.setattr(tw, "_USE_MOCK", True)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    tw._MOCK_CHALLANS.clear()
    tw._MOCK_CHALLANS["m1"] = {"id": "m1", "client_id": CLIENT, "firm_id": FIRM, "challan_no": "9", "payment_date": "2025-08-05",
                               "total_paise": 100, "financial_year": "2025-26", "quarter": "Q2", "section": "194C"}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: _user()
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/api/tds-workspace/challans/m1/retract", json={"reason": "Wrong quarter"})

    assert r.status_code == 200 and r.json()["data"]["retracted"] == "m1" and "m1" not in tw._MOCK_CHALLANS
    tw._MOCK_CHALLANS.clear()

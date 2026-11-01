"""A retracted TDS challan reopens exactly the monthly deposit obligations it closed, and a month a person reopened is not closed again on
the same challans (POST-A-362, the part the first slice left).

WHAT WAS WRONG
    The closer matched challans to months by order and kept no record of which challans a month was closed on. So a retraction could only
    NAME every month of the quarter that still read filed and say who could reopen them, and a month a person reopened because the
    pairing was wrong was closed again by the next challan saved for its quarter, on the very challans the person had rejected.

WHAT IS HELD
    * closing a month records the ids of the challans that covered it (`compliance_records.closing_tds_challan_ids`, migration 569),
      written by the closer after the close and confined to the firm and to a row that is now Filed or Completed; a failure to write it
      never fails the close;
    * a month a person reopened is left alone while every challan that covers it is among those it was closed on, said in a sentence
      when the challan just recorded is one of them, and closed again the moment a different challan covers it;
    * a retraction REOPENS the filed months whose record names the retracted challan, wherever in the register's order it was paired
      (including a month of another quarter), when the caller may approve Compliance, with the reason on the row and in the answer;
      for a caller who may not, the months are NAMED with who can reopen them and nothing is reopened;
    * a filed month that names other challans only is not mentioned; a filed month of the quarter with no record of what closed it is
      named as before and left; a month that cannot be reopened is named with the sentence and never fails the retraction;
    * after a retraction, recording the corrected challan closes the month again.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.exceptions import ValidationError
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_challan_retraction_service as retraction
from services import tds_deposit_closes_obligation as closes
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "11111111-1111-4111-8111-111111111111", "44444444-4444-4444-8444-444444444444"
CLIENT = "22222222-2222-4222-8222-222222222222"
FY = "2025-26"
MANAGER = {"id": "u1", "firm_id": FIRM, "role": "Manager", "email": "manager@f1.test", "auth_user_id": "auth-manager"}


@pytest.fixture
def world(monkeypatch):
    """The REAL branch of the router over the fake database, the audit log and the timeline stubbed where they are not the point."""
    import routers.tds_workspace as tw
    import core.supabase_client as sc
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(tw.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    state = {"user": dict(MANAGER)}
    app = FastAPI()
    app.include_router(tw.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    yield TestClient(app, raise_server_exceptions=False), db, state, tw, monkeypatch
    MOCK_COMPLIANCE_RECORDS.clear()


def obligation(year, mon, *, status="Not Started", client=CLIENT, firm=FIRM):
    last = (date(year + (mon == 12), mon % 12 + 1, 1) - date(year, mon, 1)).days
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": closes.COMPLIANCE_TYPE, "obligation_type": closes.OBLIGATION_TYPE,
        "period_label": f"TDS deposit {year}-{mon:02d}", "period_start": date(year, mon, 1).isoformat(),
        "period_end": date(year, mon, last).isoformat(), "due_date": date(year + (mon == 12), mon % 12 + 1, 7).isoformat(),
        "status": status})


def now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def deduction(db, on, tds=10_000_00, section="194C"):
    return db.seed("tds_deductions", {"firm_id": FIRM, "client_id": CLIENT, "section": section, "transaction_date": on,
                                      "payment_amount_paise": tds * 50, "tds_paise": tds, "surcharge_paise": 0, "cess_paise": 0,
                                      "deductee_name": "Vendor"})


def challan(db, tds, *, quarter="Q2", section="194C", paid_on="2025-08-05", no="0001"):
    return db.seed("tds_challans", {"firm_id": FIRM, "client_id": CLIENT, "section": section, "challan_no": no, "bsr_code": "0510001",
                                    "financial_year": FY, "quarter": quarter, "tds_paise": tds, "surcharge_paise": 0,
                                    "interest_paise": 0, "penalty_paise": 0, "total_paise": tds, "payment_date": paid_on,
                                    "minor_head": "200", "status": "deposited"})


def close(db, row, *, quarter="Q2"):
    return closes.close_for_recorded_challan(
        db=db, firm_id=FIRM, client_id=CLIENT, financial_year=FY, quarter=quarter, challan_id=row["id"], section=row["section"],
        actor=MANAGER, may_write_compliance=True)


def reopen(rec, why="The pairing was wrong"):
    from domain.compliance_record_service import compliance_record_service
    return compliance_record_service.reopen_record(rec["id"], why, firm_id=FIRM, actor=MANAGER)


def retract(client, row, reason="Keyed under the wrong quarter"):
    return client.post(f"/api/tds-workspace/challans/{row['id']}/retract", json={"reason": reason})


def a_july_closed_on(world, **kw):
    """A deduction in July, a challan that pays it on 5 August, and July's obligation closed on it."""
    _client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    c = challan(db, 10_000_00, **kw)
    out = close(db, c)
    assert out and out[0]["closed"] is True, out
    return db, ob, c


# ── what the closer records ──────────────────────────────────────────────────────────────────────────────────────────

def test_closing_a_month_records_the_challans_that_covered_it(world):
    db, ob, c = a_july_closed_on(world)
    rec = now(ob)
    assert rec["status"] == "Filed" and rec["closing_tds_challan_ids"] == [c["id"]]
    assert closes.closed_on(rec) == frozenset({c["id"]})


def test_a_month_covered_by_two_sections_records_both_challans(world):
    _client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10", 10_000_00, "194C")
    deduction(db, "2025-07-12", 4_000_00, "194J")
    ob = obligation(2025, 7)
    first = challan(db, 10_000_00, section="194C", no="Z1", paid_on="2025-08-04")
    close(db, first)
    second = challan(db, 4_000_00, section="194J", no="A2", paid_on="2025-08-06")
    assert close(db, second)[0]["closed"] is True
    assert closes.closed_on(now(ob)) == frozenset({first["id"], second["id"]})


def test_an_obligation_with_no_record_is_not_held_back_by_one(world):
    assert closes.closed_on({}) is None
    assert closes.closed_on({"closing_tds_challan_ids": None}) is None
    assert closes.closed_on({"closing_tds_challan_ids": "not a list"}) is None
    assert closes.closed_on({"closing_tds_challan_ids": []}) == frozenset()


def test_the_record_is_written_for_a_filed_row_of_the_same_firm_only(world):
    ob = obligation(2025, 7, status="Filed")
    open_ob = obligation(2025, 8, status="Ready To File")
    assert compliance_records_repo.stamp_closing_tds_challans(ob["id"], OTHER_FIRM, ["c1"]) is False
    assert compliance_records_repo.stamp_closing_tds_challans(open_ob["id"], FIRM, ["c1"]) is False
    assert now(ob).get("closing_tds_challan_ids") is None and now(open_ob).get("closing_tds_challan_ids") is None
    assert compliance_records_repo.stamp_closing_tds_challans(ob["id"], FIRM, ["c2", "c1", "c1", ""]) is True
    assert now(ob)["closing_tds_challan_ids"] == ["c1", "c2"]
    with pytest.raises(ValueError):
        compliance_records_repo.stamp_closing_tds_challans(ob["id"], "", ["c1"])


def test_a_failure_to_write_the_record_never_fails_the_close(world, monkeypatch):
    _client, db, _s, _tw, _mp = world
    seen = []
    monkeypatch.setattr(closes, "capture_soft_failure", lambda exc, **k: seen.append((str(exc), k.get("operation"))))
    monkeypatch.setattr(compliance_records_repo, "stamp_closing_tds_challans",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7)
    out = close(db, challan(db, 10_000_00))
    assert out[0]["closed"] is True and now(ob)["status"] == "Filed"
    assert seen == [("database unavailable", "tds_deposit_closes_obligation.record_challans")]


# ── a month a person reopened ────────────────────────────────────────────────────────────────────────────────────────

def test_a_reopened_month_keeps_the_record_and_is_not_closed_again_on_the_same_challan(world):
    db, ob, c = a_july_closed_on(world)
    reopen(now(ob))
    assert now(ob)["status"] == "Ready To File" and now(ob)["closing_tds_challan_ids"] == [c["id"]]
    out = close(db, c)                                  # the same challan, saved again
    assert out[0]["state"] == "not_closed" and out[0]["month"] == "2025-07"
    assert "closed on these same challans and a person reopened it" in out[0]["message"]
    assert "marked filed from Compliance" in out[0]["message"]
    assert now(ob)["status"] == "Ready To File"


def test_a_challan_saved_for_another_month_leaves_the_reopened_month_alone_and_silent(world):
    db, ob, c = a_july_closed_on(world)
    reopen(now(ob))
    deduction(db, "2025-08-11", 7_000_00)
    august = obligation(2025, 8)
    b = challan(db, 7_000_00, paid_on="2025-09-05", no="0002")
    out = close(db, b)
    assert {a["month"]: a["state"] for a in out} == {"2025-08": "closed"}, out        # nothing is said about July
    assert now(ob)["status"] == "Ready To File" and now(august)["status"] == "Filed"


def test_a_reopened_month_is_closed_again_when_a_different_challan_covers_it(world):
    db, ob, c = a_july_closed_on(world)
    reopen(now(ob))
    db.table("tds_challans").delete().eq("id", c["id"]).execute()                                   # the wrong one is gone
    corrected = challan(db, 10_000_00, paid_on="2025-08-06", no="0009")
    out = close(db, corrected)
    assert out[0]["closed"] is True and out[0]["reference"] == "0009"
    rec = now(ob)
    assert rec["status"] == "Filed" and rec["closing_tds_challan_ids"] == [corrected["id"]]


def test_a_reopened_month_that_a_further_challan_now_also_covers_is_closed_again(world):
    _client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10", 6_000_00)
    ob = obligation(2025, 7)
    a = challan(db, 6_000_00, paid_on="2025-08-05", no="0001")
    close(db, a)
    reopen(now(ob))
    deduction(db, "2025-07-20", 4_000_00)                                      # more tax found for the month, and a challan for it
    b = challan(db, 4_000_00, paid_on="2025-08-06", no="0002")
    out = close(db, b)
    assert out[0]["closed"] is True
    assert closes.closed_on(now(ob)) == frozenset({a["id"], b["id"]})


def test_a_month_closed_by_a_person_with_no_record_is_closed_by_the_register_as_before(world):
    _client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10")
    ob = obligation(2025, 7, status="Ready To File")                    # no record of what closed it
    out = close(db, challan(db, 10_000_00))
    assert out[0]["closed"] is True and now(ob)["status"] == "Filed"


# ── the retraction ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_retracting_the_challan_that_closed_a_month_reopens_that_month(world):
    client, db, _s, _tw, _mp = world
    _db, ob, c = a_july_closed_on(world)
    r = retract(client, c, reason="Keyed under the wrong quarter")
    data = r.json()["data"]
    assert r.status_code == 200 and data["reopened_obligation_ids"] == [ob["id"]]
    assert "July 2025" in data["calendar_note"] and "has been reopened" in data["calendar_note"]
    rec = now(ob)
    assert rec["status"] == "Ready To File" and rec["filed_date"] is None and rec["acknowledgement_no"] is None
    assert "The TDS challan 0001 that this month was closed on was retracted: Keyed under the wrong quarter" in rec["notes"]
    assert "Reopened on" in rec["notes"] and "manager@f1.test" in rec["notes"]
    assert db.rows("tds_challans") == []


def test_a_month_closed_on_two_challans_is_reopened_by_either_and_the_other_challan_stays(world):
    client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10", 10_000_00, "194C")
    deduction(db, "2025-07-12", 4_000_00, "194J")
    ob = obligation(2025, 7)
    first = challan(db, 10_000_00, section="194C", no="Z1", paid_on="2025-08-04")
    close(db, first)
    second = challan(db, 4_000_00, section="194J", no="A2", paid_on="2025-08-06")
    close(db, second)
    assert now(ob)["status"] == "Filed"
    data = retract(client, second).json()["data"]
    assert data["reopened_obligation_ids"] == [ob["id"]] and now(ob)["status"] == "Ready To File"
    assert [c["id"] for c in db.rows("tds_challans")] == [first["id"]]


def test_a_challan_that_closed_two_months_reopens_both(world):
    client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10", 6_000_00)
    deduction(db, "2025-08-10", 4_000_00)
    july, august = obligation(2025, 7), obligation(2025, 8)
    c = challan(db, 10_000_00, paid_on="2025-08-05")                       # pays July, and the register carries it into August
    for ob in (july, august):
        compliance_records_repo.update(ob["id"], {"status": "Filed"})
        compliance_records_repo.stamp_closing_tds_challans(ob["id"], FIRM, [c["id"]])
    data = retract(client, c).json()["data"]
    assert sorted(data["reopened_obligation_ids"]) == sorted([july["id"], august["id"]])
    assert "July 2025 and August 2025" in data["calendar_note"]
    assert now(july)["status"] == now(august)["status"] == "Ready To File"


def test_a_month_of_another_quarter_that_names_the_challan_is_reopened(world):
    client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00, quarter="Q2")
    elsewhere = obligation(2025, 11, status="Filed")                          # a Q3 month the register paired it to
    compliance_records_repo.stamp_closing_tds_challans(elsewhere["id"], FIRM, [c["id"]])
    data = retract(client, c).json()["data"]
    assert data["reopened_obligation_ids"] == [elsewhere["id"]] and now(elsewhere)["status"] == "Ready To File"


def test_a_filed_month_that_names_other_challans_is_not_mentioned_or_touched(world):
    client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00)
    other = challan(db, 5_000_00, no="0002")
    closed_on_other = obligation(2025, 7, status="Filed")
    compliance_records_repo.stamp_closing_tds_challans(closed_on_other["id"], FIRM, [other["id"]])
    data = retract(client, c).json()["data"]
    assert data["calendar_note"] is None and data["reopened_obligation_ids"] == []
    assert now(closed_on_other)["status"] == "Filed"


def test_a_filed_month_with_no_record_is_named_and_left(world):
    client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00)
    unrecorded = obligation(2025, 8, status="Filed")                           # closed before the record existed
    data = retract(client, c).json()["data"]
    assert data["reopened_obligation_ids"] == [] and now(unrecorded)["status"] == "Filed"
    note = data["calendar_note"]
    assert "August 2025" in note and "does not reopen it" in note and "nothing recorded which challan closed that month" in note
    assert "Manager or Partner can reopen" in note


def test_a_caller_who_may_not_approve_compliance_has_the_months_named_and_nothing_reopened(world):
    client, db, _s, tw, mp = world
    _db, ob, c = a_july_closed_on(world)
    mp.setattr(tw, "can_user", lambda user, resource, action: not (resource == "compliance" and action == "approve"))
    data = retract(client, c).json()["data"]
    assert data["reopened_obligation_ids"] == [] and now(ob)["status"] == "Filed"
    assert "July 2025" in data["calendar_note"] and "closed on this challan and still reads filed" in data["calendar_note"]
    assert "does not include approving Compliance" in data["calendar_note"] and "Manager or Partner can reopen" in data["calendar_note"]
    assert db.rows("tds_challans") == []                                        # the challan itself is retracted either way


def test_a_month_that_cannot_be_reopened_is_named_and_does_not_fail_the_retraction(world):
    client, db, _s, _tw, mp = world
    deduction(db, "2025-07-10", 6_000_00)
    deduction(db, "2025-08-10", 4_000_00)
    july, august = obligation(2025, 7), obligation(2025, 8)
    c = challan(db, 10_000_00)
    for ob in (july, august):
        compliance_records_repo.update(ob["id"], {"status": "Filed"})
        compliance_records_repo.stamp_closing_tds_challans(ob["id"], FIRM, [c["id"]])
    from domain.compliance_record_service import compliance_record_service
    real = compliance_record_service.reopen_record

    def refuse_july(record_id, *a, **k):
        if record_id == july["id"]:
            raise ValidationError("status", "This obligation is no longer recorded as filed: somebody changed it just now.")
        return real(record_id, *a, **k)
    mp.setattr(compliance_record_service, "reopen_record", refuse_july)
    r = retract(client, c)
    data = r.json()["data"]
    assert r.status_code == 200 and data["reopened_obligation_ids"] == [august["id"]]
    assert "August 2025" in data["calendar_note"] and "has been reopened" in data["calendar_note"]
    assert "July 2025 (This obligation is no longer recorded as filed" in data["calendar_note"] and "could not be reopened" in data["calendar_note"]
    assert db.rows("tds_challans") == []


def test_an_unexpected_failure_reopening_is_reported_and_never_fails_the_retraction(world):
    client, db, _s, _tw, mp = world
    _db, ob, c = a_july_closed_on(world)
    from domain.compliance_record_service import compliance_record_service
    seen = []
    mp.setattr(compliance_record_service, "reopen_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    import core.observability as obs
    mp.setattr(obs, "capture_soft_failure", lambda exc, **k: seen.append(k.get("operation")))
    r = retract(client, c)
    assert r.status_code == 200 and "could not be reopened just now" in r.json()["data"]["calendar_note"]
    assert seen == ["tds.challan_retraction.reopen"] and now(ob)["status"] == "Filed"


def test_a_salary_challan_reopens_and_names_nothing(world):
    client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00, section="192")
    ob = obligation(2025, 7, status="Filed")
    compliance_records_repo.stamp_closing_tds_challans(ob["id"], FIRM, [c["id"]])
    data = retract(client, c).json()["data"]
    assert data["calendar_note"] is None and data["reopened_obligation_ids"] == [] and now(ob)["status"] == "Filed"


def test_a_month_of_another_client_that_names_the_id_is_not_touched(world):
    client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00)
    theirs = obligation(2025, 7, status="Filed", client="33333333-3333-4333-8333-333333333333")
    compliance_records_repo.stamp_closing_tds_challans(theirs["id"], FIRM, [c["id"]])
    data = retract(client, c).json()["data"]
    assert data["reopened_obligation_ids"] == [] and now(theirs)["status"] == "Filed"


def test_the_calendar_effect_reads_nothing_when_the_calendar_cannot_be_read(world, monkeypatch):
    _client, db, _s, _tw, _mp = world
    c = challan(db, 10_000_00)
    monkeypatch.setattr(compliance_records_repo, "find_all", lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    effect = retraction.calendar_effect(firm_id=FIRM, client_id=CLIENT, challan=c, reason="x", actor=MANAGER)
    assert effect["note"] is None and effect["reopened"] == []


def test_the_reason_given_to_the_reopening_is_cut_to_the_limit(world):
    client, db, _s, _tw, _mp = world
    _db, ob, c = a_july_closed_on(world)
    data = retract(client, c, reason="x" * 500).json()["data"]
    assert data["reopened_obligation_ids"] == [ob["id"]]
    note_line = now(ob)["notes"].splitlines()[-1]
    assert note_line.startswith("Reopened on ") and len(note_line.split(": ", 1)[1]) <= 500


# ── the whole round trip ─────────────────────────────────────────────────────────────────────────────────────────────

def test_retract_the_wrong_challan_record_the_right_one_and_the_month_closes_again(world):
    client, db, _s, _tw, _mp = world
    _db, ob, wrong = a_july_closed_on(world, no="0001")
    assert now(ob)["status"] == "Filed"
    assert retract(client, wrong).json()["data"]["reopened_obligation_ids"] == [ob["id"]]
    assert now(ob)["status"] == "Ready To File"
    right = challan(db, 10_000_00, paid_on="2025-08-06", no="0007")
    out = close(db, right)
    assert out[0]["closed"] is True and out[0]["reference"] == "0007"
    rec = now(ob)
    assert rec["status"] == "Filed" and str(rec["filed_date"])[:10] == "2025-08-06" and rec["closing_tds_challan_ids"] == [right["id"]]


# ── what an independent review found (1-11-2026): the record must not outlive the closure it describes ─────────────────────────────

def test_a_person_who_marks_the_month_filed_from_compliance_clears_the_record(world):
    """The closer's own 'left open' sentence tells a person to mark the month filed from Compliance. That month was then closed on a payment
    of the person's own, so a later retraction of a challan the closer had named must not reopen it."""
    client, db, _s, _tw, _mp = world
    _db, ob, a = a_july_closed_on(world)
    reopen(now(ob))
    assert now(ob)["closing_tds_challan_ids"] == [a["id"]], "a person's reopen keeps the record"
    from domain.compliance_record_service import compliance_record_service
    compliance_record_service.mark_filed(ob["id"], firm_id=FIRM, actor=MANAGER, acknowledgement_no="REAL-CHALLAN", filed_date="2025-08-06")
    rec = now(ob)
    assert rec["status"] == "Filed" and rec["acknowledgement_no"] == "REAL-CHALLAN"
    assert rec.get("closing_tds_challan_ids") is None, "the old ids outlived the closure they described"
    data = retract(client, a).json()["data"]
    assert data["reopened_obligation_ids"] == [] and now(ob)["status"] == "Filed", "a month closed by a person was reopened by a retraction"
    assert "July 2025" in data["calendar_note"] and "does not reopen it" in data["calendar_note"], "it is named, with who can reopen it"


def test_moving_from_filed_to_completed_keeps_the_record(world):
    _client, _db, _s, _tw, _mp = world
    _db, ob, a = a_july_closed_on(world)
    from domain.compliance_record_service import compliance_record_service
    compliance_record_service.update_record(ob["id"], {"status": "Completed"}, firm_id=FIRM, actor=MANAGER)
    rec = now(ob)
    assert rec["status"] == "Completed" and rec["closing_tds_challan_ids"] == [a["id"]]


def test_a_person_s_reopen_keeps_the_record_and_a_retractions_reopen_forgets_it(world):
    client, db, _s, _tw, _mp = world
    _db, ob, a = a_july_closed_on(world)
    reopen(now(ob))
    assert now(ob)["closing_tds_challan_ids"] == [a["id"]]
    deduction(db, "2025-08-11", 7_000_00)
    other = obligation(2025, 8)
    b = challan(db, 7_000_00, paid_on="2025-09-05", no="0002")
    close(db, b)
    assert now(other)["status"] == "Filed"
    assert retract(client, b).json()["data"]["reopened_obligation_ids"] == [other["id"]]
    assert now(other).get("closing_tds_challan_ids") is None, "the retraction's reopen left the old record on the month"


def test_a_month_the_retraction_reopened_is_closed_again_on_the_challans_that_remain(world):
    """Two challans closed July (6,000 then 10,000 against 10,000 of tax). Retracting the first reopens July. The second alone covers it in full
    and on time, so the next challan saved for the quarter must close it again, and no sentence may call it a person's reopen."""
    client, db, _s, _tw, _mp = world
    deduction(db, "2025-07-10", 10_000_00)
    ob = obligation(2025, 7)
    a = challan(db, 6_000_00, paid_on="2025-08-04", no="0001")
    b = challan(db, 10_000_00, paid_on="2025-08-06", no="0002")
    out = close(db, b)
    assert out[0]["closed"] is True and closes.closed_on(now(ob)) == frozenset({a["id"], b["id"]})
    data = retract(client, a).json()["data"]
    assert data["reopened_obligation_ids"] == [ob["id"]] and now(ob)["status"] == "Ready To File"
    assert now(ob).get("closing_tds_challan_ids") is None
    assert "the next time a challan is recorded for the quarter" in data["calendar_note"], "the note over-promised the timing"
    deduction(db, "2025-09-10", 3_000_00)
    c = challan(db, 3_000_00, paid_on="2025-10-05", no="0003")
    out = close(db, c)
    assert now(ob)["status"] == "Filed", [a_ for a_ in out]
    assert closes.closed_on(now(ob)) == frozenset({b["id"]})


def test_a_failed_write_of_the_new_ids_leaves_no_record_and_never_the_old_ones(world, monkeypatch):
    client, db, _s, _tw, _mp = world
    _db, ob, a = a_july_closed_on(world)
    reopen(now(ob))
    db.table("tds_challans").delete().eq("id", a["id"]).execute()
    corrected = challan(db, 10_000_00, paid_on="2025-08-06", no="0009")
    monkeypatch.setattr(closes, "capture_soft_failure", lambda *a_, **k: None)
    monkeypatch.setattr(compliance_records_repo, "stamp_closing_tds_challans",
                        lambda *a_, **k: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    out = close(db, corrected)
    assert out[0]["closed"] is True and now(ob)["status"] == "Filed"
    assert now(ob).get("closing_tds_challan_ids") is None, "the old ids stood in for the new ones"


def test_the_reopen_door_does_not_forget_the_record_by_default(world):
    _client, _db, _s, _tw, _mp = world
    import inspect
    from domain.compliance_record_service import compliance_record_service
    assert inspect.signature(compliance_record_service.reopen_record).parameters["forget_what_closed_it"].default is False


def test_update_clearing_may_clear_the_record_and_nothing_else_outside_its_lists(world):
    ob = obligation(2025, 7, status="Filed")
    compliance_records_repo.stamp_closing_tds_challans(ob["id"], FIRM, ["x"])
    with pytest.raises(ValueError):
        compliance_records_repo.update_clearing(ob["id"], FIRM, {}, clear=("status",))
    compliance_records_repo.update_clearing(ob["id"], FIRM, {}, clear=compliance_records_repo.CLEARABLE_RECORD)
    assert now(ob).get("closing_tds_challan_ids") is None

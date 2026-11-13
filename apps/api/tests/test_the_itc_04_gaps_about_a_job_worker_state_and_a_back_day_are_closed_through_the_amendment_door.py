"""Two gaps FORM GST ITC-04 names about a job-work challan can be closed from a screen, and what the screens call is the door that already existed (POST-A-431, POST-A-423).

WHAT WAS WRONG
    POST-A-431. A job-work challan of tools, moulds, dies, jigs or fixtures recorded as received back with no day was named by the statement (POST-A-422), and the Delivery Challans tab's box for the day
    a whole challan came back listed a challan only while a section 143 period ran on it, which tools do not have, so no screen could give it a day. The statement said so ("the day cannot be recorded
    from a screen yet"); it now says the same thing for every challan it names, and the tab offers the box to all of them.

    POST-A-423. A job-work challan to a job worker with no GSTIN, within the client's own State, carried neither the GSTIN nor the State the form asks for: the new-challan form shows the place of supply only
    for an inter-State movement, the issue door asks for neither, and no screen changed such a challan's place of supply afterwards (the draft's correction form does, for an inter-State draft). The challan is on the statement's Table 4 with a gap sentence and nothing
    on screen closed it. The challan panel has a box for the State now; it is the SAME column the inter-State box writes (the State the goods go to, which for a job worker is the job worker's State).

WHAT THIS HOLDS (the server's half; the screens are held by `apps/web/scripts/the-itc-04-gaps-...test.ts` and the Chromium group `job-work-gaps`)
    * the amendment door gives a day to a wholly-back challan of tools with no day, keeps its status, and the statement then stops naming it; the same day is refused before a lot already recorded, as it
      is for any challan;
    * the same door records a State on an issued, a received-back and a draft job-work challan that holds no GSTIN, and Table 4 then reads it as the job worker's State and stops naming the gap; it also
      CHANGES a State already recorded (the screen's box stays, holding it);
    * the screen's two display conditions (`apps/web/lib/sales/challanOffers.ts`) are pinned to the statement's own tests by `shared/challan-offer-vectors.json`, which the web suite reads too: whatever the
      statement names, a screen offers the box for;
    * a challan WITH a GSTIN keeps reading its State from the GSTIN (a recorded place of supply is never preferred over it for the job worker);
    * the gap sentence says where the remedy is.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

import services.itc_04_service as svc
import services.sales_cycle_service as cycle
from domain.gst import itc_04 as itc
from tests.e2e_harness import FakeDB

FIRM = "FIRM-J"
CLIENT = "CLI-MFG"
TODAY = date(2026, 10, 1)
TOOLS = "moulds_dies_jigs_fixtures_tools"


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)
    monkeypatch.setattr(cycle, "ist_today", lambda: TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Mfg Co"})
    return x


def _challan(db, no, *, status="issued", goods_kind="inputs", gstin=None, place=None, back_on=None, sent_on="2026-05-10", **extra):
    return db.seed("delivery_challans", {
        "firm_id": FIRM, "client_id": CLIENT, "document_no": no, "document_date": sent_on, "reason": "job_work", "status": status,
        "goods_kind": goods_kind, "received_back_on": back_on, "extended_to": None, "consignee_name": "Precision Castings",
        "consignee_gstin": gstin, "consignee_address": "Plot 4", "place_of_supply": place, "is_inter_state": False, **extra})


def _line(db, challan, qty="10"):
    return db.seed("delivery_challan_lines", {
        "firm_id": FIRM, "client_id": CLIENT, "challan_id": challan["id"], "line_order": 0, "description": "Castings",
        "hsn_sac": "7214", "quantity": qty, "unit": "NOS", "taxable_amount_paise": 5_00_000, "gst_rate_percent": "18"})


def _statement(db):
    return svc.statement(db, FIRM, CLIENT, "2026-27", as_at=TODAY, window="2026-27:H1")


def _row(out, no):
    return next(r for r in out["table_4"]["rows"] if r["challan_no"] == no)


def _gaps_for(out, no, kind):
    return [g for g in out["table_4"]["gaps"] if g["challan_no"] == no and g["kind"] == kind]


def _amend(db, challan, patch):
    return cycle.update_challan(db, FIRM, challan["id"], patch)


def _stored(db, challan):
    return next(r for r in db.rows("delivery_challans") if r["id"] == challan["id"])


# ── POST-A-431: a back day for a challan of goods with no period ───────────────────────────

def test_a_tools_challan_recorded_back_with_no_day_is_given_its_day_by_the_amendment_door_and_stops_being_named(db):
    ch = _challan(db, "JW/020", status="received_back", goods_kind=TOOLS)
    _line(db, ch)
    named = lambda out: [g for g in out["gaps"] if "received back with no day" in g]
    assert len(named(_statement(db))) == 1

    out = _amend(db, ch, {"received_back_on": "2026-07-01"})

    assert out["status"] == "received_back" and out["received_back_on"] == "2026-07-01"
    assert _stored(db, ch)["status"] == "received_back" and _stored(db, ch)["received_back_on"] == "2026-07-01"
    assert named(_statement(db)) == [], "the statement still names a challan that has its day"


def test_the_gap_sentence_promises_the_same_remedy_for_goods_with_a_period_and_goods_without(db):
    _line(db, _challan(db, "JW/021", status="received_back", goods_kind=TOOLS))
    _line(db, _challan(db, "JW/022", status="received_back", goods_kind="inputs"))
    [gap] = [g for g in _statement(db)["gaps"] if "received back with no day" in g]
    assert "JW/021" in gap and "JW/022" in gap
    assert gap.endswith("Record the day the goods came back on the Delivery Challans tab.")
    assert "cannot be recorded from a screen" not in gap


def test_the_day_is_still_judged_for_a_challan_of_tools(db):
    ch = _challan(db, "JW/023", status="received_back", goods_kind=TOOLS, sent_on="2026-06-01")
    _line(db, ch)
    with pytest.raises(HTTPException) as caught:
        _amend(db, ch, {"received_back_on": "2026-05-01"})          # before the goods went out
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException) as caught:
        _amend(db, ch, {"received_back_on": "2026-12-31"})          # a day that has not come (today is fixed at 2026-10-01)
    assert caught.value.status_code == 422
    assert _stored(db, ch)["received_back_on"] is None


# ── POST-A-423: the job worker's State ───────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["issued", "received_back"])
def test_a_job_worker_with_no_gstin_is_named_until_a_state_is_recorded_and_then_read_as_that_state(db, status):
    ch = _challan(db, "JW/030", status=status, back_on=("2026-07-01" if status == "received_back" else None))
    _line(db, ch)
    gap = _gaps_for(_statement(db), "JW/030", "job_worker_not_identified")
    assert len(gap) == 1
    assert gap[0]["reason"].endswith("Record the State on the challan's panel on the Delivery Challans tab.")

    _amend(db, ch, {"place_of_supply": "29"})

    out = _statement(db)
    assert _gaps_for(out, "JW/030", "job_worker_not_identified") == []
    assert _row(out, "JW/030")["job_worker"]["state_code"] == "29"


def test_a_draft_can_be_given_the_state_by_the_same_door(db):
    ch = _challan(db, "JW/031", status="draft")
    _line(db, ch)
    _amend(db, ch, {"place_of_supply": "27"})
    assert _stored(db, ch)["place_of_supply"] == "27"


def test_a_challan_with_a_gstin_reads_its_state_from_the_gstin_and_not_from_the_place_of_supply(db):
    ch = _challan(db, "JW/032", gstin="29BBBBB1111B1ZR", place="27")
    _line(db, ch)
    out = _statement(db)
    worker = _row(out, "JW/032")["job_worker"]
    assert worker["gstin"] == "29BBBBB1111B1ZR" and worker["state_code"] is None, "a GSTIN carries its own State; the place of supply is not read beside it"
    assert _gaps_for(out, "JW/032", "job_worker_not_identified") == []


def test_a_state_that_is_not_a_state_code_is_refused_by_the_model_and_nothing_is_recorded(db):
    from models.sales_cycle import DeliveryChallanUpdateIn

    with pytest.raises(ValueError):
        DeliveryChallanUpdateIn(place_of_supply="99X")
    ch = _challan(db, "JW/033")
    _line(db, ch)
    assert _stored(db, ch)["place_of_supply"] is None


VECTORS = json.loads((Path(__file__).resolve().parents[3] / "shared" / "challan-offer-vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["job_worker_state"], ids=lambda c: f"{c['reason']}-{c['status']}-{c['consignee_gstin']!r}-{c['place_of_supply']!r}")
def test_the_state_box_and_the_statements_own_test_of_a_job_worker_agree(case):
    identified = itc._job_worker({"consignee_gstin": case["consignee_gstin"], "place_of_supply": case["place_of_supply"]})["identified"]
    assert identified is case["identified"], f"the statement reads this job worker as identified={identified}"
    sent = itc.is_job_work_sent({"reason": case["reason"], "status": case["status"], "document_date": "2026-05-10"})
    if sent and not identified:
        # every challan the statement names for a missing job worker is one the screen offers the box for (a gap is never left with no way to close it)
        assert case["box"] is True, "the statement names a job worker the screen offers no box for"
    if case["consignee_gstin"] and case["consignee_gstin"].strip():
        assert case["box"] is False, "a challan with a GSTIN reads its State from the GSTIN and is not offered a State"


@pytest.mark.parametrize("case", VECTORS["back_day"], ids=lambda c: f"{c['status']}-{c['received_back_on']!r}-{c['clock_applies']}")
def test_the_back_day_box_and_the_statements_own_test_agree(case, db):
    challan = {"reason": "job_work", "status": case["status"], "received_back_on": case["received_back_on"], "document_date": "2026-05-10"}
    assert itc.is_received_back_without_a_day(challan) is case["without_a_day"]
    if case["without_a_day"]:
        assert case["offered"] is True, "the statement names a challan the screen offers no day box for"
    if case["offered"]:
        # The box is offered only where the amendment door takes the day: the door is CALLED here, not reasoned about from the vector's own fields.
        challan = _challan(db, f"JW/V-{case['status']}-{case['clock_applies']}", status=case["status"], back_on=case["received_back_on"])
        _line(db, challan)
        assert _amend(db, challan, {"received_back_on": "2026-07-01"})["received_back_on"] == "2026-07-01", "the box is offered for a challan the amendment door refuses a back day"
    if case["status"] in ("draft", "cancelled"):
        challan = _challan(db, f"JW/W-{case['status']}", status=case["status"])
        _line(db, challan)
        with pytest.raises(HTTPException):
            _amend(db, challan, {"received_back_on": "2026-07-01"})


def test_a_state_already_recorded_is_changed_by_the_same_door_and_the_statement_reads_the_new_one(db):
    ch = _challan(db, "JW/034", place="27")
    _line(db, ch)
    assert _row(_statement(db), "JW/034")["job_worker"]["state_code"] == "27"
    _amend(db, ch, {"place_of_supply": "29"})
    assert _row(_statement(db), "JW/034")["job_worker"]["state_code"] == "29"


def test_the_day_is_refused_before_a_lot_already_recorded_for_a_challan_of_tools_as_for_any_other(db):
    ch = _challan(db, "JW/035", status="received_back", goods_kind=TOOLS, sent_on="2026-05-10")
    ln = _line(db, ch)
    db.seed("delivery_challan_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "challan_id": ch["id"], "challan_line_id": ln["id"], "returned_on": "2026-08-20",
        "quantity_returned": "4", "quantity_lost_or_wasted": "0", "job_worker_challan_no": "JW/22", "job_worker_challan_date": "2026-08-21",
        "nature_of_job_work": "Machining"})
    with pytest.raises(HTTPException) as caught:
        _amend(db, ch, {"received_back_on": "2026-08-01"})          # before the lot of goods already back
    assert caught.value.status_code == 422
    assert _stored(db, ch)["received_back_on"] is None
    assert _amend(db, ch, {"received_back_on": "2026-08-20"})["received_back_on"] == "2026-08-20"      # the same day as the latest lot is allowed


def test_a_job_workers_state_is_audited_with_what_it_was_and_what_it_is(db, monkeypatch):
    import routers.sales_cycle as route
    from models.sales_cycle import DeliveryChallanUpdateIn
    import services.audit_service as audit

    ch = _challan(db, "JW/036", place="27")
    _line(db, ch)
    events = []
    monkeypatch.setattr(route, "_mock", lambda: False)
    monkeypatch.setattr(route, "_db", lambda: db)
    monkeypatch.setattr(route, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    user = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@x.test", "role": "Partner"}
    route.update_challan(ch["id"], DeliveryChallanUpdateIn(place_of_supply="29"), client_id=CLIENT, current_user=user)
    assert len(events) == 1
    old, new = events[0][1]["old_data"], events[0][1]["new_data"]
    assert old["place_of_supply"] == "27" and new["place_of_supply"] == "29", "a change to the State the statement reads leaves no trace of the old one"


def test_a_back_day_given_to_a_challan_that_had_none_is_audited_with_what_it_was_and_what_it_is(db, monkeypatch):
    import routers.sales_cycle as route
    from models.sales_cycle import DeliveryChallanUpdateIn
    import services.audit_service as audit

    ch = _challan(db, "JW/037", status="received_back", goods_kind=TOOLS)
    _line(db, ch)
    events = []
    monkeypatch.setattr(route, "_mock", lambda: False)
    monkeypatch.setattr(route, "_db", lambda: db)
    monkeypatch.setattr(route, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    user = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@x.test", "role": "Partner"}
    route.update_challan(ch["id"], DeliveryChallanUpdateIn(received_back_on="2026-07-01"), client_id=CLIENT, current_user=user)
    assert len(events) == 1
    old, new = events[0][1]["old_data"], events[0][1]["new_data"]
    assert old["received_back_on"] is None and new["received_back_on"] == "2026-07-01", "a day given to a challan that had none leaves no trace of there having been none"

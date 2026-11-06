"""The day goods came back and the day a challan is dated cannot be after today in India (found by the seventeenth slice's reading of the screens the sixteenth listed as next, PRE-A-015).

WHAT WAS WRONG
    The whole-challan "received back" (`DeliveryChallanUpdateIn.received_back_on`) was a bare string handed to the update and stored: a day that had not come, a day before the goods went
    out, "" (which the route does not drop, since it only drops None, and reached the DATE column) and text that is not a day were all accepted, and the date is the one that stops the
    s.143 clock. The same amendment's `document_date` and `extended_to` were bare strings too. The ITC-04 lot door (`ChallanReturnIn`) read its two dates by cutting them to their first ten
    characters ("2026-08-201" became another day) while its SERVICE already refused a day after today and one before the goods went out, in two sentences that the other door now shares.
    A TDS challan is recorded from the bank's counterfoil, whose BSR code and serial number exist only once the bank has taken the tax, and its date was judged as a day only (so was the
    date on an ESI or professional-tax challan: the thirteenth slice refused the day of the payment and of the filing, and left the challan's own).

WHAT IS HELD
    One rule says when goods can have come back (`domain/gst/delivery_challan.goods_back_problem`): not after today in India and not before they went out. Both doors that record it ask it,
    and the amendment that moves only the day they went out asks it for its ORDER against the days already recorded as back (the whole challan's, and the earliest lot's).
    The challan amendment reads its three dates as real days stored as the canonical day, refuses a blank one (the route drops what is None, so a blank would be reported as saved or reach
    the column) and leaves `extended_to`, a plan, free to run ahead. A challan's date is not after today in India, on the TDS door and on the payroll remittance door.

THE DAY. India's day is read through `ist_today` in each module that asks it; the tests put a fixed one there.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))

import models.sales_cycle
import routers.payroll
import routers.sales_cycle
import routers.tds_workspace
import services.itc_04_service
import services.sales_cycle_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc_tests
from core.auth import get_current_user
from domain.gst import delivery_challan as dc
from models.sales_cycle import ChallanReturnIn, DeliveryChallanUpdateIn
from routers.payroll import RemittanceIn
from routers.tds_workspace import CreateChallanRequest
from test_the_sales_cycle_before_the_tax_invoice import _order_db
from tests.e2e_harness import FakeDB

INDIA_TODAY = date(2026, 10, 9)
TODAY = INDIA_TODAY.isoformat()
TOMORROW = "2026-10-10"
NOT_HAPPENED = "A return cannot be recorded for a date that has not happened. Record it when the goods are back."
PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    """Every module that asks India's day gets the fixed one. raising=False so the same file can be run against the code before this slice (the control for "fails without the change")."""
    for module in (models.sales_cycle, svc, services.itc_04_service, routers.tds_workspace, routers.payroll):
        monkeypatch.setattr(module, "ist_today", lambda: INDIA_TODAY, raising=False)


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_goods_cannot_have_come_back_before_they_went_out_or_on_a_day_that_has_not_come():
    sent = date(2026, 6, 1)
    assert dc.goods_back_problem(sent, date(2026, 6, 1), INDIA_TODAY) is None, "the day they went out is allowed"
    assert dc.goods_back_problem(sent, INDIA_TODAY, INDIA_TODAY) is None, "today is allowed"
    assert dc.goods_back_problem(sent, date(2026, 5, 31), INDIA_TODAY) == "The goods cannot have come back on 2026-05-31, before they were sent out on 2026-06-01."
    assert dc.goods_back_problem(sent, date(2026, 10, 10), INDIA_TODAY) == NOT_HAPPENED
    assert dc.goods_back_problem(None, date(2020, 1, 1), INDIA_TODAY) is None, "without the day they went out, only the future is judged"
    assert dc.goods_back_problem(None, date(2026, 10, 10), INDIA_TODAY) == NOT_HAPPENED


# ── the whole-challan "received back" and the rest of the amendment ─────────────────────────────────────────────────────────────

def test_a_challan_amendment_refuses_goods_back_after_today_and_takes_today():
    with pytest.raises(ValidationError) as caught:
        DeliveryChallanUpdateIn(received_back_on=TOMORROW)
    assert NOT_HAPPENED in str(caught.value)
    assert DeliveryChallanUpdateIn(received_back_on=TODAY).received_back_on == TODAY
    assert DeliveryChallanUpdateIn(received_back_on="20261008").received_back_on == "2026-10-08", "stored as the canonical day"
    assert DeliveryChallanUpdateIn().received_back_on is None, "not sent is unchanged"


@pytest.mark.parametrize("field", ["document_date", "received_back_on", "extended_to"])
@pytest.mark.parametrize("bad", ["", "   ", "soon", "30/09/2026", "2026-02-30"])
def test_a_challan_amendment_date_that_is_not_a_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        DeliveryChallanUpdateIn(**{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


def test_the_day_a_challan_is_extended_to_is_a_plan_and_may_run_ahead():
    assert DeliveryChallanUpdateIn(extended_to="2027-01-01").extended_to == "2027-01-01"


def _job_work_challan(db, document_date="2026-06-01"):
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/17", "document_date": document_date, "reason": dc.REASON_JOB_WORK, "goods_kind": dc.GOODS_KIND_INPUTS,
        "lines": [{"description": "Casting", "quantity": 1, "rate_paise": 100}]})
    return db.store["delivery_challans"][-1]["id"]


def test_the_amendment_refuses_goods_back_before_they_went_out_and_takes_the_day_they_went_out():
    db = _order_db()
    cid = _job_work_challan(db)
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"received_back_on": "2026-05-31"})
    assert caught.value.status_code == 422
    assert "before they were sent out on 2026-06-01" in str(caught.value.detail)
    out = svc.update_challan(db, "F1", cid, {"received_back_on": "2026-06-01"})
    assert out["status"] == "received_back"


def test_an_amendment_that_moves_the_day_they_went_out_is_compared_with_the_new_day():
    db = _order_db()
    cid = _job_work_challan(db)
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"document_date": "2026-07-01", "received_back_on": "2026-06-15"})
    assert "before they were sent out on 2026-07-01" in str(caught.value.detail)


def test_moving_the_day_they_went_out_past_a_day_already_recorded_as_back_is_refused_in_the_same_sentence():
    """The other way the pair can be left the wrong way round: the day the goods came back is already stored and the amendment moves only the day they went out."""
    db = _order_db()
    cid = _job_work_challan(db)
    svc.update_challan(db, "F1", cid, {"received_back_on": "2026-06-15"})
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"document_date": "2026-07-01"})
    assert caught.value.status_code == 422
    assert str(caught.value.detail) == "The goods cannot have come back on 2026-06-15, before they were sent out on 2026-07-01."
    assert svc.update_challan(db, "F1", cid, {"document_date": "2026-06-15"})["document_date"] == "2026-06-15", "the same day is allowed"
    assert svc.update_challan(db, "F1", cid, {"document_date": "2026-06-10"})["document_date"] == "2026-06-10", "an earlier day is allowed"


def test_an_edit_of_something_else_does_not_judge_a_pair_that_was_stored_before_the_rule():
    """A row whose recorded day is before the day they went out (from before the rule) is not made unsaveable: only an amendment that gives one of the two days is compared."""
    db = _order_db()
    cid = _job_work_challan(db)
    db.store["delivery_challans"][-1]["received_back_on"] = "2026-05-01"
    assert svc.update_challan(db, "F1", cid, {"extended_to": "2027-01-01"})["extended_to"] == "2027-01-01"
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"document_date": "2026-06-02"})
    assert "before they were sent out on 2026-06-02" in str(caught.value.detail), "an amendment that gives the day they went out is compared"


def test_moving_the_day_they_went_out_past_a_lot_already_recorded_is_refused_in_the_same_sentence():
    """A lot recorded under ITC-04 leaves the challan's own `received_back_on` empty until every line is back, so an amendment of only the day they went out is compared with the
    earliest lot as well (found by an independent read of the first version, which compared only the whole challan's day)."""
    db = _order_db()
    cid = _job_work_challan(db)
    db.store["delivery_challan_returns"] = [
        {"id": "R1", "firm_id": "F1", "client_id": "C1", "challan_id": cid, "returned_on": "2026-06-20"},
        {"id": "R2", "firm_id": "F1", "client_id": "C1", "challan_id": cid, "returned_on": "2026-06-15"},
        {"id": "R3", "firm_id": "F1", "client_id": "C1", "challan_id": "another-challan", "returned_on": "2026-05-01"},
        {"id": "R4", "firm_id": "F1", "client_id": "C2", "challan_id": cid, "returned_on": "2026-05-02"},
    ]
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"document_date": "2026-07-01"})
    assert caught.value.status_code == 422
    assert str(caught.value.detail) == "The goods cannot have come back on 2026-06-15, before they were sent out on 2026-07-01."
    assert svc.update_challan(db, "F1", cid, {"document_date": "2026-06-10"})["document_date"] == "2026-06-10", "another challan's lot, and another client's, are not this challan's"
    assert svc.update_challan(db, "F1", cid, {"document_date": "2026-06-15"})["document_date"] == "2026-06-15", "the day of the earliest lot is allowed"


def test_the_amendments_other_two_dates_are_stored_as_the_canonical_day():
    assert DeliveryChallanUpdateIn(document_date="20260601").document_date == "2026-06-01"
    assert DeliveryChallanUpdateIn(extended_to="20270601").extended_to == "2027-06-01"
    assert DeliveryChallanUpdateIn(document_date=" 2026-06-01 ").document_date == "2026-06-01", "the box's stray spaces are not part of the day"


def test_the_stamp_has_one_caller_which_judges_every_day_it_stamps():
    """`record_goods_back` writes the day it is given, which is safe only while its callers judge the day first: `itc_04_service.record_return` has judged every lot's day, and
    `update_challan` judges its own. A severity argued from 'nothing else reaches this' is a test: a second caller fails here and must judge its day with the rule first."""
    root = Path(__file__).resolve().parent.parent
    callers = sorted(str(p.relative_to(root)) for base in ("services", "routers", "domain", "jobs", "core")
                     if (root / base).exists() for p in (root / base).rglob("*.py")
                     if p.name != "sales_cycle_service.py" and re.search(r"(?<![\w.])(?:\w+\.)?record_goods_back\(", p.read_text(encoding="utf-8")))
    assert callers == ["services/itc_04_service.py"]


def test_the_service_asks_for_a_day_that_has_not_come_whoever_calls_it():
    """The request model has judged it for the screen; the service is also called with a dict."""
    db = _order_db()
    cid = _job_work_challan(db)
    with pytest.raises(HTTPException) as caught:
        svc.update_challan(db, "F1", cid, {"received_back_on": TOMORROW})
    assert str(caught.value.detail) == NOT_HAPPENED


# ── the ITC-04 lot ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _return(**over):
    base = dict(client_id="C1", challan_line_id="L1", returned_on=TODAY, quantity_returned=1)
    base.update(over)
    return ChallanReturnIn(**base)


def test_a_lot_date_is_a_real_day_and_is_not_cut_to_its_first_ten_characters():
    assert _return(returned_on="20260820").returned_on == "2026-08-20", "stored as the canonical day"
    assert _return(job_worker_challan_date="20260819").job_worker_challan_date == "2026-08-19"
    assert _return(job_worker_challan_date="").job_worker_challan_date is None, "the job worker's challan date is optional"
    for bad in ["2026-08-201", "2026-08-20T10:00:00", "soon", ""]:
        with pytest.raises(ValidationError) as caught:
            _return(returned_on=bad)
        assert "returned_on must be a date written YYYY-MM-DD." in str(caught.value)
    with pytest.raises(ValidationError) as caught:
        _return(job_worker_challan_date="2026-08-201")
    assert "job_worker_challan_date must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("back", ["2026-05-31", TOMORROW])
def test_the_itc_04_door_says_exactly_the_sentence_of_the_shared_rule(back):
    """The door's own sentence is the rule's, character for character (the older ITC-04 tests hold a fragment of it, which could drift without a failure), and nothing is stored."""
    db = FakeDB()
    c = itc_tests._challan(db, "JW/9", "2026-06-01")
    ln = itc_tests._line(db, c, qty="10")
    with pytest.raises(HTTPException) as caught:
        services.itc_04_service.record_return(db, itc_tests.FIRM, itc_tests.CLIENT, c["id"], itc_tests._payload(ln, returned_on=back), "u1")
    assert caught.value.status_code == 422
    assert caught.value.detail == dc.goods_back_problem(date(2026, 6, 1), date.fromisoformat(back), INDIA_TODAY)
    assert db.rows("delivery_challan_returns") == []


# ── the TDS challan and the payroll remittance's challan ────────────────────────────────────────────────────────────────────────────

def _tds_challan(**over):
    base = dict(client_id="C1", bsr_code="0510308", challan_no="00123", section="194J", amount_paise=1000, financial_year="2026-27", quarter="Q2")
    base.update(over)
    return CreateChallanRequest(**base)


def test_a_tds_challan_dated_after_today_is_refused_and_today_and_the_past_are_allowed():
    with pytest.raises(ValidationError) as caught:
        _tds_challan(challan_date=TOMORROW)
    assert "The challan date cannot be after today's date in India." in str(caught.value)
    assert _tds_challan(challan_date=TODAY).challan_date == TODAY
    assert _tds_challan(challan_date="2026-04-07").challan_date == "2026-04-07"
    with pytest.raises(ValidationError) as caught:
        _tds_challan(challan_date="30/09/2026")
    assert "challan_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_payroll_remittance_challan_dated_after_today_is_refused_like_the_day_it_was_paid():
    base = dict(scheme="esic", wage_month="2026-09")
    with pytest.raises(ValidationError) as caught:
        RemittanceIn(challan_date=TOMORROW, **base)
    assert "challan_date cannot be in the future" in str(caught.value)
    assert RemittanceIn(challan_date=TODAY, **base).challan_date == TODAY
    assert RemittanceIn(**base).challan_date is None, "a challan is optional on the record"


# ── over HTTP: a 422 with the sentence at the door, not a stored day and not a 500 ─────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routers.sales_cycle.router)
    app.include_router(routers.tds_workspace.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("body,sentence", [
    ({"received_back_on": TOMORROW}, NOT_HAPPENED),
    ({"received_back_on": ""}, "received_back_on must be a date written YYYY-MM-DD."),
    ({"document_date": ""}, "document_date must be a date written YYYY-MM-DD."),
    ({"extended_to": "30/09/2026"}, "extended_to must be a date written YYYY-MM-DD."),
])
def test_the_challan_amendment_door_answers_422_with_the_sentence(client, body, sentence):
    r = client.patch("/api/sales-cycle/challans/ch-1", params={"client_id": "C1"}, json=body)
    assert r.status_code == 422, r.text
    assert sentence in r.text


@pytest.mark.parametrize("day,sentence", [
    (TOMORROW, "The challan date cannot be after today's date in India."),
    ("30/09/2026", "challan_date must be a date written YYYY-MM-DD."),
])
def test_the_tds_challan_door_answers_422_with_the_sentence(client, day, sentence):
    r = client.post("/api/tds-workspace/challans", json=dict(client_id="C1", bsr_code="0510308", challan_no="00123", section="194J", amount_paise=1000,
                                                              financial_year="2026-27", quarter="Q2", challan_date=day))
    assert r.status_code == 422, r.text
    assert sentence in r.text

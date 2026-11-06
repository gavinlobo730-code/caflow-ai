"""The job worker's own challan is not dated after the day the goods came back (POST-A-393, the third item).

WHAT WAS WRONG
    The lot a person records on FORM GST ITC-04 (`ChallanReturnIn`) carries the job worker's own challan number and date. The screen's date box was given the day the goods came back as a
    bound, but a bound on a date box is an input HINT (`min`/`max`: a date outside it is reported and still handed up), and the lot door read the date as "a real day" and nothing more, so
    a challan dated a week after the goods were received was stored. (A lot with no day the goods came back is refused anyway; with that day blank the box had no bound at all.)

WHAT IS HELD
    A job worker's challan travels with the goods it sends back, so the day on it is not later than the day they were received (`domain/gst/itc_04.job_worker_challan_problem`): the plain
    order of events, no period, rate or other statutory reading. The lot door asks it after the order of the day the goods came back (not after today in India, not before they went out), so
    a challan date that passes is not after today either. The date stays optional, and the challan is somebody else's document: only its order is asked, never its number.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))

import services.itc_04_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc_tests
from domain.gst import itc_04 as itc
from tests.e2e_harness import FakeDB

INDIA_TODAY = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: INDIA_TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": itc_tests.CLIENT, "firm_id": itc_tests.FIRM, "client_name": "Mfg Co"})
    return x


def _lots(db):
    return db.table("delivery_challan_returns").select("id, returned_on, job_worker_challan_date").execute().data or []


def _sent(db):
    challan = itc_tests._challan(db, "JW/31", "2026-06-01")
    return challan, itc_tests._line(db, challan, qty="10")


SENTENCE = ("The job worker's challan is dated 2026-06-12, after the day the goods came back (2026-06-10). "
            "A challan travels with the goods, so it cannot be later than the day they were received.")


def test_a_challan_dated_after_the_day_the_goods_came_back_is_refused_in_a_sentence_and_nothing_is_recorded(db):
    challan, line = _sent(db)
    with pytest.raises(HTTPException) as caught:
        itc_tests._record(db, challan, line, returned_on="2026-06-10", job_worker_challan_date="2026-06-12")
    assert caught.value.status_code == 422
    assert caught.value.detail == SENTENCE
    assert _lots(db) == [], "a lot was recorded over the refusal"


def test_a_challan_dated_the_day_the_goods_came_back_or_before_it_is_recorded(db):
    challan, line = _sent(db)
    itc_tests._record(db, challan, line, returned_on="2026-06-10", quantity_returned=3.0, job_worker_challan_date="2026-06-10")
    itc_tests._record(db, challan, line, returned_on="2026-06-10", quantity_returned=3.0, job_worker_challan_date="2026-06-02")
    assert sorted(r["job_worker_challan_date"] for r in _lots(db)) == ["2026-06-02", "2026-06-10"]


def test_the_challans_date_stays_optional(db):
    challan, line = _sent(db)
    itc_tests._record(db, challan, line, returned_on="2026-06-10", job_worker_challan_date=None)
    assert [r["job_worker_challan_date"] for r in _lots(db)] == [None]


def test_a_challan_dated_in_the_future_is_after_the_day_the_goods_came_back_whatever_that_day_is(db):
    """The goods came back today at the latest, so a challan dated tomorrow is later than that day: no second rule about today is needed."""
    challan, line = _sent(db)
    with pytest.raises(HTTPException) as caught:
        itc_tests._record(db, challan, line, returned_on=INDIA_TODAY.isoformat(), job_worker_challan_date="2026-10-10")
    assert caught.value.status_code == 422
    assert "after the day the goods came back (2026-10-09)" in caught.value.detail
    assert _lots(db) == []


def test_the_order_of_the_days_the_goods_came_back_is_asked_first(db):
    """A day the goods cannot have come back on is the first refusal: the challan's order is meaningless against it."""
    challan, line = _sent(db)
    with pytest.raises(HTTPException) as caught:
        itc_tests._record(db, challan, line, returned_on="2026-05-30", job_worker_challan_date="2026-06-12")
    assert "before they were sent out" in caught.value.detail


def test_the_pure_rule_asks_only_the_order_and_has_no_clock():
    d = date
    assert itc.job_worker_challan_problem(None, d(2026, 6, 10)) is None
    assert itc.job_worker_challan_problem(d(2026, 6, 10), d(2026, 6, 10)) is None
    assert itc.job_worker_challan_problem(d(2026, 6, 9), d(2026, 6, 10)) is None
    assert itc.job_worker_challan_problem(d(2026, 6, 12), d(2026, 6, 10)) == SENTENCE

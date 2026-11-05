"""The dates a firm records for a professional-tax notification, an engagement letter and a stock lot are judged before they are stored (found by the fifteenth slice's drive, PRE-A-015).

WHAT WAS WRONG
    `EngagementIn` and `EngagementUpdate` took start_date and expiry_date as bare strings handed to a DATE column, so a caller that is not the screen got the database's words in a
    422 for a date it could not read, and a letter could be made that lapses before it starts. `BatchIn` read "" as a date it did not check and stored it, accepted a lot made
    tomorrow and a lot that expires before it was made, and kept the first ten characters of whatever it was sent as typed ("20260101" sorts after "2026-12-31", "2026-12-311" was
    silently cut to a different day). `PTSlabSetIn` had its own copy of the real-day rule (and a different sentence from every other model), and accepted a notification dated
    after today: a notification a person has read has been issued. `TransferIn` took its quantity as typed, so "1,500" or "5 kg" raised inside the service and answered 500. The
    screens now refuse each of these first, in a sentence; this is the same refusal for every other caller.

WHAT IS HELD
    A date that is not a real day is a 422 naming the field (`models/iso_date.a_real_date`), and what is stored is the canonical YYYY-MM-DD; an optional date left blank is the same
    as absent (on a PATCH body, which the route reads without what was not sent, a blank date is refused instead, because reading it as absent would report a success for a change
    that was never made). A professional-tax notification's day of ISSUE cannot be after today in India; the day it TAKES EFFECT may be ahead. A lot's manufacture date cannot be
    after today in India; its expiry is a plan. A letter or a lot that lapses before it starts is refused; the same day is not. A PATCH of one date of a letter is compared with
    the stored other. A transfer's quantity is a number kept to the column's three decimals.

THE DAY. India's day is read through `ist_today` in the two modules that ask it; the tests below put a fixed one there, so they mean the same thing at any hour (a day computed at
    import would have turned "tomorrow" into "today" for a suite that ran across midnight IST).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import get_current_user
from models.payroll import PTSlabSetIn
from routers.engagement_letters import EngagementIn, EngagementUpdate, router as engagement_router
from routers.inventory import BatchIn, TransferIn
from routers.payroll import router as payroll_router

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
INDIA_TODAY = date(2026, 10, 9)
TODAY = INDIA_TODAY.isoformat()
TOMORROW = "2026-10-10"
BAD_SHAPES = ["30/09/2026", "2026-02-30", "2026-9-1x", "soon"]
BANDS = [{"from_paise": 0, "to_paise": None, "amount_paise": 20000}]


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    """The two modules that ask India's day get a fixed one. A model that read the UTC clock, or `date.today()`, would not see it and these tests would fail."""
    import models.payroll
    import routers.inventory
    # raising=False so the same file can be run against the code before this slice, which had no such name in these modules (the control for "fails without the change").
    monkeypatch.setattr(models.payroll, "ist_today", lambda: INDIA_TODAY, raising=False)
    monkeypatch.setattr(routers.inventory, "ist_today", lambda: INDIA_TODAY, raising=False)


def _slabs(**over):
    base = dict(state="GJ", effective_from="2027-04-01", notification_reference="PFT/2026/12", notification_date="2026-03-10", bands=BANDS)
    base.update(over)
    return PTSlabSetIn(**base)


def _batch(**over):
    return BatchIn(**{"client_id": "C1", "service_catalogue_id": "sc1", "batch_no": "L-2026-001", **over})


def _transfer(**over):
    return TransferIn(**{"client_id": "C1", "service_catalogue_id": "sc1", "from_godown_id": "g1", "to_godown_id": "g2", "quantity": "5", "movement_date": "2026-10-08", **over})


# ── the professional-tax notification ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["effective_from", "notification_date"])
@pytest.mark.parametrize("bad", BAD_SHAPES + ["", "   "])
def test_a_notification_date_that_is_not_a_real_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        _slabs(**{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_notification_cannot_have_been_issued_on_a_day_that_has_not_come():
    with pytest.raises(ValidationError) as caught:
        _slabs(notification_date=TOMORROW)
    assert "The notification date cannot be after today's date in India." in str(caught.value)


def test_a_notification_issued_today_is_allowed_and_one_that_takes_effect_later_is_the_normal_case():
    assert _slabs(notification_date=TODAY).notification_date == TODAY
    assert _slabs(effective_from=TOMORROW).effective_from == TOMORROW
    assert _slabs(effective_from="20270401").effective_from == "2027-04-01"


def test_the_statutory_values_door_answers_422_with_the_sentence_for_a_notification_dated_ahead():
    app = FastAPI()
    app.include_router(payroll_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    client = TestClient(app, raise_server_exceptions=False)
    body = {"state": "GJ", "effective_from": "2027-04-01", "notification_reference": "PFT/2026/12", "notification_date": TOMORROW, "bands": BANDS}
    r = client.put("/api/payroll/statutory-values/pt", json=body)
    assert r.status_code == 422, r.text
    assert "The notification date cannot be after today's date in India." in r.text
    ok = client.put("/api/payroll/statutory-values/pt", json={**body, "notification_date": "2026-03-10"})
    assert ok.status_code == 200, ok.text


# ── the engagement letter ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["start_date", "expiry_date"])
@pytest.mark.parametrize("bad", BAD_SHAPES + ["2026-04-011", "2026-04-01T00:00:00"])
def test_a_letters_date_that_is_not_a_real_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        EngagementIn(title="GST", **{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_letter_date_is_no_date(blank):
    letter = EngagementIn(title="GST", start_date=blank, expiry_date=blank)
    assert (letter.start_date, letter.expiry_date) == (None, None)


def test_a_letter_does_not_lapse_before_it_starts_but_may_lapse_the_day_it_starts():
    with pytest.raises(ValidationError) as caught:
        EngagementIn(title="GST", start_date="2026-04-01", expiry_date="2026-03-01")
    assert "The expiry date cannot be before the start date." in str(caught.value)
    assert EngagementIn(title="GST", start_date="2026-04-01", expiry_date="2026-04-01").expiry_date == "2026-04-01"
    assert EngagementIn(title="GST", expiry_date="2026-03-01").start_date is None, "an expiry alone has nothing to precede"


def test_a_letters_order_is_judged_on_the_days_and_not_on_how_they_were_typed():
    """A compact date is stored as the canonical day, so a compact start and a dashed expiry are compared as days (as text, '20260401' sorts after '2026-12-31')."""
    letter = EngagementIn(title="GST", start_date="20260401", expiry_date="2026-12-31")
    assert (letter.start_date, letter.expiry_date) == ("2026-04-01", "2026-12-31")
    with pytest.raises(ValidationError):
        EngagementIn(title="GST", start_date="2026-10-31", expiry_date="20260101")


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_date_on_the_patch_is_refused_not_dropped(blank):
    with pytest.raises(ValidationError) as caught:
        EngagementUpdate(expiry_date=blank)
    assert "expiry_date must be a date written YYYY-MM-DD." in str(caught.value)
    assert EngagementUpdate(title="GST").expiry_date is None, "an omitted date stays omitted"


def test_the_patch_model_checks_the_order_only_of_the_dates_it_was_sent():
    with pytest.raises(ValidationError):
        EngagementUpdate(start_date="2026-04-01", expiry_date="2026-03-01")
    assert EngagementUpdate(expiry_date="2026-03-01").expiry_date == "2026-03-01"


def _app_with_the_engagement_door():
    app = FastAPI()
    app.include_router(engagement_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_engagement_door_answers_422_with_the_sentence_for_a_letter_that_lapses_before_it_starts():
    client = _app_with_the_engagement_door()
    r = client.post("/api/engagement-letters", json={"title": "GST", "start_date": "2026-04-01", "expiry_date": "2026-03-01"})
    assert r.status_code == 422, r.text
    assert "The expiry date cannot be before the start date." in r.text
    ok = client.post("/api/engagement-letters", json={"title": "GST", "start_date": "", "expiry_date": ""})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["engagement"]["start_date"] is None


def test_a_patch_of_one_date_is_compared_with_the_stored_other_so_a_letter_cannot_be_made_to_lapse_before_it_starts():
    """The model sees only what was sent; the route judges the dates the letter WOULD hold (found by the independent read: two PATCHes, each alone in order, left expiry 2026-01-01
    on a letter starting 2030-01-01)."""
    client = _app_with_the_engagement_door()
    made = client.post("/api/engagement-letters", json={"title": "GST", "start_date": "2026-07-01", "expiry_date": "2026-09-30"})
    assert made.status_code == 200, made.text
    letter = made.json()["data"]["engagement"]["id"]
    url = f"/api/engagement-letters/{letter}"

    early = client.patch(url, json={"expiry_date": "2026-01-01"})
    assert early.status_code == 422, early.text
    assert "The expiry date cannot be before the start date." in early.text
    late = client.patch(url, json={"start_date": "2030-01-01"})
    assert late.status_code == 422, late.text
    # …nothing was changed by the refused ones, and an order that holds is accepted, as is a PATCH that does not touch the dates.
    assert client.patch(url, json={"expiry_date": "2026-12-31"}).status_code == 200
    assert client.patch(url, json={"start_date": "2026-12-31"}).status_code == 200, "the same day is allowed"
    assert client.patch(url, json={"title": "GST, revised"}).status_code == 200


def test_the_database_branch_of_the_patch_reads_the_stored_dates_and_compares_them():
    """The same rule on the branch that talks to the database (the mock-mode test above cannot reach it): the stored dates are selected with the status, and a PATCH that would leave
    the letter lapsing before it starts is refused BEFORE the update is built."""
    from unittest.mock import MagicMock, patch

    from fastapi import HTTPException

    from routers.engagement_letters import update_engagement

    db = MagicMock()
    stored = db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value
    stored.data = {"status": "Draft", "start_date": "2026-07-01", "expiry_date": "2026-09-30"}
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "e1", "expiry_date": "2026-12-31"}]
    with patch("routers.engagement_letters._db", return_value=db), patch("routers.engagement_letters._assert_engagement_scope", return_value=None):
        with pytest.raises(HTTPException) as caught:
            update_engagement(engagement_id="e1", body=EngagementUpdate(expiry_date="2026-01-01"), current_user=PARTNER)
        assert caught.value.status_code == 422
        assert caught.value.detail == "The expiry date cannot be before the start date."
        db.table.return_value.update.assert_not_called()
        with pytest.raises(HTTPException):
            update_engagement(engagement_id="e1", body=EngagementUpdate(start_date="2030-01-01"), current_user=PARTNER)
        db.table.return_value.update.assert_not_called()
        update_engagement(engagement_id="e1", body=EngagementUpdate(expiry_date="2026-12-31"), current_user=PARTNER)
        db.table.return_value.update.assert_called_once()
    db.table.return_value.select.assert_any_call("status, start_date, expiry_date")


# ── the stock lot and the stock transfer ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["manufactured_on", "expiry_date"])
@pytest.mark.parametrize("bad", ["30/09/2026", "soon", "2026-12-311", "2026-09-30junk", "2026-09-30T00:00:00"])
def test_a_lots_date_that_is_not_a_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        _batch(**{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_lot_date_is_no_date(blank):
    lot = _batch(manufactured_on=blank, expiry_date=blank)
    assert (lot.manufactured_on, lot.expiry_date) == (None, None)


def test_a_lot_cannot_have_been_made_on_a_day_that_has_not_come_but_may_expire_later():
    with pytest.raises(ValidationError) as caught:
        _batch(manufactured_on=TOMORROW)
    assert "The manufacture date cannot be after today's date in India." in str(caught.value)
    assert _batch(manufactured_on=TODAY).manufactured_on == TODAY
    assert _batch(expiry_date=TOMORROW).expiry_date == TOMORROW, "an expiry is a plan"


def test_a_lot_does_not_lapse_before_it_was_made_but_may_lapse_the_day_it_was_made():
    with pytest.raises(ValidationError) as caught:
        _batch(manufactured_on="2026-09-01", expiry_date="2026-08-01")
    assert "The expiry date cannot be before the manufacture date." in str(caught.value)
    assert _batch(manufactured_on="2026-09-01", expiry_date="2026-09-01").expiry_date == "2026-09-01"


def test_a_lots_order_is_judged_on_the_days_and_not_on_how_they_were_typed():
    """Found by the independent read: the old reading kept '20260101' as typed, which sorts AFTER '2026-12-31', so a valid lot was refused and an expiry before the manufacture
    date was accepted (and then refused by the database's CHECK as a 400 with no sentence)."""
    lot = _batch(manufactured_on="20260101", expiry_date="2026-12-31")
    assert (lot.manufactured_on, lot.expiry_date) == ("2026-01-01", "2026-12-31")
    with pytest.raises(ValidationError) as caught:
        _batch(manufactured_on="2026-09-30", expiry_date="20260101")
    assert "The expiry date cannot be before the manufacture date." in str(caught.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_transfer_without_a_date_is_refused_in_the_doors_sentence(blank):
    with pytest.raises(ValidationError) as caught:
        _transfer(movement_date=blank)
    assert "The date the stock moved must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("bad", ["2026-10-081", "2026-10-08T00:00:00", "08/10/2026"])
def test_a_transfers_date_is_a_real_day_and_is_not_cut_to_a_different_one(bad):
    with pytest.raises(ValidationError) as caught:
        _transfer(movement_date=bad)
    assert "The date the stock moved must be a date written YYYY-MM-DD." in str(caught.value)
    assert _transfer(movement_date="20261008").movement_date == "2026-10-08", "stored as the canonical day"


@pytest.mark.parametrize("bad", ["1,500", "5 kg", "abc", "", "   ", "0.0005", "1.2345"])
def test_a_transfers_quantity_that_is_not_a_quantity_is_refused_in_a_sentence_instead_of_raising_in_the_service(bad):
    """`Decimal("1,500")` raised inside the service and answered 500 with no sentence; a fourth decimal was rounded by NUMERIC(10,3), so the value no longer matched what was typed."""
    with pytest.raises(ValidationError) as caught:
        _transfer(quantity=bad)
    text = str(caught.value)
    assert "Quantity must be a number." in text or "Quantity is kept to 3 decimals" in text


@pytest.mark.parametrize("good", ["5", "12.5", "0.001", "1500", "1500.000"])
def test_a_transfers_quantity_that_is_a_quantity_is_kept_as_typed(good):
    assert _transfer(quantity=good).quantity == good

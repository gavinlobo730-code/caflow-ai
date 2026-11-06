"""The last three write forms the date drive reached judge their dates before they are stored (found by the eighteenth slice's drive of them, PRE-A-015).

WHAT WAS WRONG
    1. A recurring SALES template (`RecurringTemplateIn` / `RecurringTemplateUpdateIn`) took its start and stop dates as bare strings. The service's date parser raised on "" or
       "30/09/2026": a 500 with no sentence (this door has no try/except), for any caller that is not the screen. An EDIT that moved only one end could leave the window the wrong way
       round (create has always refused a stop date before the start; update never asked). The manual run's `as_of` day was the same bare string, and the same 500.
    2. An export's shipping bill date (`SalesInvoiceIn` and `SalesInvoiceUpdateIn`, GSTR-1 Table 6A's sbdt) was a bare string stored as typed in a DATE column: text that was not a day
       reached the database and the door answered "Unable to … Please try again." (a 200 with `success: false`, naming no field), and a day ahead was kept. Customs issues the shipping
       bill AFTER the invoice and the date is recorded on an issued invoice too, so by the day it is recorded it is in the past.
    3. A foreign supplier's no-PE declaration date (`VendorIn` / `VendorUpdateIn`) was the same: a bare string, and the only evidence behind a nil deduction (s.201(1)/(1A) put the
       consequence of a wrong nil on the deductor), so a declaration dated tomorrow is not evidence yet.

WHAT IS HELD
    A date that is not a real day is a 422 naming the field, in the one rule every model of this kind shares (`models/iso_date`); a real one is stored as the canonical day. A template's
    window is a PLAN, so neither end is bounded by today, a blank stop date means none and an edit that clears it clears it (held at the ROUTE, which dumps the body with `exclude_unset`:
    the test below sends the edit through the door and reads the template back), and an edit that moves an end and leaves the window reversed is refused. The
    shipping bill date and the no-PE declaration date are days that have happened: not after today in India. A blank is no date on a new document and is REFUSED on an update (the route
    drops what is empty, so a blank would be reported as saved). How far before the invoice a shipping bill may be dated is customs practice, and no reading of it is assumed.

THE DAY. India's day is read through `ist_today` in `models.iso_date`, the module that asks it; the tests put a fixed one there (a day computed at import turns "tomorrow" into "today" for a
    suite that runs across midnight IST, the reason the sixteenth slice's tests do the same).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import get_current_user
from models.invoices import SalesInvoiceIn, SalesInvoiceUpdateIn
import models.iso_date
from models.parties import VendorIn, VendorUpdateIn
import routers.recurring_invoices
import routers.sales_invoices
import routers.vendors
from routers.recurring_invoices import RecurringLineIn, RecurringTemplateIn, RecurringTemplateUpdateIn

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
INDIA_TODAY = date(2026, 10, 9)
TODAY = INDIA_TODAY.isoformat()
TOMORROW = "2026-10-10"
BAD_SHAPES = ["", "   ", "30/09/2026", "2026-02-30", "2026-9-1x", "soon"]


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    """The module that asks India's day gets a fixed one. raising=False so the same file can be run against the code before this slice (the control for "fails without the change")."""
    monkeypatch.setattr(models.iso_date, "ist_today", lambda: INDIA_TODAY, raising=False)


# ── a recurring sales template's window ───────────────────────────────────────────────────────────────────────────────────────────────

def _template(**over):
    line = RecurringLineIn.model_validate({"service_catalogue_id": "sc1", "description": "Bookkeeping", "quantity": 1, "rate_paise": 500_000, "gst_rate_percent": 18})
    base = dict(client_id="c1", customer_id="cu1", title="Monthly bookkeeping", frequency="monthly", start_date="2026-11-01", lines=[line])
    base.update(over)
    return RecurringTemplateIn(**base)


@pytest.mark.parametrize("bad", BAD_SHAPES)
def test_a_template_start_date_that_is_not_a_real_day_is_refused_naming_itself(bad):
    with pytest.raises(ValidationError) as caught:
        _template(start_date=bad)
    assert "start_date must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("bad", ["30/09/2027", "2027-02-30", "later"])
def test_a_template_stop_date_that_is_not_a_real_day_is_refused_but_blank_means_none(bad):
    with pytest.raises(ValidationError) as caught:
        _template(end_date=bad)
    assert "end_date must be a date written YYYY-MM-DD." in str(caught.value)
    assert _template(end_date="").end_date is None
    assert _template(end_date="   ").end_date is None
    assert _template(end_date=None).end_date is None


def test_a_templates_window_is_a_plan_so_neither_end_is_bounded_by_today_and_both_are_stored_as_the_canonical_day():
    t = _template(start_date="20300101", end_date=" 2031-12-31 ")
    assert (t.start_date, t.end_date) == ("2030-01-01", "2031-12-31")
    assert _template(start_date="2020-01-01").start_date == "2020-01-01", "a template may begin in the past (it catches up)"


def test_an_update_refuses_a_blank_start_date_leaves_an_omitted_one_alone_and_keeps_a_blank_stop_date_as_the_instruction_to_clear_it():
    assert RecurringTemplateUpdateIn().start_date is None
    assert RecurringTemplateUpdateIn(start_date="20261201").start_date == "2026-12-01"
    with pytest.raises(ValidationError) as caught:
        RecurringTemplateUpdateIn(start_date="")
    assert "start_date must be a date written YYYY-MM-DD." in str(caught.value)
    for blank in ("", "   "):
        updated = RecurringTemplateUpdateIn(end_date=blank)
        assert updated.end_date is None
        # `exclude_unset` is how the route dumps it, and the key must survive as an explicit None: that is what the service reads as "clear".
        assert updated.model_dump(exclude_unset=True) == {"end_date": None}
    assert RecurringTemplateUpdateIn().model_dump(exclude_unset=True) == {}, "an edit that does not mention the stop date leaves it alone"
    with pytest.raises(ValidationError) as caught:
        RecurringTemplateUpdateIn(end_date="30/09/2027")
    assert "end_date must be a date written YYYY-MM-DD." in str(caught.value)


# ── an export's shipping bill date ────────────────────────────────────────────────────────────────────────────────────────────────────

def _invoice_in(**over):
    body = dict(client_id="c1", customer_id="CUST", invoice_no="INV-1", invoice_date="2026-05-10",
                lines=[{"description": "svc", "quantity": 1, "rate_paise": 100_000_00, "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}])
    body.update(over)
    return SalesInvoiceIn(**body)


@pytest.mark.parametrize("bad", ["30/09/2026", "2026-02-30", "soon", "2026-08-201"])
def test_a_shipping_bill_date_that_is_not_a_real_day_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        _invoice_in(shipping_bill_date=bad)
    assert "shipping_bill_date must be a date written YYYY-MM-DD." in str(caught.value)
    with pytest.raises(ValidationError) as caught:
        SalesInvoiceUpdateIn(shipping_bill_date=bad)
    assert "shipping_bill_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_shipping_bill_dated_after_today_is_refused_and_today_and_the_past_are_stored_as_the_canonical_day():
    for build in (lambda d: _invoice_in(shipping_bill_date=d), lambda d: SalesInvoiceUpdateIn(shipping_bill_date=d)):
        with pytest.raises(ValidationError) as caught:
            build(TOMORROW)
        assert "The shipping bill date cannot be after today's date in India." in str(caught.value)
        assert build(TODAY).shipping_bill_date == TODAY
        assert build("20250514").shipping_bill_date == "2025-05-14"
        assert build(" 2025-05-14 ").shipping_bill_date == "2025-05-14"


def test_a_blank_shipping_bill_date_is_no_date_on_a_new_invoice_and_is_refused_on_an_update():
    assert _invoice_in().shipping_bill_date is None
    assert _invoice_in(shipping_bill_date="").shipping_bill_date is None
    assert _invoice_in(shipping_bill_date="   ").shipping_bill_date is None
    assert SalesInvoiceUpdateIn().shipping_bill_date is None, "not sent is unchanged"
    with pytest.raises(ValidationError) as caught:
        SalesInvoiceUpdateIn(shipping_bill_date="")
    assert "shipping_bill_date must be a date written YYYY-MM-DD." in str(caught.value), "a blank on a PATCH would be dropped by the route and reported as saved"


# ── a foreign supplier's no-PE declaration date ───────────────────────────────────────────────────────────────────────────────────────

def _vendor(**over):
    base = dict(client_id="c1", name="Acme GmbH")
    base.update(over)
    return base


@pytest.mark.parametrize("bad", ["30/09/2026", "2026-02-30", "soon"])
def test_a_no_pe_declaration_date_that_is_not_a_real_day_is_refused_naming_the_field(bad):
    for build in (lambda d: VendorIn(**_vendor(no_pe_declaration_on=d)), lambda d: VendorUpdateIn(no_pe_declaration_on=d)):
        with pytest.raises(ValidationError) as caught:
            build(bad)
        assert "no_pe_declaration_on must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_declaration_dated_after_today_is_refused_and_today_and_the_past_are_stored_as_the_canonical_day():
    for build in (lambda d: VendorIn(**_vendor(no_pe_declaration_on=d)), lambda d: VendorUpdateIn(no_pe_declaration_on=d)):
        with pytest.raises(ValidationError) as caught:
            build(TOMORROW)
        assert "The no-PE declaration date cannot be after today's date in India." in str(caught.value)
        assert build(TODAY).no_pe_declaration_on == TODAY
        assert build("20260401").no_pe_declaration_on == "2026-04-01"


def test_a_blank_declaration_date_is_no_date_on_a_new_supplier_and_is_refused_on_an_update():
    assert VendorIn(**_vendor()).no_pe_declaration_on is None
    assert VendorIn(**_vendor(no_pe_declaration_on="")).no_pe_declaration_on is None
    assert VendorUpdateIn().no_pe_declaration_on is None
    with pytest.raises(ValidationError) as caught:
        VendorUpdateIn(no_pe_declaration_on="")
    assert "no_pe_declaration_on must be a date written YYYY-MM-DD." in str(caught.value)


# ── over HTTP: a 422 with the sentence at the door, not a 500 from the date parser or the database ──────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routers.recurring_invoices.router)
    app.include_router(routers.sales_invoices.router)
    app.include_router(routers.vendors.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_recurring_invoice_doors_answer_422_with_the_sentence(client):
    line = {"service_catalogue_id": "sc1", "description": "Bookkeeping", "quantity": 1, "rate_paise": 500_000, "gst_rate_percent": 18}
    r = client.post("/api/recurring-invoices", json=dict(client_id="c1", customer_id="cu1", title="t", frequency="monthly", start_date="30/09/2026", lines=[line]))
    assert r.status_code == 422, r.text
    assert "start_date must be a date written YYYY-MM-DD." in r.text
    r = client.put("/api/recurring-invoices/t1", json={"start_date": ""})
    assert r.status_code == 422, r.text
    assert "start_date must be a date written YYYY-MM-DD." in r.text


def test_the_invoice_and_vendor_doors_answer_422_with_the_sentence(client):
    r = client.patch("/api/sales-invoices/inv-1", json={"shipping_bill_date": TOMORROW})
    assert r.status_code == 422, r.text
    assert "The shipping bill date cannot be after today's date in India." in r.text
    r = client.patch("/api/vendors/v-1", json={"no_pe_declaration_on": "30/09/2026"})
    assert r.status_code == 422, r.text
    assert "no_pe_declaration_on must be a date written YYYY-MM-DD." in r.text
    r = client.post("/api/vendors/", json=_vendor(no_pe_declaration_on=TOMORROW))
    assert r.status_code == 422, r.text
    assert "The no-PE declaration date cannot be after today's date in India." in r.text


def test_an_edit_that_clears_the_stop_date_clears_it_through_the_door_and_one_that_does_not_mention_it_leaves_it(client):
    """The route dumps the body with `exclude_unset`, so a stop date the screen cleared (it sends null) arrives as an explicit None and one the edit does not mention is not in the dump at all.
    The model and the service are tested apart above; this holds the link between them, which was a comment until the independent read of the server half found the route could be changed to
    `exclude_none` with every test still green."""
    import services.recurring_invoice_service as rec
    line = {"service_catalogue_id": "sc1", "description": "Bookkeeping", "quantity": 1, "rate_paise": 500_000, "gst_rate_percent": 18}
    body = dict(client_id="c1", customer_id="cu1", title="t", frequency="monthly", start_date="2026-11-01", end_date="2027-10-31", lines=[line])
    created = client.post("/api/recurring-invoices", json=body)
    assert created.status_code == 200, created.text
    template_id = created.json()["data"]["id"]
    try:
        put = lambda payload: client.put(f"/api/recurring-invoices/{template_id}", json=payload)   # noqa: E731
        r = put({"title": "renamed"})
        assert r.status_code == 200 and r.json()["data"]["end_date"] == "2027-10-31", f"an edit that does not mention the stop date changed it: {r.text}"
        for cleared in ({"end_date": None}, {"end_date": ""}, {"end_date": "   "}):
            assert put({"end_date": "2027-10-31"}).json()["data"]["end_date"] == "2027-10-31"
            r = put(cleared)
            assert r.status_code == 200, (cleared, r.text)
            assert r.json()["data"]["end_date"] is None, f"{cleared} did not clear the stop date: {r.text}"
        assert put({"start_date": "2026-12-01"}).json()["data"]["start_date"] == "2026-12-01"
        r = put({"start_date": ""})
        assert r.status_code == 422 and "start_date must be a date written YYYY-MM-DD." in r.text, "a blank first day is refused on an edit, not dropped"
    finally:
        rec.MOCK_RECURRING_TEMPLATES[:] = [t for t in rec.MOCK_RECURRING_TEMPLATES if t.get("id") != template_id]


def test_a_manual_run_for_a_day_that_is_not_one_is_a_422_naming_the_field_and_a_blank_is_today(client):
    """`as_of` was a bare query string handed to the date parser: a 500 for a script (the screen never sends one). The caller's access is asked FIRST (a template that is not theirs is a 404
    before the day is judged: `tests/test_recurring_client_scope.py` holds that order for every template route, and a first version of the fix judged the day before it and broke it)."""
    import services.recurring_invoice_service as rec
    line = {"service_catalogue_id": "sc1", "description": "Bookkeeping", "quantity": 1, "rate_paise": 500_000, "gst_rate_percent": 18}
    # The template starts in 2099, so the blank-day run below (which is for the REAL today) has nothing due and generates nothing, whatever day the suite runs on: a first version started it on
    # 1 November 2026, and run on or after that day it left a draft invoice and a run row in the mock stores (found by the independent read of the eighteenth slice's last edits).
    body = dict(client_id="c1", customer_id="cu1", title="t", frequency="monthly", start_date="2099-01-01", lines=[line])
    created = client.post("/api/recurring-invoices", json=body)
    assert created.status_code == 200, created.text
    template_id = created.json()["data"]["id"]
    try:
        for path in ("/api/recurring-invoices/run", f"/api/recurring-invoices/{template_id}/run"):
            for bad in ("30/09/2026", "soon", "2026-02-30"):
                r = client.post(path, params={"as_of": bad})
                assert r.status_code == 422, (path, bad, r.text)
                assert "as_of must be a date written YYYY-MM-DD." in r.text, (path, bad, r.text)
        r = client.post("/api/recurring-invoices/run", params={"as_of": ""})
        assert r.status_code == 200, f"a blank day is no day: the run is for today ({r.text})"
        # Access first: a template that is not there for this caller is refused as it always was, whatever day was asked for.
        r = client.post("/api/recurring-invoices/no-such-template/run", params={"as_of": "soon"})
        assert r.status_code == 404, f"the day was judged before the caller's access ({r.status_code}: {r.text})"
    finally:
        rec.MOCK_RECURRING_TEMPLATES[:] = [t for t in rec.MOCK_RECURRING_TEMPLATES if t.get("id") != template_id]

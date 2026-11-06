"""The days a bank or a portal printed cannot be after today in India, and are stored as the real day they are (found by the sixteenth slice's drive, PRE-A-015).

WHAT WAS WRONG
    The section 140A challan's deposit date and the Capital Gains Accounts Scheme deposit date were typed `date` (so a real day) and nothing more: a deposit dated tomorrow was
    stored. The e-invoice acknowledgement day and the e-way bill's own date were read through `portal_day` and stored, and a day that had not come was stored with them. The
    purchase bill's Form 15CA date was a bare string stored as typed. A bank has taken a deposit, and a portal has printed an acknowledgement, a bill number and a filing, by the
    time a person records them: a later day is a typing mistake, and the screens now refuse it before anything is sent. This is the same refusal for every other caller.

WHAT IS HELD
    The §140A deposit date and the CGAS deposit date, the IRP acknowledgement day, the e-way bill's date and the Form 15CA date cannot be after today in India; the day an e-way bill is
    valid UPTO is a plan and may be ahead. A Form 15CA date is a real day stored as the canonical YYYY-MM-DD; on a new bill a blank one is no date, and on a PATCH it is refused (the
    route drops what was not sent, so a blank read as absent would be reported as saved). The advance-tax instalment's paid date already had the refusal and keeps it.

THE DAY. India's day is read through `ist_today` in each module that asks it; the tests put a fixed one there (the same reason as the fifteenth slice's: a day computed at import turns
    "tomorrow" into "today" for a suite that runs across midnight IST).
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

import models.invoices
import routers.einvoice
import routers.eway_bill
import routers.income_tax
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn
from routers.einvoice import RecordIRNRequest
from routers.eway_bill import RecordEWBGeneratedRequest
from routers.income_tax import AdvanceTaxInstallmentInput, ReinvestmentIn, SelfAssessmentChallanIn

INDIA_TODAY = date(2026, 10, 9)
TODAY = INDIA_TODAY.isoformat()
TOMORROW = "2026-10-10"
THE_SENTENCE = "cannot be after today's date in India."


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    """Every module that asks India's day gets the fixed one. A model that read the UTC clock or `date.today()` would not see it and these tests would fail. raising=False so the
    same file can be run against the code before this slice (the control for "fails without the change")."""
    for module in (routers.income_tax, routers.einvoice, routers.eway_bill, models.invoices):
        monkeypatch.setattr(module, "ist_today", lambda: INDIA_TODAY, raising=False)


def _challan(**over):
    base = dict(client_id="C1", financial_year="2026-27", bsr_code="0510308", deposit_date=TODAY, challan_serial_no="00123", total_paise=100000)
    base.update(over)
    return SelfAssessmentChallanIn(**base)


def _claim(**over):
    base = dict(section="54F", new_asset_description="A flat")
    base.update(over)
    return ReinvestmentIn(**base)


def _bill(**over):
    return PurchaseBillIn(**{"client_id": "C1", "vendor_id": "v1", "bill_date": "2026-10-01", "lines": [PurchaseBillLineIn(description="Licence", rate_paise=100000, service_catalogue_id="sc1")], **over})


# ── the §140A challan ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_challan_deposited_on_a_day_that_has_not_come_is_refused_and_today_is_allowed():
    with pytest.raises(ValidationError) as caught:
        _challan(deposit_date=TOMORROW)
    assert f"The deposit date {THE_SENTENCE}" in str(caught.value)
    assert _challan(deposit_date=TODAY).deposit_date == INDIA_TODAY
    assert _challan(deposit_date="2026-04-15").deposit_date == date(2026, 4, 15)


# ── the Capital Gains Accounts Scheme deposit ────────────────────────────────────────────────────────────────────────────────────

def test_a_cgas_deposit_dated_after_today_is_refused_and_an_unstated_one_is_allowed():
    with pytest.raises(ValidationError) as caught:
        _claim(cgas_deposit_date=TOMORROW)
    assert f"The deposit date {THE_SENTENCE}" in str(caught.value)
    assert _claim(cgas_deposit_date=TODAY).cgas_deposit_date == INDIA_TODAY
    assert _claim().cgas_deposit_date is None


# ── the advance-tax instalment keeps the refusal it already had ───────────────────────────────────────────────────────────────────

def test_an_advance_tax_instalment_paid_after_today_is_still_refused():
    with pytest.raises(ValidationError) as caught:
        AdvanceTaxInstallmentInput(installment_number=1, paid_amount_paise=100, paid_date=TOMORROW)
    assert "paid_date cannot be in the future" in str(caught.value)


# ── the e-invoice acknowledgement and the e-way bill ───────────────────────────────────────────────────────────────────────────

def test_an_acknowledgement_the_portal_printed_after_today_is_refused():
    base = dict(irn="a" * 64, ack_number="112010012345678")
    with pytest.raises(ValidationError) as caught:
        RecordIRNRequest(ack_date=TOMORROW, **base)
    assert f"The acknowledgement date {THE_SENTENCE}" in str(caught.value)
    assert RecordIRNRequest(ack_date=TODAY, **base).ack_date == TODAY
    assert RecordIRNRequest(ack_date="2026-10-09 23:59:59", **base).ack_date == TODAY, "a time of day is dropped: the day is what is stored"
    with pytest.raises(ValidationError):
        RecordIRNRequest(ack_date="soon", **base)


def test_an_e_way_bill_generated_after_today_is_refused_but_its_validity_may_run_ahead():
    base = dict(ewb_number="341234567890")
    with pytest.raises(ValidationError) as caught:
        RecordEWBGeneratedRequest(ewb_date=TOMORROW, ewb_valid_upto="2026-10-12", **base)
    assert f"The e-way bill date {THE_SENTENCE}" in str(caught.value)
    ok = RecordEWBGeneratedRequest(ewb_date=TODAY, ewb_valid_upto="2026-10-12", **base)
    assert (ok.ewb_date, ok.ewb_valid_upto) == (TODAY, "2026-10-12"), "valid upto is a plan and is stored as the day it names"
    with pytest.raises(ValidationError):
        RecordEWBGeneratedRequest(ewb_date=TODAY, ewb_valid_upto="not a day", **base)


# ── the Form 15CA date ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("make", [lambda **kw: _bill(**kw), lambda **kw: PurchaseBillUpdateIn(**kw)], ids=["create", "update"])
def test_a_form_15ca_date_is_a_real_day_not_after_today(make):
    with pytest.raises(ValidationError) as caught:
        make(form_15ca_filed_on=TOMORROW)
    assert f"The Form 15CA date {THE_SENTENCE}" in str(caught.value)
    for bad in ["30/09/2026", "2026-02-30", "soon", "2026-10-081"]:
        with pytest.raises(ValidationError) as caught:
            make(form_15ca_filed_on=bad)
        assert "form_15ca_filed_on must be a date written YYYY-MM-DD." in str(caught.value)
    assert make(form_15ca_filed_on=TODAY).form_15ca_filed_on == TODAY
    assert make(form_15ca_filed_on="20260301").form_15ca_filed_on == "2026-03-01", "stored as the canonical day"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_form_15ca_date_on_a_new_bill_is_no_date(blank):
    assert _bill(form_15ca_filed_on=blank).form_15ca_filed_on is None


def test_a_form_15ca_date_not_sent_on_a_patch_stays_not_sent():
    assert PurchaseBillUpdateIn().form_15ca_filed_on is None
    assert PurchaseBillUpdateIn(form_15ca_filed_on=None).form_15ca_filed_on is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_form_15ca_date_on_a_patch_is_refused_not_dropped(blank):
    """The route reads a PATCH through `model_dump(exclude_none=True)`, so a blank read as absent is dropped and a success is reported for a date that was not cleared (found by the
    review of the sixteenth slice: before it, the blank reached the date column and was refused by the database)."""
    with pytest.raises(ValidationError) as caught:
        PurchaseBillUpdateIn(form_15ca_filed_on=blank)
    assert "form_15ca_filed_on must be a date written YYYY-MM-DD." in str(caught.value)


def test_the_purchase_bill_patch_reads_its_body_through_the_model_that_judges_the_15ca_date():
    import inspect

    import routers.purchase_bills

    assert inspect.signature(routers.purchase_bills.update_purchase_bill).parameters["data"].annotation is PurchaseBillUpdateIn

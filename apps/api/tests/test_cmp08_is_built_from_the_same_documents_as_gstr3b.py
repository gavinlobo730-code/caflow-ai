"""GST-25: CMP-08 is built from the same documents as GSTR-3B, never a second
pipeline.

`services.gst_return_service.cmp08_statement` reuses `outward_turnover` for
row 1 (the identical figure Rule 42/43 already read off the SAME outward
document list) and the same reverse-charge filter over `_posted_bills` that
Table 3.1(d) reads for row 2 — so a composition dealer's quarterly statement
and an ordinary registration's GSTR-3B cannot disagree about what was
supplied or what was received under reverse charge. `domain/gst/composition.py`
does the arithmetic; this only checks that the two fetches feed it correctly
and that a non-composition registration is refused.
"""
from __future__ import annotations

import pytest

import services.gst_return_service as grs
import services.client_gst_registration_service as client_gst_registration_service
from domain.gst import registrations as reg

FIRM, CLIENT, PERIOD = "firm-1", "client-1", "052026"


def _registration(**over):
    base = dict(gstin="27AAAAA0000A1Z5", state_code="27",
               registration_type=reg.COMPOSITION,
               filing_frequency=reg.MONTHLY, is_primary=True,
               composition_category="manufacturer_trader")
    base.update(over)
    return reg.Registration(**base)


def _sale(value):
    return {"id": "i1", "customer_id": None, "taxable_amount_paise": value,
           "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0,
           "supply_type": "taxable", "is_reverse_charge": False,
           "is_interstate": False, "supply_state_code": "27"}


def _bill(taxable, igst=0, cgst=0, sgst=0, cess=0, rcm=True):
    return {"id": "b1", "vendor_id": "v1", "bill_no": "B1",
           "bill_date": "2026-05-10", "status": "received",
           "taxable_amount_paise": taxable, "igst_paise": igst,
           "cgst_paise": cgst, "sgst_paise": sgst, "cess_paise": cess,
           "is_reverse_charge": rcm, "cancelled_at": None}


@pytest.fixture
def books(monkeypatch):
    rows: dict = {"sales": [], "bills": []}
    monkeypatch.setattr(grs, "_posted_sales", lambda *a: rows["sales"])
    monkeypatch.setattr(grs, "_bank_lines_declaring_gst", lambda *a: [])
    monkeypatch.setattr(grs, "_disposals_declaring_gst", lambda *a: [])
    monkeypatch.setattr(grs, "_issued_credit_notes", lambda *a: [])
    monkeypatch.setattr(grs, "_issued_sales_debit_notes", lambda *a: [])
    monkeypatch.setattr(grs, "_customers_for_3b", lambda *a: {})
    monkeypatch.setattr(grs, "_classification_by_parent_invoice",
                        lambda db, firm, notes: {})
    monkeypatch.setattr(grs, "_posted_bills", lambda *a: rows["bills"])
    return rows


def _resolve_as(monkeypatch, registration):
    monkeypatch.setattr(
        client_gst_registration_service, "resolve",
        lambda db, firm_id, client_id, gstin=None: registration)


def test_row1_is_outward_turnovers_own_total(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    books["sales"] = [_sale(10_00_000_00)]
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert out["outward_supplies"]["taxable_value_paise"] == 10_00_000_00
    assert out["outward_supplies"]["cgst_paise"] == 5_000_00
    assert out["outward_supplies"]["sgst_paise"] == 5_000_00
    assert out["outward_supplies"]["igst_paise"] == 0
    assert out["rate_bps"] == 100


def test_row2_is_the_same_rcm_bills_3_1d_reads(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    books["bills"] = [_bill(50_000_00, igst=9_000_00)]
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert out["inward_rcm_supplies"]["taxable_value_paise"] == 50_000_00
    assert out["inward_rcm_supplies"]["igst_paise"] == 9_000_00


def test_a_non_rcm_bill_is_not_counted(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    books["bills"] = [_bill(50_000_00, cgst=4_500_00, sgst=4_500_00, rcm=False)]
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert out["inward_rcm_supplies"]["taxable_value_paise"] == 0


def test_row3_is_row1_plus_row2(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    books["sales"] = [_sale(5_00_000_00)]
    books["bills"] = [_bill(1_00_000_00, igst=18_000_00)]
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert (out["tax_paid"]["taxable_value_paise"]
           == out["outward_supplies"]["taxable_value_paise"]
           + out["inward_rcm_supplies"]["taxable_value_paise"])
    assert (out["tax_paid"]["tax_paise"]
           == out["outward_supplies"]["tax_paise"]
           + out["inward_rcm_supplies"]["tax_paise"])


def test_a_regular_registration_is_refused(books, monkeypatch):
    _resolve_as(monkeypatch, _registration(registration_type=reg.REGULAR,
                                           composition_category=None))
    with pytest.raises(ValueError, match="regular"):
        grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)


def test_a_missing_category_names_a_gap_and_still_answers(books, monkeypatch):
    _resolve_as(monkeypatch, _registration(composition_category=None))
    books["sales"] = [_sale(1_00_000_00)]
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert out["rate_bps"] is None
    assert any("composition category" in g.lower() for g in out["gaps"])


def test_any_month_of_the_quarter_resolves_to_the_same_period(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    out_may = grs.cmp08_statement(None, FIRM, CLIENT, "052026")
    out_jun = grs.cmp08_statement(None, FIRM, CLIENT, "062026")
    assert out_may["period"] == out_jun["period"] == "042026"
    assert out_may["quarter"] == "Q1"
    assert out_may["financial_year"] == "2026-27"


def test_interest_is_the_callers_own_figure(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD, interest_paise=500_00)
    assert out["interest_paise"] == 500_00


def test_verified_is_false_and_travels_onto_the_response(books, monkeypatch):
    _resolve_as(monkeypatch, _registration())
    out = grs.cmp08_statement(None, FIRM, CLIENT, PERIOD)
    assert out["composition_rates_verified"] is False

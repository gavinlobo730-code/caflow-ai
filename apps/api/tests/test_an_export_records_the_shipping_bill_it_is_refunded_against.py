"""
An export declares the shipping bill it is refunded against.

WHAT WAS WRONG
    domain/gst/gstr1_builder._build_exp built GSTR-1 Table 6A with

        "sbpcode": "", "sbnum": "", "sbdt": ""

    as LITERALS. Not a bug in the builder: client_sales_invoices had nowhere to
    record them. grep over migrations/, models/ and services/ for shipping_bill
    or port_code found NOTHING. So every export this software has ever prepared
    declared an empty shipping bill, and no CA could have filled it in.

    On an export made ON PAYMENT of IGST that is the refund. CGST Rule 96(1)
    makes the shipping bill itself the application, and the refund is granted by
    MATCHING the Table 6A entry against what ICEGATE holds for that shipping
    bill. With no number and no date there is nothing to match.

    Under an LUT or bond (Rule 89) the refund is claimed by a separate
    application, so a missing shipping bill does not break a matching that never
    happens — which is why the GAP below is scoped to the with-payment case. The
    field is still emitted whenever it is recorded.

THE ONE NON-OBVIOUS PART
    These are editable AFTER the invoice is issued. Customs issues the shipping
    bill after the invoice, often days later when the goods actually ship. Frozen
    with the rest of the Rule 46 content at issue, there would be no moment at
    which a CA could ever record them and Table 6A would carry three empty
    strings for a new reason. None of the three is a Rule 46 particular of the
    tax invoice — they are customs's reference for the consignment — so CGST
    s.34 is untouched.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import InvoiceForGSTR1, build_gstr1
from models.invoices import SalesInvoiceIn, SalesInvoiceUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

GSTIN = "27AAAAA0000A1Z5"
PERIOD = "052025"
FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}


def _export(ref: str, category: GSTInvoiceCategory, **over) -> InvoiceForGSTR1:
    f = dict(
        id=ref, transaction_type="sales_invoice", reference_no=ref,
        transaction_date="2025-05-10", party_gstin=None, party_name="Overseas Ltd",
        place_of_supply="96", is_interstate=True,
        taxable_amount_paise=100_000_00, cgst_paise=0, sgst_paise=0,
        igst_paise=18_000_00 if category is GSTInvoiceCategory.EXP_WP else 0,
        cess_paise=0, is_reverse_charge=False, invoice_type="Regular",
        supply_type="zero_rated", gst_invoice_category=category,
        original_invoice_ref=None, original_invoice_date=None, lines=[])
    f.update(over)
    return InvoiceForGSTR1(**f)


def _built(invoices):
    return build_gstr1(invoices, GSTIN, PERIOD)


def _first_export(payload) -> dict:
    return payload["exp"][0]["inv"][0]


# ── What Table 6A carries ───────────────────────────────────────────────────

def test_a_recorded_shipping_bill_reaches_the_payload():
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP,
                          shipping_bill_no="7654321",
                          shipping_bill_date="2025-05-14",
                          port_code="INMAA1")])
    row = _first_export(out.payload)
    assert row["sbnum"] == "7654321"
    assert row["sbpcode"] == "INMAA1"


def test_the_shipping_bill_date_is_formatted_the_way_gstn_wants_it():
    """DD-MM-YYYY at the payload boundary, YYYY-MM-DD everywhere else — the
    same split money takes between paise and rupees."""
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP,
                          shipping_bill_no="7654321",
                          shipping_bill_date="2025-05-14",
                          port_code="INMAA1")])
    assert _first_export(out.payload)["sbdt"] == "14-05-2025"


def test_nothing_recorded_is_an_empty_field_not_an_invented_one():
    """The portal accepts an export declared before the shipping bill exists;
    the details are furnished later by amendment. What is not acceptable is
    doing it silently, which is what the gap below is for."""
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WOP)])
    row = _first_export(out.payload)
    assert row["sbnum"] == "" and row["sbdt"] == "" and row["sbpcode"] == ""


# ── The gap, and its scope ──────────────────────────────────────────────────

def test_an_export_with_payment_and_no_shipping_bill_is_reported():
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP)])
    assert [g["reference_no"] for g in out.gaps] == ["EXP-1"]
    assert out.gaps[0]["kind"] == "EXP_WP"
    assert "Rule 96" in out.gaps[0]["reason"]
    assert "ICEGATE" in out.gaps[0]["reason"], (
        "the CA needs to know WHAT the missing number is matched against")


def test_a_complete_with_payment_export_reports_nothing():
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP,
                          shipping_bill_no="7654321",
                          shipping_bill_date="2025-05-14",
                          port_code="INMAA1")])
    assert out.gaps == []


def test_a_number_with_no_date_is_still_incomplete():
    """Rule 96 matches on both. Half a reference matches nothing."""
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP,
                          shipping_bill_no="7654321")])
    assert [g["reference_no"] for g in out.gaps] == ["EXP-1"]


def test_an_export_under_an_lut_is_not_reported():
    """Rule 89 claims the refund by application, so there is no matching to
    break. Reporting it anyway would be noise on the commoner case, and noise
    is how a real warning stops being read."""
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WOP)])
    assert out.gaps == []


def test_the_port_code_alone_does_not_satisfy_it():
    out = _built([_export("EXP-1", GSTInvoiceCategory.EXP_WP, port_code="INMAA1")])
    assert [g["reference_no"] for g in out.gaps] == ["EXP-1"]


# ── The port code a human types ─────────────────────────────────────────────

def _invoice_in(**over):
    body = dict(client_id=CLIENT, customer_id="CUST", invoice_no="INV-1",
                invoice_date="2025-05-10",
                lines=[{"description": "svc", "quantity": 1, "rate_paise": 100_000_00,
                        "gst_rate_percent": 18.0, "service_catalogue_id": "SVC-1"}])
    body.update(over)
    return SalesInvoiceIn(**body)


def test_a_port_code_is_upper_cased():
    assert _invoice_in(port_code="inmaa1").port_code == "INMAA1"


def test_a_port_code_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError) as e:
        _invoice_in(port_code="INMAA")
    assert "6 characters" in str(e.value)


def test_a_blank_port_code_is_absence_not_a_value():
    assert _invoice_in(port_code="   ").port_code is None
    assert _invoice_in().port_code is None


def test_membership_is_deliberately_not_checked():
    """The ICEGATE list is theirs and grows. A pattern written from memory here
    would refuse a real port with no way round it, and a refused export is
    worse than an unverified port code — the CA reads the payload before it
    goes anywhere."""
    assert _invoice_in(port_code="ZZZZZZ").port_code == "ZZZZZZ"


# ── Recordable after issue, which is the only time it exists ────────────────

@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [si])
    d.seed("firms", {"id": FIRM, "name": "F1", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    return d


def _issued(db):
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": CLIENT, "status": "issued",
        "invoice_date": "2025-05-10", "invoice_no": "INV-1",
        "supply_type": "zero_rated", "supply_state_code": "96",
    })


def test_the_shipping_bill_can_be_recorded_on_an_issued_invoice(db):
    _issued(db)
    res = si.update_invoice("INV1", SalesInvoiceUpdateIn(
        shipping_bill_no="7654321", shipping_bill_date="2025-05-14",
        port_code="INMAA1"), current_user=USER)
    assert res["success"]
    row = db.table("client_sales_invoices").select("*").eq("id", "INV1").execute().data[0]
    assert row["shipping_bill_no"] == "7654321"
    assert row["port_code"] == "INMAA1"


def test_the_rest_of_the_invoice_is_still_frozen(db):
    """The exception is exactly three fields wide. If it were wider this would
    be a hole in CGST s.34, not an accommodation of how customs works."""
    _issued(db)
    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV1", SalesInvoiceUpdateIn(invoice_date="2025-05-11"),
                          current_user=USER)
    assert e.value.status_code == 422
    assert "issued invoice" in e.value.detail

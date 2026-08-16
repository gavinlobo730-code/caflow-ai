"""
GSTR-1 classifies an invoice from what the invoice says, not from a default.

WHAT WAS WRONG
    domain/gst/classifier.py routes a supply to its GSTR-1 table — NIL_EXEMPT,
    EXP_WP/EXP_WOP, B2B, B2CL, B2CS — citing CGST §23, §16(1)(a), §16(3), §37
    and Rule 59(2). It is complete and correct, and it was never told the truth.

    gst_return_service builds its input from client_sales_invoices, which had
    none of the three columns the classifier branches on, so every read fell
    back to a default:

        supply_type       column absent -> "taxable"   for every invoice
        invoice_type      hardcoded     -> "Regular"   for every invoice
        is_reverse_charge column absent -> False       for every invoice

    Those are filing errors. A nil-rated or exempt supply was declared as
    taxable, inflating outward taxable turnover. An SEZ supply or deemed export
    was declared as ordinary B2B, leaving the recipient's CGST §16(3) refund
    claim nothing to match against. A reverse-charge supply was unflagged, so
    the return said the supplier owed tax the recipient was liable for.

    One export path worked by accident: the classifier also treats
    place_of_supply '96' as an export, and that column did exist.

    Migration 268 adds the three columns; this pins that the values reach the
    classifier rather than being defaulted away again.
"""
from __future__ import annotations

import pytest

import routers.sales_invoices as si
import services.gst_return_service as grs
from models.invoices import SalesInvoiceIn, InvoiceLineIn
from domain.gst.classifier import classify_transaction, TransactionForClassification
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z5"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [si, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                         "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True})
    d.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                "name": "Materials", "kind": "good"})
    seed_standard_coa(d, FIRM, "CLI")
    return d


def _category(**invoice_fields) -> str:
    """The GSTR-1 table this invoice lands in, via the real classifier."""
    row = {
        "id": "INV", "supply_type": "taxable", "invoice_type": "Regular",
        "is_interstate": False, "taxable_amount_paise": 100_000_00,
        **invoice_fields,
    }
    txn = TransactionForClassification(
        id=row["id"], transaction_type="sales_invoice",
        party_gstin=row.get("party_gstin", "27BBBBB1111B1Z5"),
        is_interstate=bool(row["is_interstate"]),
        taxable_amount_paise=int(row["taxable_amount_paise"]),
        supply_type=row["supply_type"], invoice_type=row["invoice_type"],
        place_of_supply=row.get("place_of_supply", "27"),
    )
    return classify_transaction(txn).value


# ── the classifier was always right; these are the answers it gives ──────────

def test_an_ordinary_domestic_sale_is_b2b():
    assert _category() == "B2B"


def test_an_sez_supply_without_payment_is_zero_rated_not_b2b():
    """CGST §16(3): supply to an SEZ under LUT/bond. Declared as B2B, the
    recipient has nothing to match a refund claim against."""
    assert _category(invoice_type="SEZ_without_payment") == "EXP_WOP"


def test_an_sez_supply_with_payment_of_igst_is_its_own_table():
    assert _category(invoice_type="SEZ_with_payment") == "EXP_WP"


def test_a_deemed_export_is_zero_rated():
    assert _category(invoice_type="Deemed_export") == "EXP_WOP"


@pytest.mark.parametrize("supply_type", ["nil_rated", "exempt", "non_gst"])
def test_nil_exempt_and_non_gst_supplies_are_not_taxable(supply_type):
    """CGST §23 / GSTR-1 table 8. Declared as taxable, these inflate outward
    taxable turnover in the return."""
    assert _category(supply_type=supply_type) == "NIL_EXEMPT"


def test_the_b2cl_threshold_still_applies_to_an_unregistered_buyer():
    """Rule 59(2) — interstate, above 2.5 lakh, no GSTIN. Unchanged by 268;
    here so a regression in the untouched path is visible."""
    assert _category(party_gstin=None, is_interstate=True,
                     taxable_amount_paise=300_000_00) == "B2CL"
    assert _category(party_gstin=None, is_interstate=True,
                     taxable_amount_paise=200_000_00) == "B2CS"


# ── the wiring: does the invoice's own value reach the classifier? ───────────

def _seed_invoice(db, **fields):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "invoice_no": "INV-1", "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": 100_000_00, "cgst_paise": 0, "sgst_paise": 0,
        "igst_paise": 0, "total_paise": 100_000_00, "is_interstate": False,
        "supply_state_code": "27", "deleted_at": None,
        **fields,
    })


def _payload(db) -> dict:
    """The GSTN payload gstr1_from_books actually produces."""
    return grs.gstr1_from_books(db, FIRM, "CLI", "062025", GSTIN)["payload"]


def _invoice_numbers(section) -> set[str]:
    return {inv["inum"] for group in (section or []) for inv in group.get("inv", [])}


def test_an_sez_invoice_lands_in_the_export_table_not_b2b(db):
    """THE test for this change, and the one the first draft of this file got
    wrong. An earlier version built the classifier's input itself and asserted
    on that — which passes whether or not gst_return_service reads the column,
    so restoring the hardcoded "Regular" failed nothing. This goes through
    gstr1_from_books and looks at the payload that would be filed.
    """
    _seed_invoice(db, invoice_no="INV-SEZ", invoice_type="SEZ_without_payment")
    _seed_invoice(db, invoice_no="INV-REG", invoice_type="Regular")

    payload = _payload(db)

    assert _invoice_numbers(payload.get("exp")) == {"INV-SEZ"}, \
        "the SEZ supply was not declared as zero-rated"
    assert _invoice_numbers(payload.get("b2b")) == {"INV-REG"}, \
        "the SEZ supply was filed as an ordinary B2B invoice"
    assert payload["exp"][0]["exp_typ"] == "WOPAY", "LUT/bond, not with payment of IGST"


def test_an_sez_supply_with_payment_is_declared_as_such(db):
    _seed_invoice(db, invoice_no="INV-SEZP", invoice_type="SEZ_with_payment")

    payload = _payload(db)

    assert _invoice_numbers(payload.get("exp")) == {"INV-SEZP"}
    assert payload["exp"][0]["exp_typ"] == "WPAY"


def test_a_nil_rated_supply_does_not_appear_as_a_taxable_b2b_invoice(db):
    """CGST §23. Declared as taxable it inflates outward taxable turnover."""
    _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated")

    payload = _payload(db)

    assert "INV-NIL" not in _invoice_numbers(payload.get("b2b"))


def test_an_ordinary_invoice_is_unchanged_by_all_of_this(db):
    """Every existing invoice defaults to Regular/taxable, so the return for a
    client with no SEZ or exempt supplies must look exactly as it did."""
    _seed_invoice(db, invoice_no="INV-PLAIN")

    payload = _payload(db)

    assert _invoice_numbers(payload.get("b2b")) == {"INV-PLAIN"}
    assert not payload.get("exp")


def test_creating_an_invoice_records_the_classification(db):
    """The API has to carry the fields through, or the columns stay at their
    defaults and nothing above this line can ever fire in production."""
    resp = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_no="INV-SEZ",
        invoice_date="2025-06-10",
        lines=[InvoiceLineIn(description="Export goods", quantity=1, rate_paise=100_000_00,
                              gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
        supply_type="zero_rated", invoice_type="SEZ_without_payment",
    ), current_user=CALLER)

    assert resp["success"] is True
    row = [r for r in db.rows("client_sales_invoices") if r["invoice_no"] == "INV-SEZ"][0]
    assert row["supply_type"] == "zero_rated"
    assert row["invoice_type"] == "SEZ_without_payment"
    assert row["is_reverse_charge"] is False


def test_an_invoice_created_without_them_is_an_ordinary_taxable_sale(db):
    """The default has to stay what the code assumed before 268, or every
    existing invoice changes meaning."""
    resp = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_no="INV-PLAIN",
        invoice_date="2025-06-10",
        lines=[InvoiceLineIn(description="Goods", quantity=1, rate_paise=100_000_00,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), current_user=CALLER)

    assert resp["success"] is True
    row = [r for r in db.rows("client_sales_invoices") if r["invoice_no"] == "INV-PLAIN"][0]
    assert row["supply_type"] == "taxable"
    assert row["invoice_type"] == "Regular"
    assert row["is_reverse_charge"] is False


def test_reverse_charge_is_carried_through(db):
    """CGST §9(3)/(4) — the recipient is liable. Unflagged, the return says the
    supplier owes tax somebody else pays."""
    resp = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_no="INV-RCM",
        invoice_date="2025-06-10",
        lines=[InvoiceLineIn(description="Service", quantity=1, rate_paise=50_000_00,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
        is_reverse_charge=True,
    ), current_user=CALLER)

    assert resp["success"] is True
    row = [r for r in db.rows("client_sales_invoices") if r["invoice_no"] == "INV-RCM"][0]
    assert row["is_reverse_charge"] is True


def test_the_classification_cannot_be_changed_on_an_issued_invoice():
    """These are CGST Rule 46 tax-invoice content, not soft fields. Changing
    which GSTR-1 table an issued invoice belongs to needs a credit note
    (CGST §34), not a silent edit — so they must stay outside the soft set."""
    assert "supply_type" not in si._SOFT_UPDATE_FIELDS
    assert "invoice_type" not in si._SOFT_UPDATE_FIELDS
    assert "is_reverse_charge" not in si._SOFT_UPDATE_FIELDS

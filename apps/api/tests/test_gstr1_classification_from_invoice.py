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
        # Rule 59(4) compares the invoice VALUE against a limit that depends on
        # the invoice date.
        invoice_value_paise=(int(row["taxable_amount_paise"])
                             + int(row.get("cgst_paise") or 0)
                             + int(row.get("sgst_paise") or 0)
                             + int(row.get("igst_paise") or 0)
                             + int(row.get("cess_paise") or 0)),
        transaction_date=row.get("invoice_date") or "2026-04-10",
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
    """Rule 59(4) — inter-state, no GSTIN, invoice value above the limit.

    This asserted that Rs 2,00,000 was B2CS, which was true until 31 July 2024.
    Notification 12/2024-Central Tax substituted "one lakh rupees" for "two and
    a half lakh rupees" in Rule 59(4) with effect from 1 August 2024, so on any
    current return that invoice is B2CL and belongs in Table 5 invoice-wise.
    The test did not merely miss the change; it pinned the superseded figure.
    """
    assert _category(party_gstin=None, is_interstate=True,
                     taxable_amount_paise=300_000_00) == "B2CL"
    assert _category(party_gstin=None, is_interstate=True,
                     taxable_amount_paise=200_000_00) == "B2CL"
    assert _category(party_gstin=None, is_interstate=True,
                     taxable_amount_paise=50_000_00) == "B2CS"


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



# ── Task #163: a note declares what the invoice it adjusts declared ──────────
#
# CGST §34: a credit or debit note is always issued "in relation to" a specific
# original tax invoice. It adjusts that invoice's value or tax and has no
# standing to redeclare the supply — GSTR-1 table 9B (CDNR) requires the
# original invoice number and date on every note for the same reason.
#
# The note tables carry none of migration 268's three columns, so every note
# read back taxable / Regular / no-reverse-charge regardless of what it was
# adjusting. In GSTR-3B that is a live misstatement: gstr3b_computer buckets
# outward supply on supply_type (3.1(a) taxable vs 3.1(c) nil/exempt), so a
# credit note against a nil-rated invoice reduced TAXABLE outward supply — a
# figure it should never have touched.

def _seed_credit_note(db, **fields):
    return db.seed("credit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "credit_note_no": "CN-1", "credit_note_date": "2025-06-20", "status": "issued",
        "taxable_amount_paise": 10_000_00, "cgst_paise": 0, "sgst_paise": 0,
        "igst_paise": 0, "total_paise": 10_000_00, "is_interstate": False,
        "supply_state_code": "27", "deleted_at": None,
        **fields,
    })


def _3b(db) -> dict:
    return grs.gstr3b_from_books(db, FIRM, "CLI", "062025", GSTIN)


def _sup(out: dict, key: str) -> int:
    """A table 3.1 outward bucket, in paise."""
    return int((out["working"]["outward"] or {})[key] or 0)


def test_a_credit_note_against_a_nil_rated_invoice_leaves_taxable_supply_alone(db):
    """THE test for #163. Before the fix this note reduced 3.1(a) taxable
    outward supply; it belongs against 3.1(c) nil/exempt (CGST §23)."""
    inv = _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated",
                        taxable_amount_paise=100_000_00)
    _seed_credit_note(db, credit_note_no="CN-NIL", sales_invoice_id=inv["id"],
                      taxable_amount_paise=10_000_00)

    out = _3b(db)

    assert _sup(out, "taxable_value_paise") == 0, \
        "a nil-rated credit note reduced TAXABLE outward supply"
    assert _sup(out, "nil_exempt_paise") == 100_000_00 - 10_000_00, \
        "the credit did not net against nil/exempt supply"


def test_a_credit_note_against_an_exempt_invoice_nets_against_exempt(db):
    inv = _seed_invoice(db, invoice_no="INV-EX", supply_type="exempt",
                        taxable_amount_paise=50_000_00)
    _seed_credit_note(db, credit_note_no="CN-EX", sales_invoice_id=inv["id"],
                      taxable_amount_paise=5_000_00)

    out = _3b(db)

    assert _sup(out, "taxable_value_paise") == 0
    assert _sup(out, "nil_exempt_paise") == 45_000_00


def test_an_ordinary_credit_note_still_reduces_taxable_supply(db):
    """No-regression guard — must hold before and after. Inheriting must not
    stop an ordinary credit note doing what it always did."""
    inv = _seed_invoice(db, invoice_no="INV-REG", taxable_amount_paise=100_000_00)
    _seed_credit_note(db, credit_note_no="CN-REG", sales_invoice_id=inv["id"],
                      taxable_amount_paise=10_000_00)

    out = _3b(db)

    assert _sup(out, "taxable_value_paise") == 100_000_00 - 10_000_00


def test_the_parent_invoice_may_predate_the_period_being_filed(db):
    """A June note routinely adjusts an April invoice. Resolving the parent
    from the period's own invoices would miss it — it is fetched by id."""
    inv = _seed_invoice(db, invoice_no="INV-APR", invoice_date="2025-04-05",
                        supply_type="nil_rated", taxable_amount_paise=80_000_00)
    _seed_credit_note(db, credit_note_no="CN-CROSS", sales_invoice_id=inv["id"],
                      taxable_amount_paise=8_000_00)

    out = _3b(db)   # period 062025 — the parent invoice is outside it

    assert _sup(out, "taxable_value_paise") == 0, \
        "the out-of-period parent invoice was not resolved"


def test_an_unlinked_note_keeps_the_defaults_rather_than_guessing(db):
    """§34 expects a reference. A note without one is already an exception the
    CA stands behind; inventing a classification would hide it."""
    _seed_credit_note(db, credit_note_no="CN-ORPHAN", sales_invoice_id=None,
                      taxable_amount_paise=7_000_00)

    out = _3b(db)

    assert _sup(out, "taxable_value_paise") == -7_000_00, \
        "an unlinked note should keep the taxable default, not vanish"


# ── Task #164: table 8 exists, so nil/exempt supply is actually filed ────────
#
# classify_transaction routes nil_rated / exempt / non_gst to NIL_EXEMPT ahead
# of every other check, and gstr1_builder consumed that category nowhere — so
# the supply was computed, categorised, and then dropped. A firm with exempt
# turnover filed a GSTR-1 that did not mention it, and nothing on the summary
# said so either.
#
# GSTN table 8 shape: nil.inv[] of {sply_ty, nil_amt, expt_amt, ngsup_amt},
# where sply_ty is INTRB2B / INTRB2C / INTRAB2B / INTRAB2C. Note the prefixes:
# INTR* is INTER-state, INTRA* is INTRA-state.

def _nil_rows(payload) -> list[dict]:
    return ((payload.get("nil") or {}).get("inv")) or []


def _nil_row(payload, sply_ty: str) -> dict:
    rows = [r for r in _nil_rows(payload) if r["sply_ty"] == sply_ty]
    assert rows, f"no table 8 row for {sply_ty}; got {[r['sply_ty'] for r in _nil_rows(payload)]}"
    return rows[0]


def test_a_nil_rated_supply_is_declared_in_table_8(db):
    """It used to vanish from the payload entirely."""
    _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated",
                  taxable_amount_paise=100_000_00)

    payload = _payload(db)

    row = _nil_row(payload, "INTRAB2B")     # intra-state, registered buyer
    assert row["nil_amt"] == 100_000.00
    assert row["expt_amt"] == 0 and row["ngsup_amt"] == 0


def test_exempt_and_non_gst_are_separate_columns_not_one_bucket(db):
    """CGST §23 / §11 — three distinct declarations. Folding them together
    would misdeclare exempt turnover as nil-rated."""
    _seed_invoice(db, invoice_no="INV-EX", supply_type="exempt",
                  taxable_amount_paise=40_000_00)
    _seed_invoice(db, invoice_no="INV-NG", supply_type="non_gst",
                  taxable_amount_paise=25_000_00)

    row = _nil_row(_payload(db), "INTRAB2B")

    assert row["expt_amt"] == 40_000.00
    assert row["ngsup_amt"] == 25_000.00
    assert row["nil_amt"] == 0


def test_interstate_and_intrastate_are_different_rows(db):
    """INTR* vs INTRA* — the confusable half of the GSTN schema."""
    _seed_invoice(db, invoice_no="INV-INTRA", supply_type="nil_rated",
                  is_interstate=False, taxable_amount_paise=10_000_00)
    _seed_invoice(db, invoice_no="INV-INTER", supply_type="nil_rated",
                  is_interstate=True, taxable_amount_paise=30_000_00)

    payload = _payload(db)

    assert _nil_row(payload, "INTRAB2B")["nil_amt"] == 10_000.00
    assert _nil_row(payload, "INTRB2B")["nil_amt"] == 30_000.00


def test_the_summary_counts_nil_supplies_so_a_reviewing_ca_can_see_them(db):
    _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated")

    out = grs.gstr1_from_books(db, FIRM, "CLI", "062025", GSTIN)

    assert out["summary"]["counts"]["nil_exempt"] == 1


def test_an_ordinary_taxable_invoice_creates_no_table_8_row(db):
    """No-regression guard: table 8 must stay absent for a return with no
    nil/exempt supply at all."""
    _seed_invoice(db, invoice_no="INV-REG")

    assert _nil_rows(_payload(db)) == []


# ── #163 + #164 together: the note now lands somewhere real ─────────────────

def test_a_credit_note_against_a_nil_invoice_nets_within_table_8(db):
    """The whole point of doing these two together. Inheriting alone moved the
    note into a table that did not exist; now it nets against the nil supply it
    actually adjusts (CGST §34), instead of reducing taxable turnover."""
    inv = _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated",
                        taxable_amount_paise=100_000_00)
    _seed_credit_note(db, credit_note_no="CN-NIL", sales_invoice_id=inv["id"],
                      taxable_amount_paise=10_000_00)

    payload = _payload(db)

    assert _nil_row(payload, "INTRAB2B")["nil_amt"] == 90_000.00, \
        "the credit note did not net against the nil supply it adjusts"
    cdnr_notes = {n["nt_num"] for g in (payload.get("cdnr") or []) for n in g.get("nt", [])}
    assert "CN-NIL" not in cdnr_notes, \
        "a nil-rated credit note was still declared as an ordinary 9B adjustment"


# ── Task #165: table 12 reports real HSN codes, not one "OTH" row ────────────
#
# gstr1_from_books built every InvoiceForGSTR1 with lines=[], so
# _build_hsn_summary always took its no-lines fallback and filed the whole
# return as a single row — hsn_sc "OTH", desc "Other", qty 0 — while the line
# rows behind it all carried an HSN/SAC code.
#
# _required_hsn_digits already encodes the rule (6 digits above ₹5 crore,
# 4 above ₹1.5 crore, optional below). It was computing the right answer and
# had nothing to truncate.

def _seed_line(db, invoice_id, **fields):
    return db.seed("client_sales_invoice_lines", {
        "sales_invoice_id": invoice_id, "description": "Steel bars",
        "hsn_sac": "72142090", "quantity": 2, "unit": "KGS",
        "rate_paise": 50_000_00, "taxable_amount_paise": 100_000_00,
        "gst_rate_bps": 1800, "cgst_paise": 9_000_00, "sgst_paise": 9_000_00,
        "igst_paise": 0, "line_total_paise": 118_000_00, "sort_order": 0,
        **fields,
    })


def _hsn_rows(payload) -> list[dict]:
    return ((payload.get("hsn") or {}).get("data")) or []


def test_the_hsn_summary_reports_the_real_code_not_OTH(db):
    """THE test for #165. Before this, every return filed one 'OTH' row."""
    inv = _seed_invoice(db, invoice_no="INV-1", cgst_paise=9_000_00, sgst_paise=9_000_00)
    _seed_line(db, inv["id"])

    rows = _hsn_rows(_payload(db))

    codes = {r["hsn_sc"] for r in rows}
    assert "OTH" not in codes, "the HSN summary still fell back to the OTH row"
    assert codes == {"72142090"}
    assert rows[0]["desc"] == "Steel bars"
    assert rows[0]["uqc"] == "KGS"
    assert rows[0]["qty"] == 2.0


def test_line_tax_and_value_reach_the_hsn_row(db):
    inv = _seed_invoice(db, invoice_no="INV-1", cgst_paise=9_000_00, sgst_paise=9_000_00)
    _seed_line(db, inv["id"])

    row = _hsn_rows(_payload(db))[0]

    # Assert the CODE too. The no-lines fallback aggregates the same totals at
    # invoice level, so checking only the money passes with or without the fix
    # — it has to be pinned to the row the line actually produced.
    assert row["hsn_sc"] == "72142090"
    assert row["txval"] == 100_000.00
    assert row["camt"] == 9_000.00 and row["samt"] == 9_000.00
    assert row["val"] == 118_000.00     # txval + all tax heads, cess included


def test_lines_sharing_an_hsn_code_aggregate_into_one_row(db):
    inv = _seed_invoice(db, invoice_no="INV-1")
    _seed_line(db, inv["id"], sort_order=0, taxable_amount_paise=100_000_00, quantity=2)
    _seed_line(db, inv["id"], sort_order=1, taxable_amount_paise=40_000_00, quantity=1)
    _seed_line(db, inv["id"], sort_order=2, hsn_sac="998314",
               description="Consulting", unit="OTH",
               taxable_amount_paise=25_000_00, quantity=1)

    rows = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}

    assert set(rows) == {"72142090", "998314"}
    assert rows["72142090"]["txval"] == 140_000.00
    assert rows["72142090"]["qty"] == 3.0
    assert rows["998314"]["txval"] == 25_000.00


def test_a_nil_rated_supply_still_appears_in_the_hsn_summary(db):
    """Table 12 covers ALL outward supplies — a nil supply belongs here with
    zero tax, as well as in table 8. It is not either/or."""
    inv = _seed_invoice(db, invoice_no="INV-NIL", supply_type="nil_rated")
    _seed_line(db, inv["id"], hsn_sac="10011000", description="Wheat",
               gst_rate_bps=0, cgst_paise=0, sgst_paise=0)

    payload = _payload(db)

    row = {r["hsn_sc"]: r for r in _hsn_rows(payload)}["10011000"]
    assert row["txval"] == 100_000.00
    assert row["camt"] == 0 and row["samt"] == 0
    assert (payload.get("nil") or {}).get("inv"), "table 8 lost the nil supply"


def test_an_invoice_with_no_lines_still_falls_back_rather_than_vanishing(db):
    """No-regression guard. Invoices predating line capture, and any row whose
    lines failed to load, must still be reported — as OTH, not dropped."""
    _seed_invoice(db, invoice_no="INV-NOLINES")

    rows = _hsn_rows(_payload(db))

    assert [r["hsn_sc"] for r in rows] == ["OTH"]
    assert rows[0]["txval"] == 100_000.00


def test_lines_are_matched_to_their_own_invoice(db):
    """A line must not leak into another invoice's HSN aggregation."""
    a = _seed_invoice(db, invoice_no="INV-A")
    b = _seed_invoice(db, invoice_no="INV-B")
    _seed_line(db, a["id"], hsn_sac="72142090", taxable_amount_paise=100_000_00)
    _seed_line(db, b["id"], hsn_sac="998314", taxable_amount_paise=25_000_00)

    rows = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}

    assert rows["72142090"]["txval"] == 100_000.00
    assert rows["998314"]["txval"] == 25_000.00


# ── Task #166: notes NET into the HSN summary instead of being skipped ───────
#
# _build_hsn_summary skipped every non-sales_invoice, so table 12 reported the
# period's outward supply GROSS while tables 4-9 reported it net of notes — the
# two halves of one return disagreeing about the same turnover, which is
# exactly what GSTN's totals validation flags.
#
# A credit note reduces the supply it adjusts and a sales debit note increases
# it (CGST §34), so both now carry a sign — value, tax and quantity alike.

def _seed_note_line(db, table, fk, note_id, **fields):
    return db.seed(table, {
        fk: note_id, "description": "Steel bars", "hsn_sac": "72142090",
        "quantity": 1, "unit": "KGS", "rate_paise": 10_000_00,
        "taxable_amount_paise": 10_000_00, "gst_rate_bps": 1800,
        "cgst_paise": 900_00, "sgst_paise": 900_00, "igst_paise": 0,
        "line_total_paise": 11_800_00, "sort_order": 0,
        **fields,
    })


def test_a_credit_note_reduces_the_hsn_row_it_adjusts(db):
    """THE test for #166. Table 12 used to ignore the note entirely and report
    the full ₹1,00,000 as if nothing had been credited back."""
    inv = _seed_invoice(db, invoice_no="INV-1", cgst_paise=9_000_00, sgst_paise=9_000_00)
    _seed_line(db, inv["id"])
    cn = _seed_credit_note(db, credit_note_no="CN-1", sales_invoice_id=inv["id"],
                           taxable_amount_paise=10_000_00)
    _seed_note_line(db, "credit_note_lines", "credit_note_id", cn["id"])

    row = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}["72142090"]

    assert row["txval"] == 90_000.00        # 100,000 - 10,000
    assert row["camt"] == 8_100.00          # 9,000 - 900
    assert row["samt"] == 8_100.00


def test_the_credited_quantity_comes_off_too(db):
    """Goods returned reduce the quantity supplied. An unsigned qty would
    overstate it while the value beside it netted correctly."""
    inv = _seed_invoice(db, invoice_no="INV-1")
    _seed_line(db, inv["id"], quantity=5)
    cn = _seed_credit_note(db, credit_note_no="CN-1", sales_invoice_id=inv["id"])
    _seed_note_line(db, "credit_note_lines", "credit_note_id", cn["id"], quantity=2)

    row = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}["72142090"]

    assert row["qty"] == 3.0


def test_a_sales_debit_note_adds_to_the_hsn_row(db):
    """CGST §34(3) — an undercharge correction increases the supply, so it
    moves table 12 the other way."""
    inv = _seed_invoice(db, invoice_no="INV-1")
    _seed_line(db, inv["id"])
    dn = db.seed("sales_debit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "debit_note_no": "DN-1", "debit_note_date": "2025-06-20", "status": "issued",
        "taxable_amount_paise": 5_000_00, "cgst_paise": 0, "sgst_paise": 0,
        "igst_paise": 0, "total_paise": 5_000_00, "is_interstate": False,
        "supply_state_code": "27", "sales_invoice_id": inv["id"], "deleted_at": None,
    })
    _seed_note_line(db, "sales_debit_note_lines", "debit_note_id", dn["id"],
                    taxable_amount_paise=5_000_00)

    row = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}["72142090"]

    assert row["txval"] == 105_000.00


def test_a_note_against_a_different_hsn_gets_its_own_row(db):
    """A credit note need not adjust every line of its invoice. It nets against
    the code it actually names."""
    inv = _seed_invoice(db, invoice_no="INV-1")
    _seed_line(db, inv["id"], hsn_sac="72142090", taxable_amount_paise=100_000_00)
    cn = _seed_credit_note(db, credit_note_no="CN-1", sales_invoice_id=inv["id"])
    _seed_note_line(db, "credit_note_lines", "credit_note_id", cn["id"],
                    hsn_sac="998314", description="Consulting",
                    taxable_amount_paise=4_000_00)

    rows = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}

    assert rows["72142090"]["txval"] == 100_000.00
    assert rows["998314"]["txval"] == -4_000.00


def test_an_invoice_with_no_note_is_unchanged(db):
    """No-regression guard — netting must not disturb the ordinary case."""
    inv = _seed_invoice(db, invoice_no="INV-1", cgst_paise=9_000_00, sgst_paise=9_000_00)
    _seed_line(db, inv["id"])

    row = {r["hsn_sc"]: r for r in _hsn_rows(_payload(db))}["72142090"]

    assert row["txval"] == 100_000.00 and row["qty"] == 2.0

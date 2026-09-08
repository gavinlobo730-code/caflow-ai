"""
The client's sales invoice names the CLIENT as supplier — not the CA practice.

`get_sales_invoice_pdf` loaded the FIRM (the tenant — the CA practice) and the
shared builder rendered that row as the supplier block under "TAX INVOICE
(Issued under Section 31, CGST Act 2017 read with Rule 46, CGST Rules 2017)".
The builder had been written for `fee_invoices`, where the practice really is
the supplier, and was reused verbatim for `client_sales_invoices`, where the
supplier is the CLIENT.

That document reached the client's customer on four paths — the Download PDF
button, the invoice email, the dunning chasers in collections_service, and the
client portal — all four through `get_sales_invoice_pdf`. The customer then
claimed input tax credit against a GSTIN that never made the supply, and could
not match it in GSTR-2B.

Three further Rule 46 defects in the same builder are covered here too:

  * SAC 998211 (legal and accounting services — the CA's OWN code) was printed
    on every line that carried no code of its own (Rule 46(g));
  * the printed rate was the constant 18, so a 5% invoice read "CGST @ 9% /
    SGST @ 9%" beside a 5% amount (Rule 46(l) — the rate actually charged);
  * the line table carried no quantity, unit, per-line rate or per-line tax
    (Rule 46(g)/(h)), never printed the place of supply (Rule 46(n)) and always
    stated "reverse charge basis: No" (Rule 46(p)).

Assertions read the rendered page text with pdfplumber, as
tests/test_invoice_pdf_line_items.py already does.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import pytest
import pdfplumber

from services.invoice_pdf_service import (
    build_invoice_pdf,
    build_sales_invoice_pdf,
    get_sales_invoice_pdf,
)


def _pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# The CA practice — the tenant. Never a party to a client's own sale.
FIRM = {
    "id": "firm-1", "name": "Mehta & Associates, Chartered Accountants",
    "gstin": "27AAAAA9999A1Z5", "pan": "AAAAA9999A", "address": "Fort, Mumbai",
}
# The selling client — the supplier of every invoice below.
CLIENT = {
    "id": "cli-1", "firm_id": "firm-1", "client_name": "Sunrise Traders",
    "legal_name": "Sunrise Traders LLP", "gstin": "27CCCCC7777C1Z1", "pan": "CCCCC7777C",
    "address_line1": "Plot 14, MIDC", "city": "Pune", "state": "Maharashtra",
    "pincode": "411019", "state_code": "27",
}
# The client's customer — the recipient.
CUSTOMER = {
    "id": "cust-1", "name": "Bluewave Industries Pvt Ltd", "gstin": "27BBBBB8888B1Z3",
    "pan": "BBBBB8888B", "address": "Andheri East", "city": "Mumbai",
    "state": "Maharashtra", "state_code": "27",
}


def _invoice(**overrides):
    """An intra-state 18% sale of ₹1,00,000 with one line."""
    base = {
        "invoice_no": "SINV-001", "invoice_date": "2026-06-01", "status": "Issued",
        "amount_paise": 100_000_00, "cgst_paise": 9_000_00, "sgst_paise": 9_000_00,
        "igst_paise": 0, "total_paise": 118_000_00,
        "supply_state_code": "27", "is_reverse_charge": False,
        "lines": [{
            "description": "Steel fasteners — M12", "hsn_sac": "73181500",
            "quantity": "250.000", "unit": "NOS", "rate_paise": 400_00,
            "gst_rate_bps": 1800, "taxable_amount_paise": 100_000_00,
            "cgst_paise": 9_000_00, "sgst_paise": 9_000_00, "igst_paise": 0,
            "line_total_paise": 118_000_00, "sort_order": 0,
        }],
    }
    base.update(overrides)
    return base


# ── A fake PostgREST, matching the shape services/invoice_pdf_service uses ────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.f = []
        self.order_ = None
        self.single_ = False

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def order(self, col, **k):
        self.order_ = col
        return self

    def maybe_single(self):
        self.single_ = True
        return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        m = [r for r in rows if all(r.get(k) == v for k, v in self.f)]
        if self.order_:
            m = sorted(m, key=lambda r: r.get(self.order_, 0))
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _db_with(monkeypatch, *, clients=(CLIENT,), invoice_overrides=None, lines=None):
    db = FakeDB()
    row = {
        "id": "inv-1", "firm_id": "firm-1", "client_id": "cli-1",
        "invoice_no": "SINV-042", "invoice_date": "2026-06-01", "due_date": None,
        "status": "Issued", "taxable_amount_paise": 100_000_00,
        "cgst_paise": 9_000_00, "sgst_paise": 9_000_00, "igst_paise": 0,
        "round_off_paise": 0, "total_paise": 118_000_00,
        "supply_state_code": "27", "is_reverse_charge": False,
        "customers": dict(CUSTOMER),
    }
    row.update(invoice_overrides or {})
    db.store["client_sales_invoices"] = [row]
    db.store["clients"] = [dict(c) for c in clients]
    db.store["firms"] = [dict(FIRM)]
    db.store["client_sales_invoice_lines"] = list(lines if lines is not None else [{
        "sales_invoice_id": "inv-1", "description": "Steel fasteners — M12",
        "hsn_sac": "73181500", "quantity": "250.000", "unit": "NOS",
        "rate_paise": 400_00, "gst_rate_bps": 1800,
        "taxable_amount_paise": 100_000_00, "cgst_paise": 9_000_00,
        "sgst_paise": 9_000_00, "igst_paise": 0, "sort_order": 0,
    }])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    return db


# ── The defect: who is the supplier ──────────────────────────────────────────

class TestSupplierIsTheClient:
    def test_get_sales_invoice_pdf_renders_the_client_as_supplier(self, monkeypatch):
        """Rule 46(b): name, address and GSTIN of the SUPPLIER — the client that
        made the sale. The firm row is in the fake DB and must not be read."""
        _db_with(monkeypatch)
        pdf, _ = get_sales_invoice_pdf("inv-1", "firm-1")
        text = _pdf_text(pdf)
        assert "Sunrise Traders LLP" in text
        assert "27CCCCC7777C1Z1" in text          # the client's GSTIN
        assert "CCCCC7777C" in text               # the client's PAN
        assert "Plot 14, MIDC" in text            # the client's address

    def test_the_ca_practice_appears_nowhere_on_a_clients_sale(self, monkeypatch):
        """The bug: the practice's GSTIN on the customer's tax invoice is a
        credit claimed against a GSTIN that made no supply — unmatchable in
        GSTR-2B (CGST §16(2)(a), Rule 36)."""
        _db_with(monkeypatch)
        pdf, _ = get_sales_invoice_pdf("inv-1", "firm-1")
        text = _pdf_text(pdf)
        assert "27AAAAA9999A1Z5" not in text      # the FIRM's GSTIN
        assert "AAAAA9999A" not in text           # the FIRM's PAN
        assert "Mehta & Associates" not in text
        assert "Fort, Mumbai" not in text

    def test_the_signature_block_is_the_suppliers(self, monkeypatch):
        """Rule 46(q): the signature is the supplier's."""
        _db_with(monkeypatch)
        pdf, _ = get_sales_invoice_pdf("inv-1", "firm-1")
        text = _pdf_text(pdf)
        assert "For Sunrise Traders LLP" in text
        assert "For Mehta & Associates, Chartered Accountants" not in text

    def test_the_customer_is_still_the_recipient(self, monkeypatch):
        _db_with(monkeypatch)
        pdf, _ = get_sales_invoice_pdf("inv-1", "firm-1")
        text = _pdf_text(pdf)
        assert "Bluewave Industries Pvt Ltd" in text
        assert "27BBBBB8888B1Z3" in text

    def test_the_supplier_lookup_is_firm_scoped(self, monkeypatch):
        """Tenancy: the service-role key bypasses RLS, so the .eq('firm_id') on
        the clients read is the isolation control. A client row belonging to
        another firm must not satisfy it."""
        other_firms_client = dict(CLIENT, firm_id="firm-2")
        _db_with(monkeypatch, clients=(other_firms_client,))
        with pytest.raises(ValueError):
            get_sales_invoice_pdf("inv-1", "firm-1")

    def test_a_missing_supplier_record_refuses_instead_of_naming_the_firm(self, monkeypatch):
        _db_with(monkeypatch, clients=())
        with pytest.raises(ValueError) as exc:
            get_sales_invoice_pdf("inv-1", "firm-1")
        assert "Rule 46(b)" in str(exc.value)

    def test_the_portal_path_still_shows_the_practice_from_its_internal_client(self, monkeypatch):
        """The client portal serves the firm's own fee invoices, and those live
        in client_sales_invoices under the firm's INTERNAL practice client
        (services/internal_client_service.provision, migration 074) — a
        `clients` row carrying the firm's legal name, PAN and GSTIN. Reading the
        supplier from `clients` therefore still names the practice there; it is
        the same rule, not an exception to it."""
        internal = {
            "id": "cli-internal", "firm_id": "firm-1",
            "client_name": "Mehta & Associates", "legal_name": "Mehta and Associates LLP",
            "gstin": "27AAAAA9999A1Z5", "pan": "AAAAA9999A", "city": "Mumbai",
            "state": "Maharashtra",
        }
        db = FakeDB()
        db.store["client_sales_invoices"] = [{
            "id": "inv-9", "firm_id": "firm-1", "client_id": "cli-internal",
            "invoice_no": "FEE-001", "invoice_date": "2026-06-01", "status": "Issued",
            "taxable_amount_paise": 100_000_00, "cgst_paise": 9_000_00,
            "sgst_paise": 9_000_00, "igst_paise": 0, "total_paise": 118_000_00,
            "supply_state_code": "27", "customers": dict(CUSTOMER),
        }]
        db.store["clients"] = [internal]
        db.store["client_sales_invoice_lines"] = [{
            "sales_invoice_id": "inv-9", "description": "Statutory audit FY 2025-26",
            "hsn_sac": "998221", "quantity": "1.000", "unit": "NOS",
            "rate_paise": 100_000_00, "gst_rate_bps": 1800,
            "taxable_amount_paise": 100_000_00, "cgst_paise": 9_000_00,
            "sgst_paise": 9_000_00, "igst_paise": 0, "sort_order": 0,
        }]
        monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
        pdf, _ = get_sales_invoice_pdf("inv-9", "firm-1")
        text = _pdf_text(pdf)
        assert "Mehta and Associates LLP" in text
        assert "27AAAAA9999A1Z5" in text
        assert "For Mehta and Associates LLP" in text

    def test_the_practices_own_fee_invoice_still_names_the_practice(self):
        """The other document is unchanged: on a fee invoice the practice really
        is the supplier and the client is the recipient."""
        invoice = {
            "invoice_no": "CF-2026-001", "invoice_date": "2026-06-01", "status": "Issued",
            "amount_paise": 100_000_00, "gst_paise": 18_000_00, "total_paise": 118_000_00,
        }
        text = _pdf_text(build_invoice_pdf(invoice, FIRM, CLIENT))
        assert "Mehta & Associates, Chartered Accountants" in text
        assert "27AAAAA9999A1Z5" in text
        assert "For Mehta & Associates, Chartered Accountants" in text
        assert "Sunrise Traders" in text          # the recipient
        assert "998211" in text                   # the practice's own SAC


# ── Rule 46(l): the rate printed is the rate charged ─────────────────────────

class TestPrintedRateIsTheRateCharged:
    def test_a_five_percent_invoice_does_not_print_nine_percent(self):
        invoice = _invoice(
            cgst_paise=2_500_00, sgst_paise=2_500_00, total_paise=105_000_00,
            lines=[{
                "description": "Packaged tea — 500g", "hsn_sac": "09024010",
                "quantity": "1000.000", "unit": "NOS", "rate_paise": 100_00,
                "gst_rate_bps": 500, "taxable_amount_paise": 100_000_00,
                "cgst_paise": 2_500_00, "sgst_paise": 2_500_00, "igst_paise": 0,
                "sort_order": 0,
            }],
        )
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "CGST @ 2.5%" in text
        assert "SGST @ 2.5%" in text
        assert "CGST @ 9%" not in text
        assert "SGST @ 9%" not in text

    def test_an_eighteen_percent_invoice_still_prints_nine_percent(self):
        text = _pdf_text(build_sales_invoice_pdf(_invoice(), CLIENT, CUSTOMER))
        assert "CGST @ 9%" in text
        assert "SGST @ 9%" in text

    def test_an_inter_state_twelve_percent_invoice_prints_igst_at_twelve(self):
        invoice = _invoice(
            cgst_paise=0, sgst_paise=0, igst_paise=12_000_00, total_paise=112_000_00,
            supply_state_code="07",
            lines=[{
                "description": "Industrial valves", "hsn_sac": "84818090",
                "quantity": "10.000", "unit": "NOS", "rate_paise": 10_000_00,
                "gst_rate_bps": 1200, "taxable_amount_paise": 100_000_00,
                "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 12_000_00,
                "sort_order": 0,
            }],
        )
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "IGST @ 12%" in text
        assert "IGST @ 18%" not in text

    def test_a_mixed_rate_invoice_states_no_single_summary_rate(self):
        """Two rates on one invoice: there is no one rate to put on the summary
        rows, and inventing one is the defect being fixed. Each LINE carries its
        own rate instead (Rule 46(l))."""
        invoice = _invoice(
            amount_paise=200_000_00, cgst_paise=11_500_00, sgst_paise=11_500_00,
            total_paise=223_000_00,
            lines=[
                {"description": "Packaged tea", "hsn_sac": "09024010", "quantity": "1",
                 "unit": "BOX", "rate_paise": 100_000_00, "gst_rate_bps": 500,
                 "taxable_amount_paise": 100_000_00, "cgst_paise": 2_500_00,
                 "sgst_paise": 2_500_00, "igst_paise": 0, "sort_order": 0},
                {"description": "Steel fasteners", "hsn_sac": "73181500", "quantity": "1",
                 "unit": "BOX", "rate_paise": 100_000_00, "gst_rate_bps": 1800,
                 "taxable_amount_paise": 100_000_00, "cgst_paise": 9_000_00,
                 "sgst_paise": 9_000_00, "igst_paise": 0, "sort_order": 1},
            ],
        )
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "CGST @" not in text
        assert "SGST @" not in text
        assert "5%" in text and "18%" in text     # each line's own rate


# ── Rule 46(g)/(h): the line table ───────────────────────────────────────────

class TestLineTableParticulars:
    def test_quantity_unit_rate_and_per_line_tax_are_printed(self):
        text = _pdf_text(build_sales_invoice_pdf(_invoice(), CLIENT, CUSTOMER))
        assert "Qty" in text and "Unit" in text and "GST Rate" in text
        # Helvetica has no rupee glyph — reportlab encodes it to "n", so the new
        # money columns say "Rs." rather than rendering "Rate (n)".
        assert "Rate (Rs.)" in text and "Tax (Rs.)" in text
        assert "250" in text                      # quantity, NUMERIC(10,3)
        assert "NOS" in text                      # unit
        assert "400.00" in text                   # rate per unit, in rupees
        assert "18,000.00" in text                # this line's own tax
        assert "73181500" in text                 # this line's own HSN

    def test_a_lineless_sale_is_not_described_as_chartered_accountancy(self):
        """The synthetic "Professional Services — Chartered Accountancy" row is
        the FEE invoice's fallback. Describing somebody else's sale that way is
        the same invention as stamping the CA's SAC on it."""
        text = _pdf_text(build_sales_invoice_pdf(_invoice(lines=[]), CLIENT, CUSTOMER))
        assert "Professional Services" not in text
        assert "Chartered Accountancy" not in text
        assert "Not recorded" in text
        assert "Line items" in text

    def test_a_line_with_no_hsn_is_not_given_the_practices_own_sac(self):
        """998211 is legal and accounting services — what the CA sells, never
        what the client sells. A missing code is reported, not substituted."""
        invoice = _invoice(lines=[{
            "description": "Assorted hardware", "hsn_sac": None,
            "quantity": "1.000", "unit": "NOS", "rate_paise": 100_000_00,
            "gst_rate_bps": 1800, "taxable_amount_paise": 100_000_00,
            "cgst_paise": 9_000_00, "sgst_paise": 9_000_00, "igst_paise": 0,
            "sort_order": 0,
        }])
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "998211" not in text
        assert "Not recorded" in text
        assert "HSN/SAC for line(s) 1" in text
        assert "Rule 46(g)" in text


# ── Rule 46(n) and 46(p) ─────────────────────────────────────────────────────

class TestPlaceOfSupplyAndReverseCharge:
    def test_place_of_supply_is_printed_with_the_name_of_the_state(self):
        invoice = _invoice(
            cgst_paise=0, sgst_paise=0, igst_paise=18_000_00, supply_state_code="07")
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "Place of Supply:" in text
        assert "07" in text
        assert "Delhi" in text

    def test_an_interstate_supply_with_no_place_of_supply_is_flagged(self):
        invoice = _invoice(
            cgst_paise=0, sgst_paise=0, igst_paise=18_000_00, supply_state_code=None)
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "Place of supply" in text
        assert "Rule 46(n)" in text

    def test_a_zero_rated_export_with_no_igst_is_still_flagged(self):
        """An export under LUT carries no IGST and is still an inter-State
        supply (IGST Act §7(5), §16), so is_interstate carries the fact."""
        invoice = _invoice(
            cgst_paise=0, sgst_paise=0, igst_paise=0, total_paise=100_000_00,
            supply_state_code=None, is_interstate=True)
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "Place of supply" in text
        assert "Rule 46(n)" in text

    def test_reverse_charge_yes_when_the_invoice_says_so(self):
        invoice = _invoice(is_reverse_charge=True)
        text = _pdf_text(build_sales_invoice_pdf(invoice, CLIENT, CUSTOMER))
        assert "Whether tax is payable on reverse charge basis: Yes" in text

    def test_reverse_charge_no_when_it_does_not(self):
        text = _pdf_text(build_sales_invoice_pdf(_invoice(), CLIENT, CUSTOMER))
        assert "Whether tax is payable on reverse charge basis: No" in text

    def test_reverse_charge_flag_survives_the_database_read(self, monkeypatch):
        _db_with(monkeypatch, invoice_overrides={"is_reverse_charge": True})
        pdf, _ = get_sales_invoice_pdf("inv-1", "firm-1")
        assert "reverse charge basis: Yes" in _pdf_text(pdf)


# ── A supplier without a GSTIN is named, not invented ────────────────────────

def test_an_unregistered_supplier_is_reported_not_filled_in():
    """CGST §31(3)(c) with Rule 49: an unregistered supplier issues a bill of
    supply, not a tax invoice. The document says what it does not hold rather
    than borrowing a GSTIN."""
    unregistered = dict(CLIENT)
    unregistered.pop("gstin")
    text = _pdf_text(build_sales_invoice_pdf(_invoice(), unregistered, CUSTOMER))
    assert "Not recorded" in text
    assert "Supplier GSTIN" in text
    assert "27AAAAA9999A1Z5" not in text


def test_totals_and_amount_in_words_are_unchanged():
    """The money was never wrong — only who was named and what was labelled.
    Guard the arithmetic the fix must not disturb."""
    text = _pdf_text(build_sales_invoice_pdf(_invoice(), CLIENT, CUSTOMER))
    assert "1,00,000.00" not in text              # formatting is western-grouped
    assert "100,000.00" in text                   # taxable value
    assert "118,000.00" in text                   # total
    assert "Rupees One Lakh Eighteen Thousand Only" in text

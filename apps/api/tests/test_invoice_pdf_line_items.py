"""
Invoice PDF line items — regression tests (H1).

build_invoice_pdf() previously rendered a single hardcoded row
("Professional Services — Chartered Accountancy", the module-level SAC_CODE
constant, and the invoice's aggregate amount) regardless of how many real
line items the invoice actually had. get_sales_invoice_pdf() never even
queried client_sales_invoice_lines, so the real per-line data was discarded
before it reached the PDF.

The fix loops over invoice["lines"] when present (one row per real line,
using that line's own description/hsn_sac/taxable_amount_paise) and falls
back to the original single synthetic row only for legacy engagement-based
invoices, which have no line-items concept at all. Preserves the tax-summary
rows, _compute_tax_splits, amount_in_words, and all other PDF content
byte-for-byte.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import pdfplumber

from services.invoice_pdf_service import build_invoice_pdf, get_sales_invoice_pdf

FIRM = {"name": "Test & Co", "gstin": "27AAAAA9999A1Z5", "address": "Mumbai"}
CLIENT = {"client_name": "Acme Pvt Ltd", "gstin": "27BBBBB8888B1Z3", "address": "Pune"}


def _pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _invoice(**overrides):
    base = {
        "invoice_no": "SINV-001", "invoice_date": "2026-06-01", "status": "Issued",
        "amount_paise": 100_000_00, "cgst_paise": 9_000_00, "sgst_paise": 9_000_00,
        "igst_paise": 0, "total_paise": 118_000_00,
    }
    base.update(overrides)
    return base


def test_single_line_invoice_renders_the_real_description():
    invoice = _invoice(lines=[
        {"description": "Statutory audit fees FY 2025-26", "hsn_sac": "998221",
         "taxable_amount_paise": 100_000_00, "sort_order": 0},
    ])
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT)
    text = _pdf_text(pdf)
    assert "Statutory audit fees FY 2025-26" in text
    assert "998221" in text
    assert "Professional Services — Chartered Accountancy" not in text


def test_multiple_line_invoice_renders_every_line_not_just_one():
    invoice = _invoice(
        amount_paise=180_000_00,
        lines=[
            {"description": "GST return filing — GSTR-1", "hsn_sac": "998222",
             "taxable_amount_paise": 60_000_00, "sort_order": 0},
            {"description": "GST return filing — GSTR-3B", "hsn_sac": "998222",
             "taxable_amount_paise": 60_000_00, "sort_order": 1},
            {"description": "TDS return filing — 26Q", "hsn_sac": "998231",
             "taxable_amount_paise": 60_000_00, "sort_order": 2},
        ],
    )
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT)
    text = _pdf_text(pdf)
    assert "GST return filing — GSTR-1" in text
    assert "GST return filing — GSTR-3B" in text
    assert "TDS return filing — 26Q" in text
    # Every real line's own HSN/SAC — never the same hardcoded constant for all.
    assert "998222" in text
    assert "998231" in text


def test_gst_tax_summary_rows_are_preserved_alongside_real_lines():
    invoice = _invoice(lines=[
        {"description": "Tax audit fees", "hsn_sac": "998221",
         "taxable_amount_paise": 100_000_00, "sort_order": 0},
    ])
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT)
    text = _pdf_text(pdf)
    assert "CGST @ 9%" in text
    assert "SGST @ 9%" in text
    assert "Total" in text
    assert "118,000.00" in text  # aggregate Taxable Value, unchanged by the fix


def test_taxable_value_total_matches_the_sum_of_real_lines():
    """Export-comparison check: the aggregate 'Taxable Value' row must equal
    the sum of the real per-line taxable amounts backing the invoice."""
    lines = [
        {"description": "Line A", "hsn_sac": "998221", "taxable_amount_paise": 40_000_00, "sort_order": 0},
        {"description": "Line B", "hsn_sac": "998221", "taxable_amount_paise": 60_000_00, "sort_order": 1},
    ]
    invoice = _invoice(amount_paise=sum(l["taxable_amount_paise"] for l in lines), lines=lines)
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT)
    text = _pdf_text(pdf)
    expected_total_str = f"{invoice['amount_paise'] // 100:,}.{invoice['amount_paise'] % 100:02d}"
    assert expected_total_str in text
    assert sum(l["taxable_amount_paise"] for l in lines) == invoice["amount_paise"]


def test_legacy_engagement_invoice_without_lines_still_renders():
    """Backward compatibility: invoices with no line-items concept (the older
    engagement-based single-amount invoices) must render exactly as before."""
    invoice = _invoice()  # no "lines" key at all
    engagement = {"service_type": "Statutory Audit"}
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT, engagement)
    text = _pdf_text(pdf)
    assert "Professional Services — Statutory Audit" in text


def test_empty_lines_list_falls_back_to_legacy_single_row():
    invoice = _invoice(lines=[])
    pdf = build_invoice_pdf(invoice, FIRM, CLIENT)
    text = _pdf_text(pdf)
    assert "Professional Services — Chartered Accountancy" in text


# ── get_sales_invoice_pdf: must actually fetch and attach real line items ──

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

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self.f)]

    def execute(self):
        m = self._match()
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


def test_get_sales_invoice_pdf_fetches_and_renders_the_real_line_items(monkeypatch):
    db = FakeDB()
    db.store["client_sales_invoices"] = [{
        "id": "inv-1", "firm_id": "firm-1", "invoice_no": "SINV-042",
        "invoice_date": "2026-06-01", "due_date": None, "status": "Issued",
        "taxable_amount_paise": 200_000_00, "cgst_paise": 18_000_00, "sgst_paise": 18_000_00,
        "igst_paise": 0, "total_paise": 236_000_00,
        "customers": {"id": "cust-1", "name": "Acme Pvt Ltd", "gstin": "27BBBBB8888B1Z3"},
    }]
    db.store["client_sales_invoice_lines"] = [
        {"sales_invoice_id": "inv-1", "description": "Consulting — Q1 review",
         "hsn_sac": "998311", "taxable_amount_paise": 120_000_00, "sort_order": 0},
        {"sales_invoice_id": "inv-1", "description": "Consulting — Q2 review",
         "hsn_sac": "998311", "taxable_amount_paise": 80_000_00, "sort_order": 1},
    ]
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(
        "services.invoice_pdf_service._load_firm",
        lambda firm_id: {"name": "Test & Co", "gstin": "27AAAAA9999A1Z5"},
    )

    pdf, filename = get_sales_invoice_pdf("inv-1", "firm-1")
    text = _pdf_text(pdf)

    assert "Consulting — Q1 review" in text
    assert "Consulting — Q2 review" in text
    assert "998311" in text
    assert filename == "invoice-SINV-042.pdf"

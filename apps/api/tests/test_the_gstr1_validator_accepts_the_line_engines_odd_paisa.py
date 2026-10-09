"""The GSTR-1 validator accepts the odd paisa the line engine puts on SGST, and nothing wider.

WHAT WAS WRONG
    `domain/sales/line_tax.compute_line_gst` computes a line's full tax and halves it: CGST is the floor, SGST
    carries the odd paisa (a 5% line on Rs 717.00 is 3,585 paise of tax, 1,792 CGST and 1,793 SGST). A document is
    the sum of its lines, so its SGST sits up to one paisa per line above its CGST. `GSTValidator.validate_invoice`
    demanded exact equality, and since the validator was wired into the path a CA actually uses
    (`gstr1_from_books`, #626) every build with such an invoice carried a validation ERROR "CGST (Xp) must equal
    SGST (Yp) for intra-state supply" -- an error on the engine's own correct output. Driving the seeded demo firm
    produced it in 10 of 12 months for one client and 31 distinct messages across the book, some 2 paise apart on a
    two-line invoice. A validator that fires on a correct return is a validator nobody reads.

THE RULE (CGST Act s.9(1), with the SGST Acts: the same rate on each half)
    0 <= SGST - CGST <= the number of lines the figures were summed over. Only in that direction, only for a caller
    that says how many lines (`line_count`), so a raw payload whose halves were typed or computed elsewhere keeps the
    strict equality, and a Rs 1,000 gap, a CGST above its SGST, and a gap wider than the lines can explain are all
    still reported.

[S] The portal's own tolerance between camt and samt could not be confirmed here (gst.gov.in is refused). If it
rejects unequal halves, the engine's split rule must change and not this validator.
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

import services.gst_return_service as grs
from domain.gst.validator import (
    GSTValidator,
    InvoiceToValidate,
    ODD_PAISA_PER_LINE,
    odd_paisa_allowance,
)
from domain.sales.line_tax import compute_line_gst
from tests._property import kernel, paise, rate_bps
from tests.e2e_harness import FakeDB, wire_e2e

PERIOD = "062025"
FIRM = "FIRM-A"
GSTIN = "27AAAAA0000A1Z2"


def _invoice(cgst, sgst, *, line_count=None, interstate=False, igst=0, taxable=1_000_00):
    return InvoiceToValidate(
        reference_no="INV-1", transaction_date="2025-06-10", party_gstin=None,
        place_of_supply="27", taxable_amount_paise=taxable, cgst_paise=cgst,
        sgst_paise=sgst, igst_paise=igst, is_interstate=interstate, gst_rate=None,
        line_count=line_count,
    )


def _fields(inv) -> set[str]:
    return {e.field for e in GSTValidator().validate_invoice(inv, PERIOD)}


def _sum_lines(lines):
    """What the books store for a document: the sum of each line's own engine output."""
    cgst = sgst = 0
    for taxable, bps in lines:
        c, s, _ = compute_line_gst(taxable, bps, False)
        cgst, sgst = cgst + c, sgst + s
    return cgst, sgst


# ── The property: the engine's own output never trips the validator ──────────────────────────────

@kernel()
@given(lines=st.lists(st.tuples(paise(1, 10 ** 9), rate_bps), min_size=1, max_size=12))
def test_whatever_the_line_engine_sums_to_the_validator_accepts(lines):
    cgst, sgst = _sum_lines(lines)
    assert 0 <= sgst - cgst <= len(lines), "the premise: the engine's gap is at most a paisa a line"
    assert "cgst_sgst" not in _fields(_invoice(cgst, sgst, line_count=len(lines)))


@kernel()
@given(lines=st.lists(st.tuples(paise(1, 10 ** 9), rate_bps), min_size=1, max_size=12),
       extra=st.integers(min_value=1, max_value=10_000_00))
def test_a_gap_wider_than_the_lines_can_explain_is_still_reported(lines, extra):
    cgst, sgst = _sum_lines(lines)
    assert "cgst_sgst" in _fields(_invoice(cgst, sgst + extra + len(lines), line_count=len(lines)))


@kernel()
@given(lines=st.lists(st.tuples(paise(1, 10 ** 9), rate_bps), min_size=1, max_size=12))
def test_an_unstated_line_count_keeps_the_strict_rule(lines):
    cgst, sgst = _sum_lines(lines)
    expected = sgst != cgst
    assert ("cgst_sgst" in _fields(_invoice(cgst, sgst, line_count=None))) is expected


# ── The directions and the edges ────────────────────────────────────────────────────────────────

def test_cgst_above_sgst_is_reported_whatever_the_line_count():
    """The engine never puts the odd paisa on CGST, so CGST above SGST is a different fault."""
    assert "cgst_sgst" in _fields(_invoice(9_001_00, 9_000_99, line_count=5))


def test_the_rupees_one_thousand_gap_is_reported_with_a_line_count():
    assert "cgst_sgst" in _fields(_invoice(9_000_00, 8_000_00, line_count=3))
    assert "cgst_sgst" in _fields(_invoice(8_000_00, 9_000_00, line_count=3))


def test_one_paisa_a_line_is_the_edge():
    assert "cgst_sgst" not in _fields(_invoice(1_792, 1_793, line_count=1))
    assert "cgst_sgst" in _fields(_invoice(1_792, 1_794, line_count=1))
    assert "cgst_sgst" not in _fields(_invoice(3_584, 3_586, line_count=2))
    assert "cgst_sgst" in _fields(_invoice(3_584, 3_587, line_count=2))


def test_a_document_with_no_line_rows_still_has_the_headers_one_computation():
    assert odd_paisa_allowance(0) == ODD_PAISA_PER_LINE
    assert "cgst_sgst" not in _fields(_invoice(1_792, 1_793, line_count=0))
    assert "cgst_sgst" in _fields(_invoice(1_792, 1_794, line_count=0))


def test_an_unstated_line_count_allows_no_gap_at_all():
    assert odd_paisa_allowance(None) == 0
    assert "cgst_sgst" in _fields(_invoice(1_792, 1_793, line_count=None))


def test_the_allowance_does_not_follow_the_tax_tolerance():
    """The odd paisa is the engine's construction, not a tolerance: widening
    TAX_TOLERANCE_PAISE (the tax-arithmetic check's slack) must not widen what
    CGST and SGST may differ by."""
    import domain.gst.validator as v
    assert v.ODD_PAISA_PER_LINE == 1
    original = v.TAX_TOLERANCE_PAISE
    v.TAX_TOLERANCE_PAISE = 50
    try:
        assert v.odd_paisa_allowance(2) == 2
    finally:
        v.TAX_TOLERANCE_PAISE = original


def test_an_inter_state_document_is_not_affected():
    assert "cgst_sgst" in _fields(_invoice(1, 1, interstate=True, line_count=3))
    assert "cgst_sgst" not in _fields(_invoice(0, 0, interstate=True, igst=100, line_count=3))


# ── On the path a CA uses ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                         "name": "Acme", "gstin": "27BBBBB1111B1ZN",
                         "state_code": "27", "is_active": True})
    return d


def _seed_invoice(db, lines, **fields):
    """A multi-line intra-State invoice whose header is the sum of the engine's own lines."""
    cgst, sgst = _sum_lines(lines)
    taxable = sum(t for t, _ in lines)
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "invoice_no": "INV-1", "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": 0,
        "total_paise": taxable + cgst + sgst, "is_interstate": False,
        "supply_state_code": "27", "deleted_at": None, **fields,
    })
    for i, (t, bps) in enumerate(lines):
        c, s, _ = compute_line_gst(t, bps, False)
        db.seed("client_sales_invoice_lines", {
            "firm_id": FIRM, "sales_invoice_id": inv["id"], "sort_order": i,
            "hsn_sac": "9983", "description": f"line {i}", "quantity": 1, "unit": "NOS",
            "rate_paise": t, "taxable_paise": t, "gst_rate_bps": bps,
            "cgst_paise": c, "sgst_paise": s, "igst_paise": 0,
        })
    return inv


def _from_books(db):
    return grs.gstr1_from_books(db, FIRM, "CLI", PERIOD, GSTIN)


def test_a_multi_line_invoice_the_engine_split_with_odd_paise_builds_without_a_cgst_sgst_error(db):
    """Three Rs 717.00 lines at 5%: 3,585 paise of tax each, so CGST is 3 paise short of SGST."""
    lines = [(71_700, 500)] * 3
    cgst, sgst = _sum_lines(lines)
    assert sgst - cgst == 3, "the premise: three odd-tax lines leave a three paisa gap"
    _seed_invoice(db, lines)
    out = _from_books(db)
    assert "cgst_sgst" not in {e["field"] for e in out["validation_errors"]}


def test_a_real_cgst_sgst_difference_on_the_same_path_is_still_reported(db):
    """The allowance is the lines', not a blanket: Rs 1,000 apart is reported."""
    _seed_invoice(db, [(71_700, 500)] * 3, cgst_paise=9_000_00, sgst_paise=8_000_00)
    assert "cgst_sgst" in {e["field"] for e in _from_books(db)["validation_errors"]}

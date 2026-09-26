"""GSTR-8 (GST-25, part 2): the e-commerce operator's monthly TCS statement.

`domain/gst/gstr8.py` does not compute the IGST/CGST/SGST split a CA records
against each seller — it CHECKS it, the same posture the GSTN offline utility
takes in its own validation (docs/compliance/sources/gst-offline-utilities/
gstr8/ValidateMod.bas.txt). The rate figures are [S]-graded; VERIFIED is
False and is asserted here rather than merely stated.
"""
from __future__ import annotations

from domain.gst import gstr8


def test_the_module_says_it_is_unverified():
    assert gstr8.VERIFIED is False


# ── financial year / period-key derivation ──────────────────────────────────

def test_fy_label_for_a_month_from_april_onward():
    assert gstr8.financial_year_label("042025") == "2025-26"
    assert gstr8.financial_year_label("032026") == "2025-26"
    assert gstr8.financial_year_label("012026") == "2025-26"


def test_fy_label_for_a_month_before_april():
    assert gstr8.financial_year_label("012025") == "2024-25"


# ── the pos field's own schema boundary ──────────────────────────────────────

def test_pos_is_not_required_before_fy_2025_26():
    assert gstr8.pos_field_required("032025") is False   # FY 2024-25


def test_pos_is_required_from_fy_2025_26():
    assert gstr8.pos_field_required("042025") is True


# ── the rate-band boundary ───────────────────────────────────────────────────

def test_exact_one_percent_required_before_july_2024():
    low, high = gstr8._rate_band_bps("062024")
    assert (low, high) == (100, 100)


def test_a_band_is_accepted_from_july_2024():
    low, high = gstr8._rate_band_bps("072024")
    assert (low, high) == (50, 100)


def test_the_band_still_applies_well_after_the_change():
    low, high = gstr8._rate_band_bps("042026")
    assert (low, high) == (50, 100)


# ── net amount liable ────────────────────────────────────────────────────────

def _row(**over):
    base = dict(supplier_gstin="27AAAAA0000A1Z5", place_of_supply=None,
               gross_registered_paise=0, returns_registered_paise=0,
               gross_unregistered_paise=0, returns_unregistered_paise=0,
               igst_paise=0, cgst_paise=0, sgst_paise=0)
    base.update(over)
    return gstr8.SupplyRow(**base)


def test_net_liable_is_gross_less_returns_across_both_recipient_kinds():
    row = _row(gross_registered_paise=10_00_000, returns_registered_paise=2_00_000,
              gross_unregistered_paise=5_00_000, returns_unregistered_paise=1_00_000)
    assert row.net_liable_paise == 12_00_000


def test_tax_collected_sums_the_three_heads():
    row = _row(igst_paise=100, cgst_paise=0, sgst_paise=0)
    assert row.tax_collected_paise == 100


# ── row-level findings ───────────────────────────────────────────────────────

def test_a_clean_row_before_the_rate_change_has_no_findings():
    # net 10,00,000 paise at exactly 1% -> 10,000 paise, split evenly
    row = _row(gross_registered_paise=10_00_000, cgst_paise=5_000, sgst_paise=5_000)
    problems = gstr8._row_problems(row, "062024", pos_required=False)
    assert problems == []


def test_a_clean_row_after_the_rate_change_at_half_a_percent_has_no_findings():
    row = _row(gross_registered_paise=10_00_000, cgst_paise=2_500, sgst_paise=2_500)
    problems = gstr8._row_problems(row, "072024", pos_required=False)
    assert problems == []


def test_cgst_not_equal_to_sgst_is_a_finding():
    row = _row(gross_registered_paise=10_00_000, cgst_paise=6_000, sgst_paise=4_000)
    problems = gstr8._row_problems(row, "072024", pos_required=False)
    assert any("CGST" in p and "SGST" in p for p in problems)


def test_tax_on_a_nil_net_amount_is_a_finding():
    row = _row(gross_registered_paise=1_00_000, returns_registered_paise=1_00_000,
              cgst_paise=100, sgst_paise=100)
    problems = gstr8._row_problems(row, "072024", pos_required=False)
    assert any("nil or negative" in p for p in problems)


def test_a_positive_net_with_no_tax_is_a_finding():
    row = _row(gross_registered_paise=10_00_000)
    problems = gstr8._row_problems(row, "072024", pos_required=False)
    assert any("no tax is recorded" in p for p in problems)


def test_tax_outside_the_band_is_a_finding():
    # net 10,00,000 at exactly 1% before the change, but this bill claims 2%.
    row = _row(gross_registered_paise=10_00_000, cgst_paise=10_000, sgst_paise=10_000)
    problems = gstr8._row_problems(row, "062024", pos_required=False)
    assert any("outside the expected range" in p for p in problems)


def test_a_missing_place_of_supply_is_a_finding_only_where_required():
    row = _row(gross_registered_paise=10_00_000, cgst_paise=2_500, sgst_paise=2_500,
              place_of_supply=None)
    assert not gstr8._row_problems(row, "072024", pos_required=False)
    assert any("place of supply" in p.lower()
              for p in gstr8._row_problems(row, "072025", pos_required=True))


def test_igst_alone_reconciles_without_a_cgst_sgst_split():
    row = _row(gross_registered_paise=10_00_000, igst_paise=10_000)
    assert gstr8._row_problems(row, "062024", pos_required=False) == []


# ── unregistered rows carry no tax at all ───────────────────────────────────

def test_unregistered_row_net_is_gross_less_returns():
    row = gstr8.UnregisteredSupplyRow(enrolment_id="EID123", gross_value_paise=5_000,
                                      returns_paise=1_000)
    assert row.net_liable_paise == 4_000


# ── the whole statement ──────────────────────────────────────────────────────

def test_the_statement_sums_every_supplier_and_names_every_finding():
    clean = _row(supplier_gstin="27AAAAA0000A1Z5",
                gross_registered_paise=10_00_000, cgst_paise=2_500, sgst_paise=2_500)
    broken = _row(supplier_gstin="29BBBBB1111B1Z5",
                 gross_registered_paise=5_00_000, cgst_paise=1_000, sgst_paise=900)
    stmt = gstr8.compute_gstr8(period="072024", supply_rows=[clean, broken],
                               unregistered_rows=[])
    assert stmt.supplier_count == 2
    assert stmt.total_net_liable_paise == 15_00_000
    assert stmt.total_cgst_paise == 3_500
    assert len(stmt.findings) == 1
    assert stmt.findings[0].supplier_gstin == "29BBBBB1111B1Z5"


def test_the_statement_carries_its_own_financial_year_and_pos_requirement():
    stmt = gstr8.compute_gstr8(period="042025", supply_rows=[], unregistered_rows=[])
    assert stmt.financial_year == "2025-26"
    assert stmt.pos_required is True
    assert stmt.rate_band_bps == (50, 100)


def test_unregistered_totals_are_kept_apart_from_registered_ones():
    reg = _row(gross_registered_paise=10_00_000, cgst_paise=2_500, sgst_paise=2_500)
    unreg = gstr8.UnregisteredSupplyRow(enrolment_id="EID1", gross_value_paise=3_000,
                                        returns_paise=0)
    stmt = gstr8.compute_gstr8(period="072024", supply_rows=[reg],
                               unregistered_rows=[unreg])
    assert stmt.total_net_liable_paise == 10_00_000
    assert stmt.total_unregistered_net_paise == 3_000
    assert stmt.unregistered_supplier_count == 1


def test_an_empty_period_answers_zero_rather_than_raising():
    stmt = gstr8.compute_gstr8(period="072024", supply_rows=[], unregistered_rows=[])
    assert stmt.total_net_liable_paise == 0
    assert stmt.findings == []

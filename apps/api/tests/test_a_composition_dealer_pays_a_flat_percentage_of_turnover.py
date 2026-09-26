"""CMP-08: a composition dealer's quarterly statement (GST-25, part 1).

domain/gst/composition.py computes the four lines the offline utility's own
VBA names (docs/compliance/sources/gst-offline-utilities/gstr4-annual/
CMP08Mod.bas.txt): outward supplies, inward RCM supplies, tax paid, interest
paid. The category-to-rate mapping is [S]-graded (VERIFIED is False) and that
is asserted here rather than merely stated — a later, confirmed edit that
forgets to flip it would otherwise ship as "verified" silently.
"""
from __future__ import annotations

from domain.gst import composition as cmp


def test_the_module_says_it_is_unverified():
    assert cmp.VERIFIED is False


def test_every_category_has_a_rate_and_every_rate_a_category():
    assert set(cmp.COMPOSITION_RATE_BPS) == set(cmp.COMPOSITION_CATEGORIES)


def test_manufacturer_trader_is_one_percent():
    rate, gap = cmp.rate_bps_for(cmp.MANUFACTURER_TRADER)
    assert rate == 100
    assert gap is None


def test_restaurant_is_five_percent():
    rate, gap = cmp.rate_bps_for(cmp.RESTAURANT)
    assert rate == 500


def test_other_services_is_six_percent():
    rate, gap = cmp.rate_bps_for(cmp.OTHER_SERVICES)
    assert rate == 600


def test_an_unrecorded_category_is_refused_not_defaulted():
    rate, gap = cmp.rate_bps_for(None)
    assert rate is None
    assert "no composition category is recorded" in gap.lower()


def test_an_unrecognised_category_is_refused():
    rate, gap = cmp.rate_bps_for("wholesaler")
    assert rate is None
    assert "wholesaler" in gap


# ── compute_cmp08 ────────────────────────────────────────────────────────────

def test_outward_tax_splits_half_cgst_half_sgst_never_igst():
    # A composition dealer's outward supply is intra-State by construction
    # (s.10(2)(c) bars inter-State outward supply outright).
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q2",
        category=cmp.MANUFACTURER_TRADER,
        outward_taxable_paise=10_00_000_00,  # ₹10,00,000 turnover, 1%% = ₹10,000
    )
    assert stmt.outward_supplies.igst_paise == 0
    assert stmt.outward_supplies.cgst_paise == 5_000_00
    assert stmt.outward_supplies.sgst_paise == 5_000_00
    assert stmt.outward_supplies.tax_paise == 10_000_00


def test_the_odd_paisa_lands_on_sgst_not_lost():
    # ₹1,00,001 at 1% is ₹1,000.01 -> 1000 paise*100 + 1 = 100001 paise total
    # tax. compute_line_gst floors the whole tax then gives SGST the remainder.
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q1",
        category=cmp.MANUFACTURER_TRADER,
        outward_taxable_paise=1_00_00_100,  # ₹1,00,001.00 in paise
    )
    total = stmt.outward_supplies.cgst_paise + stmt.outward_supplies.sgst_paise
    assert total == stmt.outward_supplies.tax_paise
    assert stmt.outward_supplies.sgst_paise >= stmt.outward_supplies.cgst_paise


def test_turnover_is_the_whole_figure_including_exempt():
    # Row 1's own label is "Outward supplies (including exempt supplies)" —
    # the caller passes the WHOLE turnover, this module does not net anything
    # out of it.
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q3",
        category=cmp.RESTAURANT,
        outward_taxable_paise=20_00_000_00,
    )
    assert stmt.outward_supplies.taxable_value_paise == 20_00_000_00


def test_row_3_is_rows_1_plus_2_by_construction():
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q4",
        category=cmp.OTHER_SERVICES,
        outward_taxable_paise=5_00_000_00,
        inward_rcm_taxable_paise=1_00_000_00,
        inward_rcm_igst_paise=18_000_00,
    )
    expected_taxable = (stmt.outward_supplies.taxable_value_paise
                        + stmt.inward_rcm_supplies.taxable_value_paise)
    assert stmt.tax_paid.taxable_value_paise == expected_taxable
    assert stmt.tax_paid.tax_paise == (stmt.outward_supplies.tax_paise
                                       + stmt.inward_rcm_supplies.tax_paise)
    assert stmt.tax_paid.igst_paise == stmt.inward_rcm_supplies.igst_paise
    assert stmt.tax_paid.cgst_paise == stmt.outward_supplies.cgst_paise
    assert stmt.tax_paid.sgst_paise == stmt.outward_supplies.sgst_paise


def test_inward_rcm_figures_are_the_callers_own_never_recomputed():
    # The domain module has no database handle to tell an inter-State RCM
    # bill from an intra-State one, so it takes the split as given.
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q1",
        category=cmp.MANUFACTURER_TRADER,
        outward_taxable_paise=0,
        inward_rcm_taxable_paise=50_000_00,
        inward_rcm_igst_paise=9_000_00,
        inward_rcm_cgst_paise=0,
        inward_rcm_sgst_paise=0,
        inward_rcm_cess_paise=0,
    )
    assert stmt.inward_rcm_supplies.igst_paise == 9_000_00
    assert stmt.inward_rcm_supplies.cgst_paise == 0


def test_a_missing_category_still_produces_a_statement_with_a_named_gap():
    # Refusing the whole statement over an unrecorded category would block a
    # CA from seeing anything at all; the module answers what it can (a nil
    # rate applied to the turnover) and names precisely what is missing.
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q2",
        category=None,
        outward_taxable_paise=10_00_000_00,
    )
    assert stmt.rate_bps is None
    assert stmt.outward_supplies.tax_paise == 0
    assert len(stmt.gaps) == 1
    assert "composition category" in stmt.gaps[0].lower()


def test_interest_is_never_guessed_it_is_the_callers_figure():
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q1",
        category=cmp.MANUFACTURER_TRADER,
        outward_taxable_paise=1_00_000_00,
        interest_paise=250_00,
    )
    assert stmt.interest_paise == 250_00
    # and the default is zero, not a computed figure:
    stmt2 = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q1",
        category=cmp.MANUFACTURER_TRADER,
        outward_taxable_paise=1_00_000_00,
    )
    assert stmt2.interest_paise == 0


def test_the_s10_2a_turnover_limit_is_named_not_enforced():
    # This module computes what the statement SAYS, not whether the dealer is
    # still eligible to file one at all — enforcing it here would silently
    # change a figure rather than raise a separate warning a caller can act on.
    stmt = cmp.compute_cmp08(
        financial_year="2026-27", quarter="Q3",
        category=cmp.OTHER_SERVICES,
        outward_taxable_paise=cmp.S10_2A_TURNOVER_LIMIT_PAISE + 1_00_000_00,
    )
    assert stmt.rate_bps == 600
    assert stmt.outward_supplies.taxable_value_paise > cmp.S10_2A_TURNOVER_LIMIT_PAISE


def test_cmpline_add_sums_every_head():
    a = cmp.CmpLine(100, 1, 2, 3, 4)
    b = cmp.CmpLine(200, 10, 20, 30, 40)
    c = a.add(b)
    assert c.taxable_value_paise == 300
    assert c.igst_paise == 11
    assert c.cgst_paise == 22
    assert c.sgst_paise == 33
    assert c.cess_paise == 44

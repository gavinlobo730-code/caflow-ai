"""
domain.tds.section_rates — FY-versioned TDS section thresholds/rates.

Verifies the F17 fix: thresholds updated to Finance Act 2025 (effective
1 April 2025), rates to Finance (No. 2) Act 2024, everything FY-versioned
with explicit verification flags, integer basis points (no float), and an
FY-derived (not hardcoded) 24Q/26Q quarter calendar per IT Rules Rule 31A.
"""
import pytest

from domain.tds.section_rates import (
    LATEST_VERIFIED_TDS_FY, TDS_RATES_BY_FY, quarter_dates, tds_rates_for,
)
from domain.tds.tds_computer import TDSComputer


FY = "2025-26"


# ── Registry resolution ───────────────────────────────────────────────────────

def test_fy_2025_26_is_verified():
    assert TDS_RATES_BY_FY["2025-26"].verified is True
    assert LATEST_VERIFIED_TDS_FY == "2025-26"


def test_fy_2026_27_is_carried_forward_unverified():
    r = TDS_RATES_BY_FY["2026-27"]
    assert r.verified is False
    # Carried forward = identical section data until verified against FA 2026
    assert r.sections == TDS_RATES_BY_FY["2025-26"].sections


def test_unknown_future_fy_falls_back_to_latest_verified():
    r = tds_rates_for("2031-32")
    assert r.fy == LATEST_VERIFIED_TDS_FY
    assert r.verified is True


def test_default_resolves_current_fy():
    assert tds_rates_for() is not None  # smoke: no crash resolving the real "today"


# ── Finance Act 2025 thresholds (the F17 stale values, corrected) ────────────

@pytest.mark.parametrize("section,threshold_rupees", [
    ("193", 10_000),     # interest on securities (was ₹1,000 in the old table)
    ("194", 10_000),     # dividends (was 5,000)
    ("194A", 10_000),    # interest, "any other payer" baseline (was 4,000)
    ("194D", 20_000),    # insurance commission (was 15,000)
    ("194G", 20_000),    # lottery-ticket commission (was 15,000)
    ("194H", 20_000),    # commission/brokerage (was 15,000)
    ("194I", 50_000),    # rent, per month or part (was 2,40,000/yr)
    ("194J", 50_000),    # professional fees (was 30,000)
    ("194K", 10_000),    # mutual-fund income (was 5,000)
    ("194LA", 5_00_000), # compulsory-acquisition compensation (was 2,50,000)
])
def test_finance_act_2025_thresholds(section, threshold_rupees):
    rule = tds_rates_for(FY).sections[section]
    assert rule.single_threshold_paise == threshold_rupees * 100


def test_194c_unchanged_with_aggregate():
    rule = tds_rates_for(FY).sections["194C"]
    assert rule.single_threshold_paise == 30_000_00
    assert rule.aggregate_threshold_paise == 1_00_000_00
    assert rule.individual_rate_bps == 100   # 1%
    assert rule.company_rate_bps == 200      # 2%


def test_finance_no2_act_2024_rate_cuts():
    """194D/194G/194H were cut from 5% to 2% (194D for non-companies)."""
    sections = tds_rates_for(FY).sections
    assert sections["194D"].individual_rate_bps == 200
    assert sections["194D"].company_rate_bps == 1000  # companies stay 10%
    assert sections["194G"].individual_rate_bps == 200
    assert sections["194H"].individual_rate_bps == 200


def test_all_rates_are_integer_bps():
    """CLAUDE.md: integer arithmetic only — bps must be ints, never float."""
    for fy_rates in TDS_RATES_BY_FY.values():
        for section, rule in fy_rates.sections.items():
            assert isinstance(rule.single_threshold_paise, int), section
            assert isinstance(rule.individual_rate_bps, int), section
            assert isinstance(rule.company_rate_bps, int), section


# ── resolve_tds through the registry ─────────────────────────────────────────

def test_resolve_tds_uses_requested_fy():
    c = TDSComputer()
    r = c.resolve_tds("194J", 60_000_00, fy=FY)
    assert r.applies is True
    assert r.tds_paise == 6_000_00
    assert isinstance(r.tds_paise, int)


def test_resolve_tds_194c_aggregate_trigger():
    """Single bill ₹25,000 is under the ₹30,000 single threshold, but prior
    FY payments of ₹80,000 push the aggregate over ₹1,00,000 → TDS applies
    on THIS bill (IT Act §194C proviso)."""
    c = TDSComputer()
    below = c.resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=0, fy=FY)
    assert below.applies is False
    tripped = c.resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=80_000_00, fy=FY)
    assert tripped.applies is True
    assert tripped.tds_paise == 25_000_00 * 100 // 10000  # 1% of this bill only


def test_resolve_tds_unknown_section_raises():
    with pytest.raises(ValueError):
        TDSComputer().resolve_tds("194ZZ", 100_000_00, fy=FY)


def test_compute_tds_amount_no_float():
    """The old compute_tds_amount did `paise * float_rate` — must now be
    integer bps end to end, with floor division."""
    c = TDSComputer()
    amt = c.compute_tds_amount("194Q", 60_00_000_00, fy=FY)  # 0.1% of ₹60L
    assert isinstance(amt, int)
    assert amt == 60_00_000_00 * 10 // 10000  # 6,000 rupees in paise


# ── Quarter calendar (Rule 31A) ───────────────────────────────────────────────

def test_quarter_dates_fy_2025_26():
    assert quarter_dates("2025-26", "Q1") == ("2025-04-01", "2025-06-30", "2025-07-31")
    assert quarter_dates("2025-26", "Q2") == ("2025-07-01", "2025-09-30", "2025-10-31")
    assert quarter_dates("2025-26", "Q3") == ("2025-10-01", "2025-12-31", "2026-01-31")
    assert quarter_dates("2025-26", "Q4") == ("2026-01-01", "2026-03-31", "2026-05-31")


def test_quarter_dates_not_pinned_to_one_fy():
    """F17: the old QUARTER_DATES dict returned 2025-26 dates for every FY."""
    assert quarter_dates("2026-27", "Q4") == ("2027-01-01", "2027-03-31", "2027-05-31")
    assert quarter_dates("2024-25", "Q1") == ("2024-04-01", "2024-06-30", "2024-07-31")


def test_quarter_dates_rejects_bad_quarter():
    with pytest.raises(ValueError):
        quarter_dates("2025-26", "Q5")


def test_workspace_due_date_helper_q4_is_31_may_of_end_year():
    """F17: _tds_return_due_date used to return '{start_year}-04-31' for Q4 —
    a nonexistent date in the wrong month AND wrong year."""
    from routers.tds_workspace import _tds_return_due_date
    assert _tds_return_due_date("Q4", "2025-26") == "2026-05-31"
    assert _tds_return_due_date("Q1", "2025-26") == "2025-07-31"
    assert _tds_return_due_date("Q3", "2025-26") == "2026-01-31"

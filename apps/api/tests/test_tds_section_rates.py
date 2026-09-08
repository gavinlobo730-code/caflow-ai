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
    (IT Act §194C(5), second limb).

    And it applies to the AGGREGATE, not to the marginal bill. §194C(5) makes
    the deduction due where "the aggregate of the amounts of such sums credited
    or paid ... exceeds one lakh rupees" — the liability attaches to that
    aggregate, so the bill that crosses carries the whole year's tax less
    whatever has already been withheld.

    This assertion used to read `25_000_00 * 100 // 10000` — ₹250, 1% of the
    crossing bill alone — against ₹1,050 due on the ₹1,05,000 aggregate. A
    short deduction is not a rounding difference: §201(1A) charges 1% a month
    interest on it and §40(a)(ia) disallows 30% of the expenditure.
    """
    c = TDSComputer()
    below = c.resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=0, fy=FY)
    assert below.applies is False
    tripped = c.resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=80_000_00, fy=FY)
    assert tripped.applies is True
    # 1% of the ₹1,05,000 aggregate, nothing withheld on the earlier bills.
    assert tripped.tds_paise == 1_05_000_00 * 100 // 10000 == 1_050_00


def test_resolve_tds_credits_what_was_already_withheld():
    """Once the aggregate is charged, every later bill charges the NEW
    aggregate and credits what earlier bills already withheld — otherwise the
    same ₹1,05,000 is taxed again on the next bill.

    IT Act §194C(5) with §200: the deduction is on the aggregate; what has been
    deducted and paid to the credit of the Central Government is not deducted
    twice.
    """
    c = TDSComputer()
    # Sixth ₹25,000 bill: aggregate ₹1,30,000 → ₹1,300 due, ₹1,050 already
    # withheld on the bill that crossed → ₹250 now.
    r = c.resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=1_05_000_00,
                      fy_prior_tds_paise=1_050_00, fy=FY)
    assert r.applies is True
    assert r.tds_paise == 250_00


def test_already_withheld_never_produces_a_negative_deduction():
    """A credit note or a rate change can leave more withheld than the fresh
    aggregate needs. The engine deducts nothing; it never hands money back
    through a negative withholding (there is no such thing on a 26Q line)."""
    r = TDSComputer().resolve_tds("194C", 25_000_00, fy_prior_taxable_paise=1_05_000_00,
                                  fy_prior_tds_paise=99_999_00, fy=FY)
    assert r.applies is True
    assert r.tds_paise == 0


def test_resolve_tds_unknown_section_raises():
    with pytest.raises(ValueError):
        TDSComputer().resolve_tds("194ZZ", 100_000_00, fy=FY)


def test_compute_tds_amount_no_float():
    """The old compute_tds_amount did `paise * float_rate` — must now be
    integer bps end to end, with floor division.

    The AMOUNT this asserts was also wrong. IT Act §194Q(1) charges "a sum
    equal to 0.1 per cent of such sum EXCEEDING fifty lakh rupees" — the
    ₹50,00,000 is not merely a trigger, it is carved out of the base. On a
    ₹60,00,000 purchase the base is the ₹10,00,000 excess and the tax is
    ₹1,000. This test used to assert ₹6,000 — 0.1% of the whole invoice —
    which is six times the statutory amount, deducted from the seller and paid
    to the Government against a liability that does not exist.
    """
    c = TDSComputer()
    amt = c.compute_tds_amount("194Q", 60_00_000_00, fy=FY)
    assert isinstance(amt, int)
    # 0.1% of (₹60,00,000 − ₹50,00,000), NOT of ₹60,00,000.
    assert amt == (60_00_000_00 - 50_00_000_00) * 10 // 10000 == 1_000_00


def test_194q_is_the_only_section_charged_on_the_excess():
    """The excess basis is a property of §194Q(1)'s own wording, not a general
    rule: every other section here charges on the whole sum once its threshold
    is crossed (§194J deducts on all ₹60,000, not on the ₹10,000 excess)."""
    sections = tds_rates_for(FY).sections
    assert sections["194Q"].charge_on_excess_only is True
    for name, rule in sections.items():
        if name != "194Q":
            assert rule.charge_on_excess_only is False, name


# ── FY aggregate thresholds (defect 1) ───────────────────────────────────────

@pytest.mark.parametrize("section,limit_rupees", [
    # Each section's own annual limit, in the statute's own "aggregate of the
    # sums ... during the financial year" wording.
    ("194A", 10_000),   # §194A(3)(i)/(iii) — "any other payer" case modelled
    ("194C", 1_00_000), # §194C(5) second limb
    ("194D", 20_000),   # §194D proviso
    ("194G", 20_000),   # §194G(1) proviso
    ("194H", 20_000),   # §194H proviso
    ("194J", 50_000),   # §194J proviso, clause (B)
])
def test_sections_with_an_fy_aggregate_carry_one(section, limit_rupees):
    """Before this, only §194C had an aggregate_threshold_paise, so the second
    limb of resolve_tds's `applies` test was dead for every other section — a
    consultant billing ₹30,000 four times had nothing withheld all year."""
    rule = tds_rates_for(FY).sections[section]
    assert rule.aggregate_threshold_paise == limit_rupees * 100


def test_194j_four_bills_below_the_single_threshold_still_withhold():
    """§194J's proviso: no deduction where "such sum or, as the case may be,
    the aggregate of the sums credited or paid ... during the financial year
    does not exceed fifty thousand rupees". Four ₹30,000 bills exceed it at the
    second, and the year's withholding is 10% of the whole ₹1,20,000 — ₹12,000,
    not the zero the missing aggregate threshold produced.
    """
    c = TDSComputer()
    prior_taxable = 0
    prior_tds = 0
    per_bill = []
    for _ in range(4):
        r = c.resolve_tds("194J", 30_000_00, fy_prior_taxable_paise=prior_taxable,
                          fy_prior_tds_paise=prior_tds, fy=FY)
        per_bill.append(r.tds_paise)
        prior_taxable += 30_000_00
        prior_tds += r.tds_paise
    # Nothing on the first (₹30,000 aggregate), then the aggregate is charged.
    assert per_bill == [0, 6_000_00, 3_000_00, 3_000_00]
    assert sum(per_bill) == 12_000_00 == 1_20_000_00 * 1000 // 10000


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


# ── s. 194Q's threshold is BOTH limbs ────────────────────────────────────────

def test_194q_aggregates_across_the_year_and_charges_only_the_excess():
    """IT Act s. 194Q(1): "purchase of goods of the value OR AGGREGATE OF SUCH
    VALUE exceeding fifty lakh rupees in any previous year".

    Both limbs carry ₹50,00,000, and the threshold is carved OUT of the base
    rather than only triggering it. Modelled with only the single-payment limb,
    two ₹30,00,000 bills to one seller withheld NOTHING against ₹1,000 due on
    the ₹60,00,000 year — a 100% short deduction carrying s. 201(1A) interest
    at 1% a month and a s. 40(a)(ia) disallowance of 30% of the expenditure.

    The aggregate limb became safe to model only once the purchase-bill path
    started crediting what earlier bills withheld: charging a running aggregate
    without that credit re-charges the whole year on every later bill.
    """
    c = TDSComputer()
    b1 = c.resolve_tds("194Q", 30_00_000_00, fy=FY)
    assert not b1.applies and b1.tds_paise == 0      # year to date ₹30L — under

    b2 = c.resolve_tds("194Q", 30_00_000_00,
                       fy_prior_taxable_paise=30_00_000_00,
                       fy_prior_tds_paise=b1.tds_paise, fy=FY)
    # ₹60,00,000 year, ₹10,00,000 excess, 0.1% = ₹1,000 — all of it falls on
    # the bill that crosses.
    assert b2.applies and b2.tds_paise == 1_000_00

    b3 = c.resolve_tds("194Q", 30_00_000_00,
                       fy_prior_taxable_paise=60_00_000_00,
                       fy_prior_tds_paise=b1.tds_paise + b2.tds_paise, fy=FY)
    assert b3.tds_paise == 3_000_00                  # ₹4,000 cumulative less ₹1,000

    total = b1.tds_paise + b2.tds_paise + b3.tds_paise
    assert total == (90_00_000_00 - 50_00_000_00) * 10 // 10000


def test_194q_single_payment_is_unchanged_by_the_aggregate_limb():
    """A one-off ₹60,00,000 purchase still bears ₹1,000, not ₹6,000 and not
    ₹1,000 twice. The aggregate limb must not double-count the same sum."""
    c = TDSComputer()
    r = c.resolve_tds("194Q", 60_00_000_00, fy=FY)
    assert r.applies and r.tds_paise == 1_000_00


def test_194q_is_still_the_only_section_charged_on_the_excess():
    """Adding the aggregate limb must not have made 194Q look like the others,
    nor given another section the excess base. s. 194Q(1) is alone in saying
    "of such sum exceeding" — every other section charges the whole sum once
    its threshold is crossed."""
    rules = tds_rates_for(FY).sections
    assert [s for s, r in rules.items() if r.charge_on_excess_only] == ["194Q"]
    assert rules["194Q"].aggregate_threshold_paise == rules["194Q"].single_threshold_paise == 50_00_000_00

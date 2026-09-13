"""CGST Rule 43 — the sixty-month common-credit apportionment on capital goods.

FA-19. A registered person making both taxable and exempt supplies cannot keep
the whole input tax credit on a machine used for both: Rule 43 spreads that
credit over SIXTY tax periods and adds the exempt-turnover share of each
instalment back to output tax.

Nothing in this product computed it. `fixed_assets` has carried the tax split
and `itc_eligible` since migration 343 and the outward turnover is already
computed for GSTR-3B; the one fact nobody held was which of Rule 43(1)'s three
uses an asset is put to, which migration 372 adds.

WHAT THESE TESTS PIN, in order of what would hurt most if it broke:

  * the arithmetic, per head, against figures worked by hand;
  * the rounding DIRECTION — Te is added to output tax and 43(1)(h) charges
    interest on it, so understating it is a growing shortfall;
  * that an unclassified asset is left OUT and NAMED, never assumed either way;
  * that the sixty instalments are counted from the invoice month and are
    sixty exactly — not fifty-nine, not sixty-one;
  * that a zero-rated supply is not in E, which is the one exclusion that
    would reverse credit the export scheme exists to give back.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.gst import rule_43
from domain.gst.rule_43 import (
    CapitalGood, Turnover, USE_COMMON, USE_EXCLUSIVELY_EXEMPT,
    USE_EXCLUSIVELY_TAXABLE, USEFUL_LIFE_MONTHS, compute, period_index,
)

APR = date(2025, 4, 1)


def _good(name="Lathe", *, inv=date(2025, 4, 10), igst=0, cgst=0, sgst=0,
          eligible=True, use=USE_COMMON):
    return CapitalGood(asset_id=name.lower(), asset_name=name, invoice_date=inv,
                       igst_paise=igst, cgst_paise=cgst, sgst_paise=sgst,
                       itc_eligible=eligible, use=use)


# ── The arithmetic ───────────────────────────────────────────────────────────

def test_te_is_one_sixtieth_of_the_credit_times_the_exempt_share():
    """Worked by hand: ₹900 CGST ÷ 60 = ₹15 a month; 20% exempt → ₹3."""
    r = compute([_good(cgst=90_000, sgst=90_000)], period="042025",
                period_start=APR,
                turnover=Turnover(exempt_paise=20_00_000, total_paise=1_00_00_000))
    assert r.refused is False
    assert r.te_paise["cgst"] == 300
    assert r.te_paise["sgst"] == 300
    assert r.te_paise["igst"] == 0


def test_each_head_is_apportioned_separately():
    """Rule 43(2) — 'the amount Te shall be computed separately for input tax
    credit of central tax, State tax, Union territory tax and integrated tax'.
    One total would be unallocable across the three output heads."""
    r = compute([_good(igst=6_00_000), _good("Press", cgst=3_00_000, sgst=3_00_000)],
                period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    # 600000/60 = 10000 * 0.5 = 5000 ; 300000/60 = 5000 * 0.5 = 2500
    assert r.te_paise == {"igst": 5000, "cgst": 2500, "sgst": 2500}


def test_the_division_happens_once_on_the_aggregate_not_per_asset():
    """Sixty per-asset divisions round sixty times and drift. Tc is aggregated
    first — 43(1)(d) says 'the aggregate of the amounts of A' — and ÷60 and
    ×E/F are applied to that."""
    # Three assets of 1 paise of credit each. Per-asset the ceiling would give
    # 1 paise three times; on the aggregate it is one.
    goods = [_good(f"A{i}", cgst=1) for i in range(3)]
    r = compute(goods, period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.common_credit_paise["cgst"] == 3
    assert r.te_paise["cgst"] == 1        # ceil(3 / 60) — not 3


def test_a_fraction_of_a_paisa_rounds_UP():
    """Te is added to the output tax liability and Rule 43(1)(h) attaches
    interest to it, so understating it is a shortfall that grows. Rounding up
    cannot create one. Opposite direction from the §15(3) discount, which
    floors because there understating cannot under-declare tax."""
    # 100 paise of credit, 1% exempt: 100/60 * 0.01 = 0.0166… paise.
    r = compute([_good(cgst=100)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=100))
    assert r.te_paise["cgst"] == 1


def test_nil_exempt_turnover_gives_nil_te_and_says_so():
    r = compute([_good(cgst=90_000)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=0, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert any("No exempt supplies" in c for c in r.caveats)
    # The instalment still counts against the sixty — the asset participates.
    assert [ln.included for ln in r.lines] == [True]


def test_wholly_exempt_turnover_reverses_the_whole_instalment():
    r = compute([_good(cgst=90_000)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1_00_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 1500      # 90000 / 60


# ── The sixty instalments ────────────────────────────────────────────────────

def test_the_invoice_month_is_instalment_one():
    assert period_index(date(2025, 4, 10), date(2025, 4, 1)) == 1


def test_the_life_is_sixty_periods_exactly():
    """Not 59 and not 61. Rule 43(1)(c) gives five years 'from the date of the
    invoice' and (e) divides by sixty, so counting the invoice month as the
    first makes them sixty and settles the expiry month with no part-month
    arithmetic."""
    inv = date(2025, 4, 10)
    assert period_index(inv, date(2030, 3, 1)) == USEFUL_LIFE_MONTHS       # 60
    assert period_index(inv, date(2030, 4, 1)) == USEFUL_LIFE_MONTHS + 1   # 61


def test_the_last_month_of_the_life_still_apportions():
    r = compute([_good(cgst=60_000)], period="032030", period_start=date(2030, 3, 1),
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.lines[0].included is True
    assert r.lines[0].period_index == 60


def test_the_month_after_it_does_not():
    r = compute([_good(cgst=60_000)], period="042030", period_start=date(2030, 4, 1),
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.lines[0].included is False
    assert "five-year useful life ran out" in r.lines[0].reason
    assert r.te_paise["cgst"] == 0


def test_an_asset_bought_after_the_period_does_not_apportion():
    r = compute([_good(inv=date(2025, 9, 1), cgst=60_000)], period="042025",
                period_start=APR, turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.lines[0].included is False
    assert "Acquired after this tax period" in r.lines[0].reason


def test_two_assets_in_one_month_take_the_same_instalment_whatever_the_day():
    """A tax period is a month. An asset invoiced on the 2nd and one invoiced
    on the 28th of the same month take their first instalment in the same
    return, so the count is calendar-month arithmetic and not days."""
    early = _good("Early", inv=date(2025, 4, 2), cgst=60_000)
    late = _good("Late", inv=date(2025, 4, 28), cgst=60_000)
    r = compute([early, late], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert {ln.period_index for ln in r.lines} == {1}


# ── The three uses ───────────────────────────────────────────────────────────

def test_an_unclassified_asset_is_left_out_and_named():
    """Guessing is unsafe in BOTH directions — assuming common reverses credit
    §16(1) gives, assuming exclusively taxable leaves Te unpaid with 43(1)(h)
    interest running. So it is reported, the same shape as
    vendors.msme_status."""
    r = compute([_good(cgst=6_00_000, use=None)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert r.lines[0].included is False
    assert r.lines[0].reason == rule_43.GAP_USE_NOT_CLASSIFIED
    assert len(r.gaps) == 1
    assert "no Rule 43 use recorded" in r.gaps[0]


def test_exclusively_exempt_reverses_nothing_because_nothing_was_credited():
    """43(1)(a) — no credit was available in the first place, so there is
    nothing to apportion. Not the same as a nil Te on a common asset."""
    r = compute([_good(cgst=6_00_000, use=USE_EXCLUSIVELY_EXEMPT)],
                period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert "43(1)(a)" in r.lines[0].reason
    assert r.gaps == ()


def test_exclusively_taxable_keeps_the_whole_credit():
    """43(1)(b) — supplies 'other than exempted supplies', zero-rated
    included. Rule 43 never reaches the asset."""
    r = compute([_good(cgst=6_00_000, use=USE_EXCLUSIVELY_TAXABLE)],
                period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert "43(1)(b)" in r.lines[0].reason
    assert r.gaps == ()


def test_an_asset_whose_credit_status_is_unknown_is_a_gap_not_a_zero():
    """`itc_eligible` is NULL on every asset predating migration 343. Rule 43
    apportions credit ACTUALLY TAKEN, so an asset that may never have had any
    is reported rather than reversed."""
    r = compute([_good(cgst=6_00_000, eligible=None)], period="042025",
                period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert r.lines[0].reason == rule_43.GAP_ITC_NOT_STATED
    assert any("CLAIMED as credit is not recorded" in g for g in r.gaps)


def test_blocked_credit_is_excluded_and_is_not_a_gap():
    """§17(5) tax was never claimed — migration 343 capitalises it into the
    asset's cost, where it depreciates. There is nothing to apportion and
    nothing for the CA to go and record."""
    r = compute([_good(cgst=6_00_000, eligible=False)], period="042025",
                period_start=APR,
                turnover=Turnover(exempt_paise=50_00_000, total_paise=1_00_00_000))
    assert r.te_paise["cgst"] == 0
    assert "§17(5)" in r.lines[0].reason
    assert r.gaps == ()


def test_an_asset_with_no_acquisition_date_is_a_gap():
    r = compute([_good(inv=None, cgst=6_00_000)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.lines[0].reason == rule_43.GAP_NO_INVOICE_DATE
    assert any("date of the invoice" in g for g in r.gaps)


def test_an_asset_with_no_gst_recorded_is_not_a_gap():
    """Plenty of assets legitimately carry no tax — bought before registration,
    from an unregistered supplier, or constructed. There is nothing for the CA
    to go and look up, so it is a reason and not a gap."""
    r = compute([_good(cgst=0, sgst=0, igst=0)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=1))
    assert r.lines[0].included is False
    assert "No GST recorded" in r.lines[0].reason
    assert r.gaps == ()


# ── The refusals and the caveats ─────────────────────────────────────────────

def test_no_turnover_at_all_is_REFUSED_rather_than_divided_by_zero():
    """The proviso to Rule 43(1)(g): where the turnover of a period is nil or
    unavailable, E and F are taken from the LAST period for which they are.
    Those are a different period's figures and are not invented here."""
    r = compute([_good(cgst=6_00_000)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=0, total_paise=0))
    assert r.refused is True
    assert r.te_paise == {"igst": 0, "cgst": 0, "sgst": 0}
    assert "last tax period" in r.refusal


def test_turnover_not_supplied_at_all_is_the_same_refusal():
    r = compute([_good(cgst=6_00_000)], period="042025", period_start=APR,
                turnover=None)
    assert r.refused is True
    assert r.refusal


def test_the_refusal_still_reports_the_assets():
    """A CA who has to go and find last period's turnover still needs to know
    which assets the working covers, and which are unclassified."""
    r = compute([_good(cgst=6_00_000), _good("Unmarked", cgst=1, use=None)],
                period="042025", period_start=APR, turnover=None)
    assert len(r.lines) == 2
    assert len(r.gaps) == 1
    assert r.common_credit_paise["cgst"] == 6_00_000


def test_every_answer_says_the_transition_is_not_modelled():
    """The provisos to 43(1)(c) and (d) reduce an asset's input tax by five
    percentage points per quarter when it MOVES between uses. One column
    records what an asset is now, not when it changed."""
    r = compute([], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=2))
    assert rule_43.TRANSITION_NOT_MODELLED in r.caveats


def test_every_answer_says_the_excise_exclusion_is_not_modelled():
    """The Explanation to 43(1)(g) takes central and state excise on petroleum,
    tobacco and alcohol out of both E and F. Nothing separates them from the
    non-GST bucket here."""
    r = compute([], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=2))
    assert rule_43.EXCISE_EXCLUSION_NOT_MODELLED in r.caveats


def test_nothing_running_says_so_rather_than_reporting_a_bare_zero():
    r = compute([_good(cgst=6_00_000, use=USE_EXCLUSIVELY_TAXABLE)],
                period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=1, total_paise=2))
    assert any("nothing to apportion" in c for c in r.caveats)


# ── The shape of the answer ──────────────────────────────────────────────────

def test_to_dict_carries_the_total_and_the_undivided_aggregate():
    """`common_credit_paise` is Tr × 60 — kept undivided so a reader can check
    the arithmetic without re-deriving the rounding."""
    d = compute([_good(cgst=90_000)], period="042025", period_start=APR,
                turnover=Turnover(exempt_paise=20_00_000,
                                  total_paise=1_00_00_000)).to_dict()
    assert d["te_total_paise"] == sum(d["te_paise"].values())
    assert d["common_credit_paise"]["cgst"] == 90_000
    assert d["useful_life_months"] == 60
    assert d["period"] == "042025"


def test_a_negative_tax_figure_cannot_pull_the_credit_down():
    """`credit_paise` clamps at zero. A negative amount on a capital good is
    not a refund of credit, it is a data error, and letting it net against
    another asset's credit would understate Te silently."""
    g = CapitalGood("x", "Odd", date(2025, 4, 1), cgst_paise=-500,
                    itc_eligible=True, use=USE_COMMON)
    assert g.credit_paise("cgst") == 0


def test_the_valid_uses_are_the_three_the_check_constraint_allows():
    """models/accounting.py validates against this tuple and migration 372's
    CHECK spells the same three. A fourth accepted here would be refused by the
    database, which is a 500 rather than a 422."""
    assert rule_43.VALID_USES == ("common", "exclusively_exempt",
                                  "exclusively_taxable")

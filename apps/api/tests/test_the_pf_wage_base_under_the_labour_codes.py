"""The s.2(y) wage base: the 50% rule, and everything it must NOT disturb.

WHY THIS EXISTS

    Until 21-11-2025 the PF base was `basic + DA` and that was right. The Code
    on Social Security subsumed the EPF Act that day and adopts the Code on
    Wages §2(y) definition, which caps the listed exclusions at half of total
    remuneration and deems the excess to be wages.

    The failure this prevents is silent and it lands in somebody's provident
    fund: on a total of ₹28,000 split ₹10,000 basic / ₹18,000 HRA the base is
    ₹14,000 and not ₹10,000, so employee PF is ₹1,680 and not ₹1,200 — ₹480 a
    month understated on each side, with the employer short by the same again.

    Most of these tests are about what must NOT change: the ordinary salary
    structure, anyone above the ₹15,000 ceiling, and every month before
    commencement. A rule that fires when it should not would move money the
    other way, and that is just as wrong.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.payroll import wage_base
from routers.payroll import _compute_slip


# ── the domain function ──────────────────────────────────────────────────────

GOVERNED = dict(fy_label="2025-26", month=12)   # December 2025


def test_the_documented_failure_case_is_now_computed_correctly():
    """₹28,000 as ₹10,000 basic + ₹18,000 HRA. Exclusions are 64% of total."""
    r = wage_base.compute(wage_components_paise=10_000_00,
                          excluded_components_paise=18_000_00, **GOVERNED)
    assert r.total_remuneration_paise == 28_000_00
    assert r.deemed_addback_paise == 4_000_00     # 18,000 - half of 28,000
    assert r.wages_paise == 14_000_00
    assert r.rule_applied is True
    assert r.addback_applies is True


def test_the_ordinary_structure_is_untouched():
    """basic 40% + HRA 20% + LTA 5% of ₹28,000: exclusions are 25%, well under."""
    r = wage_base.compute(
        wage_components_paise=(11_200 + 1_400 + 7_400) * 100,   # basic, medical, special
        excluded_components_paise=(5_600 + 2_400) * 100,        # HRA, LTA
        **GOVERNED)
    assert r.deemed_addback_paise == 0
    assert r.addback_applies is False
    # rule_applied says the PERIOD is governed; addback says it bit. Different
    # questions, and conflating them would hide the common case.
    assert r.rule_applied is True


def test_exactly_fifty_percent_does_not_add_back():
    """The proviso bites on EXCESS. Half is not excess."""
    r = wage_base.compute(wage_components_paise=10_000_00,
                          excluded_components_paise=10_000_00, **GOVERNED)
    assert r.deemed_addback_paise == 0
    assert r.wages_paise == 10_000_00


def test_one_paise_over_half_adds_back_one_paise():
    r = wage_base.compute(wage_components_paise=10_000_00,
                          excluded_components_paise=10_000_01, **GOVERNED)
    assert r.deemed_addback_paise == 1


# ── the period test ──────────────────────────────────────────────────────────

def test_a_month_before_commencement_reproduces_the_old_base_exactly():
    r = wage_base.compute(wage_components_paise=10_000_00,
                          excluded_components_paise=18_000_00,
                          fy_label="2025-26", month=10)     # October 2025
    assert r.rule_applied is False
    assert r.deemed_addback_paise == 0
    assert r.wages_paise == 10_000_00


def test_the_commencement_month_itself_is_governed():
    """The Codes commenced 21-11-2025, part-way through November.

    A month is paid as one thing; splitting it at the 21st would produce a wage
    base for a fortnight, which no return has a column for. The test is on the
    month END.
    """
    assert wage_base.rule_in_force("2025-26", 11) is True
    assert wage_base.rule_in_force("2025-26", 10) is False


def test_january_belongs_to_the_second_calendar_year_of_the_label():
    """FY 2025-26 runs Apr 2025 to Mar 2026, so month 1 is January 2026."""
    assert wage_base._last_day_of("2025-26", 1) == date(2026, 1, 31)
    assert wage_base._last_day_of("2025-26", 4) == date(2025, 4, 30)
    assert wage_base._last_day_of("2024-25", 2) == date(2025, 2, 28)   # non-leap
    assert wage_base._last_day_of("2023-24", 2) == date(2024, 2, 29)   # leap


@pytest.mark.parametrize("fy,month", [(None, 12), ("2025-26", None),
                                      ("", 12), ("2025-26", 0), ("2025-26", 13),
                                      ("nonsense", 12)])
def test_an_unknown_or_malformed_period_falls_back_to_the_old_rule(fy, month):
    """Not an exception, and not the new rule.

    A caller that cannot say which month it is computing must not have a rule
    applied to a period it may not govern — that would rewrite historic
    payslips. Falling back to the pre-Code base is the conservative answer.
    """
    assert wage_base.rule_in_force(fy, month) is False
    r = wage_base.compute(wage_components_paise=10_000_00,
                          excluded_components_paise=18_000_00,
                          fy_label=fy, month=month)
    assert r.wages_paise == 10_000_00


# ── the classification ───────────────────────────────────────────────────────

def test_medical_special_and_other_stay_on_the_wage_side():
    """Only HRA (clause f) and LTA (clause d) are excluded by name.

    A cash medical allowance is not clause (b), which is amenities in kind
    excluded by government order. A special allowance is not clause (e), which
    is about defraying expenses actually entailed by the job — and
    *RPFC v. Vivekananda Vidyamandir* (2019) held universally-paid allowances to
    be basic wages. Anything unclassified defaults to wages because that is the
    direction that cannot under-deduct.
    """
    emp = dict(basic_paise=10_000_00, hra_percent=0, da_percent=0,
               medical_paise=5_000_00, special_allowance_paise=8_000_00,
               other_allowances_paise=5_000_00,
               pf_applicable=True, esi_applicable=False, pt_applicable=False)
    slip = _compute_slip(emp, fy="2025-26", pt_month=12)
    # No exclusions at all, so nothing to add back and the base is everything.
    assert slip["pf_wages_addback_paise"] == 0
    assert slip["pf_wages_paise"] == 28_000_00


# ── end to end through the slip, which is where the money actually moves ─────

def _breaching_employee():
    """₹10,000 basic with HRA at 180% of it — the low-basic/high-allowance shape."""
    return dict(basic_paise=10_000_00, hra_percent=180, da_percent=0,
                pf_applicable=True, esi_applicable=False, pt_applicable=False)


def test_the_slip_deducts_the_higher_figure_for_a_governed_month():
    slip = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=12)
    assert slip["hra_paise"] == 18_000_00
    assert slip["pf_wages_paise"] == 14_000_00
    assert slip["pf_wages_addback_paise"] == 4_000_00
    assert slip["pf_wages_rule_applied"] is True
    assert slip["pf_employee_paise"] == 1_680_00        # 12% of 14,000, not 1,200


def test_the_same_employee_in_a_pre_code_month_is_unchanged():
    slip = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=10)
    assert slip["pf_wages_paise"] == 10_000_00
    assert slip["pf_wages_addback_paise"] == 0
    assert slip["pf_wages_rule_applied"] is False
    assert slip["pf_employee_paise"] == 1_200_00


def test_above_the_ceiling_the_add_back_changes_nothing():
    """₹15,000 is unchanged, and it is what bounds this whole problem.

    Basic alone already exceeds the ceiling, so `min(wages, 15000)` was giving
    the right answer before and gives the same one now.
    """
    emp = dict(basic_paise=40_000_00, hra_percent=180, da_percent=0,
               pf_applicable=True, esi_applicable=False, pt_applicable=False)
    governed = _compute_slip(emp, fy="2025-26", pt_month=12)
    before   = _compute_slip(emp, fy="2025-26", pt_month=10)
    assert governed["pf_employee_paise"] == before["pf_employee_paise"] == 1_800_00


def test_the_employer_side_moves_by_the_same_amount():
    """The under-deduction was on BOTH sides; so is the correction."""
    governed = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=12)
    before   = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=10)
    assert governed["pf_employee_paise"] - before["pf_employee_paise"] == 480_00
    assert governed["pf_employer_paise"] - before["pf_employer_paise"] == 480_00


def test_esi_is_deliberately_not_touched():
    """ESI may err the OTHER way and that is unconfirmed — see the module.

    Pinned so a later change to the ESI base is a deliberate act with its own
    reasoning, rather than something that rides along with this one.
    """
    emp = dict(basic_paise=10_000_00, hra_percent=100, da_percent=0,
               pf_applicable=False, esi_applicable=True, pt_applicable=False)
    governed = _compute_slip(emp, fy="2025-26", pt_month=12)
    before   = _compute_slip(emp, fy="2025-26", pt_month=10)
    assert governed["esi_employee_paise"] == before["esi_employee_paise"]


def test_a_one_time_bonus_does_not_shrink_the_add_back():
    """One-time earnings are outside the §2(y) denominator, on purpose.

    Putting a bonus into total remuneration would raise the 50% half and
    SHRINK the add-back — the direction that under-deducts. A bonus is an
    exclusion at clause (a) anyway.
    """
    from domain.payroll.one_time_earnings import Bundle

    plain = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=12)
    with_bonus = _compute_slip(
        _breaching_employee(), fy="2025-26", pt_month=12,
        one_time=Bundle(total_paise=50_000_00, taxable_paise=50_000_00,
                        lines=("a-bonus",)))
    # The bonus reaches gross, so the slip is genuinely different...
    assert with_bonus["gross_paise"] > plain["gross_paise"]
    # ...but it did not move the wage test.
    assert with_bonus["pf_wages_addback_paise"] == plain["pf_wages_addback_paise"] == 4_000_00
    assert with_bonus["pf_wages_paise"] == plain["pf_wages_paise"]


def test_arrears_of_basic_still_reach_the_pf_base_on_top():
    """`ot.pf_wages_paise` is added AFTER the §2(y) figure, as it always was."""
    from domain.payroll.one_time_earnings import Bundle

    slip = _compute_slip(_breaching_employee(), fy="2025-26", pt_month=12,
                         one_time=Bundle(total_paise=2_000_00, pf_wages_paise=2_000_00,
                                         taxable_paise=2_000_00, lines=("arrears",)))
    # 14,000 from the wage base + 2,000 arrears, then the 15,000 ceiling bites.
    assert slip["pf_wages_paise"] == 14_000_00      # the §2(y) figure alone
    assert slip["pf_employee_paise"] == 1_800_00    # 12% of the capped 15,000

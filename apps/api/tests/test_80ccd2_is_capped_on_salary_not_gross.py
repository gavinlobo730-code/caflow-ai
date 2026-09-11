"""§80CCD(2)'s cap is a percentage of SALARY, not of gross pay (PAY-22).

THE SECTION, AND THE WORD THAT MATTERS

§80CCD(2) allows the employer's NPS contribution as a deduction, capped at a
percentage "of his salary in the previous year". The Explanation to §80CCD
defines that word:

    "'salary' includes dearness allowance, if the terms of employment so
     provide, but excludes all other allowances and perquisites."

So the base is basic + DA. Gross pay is basic + DA PLUS precisely the
allowances the Explanation excludes.

WHAT WAS WRONG

`routers/payroll.py` computed `(basic + da) * months_in_year` and passed it as
`basic_plus_da_paise` — the §10(13A) HRA base — and passed NOTHING for
`salary_for_80ccd2_paise`. `declarations._build_request` therefore fell back to
`gross_salary_paise`, and the cap was computed on the wrong figure.

Measured on the engine before the fix, for one employee on ₹30,00,000 gross with
₹12,00,000 basic + DA who declared ₹2,50,000 of employer NPS:

    cap on gross     (10% of 30,00,000) = ₹3,00,000  -> ₹2,50,000 allowed
    cap on basic+DA  (10% of 12,00,000) = ₹1,20,000  -> ₹1,20,000 allowed
    tax                                   ₹3,97,800 vs ₹4,38,360

₹40,560 under-withheld for the year, per employee, and §192(1) makes the
EMPLOYER answerable for a correct deduction.

WHY IT SURVIVED, WHICH IS THE REUSABLE PART

Payroll holds no employer-side NPS figure at all — nothing anywhere passes
`employer_nps_paise`. So the wrong base is only reachable when an EMPLOYEE
declares an §80CCD(2) line, which `_apply_declaration` adds to
`employer_nps_80ccd2_paise`. Every test of the engine itself passes the base
explicitly, so none of them could see it; and with no declaration the deduction
is zero and the base is irrelevant. The defect needed both halves at once.
"""
from __future__ import annotations

from domain.income_tax.itr_engine import (
    ITREngine, ITRComputeRequest,
    LIMIT_80CCD2_OTHER_PERCENT, LIMIT_80CCD2_GOVT_PERCENT,
)

FY = "2025-26"
GROSS = 30_00_000 * 100
BASIC_DA = 12_00_000 * 100
NPS = 2_50_000 * 100


def _compute(base, nps=NPS, govt=False, gross=GROSS):
    return ITREngine().compute(ITRComputeRequest(
        gross_salary_paise=gross, employer_nps_80ccd2_paise=nps,
        salary_for_80ccd2_paise=base, is_government_employee=govt,
        use_new_regime=True, fy=FY))


# ── the engine's own rule ────────────────────────────────────────────────────

def test_the_cap_is_a_percentage_of_the_salary_base_it_is_given():
    r = _compute(BASIC_DA)
    assert r.deduction_80ccd2_paise == BASIC_DA * LIMIT_80CCD2_OTHER_PERCENT // 100


def test_a_government_employee_gets_the_wider_percentage():
    """§80CCD(2)'s two limbs: 14% for a Central or State Government employer."""
    assert LIMIT_80CCD2_GOVT_PERCENT > LIMIT_80CCD2_OTHER_PERCENT
    r = _compute(BASIC_DA, govt=True)
    assert r.deduction_80ccd2_paise == BASIC_DA * LIMIT_80CCD2_GOVT_PERCENT // 100


def test_the_contribution_itself_still_caps_the_deduction():
    """The allowance is the LESSER of the contribution and the percentage — a
    small contribution is not grossed up to the cap."""
    small = 10_000 * 100
    assert _compute(BASIC_DA, nps=small).deduction_80ccd2_paise == small


def test_gross_gives_a_bigger_cap_than_salary_and_that_is_the_defect():
    """The two figures the fallback chose between, side by side."""
    on_salary = _compute(BASIC_DA).deduction_80ccd2_paise
    on_gross = _compute(None).deduction_80ccd2_paise
    assert on_gross > on_salary, (
        "if gross no longer exceeds basic+DA this fixture stopped exercising "
        "the defect — pick an employee whose allowances are a real share of pay")
    assert on_gross == NPS and on_salary == BASIC_DA * LIMIT_80CCD2_OTHER_PERCENT // 100


def test_the_wrong_base_under_withholds_and_the_employer_answers_for_it():
    correct = _compute(BASIC_DA).total_tax_paise
    wrong = _compute(None).total_tax_paise
    assert wrong < correct, "the fallback to gross cuts the tax, which is the harm"
    assert correct - wrong == 40_560 * 100, (
        "the figure in this module's docstring — if it moves, the docstring is "
        "now wrong and says something specific that is false")


# ── payroll passes it, which is the fix ──────────────────────────────────────

def test_payroll_supplies_the_salary_base_and_will_not_start_without_it():
    """REQUIRED, not defaulted, and that is deliberate.

    A default of 0 would cap the deduction at nil — over-withholding, which is
    the safe direction but silently wrong. A default of gross is what this fixed.
    Required means the next caller has to decide, and gets a TypeError rather
    than a number if they do not.
    """
    import inspect
    from routers.payroll import _monthly_tds

    sig = inspect.signature(_monthly_tds)
    p = sig.parameters.get("salary_for_80ccd2_paise")
    assert p is not None, (
        "_monthly_tds must take the §80CCD(2) salary base; without it "
        "declarations._build_request falls back to gross_salary_paise")
    assert p.default is inspect.Parameter.empty, "it must have no default"
    assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_hra_base_and_the_80ccd2_base_are_the_same_figure():
    """§10(13A) and the Explanation to §80CCD both mean basic + DA. They are one
    fact read by two sections, so payroll computes it once — and the source is
    pinned here because a later edit that recomputed one of them differently
    would be a second implementation of the same statutory phrase."""
    import re
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "routers" / "payroll.py"
    text = src.read_text()
    for arg in ("basic_plus_da_paise", "salary_for_80ccd2_paise"):
        m = re.search(rf"{arg}=\(basic \+ da\) \* months_in_year,", text)
        assert m, f"{arg} should be the recurring (basic + da) * months_in_year"

"""
Employee income-tax declarations — IT Act §192, §115BAC, Rule 26C.

Every figure asserted here is arrived at by hand from the statute and checked
against the FY 2025-26 rates in domain/income_tax/statutory_rates.py, not read
back off the implementation.
"""
import pytest

from domain.payroll import declarations as D
from domain.income_tax.itr_engine import ITRComputeRequest, ITREngine
from routers.payroll import (
    _monthly_tds, _months_remaining_for_spread, _verified_only_from_month,
    PROOF_CUTOFF_MONTH_OF_FY,
)

FY = "2025-26"


def _decl(**kw) -> D.Declaration:
    kw.setdefault("employee_id", "e1")
    kw.setdefault("fy", FY)
    return D.Declaration(**kw)


def _tax(decl, salary_paise, *, verified_only=False, pt=0):
    return D.withholding_tax_paise(
        decl=decl, projected_annual_salary_paise=salary_paise, fy=FY,
        verified_only=verified_only, professional_tax_paise=pt)


# ── The regime intimation ────────────────────────────────────────────────────

def test_no_declaration_means_the_default_regime():
    """§115BAC(1A) is the default. CBDT Circular 04/2023: absent an intimation
    the employer withholds under it."""
    # ₹12,75,000 gross - ₹75,000 §16(ia) = ₹12,00,000, which §87A reduces to nil.
    assert _tax(None, 12_75_000 * 100) == 0
    # A rupee more and the rebate's marginal relief takes over rather than the
    # whole slab charge landing at once.
    assert _tax(None, 12_80_000 * 100) > 0


def test_old_regime_intimation_changes_the_basis():
    at_15l_new = _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100)
    at_15l_old = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)
    # Old regime is worse on the slabs alone, before any deduction is claimed —
    # which is exactly why an employee only opts out when they have deductions.
    assert at_15l_old > at_15l_new


def test_the_intimation_is_not_the_115bac_6_election():
    """CBDT Circular 04/2023: intimating a regime to the employer 'would not
    amount to exercising option in terms of sub-section (6) of section 115BAC'.

    The declaration must say so, because an employee with business income who
    tells payroll 'old regime' and never files Form 10-IEA is withheld on one
    basis and assessed on the other.
    """
    notices = D.notices(_decl(regime=D.REGIME_OLD))
    assert any("10-IEA" in n for n in notices), notices
    assert any("115BAC(6)" in n for n in notices), notices


# ── Chapter VI-A and the regime gate ─────────────────────────────────────────

def test_80c_reduces_tax_under_the_old_regime_by_exactly_the_slab_rate():
    d = _decl(regime=D.REGIME_OLD)
    d.items.append(D.DeclarationItem(section=D.SECTION_80C,
                                     amount_declared_paise=1_50_000 * 100))
    without = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)
    with_80c = _tax(d, 15_00_000 * 100)
    # ₹1,50,000 at the 30% slab, plus 4% cess = ₹46,800.
    assert without - with_80c == 46_800 * 100


def test_80c_reduces_nothing_under_the_new_regime():
    """§115BAC(2) allows no §80C. The claim is recorded and has no effect."""
    d = _decl(regime=D.REGIME_NEW)
    d.items.append(D.DeclarationItem(section=D.SECTION_80C,
                                     amount_declared_paise=1_50_000 * 100))
    assert _tax(d, 15_00_000 * 100) == _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100)


def test_80ccd2_survives_the_new_regime():
    """The one Chapter VI-A head a salaried employee keeps under §115BAC(2)."""
    d = _decl(regime=D.REGIME_NEW)
    d.items.append(D.DeclarationItem(section=D.SECTION_80CCD2,
                                     amount_declared_paise=50_000 * 100))
    assert _tax(d, 15_00_000 * 100) < _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100)


def test_a_new_regime_employee_is_told_their_claims_do_nothing():
    d = _decl(regime=D.REGIME_NEW, rent_paid_declared_paise=2_40_000 * 100)
    d.items.append(D.DeclarationItem(section=D.SECTION_80C,
                                     amount_declared_paise=1_50_000 * 100))
    notices = D.notices(d)
    assert any("80C" in n for n in notices), notices
    assert any("10(13A)" in n for n in notices), notices


def test_an_unrecognised_section_is_refused_not_bucketed():
    d = _decl(regime=D.REGIME_OLD)
    d.items.append(D.DeclarationItem(section="80XYZ", amount_declared_paise=10_000 * 100))
    problems = D.validate(d)
    assert any("80XYZ" in p for p in problems), problems


# ── §80TTA must have income behind it ────────────────────────────────────────

def test_80tta_is_capped_at_the_interest_actually_reported():
    """§80TTA(1) deducts interest 'included in the gross total income'.

    Uncapped, an employee who claimed ₹10,000 of §80TTA and reported no
    interest income got the relief on income never brought to tax.
    """
    claimed_only = _decl(regime=D.REGIME_OLD)
    claimed_only.items.append(D.DeclarationItem(section=D.SECTION_80TTA,
                                                amount_declared_paise=10_000 * 100))
    bare = _decl(regime=D.REGIME_OLD)
    assert _tax(claimed_only, 15_00_000 * 100) == _tax(bare, 15_00_000 * 100)

    # Reported as well as claimed, the two cancel exactly: ₹10,000 into gross
    # total income and ₹10,000 out again as the deduction.
    both = _decl(regime=D.REGIME_OLD, other_income_declared_paise=10_000 * 100)
    both.items.append(D.DeclarationItem(section=D.SECTION_80TTA,
                                        amount_declared_paise=10_000 * 100))
    assert _tax(both, 15_00_000 * 100) == _tax(bare, 15_00_000 * 100)


# ── §192(2B) and its proviso ─────────────────────────────────────────────────

def test_other_income_increases_the_withholding():
    d = _decl(regime=D.REGIME_NEW, other_income_declared_paise=5_00_000 * 100)
    assert _tax(d, 15_00_000 * 100) > _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100)


def test_reporting_other_income_can_never_reduce_the_withholding():
    """The §192(2B) proviso, pinned as the invariant it is.

    Tax is monotonic in income here — marginal relief caps how fast tax rises
    and never reverses it — so the guard in withholding_tax_paise does not
    currently bind. This test is what says so, and what would fail if a future
    change (a third-party TDS credit, a deduction keyed to other income) made
    it bind.
    """
    engine = ITREngine()
    for salary in range(5_00_000, 60_00_000, 2_50_000):
        for other in (10_000, 1_00_000, 5_00_000):
            alone = engine.compute(ITRComputeRequest(
                gross_salary_paise=salary * 100, fy=FY)).total_tax_paise
            with_other = engine.compute(ITRComputeRequest(
                gross_salary_paise=salary * 100,
                other_income_paise=other * 100, fy=FY)).total_tax_paise
            assert with_other >= alone, (salary, other, alone, with_other)


def test_a_house_property_loss_is_the_provisos_one_exception():
    """§192(2B)'s proviso lets a house property loss — and only that — reduce
    the tax deductible. §115BAC(2)(i) then bars it under the new regime."""
    old = _decl(regime=D.REGIME_OLD, house_property_loss_declared_paise=2_00_000 * 100)
    assert _tax(old, 15_00_000 * 100) < _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)

    new = _decl(regime=D.REGIME_NEW, house_property_loss_declared_paise=2_00_000 * 100)
    assert _tax(new, 15_00_000 * 100) == _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100)


# ── Rule 26C / Form 12BB particulars ─────────────────────────────────────────

def test_landlord_pan_is_required_once_rent_passes_one_lakh():
    under = _decl(rent_paid_declared_paise=1_00_000 * 100, landlord_name="A Nair")
    assert not any("PAN" in p for p in D.validate(under))

    over = _decl(rent_paid_declared_paise=1_00_001 * 100, landlord_name="A Nair")
    assert any("Rule 26C" in p for p in D.validate(over)), D.validate(over)

    ok = _decl(rent_paid_declared_paise=2_40_000 * 100, landlord_name="A Nair",
               landlord_pan="ABCDE1234F")
    assert not any("PAN" in p for p in D.validate(ok)), D.validate(ok)


def test_a_malformed_landlord_pan_is_refused():
    d = _decl(rent_paid_declared_paise=2_40_000 * 100, landlord_name="A Nair",
              landlord_pan="ABCD1234F")
    assert any("not a valid PAN" in p for p in D.validate(d))


def test_lender_pan_is_required_for_24b_with_no_threshold():
    """Unlike the landlord's, Rule 26C attaches no rent threshold to this one."""
    d = _decl(regime=D.REGIME_OLD, home_loan_interest_declared_paise=1 * 100)
    assert any("lender's PAN" in p for p in D.validate(d)), D.validate(d)


def test_a_proof_cannot_support_more_than_was_claimed():
    d = _decl(regime=D.REGIME_OLD)
    d.items.append(D.DeclarationItem(
        section=D.SECTION_80C, amount_declared_paise=50_000 * 100,
        amount_verified_paise=1_50_000 * 100, status=D.ITEM_VERIFIED))
    assert any("never more" in p for p in D.validate(d)), D.validate(d)


# ── Declared versus verified ─────────────────────────────────────────────────

def test_a_declaration_works_on_trust_until_the_proof_cutoff():
    d = _decl(regime=D.REGIME_OLD)
    d.items.append(D.DeclarationItem(section=D.SECTION_80C,
                                     amount_declared_paise=1_50_000 * 100))
    bare = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)
    assert _tax(d, 15_00_000 * 100, verified_only=False) < bare
    # From the fourth quarter it stops reducing tax, because §192(1) makes the
    # employer answerable and there is still salary left to correct against.
    assert _tax(d, 15_00_000 * 100, verified_only=True) == bare


def test_a_verified_line_keeps_working_after_the_cutoff():
    d = _decl(regime=D.REGIME_OLD, proofs_verified=True)
    d.items.append(D.DeclarationItem(
        section=D.SECTION_80C, amount_declared_paise=1_50_000 * 100,
        amount_verified_paise=1_50_000 * 100, status=D.ITEM_VERIFIED))
    bare = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)
    assert _tax(d, 15_00_000 * 100, verified_only=True) < bare


def test_a_rejected_line_is_worth_nothing_on_either_basis():
    d = _decl(regime=D.REGIME_OLD)
    d.items.append(D.DeclarationItem(
        section=D.SECTION_80C, amount_declared_paise=1_50_000 * 100,
        status=D.ITEM_REJECTED))
    bare = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100)
    assert _tax(d, 15_00_000 * 100, verified_only=False) == bare
    assert _tax(d, 15_00_000 * 100, verified_only=True) == bare


def test_the_proof_cutoff_falls_in_the_fourth_quarter():
    d = _decl()
    assert PROOF_CUTOFF_MONTH_OF_FY == 10          # January
    assert _verified_only_from_month(12, d) is False   # December, month 9 of the FY
    assert _verified_only_from_month(1, d) is True     # January,  month 10
    assert _verified_only_from_month(3, d) is True     # March,    month 12
    # No declaration, nothing to gate.
    assert _verified_only_from_month(1, None) is False


# ── §192(3): spreading the year's tax ────────────────────────────────────────

def test_with_no_history_the_year_is_spread_over_twelve_months():
    """The mid-year-onboarding trap.

    A firm that starts using this system in October has been deducting since
    April through whatever they used before. Those deductions are real, are on
    the employee's 26AS and are invisible here. Spreading the whole year's tax
    over the remaining six months would double every payslip's TDS, and nothing
    on the payslip would look wrong — so the spread counts months THIS payroll
    has paid, not months of the calendar.
    """
    assert _months_remaining_for_spread(0) == 12
    common = dict(declaration=None, annual_gross_paise=15_00_000 * 100,
                  basic_plus_da_paise=0, hra_received_paise=0,
                  professional_tax_paise=0, fy=FY)
    april = _monthly_tds(month=4, tds_already_deducted_paise=0,
                         months_already_paid=0, **common)
    october = _monthly_tds(month=10, tds_already_deducted_paise=0,
                           months_already_paid=0, **common)
    assert april == october


def test_192_3_spreads_what_is_left_over_the_months_that_remain():
    """§192(3): the employer may 'increase or reduce the amount to be deducted
    ... for the purpose of adjusting any excess or deficiency arising out of any
    previous deduction ... during the financial year'.

    Without it, an employee who proves ₹1,50,000 of §80C in December has Apr-Nov
    withheld at the undeclared rate and no mechanism ever gives it back.
    """
    assert _months_remaining_for_spread(8) == 4
    common = dict(declaration=None, annual_gross_paise=15_00_000 * 100,
                  basic_plus_da_paise=0, hra_received_paise=0,
                  professional_tax_paise=0, fy=FY)
    # Annual tax on ₹15,00,000 under the new regime is ₹97,500; eight months at
    # ₹8,125 is ₹65,000, leaving ₹32,500 over four months.
    assert _monthly_tds(month=12, tds_already_deducted_paise=65_000 * 100,
                        months_already_paid=8, **common) == 8_125 * 100


def test_over_withholding_is_never_refunded_through_the_payslip():
    """§192 authorises DEDUCTING tax, not paying it back. Where more has been
    withheld than the year now needs, the excess is refunded on assessment."""
    common = dict(declaration=None, annual_gross_paise=15_00_000 * 100,
                  basic_plus_da_paise=0, hra_received_paise=0,
                  professional_tax_paise=0, fy=FY)
    assert _monthly_tds(month=3, tds_already_deducted_paise=5_00_000 * 100,
                        months_already_paid=11, **common) == 0


def test_a_late_verified_declaration_trues_up_inside_the_year():
    """The whole point of applying §192(3).

    Compared like with like — the same employee on the same regime, with and
    without the proved §80C — the deduction for the months that remain falls,
    instead of the employee carrying the over-withholding to a refund claim a
    year later.
    """
    common = dict(annual_gross_paise=15_00_000 * 100, basic_plus_da_paise=0,
                  hra_received_paise=0, professional_tax_paise=0, fy=FY,
                  month=1, months_already_paid=9,
                  tds_already_deducted_paise=9 * 17_550 * 100)

    proved = _decl(regime=D.REGIME_OLD, proofs_verified=True)
    proved.items.append(D.DeclarationItem(
        section=D.SECTION_80C, amount_declared_paise=1_50_000 * 100,
        amount_verified_paise=1_50_000 * 100, status=D.ITEM_VERIFIED))

    with_proof = _monthly_tds(declaration=proved, **common)
    without = _monthly_tds(declaration=_decl(regime=D.REGIME_OLD), **common)
    assert with_proof < without

    # And the arithmetic is exactly §192(3)'s: annual tax on ₹15,00,000 under
    # the old regime after §16(ia) ₹50,000 and §80C ₹1,50,000 is ₹2,10,600.
    # Nine months at ₹17,550 is ₹1,57,950, leaving ₹52,650 over three months.
    assert with_proof == 17_550 * 100


def test_an_old_regime_intimation_is_not_automatically_the_cheaper_one():
    """Worth pinning, because it is the mistake employees make.

    At ₹15,00,000 with only ₹1,50,000 of §80C, the old regime costs ₹2,10,600
    against the new regime's ₹97,500. Payroll withholds on what was intimated
    and does not second-guess it — but it must not be built on an assumption
    that opting out always saves tax.
    """
    with_80c = _decl(regime=D.REGIME_OLD)
    with_80c.items.append(D.DeclarationItem(section=D.SECTION_80C,
                                            amount_declared_paise=1_50_000 * 100))
    assert _tax(with_80c, 15_00_000 * 100) == 2_10_600 * 100
    assert _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100) == 97_500 * 100


# ── §16(iii) under the two regimes ───────────────────────────────────────────

def test_professional_tax_reduces_tax_only_under_the_old_regime():
    """§115BAC(2)(i) computes total income without any section 16 deduction
    save clause (ia). Professional tax under clause (iii) is not available."""
    pt = 2_500 * 100
    old_with = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100, pt=pt)
    old_without = _tax(_decl(regime=D.REGIME_OLD), 15_00_000 * 100, pt=0)
    assert old_with < old_without

    new_with = _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100, pt=pt)
    new_without = _tax(_decl(regime=D.REGIME_NEW), 15_00_000 * 100, pt=0)
    assert new_with == new_without


# ── §192(1): the estimate is of THIS year's salary ───────────────────────────

def test_a_mid_year_joiner_is_projected_over_the_months_they_will_work():
    """§192(1) requires TDS on "the estimated income of the assessee under the
    head Salaries" FOR THAT FINANCIAL YEAR.

    For someone joining on 1 October that estimate is six months of salary, not
    twelve. Projecting twelve over-deducts severely and §192(3) cannot recover
    it, because the projection itself is what is wrong — the money comes back
    only on assessment, a year later.

    Measured before the fix: an October joiner on ₹2,00,000 a month, who earns
    ₹12,00,000 in the year and owes nothing after the §16(ia) deduction and the
    §87A rebate, had ₹1,46,250 withheld.
    """
    from routers.payroll import _months_employed_in_fy, _compute_slip

    assert _months_employed_in_fy("2025-10-01", "2025-26") == 6
    assert _months_employed_in_fy("2025-04-01", "2025-26") == 12
    assert _months_employed_in_fy("2020-01-01", "2025-26") == 12
    assert _months_employed_in_fy("2026-01-15", "2025-26") == 3
    # Unknown falls back to twelve — the pre-existing behaviour, and the
    # direction §192(1) makes the employer liable for getting wrong.
    assert _months_employed_in_fy(None, "2025-26") == 12

    emp = {"id": "e", "basic_paise": 2_00_000 * 100, "hra_percent": 0,
           "da_percent": 0, "pf_applicable": False, "esi_applicable": False,
           "pt_applicable": False}
    joiner = _compute_slip(emp, fy=FY, pt_month=10, months_employed_in_fy=6)
    full_year = _compute_slip(emp, fy=FY, pt_month=10, months_employed_in_fy=12)
    assert joiner["tds_paise"] == 0
    assert full_year["tds_paise"] == 24_375 * 100
    assert (full_year["tds_paise"] - joiner["tds_paise"]) * 6 == 1_46_250 * 100


def test_what_is_already_paid_this_year_is_a_fact_not_a_projection():
    """The estimate is what HAS been paid plus what is still to come, so a
    mid-year raise is picked up for the remaining months without rewriting the
    months already paid."""
    from routers.payroll import _compute_slip
    emp = {"id": "e", "basic_paise": 3_00_000 * 100, "hra_percent": 0,
           "da_percent": 0, "pf_applicable": False, "esi_applicable": False,
           "pt_applicable": False}
    # Six months already paid at ₹1,00,000, now raised to ₹3,00,000 for six more.
    s = _compute_slip(emp, fy=FY, pt_month=10, months_employed_in_fy=12,
                      months_already_paid=6,
                      gross_already_paid_paise=6_00_000 * 100)
    # The year is estimated at ₹6,00,000 + 6 x ₹3,00,000 = ₹24,00,000, not
    # 12 x ₹3,00,000 = ₹36,00,000.
    twelve_times_this_month = _compute_slip(emp, fy=FY, pt_month=10,
                                            months_employed_in_fy=12)
    assert s["tds_paise"] < twelve_times_this_month["tds_paise"]

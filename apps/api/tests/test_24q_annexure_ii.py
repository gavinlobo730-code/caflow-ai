"""
Form 24Q Q4 Annexure II — the annual salary detail behind Form 16.

WHY THERE IS NO FORM 16 GENERATOR, AND SHOULD NOT BE

A self-generated Form 16 cannot lawfully be issued. CBDT Notification 09/2019 of
06-05-2019 requires Part B of the salary TDS certificate to be DOWNLOADED FROM
TRACES for every deduction made on or after 01-04-2018; Part A had been
TRACES-only for years already. An employer who prints their own Form 16 has
issued nothing — the employee's certificate is the one TRACES generated.

TRACES builds Part B from a single input: Annexure II of the Q4 24Q return, in
the format Notification 36/2019 substituted. So the thing that actually produces
Form 16 is a correct Annexure II, and that is what this builds.

WHAT IT WILL NOT INVENT

The salary side is the employer's. §17(2) perquisites, exemptions under §10, and
Chapter VI-A are the EMPLOYEE's, with proofs behind them. They are returned as
named gaps rather than silent zeroes — an HRA allowance on a payslip is not an
HRA exemption, and treating one as the other is the commonest way a Form 16
overstates relief.
"""
from __future__ import annotations

import pytest

from domain.payroll.annexure2 import build_annexure_ii

STD_DEDUCTION = 75_000_00


def _slip(**over) -> dict:
    base = dict(employee_id="e1", basic_paise=50_000_00, hra_paise=20_000_00,
                da_paise=0, lta_paise=0, medical_paise=0,
                special_allowance_paise=0, other_allowances_paise=0,
                pt_paise=200_00, tds_paise=5_000_00)
    base.update(over)
    return base


def _emp(**over) -> dict:
    base = dict(id="e1", name="Asha Kumar", pan="ABCDE1234F")
    base.update(over)
    return base


def _build(slips=None, emps=None, months_expected=12):
    slips = slips if slips is not None else [_slip()] * 12
    emps = emps or [_emp()]
    return build_annexure_ii(
        slips=slips, employees_by_id={e["id"]: e for e in emps},
        standard_deduction_paise=STD_DEDUCTION, months_expected=months_expected)


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_the_salary_head_is_computed_the_way_sections_15_to_17_say():
    a = _build()
    r = a.rows[0]
    assert r.salary_17_1_paise == 12 * 70_000_00           # basic + HRA, 12 months
    assert r.standard_deduction_16_ia_paise == STD_DEDUCTION
    # The PT actually deducted is always RECORDED — the annexure reports it
    # either way, and a CA reconciling to the payslips needs to see it.
    assert r.professional_tax_16_iii_paise == 12 * 200_00
    # But it is only ALLOWED under the old regime. This employee filed no
    # declaration, so they were withheld on the §115BAC(1A) default, and
    # §115BAC(2)(i) excludes every deduction under section 16 except clause
    # (ia). Before this was gated, the annexure claimed §16(iii) for everyone —
    # including everyone it was not available to, since payroll withholds on
    # the new regime by default.
    assert r.uses_new_regime is True
    assert r.allowable_professional_tax_paise == 0
    assert r.income_under_salaries_paise == 12 * 70_000_00 - STD_DEDUCTION
    assert r.tds_deducted_paise == 12 * 5_000_00


def test_professional_tax_is_allowed_under_the_old_regime():
    """§16(iii) survives for an employee who intimated the old regime.

    The mirror of the test above, and the reason the gate is on the REGIME and
    not simply switched off: an old-regime employee is entitled to the
    deduction, and dropping it for them would overstate their income instead.
    """
    a = _build()
    r = a.rows[0]
    r.uses_new_regime = False
    assert r.allowable_professional_tax_paise == 12 * 200_00
    assert r.income_under_salaries_paise == (
        12 * 70_000_00 - STD_DEDUCTION - 12 * 200_00)


def test_salary_is_summed_from_components_not_from_gross():
    """gross_paise on the slip is what was PAID. §17(1) is what is SALARY, and a
    component added later that is not salary — a reimbursement — must not walk
    into the figure just by being on the payslip."""
    a = _build([_slip(gross_paise=99_99_999_00)])
    assert a.rows[0].salary_17_1_paise == 70_000_00


def test_the_standard_deduction_cannot_exceed_the_salary():
    """§16(ia) is capped at the salary — someone paid ₹40,000 for the year does
    not get a ₹75,000 deduction and a negative head."""
    a = _build([_slip(basic_paise=40_000_00, hra_paise=0)])
    assert a.rows[0].standard_deduction_16_ia_paise == 40_000_00
    assert a.rows[0].income_under_salaries_paise == 0


def test_the_salary_head_never_goes_negative():
    a = _build([_slip(basic_paise=100_00, hra_paise=0, pt_paise=5_000_00)])
    assert a.rows[0].income_under_salaries_paise == 0


def test_totals_across_employees():
    a = _build([_slip(), _slip(employee_id="e2")],
               [_emp(), _emp(id="e2", name="Second", pan="ZYXWV9876K")])
    t = a.totals()
    assert t["employees"] == 2
    assert t["tds_paise"] == 10_000_00


# ── what it refuses ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "", "ABCDE1234", "ABCDE12345"])
def test_an_employee_without_a_valid_pan_is_refused(bad):
    """TRACES generates Part B AGAINST THE PAN, so without one the certificate
    cannot be issued at all — this is not a cosmetic field."""
    a = _build(emps=[_emp(pan=bad)])
    assert a.rows == []
    assert any("Form 16 Part B" in p for p in a.problems), a.problems
    assert not a.is_ready


# ── what it declares rather than invents ─────────────────────────────────────

def test_perquisites_and_exemptions_are_named_gaps_not_silent_zeroes():
    """With nothing valued and nothing declared, both must be SAID rather than
    reported as a confident nil."""
    a = _build()
    joined = " ".join(a.gaps)
    assert "§17(2) perquisite" in joined
    assert "§10(13A)" in joined and "rent ACTUALLY PAID" in joined
    assert "Chapter VI-A" in joined


def test_a_valued_perquisite_reaches_the_row_and_stops_being_a_gap():
    """Migration 299 and domain/payroll/perquisites.py close this gap for
    anyone actually valued. It must both COUNT into §17(2) and stop being
    reported as missing — a gap that persists after the work is done trains
    people to ignore gaps."""
    a = build_annexure_ii(
        slips=[_slip()] * 12,
        employees_by_id={"e1": _emp()},
        standard_deduction_paise=STD_DEDUCTION,
        perquisites_by_employee={
            "e1": [{"value_paise": 1_20_000_00, "label": "Motor car"}]},
    )
    r = a.rows[0]
    assert r.perquisites_17_2_paise == 1_20_000_00
    assert r.gross_salary_paise == r.salary_17_1_paise + 1_20_000_00
    assert not any("§17(2) perquisite" in g for g in a.gaps)


def test_gaps_do_not_block_filing():
    """An annexure with no Chapter VI-A is CORRECT for an employee who declared
    none. Gaps are things only the CA can supply; problems are things that are
    wrong. Conflating them would make a valid return unfilable."""
    a = _build()
    assert a.gaps and not a.problems
    assert a.is_ready


def test_a_part_year_employee_is_flagged_for_previous_employer_salary():
    """§192(2): salary from a previous employer that the employee reported
    belongs in this annexure, and is not in these books."""
    a = _build([_slip()] * 5, months_expected=12)
    assert any("PREVIOUS employer" in g for g in a.gaps), a.gaps


def test_no_gaps_are_claimed_when_there_is_no_salary_at_all():
    """An empty year should not lecture the CA about perquisites nobody had."""
    a = build_annexure_ii(slips=[], employees_by_id={},
                          standard_deduction_paise=STD_DEDUCTION)
    assert a.rows == [] and a.gaps == [] and a.problems == []


# ── §16(ia) is not one number ────────────────────────────────────────────────
#
# Finance Act 2023 extended the standard deduction to the new regime and Finance
# (No. 2) Act 2024 raised the NEW regime's figure to ₹75,000, leaving the OLD
# regime's at ₹50,000. §16(ia) is the single clause of section 16 that survives
# §115BAC(2)(i), which is exactly what makes it easy to treat as regime-blind —
# and this builder did, handing every employee ₹75,000 although the row already
# consulted `uses_new_regime` for professional tax a few lines away.
#
# ₹25,000 per old-regime employee of understated income under the head
# Salaries, on the annexure TRACES builds Form 16 Part B from. Wrong in the
# employee's favour and traceable to the employer.

OLD_STD_DEDUCTION = 50_000_00


def _declaration(**over):
    from domain.payroll import declarations as d
    base = dict(employee_id="e1", fy="2026-27", regime=d.REGIME_OLD,
                status=d.STATUS_VERIFIED, proofs_verified=True)
    base.update(over)
    return d.Declaration(**base)


def _build_with_regime(decl, *, old_std=OLD_STD_DEDUCTION):
    return build_annexure_ii(
        slips=[_slip()] * 12,
        employees_by_id={"e1": _emp()},
        standard_deduction_paise=STD_DEDUCTION,
        old_regime_standard_deduction_paise=old_std,
        declarations_by_employee={"e1": decl},
    )


def test_an_old_regime_employee_gets_the_old_regimes_standard_deduction():
    r = _build_with_regime(_declaration()).rows[0]
    assert r.uses_new_regime is False
    assert r.standard_deduction_16_ia_paise == OLD_STD_DEDUCTION
    # Income under the head is HIGHER by the ₹25,000 that was being given away,
    # net of the §16(iii) professional tax this employee is entitled to.
    assert r.income_under_salaries_paise == (
        12 * 70_000_00 - OLD_STD_DEDUCTION - 12 * 200_00)


def test_a_new_regime_employee_still_gets_seventy_five_thousand():
    """The mirror. Fixing the old regime must not move the new one."""
    from domain.payroll import declarations as d
    r = _build_with_regime(_declaration(regime=d.REGIME_NEW)).rows[0]
    assert r.uses_new_regime is True
    assert r.standard_deduction_16_ia_paise == STD_DEDUCTION
    assert r.allowable_professional_tax_paise == 0


def test_the_two_regimes_differ_by_exactly_the_statutory_gap():
    from domain.payroll import declarations as d
    old = _build_with_regime(_declaration()).rows[0]
    new = _build_with_regime(_declaration(regime=d.REGIME_NEW)).rows[0]
    assert (new.standard_deduction_16_ia_paise
            - old.standard_deduction_16_ia_paise) == 25_000_00


def test_the_old_regime_figure_is_still_capped_at_the_salary():
    """§16 deductions come out of salary; the head cannot produce a loss."""
    a = build_annexure_ii(
        slips=[_slip(basic_paise=30_000_00, hra_paise=0, pt_paise=0)],
        employees_by_id={"e1": _emp()},
        standard_deduction_paise=STD_DEDUCTION,
        old_regime_standard_deduction_paise=OLD_STD_DEDUCTION,
        declarations_by_employee={"e1": _declaration()},
        months_expected=1,
    )
    assert a.rows[0].standard_deduction_16_ia_paise == 30_000_00
    assert a.rows[0].income_under_salaries_paise == 0


def test_an_old_regime_row_with_no_old_figure_supplied_says_so():
    """A caller with only new-regime employees need not supply the old figure.
    Where one turns up anyway the row keeps what it was given and the annexure
    NAMES it — a wrong number nobody is told about is the failure this module
    exists to prevent."""
    a = _build_with_regime(_declaration(), old_std=None)
    assert a.rows[0].standard_deduction_16_ia_paise == STD_DEDUCTION
    assert any("old-regime §16(ia)" in g and "Asha Kumar".upper() in g.upper()
               for g in a.gaps), a.gaps


def test_a_new_regime_only_annexure_never_reports_that_gap():
    from domain.payroll import declarations as d
    a = _build_with_regime(_declaration(regime=d.REGIME_NEW), old_std=None)
    assert not any("old-regime §16(ia)" in g for g in a.gaps)

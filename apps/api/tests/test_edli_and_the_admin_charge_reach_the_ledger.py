"""
EDLI and the EPF administrative charge are employer costs, and the ledger
had never carried them.

WHAT WAS WRONG
    routers/payroll.py::_compute_pf returns five employer figures and migration
    295 gave payroll_slips a column for each. Two of them —

        edli_paise       0.5% under EDLI 1976
        pf_admin_paise   0.5% EPF administrative charge

    — are employer costs OUTSIDE the 12%, deducted from nobody, remitted on the
    same monthly challan as the rest. They were computed, stored on every slip,
    and added up correctly on the statutory card.

    They never reached the general ledger. create_run totalled only

        totals["pf"] += pf_employee_paise + pf_employer_paise

    and journal_for_payroll credited PF Payable with exactly that. So every
    payroll accrual understated the employer's cost of employment, and the PF
    liability, by roughly 1% of PF wages — about ₹150 a month per member at the
    ₹15,000 ceiling.

    It does not self-correct. The challan paid to EPFO includes both; the
    ledger's PF Payable did not; so the payment cleared a liability that was
    never fully raised, and the shortfall landed wherever the bank entry was
    coded. The trial balance still balanced, which is why it survived — the
    entry was internally consistent and simply short.

THE FLOOR IS WHY THIS IS A RUN FIGURE
    The administrative charge carries a statutory MINIMUM of ₹500 per
    ESTABLISHMENT per month, not per member, so what is owed cannot be
    reconstructed by adding up payslips: three members at ₹60 each owe ₹500, not
    ₹180. /statutory-position had that rule and was the only place that did; it
    is MOVED to domain/payroll/statutory.py rather than copied, because two
    implementations of one statutory floor drift.

NEGATIVE CONTROL
    Drop `edli` and `pf_admin` from _build_payroll_lines' PF credit and the four
    journal tests fail — the entry is short by exactly them. Revert
    create_run's two totals and the run tests fail. Replace
    admin_charge_for_establishment's max() with the raw total and the floor
    tests fail.
"""
from __future__ import annotations

import pytest

from domain.payroll.statutory import admin_charge_for_establishment, rates_for
from services.phase2_journal_service import Phase2JournalService

ACCOUNTS = {"salary_exp": "A-EXP", "net": "A-NET", "pf": "A-PF", "esi": "A-ESI",
            "pt": "A-PT", "tds": "A-TDS", "loans": "A-LOAN"}


def _run(**kw) -> dict:
    """A one-member month at the PF ceiling, with the figures a real run has."""
    base = {
        "month": "2026-06",
        "total_gross_paise": 5_000_000,      # ₹50,000
        "total_net_paise": 4_640_000,
        "total_pf_paise": 360_000,           # employee 1,800 + employer 1,800
        "total_esi_paise": 0,
        "total_pt_paise": 0,
        "total_tds_paise": 0,
        "total_loan_recovery_paise": 0,
        "total_edli_paise": 7_500,           # ₹75
        "total_pf_admin_paise": 50_000,      # ₹500 — the establishment floor
    }
    base.update(kw)
    return base


def _lines(run: dict) -> list[dict]:
    return Phase2JournalService._build_payroll_lines(ACCOUNTS, run)


def _credit_to(lines: list[dict], account_id: str) -> int:
    return sum(l["credit_paise"] for l in lines if l["account_id"] == account_id)


def _debit_to(lines: list[dict], account_id: str) -> int:
    return sum(l["debit_paise"] for l in lines if l["account_id"] == account_id)


# ── the ledger carries them ──────────────────────────────────────────────────

def test_pf_payable_carries_edli_and_the_admin_charge():
    """THE HEADLINE. Before this, PF Payable was credited 360,000 and the
    employer owed 417,500."""
    lines = _lines(_run())
    assert _credit_to(lines, "A-PF") == 360_000 + 7_500 + 50_000


def test_the_employer_cost_rises_by_exactly_them():
    """The debit is DEFINED as the sum of the credits, so adding them to PF
    Payable raises Salaries Expense by the same amount and the entry stays
    balanced by construction."""
    without = _lines(_run(total_edli_paise=0, total_pf_admin_paise=0))
    with_ = _lines(_run())
    assert _debit_to(with_, "A-EXP") - _debit_to(without, "A-EXP") == 7_500 + 50_000


def test_the_entry_still_balances():
    lines = _lines(_run())
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_the_narration_says_what_is_in_the_line():
    """A line reading "employee + employer" while holding EDLI and the admin
    charge as well is a line that lies to whoever reconciles the challan."""
    [pf_line] = [l for l in _lines(_run()) if l["account_id"] == "A-PF"]
    assert "EDLI" in pf_line["narration"]
    assert "admin charge" in pf_line["narration"]


def test_one_credit_line_to_pf_payable_not_three():
    """All of it is remitted on one challan to one authority. Three lines
    against one account in one entry read as three liabilities and reconcile as
    one."""
    assert len([l for l in _lines(_run()) if l["account_id"] == "A-PF"]) == 1


# ── nothing historical changes ───────────────────────────────────────────────

def test_a_run_from_before_the_columns_posts_exactly_what_it_did():
    """Migration 329 defaults both to 0 and does NOT backfill: a posted entry is
    immutable, so a recomputed column would disagree with the ledger beside it.
    A run carrying zeros must therefore produce the old entry unchanged."""
    old = _run(total_edli_paise=0, total_pf_admin_paise=0)
    assert _credit_to(_lines(old), "A-PF") == 360_000
    assert _debit_to(_lines(old), "A-EXP") == 4_640_000 + 360_000


def test_a_run_with_the_keys_absent_altogether_is_treated_as_zero():
    """A dict read straight from a pre-329 database has no such keys at all."""
    old = _run()
    del old["total_edli_paise"]
    del old["total_pf_admin_paise"]
    assert _credit_to(_lines(old), "A-PF") == 360_000


# ── the invariant ────────────────────────────────────────────────────────────

def test_the_identity_guard_ceiling_includes_the_new_cost():
    """The guard's ceiling was gross + pf + esi, and EDLI and the admin charge
    sit ON TOP of that.

    Honest about what this proves: with real figures the guard would not fire
    anyway, because an employee's own deductions always exceed the ~1% these two
    add. The widened ceiling is defensive — it is there so a future run whose
    employee deductions are small (everyone excluded from PF but the
    establishment still owing the ₹500 floor, say) does not trip a guard meant
    to catch a MISSING credit leg. Asserted on the expression rather than on a
    contrived run, because a contrived one would be asserting my arithmetic
    rather than the rule.
    """
    import inspect
    src = inspect.getsource(Phase2JournalService._build_payroll_lines)
    assert "ceiling = gross + pf + esi + edli + pf_admin" in src
    assert _lines(_run()), "and a normal run still posts"


def test_the_identity_guard_still_catches_a_missing_credit_leg():
    """The other half. A net reduced by a deduction with no matching credit
    would silently understate salary expense, and the balance check cannot see
    it because the debit is defined as the sum of the credits."""
    with pytest.raises(ValueError, match="identity violated"):
        _lines(_run(total_net_paise=1_000_000))


# ── the establishment floor ──────────────────────────────────────────────────

def test_the_admin_charge_is_floored_at_the_establishment_minimum():
    """Three members at ₹60 each owe ₹500, not ₹180."""
    assert admin_charge_for_establishment(18_000) == 50_000


def test_a_charge_above_the_floor_is_left_alone():
    assert admin_charge_for_establishment(60_000) == 60_000


def test_a_month_with_no_contributing_members_owes_nothing():
    """The floor applies to an establishment that is contributing, not to one
    with no payroll at all. Returning ₹500 would invent a liability out of a
    month in which nobody was employed."""
    assert admin_charge_for_establishment(0) == 0


def test_the_floor_comes_from_the_fy_registry_not_a_literal():
    assert admin_charge_for_establishment(1) == rates_for().pf.admin_minimum_paise


def test_the_floor_rule_lives_in_one_place():
    """MOVED, not copied. /statutory-position had it and was the only place
    that did; create_run needed the same rule, and two implementations of one
    statutory floor drift."""
    import inspect
    import routers.payroll as pr
    src = inspect.getsource(pr)
    assert src.count("payroll_admin_charge(") == 2, \
        "create_run and statutory_position, both through the shared helper"
    assert "admin_minimum_paise" not in src, \
        "the floor is applied in domain/payroll/statutory.py, not inline here"


def test_the_run_totals_both_and_stores_them():
    import inspect
    import routers.payroll as pr
    src = inspect.getsource(pr.create_run)
    assert 'totals["edli"]  += int(slip.get("edli_paise") or 0)' in src
    assert 'totals["admin"] += int(slip.get("pf_admin_paise") or 0)' in src
    assert '"total_edli_paise":     totals["edli"]' in src
    assert '"total_pf_admin_paise": totals["admin"]' in src


def test_the_floor_is_applied_to_the_run_not_to_a_payslip():
    """It is per ESTABLISHMENT. Applying it inside _compute_pf would charge
    ₹500 per member."""
    import inspect
    import routers.payroll as pr
    assert "payroll_admin_charge" not in inspect.getsource(pr._compute_pf)
    assert "payroll_admin_charge" in inspect.getsource(pr.create_run)

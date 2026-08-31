"""
Effective-dated salary revisions, and loans recovered through the payslip.
Migration 300.
"""
import logging

import pytest

import routers.payroll as pr


class _Rows:
    """The smallest stand-in for the query surface these helpers use."""
    def __init__(self, rows, fail=False):
        self._rows, self._fail = rows, fail

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self

    def execute(self):
        if self._fail:
            raise RuntimeError("the database is having a day")
        return type("R", (), {"data": list(self._rows)})()


class _DB:
    def __init__(self, by_table): self._by = by_table
    def table(self, name): return self._by.get(name, _Rows([]))


REV = "payroll_salary_revisions"
LOANS = "payroll_loans"


# ── The logger that was missing ──────────────────────────────────────────────

def test_the_module_logger_exists():
    """Every 'read failed, carry on with the safe default' branch logs through
    _logger. It was referenced in five of them and never defined, so the first
    real read failure would have raised NameError from inside the except —
    turning a graceful degradation into a 500, on the one day something was
    already going wrong."""
    assert isinstance(pr._logger, logging.Logger)


@pytest.mark.parametrize("helper,tables", [
    (lambda db: pr._salary_in_force(db, "f", "c", "2026-07"), REV),
    (lambda db: pr._loan_instalments_for_run(db, "f", "c"), LOANS),
])
def test_a_failed_read_degrades_instead_of_raising(helper, tables):
    assert helper(_DB({tables: _Rows([], fail=True)})) == {}


# ── Effective-dated revisions ────────────────────────────────────────────────

def _rev(emp, date, basic):
    return {"employee_id": emp, "effective_from": date, "basic_paise": basic,
            "hra_percent": 40, "da_percent": 0, "lta_paise": 0,
            "medical_paise": 0, "special_allowance_paise": 0,
            "other_allowances_paise": 0}


def test_the_latest_revision_on_or_before_the_month_wins():
    db = _DB({REV: _Rows([_rev("e1", "2026-04-01", 50_000_00),
                          _rev("e1", "2026-10-01", 60_000_00)])})
    assert pr._salary_in_force(db, "f", "c", "2026-07")["e1"]["basic_paise"] == 50_000_00
    assert pr._salary_in_force(db, "f", "c", "2026-10")["e1"]["basic_paise"] == 60_000_00
    assert pr._salary_in_force(db, "f", "c", "2027-01")["e1"]["basic_paise"] == 60_000_00


def test_a_future_revision_does_not_apply_yet():
    """The point of entering one in advance: someone whose raise takes effect
    on 1 January must not be paid it in December."""
    db = _DB({REV: _Rows([_rev("e1", "2027-01-01", 60_000_00)])})
    assert pr._salary_in_force(db, "f", "c", "2026-12") == {}


def test_a_revision_effective_on_the_first_of_the_month_applies_that_month():
    db = _DB({REV: _Rows([_rev("e1", "2026-07-01", 60_000_00)])})
    assert "e1" in pr._salary_in_force(db, "f", "c", "2026-07")


def test_an_employee_with_no_revision_is_absent_rather_than_defaulted():
    """Absent means 'fall back to the master'. Inventing an effective date for
    the pay someone happens to be on today would put a fact in the record that
    nobody established."""
    db = _DB({REV: _Rows([_rev("e1", "2026-04-01", 50_000_00)])})
    assert "e2" not in pr._salary_in_force(db, "f", "c", "2026-07")


# ── Loan recovery ────────────────────────────────────────────────────────────

def _loan(emp, outstanding, instalment):
    return {"employee_id": emp, "outstanding_paise": outstanding,
            "monthly_instalment_paise": instalment}


def test_the_instalment_is_capped_at_what_is_still_owed():
    """An instalment larger than the balance would over-recover — the employer
    taking money they are not owed."""
    db = _DB({LOANS: _Rows([_loan("e1", 3_000_00, 10_000_00)])})
    assert pr._loan_instalments_for_run(db, "f", "c") == {"e1": 3_000_00}


def test_two_loans_for_one_employee_are_added():
    db = _DB({LOANS: _Rows([_loan("e1", 50_000_00, 5_000_00),
                            _loan("e1", 20_000_00, 2_000_00)])})
    assert pr._loan_instalments_for_run(db, "f", "c") == {"e1": 7_000_00}


def test_a_settled_loan_contributes_nothing():
    db = _DB({LOANS: _Rows([_loan("e1", 0, 5_000_00)])})
    assert pr._loan_instalments_for_run(db, "f", "c") == {}


# ── Recovery never outranks a statutory deduction ────────────────────────────

def _slip(**kw):
    emp = dict(id="e1", basic_paise=20_000_00, hra_percent=0, da_percent=0,
               pf_applicable=True, esi_applicable=True, pt_applicable=False,
               eps_eligible=True)
    emp.update(kw.pop("emp", {}))
    return pr._compute_slip(emp, fy="2025-26", pt_month=4, **kw)


def test_a_loan_is_recovered_after_the_statutory_deductions():
    plain = _slip()
    with_loan = _slip(loan_instalment_paise=1_000_00)
    assert with_loan["pf_employee_paise"] == plain["pf_employee_paise"]
    assert with_loan["esi_employee_paise"] == plain["esi_employee_paise"]
    assert with_loan["tds_paise"] == plain["tds_paise"]
    assert with_loan["loan_recovery_paise"] == 1_000_00
    assert with_loan["net_paise"] == plain["net_paise"] - 1_000_00


def test_recovery_cannot_push_net_pay_below_zero():
    """PF, ESI, professional tax and TDS are owed to somebody else and come
    first. An employer may not recover an advance from money that was never
    there — a recovery that overdrew the payslip would be a debt collected on
    paper and an overdraft in fact."""
    s = _slip(loan_instalment_paise=99_00_000_00)
    assert s["net_paise"] == 0
    statutory = (s["pf_employee_paise"] + s["esi_employee_paise"]
                 + s["pt_paise"] + s["tds_paise"])
    assert s["loan_recovery_paise"] == s["gross_paise"] - statutory


def test_no_loan_leaves_the_slip_exactly_as_it_was():
    assert _slip()["loan_recovery_paise"] == 0

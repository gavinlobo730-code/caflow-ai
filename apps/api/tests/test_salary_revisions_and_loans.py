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


# ── The recovery has to reach the ledger ─────────────────────────────────────

def test_the_payroll_journal_balances_with_a_loan_recovery():
    """The integration this nearly broke.

    The accrual journal debits Salaries Expense with the SUM of its credits, so
    a deduction with no credit leg makes the debit too small and understates
    salary expense. _build_payroll_lines' own guard names this exact case — "a
    future loan/advance recovery" — so finalising a run with a recovery would
    have RAISED rather than posted a wrong journal. Loud, and still broken.

    Recovering an advance does not reduce the salary cost; it settles part of it
    by extinguishing a receivable instead of paying cash. So it is a credit leg
    like any other deduction and the identity still holds.
    """
    from services.phase2_journal_service import Phase2JournalService

    ids = {"salary_exp": "exp", "net": "net", "pf": "pf", "esi": "esi",
           "pt": "pt", "tds": "tds", "loans": "loans"}
    # gross 10,00,000; PF 1,20,000 (60,000 employee + 60,000 employer);
    # PT 2,400; TDS 1,00,000 -> net is 8,37,600 before any recovery, and
    # 8,17,600 after recovering 20,000.
    run = {"month": "2026-07", "total_gross_paise": 10_00_000_00,
           "total_net_paise": 8_17_600_00, "total_pf_paise": 1_20_000_00,
           "total_esi_paise": 0, "total_pt_paise": 2_400_00,
           "total_tds_paise": 1_00_000_00,
           "total_loan_recovery_paise": 20_000_00}

    lines = Phase2JournalService._build_payroll_lines(ids, run)
    debits = sum(l["debit_paise"] for l in lines)
    credits = sum(l["credit_paise"] for l in lines)
    assert debits == credits, "the payroll accrual must balance"
    # And the salary COST is unchanged by the recovery: 10,00,000 of gross plus
    # 60,000 of employer PF. Booking the recovery as a reduction in expense
    # would understate both the expense and the receivable, and the two errors
    # would hide each other.
    assert debits == 10_60_000_00

    loan_line = [l for l in lines if l["account_id"] == "loans"]
    assert len(loan_line) == 1
    assert loan_line[0]["credit_paise"] == 20_000_00
    assert loan_line[0]["debit_paise"] == 0


def test_a_run_with_no_recovery_posts_exactly_as_before():
    """No recovery, no line — and in particular no lookup of a receivable
    account that a firm's chart may not have."""
    from services.phase2_journal_service import Phase2JournalService

    ids = {"salary_exp": "exp", "net": "net", "pf": "pf", "esi": "esi",
           "pt": "pt", "tds": "tds", "loans": None}
    run = {"month": "2026-07", "total_gross_paise": 10_00_000_00,
           "total_net_paise": 8_37_600_00, "total_pf_paise": 1_20_000_00,
           "total_esi_paise": 0, "total_pt_paise": 2_400_00,
           "total_tds_paise": 1_00_000_00, "total_loan_recovery_paise": 0}

    lines = Phase2JournalService._build_payroll_lines(ids, run)
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)
    assert not [l for l in lines if l["account_id"] is None]


# ── The balance actually falls ───────────────────────────────────────────────

class _Recording(_Rows):
    """A _Rows that also remembers the updates written through it."""
    def __init__(self, rows):
        super().__init__(rows)
        self.updates = []
        self._pending = None

    def update(self, payload):
        self._pending = payload
        return self

    def eq(self, col, val):
        if self._pending is not None:
            self.updates.append((col, val, self._pending))
            self._pending = None
        return self


def test_a_recovery_reduces_the_outstanding_balance():
    """Without this the same instalment is deducted every month forever: the
    balance is read to cap the instalment and was never written back."""
    slips = _Rows([{"employee_id": "e1", "loan_recovery_paise": 5_000_00}])
    loans = _Recording([{"id": "L1", "employee_id": "e1",
                         "outstanding_paise": 20_000_00}])
    db = _DB({"payroll_slips": slips, "payroll_loans": loans})

    assert pr._apply_loan_recoveries(db, "f", "c", "run1") == 1
    col, val, payload = loans.updates[0]
    assert (col, val) == ("id", "L1")
    assert payload["outstanding_paise"] == 15_000_00
    assert payload["closed_on"] is None


def test_a_loan_paid_off_is_closed():
    """Closed so it stops being read at all next month, rather than being
    filtered out every time."""
    slips = _Rows([{"employee_id": "e1", "loan_recovery_paise": 20_000_00}])
    loans = _Recording([{"id": "L1", "employee_id": "e1",
                         "outstanding_paise": 20_000_00}])
    pr._apply_loan_recoveries(_DB({"payroll_slips": slips, "payroll_loans": loans}),
                              "f", "c", "run1")
    payload = loans.updates[0][2]
    assert payload["outstanding_paise"] == 0
    assert payload["closed_on"] is not None


def test_a_run_that_recovered_nothing_writes_nothing():
    slips = _Rows([{"employee_id": "e1", "loan_recovery_paise": 0}])
    loans = _Recording([{"id": "L1", "employee_id": "e1",
                         "outstanding_paise": 20_000_00}])
    assert pr._apply_loan_recoveries(
        _DB({"payroll_slips": slips, "payroll_loans": loans}), "f", "c", "run1") == 0
    assert loans.updates == []


def test_a_failed_write_down_does_not_raise():
    """The journal has already posted by the time this runs. Refusing to
    finalise a correct payroll because a balance could not be written down
    would be the worse failure; a missed write-down is visible on the next
    payslip and on the loan list."""
    db = _DB({"payroll_slips": _Rows([], fail=True)})
    assert pr._apply_loan_recoveries(db, "f", "c", "run1") == 0


def test_the_payslip_shows_every_deduction_that_reduced_net_pay():
    """Gross minus the deductions SHOWN must equal the net shown. A recovery
    that reduces net pay without appearing on the payslip is exactly the
    difference an employee would have to work out for themselves."""
    from services.payslip_pdf_service import deduction_lines

    slip = {"gross_paise": 50_000_00, "pf_employee_paise": 1_800_00,
            "esi_employee_paise": 0, "pt_paise": 200_00, "tds_paise": 5_000_00,
            "loan_recovery_paise": 1_000_00}
    rows, total = deduction_lines(slip)
    assert total == 8_000_00
    assert ["Loan / Advance Recovery", "₹1,000.00"] in rows
    # And the payslip reconciles: gross less the deductions shown IS the net.
    assert slip["gross_paise"] - total == 42_000_00


def test_a_nil_recovery_is_not_a_row_on_everyone_s_payslip():
    """The statutory four always show, so an employee can see PF or TDS was
    considered and came to nothing. A zero advance line for everyone who has no
    advance is only noise."""
    from services.payslip_pdf_service import deduction_lines

    rows, total = deduction_lines({"pf_employee_paise": 1_800_00,
                                   "esi_employee_paise": 0, "pt_paise": 200_00,
                                   "tds_paise": 5_000_00})
    assert total == 7_000_00
    assert len(rows) == 5           # header + the statutory four
    assert not any("Loan" in r[0] for r in rows)

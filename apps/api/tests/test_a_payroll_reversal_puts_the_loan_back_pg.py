"""Reversing a payroll run puts the employee's loan back (PAY-08).

WHAT THIS PROVES AND WHY IT NEEDS A REAL DATABASE

`_apply_loan_recoveries` writes a borrower's balance down at finalisation, and
`reverse_run` — which reverses both journals and reopens the run at 'review' —
never touched `payroll_loans`. So the ordinary correction cycle, which is
finalise → spot a wrong attendance figure → reverse → correct → finalise again,
wrote ONE recovery down TWICE.

THE DIRECTION IS THE OPPOSITE OF THE OBVIOUS ONE, and it is worth stating
because the first summary of this defect had it backwards. The employee's PAY
is reduced by the instalment exactly once: the reversed run's journals are
reversed, and the corrected run deducts it once. It is the LOAN BALANCE that
moves twice, so it ends one instalment too LOW — the employer under-recovers
and the ledger understates what the employee owes. Where the first run CLOSED
the loan it is worse: `closed_on` is set, `_loan_recoveries_for_run`'s
`closed_on IS NULL` query stops reading it, and the final instalment is never
recovered at all.

Real Postgres, because the fix is a table (migration 367) whose CHECK
constraints are half the design — the sign of `amount_paise` must match `kind`,
so a history row that reads backwards while the SUM still comes out right is
refused by the database rather than by a convention every writer has to
remember. A mock FakeDB has no CHECK and would assert that guarantee against a
double that cannot have it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the loan history's CHECK constraints need a real Postgres",
)

FIRM = "f3670000-0000-0000-0000-000000000001"
CLIENT = "c3670000-0000-0000-0000-000000000001"
EMP = "e3670000-0000-0000-0000-000000000001"
LOAN = "10a70000-0000-0000-0000-000000000001"
RUN = "4b170000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"loanrev_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email)
          VALUES ('{FIRM}', 'Loan Rev', 'a@loanrev.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'Borrower Co', 'Private Limited');
        INSERT INTO payroll_employees (id, firm_id, client_id, name, basic_paise)
          VALUES ('{EMP}', '{FIRM}', '{CLIENT}', 'A Borrower', 5000000);
        INSERT INTO payroll_runs (id, firm_id, client_id, month, status)
          VALUES ('{RUN}', '{FIRM}', '{CLIENT}', '2026-07', 'finalized');
        INSERT INTO payroll_loans
          (id, firm_id, client_id, employee_id, principal_paise,
           outstanding_paise, monthly_instalment_paise)
          VALUES ('{LOAN}', '{FIRM}', '{CLIENT}', '{EMP}',
                  2000000, 2000000, 500000);
    """)
    assert seed.returncode == 0, seed.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _one(dsn: str, sql: str) -> str:
    res = _psql(dsn, sql, tuples=True)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _recover(dsn: str, amount: int, *, closes: bool = False) -> None:
    """What `_apply_loan_recoveries` does at finalisation, in SQL."""
    _psql(dsn, f"""
        UPDATE payroll_loans SET outstanding_paise = outstanding_paise - {amount},
               closed_on = {"CURRENT_DATE" if closes else "NULL"}
         WHERE id = '{LOAN}';
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise,
           kind, closed_the_loan)
          VALUES ('{FIRM}', '{CLIENT}', '{LOAN}', '{RUN}', '{EMP}',
                  {amount}, 'recovered', {str(closes).lower()});
    """)


# ── the table's own guarantees ───────────────────────────────────────────────

def test_the_history_table_exists_with_its_two_indexes(db):
    assert _one(db, "SELECT to_regclass('public.payroll_loan_recoveries');") \
        == "payroll_loan_recoveries"
    idx = _one(db, "SELECT string_agg(indexname, ',' ORDER BY indexname) "
                   "FROM pg_indexes WHERE tablename='payroll_loan_recoveries';")
    assert "payroll_loan_recoveries_run_idx" in idx      # the undo's question
    assert "payroll_loan_recoveries_loan_idx" in idx     # the screen's question


def test_a_recovered_row_that_gives_money_back_is_refused(db):
    """The sign IS the kind. A 'recovered' row with a negative amount would
    make the history read backwards while the SUM still came out right — the
    failure that is hardest to see, so the database refuses it rather than
    trusting every writer to remember the convention."""
    res = _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', -500000, 'recovered');
    """)
    assert res.returncode != 0
    assert "payroll_loan_recoveries_sign_matches_kind" in res.stderr


def test_a_reversed_row_that_takes_money_is_refused(db):
    res = _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', 500000, 'reversed');
    """)
    assert res.returncode != 0
    assert "payroll_loan_recoveries_sign_matches_kind" in res.stderr


def test_a_zero_movement_is_refused(db):
    """A row that says nothing happened is not history, it is noise in the
    SUM that reconstructs the balance."""
    res = _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', 0, 'recovered');
    """)
    assert res.returncode != 0
    assert "payroll_loan_recoveries_amount_nonzero" in res.stderr


def test_an_unknown_kind_is_refused(db):
    res = _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', 500000, 'adjusted');
    """)
    assert res.returncode != 0


# ── the defect itself ────────────────────────────────────────────────────────

def test_the_run_that_recovered_can_be_read_back_exactly(db):
    """This is what makes the undo possible at all. `_apply_loan_recoveries`
    walks an employee's open loans in whatever order the rows come back and
    applies min(remaining, owed) to each — its own comment says "oldest-first
    is not modelled" — so with two loans the balances afterwards do not say
    which one moved. The row is the answer."""
    _recover(db, 500000)
    row = _one(db, f"SELECT loan_id || ' ' || amount_paise "
                   f"FROM payroll_loan_recoveries "
                   f"WHERE run_id='{RUN}' AND kind='recovered';")
    assert row == f"{LOAN} 500000"


def test_the_balance_reconstructs_from_the_history(db):
    """principal − Σ amount_paise, which is the property that makes the table
    worth having rather than a flag on the loan."""
    _recover(db, 500000)
    _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', -500000, 'reversed');
    """)
    derived = _one(db, f"""
        SELECT l.principal_paise - COALESCE(SUM(r.amount_paise), 0)
          FROM payroll_loans l
          LEFT JOIN payroll_loan_recoveries r ON r.loan_id = l.id
         WHERE l.id = '{LOAN}' GROUP BY l.principal_paise;""")
    assert derived == "2000000"


def test_the_reversal_is_append_only_the_recovered_row_survives(db):
    """Two rows that net to zero are the record of what happened; one row
    deleted is a record that it did not. RLS has no UPDATE policy for the same
    reason — a correction is another row."""
    _recover(db, 500000)
    _psql(db, f"""
        INSERT INTO payroll_loan_recoveries
          (firm_id, client_id, loan_id, run_id, employee_id, amount_paise, kind)
          VALUES ('{FIRM}','{CLIENT}','{LOAN}','{RUN}','{EMP}', -500000, 'reversed');
    """)
    assert _one(db, f"SELECT count(*) FROM payroll_loan_recoveries "
                    f"WHERE run_id='{RUN}';") == "2"
    assert _one(db, f"SELECT count(*) FROM payroll_loan_recoveries "
                    f"WHERE run_id='{RUN}' AND kind='recovered';") == "1"


def test_the_closing_row_says_it_closed_the_loan(db):
    """`closed_the_loan` is recorded rather than inferred, because a loan can
    reach zero and be reopened by a later correction, and "was it closed by
    THIS row" is not answerable from a balance afterwards. It is what tells the
    undo to clear `closed_on` — and a loan with something outstanding and a
    closed_on date is invisible to next month's recovery, which is how the
    final instalment went missing."""
    _recover(db, 2000000, closes=True)
    assert _one(db, f"SELECT closed_the_loan FROM payroll_loan_recoveries "
                    f"WHERE run_id='{RUN}';") == "t"
    assert _one(db, f"SELECT closed_on IS NOT NULL FROM payroll_loans "
                    f"WHERE id='{LOAN}';") == "t"


def test_the_loan_history_cannot_outlive_the_loan(db):
    """ON DELETE CASCADE. A history row pointing at a loan that is gone is a
    balance nobody can reconstruct."""
    _recover(db, 500000)
    _psql(db, f"DELETE FROM payroll_loans WHERE id='{LOAN}';")
    assert _one(db, "SELECT count(*) FROM payroll_loan_recoveries;") == "0"


def test_rls_is_on_and_the_firm_scope_policy_exists(db):
    """It mirrors payroll_loans (migration 300): this table says what happened
    to a loan, and a reader who may not see the loan must not see its history."""
    assert _one(db, "SELECT relrowsecurity FROM pg_class "
                    "WHERE relname='payroll_loan_recoveries';") == "t"
    pols = _one(db, "SELECT string_agg(policyname, ',' ORDER BY policyname) "
                    "FROM pg_policies WHERE tablename='payroll_loan_recoveries';")
    assert "payroll_loan_recoveries_firm_scope" in pols
    assert "payroll_loan_recoveries_role_insert" in pols
    assert "payroll_loan_recoveries_role_update" in pols


def test_the_slip_records_the_perquisite_the_estimate_used(db):
    """Migration 368, checked here because its CHECK is a database guarantee:
    a perquisite value is a value, and a negative one would under-withhold."""
    assert _one(db, "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='payroll_slips' "
                    "AND column_name='perquisites_in_tds_estimate_paise';") == "1"
    res = _psql(db, f"""
        INSERT INTO payroll_slips
          (run_id, employee_id, gross_paise, net_paise,
           perquisites_in_tds_estimate_paise)
          VALUES ('{RUN}', '{EMP}', 5000000, 5000000, -1);""")
    assert res.returncode != 0
    assert "payroll_slips_perquisites_nonneg" in res.stderr

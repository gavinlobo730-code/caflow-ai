"""
Migration 323 — an employee reads a payslip only once its run is RELEASED.

THE BUG THIS PINS
    Migration 262 scoped the employee portal's reads by IDENTITY and nothing
    else:

        employee_reads_own_payslips     USING (employee_id IN (SELECT my_employee_ids()))
        employee_reads_own_payroll_runs USING (id IN (SELECT my_payroll_run_ids()))

    payroll_runs.status is NOT NULL DEFAULT 'draft'. Neither policy read it. So
    the moment a CA pressed Generate — POST /api/payroll/runs writes 'draft' —
    every portal-linked employee could read their own UNAPPROVED payslip:
    before the reviewer, before the client employer approved it, before a rupee
    was posted. A figure that is still going to change, presented to the person
    it is deducted from.

    The rest of the codebase already drew this line. The ECR and the ESIC
    return both refuse a run that is not finalised, in those words; Form 16 and
    the 24Q filter their source runs the same way; tds_return_service names the
    pair _PAYROLL_POSTED = ("finalized", "paid"). Only RLS never got it.

    Latent when found — production held no payroll_employees row with
    auth_user_id or portal_enabled — so this closes it before the first invite
    rather than after.

WHY BOTH OBJECTS ARE TESTED SEPARATELY
    Tightening my_payroll_run_ids() alone hides the RUN, and the portal's
    payroll_runs!inner(month) embed would then drop the slip as a side effect
    of the inner join. That is a property of the caller's QUERY SHAPE, not of
    the policy — a plain `SELECT FROM payroll_slips` would still return the
    draft slip. test_a_draft_payslip_is_invisible_on_its_own asserts the slip
    is gone without any join at all, which is the assertion the inner-join
    reasoning cannot make.

NEGATIVE CONTROL
    Revert migration 323 (restore 262's two-line function and the identity-only
    slip policy) and both draft tests fail: the draft slip and its run come
    back.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="employee portal RLS proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000323"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000323"
EMP = "cccccccc-0000-0000-0000-000000000323"
AUTH_EMP = "44444444-4444-4444-4444-444444444444"
DRAFT_RUN = "dddddddd-0000-0000-0000-000000000d01"
FINAL_RUN = "dddddddd-0000-0000-0000-000000000f01"
DRAFT_GROSS = 1111100
FINAL_GROSS = 2222200


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
            f"SET ROLE authenticated; ")


@pytest.fixture()
def seeded(pg_template):
    """One employee with TWO payslips: one on a draft run, one on a finalised
    run. Same employee on purpose — identity is held constant so the only thing
    that can explain a difference in visibility is the run's status."""
    admin = _ADMIN.strip()
    dbname = f"m323_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_EMP}','emp323@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M323 Firm','m323@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT}','{FIRM}','M323 Client','Private Limited');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMP}','{FIRM}','{CLIENT}','Employee 323','{AUTH_EMP}',true);
            INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES
              ('{DRAFT_RUN}','{FIRM}','{CLIENT}','2026-07','draft'),
              ('{FINAL_RUN}','{FIRM}','{CLIENT}','2026-06','finalized');
            INSERT INTO payroll_slips (id, run_id, employee_id, gross_paise, net_paise) VALUES
              (gen_random_uuid(),'{DRAFT_RUN}','{EMP}',{DRAFT_GROSS},1000000),
              (gen_random_uuid(),'{FINAL_RUN}','{EMP}',{FINAL_GROSS},2000000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _scalar(dsn: str, auth: str, sql: str) -> str:
    r = _psql(dsn, _as(auth) + sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ─── the released run is still readable, which is the point of the portal ────

def test_a_finalised_payslip_is_readable(seeded):
    assert _scalar(seeded, AUTH_EMP,
                   f"SELECT gross_paise FROM payroll_slips WHERE gross_paise = {FINAL_GROSS};"
                   ) == str(FINAL_GROSS)


def test_the_finalised_run_behind_it_is_readable(seeded):
    """The portal's payroll_runs!inner(month) embed needs the parent row."""
    assert _scalar(seeded, AUTH_EMP, "SELECT month FROM payroll_runs;") == "2026-06"


# ─── the draft is not ────────────────────────────────────────────────────────

def test_a_draft_payslip_is_invisible_on_its_own(seeded):
    """No join, no embed: a plain select on payroll_slips. This is the
    assertion that the inner-join argument cannot make for us."""
    assert _scalar(seeded, AUTH_EMP,
                   f"SELECT count(*) FROM payroll_slips WHERE gross_paise = {DRAFT_GROSS};") == "0"


def test_the_draft_run_is_invisible(seeded):
    assert _scalar(seeded, AUTH_EMP,
                   "SELECT count(*) FROM payroll_runs WHERE status = 'draft';") == "0"


def test_exactly_one_payslip_is_visible(seeded):
    """Both slips belong to this employee. Only one is released, so the count
    separates 'scoped by identity' from 'scoped by identity AND release'."""
    assert _scalar(seeded, AUTH_EMP, "SELECT count(*) FROM payroll_slips;") == "1"


# ─── review is not release ───────────────────────────────────────────────────

def test_a_run_under_review_is_still_not_readable(seeded):
    """'review' is a staff stage, not a publication. The vocabulary is
    draft/review/finalized/paid and only the last two are released."""
    assert _psql(seeded, f"UPDATE payroll_runs SET status = 'review' WHERE id = '{DRAFT_RUN}';"
                 ).returncode == 0
    assert _scalar(seeded, AUTH_EMP, "SELECT count(*) FROM payroll_slips;") == "1"


def test_paid_counts_as_released(seeded):
    """The other half of _PAYROLL_POSTED. A run that has been disbursed must
    not vanish from the employee's own history."""
    assert _psql(seeded, f"UPDATE payroll_runs SET status = 'paid' WHERE id = '{FINAL_RUN}';"
                 ).returncode == 0
    assert _scalar(seeded, AUTH_EMP, "SELECT count(*) FROM payroll_slips;") == "1"


def test_releasing_a_run_makes_its_payslip_appear(seeded):
    """The transition itself, in the direction a CA drives it."""
    assert _scalar(seeded, AUTH_EMP, "SELECT count(*) FROM payroll_slips;") == "1"
    assert _psql(seeded, f"UPDATE payroll_runs SET status = 'finalized' WHERE id = '{DRAFT_RUN}';"
                 ).returncode == 0
    assert _scalar(seeded, AUTH_EMP, "SELECT count(*) FROM payroll_slips;") == "2"

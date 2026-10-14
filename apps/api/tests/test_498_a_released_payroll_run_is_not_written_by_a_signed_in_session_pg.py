"""Migration 498 — a finalized or paid payroll run, and its payslips, cannot be changed from a signed-in session.

THE BUG THIS PINS (ledger POST-B-004, the half migration 485 left)
    The API refuses to touch a released payroll run, but the database did not: a signed-in session holding
    `payroll:write` (a Manager's, since 485) could rewrite a released run's totals or a payslip's figures, set a draft
    straight to `finalized` or `paid` with no journal behind it, reopen a released run without reversing its books, or
    delete it, which cascades to the append-only release log. The browser reads these two tables and writes neither,
    so no screen depended on any of it.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION (a Partner and an assigned Manager, both of whom the tier lets write)
    * a finalized or paid run cannot be updated, set back, upserted onto or deleted, and the release-log rows survive;
    * no run can be inserted or updated INTO finalized or paid;
    * a payslip of a finalized or paid run cannot be updated, deleted, upserted onto, added to, moved into or moved
      out of, and the refusal is the same for an unassigned Executive and for the employee themselves (whose insert is
      refused by this trigger before row security gets to it);
    * a foreign-key cascade started by a signed-in session is judged as that session (an employee with a released
      payslip, a client with a released run);
    * the refusal is SQLSTATE 42501 and its sentence says what to do instead;
    * a DRAFT or REVIEW run, and its slips, are written exactly as before (the control that makes every refusal above
      mean something);
    * the API (`service_role`) still makes its three transitions (finalize, pay, reverse) and a recompute, but a run
      does not BECOME finalized without its journal or paid without both, whichever way it is written;
    * the database owner is not judged, which is what lets fixtures and a deliberate repair work;
    * exactly these two triggers exist on the two tables, and a new released status in the CHECK fails the suite;
    * the migration is idempotent, and its own rollback puts every hole back (the negative control).

The access matrix (`test_rls_role_by_table_matrix_pg.py`) DISABLES these two triggers in its world: they answer before
row security does, and that instrument measures row security. This module measures the freeze.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "498_a_finalized_or_paid_payroll_run_and_its_payslips_cannot_be_changed_from_a_signed_in_session"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the released-payroll-run proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000498"
CLIENT = "cccccccc-0000-0000-0000-00000000a498"
STAFF = {"partner": "Partner", "manager": "Manager", "executive": "Executive"}
ASSIGNED = ("manager",)          # the Partner is firm-wide; the Executive is deliberately NOT assigned to the client
AUTH = {k: f"11111111-1111-1111-1111-{i:012d}" for i, k in enumerate([*STAFF, "employee"], start=1)}
USER = {k: f"bbbbbbbb-1111-1111-1111-{i:012d}" for i, k in enumerate(STAFF, start=1)}
EMP1, EMP2 = "eeeeeeee-0000-0000-0000-000000000001", "eeeeeeee-0000-0000-0000-000000000002"
RUN = {s: f"dddddddd-0000-0000-0000-00000000000{i}" for i, s in enumerate(["draft", "review", "finalized", "paid"], 1)}
MONTH = {"draft": "2026-04", "review": "2026-05", "finalized": "2026-06", "paid": "2026-07"}
SLIP = {s: f"55555555-0000-0000-0000-00000000000{i}" for i, s in enumerate(RUN, 1)}
JE_ACCRUAL, JE_DISBURSEMENT = "99999999-0000-0000-0000-000000000001", "99999999-0000-0000-0000-000000000002"
GROSS, NET = 5_000_000, 4_500_000
WHO = ["partner", "manager"]     # the two whom the tier lets write


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return _psql(dsn, f"\\set VERBOSITY verbose\nSET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _as_service(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"\\set VERBOSITY verbose\nSET ROLE service_role; {sql}")


def _refused(r: subprocess.CompletedProcess, *words: str) -> bool:
    return r.returncode != 0 and "42501" in r.stderr and all(w in r.stderr for w in words)


def _count(dsn: str, sql: str) -> int:
    return int(_ok(dsn, sql))


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"releasedrun_m498_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m498.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{FIRM}', '{AUTH[k]}', '{k}@m498.test', '{k}', '{role}', true)"
                          for k, role in STAFF.items())
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT}')" for k in ASSIGNED)
        runs = ", ".join(f"('{RUN[s]}', '{FIRM}', '{CLIENT}', '{MONTH[s]}', '{s}')" for s in RUN)
        slips = ", ".join(f"('{SLIP[s]}', '{RUN[s]}', '{EMP1}', {GROSS}, {NET})" for s in RUN)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M498 Firm','m498@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled) VALUES
                ('{EMP1}', '{FIRM}', '{CLIENT}', 'Employee One', '{AUTH["employee"]}', true),
                ('{EMP2}', '{FIRM}', '{CLIENT}', 'Employee Two', NULL, false);
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status) VALUES
                ('{JE_ACCRUAL}', '{FIRM}', '{CLIENT}', '2026-06-30', 'accrual', 'Journal', true, 'posted'),
                ('{JE_DISBURSEMENT}', '{FIRM}', '{CLIENT}', '2026-07-05', 'disbursement', 'Payment', true, 'posted');
            INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES {runs};
            INSERT INTO payroll_slips (id, run_id, employee_id, gross_paise, net_paise) VALUES {slips};
            UPDATE payroll_runs SET total_net_paise = {NET}, total_gross_paise = {GROSS};
            INSERT INTO payroll_run_transitions (firm_id, run_id, from_status, to_status)
                 VALUES ('{FIRM}', '{RUN["finalized"]}', 'review', 'finalized');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _apply(dsn: str, path: Path) -> None:
    r = _psql(dsn, path.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr


def _net(dsn: str, status: str) -> int:
    return _count(dsn, f"SELECT total_net_paise FROM payroll_runs WHERE id = '{RUN[status]}';")


def _status(dsn: str, status: str) -> str:
    return _ok(dsn, f"SELECT status FROM payroll_runs WHERE id = '{RUN[status]}';")


# ── a released run is not changed, reopened or deleted from a signed-in session ─────────────────────────────────
@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_released_runs_figures_cannot_be_rewritten(db, who, released):
    r = _as(db, who, f"UPDATE payroll_runs SET total_net_paise = 1, total_tds_paise = 1 WHERE id = '{RUN[released]}';")
    assert _refused(r, "cannot be changed from a signed-in session", released), r.stderr
    assert _net(db, released) == NET


@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_released_run_cannot_be_reopened_without_reversing_its_books(db, who, released):
    r = _as(db, who, f"UPDATE payroll_runs SET status = 'review' WHERE id = '{RUN[released]}';")
    assert _refused(r, "Release tab"), r.stderr
    assert _status(db, released) == released


@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_released_run_cannot_be_deleted_and_its_release_log_survives(db, who, released):
    r = _as(db, who, f"DELETE FROM payroll_runs WHERE id = '{RUN[released]}';")
    assert _refused(r, "cannot be changed from a signed-in session"), r.stderr
    assert _status(db, released) == released
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN[released]}';") == 1
    assert _count(db, "SELECT count(*) FROM payroll_run_transitions;") == 1


@pytest.mark.parametrize("who", WHO)
def test_an_upsert_cannot_reach_a_released_run_by_id_or_by_month(db, who):
    """INSERT ... ON CONFLICT DO UPDATE takes the UPDATE branch for a conflicting row, and that fires the trigger."""
    by_id = _as(db, who, f"INSERT INTO payroll_runs (id, firm_id, client_id, month) "
                         f"VALUES ('{RUN['finalized']}', '{FIRM}', '{CLIENT}', '2026-06') "
                         f"ON CONFLICT (id) DO UPDATE SET total_net_paise = 1;")
    assert _refused(by_id, "cannot be changed from a signed-in session"), by_id.stderr
    by_month = _as(db, who, f"INSERT INTO payroll_runs (firm_id, client_id, month) "
                            f"VALUES ('{FIRM}', '{CLIENT}', '2026-07') "
                            f"ON CONFLICT (firm_id, client_id, month) DO UPDATE SET total_net_paise = 1;")
    assert _refused(by_month, "cannot be changed from a signed-in session"), by_month.stderr
    assert _net(db, "finalized") == NET and _net(db, "paid") == NET


@pytest.mark.parametrize("target", ["finalized", "paid"])
@pytest.mark.parametrize("source", ["draft", "review"])
@pytest.mark.parametrize("who", WHO)
def test_a_run_cannot_be_released_by_setting_its_status(db, who, source, target):
    """Released means a posted journal, and only the API's finalise posts one."""
    r = _as(db, who, f"UPDATE payroll_runs SET status = '{target}' WHERE id = '{RUN[source]}';")
    assert _refused(r, "Release tab", target), r.stderr
    assert _status(db, source) == source


@pytest.mark.parametrize("target", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_run_cannot_be_inserted_already_released(db, who, target):
    r = _as(db, who, f"INSERT INTO payroll_runs (firm_id, client_id, month, status) "
                     f"VALUES ('{FIRM}', '{CLIENT}', '2026-08', '{target}');")
    assert _refused(r, target), r.stderr
    assert _count(db, "SELECT count(*) FROM payroll_runs WHERE month = '2026-08';") == 0


# ── the control: a draft or review run is written exactly as before ─────────────────────────────────────────────
@pytest.mark.parametrize("unreleased", ["draft", "review"])
@pytest.mark.parametrize("who", WHO)
def test_an_unreleased_run_is_still_written_by_someone_the_tier_lets_write(db, who, unreleased):
    r = _as(db, who, f"UPDATE payroll_runs SET total_net_paise = 7 WHERE id = '{RUN[unreleased]}';")
    assert r.returncode == 0, r.stderr
    assert _net(db, unreleased) == 7


@pytest.mark.parametrize("who", WHO)
def test_a_draft_run_can_still_be_moved_to_review_and_back(db, who):
    r = _as(db, who, f"UPDATE payroll_runs SET status = 'review' WHERE id = '{RUN['draft']}'; "
                     f"UPDATE payroll_runs SET status = 'draft' WHERE id = '{RUN['draft']}';")
    assert r.returncode == 0, r.stderr
    assert _status(db, "draft") == "draft"


@pytest.mark.parametrize("who", WHO)
def test_a_new_draft_run_can_still_be_inserted(db, who):
    r = _as(db, who, f"INSERT INTO payroll_runs (firm_id, client_id, month) VALUES ('{FIRM}', '{CLIENT}', '2026-09');")
    assert r.returncode == 0, r.stderr
    assert _count(db, "SELECT count(*) FROM payroll_runs WHERE month = '2026-09' AND status = 'draft';") == 1


@pytest.mark.parametrize("who", WHO)
def test_an_unreleased_run_can_still_be_deleted_with_its_slips(db, who):
    r = _as(db, who, f"DELETE FROM payroll_runs WHERE id = '{RUN['draft']}';")
    assert r.returncode == 0, r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN['draft']}';") == 0


# ── payslips ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_released_runs_payslip_cannot_be_rewritten(db, who, released):
    r = _as(db, who, f"UPDATE payroll_slips SET net_paise = 1, tds_paise = 1 WHERE id = '{SLIP[released]}';")
    assert _refused(r, "payslips of a finalized or paid payroll run"), r.stderr
    assert _count(db, f"SELECT net_paise FROM payroll_slips WHERE id = '{SLIP[released]}';") == NET


@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_released_runs_payslip_cannot_be_deleted(db, who, released):
    r = _as(db, who, f"DELETE FROM payroll_slips WHERE id = '{SLIP[released]}';")
    assert _refused(r, "payslips of a finalized or paid payroll run"), r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE id = '{SLIP[released]}';") == 1


@pytest.mark.parametrize("released", ["finalized", "paid"])
@pytest.mark.parametrize("who", WHO)
def test_a_payslip_cannot_be_added_to_a_released_run(db, who, released):
    r = _as(db, who, f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                     f"VALUES ('{RUN[released]}', '{EMP2}', 1, 1);")
    assert _refused(r, "added to, or moved into"), r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN[released]}';") == 1


@pytest.mark.parametrize("who", WHO)
def test_a_payslip_cannot_be_moved_into_a_released_run(db, who):
    r = _as(db, who, f"UPDATE payroll_slips SET run_id = '{RUN['finalized']}', employee_id = '{EMP2}' "
                     f"WHERE id = '{SLIP['draft']}';")
    assert _refused(r, "added to, or moved into"), r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN['draft']}';") == 1


@pytest.mark.parametrize("who", WHO)
def test_a_payslip_cannot_be_moved_out_of_a_released_run(db, who):
    r = _as(db, who, f"UPDATE payroll_slips SET run_id = '{RUN['draft']}', employee_id = '{EMP2}' "
                     f"WHERE id = '{SLIP['finalized']}';")
    assert _refused(r, "payslips of a finalized or paid payroll run"), r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN['finalized']}';") == 1


@pytest.mark.parametrize("who", WHO)
def test_an_upsert_cannot_reach_a_released_runs_payslip(db, who):
    r = _as(db, who, f"INSERT INTO payroll_slips (id, run_id, employee_id, gross_paise, net_paise) "
                     f"VALUES ('{SLIP['finalized']}', '{RUN['finalized']}', '{EMP1}', 1, 1) "
                     f"ON CONFLICT (id) DO UPDATE SET net_paise = 1;")
    assert _refused(r, "added to, or moved into"), r.stderr
    assert _count(db, f"SELECT net_paise FROM payroll_slips WHERE id = '{SLIP['finalized']}';") == NET


@pytest.mark.parametrize("unreleased", ["draft", "review"])
@pytest.mark.parametrize("who", WHO)
def test_the_slips_of_an_unreleased_run_are_still_written(db, who, unreleased):
    r = _as(db, who, f"UPDATE payroll_slips SET net_paise = 9 WHERE id = '{SLIP[unreleased]}'; "
                     f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                     f"VALUES ('{RUN[unreleased]}', '{EMP2}', 2, 2); "
                     f"DELETE FROM payroll_slips WHERE run_id = '{RUN[unreleased]}' AND employee_id = '{EMP2}';")
    assert r.returncode == 0, r.stderr
    assert _count(db, f"SELECT net_paise FROM payroll_slips WHERE id = '{SLIP[unreleased]}';") == 9


# ── whoever is signed in, not only the two whom the tier lets write ─────────────────────────────────────────────
def test_the_employee_cannot_add_a_payslip_to_a_released_run(db):
    """Row security would refuse this too; for a released run this trigger answers first, in its own words."""
    r = _as(db, "employee", f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                            f"VALUES ('{RUN['finalized']}', '{EMP1}', 1, 1);")
    assert _refused(r, "added to, or moved into"), r.stderr
    assert _count(db, "SELECT count(*) FROM payroll_slips WHERE net_paise = 1;") == 0


def test_an_unassigned_executive_cannot_insert_a_released_run(db):
    r = _as(db, "executive", f"INSERT INTO payroll_runs (firm_id, client_id, month, status) "
                             f"VALUES ('{FIRM}', '{CLIENT}', '2026-08', 'finalized');")
    assert _refused(r), r.stderr
    assert _count(db, "SELECT count(*) FROM payroll_runs WHERE month = '2026-08';") == 0


@pytest.mark.parametrize("who", ["employee", "executive"])
def test_someone_row_security_already_hides_the_rows_from_changes_nothing_either_way(db, who):
    """For an UPDATE or DELETE, row security filters the rows before the trigger sees any: no error, no change."""
    r = _as(db, who, f"UPDATE payroll_runs SET total_net_paise = 1 WHERE id = '{RUN['finalized']}'; "
                     f"DELETE FROM payroll_slips WHERE id = '{SLIP['finalized']}';")
    assert r.returncode == 0, r.stderr
    assert _net(db, "finalized") == NET
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE id = '{SLIP['finalized']}';") == 1


# ── a cascade started by a signed-in session is judged as that session ──────────────────────────────────────────
def test_a_signed_in_session_cannot_delete_an_employee_with_a_released_payslip(db):
    r = _as(db, "partner", f"DELETE FROM payroll_employees WHERE id = '{EMP1}';")
    assert _refused(r, "payslips of a finalized or paid payroll run"), r.stderr
    assert _count(db, f"SELECT count(*) FROM payroll_employees WHERE id = '{EMP1}';") == 1
    assert _count(db, "SELECT count(*) FROM payroll_slips;") == 4


def test_a_signed_in_session_cannot_delete_a_client_with_a_released_run(db):
    # The fixture's two posted journals would be refused by the ledger's own immutability triggers when the client's
    # rows cascade, which is a different refusal; remove them (as the owner, with triggers off) so this one is measured.
    _ok(db, "SET session_replication_role = replica; DELETE FROM journal_entries;")
    r = _as(db, "partner", f"DELETE FROM clients WHERE id = '{CLIENT}';")
    assert _refused(r, "payroll run cannot be changed from a signed-in session"), r.stderr
    assert _count(db, f"SELECT count(*) FROM clients WHERE id = '{CLIENT}';") == 1
    assert _count(db, "SELECT count(*) FROM payroll_run_transitions;") == 1


def test_the_same_cascades_still_work_for_the_database_owner(db):
    """A deliberate removal of a client's whole payroll by the administrator is not a signed-in write."""
    _ok(db, f"DELETE FROM payroll_employees WHERE id = '{EMP2}';")
    _ok(db, f"DELETE FROM payroll_runs WHERE id = '{RUN['finalized']}';")
    assert _count(db, "SELECT count(*) FROM payroll_run_transitions;") == 0


# ── the API and the database owner ──────────────────────────────────────────────────────────────────────────────
def test_the_api_still_finalizes_pays_and_reverses_a_run(db):
    """The three transitions the payroll router makes with the privileged client, in the order it makes them, each
    carrying what it carries in production (the journal ids set in the same UPDATE as the status)."""
    r = _as_service(db, f"""
        UPDATE payroll_runs SET status = 'finalized', finalized_at = now(), journal_entry_id = '{JE_ACCRUAL}'
         WHERE id = '{RUN['review']}';
        UPDATE payroll_runs SET status = 'paid', paid_at = now(), payment_reference = 'UTR1',
               disbursement_journal_entry_id = '{JE_DISBURSEMENT}' WHERE id = '{RUN['review']}';
        UPDATE payroll_runs SET status = 'review', journal_entry_id = NULL, disbursement_journal_entry_id = NULL,
               finalized_at = NULL, paid_at = NULL, paid_from_account_id = NULL, payment_reference = NULL
         WHERE id = '{RUN['review']}';
    """)
    assert r.returncode == 0, r.stderr
    assert _status(db, "review") == "review"


def test_the_api_still_recomputes_and_deletes_an_unreleased_run(db):
    r = _as_service(db, f"""
        DELETE FROM payroll_slips WHERE run_id = '{RUN['review']}';
        INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) VALUES ('{RUN['review']}', '{EMP1}', 3, 3);
        UPDATE payroll_runs SET total_net_paise = 3 WHERE id = '{RUN['review']}';
        DELETE FROM payroll_runs WHERE id = '{RUN['draft']}';
    """)
    assert r.returncode == 0, r.stderr
    assert _net(db, "review") == 3


def test_the_api_cannot_finalize_a_run_without_the_journal_that_posted_it(db):
    r = _as_service(db, f"UPDATE payroll_runs SET status = 'finalized', finalized_at = now() WHERE id = '{RUN['review']}';")
    assert r.returncode != 0 and "23514" in r.stderr and "only with the journal that posted it" in r.stderr, r.stderr
    assert _status(db, "review") == "review"


@pytest.mark.parametrize("missing", ["journal_entry_id", "disbursement_journal_entry_id"])
def test_the_api_cannot_mark_a_run_paid_without_both_journals(db, missing):
    values = {"journal_entry_id": f"'{JE_ACCRUAL}'", "disbursement_journal_entry_id": f"'{JE_DISBURSEMENT}'"}
    values[missing] = "NULL"
    assignments = ", ".join(f"{c} = {v}" for c, v in values.items())
    r = _as_service(db, f"UPDATE payroll_runs SET status = 'paid', {assignments} WHERE id = '{RUN['review']}';")
    assert r.returncode != 0 and "23514" in r.stderr and "its disbursement journal" in r.stderr, r.stderr
    assert _status(db, "review") == "review"


def test_the_api_cannot_insert_a_run_already_released_without_its_journal(db):
    r = _as_service(db, f"INSERT INTO payroll_runs (firm_id, client_id, month, status) "
                        f"VALUES ('{FIRM}', '{CLIENT}', '2026-08', 'finalized');")
    assert r.returncode != 0 and "23514" in r.stderr, r.stderr


def test_a_run_released_earlier_is_not_asked_for_evidence_it_never_had(db):
    """The check is on the transition only: the seeded runs have no journal ids (the owner wrote them), and the API
    changing a figure on one, or paying it with both journals, must not be refused for what the row lacked."""
    r = _as_service(db, f"UPDATE payroll_runs SET total_net_paise = 8 WHERE id = '{RUN['paid']}';")
    assert r.returncode == 0, r.stderr
    r = _as_service(db, f"UPDATE payroll_runs SET status = 'paid', journal_entry_id = '{JE_ACCRUAL}', "
                        f"disbursement_journal_entry_id = '{JE_DISBURSEMENT}' WHERE id = '{RUN['finalized']}';")
    assert r.returncode == 0, r.stderr


def test_the_database_owner_can_still_repair_a_released_run(db):
    """A deliberate, reviewable act; also what lets a fixture seed a released run."""
    _ok(db, f"UPDATE payroll_runs SET total_net_paise = 5 WHERE id = '{RUN['finalized']}';")
    assert _net(db, "finalized") == 5


# ── the shape of the thing ──────────────────────────────────────────────────────────────────────────────────────
def test_exactly_these_triggers_guard_the_two_tables(db):
    got = _ok(db, """
        SELECT c.relname || ':' || t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
         WHERE NOT t.tgisinternal AND c.relname IN ('payroll_runs', 'payroll_slips')
           AND t.tgname NOT LIKE 'trg_audit%' ORDER BY 1;""").splitlines()
    assert got == ["payroll_runs:a_released_payroll_run_is_not_written_by_a_session",
                   "payroll_slips:a_released_runs_payslips_are_not_written_by_a_session"]


def test_no_browser_role_can_call_the_trigger_functions_directly(db):
    for fn in ("refuse_a_signed_in_change_to_a_released_payroll_run",
               "refuse_a_signed_in_change_to_the_payslips_of_a_released_run"):
        assert _ok(db, f"SELECT has_function_privilege('authenticated', 'public.{fn}()', 'EXECUTE')"
                       f" OR has_function_privilege('anon', 'public.{fn}()', 'EXECUTE');") == "f"


def test_the_released_statuses_are_the_ones_the_triggers_name(db):
    """The triggers write 'finalized' and 'paid' out. A status added to the CHECK later is one they do not know, and
    this fails the day it is added so somebody decides whether it is released."""
    statuses = _ok(db, """
        SELECT string_agg(s, ',' ORDER BY s) FROM (
          SELECT unnest(string_to_array(regexp_replace(pg_get_constraintdef(oid), '^.*ARRAY\\[|\\].*$', '', 'g'), ', ')) AS s
            FROM pg_constraint WHERE conrelid = 'public.payroll_runs'::regclass AND conname = 'payroll_runs_status_check'
        ) q;""")
    named = sorted(x.split("::")[0].strip("'") for x in statuses.split(","))
    assert named == ["draft", "finalized", "paid", "review"], (
        f"payroll_runs_status_check now allows {named}: decide whether the new status is released and, if it is, "
        "extend both trigger functions, my_payroll_run_ids() and the API's _PAYROLL_UNRELEASED")


def test_498_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    r = _as(db, "partner", f"UPDATE payroll_runs SET total_net_paise = 1 WHERE id = '{RUN['finalized']}';")
    assert _refused(r, "cannot be changed from a signed-in session"), r.stderr


# ── the negative control ────────────────────────────────────────────────────────────────────────────────────────
def test_its_own_rollback_puts_every_hole_back(db):
    """Without the triggers, the very statements refused above go through, release log included. This is what makes
    the refusals mean the migration and not something already in the schema, and it is why the 'release log
    survives' assertion above is not vacuously true."""
    _apply(db, ROLLBACK)
    as_manager = lambda sql: _as(db, "manager", sql).returncode == 0    # noqa: E731
    assert as_manager(f"UPDATE payroll_runs SET total_net_paise = 1 WHERE id = '{RUN['finalized']}';")
    assert as_manager(f"UPDATE payroll_runs SET status = 'review' WHERE id = '{RUN['paid']}';")
    assert as_manager(f"UPDATE payroll_runs SET status = 'paid' WHERE id = '{RUN['draft']}';")
    assert as_manager(f"INSERT INTO payroll_runs (firm_id, client_id, month, status) "
                      f"VALUES ('{FIRM}', '{CLIENT}', '2026-08', 'finalized');")
    assert as_manager(f"UPDATE payroll_slips SET net_paise = 1 WHERE id = '{SLIP['finalized']}';")
    assert as_manager(f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                      f"VALUES ('{RUN['finalized']}', '{EMP2}', 1, 1);")
    assert as_manager(f"UPDATE payroll_slips SET run_id = '{RUN['finalized']}', employee_id = '{EMP2}' "
                      f"WHERE id = '{SLIP['draft']}';")
    assert as_manager(f"DELETE FROM payroll_slips WHERE id = '{SLIP['paid']}';")
    assert as_manager(f"DELETE FROM payroll_runs WHERE id = '{RUN['finalized']}';")
    assert _count(db, "SELECT count(*) FROM payroll_run_transitions;") == 0      # the release log went with it

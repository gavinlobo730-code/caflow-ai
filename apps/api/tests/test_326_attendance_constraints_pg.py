"""
Migration 326, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. The identity is a CHECK on the table, not only a rule in Python.
       app/payroll/attendance/page.tsx wrote this table straight through
       PostgREST, and ~83 tables are written that way — rbac() never runs there
       and the constraint is the only thing that survives.

    2. NOT VALID means "guard every future write, leave history alone". Rows
       written by the old bulk save do not all satisfy the identity — precisely
       because calcLOP floored the remainder at zero — so validating would fail
       the migration on the data the constraint exists to stop being created,
       which would leave it unapplied and the bug open. These tests assert both
       halves: a new bad row is refused, and an OLD bad row still sits there.

    3. Manager+ writes. Migration 027's only policy scoped attendance by firm
       and nothing else, so a Reviewer — whose whole role is to look — could
       change what somebody is paid, from the browser.

THE TRAP THESE ARE BUILT AROUND
    A denied INSERT raises. A denied UPDATE does NOT: PostgreSQL silently skips
    rows failing USING, so the statement "succeeds" having changed nothing. The
    UPDATE cases assert the ROW COUNT, because the obvious simplification is
    the one that makes them vacuous.

NEGATIVE CONTROL
    Drop the two CHECK constraints and every arithmetic test passes a
    contradictory row straight in — including the 26-present-plus-4-days-leave
    row that was a full month's salary. Create the three policies PERMISSIVE
    instead of RESTRICTIVE and the Reviewer/Executive tests fail, because a
    permissive policy ORs with migration 027's firm policy and WIDENS access.

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
    reason="attendance contract proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000326"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000326"
EMP = "cccccccc-0000-0000-0000-000000000326"
UID = {
    "Partner":   "d0000000-0000-0000-0000-000000000326",
    "Manager":   "d0000000-0000-0000-0000-000000000327",
    "Executive": "d0000000-0000-0000-0000-000000000328",
    "Reviewer":  "d0000000-0000-0000-0000-000000000329",
}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(dsn: str, role: str, sql: str) -> subprocess.CompletedProcess:
    """As the signed-in user holding `role`.

    SET LOCAL ROLE authenticated matters: the table is owned by postgres and an
    owner BYPASSES RLS, so running these as the migration user would make every
    assertion pass whatever the policies said.
    """
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID[role]}\"}}'; "
                      f"{sql} ROLLBACK;")


def _rows_changed(dsn: str, role: str, statement: str) -> int:
    r = _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                   f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID[role]}\"}}'; "
                   f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; ROLLBACK;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m326_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "326_attendance_is_something_somebody_entered.sql" not in pg_template.failed, (
            "migration 326 did not apply — everything below would pass vacuously")
        stmts = [
            "INSERT INTO auth.users (id, email) VALUES "
            + ", ".join(f"('{u}', '{r}326@t.in')" for r, u in UID.items()) + ";",
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F326','f326@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C326','Private Limited','AAACA1234E');",
            "INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            + ", ".join(f"('{u}','{FIRM}','{u}','{r}','{r}326@t.in','{r}')"
                        for r, u in UID.items()) + ";",
            "INSERT INTO user_client_assignments (user_id, client_id, firm_id) VALUES "
            + ", ".join(f"('{UID[r]}','{CLIENT}','{FIRM}')"
                        for r in ("Manager", "Executive", "Reviewer")) + ";",
            f"INSERT INTO payroll_employees (id, firm_id, client_id, name) "
            f"VALUES ('{EMP}','{FIRM}','{CLIENT}','Asha');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _att(month=8, **cols) -> str:
    base = {"working_days": 26, "days_present": 26, "casual_leaves": 0,
            "sick_leaves": 0, "earned_leaves": 0, "lop_days": 0}
    base.update(cols)
    keys = ", ".join(base)
    vals = ", ".join(str(v) for v in base.values())
    return (f"INSERT INTO attendance (firm_id, employee_id, month, year, {keys}) "
            f"VALUES ('{FIRM}','{EMP}',{month},2026,{vals});")


# ── the identity, enforced by the table ──────────────────────────────────────

def test_a_row_whose_days_add_up_is_accepted(db):
    r = _psql(db, _att(days_present=22, casual_leaves=2, lop_days=2))
    assert r.returncode == 0, r.stderr


def test_the_row_that_used_to_be_a_free_full_month_is_refused(db):
    """26 present plus four days' casual leave in a 26-day month. calcLOP's
    Math.max(0, …) made this zero loss of pay and full pay."""
    r = _psql(db, _att(days_present=26, casual_leaves=4, lop_days=0))
    assert r.returncode != 0
    assert "attendance_days_add_up_to_the_working_days" in r.stderr


def test_days_that_fall_short_are_refused_too(db):
    """The other direction: 20 present and no leave, but loss of pay recorded
    as zero, would pay a full month for twenty days' work."""
    r = _psql(db, _att(days_present=20, lop_days=0))
    assert r.returncode != 0
    assert "attendance_days_add_up_to_the_working_days" in r.stderr


def test_a_month_longer_than_any_month_is_refused(db):
    r = _psql(db, _att(working_days=40, days_present=40))
    assert r.returncode != 0
    assert "attendance_days_are_within_a_month" in r.stderr


def test_zero_working_days_is_refused(db):
    """_compute_slip floors working_days at 1 to avoid dividing by zero —
    because nothing here stopped a zero reaching it."""
    r = _psql(db, _att(working_days=0, days_present=0))
    assert r.returncode != 0
    assert "attendance_days_are_within_a_month" in r.stderr


def test_a_negative_day_count_is_refused(db):
    r = _psql(db, _att(days_present=27, lop_days=-1))
    assert r.returncode != 0
    assert "attendance_days_are_within_a_month" in r.stderr


def test_an_update_that_breaks_the_identity_is_refused(db):
    """NOT VALID skips the initial scan; it does NOT stop applying to updates."""
    assert _psql(db, _att(days_present=22, lop_days=4)).returncode == 0
    r = _psql(db, f"UPDATE attendance SET lop_days = 0 WHERE employee_id = '{EMP}';")
    assert r.returncode != 0
    assert "attendance_days_add_up_to_the_working_days" in r.stderr


def test_the_constraints_are_declared_not_valid(db):
    """The half that makes this migration applicable at all. History written by
    the old bulk save does not satisfy the identity, and validating would fail
    the migration on exactly the data it exists to stop being created."""
    r = _psql(db, "SELECT conname, convalidated FROM pg_constraint "
                  "WHERE conname LIKE 'attendance_days%' ORDER BY conname;", tuples=True)
    assert r.returncode == 0, r.stderr
    rows = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    assert len(rows) == 2, rows
    assert all(ln.endswith("|f") for ln in rows), f"both must be NOT VALID: {rows}"


# ── who said so ──────────────────────────────────────────────────────────────

def test_a_row_can_record_who_entered_it(db):
    r = _psql(db, _att(days_present=26).replace(
        f"VALUES ('{FIRM}','{EMP}',8,2026,",
        f"VALUES ('{FIRM}','{EMP}',8,2026,").replace(
        "INSERT INTO attendance (firm_id, employee_id, month, year, ",
        "INSERT INTO attendance (entered_by, entered_at, firm_id, employee_id, month, year, ").replace(
        f"VALUES ('{FIRM}'", f"VALUES ('{UID['Manager']}', now(), '{FIRM}'"))
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT entered_by IS NOT NULL AND entered_at IS NOT NULL "
                    "FROM attendance;", tuples=True)
    assert got.stdout.strip() == "t"


def test_authorship_is_nullable_because_history_has_none(db):
    """Every row already in this table came from the bulk save, and the honest
    answer to 'who entered this' for those is that nobody knows."""
    assert _psql(db, _att()).returncode == 0
    got = _psql(db, "SELECT entered_by IS NULL FROM attendance;", tuples=True)
    assert got.stdout.strip() == "t"


# ── who may write it ─────────────────────────────────────────────────────────

def test_a_manager_can_enter_attendance(db):
    """The other half of any access rule. One that also blocks the people
    entitled to the action is one that gets reverted the same week."""
    r = _as(db, "Manager", _att(days_present=24, lop_days=2))
    assert r.returncode == 0, r.stderr


def test_a_partner_can_enter_attendance(db):
    assert _as(db, "Partner", _att(days_present=24, lop_days=2)).returncode == 0


def test_a_reviewer_cannot_change_what_somebody_is_paid(db):
    """The headline of section 3. Migration 027's policy scoped this table by
    firm and by nothing else, and a Reviewer's whole role is to look."""
    r = _as(db, "Reviewer", _att(days_present=24, lop_days=2))
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_an_executive_cannot_either(db):
    r = _as(db, "Executive", _att(days_present=24, lop_days=2))
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_a_reviewer_cannot_edit_an_existing_row(db):
    """The row count IS the assertion: a policy-denied UPDATE reports success
    having changed nothing, so 'no error' would pass with no policy at all."""
    assert _psql(db, _att(days_present=24, lop_days=2)).returncode == 0
    assert _rows_changed(
        db, "Reviewer",
        "UPDATE attendance SET days_present = 26, lop_days = 0") == 0


def test_a_manager_can_edit_an_existing_row(db):
    assert _psql(db, _att(days_present=24, lop_days=2)).returncode == 0
    assert _rows_changed(
        db, "Manager",
        "UPDATE attendance SET days_present = 25, lop_days = 1") == 1


def test_a_reviewer_cannot_delete_a_row(db):
    assert _psql(db, _att(days_present=24, lop_days=2)).returncode == 0
    assert _rows_changed(db, "Reviewer", "DELETE FROM attendance") == 0


# ── the cut-off ──────────────────────────────────────────────────────────────

_SETTINGS = (f"INSERT INTO client_payroll_settings (firm_id, client_id, inputs_due_day) "
             f"VALUES ('{FIRM}','{CLIENT}',5);")


def test_a_cutoff_day_is_recorded(db):
    assert _psql(db, _SETTINGS).returncode == 0


@pytest.mark.parametrize("day", [0, 29, 30, 31])
def test_a_cutoff_day_no_month_reliably_has_is_refused(db, day):
    """Capped at 28 because every month has a 28th and none reliably has a
    29th. A cut-off of the 30th would silently not exist in February."""
    r = _psql(db, _SETTINGS.replace(",5)", f",{day})"))
    assert r.returncode != 0
    assert "client_payroll_settings_inputs_due_day_check" in r.stderr


def test_no_cutoff_is_a_permitted_state(db):
    """A firm that has not agreed a date with this client has not agreed one,
    and the read reports that rather than a default nobody promised."""
    r = _psql(db, _SETTINGS.replace(", inputs_due_day)", ")").replace(",5)", ")"))
    assert r.returncode == 0, r.stderr


def test_one_settings_row_per_client(db):
    assert _psql(db, _SETTINGS).returncode == 0
    r = _psql(db, _SETTINGS)
    assert r.returncode != 0 and "unique" in r.stderr.lower()


def test_an_executive_cannot_move_the_cutoff(db):
    r = _as(db, "Executive", _SETTINGS)
    assert r.returncode != 0 and "row-level security" in r.stderr

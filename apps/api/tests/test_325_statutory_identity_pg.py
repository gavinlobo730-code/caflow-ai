"""
Migration 325, proved against real PostgreSQL.

WHAT IS BEING PROVED
    Three things the SQL asserts and Python cannot:

    1. The TAN CHECK. `^[A-Z]{4}[0-9]{5}[A-Z]$` at the column, not only in
       routers/payroll.py — CLAUDE.md records that ~83 tables are written
       DIRECTLY from the browser through PostgREST, where rbac() never runs and
       the constraint is the only check that survives.

    2. The NON-BLANK checks on the four registrations that have no format. They
       are the whole reason those columns can be permissive: an empty string
       recorded as an identifier is exactly the silent default this table
       exists to end, and it is the one malformation that can be ruled out
       without knowing the format.

    3. Firm isolation and the Manager+ write guard, run as `authenticated`
       against the real policies. A TAN goes onto a filed quarter; an Executive
       keying one is a change somebody senior should be making.

THE TRAP THESE ARE BUILT AROUND
    A denied INSERT raises. A denied UPDATE or DELETE does NOT — PostgreSQL
    silently skips rows failing USING, so the statement "succeeds" having
    changed nothing. Every UPDATE case below asserts the ROW COUNT, because the
    obvious simplification is the one that makes it vacuous.

NEGATIVE CONTROL
    Drop the CHECK constraints from migration 325 and the four malformed-value
    tests pass a blank or a PAN straight in. Create the role policies
    PERMISSIVE instead of RESTRICTIVE and the two Executive tests fail — a
    permissive policy ORs with the firm policy and WIDENS access, which is
    invisible in pg_policies.

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
    reason="statutory identity proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000325"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000326"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000325"
OTHER_CLIENT = "bbbbbbbb-0000-0000-0000-000000000326"
UID = {
    "Partner":   "c0000000-0000-0000-0000-000000000325",
    "Manager":   "c0000000-0000-0000-0000-000000000326",
    "Executive": "c0000000-0000-0000-0000-000000000327",
}
OTHER_UID = "c0000000-0000-0000-0000-000000000328"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(dsn: str, uid: str, sql: str) -> subprocess.CompletedProcess:
    """Run `sql` as a signed-in user.

    SET LOCAL ROLE authenticated matters: these tables are owned by postgres and
    an owner BYPASSES RLS entirely, so running as the migration user would make
    every isolation assertion below pass whatever the policies said.
    """
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{uid}\"}}'; "
                      f"{sql} ROLLBACK;")


def _rows_changed(dsn: str, uid: str, statement: str) -> int:
    r = _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                   f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{uid}\"}}'; "
                   f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; ROLLBACK;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m325_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "325_a_client_has_its_own_statutory_registrations.sql" not in pg_template.failed, (
            "migration 325 did not apply — everything below would pass vacuously")
        stmts = [
            "INSERT INTO auth.users (id, email) VALUES "
            + ", ".join(f"('{u}', '{r}325@t.in')" for r, u in UID.items())
            + f", ('{OTHER_UID}', 'other325@t.in');",
            f"INSERT INTO firms (id, name, email) VALUES "
            f"('{FIRM}', 'F325', 'f325@t.in'), ('{OTHER_FIRM}', 'F326', 'f326@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C325', 'Private Limited', 'AAACA1234E'), "
            f"('{OTHER_CLIENT}', '{OTHER_FIRM}', 'C326', 'Private Limited', 'AAACA1234F');",
            "INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            + ", ".join(f"('{u}', '{FIRM}', '{u}', '{r}', '{r}325@t.in', '{r}')"
                        for r, u in UID.items())
            + f", ('{OTHER_UID}', '{OTHER_FIRM}', '{OTHER_UID}', 'O', 'other325@t.in', 'Partner');",
            "INSERT INTO user_client_assignments (user_id, client_id, firm_id) VALUES "
            + ", ".join(f"('{UID[r]}', '{CLIENT}', '{FIRM}')" for r in ("Manager", "Executive"))
            + ";",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _ident(**cols) -> str:
    keys = ", ".join(cols)
    vals = ", ".join("NULL" if v is None else f"'{v}'" for v in cols.values())
    return (f"INSERT INTO client_statutory_identity (firm_id, client_id, {keys}) "
            f"VALUES ('{FIRM}', '{CLIENT}', {vals});")


# ── 1. the TAN check, at the column ──────────────────────────────────────────

def test_a_well_formed_tan_is_accepted(db):
    r = _psql(db, _ident(tan="MUMA12345B"))
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("bad", ["MUMA12345", "MUMA123456B", "AAAAA1234A", "muma12345b", ""])
def test_a_string_that_is_not_a_tan_is_refused_by_the_database(db, bad):
    """Not only by the router. The browser writes ~83 tables directly through
    PostgREST, where rbac() never runs — the constraint is what survives."""
    r = _psql(db, _ident(tan=bad))
    assert r.returncode != 0
    assert "client_statutory_identity_tan_check" in r.stderr


def test_a_null_tan_is_allowed_because_absent_is_a_real_answer(db):
    r = _psql(db, _ident(tan=None, epf_establishment_code="MHBAN0012345000"))
    assert r.returncode == 0, r.stderr


# ── 2. the four with no format still cannot be blank ─────────────────────────

@pytest.mark.parametrize("col", ["epf_establishment_code", "esic_employer_code", "lin"])
def test_a_blank_registration_number_is_refused(db, col):
    """The one malformation rulable out without knowing the format. An empty
    string recorded as an identifier is the silent default this table exists to
    end — it reads as "recorded" everywhere and identifies nothing."""
    r = _psql(db, _ident(**{col: "   "}))
    assert r.returncode != 0
    assert f"client_statutory_identity_{col}_check" in r.stderr


def test_a_regional_epf_code_is_stored_exactly_as_given(db):
    """No pattern is invented. These vary by region, vintage and issuing office,
    and a regex from memory would refuse a valid registration rather than catch
    a typo."""
    assert _psql(db, _ident(epf_establishment_code="MHBAN0012345000")).returncode == 0
    assert _psql(db, "SELECT epf_establishment_code FROM client_statutory_identity;",
                 tuples=True).stdout.strip() == "MHBAN0012345000"


# ── 3. one row per client, one PT row per state ──────────────────────────────

def test_a_second_identity_row_for_the_same_client_is_refused(db):
    assert _psql(db, _ident(tan="MUMA12345B")).returncode == 0
    r = _psql(db, _ident(tan="MUMB12345C"))
    assert r.returncode != 0 and "unique" in r.stderr.lower()


def test_two_states_can_hold_two_pt_registrations(db):
    r = _psql(db, f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) "
                  f"VALUES ('{FIRM}','{CLIENT}','MH','27123456789P'), "
                  f"('{FIRM}','{CLIENT}','KA','KA-PTRC-9');")
    assert r.returncode == 0, r.stderr


def test_the_same_state_twice_is_refused(db):
    _psql(db, f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) "
              f"VALUES ('{FIRM}','{CLIENT}','MH','27123456789P');")
    r = _psql(db, f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) "
                  f"VALUES ('{FIRM}','{CLIENT}','MH','OTHER');")
    assert r.returncode != 0 and "unique" in r.stderr.lower()


def test_a_state_that_is_not_a_two_letter_code_is_refused(db):
    r = _psql(db, f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) "
                  f"VALUES ('{FIRM}','{CLIENT}','Maharashtra','X');")
    assert r.returncode != 0 and "client_pt_registrations_state_check" in r.stderr


# ── 4. firm isolation and the Manager+ guard, as `authenticated` ─────────────

def test_a_partner_can_record_an_identity(db):
    """The other half of any access rule. One that also blocks the people
    entitled to the action is one that gets reverted the same week."""
    r = _as(db, UID["Partner"], _ident(tan="MUMA12345B"))
    assert r.returncode == 0, r.stderr


def test_a_manager_can_record_an_identity(db):
    r = _as(db, UID["Manager"], _ident(tan="MUMA12345B"))
    assert r.returncode == 0, r.stderr


def test_an_executive_cannot_record_an_identity(db):
    """payroll:write is Manager+, and these numbers go onto filed returns."""
    r = _as(db, UID["Executive"], _ident(tan="MUMA12345B"))
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_an_executive_cannot_record_a_pt_registration(db):
    r = _as(db, UID["Executive"],
            f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) "
            f"VALUES ('{FIRM}','{CLIENT}','MH','27123456789P');")
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_another_firm_cannot_read_this_client_s_tan(db):
    assert _psql(db, _ident(tan="MUMA12345B")).returncode == 0
    r = _psql(db, f"BEGIN; SET LOCAL ROLE authenticated; "
                  f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{OTHER_UID}\"}}'; "
                  f"SELECT count(*) FROM client_statutory_identity; ROLLBACK;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] == "0"


def test_another_firm_cannot_overwrite_this_client_s_tan(db):
    """The row count is the assertion. A policy-denied UPDATE reports success
    having changed nothing, so "no error" would pass with no policy at all."""
    assert _psql(db, _ident(tan="MUMA12345B")).returncode == 0
    assert _rows_changed(db, OTHER_UID,
                         "UPDATE client_statutory_identity SET tan = 'DELM99999Z'") == 0
    assert _psql(db, "SELECT tan FROM client_statutory_identity;",
                 tuples=True).stdout.strip() == "MUMA12345B"


def test_a_manager_in_the_owning_firm_can_overwrite_it(db):
    assert _psql(db, _ident(tan="MUMA12345B")).returncode == 0
    assert _rows_changed(db, UID["Manager"],
                         "UPDATE client_statutory_identity SET tan = 'DELM99999Z'") == 1


def test_an_executive_cannot_overwrite_it(db):
    assert _psql(db, _ident(tan="MUMA12345B")).returncode == 0
    assert _rows_changed(db, UID["Executive"],
                         "UPDATE client_statutory_identity SET tan = 'DELM99999Z'") == 0

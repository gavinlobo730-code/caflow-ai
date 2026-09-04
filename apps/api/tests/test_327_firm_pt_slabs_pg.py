"""
Migration 327, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. The provenance columns are NOT NULL. The entire argument for letting a
       hand-entered figure drive a statutory deduction is that a named person
       read a named notification on a named date; a row without that is an
       unsourced number in a payslip, which is the fault the refusals in
       professional_tax.py exist to prevent, with a nicer interface. This has
       to hold at the COLUMN, because ~83 tables are written directly from the
       browser through PostgREST where rbac() never runs.

    2. The band shape. to_paise must exceed from_paise (an inverted band would
       match nothing and read as a nil slab), and no two bands in one version
       may start at the same figure (the lookup would be order-dependent).

    3. Manager+ writes. These figures drive a deduction across EVERY client of
       the firm at once, so the blast radius of a typo here is larger than
       anything else in payroll — larger than migration 325's per-client
       identity.

THE TRAP
    A denied INSERT raises. A denied UPDATE does NOT — PostgreSQL silently
    skips rows failing USING, so the statement "succeeds" having changed
    nothing. The UPDATE cases assert the ROW COUNT.

NEGATIVE CONTROL
    Make notification_reference and notification_date nullable and the four
    provenance tests pass an unsourced slab straight in. Create the role
    policies PERMISSIVE instead of RESTRICTIVE and the Executive and Reviewer
    tests fail — a permissive policy ORs with the firm policy and WIDENS
    access, which is invisible in pg_policies.

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
    reason="firm PT slab proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000327"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000328"
UID = {
    "Partner":   "e0000000-0000-0000-0000-000000000327",
    "Manager":   "e0000000-0000-0000-0000-000000000328",
    "Executive": "e0000000-0000-0000-0000-000000000329",
    "Reviewer":  "e0000000-0000-0000-0000-00000000032a",
}
OTHER_UID = "e0000000-0000-0000-0000-00000000032b"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    """As a signed-in user — `who` is a role name from UID, or a raw auth id.

    SET LOCAL ROLE authenticated matters: the table is owned by postgres and an
    owner BYPASSES RLS, so running as the migration user would make every
    assertion pass whatever the policies said.
    """
    uid = UID.get(who, who)
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{uid}\"}}'; "
                      f"{sql} ROLLBACK;")


def _rows_changed(dsn: str, who: str, statement: str) -> int:
    uid = UID.get(who, who)
    r = _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                   f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{uid}\"}}'; "
                   f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; ROLLBACK;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m327_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "327_a_firm_records_the_statutory_values_it_reads.sql" not in pg_template.failed, (
            "migration 327 did not apply — everything below would pass vacuously")
        stmts = [
            "INSERT INTO auth.users (id, email) VALUES "
            + ", ".join(f"('{u}', '{r}327@t.in')" for r, u in UID.items())
            + f", ('{OTHER_UID}', 'other327@t.in');",
            f"INSERT INTO firms (id, name, email) VALUES "
            f"('{FIRM}','F327','f327@t.in'), ('{OTHER_FIRM}','F328','f328@t.in');",
            "INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            + ", ".join(f"('{u}','{FIRM}','{u}','{r}','{r}327@t.in','{r}')"
                        for r, u in UID.items())
            + f", ('{OTHER_UID}','{OTHER_FIRM}','{OTHER_UID}','O','other327@t.in','Partner');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _band(**cols) -> str:
    base = {"state": "'GJ'", "effective_from": "'2026-04-01'", "basis": "'monthly'",
            "from_paise": "0", "to_paise": "1200000", "amount_paise": "0",
            "notification_reference": "'GJ/PT/2026-01'", "notification_date": "'2026-03-15'"}
    base.update({k: (v if isinstance(v, str) else str(v)) for k, v in cols.items()})
    keys = ", ".join(base)
    vals = ", ".join(base.values())
    return (f"INSERT INTO firm_pt_slabs (firm_id, {keys}) "
            f"VALUES ('{FIRM}', {vals});")


# ── 1. provenance, at the column ─────────────────────────────────────────────

def test_a_sourced_slab_is_accepted(db):
    assert _psql(db, _band()).returncode == 0, "the ordinary case must work"


def test_a_slab_with_no_notification_reference_is_refused(db):
    r = _psql(db, _band(notification_reference="NULL"))
    assert r.returncode != 0
    assert "notification_reference" in r.stderr


def test_a_blank_notification_reference_is_refused(db):
    """An empty string reads as "recorded" everywhere and sources nothing —
    the same silent default a NULL would be, wearing a value's clothes."""
    r = _psql(db, _band(notification_reference="'   '"))
    assert r.returncode != 0
    assert "firm_pt_slabs_notification_reference_check" in r.stderr


def test_a_slab_with_no_notification_date_is_refused(db):
    r = _psql(db, _band(notification_date="NULL"))
    assert r.returncode != 0
    assert "notification_date" in r.stderr


def test_a_slab_with_no_effective_from_is_refused(db):
    """Without it there is no way to say which month a revision starts in, and
    a run for an earlier month would silently restate a posted period."""
    r = _psql(db, _band(effective_from="NULL"))
    assert r.returncode != 0
    assert "effective_from" in r.stderr


# ── 2. band shape ────────────────────────────────────────────────────────────

def test_an_open_top_band_is_allowed(db):
    assert _psql(db, _band(from_paise=1200000, to_paise="NULL",
                           amount_paise=20000)).returncode == 0


def test_an_inverted_band_is_refused(db):
    """to_paise below from_paise matches no wage at all, so it would read on
    screen as a recorded slab and deduct from nobody."""
    r = _psql(db, _band(from_paise=1200000, to_paise=500000))
    assert r.returncode != 0
    # A CHECK spanning two columns is named for the table, not for a column.
    assert "firm_pt_slabs_check" in r.stderr


def test_a_negative_amount_is_refused(db):
    r = _psql(db, _band(amount_paise=-100))
    assert r.returncode != 0
    assert "firm_pt_slabs_amount_paise_check" in r.stderr


def test_two_bands_starting_at_the_same_figure_are_refused(db):
    """Which one wins would be an accident of row order."""
    assert _psql(db, _band()).returncode == 0
    r = _psql(db, _band(amount_paise=20000))
    assert r.returncode != 0 and "unique" in r.stderr.lower()


def test_the_same_band_in_a_different_version_is_allowed(db):
    """A revision is a NEW effective_from, so the same band figure recurs."""
    assert _psql(db, _band()).returncode == 0
    assert _psql(db, _band(effective_from="'2027-04-01'",
                           notification_reference="'GJ/PT/2027-01'",
                           notification_date="'2027-03-10'")).returncode == 0


def test_an_unknown_basis_is_refused(db):
    r = _psql(db, _band(basis="'quarterly'"))
    assert r.returncode != 0 and "firm_pt_slabs_basis_check" in r.stderr


def test_a_month_that_is_not_a_month_is_refused(db):
    r = _psql(db, _band(months="ARRAY[13]::smallint[]"))
    assert r.returncode != 0 and "firm_pt_slabs_months_check" in r.stderr


def test_named_months_are_allowed(db):
    """A half-yearly levy or a differential month, recorded without a rule
    engine."""
    assert _psql(db, _band(months="ARRAY[9,3]::smallint[]")).returncode == 0


def test_a_state_code_that_is_not_two_letters_is_refused(db):
    r = _psql(db, _band(state="'Gujarat'"))
    assert r.returncode != 0 and "firm_pt_slabs_state_check" in r.stderr


# ── 3. who may write it ──────────────────────────────────────────────────────

def test_a_manager_can_record_a_slab(db):
    """The other half of any access rule — one that blocks the people entitled
    to the action is one that gets reverted the same week."""
    r = _as(db, "Manager", _band())
    assert r.returncode == 0, r.stderr


def test_a_partner_can_record_a_slab(db):
    assert _as(db, "Partner", _band()).returncode == 0


def test_an_executive_cannot_record_a_slab(db):
    """This figure deducts from every client of the firm in that state at once,
    so the blast radius is wider than anything else in payroll."""
    r = _as(db, "Executive", _band())
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_a_reviewer_cannot_record_a_slab(db):
    r = _as(db, "Reviewer", _band())
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_an_executive_cannot_edit_a_recorded_slab(db):
    """The row count IS the assertion: a policy-denied UPDATE reports success
    having changed nothing, so "no error" would pass with no policy at all."""
    assert _psql(db, _band()).returncode == 0
    assert _rows_changed(db, "Executive",
                         "UPDATE firm_pt_slabs SET amount_paise = 99999") == 0


def test_a_manager_can_edit_a_recorded_slab(db):
    assert _psql(db, _band()).returncode == 0
    assert _rows_changed(db, "Manager",
                         "UPDATE firm_pt_slabs SET amount_paise = 5000") == 1


def test_an_executive_cannot_delete_a_recorded_slab(db):
    assert _psql(db, _band()).returncode == 0
    assert _rows_changed(db, "Executive", "DELETE FROM firm_pt_slabs") == 0


# ── 4. firm isolation ────────────────────────────────────────────────────────

def test_another_firm_cannot_read_these_slabs(db):
    assert _psql(db, _band()).returncode == 0
    r = _psql(db, f"BEGIN; SET LOCAL ROLE authenticated; "
                  f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{OTHER_UID}\"}}'; "
                  f"SELECT count(*) FROM firm_pt_slabs; ROLLBACK;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] == "0"


def test_another_firm_cannot_change_these_slabs(db):
    assert _psql(db, _band()).returncode == 0
    assert _rows_changed(db, OTHER_UID,
                         "UPDATE firm_pt_slabs SET amount_paise = 99999") == 0
    assert _psql(db, "SELECT amount_paise FROM firm_pt_slabs;",
                 tuples=True).stdout.strip() == "0"

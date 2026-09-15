"""Migration 390 — a client's GST registrations, on real PostgreSQL (GST-20).

WHY THIS NEEDS A REAL DATABASE. The design is mostly constraints: that the state
code is the GSTIN's own first two characters, that one GSTIN belongs to one
client and one client to one GSTIN, and — the structural half — that the RETURN
tables are keyed per registration, which is exactly what
`UNIQUE (client_id, period)` forbade. None of it is observable in mock mode.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CLIENT2 = "33333333-3333-3333-3333-333333333333"

MAHARASHTRA = "27AAPFU0939F1ZV"
KARNATAKA = "29AAPFU0939F1ZR"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"gstreg_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan, gstin)
            VALUES ('{CLIENT}',  '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A',
                    '{MAHARASHTRA}'),
                   ('{CLIENT2}', '{FIRM}', 'C2', 'Private Limited', 'AAACB1234B', NULL);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _reg(dsn, *, client=CLIENT, gstin=KARNATAKA, state=None,
         kind="'regular'", freq="'monthly'"):
    state_sql = f"'{state}'" if state is not None else f"left('{gstin}', 2)"
    return _psql(dsn, f"""
        INSERT INTO client_gst_registrations
               (firm_id, client_id, gstin, state_code, registration_type,
                filing_frequency)
        VALUES ('{FIRM}', '{client}', '{gstin}', {state_sql}, {kind}, {freq});
    """)


def _ret(dsn, table, *, period="062026", gstin=MAHARASHTRA, client=CLIENT):
    return _psql(dsn, f"""
        INSERT INTO {table} (firm_id, client_id, period, gstin)
        VALUES ('{FIRM}', '{client}', '{period}', '{gstin}');
    """)


# ── the registration row ────────────────────────────────────────────────────

def test_an_additional_registration_is_accepted(db):
    assert _reg(db).returncode == 0


def test_the_state_code_must_be_the_gstins_own(db):
    """A registration is state-wise (CGST Act s.25(1)), so a state code that
    disagrees with the number means one of the two is wrong — and guessing
    which puts every supply under it in the wrong state."""
    assert _reg(db, state="27").returncode != 0


def test_a_malformed_gstin_is_refused_by_the_column(db):
    """The SHAPE only — the check digit is not testable in SQL and is the API's
    door. Both are needed: this catches a direct write, that catches a human."""
    assert _reg(db, gstin="29AAPFU0939F1Z").returncode != 0
    assert _reg(db, gstin="AAPFU0939F1ZR9").returncode != 0


def test_one_registration_per_gstin_per_client(db):
    assert _reg(db).returncode == 0
    assert _reg(db).returncode != 0


def test_a_gstin_cannot_belong_to_TWO_clients_of_one_firm(db):
    """A GSTIN identifies one taxable person. Caught in the database because
    the app would have to scan every client to notice."""
    assert _reg(db).returncode == 0
    assert _reg(db, client=CLIENT2).returncode != 0


def test_a_withdrawn_registration_frees_its_gstin(db):
    assert _reg(db).returncode == 0
    assert _psql(db, "UPDATE client_gst_registrations SET deleted_at = now();").returncode == 0
    assert _reg(db).returncode == 0


def test_the_kind_check_accepts_exactly_the_modules_vocabulary(db):
    """Compared against the ENGINE's own tuple, never a list spelled here: a
    guard naming nine strings passes a WIDENED constraint."""
    from domain.gst import registrations as reg
    defn = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.client_gst_registrations'::regclass
           AND contype = 'c'
           AND pg_get_constraintdef(oid) LIKE '%registration_type%';
    """)
    assert defn
    assert set(re.findall(r"'([a-z_]+)'", defn[0])) == set(reg.REGISTRATION_TYPES)


def test_the_dates_run_forward(db):
    assert _psql(db, f"""
        INSERT INTO client_gst_registrations
               (firm_id, client_id, gstin, state_code, effective_from, effective_to)
        VALUES ('{FIRM}', '{CLIENT}', '{KARNATAKA}', '29',
                DATE '2026-06-01', DATE '2026-05-01');
    """).returncode != 0


# ── THE STRUCTURAL HALF: a return per registration ──────────────────────────

def test_two_registrations_can_hold_the_same_periods_return(db):
    """The whole finding. `UNIQUE (client_id, period)` made this impossible
    whatever the code did."""
    for table in ("gstr1_returns", "gstr3b_returns"):
        assert _ret(db, table, gstin=MAHARASHTRA).returncode == 0, table
        assert _ret(db, table, gstin=KARNATAKA).returncode == 0, table


def test_one_registration_still_files_one_return_a_period(db):
    """Narrowed, not removed: there is one GSTR-1 per registration for a month,
    and a second save is a REVISION of that draft."""
    for table in ("gstr1_returns", "gstr3b_returns"):
        assert _ret(db, table).returncode == 0, table
        assert _ret(db, table).returncode != 0, table


def test_the_old_constraint_is_gone(db):
    for table in ("gstr1_returns", "gstr3b_returns"):
        got = _rows(db, f"""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'public.{table}'::regclass AND contype = 'u';
        """)
        assert f"{table}_client_id_period_key" not in got, (
            f"{table} still carries the (client_id, period) unique key, so a "
            "client with two registrations cannot hold both returns")



def test_the_narrowed_key_HAS_NO_NULL_ESCAPE_HATCH(db):
    """The precondition that makes narrowing the key safe, asserted as the RULE
    rather than as the column property it happens to rest on.

    Postgres treats NULLs as DISTINCT in a unique index, so `(client_id, period,
    gstin)` enforces NOTHING on a row that leaves the GSTIN blank — and
    `gstr3b_returns.gstin` IS nullable (036 omitted it; 234 added it as a bare
    TEXT). Narrowing the key would therefore have REMOVED the protection
    `UNIQUE (client_id, period)` gave such rows rather than refining it. That is
    why the indexes key on `coalesce(gstin, '')`.

    Written as "two returns with no registration recorded, one client, one
    period, must be refused" so it holds whichever way a later migration closes
    it — a NOT NULL on the column would satisfy it too.
    """
    for table in ("gstr1_returns", "gstr3b_returns"):
        first = _psql(db, f"""
            INSERT INTO {table} (firm_id, client_id, period, gstin)
            VALUES ('{FIRM}', '{CLIENT}', '072026', NULL);
        """)
        if first.returncode != 0:
            # The column refuses it outright, which is the same rule enforced
            # one layer earlier.
            assert "null value" in first.stderr.lower(), first.stderr
            continue
        second = _psql(db, f"""
            INSERT INTO {table} (firm_id, client_id, period, gstin)
            VALUES ('{FIRM}', '{CLIENT}', '072026', NULL);
        """)
        assert second.returncode != 0, (
            f"{table} took TWO returns for one client and one period with no "
            "GSTIN recorded — the narrowed key has a NULL escape hatch, and "
            "that is weaker than the constraint it replaced")


# ── access ──────────────────────────────────────────────────────────────────

def test_the_browser_may_read_and_never_write(db):
    grants = _rows(db, """
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_name = 'client_gst_registrations' AND grantee = 'authenticated'
         ORDER BY privilege_type;
    """)
    assert grants == ["SELECT"], (
        "every write must go through the API so rbac(), the check digit and "
        "the duplicate test all run")


def test_the_table_is_assignment_scoped(db):
    assert "client_gst_registrations_assignment_scope" in _rows(db, """
        SELECT policyname FROM pg_policies
         WHERE tablename = 'client_gst_registrations' AND permissive = 'RESTRICTIVE';
    """)


def test_row_level_security_is_on(db):
    assert _rows(db, """
        SELECT relrowsecurity FROM pg_class
         WHERE relname = 'client_gst_registrations';
    """) == ["t"]

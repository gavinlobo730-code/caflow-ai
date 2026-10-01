"""Migration 460 — the post-dated cheque register, on real PostgreSQL (accounting-21).

WHY THIS NEEDS A REAL DATABASE. The design is constraints: that a received
cheque is a CUSTOMER's and an issued one a VENDOR's and the other three
combinations are unrepresentable; that the amount is positive; that the same
cheque number twice for the same party is refused while a CANCELLED row frees
it; that the table has NO journal column, because a PDC is a memorandum and
posts nothing; and that the guards every `client_id` table carries are there.
None of it is observable in mock mode.

Runs only with HARNESS_PG set and psql on PATH, like every other `*_pg.py` test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

MIGRATION = "460_a_post_dated_cheque_is_a_memo_until_it_is_presented.sql"
FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CUSTOMER = "44444444-4444-4444-4444-444444444444"
CUSTOMER_B = "44444444-4444-4444-4444-444444444445"
VENDOR = "77777777-7777-7777-7777-777777777777"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


@pytest.fixture()
def db(pg_template):
    assert MIGRATION not in pg_template.failed, (
        f"{MIGRATION} did not apply cleanly to a fresh database")
    admin = _ADMIN.strip()
    name = f"pdc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO customers (id, firm_id, client_id, name)
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Dealer Co'),
                   ('{CUSTOMER_B}', '{FIRM}', '{CLIENT}', 'Retail Co');
            INSERT INTO vendors (id, firm_id, client_id, name)
            VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Supplier');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _pdc(dsn, *, direction="received", customer=CUSTOMER, vendor=None, no="000123",
         amount=5_000_000, date="2026-11-15", status="held", allocations="'[]'"):
    cust = f"'{customer}'" if customer else "NULL"
    vend = f"'{vendor}'" if vendor else "NULL"
    return _psql(dsn, f"""
        INSERT INTO post_dated_cheques
               (firm_id, client_id, direction, customer_id, vendor_id, cheque_no,
                cheque_date, amount_paise, status, allocations)
        VALUES ('{FIRM}', '{CLIENT}', '{direction}', {cust}, {vend}, '{no}',
                DATE '{date}', {amount}, '{status}', {allocations}::jsonb);
    """)


# ── a memorandum posts nothing ───────────────────────────────────────────────

def test_the_table_has_no_journal_column_because_a_cheque_posts_nothing(db):
    cols = set(_rows(db, "SELECT column_name FROM information_schema.columns "
                         "WHERE table_name = 'post_dated_cheques';"))
    assert "journal_entry_id" not in cols
    assert not {c for c in cols if "journal" in c}
    # What it DOES carry is which ordinary document it became.
    assert {"converted_receipt_id", "converted_payment_id"} <= cols


def test_recording_a_cheque_adds_no_ledger_row(db):
    before = _rows(db, "SELECT (SELECT count(*) FROM journal_entries) || ',' || "
                       "(SELECT count(*) FROM journal_lines);")
    assert _pdc(db).returncode == 0
    assert _rows(db, "SELECT (SELECT count(*) FROM journal_entries) || ',' || "
                     "(SELECT count(*) FROM journal_lines);") == before


# ── the party matches the direction ──────────────────────────────────────────

def test_a_received_cheque_names_a_customer_and_an_issued_one_a_vendor(db):
    assert _pdc(db).returncode == 0
    assert _pdc(db, direction="issued", customer=None, vendor=VENDOR, no="000200").returncode == 0


@pytest.mark.parametrize("kwargs", [
    dict(direction="received", customer=None, vendor=VENDOR),       # wrong party
    dict(direction="issued", customer=CUSTOMER, vendor=None),       # wrong party
    dict(direction="received", customer=CUSTOMER, vendor=VENDOR),   # both
    dict(direction="received", customer=None, vendor=None),         # neither
])
def test_the_other_party_combinations_are_unrepresentable(db, kwargs):
    assert _pdc(db, **kwargs).returncode != 0


def test_an_unknown_direction_or_status_is_refused(db):
    assert _pdc(db, direction="exchanged").returncode != 0
    assert _pdc(db, status="presented").returncode != 0


# ── the figures ──────────────────────────────────────────────────────────────

def test_the_amount_must_be_positive(db):
    assert _pdc(db, amount=0).returncode != 0
    assert _pdc(db, amount=-100).returncode != 0


def test_a_blank_cheque_number_is_refused(db):
    assert _pdc(db, no="   ").returncode != 0


def test_allocations_must_be_a_list(db):
    assert _pdc(db, allocations="'{}'").returncode != 0
    assert _pdc(db, allocations="'[{\"sales_invoice_id\": \"x\", \"allocated_paise\": 1}]'").returncode == 0


# ── one cheque once ──────────────────────────────────────────────────────────

def test_the_same_cheque_number_twice_for_one_party_is_refused(db):
    assert _pdc(db).returncode == 0
    assert _pdc(db, no=" 000123 ").returncode != 0, "spacing does not make it a second cheque"


def test_the_same_number_for_a_different_party_is_a_different_cheque(db):
    assert _pdc(db).returncode == 0
    assert _pdc(db, customer=CUSTOMER_B).returncode == 0


def test_the_same_number_received_and_issued_are_different_cheques(db):
    assert _pdc(db).returncode == 0
    assert _pdc(db, direction="issued", customer=None, vendor=VENDOR).returncode == 0


def test_a_cancelled_cheque_frees_its_number(db):
    assert _pdc(db).returncode == 0
    assert _psql(db, "UPDATE post_dated_cheques SET status = 'cancelled';").returncode == 0
    assert _pdc(db).returncode == 0


# ── the guards every client_id table carries ─────────────────────────────────

def test_the_table_has_rls_the_firm_policy_and_the_restrictive_assignment_scope(db):
    assert _rows(db, "SELECT relrowsecurity FROM pg_class "
                     "WHERE relname = 'post_dated_cheques';") == ["t"]
    policies = set(_rows(db, """
        SELECT policyname || ':' || permissive FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'post_dated_cheques';"""))
    assert "firm_isolation:PERMISSIVE" in policies
    assert "post_dated_cheques_assignment_scope:RESTRICTIVE" in policies


def test_the_signed_in_role_reads_and_only_the_service_role_writes(db):
    grants = {tuple(r.split("|")) for r in _rows(db, """
        SELECT grantee || '|' || privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = 'post_dated_cheques'
           AND grantee IN ('authenticated', 'service_role');""")}
    assert ("authenticated", "SELECT") in grants
    assert not {g for g in grants if g[0] == "authenticated" and g[1] != "SELECT"}
    assert {("service_role", p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")} <= grants

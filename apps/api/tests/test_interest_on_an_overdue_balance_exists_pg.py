"""Migration 461 — interest on an overdue customer balance, on real PostgreSQL
(accounting-22).

WHY THIS NEEDS A REAL DATABASE. The design is constraints: that the RATE is
nullable with no default and NULL is not 0 (a client that does not charge
interest has not stated a rate, and a stated 0 is "waived"); that a unit slip
(1800 typed as 18000) is refused at 100% a year; that grace and basis are
bounded; that a charge's period is ordered and its days positive; that the same
overdue invoice cannot be claimed twice up to the same date (the backstop for
two clicks in one instant); that a deleted draft nulls its pointer rather than
the charge row vanishing; and that the new table carries the firm policy and the
RESTRICTIVE assignment scope. None of it is observable in mock mode.

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

MIGRATION = "461_interest_on_an_overdue_customer_balance.sql"
FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CUSTOMER = "44444444-4444-4444-4444-444444444444"
OVERDUE = "88888888-8888-8888-8888-888888888881"
DRAFT = "88888888-8888-8888-8888-888888888882"


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
    name = f"li_{uuid.uuid4().hex[:12]}"
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
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Dealer Co');
            INSERT INTO client_sales_invoices
                   (id, firm_id, client_id, customer_id, invoice_no, invoice_date,
                    due_date, total_paise, status)
            VALUES ('{OVERDUE}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV/1',
                    DATE '2026-07-01', DATE '2026-08-22', 10000000, 'issued'),
                   ('{DRAFT}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'DRAFT-1',
                    DATE '2026-10-01', NULL, 157808, 'draft');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _terms(dsn, rate="NULL", grace="0", basis="'due_date'"):
    return _psql(dsn, f"""
        UPDATE customers SET late_interest_rate_bps = {rate},
               late_interest_grace_days = {grace}, late_interest_from = {basis}
         WHERE id = '{CUSTOMER}';""")


def _charge(dsn, *, invoice=OVERDUE, draft=DRAFT, p_from="2026-08-22", p_to="2026-10-01",
            days=40, out=10000000, interest=197260, rate=1800):
    d = f"'{draft}'" if draft else "NULL"
    return _psql(dsn, f"""
        INSERT INTO late_interest_charges
               (firm_id, client_id, customer_id, sales_invoice_id, interest_invoice_id,
                period_from, period_to, days, outstanding_paise, rate_bps, interest_paise)
        VALUES ('{FIRM}', '{CLIENT}', '{CUSTOMER}', '{invoice}', {d},
                DATE '{p_from}', DATE '{p_to}', {days}, {out}, {rate}, {interest});
    """)


# ── the terms ────────────────────────────────────────────────────────────────

def test_a_customer_states_no_rate_until_somebody_does_and_null_is_not_zero(db):
    assert _rows(db, f"SELECT late_interest_rate_bps IS NULL FROM customers "
                     f"WHERE id = '{CUSTOMER}';") == ["t"]
    assert _rows(db, "SELECT is_nullable FROM information_schema.columns WHERE "
                     "table_name = 'customers' AND column_name = 'late_interest_rate_bps';") == ["YES"]
    assert _rows(db, "SELECT column_default IS NULL FROM information_schema.columns WHERE "
                     "table_name = 'customers' AND column_name = 'late_interest_rate_bps';") == ["t"]
    # A stated zero ("waived") is a different fact and is accepted.
    assert _terms(db, rate="0").returncode == 0
    assert _rows(db, f"SELECT late_interest_rate_bps FROM customers WHERE id = '{CUSTOMER}';") == ["0"]


def test_grace_and_basis_default_to_nothing_and_the_due_date(db):
    assert _rows(db, f"SELECT late_interest_grace_days || '|' || late_interest_from "
                     f"FROM customers WHERE id = '{CUSTOMER}';") == ["0|due_date"]


@pytest.mark.parametrize("rate,ok", [("0", True), ("1800", True), ("10000", True),
                                     ("10001", False), ("-1", False), ("NULL", True)])
def test_a_rate_over_a_hundred_percent_a_year_is_a_unit_slip_and_is_refused(db, rate, ok):
    assert (_terms(db, rate=rate).returncode == 0) is ok


@pytest.mark.parametrize("grace,ok", [("0", True), ("365", True), ("366", False), ("-1", False)])
def test_grace_is_bounded(db, grace, ok):
    assert (_terms(db, rate="1800", grace=grace).returncode == 0) is ok


def test_the_basis_is_one_of_the_two(db):
    assert _terms(db, rate="1800", basis="'invoice_date'").returncode == 0
    assert _terms(db, rate="1800", basis="'payment_date'").returncode != 0


# ── the charges ──────────────────────────────────────────────────────────────

def test_a_charge_is_accepted(db):
    assert _charge(db).returncode == 0


def test_a_period_is_ordered_and_has_days(db):
    assert _charge(db, p_from="2026-10-01", p_to="2026-10-01", days=1).returncode != 0
    assert _charge(db, p_from="2026-10-05", p_to="2026-10-01").returncode != 0
    assert _charge(db, days=0).returncode != 0


def test_no_figure_can_be_negative(db):
    assert _charge(db, interest=-1).returncode != 0
    assert _charge(db, out=-1).returncode != 0


def test_the_same_invoice_cannot_be_claimed_twice_up_to_the_same_date(db):
    """The backstop for two clicks on 'Prepare draft' in the same instant."""
    assert _charge(db).returncode == 0
    assert _charge(db).returncode != 0


def test_a_later_period_for_the_same_invoice_is_a_second_claim(db):
    assert _charge(db).returncode == 0
    assert _charge(db, p_from="2026-10-01", p_to="2026-10-11", days=10,
                   interest=49315).returncode == 0


def test_deleting_the_draft_nulls_the_pointer_and_keeps_the_charge_row(db):
    """A charge STANDS only while its draft does — derived at read time — so a
    hard-deleted draft must leave the row (with no draft) rather than erase it
    or be blocked by it."""
    assert _charge(db).returncode == 0
    assert _psql(db, f"DELETE FROM client_sales_invoices WHERE id = '{DRAFT}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM late_interest_charges;") == ["1"]
    assert _rows(db, "SELECT interest_invoice_id IS NULL FROM late_interest_charges;") == ["t"]


def test_the_charge_goes_with_the_invoice_it_was_computed_on(db):
    assert _charge(db).returncode == 0
    assert _psql(db, f"DELETE FROM client_sales_invoices WHERE id = '{OVERDUE}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM late_interest_charges;") == ["0"]


# ── the guards every client_id table carries ─────────────────────────────────

def test_the_table_has_rls_the_firm_policy_and_the_restrictive_assignment_scope(db):
    assert _rows(db, "SELECT relrowsecurity FROM pg_class "
                     "WHERE relname = 'late_interest_charges';") == ["t"]
    policies = set(_rows(db, """
        SELECT policyname || ':' || permissive FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'late_interest_charges';"""))
    assert "firm_isolation:PERMISSIVE" in policies
    assert "late_interest_charges_assignment_scope:RESTRICTIVE" in policies


def test_the_signed_in_role_reads_and_only_the_service_role_writes(db):
    grants = {tuple(r.split("|")) for r in _rows(db, """
        SELECT grantee || '|' || privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = 'late_interest_charges'
           AND grantee IN ('authenticated', 'service_role');""")}
    assert ("authenticated", "SELECT") in grants
    assert not {g for g in grants if g[0] == "authenticated" and g[1] != "SELECT"}
    assert {("service_role", p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")} <= grants

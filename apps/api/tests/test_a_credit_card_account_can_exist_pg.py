"""Migration 386 — a credit card is a bank account, on real PostgreSQL
(BANK-21).

WHY THIS NEEDS A REAL DATABASE. The whole of migration 386 is a CHECK
constraint, and a CHECK is the one kind of rule the in-memory double cannot
express: every mock-mode test would pass on a database that still refuses the
value. The rollback's own refusal — it will not narrow the constraint under
existing card rows — is a plpgsql block, which is the same.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")
_MIG = Path(__file__).resolve().parent.parent / "migrations"

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"


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
    name = f"card_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _account(dsn: str, account_type: str, no: str = "4321") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO bank_accounts (firm_id, client_id, bank_name, account_no, account_type)
        VALUES ('{FIRM}', '{CLIENT}', 'HDFC', '{no}', '{account_type}');
    """)


@pytest.mark.parametrize("account_type", ["Current", "Savings", "Cash Credit",
                                          "Overdraft", "Credit Card"])
def test_every_kind_the_engine_knows_can_be_created(db, account_type):
    r = _account(db, account_type)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("account_type", ["Card", "credit card", "Loan", ""])
def test_a_kind_the_engine_does_not_know_is_refused(db, account_type):
    assert _account(db, account_type).returncode != 0


def test_the_check_accepts_exactly_the_engines_vocabulary(db):
    """THE RULE, NOT FIVE SPELLINGS OF IT. Naming a handful of good and bad
    values catches a CHECK that was dropped and misses one that was WIDENED,
    and a widened CHECK lets a value through that decides which LEDGER the
    account gets — asset or liability."""
    from domain.banking import account_kind as ak
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.bank_accounts'::regclass
           AND conname = 'bank_accounts_account_type_check';
    """)
    assert definition, "the CHECK is gone"
    accepted = set(re.findall(r"'([^']*)'", definition[0]))
    assert accepted == set(ak.ACCOUNT_TYPES), accepted


def test_a_cards_opening_balance_is_stored_negative(db):
    """The store holds LEDGER sign — positive is a debit balance — so a card's
    is a credit balance. The column is BIGINT and takes it; a NOT NULL CHECK
    forbidding a negative would have made the whole design impossible."""
    r = _psql(db, f"""
        INSERT INTO bank_accounts (firm_id, client_id, bank_name, account_no,
                                   account_type, opening_balance_paise, opening_balance_date)
        VALUES ('{FIRM}', '{CLIENT}', 'HDFC', '9999', 'Credit Card', -5000000, DATE '2026-04-01');
    """)
    assert r.returncode == 0, r.stderr
    assert _rows(db, "SELECT opening_balance_paise FROM bank_accounts "
                     "WHERE account_no = '9999';") == ["-5000000"]


def test_the_column_comment_says_which_sign_is_stored(db):
    got = _rows(db, """
        SELECT col_description('public.bank_accounts'::regclass, ordinal_position)
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='bank_accounts'
           AND column_name='account_type';
    """)
    assert got and "LEDGER sign" in got[0], got


def test_the_rollback_refuses_while_a_card_account_exists(db):
    """Narrowing the CHECK under existing rows would leave rows the constraint
    forbids, and deleting them would take a statement, its coding and its
    reconciliation with it."""
    assert _account(db, "Credit Card").returncode == 0
    rollback = (_MIG / "386_a_credit_card_is_a_bank_account_that_is_a_liability_rollback.sql"
                ).read_text(encoding="utf-8")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=rollback, capture_output=True, text=True)
    assert r.returncode != 0
    assert "credit-card bank account" in r.stderr
    # And it changed nothing.
    assert _rows(db, "SELECT count(*) FROM bank_accounts "
                     "WHERE account_type = 'Credit Card';") == ["1"]


def test_the_rollback_narrows_the_check_when_no_card_exists(db):
    rollback = (_MIG / "386_a_credit_card_is_a_bank_account_that_is_a_liability_rollback.sql"
                ).read_text(encoding="utf-8")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=rollback, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _account(db, "Credit Card").returncode != 0
    assert _account(db, "Current", no="1234").returncode == 0

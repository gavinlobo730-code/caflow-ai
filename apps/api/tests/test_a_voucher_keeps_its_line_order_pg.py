"""Migration 384 — a voucher's lines carry the order they were written, on real
PostgreSQL (ACC-16).

WHY THIS NEEDS A REAL DATABASE. The whole mechanism is `WITH ORDINALITY`: the
order comes out of the jsonb array's own position, so not one posting function
has to remember to send an index. There is no way to observe that in mock mode
— the in-memory doubles have no `rpc` and take the Python fallback — and it is
also the half that CREATE OR REPLACE can silently break, because a function
that compiles is a function that deploys.

Two functions insert lines and BOTH are replaced: `post_journal_atomic` on the
way in, and `edit_posted_journal`, which DELETEs every line and re-inserts the
array it was given. Missing the second would have lost the CA's order the first
time they corrected the voucher, silently — the derived read-time rule still
gives a stable answer, just the conventional one rather than theirs.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
EXPENSE = "33333333-3333-3333-3333-333333333333"
CGST = "44444444-4444-4444-4444-444444444444"
SGST = "55555555-5555-5555-5555-555555555555"
BANK = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


def _q(obj) -> str:
    """A jsonb literal for psql — single quotes doubled, nothing interpolated
    by hand."""
    return "'" + json.dumps(obj).replace("'", "''") + "'::jsonb"


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"lineorder_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited');
            INSERT INTO chart_of_accounts
                (id, firm_id, client_id, account_code, account_name, account_type, is_active)
            VALUES ('{EXPENSE}', '{FIRM}', '{CLIENT}', '5100', 'Bank Charges', 'Expense', true),
                   ('{CGST}',    '{FIRM}', '{CLIENT}', '1410', 'CGST Input',   'Asset',   true),
                   ('{SGST}',    '{FIRM}', '{CLIENT}', '1411', 'SGST Input',   'Asset',   true),
                   ('{BANK}',    '{FIRM}', '{CLIENT}', '1200', 'Bank',         'Asset',   true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _entry(ref: str) -> dict:
    return {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-06-15",
            "reference_no": ref, "narration": "Bank charges", "entry_type": "Journal",
            "is_posted": True, "source_type": "manual"}


# The order a CA writes a bank charge in — the expense, then each tax head,
# then the money out. None of it is recoverable from the amounts.
_CHARGE = [
    {"account_id": EXPENSE, "debit_paise": 50000, "credit_paise": 0, "narration": "Charge"},
    {"account_id": CGST, "debit_paise": 4500, "credit_paise": 0, "narration": "CGST"},
    {"account_id": SGST, "debit_paise": 4500, "credit_paise": 0, "narration": "SGST"},
    {"account_id": BANK, "debit_paise": 0, "credit_paise": 59000, "narration": "Bank"},
]


def _order(dsn: str, entry_id: str) -> list[tuple[int, str]]:
    return [tuple(r.split("|")) for r in _rows(
        dsn, f"SELECT line_order, narration FROM journal_lines "
             f"WHERE journal_entry_id = '{entry_id}' ORDER BY line_order;")]


def _post(dsn: str, ref: str, lines: list[dict]) -> str:
    return _rows(dsn, f"SELECT post_journal_atomic({_q(_entry(ref))}, {_q(lines)});")[0]


def test_the_column_exists_and_is_nullable(db):
    got = _rows(db, """
        SELECT is_nullable, column_default, data_type FROM information_schema.columns
         WHERE table_schema='public' AND table_name='journal_lines' AND column_name='line_order';
    """)
    assert got == ["YES||integer"], got


def test_posting_records_the_array_position_of_every_line(db):
    entry = _post(db, "MJ-ORD-1", _CHARGE)
    assert _order(db, entry) == [("0", "Charge"), ("1", "CGST"), ("2", "SGST"), ("3", "Bank")]


def test_the_order_survives_a_shape_the_amounts_cannot_recover(db):
    """The CREDIT written first. Nothing about the amounts says so, which is
    exactly why the column has to exist — the derived rule would put the debits
    first and be wrong about this voucher."""
    lines = [_CHARGE[3], _CHARGE[0], _CHARGE[1], _CHARGE[2]]
    entry = _post(db, "MJ-ORD-2", lines)
    assert _order(db, entry) == [("0", "Bank"), ("1", "Charge"), ("2", "CGST"), ("3", "SGST")]


def test_a_caller_that_sends_its_own_line_order_wins(db):
    lines = [dict(l, line_order=3 - i) for i, l in enumerate(_CHARGE)]
    entry = _post(db, "MJ-ORD-3", lines)
    assert _order(db, entry) == [("0", "Bank"), ("1", "SGST"), ("2", "CGST"), ("3", "Charge")]


def test_the_posting_kernel_still_refuses_an_unbalanced_entry(db):
    """CREATE OR REPLACE overwrites whatever is there, so the guards that were
    already in the function are asserted after the replacement, not before."""
    bad = [dict(_CHARGE[0]), dict(_CHARGE[3], credit_paise=1)]
    r = _psql(db, f"SELECT post_journal_atomic({_q(_entry('MJ-BAD'))}, {_q(bad)});")
    assert r.returncode != 0
    assert "imbalance" in r.stderr.lower()


def test_the_posting_kernel_still_refuses_a_zero_value_entry(db):
    zero = [dict(_CHARGE[0], debit_paise=0), dict(_CHARGE[3], credit_paise=0)]
    r = _psql(db, f"SELECT post_journal_atomic({_q(_entry('MJ-ZERO'))}, {_q(zero)});")
    assert r.returncode != 0
    assert "zero-value" in r.stderr.lower()


def test_a_retry_on_the_same_reference_still_returns_the_first_entry(db):
    """The unique_violation branch — the one piece of the function that a
    careless rewrite drops and that only shows up under concurrency."""
    first = _post(db, "MJ-DUP", _CHARGE)
    again = _post(db, "MJ-DUP", _CHARGE)
    assert first == again
    assert _rows(db, f"SELECT count(*) FROM journal_lines "
                     f"WHERE journal_entry_id = '{first}';") == ["4"]


def test_correcting_a_posted_voucher_renumbers_it_from_the_array_saved(db):
    """`edit_posted_journal` replaces rather than reconciles. Before 384 the
    replacement lines came back with line_order NULL, so the CA's order was
    lost the first time they corrected the entry."""
    entry = _post(db, "MJ-EDIT", _CHARGE)
    edited = [
        {"account_id": BANK, "debit_paise": 0, "credit_paise": 59000, "narration": "Bank"},
        {"account_id": EXPENSE, "debit_paise": 59000, "credit_paise": 0, "narration": "Charge only"},
    ]
    r = _psql(db, f"""
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{entry}'::uuid, {_q(edited)},
            NULL, NULL, NULL, NULL);
    """)
    assert r.returncode == 0, r.stderr
    assert _order(db, entry) == [("0", "Bank"), ("1", "Charge only")]


def test_the_edit_path_still_refuses_an_auto_posted_entry(db):
    """ACC-04's gate, asserted after the replacement for the same reason."""
    entry = _rows(db, f"SELECT post_journal_atomic("
                      f"{_q(dict(_entry('MJ-AUTO'), source_type='sales_invoice'))}, "
                      f"{_q(_CHARGE)});")[0]
    r = _psql(db, f"""
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{entry}'::uuid, {_q(_CHARGE)},
            NULL, NULL, NULL, NULL);
    """)
    assert r.returncode != 0
    assert "posted automatically" in r.stderr.lower()


def test_the_edit_path_still_refuses_an_unbalanced_correction(db):
    entry = _post(db, "MJ-EDIT-BAD", _CHARGE)
    bad = [dict(_CHARGE[0]), dict(_CHARGE[3], credit_paise=1)]
    r = _psql(db, f"""
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{entry}'::uuid, {_q(bad)},
            NULL, NULL, NULL, NULL);
    """)
    assert r.returncode != 0
    assert "unbalanced" in r.stderr.lower()


def test_a_line_written_before_384_stays_null_rather_than_being_backfilled(db):
    """Migration 251 makes a posted line immutable, so a backfill for a DISPLAY
    order would mean disabling that trigger against production. The read-time
    rule in domain/accounting/line_order.py orders these instead."""
    entry = str(uuid.uuid4())
    r = _psql(db, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration,
                                     entry_type, is_posted, source_type)
        VALUES ('{entry}', '{FIRM}', '{CLIENT}', DATE '2025-04-10', 'old', 'Journal',
                true, 'manual');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        VALUES ('{entry}', '{EXPENSE}', 100000, 0), ('{entry}', '{BANK}', 0, 100000);
    """)
    assert r.returncode == 0, r.stderr
    assert _rows(db, f"SELECT count(*) FROM journal_lines "
                     f"WHERE journal_entry_id = '{entry}' AND line_order IS NULL;") == ["2"]

"""Migration 405's data repair, proved against real PostgreSQL.

WHAT IS BEING PROVED
    The repair reruns against production ONCE, with no review step in front of
    it (CLAUDE.md, "Migrations"), and it rewrites a counter that decides what a
    customer is told: `email_service.send_payment_reminder_to_customer` reads
    `reminder_count` and words its third and later emails as a FINAL demand. So
    the split has to be DERIVED and not guessed, and that is what these assert.

    `invoice_deliveries` is the record of every send attempt, and migration 097
    makes it immutable ("no DELETE ... immutable evidence of every send
    attempt, whether successful or not"). So the number of reminders a customer
    actually received is a COUNT over it. Everything above that count was the
    nightly sweep's, and moves to the internal columns.

THE STATEMENT UNDER TEST IS READ OUT OF THE MIGRATION, NOT RE-TYPED.
    A re-typed copy proves that the copy works. `_repair_statement()` slices the
    real file, so a later edit to the migration is what this runs -- and the
    slice asserts it found something, because a silently empty statement would
    make every case below pass by doing nothing.

THREE CASES, AND THE MIDDLE ONE IS THE JUDGEMENT
    swept-only        -> the whole count is internal, and the old timestamp is
                         unambiguously the sweep's, so it carries over.
    mixed             -> the COUNT is still exact (it is a count of deliveries),
                         but `last_reminded_at` was whichever writer ran most
                         recently and there is no way to tell them apart. So
                         `last_internal_followup_at` is left NULL for the next
                         sweep rather than guessed.
    genuinely emailed -> untouched.

NEGATIVE CONTROL
    Drop the `AND d.status = 'sent'` limb and a FAILED send counts as a
    reminder the customer received, so `test_a_failed_send_is_not_a_reminder`
    fails. Replace the derivation with `reminder_count = 0` and the mixed case
    fails, having thrown away two real sends.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (API_ROOT / "migrations"
             / "405_an_internal_follow_up_note_is_not_a_reminder_the_customer_got.sql")
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the 405 repair proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000405"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000405"
CUSTOMER = "cccccccc-0000-0000-0000-000000000405"


def _repair_statement() -> str:
    """The real WITH emailed AS (...) UPDATE ..., sliced out of the migration."""
    body = MIGRATION.read_text()
    m = re.search(r"^WITH emailed AS \(.*?;\s*$", body, re.S | re.M)
    assert m, "migration 405 no longer contains the repair this test replays"
    stmt = m.group(0)
    # Vacuity floor: a statement that lost its derivation would still "apply".
    assert "invoice_deliveries" in stmt and "count(d.id)" in stmt, stmt[:200]
    return stmt


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _row(dsn: str, invoice_no: str) -> tuple:
    r = _psql(dsn, f"""
        SELECT coalesce(reminder_count, -1),
               coalesce(last_reminded_at::text, 'NULL'),
               coalesce(internal_followup_count, -1),
               coalesce(last_internal_followup_at::text, 'NULL')
          FROM client_sales_invoices
         WHERE firm_id = '{FIRM}' AND invoice_no = '{invoice_no}';
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    line = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1]
    a, b, c, d = line.split("|")
    return int(a), b, int(c), d


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m405_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION.name not in pg_template.failed, (
            "migration 405 did not apply — everything below would pass vacuously")
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F405', 'f405@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C405', 'Private Limited', 'AAACA1234A');
            INSERT INTO customers (id, firm_id, client_id, name)
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Acme');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _invoice(dsn: str, no: str, *, count: int, last: str) -> str:
    r = _psql(dsn, f"""
        INSERT INTO client_sales_invoices
          (firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
           total_paise, status, reminder_count, last_reminded_at)
        VALUES ('{FIRM}', '{CLIENT}', '{CUSTOMER}', '{no}', '2026-05-01',
                '2026-05-31', 118000, 'issued', {count}, {last});
    """)
    assert r.returncode == 0, r.stderr
    return no


def _delivery(dsn: str, no: str, *, status: str, sent_at: str) -> None:
    r = _psql(dsn, f"""
        INSERT INTO invoice_deliveries
          (firm_id, client_id, invoice_id, sent_to, kind, status, sent_at)
        SELECT '{FIRM}', '{CLIENT}', i.id, 'a@b.in', 'reminder', '{status}', {sent_at}
          FROM client_sales_invoices i
         WHERE i.firm_id = '{FIRM}' AND i.invoice_no = '{no}';
    """)
    assert r.returncode == 0, r.stderr


def _repair(dsn: str) -> None:
    r = _psql(dsn, _repair_statement())
    assert r.returncode == 0, r.stderr


def test_a_sweep_only_invoice_moves_its_whole_count(db):
    """The production case: reminder_count = 5 against zero reminder deliveries.

    Two such rows existed on 18-09-2026, both on the firm whose
    internal_client_id is NULL and neither of them the practice's own fee
    invoice. The next genuine reminder on either would have opened as a final
    demand to a customer never contacted once.
    """
    _invoice(db, "SWEPT/1", count=5, last="'2026-09-16 04:21:06+00'")
    _repair(db)
    emailed_n, emailed_at, internal_n, internal_at = _row(db, "SWEPT/1")
    assert (emailed_n, emailed_at) == (0, "NULL"), (
        "nothing was emailed, so the customer-facing count is zero")
    assert internal_n == 5
    assert internal_at.startswith("2026-09-16"), (
        "with no send in the picture the old timestamp is unambiguously the "
        "sweep's, so it carries over rather than being discarded")


def test_a_mixed_invoice_keeps_the_sends_and_refuses_to_guess_the_rest(db):
    _invoice(db, "MIXED/1", count=5, last="'2026-09-16 04:21:06+00'")
    _delivery(db, "MIXED/1", status="sent", sent_at="'2026-08-01 10:00:00+00'")
    _delivery(db, "MIXED/1", status="sent", sent_at="'2026-08-20 10:00:00+00'")
    _repair(db)
    emailed_n, emailed_at, internal_n, internal_at = _row(db, "MIXED/1")
    assert emailed_n == 2, "two reminders reached the customer and both survive"
    assert emailed_at.startswith("2026-08-20"), "the LATEST real send"
    assert internal_n == 3, "the remaining three were the sweep's"
    assert internal_at == "NULL", (
        "last_reminded_at was whichever writer ran most recently and the two "
        "cannot be told apart, so this is left for the next sweep, not guessed")


def test_an_invoice_that_was_genuinely_emailed_is_untouched(db):
    _invoice(db, "REAL/1", count=2, last="'2026-08-20 10:00:00+00'")
    _delivery(db, "REAL/1", status="sent", sent_at="'2026-08-01 10:00:00+00'")
    _delivery(db, "REAL/1", status="sent", sent_at="'2026-08-20 10:00:00+00'")
    _repair(db)
    emailed_n, emailed_at, internal_n, internal_at = _row(db, "REAL/1")
    assert emailed_n == 2 and emailed_at.startswith("2026-08-20")
    assert (internal_n, internal_at) == (0, "NULL")


def test_a_failed_send_is_not_a_reminder(db):
    """migration 097 keeps failed attempts too, precisely so they are evidence.

    A bounced or refused send reached nobody, so it may not consume a number —
    which is the whole defect this migration repairs, in miniature.
    """
    _invoice(db, "FAILED/1", count=3, last="'2026-09-16 04:21:06+00'")
    _delivery(db, "FAILED/1", status="failed", sent_at="NULL")
    _delivery(db, "FAILED/1", status="bounced", sent_at="NULL")
    _repair(db)
    emailed_n, emailed_at, internal_n, _ = _row(db, "FAILED/1")
    assert (emailed_n, emailed_at) == (0, "NULL")
    assert internal_n == 3


def test_an_untouched_invoice_is_not_rewritten(db):
    """The repair's WHERE names only rows carrying a count or a timestamp, so a
    clean invoice is not dragged through it."""
    _invoice(db, "CLEAN/1", count=0, last="NULL")
    _repair(db)
    assert _row(db, "CLEAN/1") == (0, "NULL", 0, "NULL")


def test_the_repair_is_idempotent(db):
    """It reruns whenever the migration runner replays, and a second pass must
    not move a count it already corrected."""
    _invoice(db, "TWICE/1", count=5, last="'2026-09-16 04:21:06+00'")
    _delivery(db, "TWICE/1", status="sent", sent_at="'2026-08-01 10:00:00+00'")
    _repair(db)
    once = _row(db, "TWICE/1")
    _repair(db)
    assert _row(db, "TWICE/1") == once, (
        "a second pass recomputed the same derivation and changed nothing")
    assert once[0] == 1 and once[2] == 4

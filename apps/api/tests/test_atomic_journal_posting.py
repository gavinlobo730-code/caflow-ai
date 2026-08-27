"""
R1.6 — atomic journal posting (fixes finding F2), proven on real PostgreSQL.

migrations/152 post_journal_atomic inserts the journal header and its lines in ONE
transaction. This asserts the two guarantees the two-call PostgREST path lacked:
  * a line failure rolls the header back with it — no immutable orphan header;
  * the (firm, client, reference_no, entry_date) idempotency key dedupes to the
    winning entry instead of creating a duplicate.

migrations/243 adds a THIRD guarantee, proven below: post_journal_atomic itself
now refuses an imbalanced or zero-value journal, at the database layer, matching
the defense-in-depth settle_receipt_atomic already had (migration 235). This is
the DB-level backstop for the balance check services/phase2_journal_service.py's
_create_journal already does in Python — the guard here exists for whatever
future caller reaches this RPC WITHOUT that Python check ever running.

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other DB tests);
skips in the mock-mode CI job. The `migrations` CI job runs it against its Postgres.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="atomic-journal proof requires HARNESS_PG + psql",
)

FIRM = "f0000000-0000-0000-0000-000000000001"
CLIENT = "c0000000-0000-0000-0000-000000000001"
ACC_BANK = "a0000000-0000-0000-0000-000000000001"
ACC_SALES = "a0000000-0000-0000-0000-000000000002"

SEED = f"""
INSERT INTO firms (id,name,email) VALUES ('{FIRM}','F','f@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type)
  VALUES ('{CLIENT}','{FIRM}','C','Private Limited');
INSERT INTO chart_of_accounts (id,firm_id,client_id,account_code,account_name,account_type) VALUES
  ('{ACC_BANK}','{FIRM}',NULL,'1000','Bank','Asset'),
  ('{ACC_SALES}','{FIRM}',NULL,'4000','Sales','Revenue');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _entry(ref: str) -> str:
    return json.dumps({
        "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05",
        "reference_no": ref, "narration": "t", "entry_type": "Journal",
        "is_posted": True, "status": "posted",
    }).replace("'", "''")


def _lines(cgst_bad: bool = False) -> str:
    debit = {"account_id": ACC_BANK, "debit_paise": 100000, "credit_paise": 0}
    credit = {"account_id": ACC_SALES, "debit_paise": 0, "credit_paise": 100000}
    if cgst_bad:
        # A line with BOTH debit and credit > 0 violates the journal_lines XOR check.
        credit = {"account_id": ACC_SALES, "debit_paise": 100000, "credit_paise": 100000}
    return json.dumps([debit, credit]).replace("'", "''")


def _lines_imbalanced() -> str:
    debit = {"account_id": ACC_BANK, "debit_paise": 100000, "credit_paise": 0}
    credit = {"account_id": ACC_SALES, "debit_paise": 0, "credit_paise": 90000}
    return json.dumps([debit, credit]).replace("'", "''")


def _lines_zero() -> str:
    debit = {"account_id": ACC_BANK, "debit_paise": 0, "credit_paise": 0}
    credit = {"account_id": ACC_SALES, "debit_paise": 0, "credit_paise": 0}
    return json.dumps([debit, credit]).replace("'", "''")


def _call(dsn: str, ref: str, bad: bool = False) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SELECT post_journal_atomic('{_entry(ref)}'::jsonb, '{_lines(bad)}'::jsonb);", tuples=True)


def _call_with_lines(dsn: str, ref: str, lines_json: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SELECT post_journal_atomic('{_entry(ref)}'::jsonb, '{lines_json}'::jsonb);", tuples=True)


@pytest.fixture()
def seeded_db(pg_template):
    """A fresh database per test, CLONED from the session template.

    It used to replay the whole migration set here — 309 files, ~35 seconds —
    for each of the five tests below. That is 26% of the real-Postgres CI job
    spent rebuilding the same schema five times, and it is precisely the waste
    conftest.pg_template was introduced to end: "~40 minutes of CI spent
    rebuilding the same schema". This file was missed by that sweep because it
    is not named *_pg.py.

    Postgres copies a database at the file level, so the clone costs about a
    second. ISOLATION IS UNCHANGED: every test still gets its own brand-new
    database nothing else can see, seeded from scratch. Only how the schema got
    there changed, and a template clone is a byte copy of a freshly-migrated
    database — identical to what these tests started from before.
    """
    admin = _ADMIN.strip()
    dbname = f"r16_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn,
             f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # The RPC these tests exercise has to exist, or every assertion below
        # would pass vacuously against a database that simply cannot post.
        assert "152_atomic_journal_posting.sql" not in pg_template.failed, (
            "152_atomic_journal_posting.sql did not apply — post_journal_atomic "
            "is missing and everything below would prove nothing")
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _count(dsn: str, ref: str) -> int:
    r = _psql(dsn, f"SELECT count(*) FROM journal_entries WHERE reference_no='{ref}';", tuples=True)
    return int(r.stdout.strip())


def test_happy_path_inserts_header_and_lines(seeded_db):
    r = _call(seeded_db, "REF-OK")
    assert r.returncode == 0, r.stderr
    assert _count(seeded_db, "REF-OK") == 1
    lines = _psql(seeded_db, "SELECT count(*) FROM journal_lines;", tuples=True)
    assert int(lines.stdout.strip()) == 2


def test_bad_line_rolls_back_header_no_orphan(seeded_db):
    """The F2 guarantee: a failing line must not leave a posted orphan header."""
    r = _call(seeded_db, "REF-BAD", bad=True)
    assert r.returncode != 0, "expected the XOR-violating line to fail the call"
    assert _count(seeded_db, "REF-BAD") == 0, "header must have rolled back with the failed line"
    # And no stray lines were left either.
    assert int(_psql(seeded_db, "SELECT count(*) FROM journal_lines;", tuples=True).stdout.strip()) == 0


def test_duplicate_reference_dedupes_to_same_entry(seeded_db):
    first = _call(seeded_db, "REF-DUP")
    assert first.returncode == 0
    id1 = first.stdout.strip()
    second = _call(seeded_db, "REF-DUP")
    assert second.returncode == 0
    id2 = second.stdout.strip()
    assert id1 == id2, "duplicate idempotency key must return the same entry id"
    assert _count(seeded_db, "REF-DUP") == 1, "must not create a duplicate header"


def test_imbalanced_journal_rejected_at_db_level(seeded_db):
    """Migration 243: the DB-level backstop, independent of the Python check
    services/phase2_journal_service.py._create_journal already does — this
    proves the guard holds even for a caller that skips that Python check
    entirely and calls the RPC directly, exactly as done here."""
    r = _call_with_lines(seeded_db, "REF-IMBALANCED", _lines_imbalanced())
    assert r.returncode != 0, "expected an imbalanced journal to be rejected"
    assert "imbalance" in (r.stderr or "").lower()
    assert _count(seeded_db, "REF-IMBALANCED") == 0, "no header may be created for a rejected post"
    assert int(_psql(seeded_db, "SELECT count(*) FROM journal_lines;", tuples=True).stdout.strip()) == 0


def test_zero_value_journal_rejected_at_db_level(seeded_db):
    """Migration 243: a balanced-but-zero journal is meaningless and must never
    post, at the DB level, mirroring settle_receipt_atomic's own guard."""
    r = _call_with_lines(seeded_db, "REF-ZERO", _lines_zero())
    assert r.returncode != 0, "expected a zero-value journal to be rejected"
    assert "zero-value" in (r.stderr or "").lower()
    assert _count(seeded_db, "REF-ZERO") == 0

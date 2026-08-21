"""
Migration 274 — a reversal stamps its original, as `authenticated`.

WHAT WAS WRONG, IN PRODUCTION
    2026-08-21 12:32:27  permission denied for table journal_entries  42501
    UPDATE "public"."journal_entries" SET "is_reversed" = ...

    reverse_entry posted the reversal through post_journal_atomic (SECURITY
    DEFINER since 271, so that half worked) and then issued a SEPARATE plain
    UPDATE to stamp the original. `authenticated` has SELECT on journal_entries
    and nothing else, so the stamp failed while the reversal committed — and the
    CA was shown "0 of 1 reversed / API error 500" over a reversal that had
    posted.

WHY THIS NEEDS A REAL DATABASE
    Every part of the bug lives in Postgres and in no Python: the missing GRANT,
    the SECURITY DEFINER boundary, and prevent_posted_journal_update — which
    permits an is_reversed FALSE->TRUE flip on a posted row when NOTHING ELSE
    changes and refuses everything else. A mock cannot tell you whether the
    write is permitted; it can only tell you the code attempted it, which it
    always did.

    The `authenticated` role is the whole point. Running these as the owner
    would pass against the broken code too.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="reversal stamp proof requires HARNESS_PG + psql",
)

FIRM = "f4000000-0000-0000-0000-000000000001"
CLIENT = "c4000000-0000-0000-0000-000000000001"
AUTH = "44444444-4444-4444-4444-444444444444"
USER = "d4000000-0000-0000-0000-000000000001"
ACC_A = "a4000000-0000-0000-0000-00000000000a"
ACC_B = "a4000000-0000-0000-0000-00000000000b"
ORIG = "e4000000-0000-0000-0000-000000000001"

SEED = f"""
INSERT INTO auth.users (id) VALUES ('{AUTH}') ON CONFLICT DO NOTHING;
INSERT INTO firms (id,name,email) VALUES ('{FIRM}','F','f@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type)
  VALUES ('{CLIENT}','{FIRM}','C','Proprietorship');
INSERT INTO users (id,firm_id,full_name,email,role,auth_user_id)
  VALUES ('{USER}','{FIRM}','P','p@t.in','Partner','{AUTH}');
INSERT INTO chart_of_accounts (id,firm_id,client_id,account_code,account_name,account_type)
  VALUES ('{ACC_A}','{FIRM}','{CLIENT}','1200','Trade Receivables','Asset'),
         ('{ACC_B}','{FIRM}','{CLIENT}','4000','Sales Revenue','Revenue');
INSERT INTO journal_entries
  (id, firm_id, client_id, entry_date, reference_no, narration, entry_type,
   is_posted, status)
VALUES
  ('{ORIG}','{FIRM}','{CLIENT}','2026-08-21','JNL-001','Credit Sales','Journal',
   true,'posted');
INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
VALUES ('{ORIG}','{ACC_A}',1000000000,0), ('{ORIG}','{ACC_B}',0,1000000000);
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _reversal_payload(rev_id: str) -> tuple[str, str]:
    entry = json.dumps({
        "id": rev_id, "firm_id": FIRM, "client_id": CLIENT,
        "entry_date": "2026-08-21", "reference_no": f"REV-{rev_id[:8]}",
        "narration": "Reversal of JNL-001", "entry_type": "Journal",
        "is_posted": True, "status": "posted", "reversal_of": ORIG,
    })
    lines = json.dumps([
        {"account_id": ACC_A, "debit_paise": 0, "credit_paise": 1000000000},
        {"account_id": ACC_B, "debit_paise": 1000000000, "credit_paise": 0},
    ])
    return entry.replace("'", "''"), lines.replace("'", "''")


def _as_authenticated(sql: str) -> str:
    claims = json.dumps({"sub": AUTH, "role": "authenticated"}).replace("'", "''")
    return (f"SET LOCAL ROLE authenticated; "
            f"SELECT set_config('request.jwt.claims', '{claims}', true); {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"rev_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_original_is_stamped_when_the_reversal_posts(db):
    """The bug: this stamp was a separate UPDATE and failed with 42501."""
    rev = str(uuid.uuid4())
    entry, lines = _reversal_payload(rev)
    r = _psql(db, _as_authenticated(
        f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);"))
    assert r.returncode == 0, f"the reversal itself failed: {r.stderr}"

    got = _psql(db, f"SELECT is_reversed FROM journal_entries WHERE id='{ORIG}';",
                tuples=True)
    assert got.stdout.strip() == "t", (
        "the original was not stamped — a reversed entry that still reads "
        "is_reversed = false keeps matching the kernel's dedup fast-path, so a "
        "re-post of the same document returns the DEAD entry's id"
    )


def test_the_reversal_itself_posts(db):
    rev = str(uuid.uuid4())
    entry, lines = _reversal_payload(rev)
    _psql(db, _as_authenticated(
        f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);"))
    got = _psql(db, f"SELECT count(*) FROM journal_entries WHERE reversal_of='{ORIG}';",
                tuples=True)
    assert got.stdout.strip() == "1"


def test_the_original_is_otherwise_untouched(db):
    """The trigger permits the flip only when NOTHING ELSE changes. If this
    drifts, the write stops being permitted at all."""
    before = _psql(db, f"""
        SELECT entry_date||'|'||reference_no||'|'||narration||'|'||is_posted||'|'||status
          FROM journal_entries WHERE id='{ORIG}';""", tuples=True).stdout.strip()
    rev = str(uuid.uuid4())
    entry, lines = _reversal_payload(rev)
    _psql(db, _as_authenticated(
        f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);"))
    after = _psql(db, f"""
        SELECT entry_date||'|'||reference_no||'|'||narration||'|'||is_posted||'|'||status
          FROM journal_entries WHERE id='{ORIG}';""", tuples=True).stdout.strip()
    assert before == after


def test_stamping_an_already_reversed_original_is_a_no_op_not_an_error(db):
    """prevent_posted_journal_update RAISES on a flip FROM true. Without the
    COALESCE(is_reversed,false) = false guard in the UPDATE, a second reversal
    attempt would error inside the function rather than being refused cleanly
    upstream."""
    _psql(db, f"UPDATE journal_entries SET is_reversed = true WHERE id='{ORIG}';")
    rev = str(uuid.uuid4())
    entry, lines = _reversal_payload(rev)
    r = _psql(db, _as_authenticated(
        f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);"))
    assert r.returncode == 0, (
        f"re-stamping an already-reversed original errored: {r.stderr}")


def test_a_reversal_cannot_stamp_another_firms_entry(db):
    """SECURITY DEFINER means RLS is not running, so the UPDATE carries its own
    firm predicate. A forged reversal_of must not reach another tenant."""
    other_firm = "f4000000-0000-0000-0000-0000000000ff"
    other_entry = "e4000000-0000-0000-0000-0000000000ff"
    setup = _psql(db, f"""
        INSERT INTO firms (id,name,email) VALUES ('{other_firm}','G','g@t.in');
        INSERT INTO clients (id,firm_id,client_name,entity_type)
          VALUES ('c4000000-0000-0000-0000-0000000000ff','{other_firm}','X','Proprietorship');
        INSERT INTO journal_entries
          (id, firm_id, client_id, entry_date, reference_no, narration, entry_type,
           is_posted, status)
        VALUES ('{other_entry}','{other_firm}','c4000000-0000-0000-0000-0000000000ff',
                '2026-08-21','OTHER','Theirs','Journal',true,'posted');
    """)
    assert setup.returncode == 0, setup.stderr

    rev = str(uuid.uuid4())
    entry = json.dumps({
        "id": rev, "firm_id": FIRM, "client_id": CLIENT,
        "entry_date": "2026-08-21", "reference_no": f"REV-{rev[:8]}",
        "narration": "forged", "entry_type": "Journal",
        "is_posted": True, "status": "posted",
        "reversal_of": other_entry,          # ← another firm's entry
    }).replace("'", "''")
    lines = json.dumps([
        {"account_id": ACC_A, "debit_paise": 0, "credit_paise": 100},
        {"account_id": ACC_B, "debit_paise": 100, "credit_paise": 0},
    ]).replace("'", "''")
    _psql(db, _as_authenticated(
        f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);"))

    got = _psql(db, f"SELECT is_reversed FROM journal_entries WHERE id='{other_entry}';",
                tuples=True)
    assert got.stdout.strip() in ("f", ""), (
        "a reversal in one firm stamped another firm's journal entry"
    )


def test_the_backfill_repaired_entries_the_gap_left_behind(db):
    """Migration 274's second half. Seeded here as the bug left production:
    a reversal exists, the original is not flagged."""
    orphan = "e4000000-0000-0000-0000-0000000000aa"
    rev = "e4000000-0000-0000-0000-0000000000ab"
    r = _psql(db, f"""
        INSERT INTO journal_entries
          (id, firm_id, client_id, entry_date, reference_no, narration,
           entry_type, is_posted, status, is_reversed)
        VALUES ('{orphan}','{FIRM}','{CLIENT}','2026-08-01','OLD','x','Journal',
                true,'posted',false);
        INSERT INTO journal_entries
          (id, firm_id, client_id, entry_date, reference_no, narration,
           entry_type, is_posted, status, reversal_of)
        VALUES ('{rev}','{FIRM}','{CLIENT}','2026-08-02','REV-OLD','y','Journal',
                true,'posted','{orphan}');
    """)
    assert r.returncode == 0, r.stderr

    # The statement migration 274 runs, replayed.
    fix = _psql(db, """
        UPDATE public.journal_entries o SET is_reversed = true
         WHERE COALESCE(o.is_reversed, false) = false
           AND EXISTS (SELECT 1 FROM public.journal_entries r
                        WHERE r.reversal_of = o.id AND r.deleted_at IS NULL);
    """)
    assert fix.returncode == 0, f"the backfill is not a permitted write: {fix.stderr}"
    got = _psql(db, f"SELECT is_reversed FROM journal_entries WHERE id='{orphan}';",
                tuples=True)
    assert got.stdout.strip() == "t"

"""
Migration 275 — discard_posted_journal, against a real database.

WHAT IT IS FOR
    A CA teaching a trainee, or posting a dummy entry to see what a screen
    does, was left with a reversal to undo something that was never a
    transaction: two permanent rows netting to zero, noise in the books
    masquerading as rigour.

    Migration 266 already established the principle for EDITING — absolute
    immutability is stricter than Indian law, because the proviso to Rule 3(1)
    of the Companies (Accounts) Rules 2014 requires an edit log of each change,
    which presumes entries can change. It stopped short of deletion without
    saying why. 275 gives discarding the same gate.

WHY A REAL DATABASE
    Every limit lives in SQL: journal_period_lock_reason, the
    app.journal_edit escape that lets a posted row be written at all,
    prevent_posted_journal_update, and apb_rebuild_client. A double can prove
    the function was CALLED; only Postgres can prove what it refuses.

WHAT IS ASSERTED
    The three limits, each refusing by name; that a permitted discard actually
    leaves the books; and — the one most easily forgotten — that the reporting
    passbook is rebuilt, so the trial balance does not silently stop agreeing
    with the ledger.
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
    reason="discard gate proof requires HARNESS_PG + psql",
)

FIRM = "f5000000-0000-0000-0000-000000000001"
CLIENT = "c5000000-0000-0000-0000-000000000001"
ACTOR = "d5000000-0000-0000-0000-000000000001"
AUTH = "55555555-5555-5555-5555-555555555555"
CASH = "a5000000-0000-0000-0000-00000000000a"
SALES = "a5000000-0000-0000-0000-00000000000b"

MANUAL = "e5000000-0000-0000-0000-000000000001"
AUTOPOSTED = "e5000000-0000-0000-0000-000000000002"
DRAFT = "e5000000-0000-0000-0000-000000000003"

AMOUNT = 5000000  # ₹50,000 in paise


def _entry(eid: str, ref: str, source: str | None, posted: bool = True,
           date: str = "2026-08-21", reversal_of: str | None = None) -> str:
    """reversal_of is set on the INSERT, not by a follow-up UPDATE: the
    immutability trigger refuses to update a posted row, which is the rule this
    file exists to test around."""
    src = f"'{source}'" if source else "NULL"
    rev = f"'{reversal_of}'" if reversal_of else "NULL"
    return f"""
INSERT INTO journal_entries
  (id, firm_id, client_id, entry_date, reference_no, narration, entry_type,
   is_posted, status, source_type, reversal_of)
VALUES ('{eid}','{FIRM}','{CLIENT}','{date}','{ref}','n','Journal',
        {str(posted).lower()},'{"posted" if posted else "draft"}',{src},{rev});
INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
VALUES ('{eid}','{CASH}',{AMOUNT},0), ('{eid}','{SALES}',0,{AMOUNT});
"""


SEED = f"""
INSERT INTO auth.users (id) VALUES ('{AUTH}') ON CONFLICT DO NOTHING;
INSERT INTO firms (id,name,email) VALUES ('{FIRM}','F','f@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type)
  VALUES ('{CLIENT}','{FIRM}','C','Proprietorship');
INSERT INTO users (id,firm_id,full_name,email,role,auth_user_id)
  VALUES ('{ACTOR}','{FIRM}','P','p@t.in','Partner','{AUTH}');
INSERT INTO chart_of_accounts (id,firm_id,client_id,account_code,account_name,account_type)
  VALUES ('{CASH}','{FIRM}','{CLIENT}','1000','Cash','Asset'),
         ('{SALES}','{FIRM}','{CLIENT}','4000','Sales','Revenue');
""" + _entry(MANUAL, "JNL-001", "manual") \
    + _entry(AUTOPOSTED, "INV-001", "sales_invoice") \
    + _entry(DRAFT, "JNL-DRAFT", "manual", posted=False)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _discard(dsn: str, entry_id: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        SELECT public.discard_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{entry_id}'::uuid, '{ACTOR}'::uuid);
    """)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"disc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        # The passbook is trigger-maintained on insert; start from the truth.
        _psql(dsn, f"SELECT public.apb_rebuild_client('{FIRM}','{CLIENT}');")
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── The thing it is for ──────────────────────────────────────────────────────

def test_a_manual_entry_in_an_open_period_is_discarded(db):
    r = _discard(db, MANUAL)
    assert r.returncode == 0, f"a manual entry in an open period was refused: {r.stderr}"


def test_it_is_a_soft_delete_and_the_lines_survive(db):
    """Rule 3(1) wants an edit log. A deletion that records nothing of WHAT was
    deleted is not one."""
    _discard(db, MANUAL)
    got = _psql(db, f"""
        SELECT (SELECT count(*) FROM journal_entries WHERE id='{MANUAL}')
            || '|' || (SELECT count(*) FROM journal_entries
                        WHERE id='{MANUAL}' AND deleted_at IS NOT NULL)
            || '|' || (SELECT count(*) FROM journal_lines
                        WHERE journal_entry_id='{MANUAL}');
    """, tuples=True)
    assert got.stdout.strip() == "1|1|2", "row present, stamped, both lines intact"


def test_the_discarded_entry_leaves_the_reporting_passbook(db):
    """The limit most easily forgotten. apb_rebuild_client filters
    `is_posted AND deleted_at IS NULL`, but the passbook's own triggers are
    additive-only and never saw the discard — without the rebuild inside the
    function, account_period_balances keeps the entry's figures and the trial
    balance silently stops agreeing with the ledger."""
    before = _psql(db, f"""
        SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances
         WHERE client_id='{CLIENT}' AND account_id='{CASH}';""", tuples=True).stdout.strip()
    # Both posted entries debit CASH, so the passbook starts at 2 x AMOUNT.
    # Asserting the exact remainder after the discard is stronger than asserting
    # zero: it proves the rebuild removed the discarded entry and NOTHING else.
    assert before == str(2 * AMOUNT), f"passbook did not start from both entries: {before}"

    r = _discard(db, MANUAL)
    assert r.returncode == 0, r.stderr

    after = _psql(db, f"""
        SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances
         WHERE client_id='{CLIENT}' AND account_id='{CASH}';""", tuples=True).stdout.strip()
    assert after == str(AMOUNT), (
        f"passbook holds {after} paise, expected {AMOUNT} — the surviving "
        "auto-posted entry only. A stale figure here means the trial balance "
        "has silently stopped agreeing with the ledger."
    )


# ── Limit 1: manual only ─────────────────────────────────────────────────────

def test_an_auto_posted_entry_is_refused(db):
    """Discarding an invoice's journal leaves the invoice pointing at nothing
    and the sub-ledger disagreeing with the GL."""
    r = _discard(db, AUTOPOSTED)
    assert r.returncode != 0, "an auto-posted journal must not be discardable"
    assert "posted automatically" in r.stderr, r.stderr


def test_the_refusal_names_the_document_type(db):
    """'Correct the document itself' is only actionable if the CA is told WHICH
    document."""
    r = _discard(db, AUTOPOSTED)
    assert "sales_invoice" in r.stderr, r.stderr


# ── Limit 2: the period must be open ─────────────────────────────────────────

def test_a_locked_financial_year_refuses_the_discard(db):
    """The same gate the edit path uses — journal_period_lock_reason. Not a
    second implementation, which would drift."""
    lock = _psql(db, f"""
        UPDATE firms SET locked_financial_years = ARRAY['2026-27']
         WHERE id = '{FIRM}';""")
    assert lock.returncode == 0, lock.stderr

    r = _discard(db, MANUAL)
    assert r.returncode != 0, "a locked year must refuse the discard"
    assert "2026-27" in r.stderr or "lock" in r.stderr.lower(), r.stderr


def test_the_entry_survives_a_refused_discard(db):
    _psql(db, f"UPDATE firms SET locked_financial_years = ARRAY['2026-27'] WHERE id='{FIRM}';")
    _discard(db, MANUAL)
    got = _psql(db, f"SELECT deleted_at IS NULL FROM journal_entries WHERE id='{MANUAL}';",
                tuples=True)
    assert got.stdout.strip() == "t", "a refused discard must write nothing"


# ── Limit 3: not entangled with a reversal ───────────────────────────────────

def test_a_reversed_entry_is_refused(db):
    """Discarding it would leave the reversal pointing at nothing."""
    _psql(db, f"""
        UPDATE journal_entries SET is_reversed = true WHERE id = '{MANUAL}';""")
    r = _discard(db, MANUAL)
    assert r.returncode != 0
    assert "reversed" in r.stderr.lower(), r.stderr


def test_a_reversal_itself_is_refused(db):
    """Discarding it would leave its original flagged reversed with nothing to
    show for it."""
    rev = "e5000000-0000-0000-0000-0000000000aa"
    setup = _psql(db, _entry(rev, "REV-001", "manual", reversal_of=MANUAL))
    assert setup.returncode == 0, setup.stderr
    r = _discard(db, rev)
    assert r.returncode != 0
    assert "is a reversal" in r.stderr.lower(), r.stderr


# ── Scope ────────────────────────────────────────────────────────────────────

def test_another_firms_entry_is_not_found(db):
    other = "f5000000-0000-0000-0000-0000000000ff"
    setup = _psql(db, f"""
        INSERT INTO firms (id,name,email) VALUES ('{other}','G','g@t.in');""")
    assert setup.returncode == 0, setup.stderr
    r = _psql(db, f"""
        SELECT public.discard_posted_journal(
            '{other}'::uuid, '{CLIENT}'::uuid, '{MANUAL}'::uuid, '{ACTOR}'::uuid);""")
    assert r.returncode != 0
    assert "not found" in r.stderr.lower(), r.stderr


def test_discarding_twice_is_not_found_the_second_time(db):
    assert _discard(db, MANUAL).returncode == 0
    r = _discard(db, MANUAL)
    assert r.returncode != 0, "a discarded entry should no longer be reachable"
    assert "not found" in r.stderr.lower(), r.stderr


def test_the_anon_key_cannot_execute_it(db):
    """SECURITY DEFINER + the anon key being inlined into the browser bundle is
    the pairing migration 272 had to undo for three other functions."""
    r = _psql(db, """
        SELECT has_function_privilege('anon',
            'public.discard_posted_journal(uuid,uuid,uuid,uuid)', 'EXECUTE');""",
        tuples=True)
    assert r.stdout.strip() == "f", "anon must not be able to discard journal entries"

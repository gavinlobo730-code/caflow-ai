"""
Migration 266 — a posted journal may be corrected until the period closes, on
real PostgreSQL.

WHY THIS ONE HAS TO RUN AGAINST A REAL DATABASE
    Everything migration 266 does lives in the database: the trigger carve-out,
    the period lock, the balance check, the passbook rebuild and the drift
    assertion are all inside edit_posted_journal. A stub can prove the service
    CALLS it. Only Postgres can prove it does the right thing when it runs, and
    this is the one function in the product allowed to rewrite rows of a posted
    ledger.

    Migration 251's own history is the argument. A guard that was never applied
    went unnoticed for roughly two hundred migrations, and the gap let a data
    migration rewrite posted lines and desync the reporting passbook until 249
    repaired it by hand. The lesson there was that a guard's ABSENCE was
    invisible. The same applies to a carve-out: one that leaks, or a rebuild
    that silently does nothing, would look exactly like success.

WHAT IS PINNED
    * 251 does not regress — a direct UPDATE or DELETE on a posted entry's lines
      is still refused, and the carve-out does not leak past the function
    * the correction actually lands, and the passbook is rebuilt to match
    * a locked financial year and a filed return each refuse, with a reason
    * an unbalanced correction is refused in integer paise
    * deleting a posted entry is still impossible
    * the edit log records the LINES, not merely the header — the amounts are on
      the lines, and Rule 3(1) is about what changed
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

FIRM   = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CASH   = "33333333-3333-3333-3333-333333333333"
SALES  = "44444444-4444-4444-4444-444444444444"
RENT   = "77777777-7777-7777-7777-777777777777"
POSTED = "55555555-5555-5555-5555-555555555555"
ACTOR  = "88888888-8888-8888-8888-888888888888"

# 1,00,000.00 rupees, in paise. Integer throughout — no float ever touches a
# rupee value, here or in the function under test.
AMOUNT = 10_000_000
CORRECTED = 12_500_000


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _edit(dsn: str, lines_json: str, *, date: str = "2026-06-15",
          narration: str = "Rent, corrected", actor: str = ACTOR) -> subprocess.CompletedProcess:
    """Call the function the way the service does."""
    return _psql(dsn, f"""
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{POSTED}'::uuid,
            '{lines_json}'::jsonb, '{narration}', NULL, '{date}'::date, '{actor}'::uuid);
    """)


def _balanced(debit_account: str, credit_account: str, amount: int) -> str:
    return (f'[{{"account_id":"{debit_account}","debit_paise":{amount},"credit_paise":0,"narration":"dr"}},'
            f' {{"account_id":"{credit_account}","debit_paise":0,"credit_paise":{amount},"narration":"cr"}}]')


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r266_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres",
             f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type, is_active)
            VALUES ('{CASH}',  '{FIRM}', '{CLIENT}', '1000', 'Cash',  'Asset',   true),
                   ('{SALES}', '{FIRM}', '{CLIENT}', '4000', 'Sales', 'Revenue', true),
                   ('{RENT}',  '{FIRM}', '{CLIENT}', '5000', 'Rent',  'Expense', true);
            INSERT INTO journal_entries
                (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, source_type)
            VALUES ('{POSTED}', '{FIRM}', '{CLIENT}', '2026-06-15', 'MJ-1', 'Rent', 'Journal', true, 'manual');
            INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
            VALUES ('{POSTED}', '{RENT}', {AMOUNT}, 0),
                   ('{POSTED}', '{CASH}', 0, {AMOUNT});
        """)
        if seed.returncode != 0:
            pytest.skip(f"seed failed: {seed.stderr[:300]}")
        yield dsn
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── the migration landed at all ──────────────────────────────────────────────

def test_the_migration_applied(pg_template):
    failed = {f for f in pg_template.failed if "266" in f}
    assert not failed, f"migration 266 did not apply cleanly: {failed}"


def test_its_objects_exist(db):
    for fn in ("edit_posted_journal", "journal_period_lock_reason",
               "journal_edit_in_progress", "audit_capture_journal_line"):
        assert _scalar(db, f"SELECT to_regprocedure('public.{fn}') IS NOT NULL "
                           f"OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                           f"WHERE n.nspname='public' AND p.proname='{fn}');") == "t", fn


# ── 251 must not regress ─────────────────────────────────────────────────────

def test_a_direct_update_of_a_posted_line_is_still_refused(db):
    r = _psql(db, f"UPDATE journal_lines SET debit_paise = 1 WHERE journal_entry_id = '{POSTED}';")

    assert r.returncode != 0, "migration 251's guard regressed — posted lines are writable again"
    assert "posted journal entry" in (r.stderr or "")


def test_a_direct_delete_of_a_posted_line_is_still_refused(db):
    r = _psql(db, f"DELETE FROM journal_lines WHERE journal_entry_id = '{POSTED}';")

    assert r.returncode != 0


def test_a_posted_entry_still_cannot_be_deleted(db):
    """A correction rewrites an entry. It never makes one vanish — the edit log
    must still have something to point at."""
    r = _psql(db, f"DELETE FROM journal_entries WHERE id = '{POSTED}';")

    assert r.returncode != 0
    assert "reversal" in (r.stderr or "").lower()


def test_the_carve_out_does_not_leak_past_the_function(db):
    """The flag is transaction-local and only edit_posted_journal sets it. If it
    survived into the next statement on a pooled connection, every guard in this
    file would be decorative."""
    ok = _edit(db, _balanced(RENT, CASH, CORRECTED))
    assert ok.returncode == 0, ok.stderr

    after = _psql(db, f"UPDATE journal_lines SET debit_paise = 1 WHERE journal_entry_id = '{POSTED}';")
    assert after.returncode != 0, "the edit flag leaked — posted lines stayed writable afterwards"


# ── every guard, not just the one you found ──────────────────────────────────

def test_every_posted_guard_that_fires_on_update_honours_the_carve_out(db):
    """The bug this pins cost the whole feature once already.

    journal_entries carries guards from TWO migrations that never knew about
    each other — 055's trg_prevent_posted_journal_update and 058's
    trg_journal_immutability. 266 was written against the second and missed the
    first, so the carve-out let the edit through one trigger and the other
    rejected it a statement later. Every test below this line failed, and the
    reason was in neither the function nor the trigger anyone was reading.

    So this does not name the three guards that exist today. It finds every
    trigger function on the journal tables that refuses a write because a row
    is posted, and insists each one knows about the carve-out. A fourth guard
    added by some future migration fails here rather than in production.
    """
    guards = _scalar(db, """
        SELECT string_agg(DISTINCT p.proname, ',' ORDER BY p.proname)
          FROM pg_trigger t
          JOIN pg_proc p ON p.oid = t.tgfoid
          JOIN pg_class c ON c.oid = t.tgrelid
         WHERE NOT t.tgisinternal
           AND c.relname IN ('journal_entries', 'journal_lines')
           AND (t.tgtype & 16) <> 0                       -- fires on UPDATE
           AND pg_get_functiondef(p.oid) ILIKE '%is_posted%'
           AND pg_get_functiondef(p.oid) ILIKE '%RAISE EXCEPTION%';
    """)
    assert guards, "no posted-entry guard found at all — 251 has regressed"

    deaf = [g for g in guards.split(",")
            if "journal_edit_in_progress" not in _scalar(
                db, f"SELECT pg_get_functiondef('public.{g}'::regproc);")]
    assert not deaf, (
        f"these posted-entry guards fire on UPDATE but do not honour the edit "
        f"carve-out, so edit_posted_journal cannot work: {deaf}")


def test_the_guard_still_works_for_the_role_that_does_the_writing(db):
    """Every other test here connects as the harness superuser, which bypasses
    permission checks — so none of them can see a missing GRANT.

    The immutability triggers are NOT security definer: they execute
    journal_edit_in_progress() as whoever is doing the write. The first version
    of 266 revoked EXECUTE on that function from PUBLIC, reasoning about the
    carve-out flag as if reading it were the same as setting it. The result was
    that service_role — the backend's own role — could no longer delete a line
    off a DRAFT entry: "permission denied for function
    journal_edit_in_progress", raised by the guard that was supposed to be
    letting it through. Run as the real role, or this class of break is
    invisible.
    """
    draft = "6a6a6a6a-6a6a-6a6a-6a6a-6a6a6a6a6a6a"
    r = _psql(db, f"""
        SET ROLE service_role;
        INSERT INTO journal_entries
            (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, source_type)
        VALUES ('{draft}', '{FIRM}', '{CLIENT}', '2026-06-21', 'MJ-3', 'Draft', 'Journal', false, 'manual');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        VALUES ('{draft}', '{RENT}', {AMOUNT}, 0);
        UPDATE journal_lines SET debit_paise = {CORRECTED} WHERE journal_entry_id = '{draft}';
        DELETE FROM journal_lines WHERE journal_entry_id = '{draft}';
    """)
    assert r.returncode == 0, r.stderr

    # ...and the guard still refuses what it is there to refuse, as that role.
    blocked = _psql(db, f"SET ROLE service_role; "
                        f"UPDATE journal_lines SET debit_paise = 1 WHERE journal_entry_id = '{POSTED}';")
    assert blocked.returncode != 0, "posted lines are writable by service_role"

    ok = _psql(db, f"""
        SET ROLE service_role;
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{POSTED}'::uuid,
            '{_balanced(RENT, CASH, CORRECTED)}'::jsonb, 'Rent, corrected', NULL,
            '2026-06-15'::date, '{ACTOR}'::uuid);
    """)
    assert ok.returncode == 0, ok.stderr


def test_deleting_a_draft_entry_actually_deletes_it(db):
    """055's guard fires BEFORE UPDATE OR DELETE and ended in a bare RETURN NEW.
    NEW is NULL in a DELETE trigger, and a BEFORE DELETE row trigger returning
    NULL cancels the delete — silently, reporting success. Deleting a draft has
    therefore been a no-op since 055, hidden because the product soft-deletes.
    266 returns OLD on that path.
    """
    draft = "66666666-6666-6666-6666-666666666666"
    assert _psql(db, f"""
        INSERT INTO journal_entries
            (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, source_type)
        VALUES ('{draft}', '{FIRM}', '{CLIENT}', '2026-06-20', 'MJ-2', 'Draft', 'Journal', false, 'manual');
    """).returncode == 0

    r = _psql(db, f"DELETE FROM journal_entries WHERE id = '{draft}';")
    assert r.returncode == 0, r.stderr

    assert _scalar(db, f"SELECT count(*) FROM journal_entries WHERE id = '{draft}';") == "0", \
        "the delete reported success and the row is still there"


# ── the correction itself ────────────────────────────────────────────────────

def test_an_open_period_can_be_corrected(db):
    r = _edit(db, _balanced(RENT, CASH, CORRECTED))
    assert r.returncode == 0, r.stderr

    assert _scalar(db, f"SELECT sum(debit_paise) FROM journal_lines "
                       f"WHERE journal_entry_id = '{POSTED}';") == str(CORRECTED)
    assert _scalar(db, f"SELECT narration FROM journal_entries WHERE id = '{POSTED}';") \
        == "Rent, corrected"


def test_the_correction_can_change_which_accounts_are_used(db):
    """Not only amounts. Miscoding rent to the wrong expense account is the
    commonest correction a CA makes."""
    r = _edit(db, _balanced(SALES, CASH, AMOUNT))
    assert r.returncode == 0, r.stderr

    accounts = _scalar(db, f"SELECT string_agg(DISTINCT account_id::text, ',' ORDER BY account_id::text) "
                           f"FROM journal_lines WHERE journal_entry_id = '{POSTED}';")
    assert RENT not in accounts
    assert SALES in accounts


def test_the_reporting_passbook_is_rebuilt_to_match(db):
    """THE reason edits were forbidden. account_period_balances is maintained by
    additive-only triggers, so without an explicit rebuild the cache keeps the
    OLD figure while the ledger holds the new one — and Trial Balance, P&L and
    Balance Sheet all read the cache."""
    before = _scalar(db, f"SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances "
                         f"WHERE client_id = '{CLIENT}' AND account_id = '{RENT}';")
    assert before == str(AMOUNT), f"seed did not populate the passbook (got {before})"

    assert _edit(db, _balanced(RENT, CASH, CORRECTED)).returncode == 0

    after = _scalar(db, f"SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances "
                        f"WHERE client_id = '{CLIENT}' AND account_id = '{RENT}';")
    assert after == str(CORRECTED), (
        f"passbook still says {after}, ledger says {CORRECTED} — reports would disagree "
        f"with the ledger, silently")


def test_drift_is_asserted_not_assumed(db):
    """apb_assert_no_drift runs inside the same transaction. An unasserted
    rebuild is how 249's drift went unnoticed in the first place."""
    assert _edit(db, _balanced(RENT, CASH, CORRECTED)).returncode == 0

    assert _scalar(db, "SELECT count(*) FROM public.apb_drifted_clients();") == "0"


# ── the locks ────────────────────────────────────────────────────────────────

def test_a_locked_financial_year_refuses(db):
    """FY 2026-27 runs 1 Apr 2026 to 31 Mar 2027 (Income Tax Act §3), so the
    15 Jun 2026 entry falls inside it."""
    assert _psql(db, f"UPDATE firms SET locked_financial_years = ARRAY['2026-27'] "
                     f"WHERE id = '{FIRM}';").returncode == 0

    r = _edit(db, _balanced(RENT, CASH, CORRECTED))
    assert r.returncode != 0
    assert "2026-27 is locked" in (r.stderr or "")
    assert _scalar(db, f"SELECT sum(debit_paise) FROM journal_lines "
                       f"WHERE journal_entry_id = '{POSTED}';") == str(AMOUNT), \
        "the ledger moved despite the refusal"


def test_a_filed_return_refuses_and_says_what_to_do_instead(db):
    assert _psql(db, f"""
        INSERT INTO filings (client_id, filing_type, period_start, period_end, filed_date, status)
        VALUES ('{CLIENT}', 'GSTR-3B', '2026-06-01', '2026-06-30', '2026-07-18', 'filed');
    """).returncode == 0

    r = _edit(db, _balanced(RENT, CASH, CORRECTED))
    assert r.returncode != 0
    err = r.stderr or ""
    assert "GSTR-3B" in err and "18 Jul 2026" in err
    assert "reversal" in err, "a refusal must tell the CA what to do instead"


def test_an_unfiled_return_does_not_block(db):
    """A filing ROW exists but was never filed — a task in the calendar, not a
    document at the portal. Blocking on it would freeze books nobody has
    submitted anything for."""
    assert _psql(db, f"""
        INSERT INTO filings (client_id, filing_type, period_start, period_end, filed_date, status)
        VALUES ('{CLIENT}', 'GSTR-3B', '2026-06-01', '2026-06-30', NULL, 'draft');
    """).returncode == 0

    assert _edit(db, _balanced(RENT, CASH, CORRECTED)).returncode == 0


def test_a_filing_for_a_different_period_does_not_block(db):
    assert _psql(db, f"""
        INSERT INTO filings (client_id, filing_type, period_start, period_end, filed_date, status)
        VALUES ('{CLIENT}', 'GSTR-3B', '2026-01-01', '2026-01-31', '2026-02-18', 'filed');
    """).returncode == 0

    assert _edit(db, _balanced(RENT, CASH, CORRECTED)).returncode == 0


def test_redating_into_a_locked_year_refuses(db):
    """Moving an entry OUT of an open period INTO a closed one changes the closed
    period's numbers. Checking only the entry's current date would miss it."""
    assert _psql(db, f"UPDATE firms SET locked_financial_years = ARRAY['2025-26'] "
                     f"WHERE id = '{FIRM}';").returncode == 0

    r = _edit(db, _balanced(RENT, CASH, CORRECTED), date="2025-12-01")
    assert r.returncode != 0
    assert "2025-26 is locked" in (r.stderr or "")


# ── double entry ─────────────────────────────────────────────────────────────

def test_an_unbalanced_correction_refuses(db):
    lines = (f'[{{"account_id":"{RENT}","debit_paise":{CORRECTED},"credit_paise":0}},'
             f' {{"account_id":"{CASH}","debit_paise":0,"credit_paise":{AMOUNT}}}]')
    r = _edit(db, lines)

    assert r.returncode != 0
    assert "Unbalanced" in (r.stderr or "")
    assert _scalar(db, f"SELECT sum(debit_paise) FROM journal_lines "
                       f"WHERE journal_entry_id = '{POSTED}';") == str(AMOUNT)


def test_a_single_leg_correction_refuses(db):
    r = _edit(db, f'[{{"account_id":"{RENT}","debit_paise":0,"credit_paise":0}}]')

    assert r.returncode != 0
    assert "two lines" in (r.stderr or "")


def test_a_correction_of_an_unknown_entry_refuses(db):
    r = _psql(db, f"""
        SELECT public.edit_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '99999999-9999-9999-9999-999999999999'::uuid,
            '{_balanced(RENT, CASH, AMOUNT)}'::jsonb, NULL, NULL, NULL, '{ACTOR}'::uuid);
    """)

    assert r.returncode != 0
    assert "not found" in (r.stderr or "").lower()


def test_another_firms_entry_is_not_reachable(db):
    r = _psql(db, f"""
        SELECT public.edit_posted_journal(
            '99999999-9999-9999-9999-999999999999'::uuid, '{CLIENT}'::uuid, '{POSTED}'::uuid,
            '{_balanced(RENT, CASH, CORRECTED)}'::jsonb, NULL, NULL, NULL, '{ACTOR}'::uuid);
    """)

    assert r.returncode != 0, "a cross-firm entry id was editable"


# ── the edit log ─────────────────────────────────────────────────────────────

def test_the_edit_log_records_the_lines_not_just_the_header(db):
    """Rule 3(1) asks what CHANGED. The amounts and accounts are on the lines, so
    a log covering only the entry header records that something happened and
    nothing about what.

    journal_lines has no firm_id, which is why the generic audit_capture could
    not be used — it reads firm_id off the changed row and would have written
    nothing, forever. auth.uid() is set here because the trigger records the
    actor and skips when there is none.
    """
    # users.auth_user_id FKs to auth.users (migration 005), so the Supabase-side
    # row has to exist first — the harness bootstrap provides the minimal shape.
    seed_user = _psql(db, f"""
        INSERT INTO auth.users (id, email) VALUES ('{ACTOR}', 'ca@t.in');
        INSERT INTO users (id, firm_id, email, auth_user_id, full_name, role)
        VALUES (gen_random_uuid(), '{FIRM}', 'ca@t.in', '{ACTOR}', 'CA', 'Partner');
    """)
    assert seed_user.returncode == 0, seed_user.stderr

    before = _scalar(db, "SELECT count(*) FROM audit_log WHERE entity_type = 'journal_line';")

    r = subprocess.run(
        ["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
         f"""SET request.jwt.claims = '{{"sub":"{ACTOR}"}}';
             SELECT public.edit_posted_journal(
                 '{FIRM}'::uuid, '{CLIENT}'::uuid, '{POSTED}'::uuid,
                 '{_balanced(RENT, CASH, CORRECTED)}'::jsonb,
                 'Rent, corrected', NULL, '2026-06-15'::date, '{ACTOR}'::uuid);"""],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    after = int(_scalar(db, "SELECT count(*) FROM audit_log WHERE entity_type = 'journal_line';"))
    assert after > int(before), "the edit log recorded nothing about the lines"

    # The old figure has to be recoverable — "what did it change FROM" is the
    # question an auditor actually asks.
    assert _scalar(db, f"""
        SELECT count(*) FROM audit_log
        WHERE entity_type = 'journal_line' AND action = 'delete'
          AND (old_data->>'debit_paise')::bigint = {AMOUNT};""") != "0", \
        "the pre-edit amount is not in the log"

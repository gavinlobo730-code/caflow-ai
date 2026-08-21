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
           date: str = "2026-08-21", reversal_of: str | None = None,
           is_reversed: bool = False) -> str:
    """reversal_of is set on the INSERT, not by a follow-up UPDATE: the
    immutability trigger refuses to update a posted row, which is the rule this
    file exists to test around."""
    src = f"'{source}'" if source else "NULL"
    rev = f"'{reversal_of}'" if reversal_of else "NULL"
    return f"""
INSERT INTO journal_entries
  (id, firm_id, client_id, entry_date, reference_no, narration, entry_type,
   is_posted, status, source_type, reversal_of, is_reversed)
VALUES ('{eid}','{FIRM}','{CLIENT}','{date}','{ref}','n','Journal',
        {str(posted).lower()},'{"posted" if posted else "draft"}',{src},{rev},
        {str(is_reversed).lower()});
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


def _discard(dsn: str, entry_id: str, with_pair: bool = False) -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        SELECT public.discard_posted_journal(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{entry_id}'::uuid, '{ACTOR}'::uuid,
            {str(with_pair).lower()});
    """)


REV = "e5000000-0000-0000-0000-0000000000aa"


def _pair(dsn: str, rev_date: str = "2026-08-21",
          rev_source: str = "manual") -> subprocess.CompletedProcess:
    """Turn MANUAL into a reversed pair: it is stamped is_reversed, and REV
    points back at it. This is the shape a CA is left holding after undoing a
    dummy entry — two rows netting to zero, which is what 276 exists to clear.

    The stamp goes on by UPDATE because that is how the product does it:
    prevent_posted_journal_update permits the is_reversed flip specifically
    (migration 274) and refuses everything else on a posted row."""
    return _psql(dsn, _entry(REV, "REV-001", rev_source, date=rev_date,
                             reversal_of=MANUAL)
                 + f"UPDATE journal_entries SET is_reversed = true WHERE id = '{MANUAL}';")


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


# ── Limit 3: half a pair, never ──────────────────────────────────────────────
# 275 refused BOTH halves outright, on the grounds that deleting the original
# strands the reversal and deleting the reversal strands the original. Both
# sentences are true of deleting ONE half and neither is true of deleting the
# pair — which is the case the feature was built for. 276 keeps the refusal for
# a lone half and adds the pair.

def test_half_a_pair_is_refused_from_the_original_side(db):
    assert _pair(db).returncode == 0
    r = _discard(db, MANUAL)
    assert r.returncode != 0, "deleting a reversed entry alone strands its reversal"
    assert "reversed by" in r.stderr.lower(), r.stderr


def test_half_a_pair_is_refused_from_the_reversal_side(db):
    assert _pair(db).returncode == 0
    r = _discard(db, REV)
    assert r.returncode != 0, "deleting a reversal alone strands its original"
    assert "is the reversal of" in r.stderr.lower(), r.stderr


def test_the_refusal_names_the_other_half(db):
    """A refusal that does not say WHICH entry is holding this one down leaves
    the CA hunting for it. Both directions name their counterpart."""
    assert _pair(db).returncode == 0
    assert "REV-001" in _discard(db, MANUAL).stderr
    assert "JNL-001" in _discard(db, REV).stderr


def test_a_dangling_is_reversed_flag_does_not_block_the_delete(db):
    """Entanglement is judged by what is actually THERE, not by the flag. An
    entry stamped is_reversed whose reversal has already gone points at nothing,
    so deleting it strands nothing — and refusing would leave a row no CA could
    ever remove, on the strength of a boolean describing a row that is gone."""
    stamp = _psql(db, f"UPDATE journal_entries SET is_reversed = true WHERE id='{MANUAL}';")
    assert stamp.returncode == 0, stamp.stderr
    r = _discard(db, MANUAL)
    assert r.returncode == 0, f"a flag with no live reversal behind it blocked the delete: {r.stderr}"


# ── The pair, deleted together ───────────────────────────────────────────────

def test_the_pair_flag_on_an_unpaired_entry_just_deletes_it(db):
    """The product sends with_pair on every deletion, because the confirm text
    says so and half a pair is refused either way round regardless. So the flag
    is set for the ORDINARY case far more often than for a pair, and it must not
    turn a lone entry into anything else."""
    r = _discard(db, MANUAL, with_pair=True)
    assert r.returncode == 0, r.stderr
    n = _psql(db, f"""
        SELECT count(*) FROM journal_entries WHERE deleted_at IS NOT NULL;""", tuples=True)
    assert n.stdout.strip() == "1", "the flag took something else with it"


def test_a_pair_goes_together(db):
    assert _pair(db).returncode == 0
    r = _discard(db, MANUAL, with_pair=True)
    assert r.returncode == 0, f"a manual pair in an open period was refused: {r.stderr}"

    got = _psql(db, f"""
        SELECT count(*) FROM journal_entries
         WHERE id IN ('{MANUAL}','{REV}') AND deleted_at IS NOT NULL;""", tuples=True)
    assert got.stdout.strip() == "2", "both halves must go, or neither"


def test_the_pair_can_be_deleted_from_either_end(db):
    """A CA selects whichever row they happened to click. Asking them to start
    from the original would be a rule with no reason a user could infer."""
    assert _pair(db).returncode == 0
    r = _discard(db, REV, with_pair=True)
    assert r.returncode == 0, r.stderr
    got = _psql(db, f"""
        SELECT count(*) FROM journal_entries
         WHERE id IN ('{MANUAL}','{REV}') AND deleted_at IS NOT NULL;""", tuples=True)
    assert got.stdout.strip() == "2", got.stdout


def test_the_pair_leaves_the_reporting_passbook(db):
    """A reversal pair nets to zero, so the TOTAL cannot prove the rebuild ran —
    it is unchanged either way. The debit side can: MANUAL and REV each debit
    CASH, so the passbook holds 3 x AMOUNT before and only the surviving
    auto-posted entry's 1 x AMOUNT after."""
    assert _pair(db).returncode == 0
    _psql(db, f"SELECT public.apb_rebuild_client('{FIRM}','{CLIENT}');")
    before = _psql(db, f"""
        SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances
         WHERE client_id='{CLIENT}' AND account_id='{CASH}';""", tuples=True).stdout.strip()
    assert before == str(3 * AMOUNT), f"passbook did not start from all three entries: {before}"

    assert _discard(db, MANUAL, with_pair=True).returncode == 0

    after = _psql(db, f"""
        SELECT COALESCE(sum(debit_paise), 0) FROM account_period_balances
         WHERE client_id='{CLIENT}' AND account_id='{CASH}';""", tuples=True).stdout.strip()
    assert after == str(AMOUNT), (
        f"passbook holds {after} paise, expected {AMOUNT} — the surviving "
        "auto-posted entry only."
    )


def test_a_pair_with_an_auto_posted_half_is_refused(db):
    """A manual entry reversed by a document's cascade. The manual half looks
    deletable on its own terms; the cascade's half is a document's journal and
    is not. Judging the pair by the requested row alone would delete it."""
    assert _pair(db, rev_source="sales_invoice").returncode == 0
    r = _discard(db, MANUAL, with_pair=True)
    assert r.returncode != 0, "an auto-posted half must stop the pair"
    assert "REV-001" in r.stderr and "sales_invoice" in r.stderr, r.stderr


def test_neither_half_moves_when_the_pair_is_refused(db):
    assert _pair(db, rev_source="sales_invoice").returncode == 0
    _discard(db, MANUAL, with_pair=True)
    got = _psql(db, f"""
        SELECT count(*) FROM journal_entries
         WHERE id IN ('{MANUAL}','{REV}') AND deleted_at IS NULL;""", tuples=True)
    assert got.stdout.strip() == "2", "a refused pair delete must write nothing"


def test_the_period_gate_is_applied_to_the_REVERSALS_date_too(db):
    """The limit most easily missed. A reversal is normally dated later than the
    entry it reverses and often lands in a different financial year. Judging the
    pair by the original's date alone would let a pair straddling a locked year
    move — deleting a row out of a period the CA has already closed."""
    assert _pair(db, rev_date="2027-06-30").returncode == 0   # FY 2027-28
    lock = _psql(db, f"""
        UPDATE firms SET locked_financial_years = ARRAY['2027-28'] WHERE id='{FIRM}';""")
    assert lock.returncode == 0, lock.stderr

    r = _discard(db, MANUAL, with_pair=True)
    assert r.returncode != 0, (
        "the original sits in an OPEN year, so this can only pass if the "
        "reversal's own date was never judged"
    )
    assert "REV-001" in r.stderr, r.stderr


# ── The record the deletion leaves ───────────────────────────────────────────
# 266 gave journal_lines its own audit trigger, so EDITS are covered. A discard
# is an UPDATE on journal_entries alone — the lines are never touched, so that
# trigger never fires, and audit_log was left holding a header with no money in
# it. These are the assertions that the deletion record is worth having.

def _audit(dsn: str, entry_id: str, field: str) -> str:
    return _psql(dsn, f"""
        SELECT {field} FROM audit_log
         WHERE entity_type='journal_entry' AND entity_id='{entry_id}' AND action='delete'
         ORDER BY created_at DESC LIMIT 1;""", tuples=True).stdout.strip()


def test_the_deletion_writes_an_audit_row(db):
    assert _discard(db, MANUAL).returncode == 0
    assert _audit(db, MANUAL, "id") != "", \
        "a deletion with no audit row is the silence Rule 3(1) exists to forbid"


def test_the_audit_row_holds_every_line(db):
    """The header alone records nothing of what was deleted. Both lines, with
    their amounts, must be in the row written at the moment of deletion."""
    assert _discard(db, MANUAL).returncode == 0
    n = _audit(db, MANUAL, "jsonb_array_length(old_data->'lines')")
    assert n == "2", f"old_data carries {n or 'no'} lines, expected 2"

    total = _audit(db, MANUAL, """(
        SELECT sum((l->>'debit_paise')::bigint)
          FROM jsonb_array_elements(old_data->'lines') l)""")
    assert total == str(AMOUNT), f"the deleted amount is not in the record: {total!r}"


def test_the_audit_row_names_the_accounts_not_just_their_ids(db):
    """An account id is a record only while the chart of accounts still holds it
    under that name. The point of this row is to be legible years later."""
    assert _discard(db, MANUAL).returncode == 0
    names = _audit(db, MANUAL, """(
        SELECT string_agg(l->>'account_name', ',' ORDER BY l->>'account_name')
          FROM jsonb_array_elements(old_data->'lines') l)""")
    assert names == "Cash,Sales", f"accounts not resolved in the record: {names!r}"


def test_both_halves_of_a_pair_are_recorded_separately(db):
    """One audit row per entry, each holding its own lines — not one row for the
    pair. An auditor asks about an entry, and audit_log is keyed by entity_id."""
    assert _pair(db).returncode == 0
    assert _discard(db, MANUAL, with_pair=True).returncode == 0
    for eid in (MANUAL, REV):
        assert _audit(db, eid, "jsonb_array_length(old_data->'lines')") == "2", eid


def test_a_refused_deletion_writes_no_audit_row(db):
    """The record is written inside the transaction, so a refusal rolls it back
    with everything else. An audit trail claiming deletions that never happened
    is worse than none."""
    _psql(db, f"UPDATE firms SET locked_financial_years = ARRAY['2026-27'] WHERE id='{FIRM}';")
    _discard(db, MANUAL)
    assert _audit(db, MANUAL, "id") == "", "a refused delete left a deletion in the log"


def test_the_snapshot_helper_is_scoped_to_the_firm(db):
    """It is handed p_firm/p_client by its callers and must not return a row for
    the wrong one — the app-layer filter is the primary isolation control here."""
    got = _psql(db, f"""
        SELECT public.journal_entry_snapshot(
            'f5000000-0000-0000-0000-0000000000ff'::uuid, '{CLIENT}'::uuid, '{MANUAL}'::uuid)
        IS NULL;""", tuples=True)
    assert got.stdout.strip() == "t", "the snapshot crossed a firm boundary"


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
            'public.discard_posted_journal(uuid,uuid,uuid,uuid,boolean)', 'EXECUTE');""",
        tuples=True)
    assert r.stdout.strip() == "f", "anon must not be able to discard journal entries"


def test_the_old_four_argument_signature_is_gone(db):
    """276 added a fifth parameter with a default. Left side by side with 275's
    four-argument function that is an OVERLOAD, not a replacement, and every
    four-argument call — which is what the router sends — becomes ambiguous and
    fails. It has to have been dropped."""
    r = _psql(db, """
        SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname = 'discard_posted_journal';""",
        tuples=True)
    assert r.stdout.strip() == "1", "two overloads present — a 4-arg call is ambiguous"


def test_anon_cannot_read_the_ledger_through_the_snapshot_helper(db):
    r = _psql(db, """
        SELECT has_function_privilege('anon',
            'public.journal_entry_snapshot(uuid,uuid,uuid)', 'EXECUTE');""",
        tuples=True)
    assert r.stdout.strip() == "f", "anon must not be able to read journal entries"

"""
Migration 360 — a journal line's account belongs to the entry's own client.

WHAT WAS WRONG (ACC-21)
    `post_journal_atomic` validates the ENTRY three ways (the firm is the
    caller's, the client is assigned to them, the firm's internal client is
    Partner-only) and then inserts the LINES with `(l->>'account_id')::uuid` and
    no validation at all. `journal_lines.account_id` carries one global foreign
    key to `chart_of_accounts(id)` and nothing else, so every account id in the
    database satisfied it — including another firm's. `edit_posted_journal` had
    the same omission. The entry was scoped; the money was not.

WHY THESE TESTS GO THROUGH THE TABLE AND NOT ONLY THE RPC
    The fix is a trigger on `journal_lines` rather than an EXISTS check inside
    each function, because the rule lived in zero places and putting it in two
    is how it comes to live in one. So the tests that matter most are the ones
    that write the table DIRECTLY, as the most privileged role there is: they
    prove the gate is the TABLE, and that a third writer — a repair script, a
    future RPC, the ORM path — cannot get round it by not being one of the two
    functions the finding named.

WHAT IS ALLOWED
    An account of the entry's firm belonging to the entry's client, and an
    account of the entry's firm belonging to NO client — `chart_of_accounts.
    client_id` is nullable and NULL there means a firm-level account, which any
    of that firm's entries may legitimately use. The firm check does the
    isolation; the client check narrows within it. Both are asserted, because a
    guard that refuses the firm-level account would break every seeded chart in
    this repo and would be discovered in production rather than here.
"""
from __future__ import annotations

import json
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
    reason="journal-line tenancy proof requires HARNESS_PG + psql",
)

FIRM = "f3600000-0000-0000-0000-000000000001"
OTHER_FIRM = "f3600000-0000-0000-0000-000000000002"
CLIENT = "c3600000-0000-0000-0000-000000000001"
SIBLING = "c3600000-0000-0000-0000-000000000002"      # same firm, different client
FOREIGN_CLIENT = "c3600000-0000-0000-0000-000000000003"   # the other firm's

ACC_OWN_DR = "a3600000-0000-0000-0000-000000000001"   # firm + CLIENT
ACC_OWN_CR = "a3600000-0000-0000-0000-000000000002"   # firm + CLIENT
ACC_FIRM_LEVEL = "a3600000-0000-0000-0000-000000000003"   # firm, client_id NULL
ACC_SIBLING = "a3600000-0000-0000-0000-000000000004"  # firm + SIBLING
ACC_FOREIGN = "a3600000-0000-0000-0000-000000000005"  # OTHER_FIRM

SEED = f"""
INSERT INTO firms (id,name,email) VALUES
  ('{FIRM}','F','f360@t.in'), ('{OTHER_FIRM}','G','g360@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type) VALUES
  ('{CLIENT}','{FIRM}','Mine','Proprietorship'),
  ('{SIBLING}','{FIRM}','My other client','Proprietorship'),
  ('{FOREIGN_CLIENT}','{OTHER_FIRM}','Somebody else''s','Proprietorship');
INSERT INTO chart_of_accounts (id,firm_id,client_id,account_code,account_name,account_type) VALUES
  ('{ACC_OWN_DR}','{FIRM}','{CLIENT}','1100','Trade Receivables','Asset'),
  ('{ACC_OWN_CR}','{FIRM}','{CLIENT}','4000','Sales Revenue','Revenue'),
  ('{ACC_FIRM_LEVEL}','{FIRM}',NULL,'1000','Bank — firm level','Asset'),
  -- Both account_code AND account_name are unique per FIRM (migration 015),
  -- not per client, so the sibling's revenue account can share neither.
  ('{ACC_SIBLING}','{FIRM}','{SIBLING}','4001','Sibling Sales Revenue','Revenue'),
  ('{ACC_FOREIGN}','{OTHER_FIRM}','{FOREIGN_CLIENT}','4000','Sales Revenue','Revenue');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e360_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, SEED)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _entry_row(dsn_: str, ref: str, client: str = CLIENT, firm: str = FIRM,
               posted: bool = True) -> str:
    eid = str(uuid.uuid4())
    r = _psql(dsn_, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                                     narration, entry_type, is_posted, status)
        VALUES ('{eid}','{firm}','{client}','2026-08-20','{ref}','n','Journal',
                {'true' if posted else 'false'},
                '{'posted' if posted else 'draft'}');
    """)
    assert r.returncode == 0, r.stderr
    return eid


def _insert_lines(dsn_: str, entry_id: str, legs) -> subprocess.CompletedProcess:
    values = ", ".join(
        f"('{entry_id}','{acct}',{dr},{cr})" for acct, dr, cr in legs)
    return _psql(dsn_, "INSERT INTO journal_lines "
                       "(journal_entry_id, account_id, debit_paise, credit_paise) "
                       f"VALUES {values};")


def _count_lines(dsn_: str, entry_id: str) -> int:
    r = _psql(dsn_, f"SELECT count(*) FROM journal_lines WHERE journal_entry_id='{entry_id}'", tuples=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


# ── What must still work ─────────────────────────────────────────────────────

def test_the_entrys_own_clients_accounts_post(dsn):
    eid = _entry_row(dsn, "OK-1")
    r = _insert_lines(dsn, eid, [(ACC_OWN_DR, 500000, 0), (ACC_OWN_CR, 0, 500000)])
    assert r.returncode == 0, r.stderr
    assert _count_lines(dsn, eid) == 2


def test_a_firm_level_account_is_not_a_foreign_account(dsn):
    """`chart_of_accounts.client_id` NULL means the FIRM's own books, and every
    seeded chart in this repo uses them — including the one
    test_journal_posting_privileges_pg.py posts through. Refusing them would be
    a guard that fails in production and passes here."""
    eid = _entry_row(dsn, "OK-2")
    r = _insert_lines(dsn, eid, [(ACC_FIRM_LEVEL, 500000, 0), (ACC_OWN_CR, 0, 500000)])
    assert r.returncode == 0, r.stderr
    assert _count_lines(dsn, eid) == 2


# ── What must not ────────────────────────────────────────────────────────────

def test_another_client_of_the_same_firm_is_refused(dsn):
    """The narrower half of the rule, and the one a firm-only check would miss:
    both clients belong to the caller, so nothing about the FIRM is wrong — the
    money would simply land in the wrong client's ledger."""
    eid = _entry_row(dsn, "BAD-1")
    r = _insert_lines(dsn, eid, [(ACC_OWN_DR, 500000, 0), (ACC_SIBLING, 0, 500000)])
    assert r.returncode != 0
    assert ACC_SIBLING in r.stderr
    assert _count_lines(dsn, eid) == 0


def test_another_firms_account_is_refused(dsn):
    eid = _entry_row(dsn, "BAD-2")
    r = _insert_lines(dsn, eid, [(ACC_OWN_DR, 500000, 0), (ACC_FOREIGN, 0, 500000)])
    assert r.returncode != 0
    assert ACC_FOREIGN in r.stderr
    assert _count_lines(dsn, eid) == 0


def test_one_bad_leg_refuses_the_whole_statement(dsn):
    """Statement-level, so a batch is all-or-nothing. A partially-inserted set
    of legs is an unbalanced entry, which is worse than a refusal."""
    eid = _entry_row(dsn, "BAD-3")
    r = _insert_lines(dsn, eid, [
        (ACC_OWN_DR, 500000, 0), (ACC_OWN_CR, 0, 400000), (ACC_FOREIGN, 0, 100000)])
    assert r.returncode != 0
    assert _count_lines(dsn, eid) == 0


def test_a_drafts_line_cannot_be_repointed_at_a_foreign_account(dsn):
    """Where the UPDATE arm of the trigger actually does the work.

    A DRAFT entry's lines are freely updatable — migration 251 refuses only a
    POSTED entry's (see the next test) — and a draft becomes permanent the
    moment it is posted. So the door the INSERT arm alone would leave open is:
    insert clean lines on a draft, repoint one, then post."""
    eid = _entry_row(dsn, "UPD-DRAFT", posted=False)
    assert _insert_lines(dsn, eid, [(ACC_OWN_DR, 500000, 0), (ACC_OWN_CR, 0, 500000)]).returncode == 0
    r = _psql(dsn, f"UPDATE journal_lines SET account_id='{ACC_FOREIGN}' "
                   f"WHERE journal_entry_id='{eid}' AND account_id='{ACC_OWN_CR}';")
    assert r.returncode != 0
    assert ACC_FOREIGN in r.stderr
    still = _psql(dsn, f"SELECT count(*) FROM journal_lines WHERE account_id='{ACC_FOREIGN}'", tuples=True)
    assert still.stdout.strip() == "0"


def test_a_posted_line_is_refused_earlier_by_migration_251(dsn):
    """Recorded so the layering is not mistaken for this trigger firing.

    `prevent_posted_journal_line_modification` (migration 251) is BEFORE UPDATE
    OR DELETE and refuses ANY change to a posted entry's lines, so it answers
    first and this trigger is never reached. Both refusals are correct; only the
    message differs, and a later reader comparing messages should know why."""
    eid = _entry_row(dsn, "UPD-POSTED")
    assert _insert_lines(dsn, eid, [(ACC_OWN_DR, 500000, 0), (ACC_OWN_CR, 0, 500000)]).returncode == 0
    r = _psql(dsn, f"UPDATE journal_lines SET account_id='{ACC_FOREIGN}' "
                   f"WHERE journal_entry_id='{eid}' AND account_id='{ACC_OWN_CR}';")
    assert r.returncode != 0
    assert "posted journal entry" in r.stderr


def test_the_gate_is_the_table_not_the_caller(dsn):
    """Run as the most privileged role in the database — `postgres`, which owns
    the schema, bypasses RLS and is exempt from the year-lock guard. It is still
    refused, which is the whole argument for the trigger over an EXISTS check in
    each function: a writer that is not one of those functions gets the rule
    anyway."""
    eid = _entry_row(dsn, "SUPER-1")
    r = _psql(dsn, "SET LOCAL ROLE postgres; "
                   "INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) "
                   f"VALUES ('{eid}','{ACC_FOREIGN}',500000,0);")
    assert r.returncode != 0
    assert _count_lines(dsn, eid) == 0


# ── Through the RPC the finding named ────────────────────────────────────────

def _post(dsn_: str, ref: str, legs, client: str = CLIENT) -> subprocess.CompletedProcess:
    entry = json.dumps({
        "firm_id": FIRM, "client_id": client, "entry_date": "2026-08-20",
        "reference_no": ref, "narration": "n", "entry_type": "Journal",
        "is_posted": True, "status": "posted",
    }).replace("'", "''")
    lines = json.dumps([
        {"account_id": a, "debit_paise": dr, "credit_paise": cr} for a, dr, cr in legs
    ]).replace("'", "''")
    return _psql(dsn_, f"SELECT post_journal_atomic('{entry}'::jsonb, '{lines}'::jsonb);")


def test_post_journal_atomic_posts_its_own_clients_accounts(dsn):
    assert _post(dsn, "RPC-OK", [(ACC_OWN_DR, 500000, 0), (ACC_OWN_CR, 0, 500000)]).returncode == 0


def test_post_journal_atomic_refuses_a_foreign_account(dsn):
    r = _post(dsn, "RPC-BAD", [(ACC_OWN_DR, 500000, 0), (ACC_FOREIGN, 0, 500000)])
    assert r.returncode != 0
    assert ACC_FOREIGN in r.stderr
    # And the ENTRY is gone too — the whole call is one transaction, so a
    # refused set of lines must not leave a headerless entry behind.
    left = _psql(dsn, "SELECT count(*) FROM journal_entries WHERE reference_no='RPC-BAD'", tuples=True)
    assert left.stdout.strip() == "0"


def test_post_journal_atomic_refuses_a_sibling_clients_account(dsn):
    r = _post(dsn, "RPC-SIB", [(ACC_OWN_DR, 500000, 0), (ACC_SIBLING, 0, 500000)])
    assert r.returncode != 0
    assert ACC_SIBLING in r.stderr


def test_the_trigger_names_the_account_it_refused(dsn):
    """The message is read by whoever is debugging a refused import, so it names
    the offending id rather than saying a line was wrong."""
    eid = _entry_row(dsn, "MSG-1")
    r = _insert_lines(dsn, eid, [(ACC_FOREIGN, 500000, 0)])
    assert "do not belong to this entry" in r.stderr, r.stderr

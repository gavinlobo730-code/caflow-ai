"""Migration 486 — the database functions that write as their owner now ask who is calling.

THE BUG THIS PINS
    Eight functions in `public` run as their owner (SECURITY DEFINER, so row security does not apply inside them),
    were executable by every signed-in user and never checked that their arguments belonged to the caller. The
    sharpest, `numbered_document_atomic`, takes the TABLE as a parameter: a signed-in identity with no staff record
    at all could make it insert a Partner row into `users`, which a direct insert refuses. The access matrix could
    not see it, because it tries table writes and these are function calls.

WHAT IS ASSERTED, FOR EVERY KIND OF CALLER
    The callers: a Partner, an assigned Manager, an assigned Executive, an Executive assigned to nothing, an assigned
    Reviewer (all of firm A), a Partner of another firm, a signed-in identity with no `users` row at all, the service
    role, and a plain administrator connection with no JWT (a migration, a harness). For each function the guard's
    refusal is SQLSTATE 42501; "let through" means the guard passed and the function's OWN logic then answered
    (whatever it answered, as long as it was not a 42501 from the guard).

    * numbered_document_atomic: a table that is not one of the four numbered documents is refused for EVERYONE,
      the service role and the administrator included, and the Partner row is never written; the four documents
      need accounting:write (Manager), the caller's own firm and a client they can reach.
    * settle_receipt_atomic: a receipt and journal naming different firms or clients are refused for everyone;
      otherwise accounting:write (Manager) OR banking:write (Executive), because a bank match-multi settles receipts.
    * edit/discard_posted_journal: accounting:write, the caller's firm and client, and the actor recorded must be the
      caller (the auth id or the users id).
    * replace_gstr2b_reconciliation: gst:compute (Executive) on a client the caller reaches.
    * record_fee_receipt_atomic: billing:write (Partner).
    * get_cash_payments_above_threshold: a read; the caller's firm and reach of the client, no tier.
    * increment_message_count: the conversation belongs to the caller's firm.
    * The originals (`<name>__unguarded`) are not executable by `authenticated` or `anon`; the wrappers are executable
      by `authenticated` and not by `anon`.
    * The negative control: the migration's own rollback puts the hole back (the outsider's Partner row is written),
      which is what makes every refusal above mean something.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
ROLLBACK = MIGRATIONS / "486_the_database_functions_that_write_as_their_owner_now_ask_who_is_calling_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the definer-function proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000486"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000487"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a486"
CLIENT_B = "cccccccc-0000-0000-0000-00000000b486"
CLIENT_OTHER = "cccccccc-0000-0000-0000-00000000c486"
VENDOR = "dddddddd-0000-0000-0000-000000000486"
CONVERSATION = "eeeeeeee-0000-0000-0000-000000000486"
MISSING = "99999999-0000-0000-0000-000000000486"

AUTH = {k: f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-0000-0000-000000000486" for k, n in (
    ("partner", "1"), ("manager", "2"), ("exec_a", "3"), ("exec_u", "4"), ("reviewer", "5"),
    ("other_partner", "6"), ("outsider", "7"))}
USER = {k: v.replace("-0000-0000-0000-", "-1111-0000-0000-", 1) for k, v in AUTH.items() if k != "outsider"}
ASSIGNED_TO_A = ("manager", "exec_a", "reviewer")

#: who -> (does the guard let them through?) for each function, as the migration header states it.
FIRM_A_STAFF = ("partner", "manager", "exec_a", "exec_u", "reviewer")
REFUSED_EVERYWHERE = ("other_partner", "outsider")


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-X", "-q"]
    args += (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _sqlstate(stderr: str) -> str | None:
    m = re.search(r"ERROR:\s+([0-9A-Z]{5}):", stderr)
    return m.group(1) if m else None


def _as(who: str | None) -> str:
    if who is None:
        return ""
    if who == "service":
        return "SET ROLE service_role; "
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; "


def _call(dsn: str, who: str | None, sql: str) -> tuple[str | None, str]:
    """(SQLSTATE of the refusal or None if it ran, stdout) of `sql` as `who` (None = administrator, no JWT)."""
    r = _psql(dsn, _as(who) + sql)
    return (None if r.returncode == 0 else _sqlstate(r.stderr) or "??????"), r.stdout


def _guard_refuses(dsn: str, who: str | None, sql: str) -> bool:
    state, _ = _call(dsn, who, sql)
    return state == "42501"


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"def486_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        roles = (("partner", "Partner"), ("manager", "Manager"), ("exec_a", "Executive"), ("exec_u", "Executive"),
                 ("reviewer", "Reviewer"), ("other_partner", "Partner"))
        auth_rows = ", ".join(f"('{v}', '{k}@d486.test')" for k, v in AUTH.items())
        users = ", ".join(
            f"('{USER[k]}', '{OTHER_FIRM if k == 'other_partner' else FIRM}', '{AUTH[k]}', '{k}@d486.test', "
            f"'{k}', '{role}', true)" for k, role in roles)
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT_A}')" for k in ASSIGNED_TO_A)
        _ok(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','D486 Firm','d486@test.in'), ('{OTHER_FIRM}','D486 Other','d486o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B','Private Limited'),
              ('{CLIENT_OTHER}','{OTHER_FIRM}','Client Other','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}','{FIRM}','{CLIENT_A}','V');
            INSERT INTO ai_conversations (id, firm_id, user_id) VALUES ('{CONVERSATION}','{FIRM}','{USER['partner']}');
            INSERT INTO fixed_assets (firm_id, client_id, asset_name, asset_category, purchase_date, purchase_cost_paise)
              VALUES ('{FIRM}','{CLIENT_A}','A1','Plant','2025-04-01',100),
                     ('{FIRM}','{CLIENT_B}','B1','Plant','2025-04-01',100);
        """)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── the call shapes ──────────────────────────────────────────────────────────
def _debit_note(table: str = "debit_notes", lines: str = "debit_note_lines", fk: str = "debit_note_id",
                firm: str = FIRM, client: str = CLIENT_A, no: str | None = None) -> str:
    no = no or f"DN-{uuid.uuid4().hex[:6]}"
    return (
        f"SELECT numbered_document_atomic('{table}', jsonb_build_object('firm_id','{firm}','client_id','{client}',"
        f"'vendor_id','{VENDOR}','debit_note_no','{no}','debit_note_date','2024-06-01',"
        f"'taxable_amount_paise',100000,'total_paise',118000,'status','draft'), '{lines}', '[]'::jsonb, '{fk}');")


def _partner_row_via(table_call_who: str | None) -> str:
    """The reproduction: ask the function to write a Partner `users` row for the outsider."""
    return (
        "SELECT numbered_document_atomic('users', jsonb_build_object('firm_id','%s','auth_user_id','%s',"
        "'email','mallory@d486.test','full_name','Mallory','role','Partner','is_active',true), "
        "'debit_note_lines', '[]'::jsonb, 'debit_note_id');" % (FIRM, AUTH["outsider"]))


def _settle(firm: str = FIRM, client: str = CLIENT_A, receipt_firm: str | None = None) -> str:
    return (
        "SELECT settle_receipt_atomic(jsonb_build_object('firm_id','%s','client_id','%s'), "
        "jsonb_build_object('firm_id','%s','client_id','%s','reference_no','R1'), '[]'::jsonb, '[]'::jsonb);"
        % (receipt_firm or firm, client, firm, client))


def _edit(firm: str = FIRM, client: str = CLIENT_A, actor: str | None = None) -> str:
    a = f"'{actor}'::uuid" if actor else "NULL"
    return (f"SELECT edit_posted_journal('{firm}','{client}','{MISSING}','[]'::jsonb, NULL, NULL, NULL, {a});")


def _discard(firm: str = FIRM, client: str = CLIENT_A, actor: str | None = None) -> str:
    a = f"'{actor}'::uuid" if actor else "NULL"
    return f"SELECT discard_posted_journal('{firm}','{client}','{MISSING}',{a}, false);"


def _replace_2b(firm: str = FIRM, client: str = CLIENT_A) -> str:
    return f"SELECT * FROM replace_gstr2b_reconciliation('{firm}','{client}','2026-04','[]'::jsonb,'{{}}'::jsonb);"


def _fee_receipt(firm: str = FIRM) -> str:
    return (f"SELECT record_fee_receipt_atomic('{firm}','{MISSING}','2026-04-01',100,'cash',NULL,NULL);")


def _cash(firm: str = FIRM, client: str = CLIENT_A) -> str:
    return f"SELECT count(*) FROM get_cash_payments_above_threshold('{firm}','{client}',1);"


def _bump(conv: str = CONVERSATION) -> str:
    return f"SELECT increment_message_count('{conv}');"


# ── numbered_document_atomic ─────────────────────────────────────────────────
def test_the_reproduction_is_refused_and_writes_no_partner_row(db):
    for who in ("outsider", "reviewer", "exec_u", "manager", "partner", "other_partner", "service", None):
        assert _guard_refuses(db, who, _partner_row_via(who)), who
    assert _ok(db, f"SELECT count(*) FROM users WHERE auth_user_id = '{AUTH['outsider']}';") == "0"


def test_only_the_four_numbered_documents_are_accepted_by_anyone(db):
    for table, lines, fk in (("credit_notes", "debit_note_lines", "debit_note_id"),
                             ("debit_notes", "credit_note_lines", "debit_note_id"),
                             ("debit_notes", "debit_note_lines", "credit_note_id"),
                             ("firms", "debit_note_lines", "debit_note_id")):
        for who in ("partner", "service", None):
            assert _guard_refuses(db, who, _debit_note(table, lines, fk)), (table, lines, fk, who)


def test_a_debit_note_is_issued_by_manager_and_above_of_the_firm_for_a_client_they_reach(db):
    for who in ("partner", "manager", "service", None):
        state, _ = _call(db, who, _debit_note())
        assert state is None, (who, state)
    for who in ("exec_a", "exec_u", "reviewer", "other_partner", "outsider"):
        assert _guard_refuses(db, who, _debit_note()), who
    # the Partner of another firm cannot issue for firm A's client; firm A's Partner cannot name another firm's
    assert _guard_refuses(db, "other_partner", _debit_note(firm=OTHER_FIRM, client=CLIENT_A))
    assert _guard_refuses(db, "partner", _debit_note(firm=OTHER_FIRM, client=CLIENT_OTHER))


# ── settle_receipt_atomic ────────────────────────────────────────────────────
def test_a_receipt_and_its_journal_must_name_one_firm_for_everyone(db):
    for who in ("partner", "service", None):
        assert _guard_refuses(db, who, _settle(receipt_firm=OTHER_FIRM)), who


def test_a_receipt_is_settled_by_accounting_write_or_a_bank_match(db):
    for who in ("partner", "manager", "exec_a", "service", None):
        state, _ = _call(db, who, _settle())
        assert state != "42501", (who, state)           # the guard passed; the function answered for itself
    for who in ("reviewer", "exec_u", "other_partner", "outsider"):
        assert _guard_refuses(db, who, _settle()), who


# ── the journal edit and discard ─────────────────────────────────────────────
@pytest.mark.parametrize("call", [_edit, _discard], ids=["edit", "discard"])
def test_a_manual_journal_is_changed_by_accounting_write_on_a_client_the_caller_reaches(db, call):
    for who in ("partner", "manager"):
        state, _ = _call(db, who, call())
        assert state not in ("42501",), (who, state)
    for who in ("exec_a", "exec_u", "reviewer", "other_partner", "outsider"):
        assert _guard_refuses(db, who, call()), who
    assert _guard_refuses(db, "partner", call(firm=OTHER_FIRM, client=CLIENT_OTHER))


@pytest.mark.parametrize("call", [_edit, _discard], ids=["edit", "discard"])
def test_the_actor_recorded_must_be_the_caller(db, call):
    assert _guard_refuses(db, "manager", call(actor=USER["partner"]))
    assert _guard_refuses(db, "manager", call(actor=AUTH["partner"]))
    for mine in (USER["manager"], AUTH["manager"]):
        state, _ = _call(db, "manager", call(actor=mine))
        assert state != "42501", mine
    state, _ = _call(db, "service", call(actor=USER["partner"]))
    assert state != "42501"      # the backend may name whom it acts for


# ── the 2B replace, the fee receipt, the cash read, the counter ──────────────
def test_a_2b_is_replaced_by_gst_compute_on_a_client_the_caller_reaches(db):
    for who in ("partner", "manager", "exec_a", "service", None):
        state, _ = _call(db, who, _replace_2b())
        assert state != "42501", (who, state)
    for who in ("reviewer", "exec_u", "other_partner", "outsider"):
        assert _guard_refuses(db, who, _replace_2b()), who


def test_a_fee_receipt_is_a_partners(db):
    for who in ("partner", "service", None):
        state, _ = _call(db, who, _fee_receipt())
        assert state != "42501", (who, state)
    for who in ("manager", "exec_a", "reviewer", "other_partner", "outsider"):
        assert _guard_refuses(db, who, _fee_receipt()), who


def test_the_cash_payments_read_needs_the_firm_and_the_clients_reach_and_no_tier(db):
    for who in ("partner", "manager", "exec_a", "reviewer", "service", None):
        state, out = _call(db, who, _cash())
        assert state is None and out.strip().splitlines()[-1] == "0", (who, state)
    for who in ("exec_u", "other_partner", "outsider"):
        assert _guard_refuses(db, who, _cash()), who


def test_a_conversations_counter_is_bumped_inside_its_own_firm(db):
    state, out = _call(db, "partner", _bump())
    assert state is None and out.strip().splitlines()[-1] == "1"
    assert _guard_refuses(db, "other_partner", _bump())
    assert _guard_refuses(db, "outsider", _bump())
    state, _ = _call(db, "service", _bump())
    assert state is None
    state, out = _call(db, "partner", _bump(MISSING))     # no such conversation: nothing to guard, nothing bumped
    assert state is None


def _worklist(firm: str = FIRM, ids: str = "NULL") -> str:
    return (f"SELECT coalesce(string_agg(client_id::text, ',' ORDER BY client_id::text), '') "
            f"FROM hub_client_worklist('{firm}','fixed_assets',{ids});")


def _clients_seen(who: str | None, db: str, ids: str = "NULL") -> set[str]:
    state, out = _call(db, who, _worklist(ids=ids))
    assert state is None, (who, state)
    return {c for c in out.rstrip("\n").split("\n")[-1].split(",") if c}


def test_the_hub_worklist_shows_a_non_partner_only_the_clients_they_reach(db):
    both = {CLIENT_A, CLIENT_B}
    assert _clients_seen("partner", db) == both
    assert _clients_seen("service", db) == both and _clients_seen(None, db) == both
    for who in ("manager", "exec_a", "reviewer"):
        assert _clients_seen(who, db) == {CLIENT_A}, who                       # no list asked for: all of THEIRS
        assert _clients_seen(who, db, f"ARRAY['{CLIENT_B}'::uuid]") == set(), who   # a client they do not reach
    assert _clients_seen("exec_u", db) == set()
    for who in ("other_partner", "outsider"):
        assert _guard_refuses(db, who, _worklist()), who


def test_the_hub_worklist_never_shows_a_non_partner_the_internal_client(db):
    # The firm's internal practice client is named on the firm (`firms.internal_client_id`, read by my_internal_client_id).
    _ok(db, f"UPDATE clients SET is_internal = true WHERE id = '{CLIENT_A}'; "
            f"UPDATE firms SET internal_client_id = '{CLIENT_A}' WHERE id = '{FIRM}';")
    assert CLIENT_A not in _clients_seen("manager", db)
    assert CLIENT_A in _clients_seen("partner", db)


# ── privileges ───────────────────────────────────────────────────────────────
SIGNATURES = {
    "numbered_document_atomic": "text,jsonb,text,jsonb,text",
    "settle_receipt_atomic": "jsonb,jsonb,jsonb,jsonb",
    "edit_posted_journal": "uuid,uuid,uuid,jsonb,text,text,date,uuid",
    "discard_posted_journal": "uuid,uuid,uuid,uuid,boolean",
    "replace_gstr2b_reconciliation": "uuid,uuid,text,jsonb,jsonb",
    "record_fee_receipt_atomic": "uuid,uuid,date,bigint,text,text,text",
    "increment_message_count": "uuid",
    "get_cash_payments_above_threshold": "uuid,uuid,bigint",
    "hub_client_worklist": "uuid,text,uuid[]",
}


@pytest.mark.parametrize("name,sig", sorted(SIGNATURES.items()))
def test_the_originals_are_out_of_reach_and_the_wrappers_are_in(db, name, sig):
    q = lambda role, fn: _ok(db, f"SELECT has_function_privilege('{role}', 'public.{fn}({sig})'::regprocedure, 'EXECUTE');")
    assert q("authenticated", name) == "t" and q("service_role", name) == "t" and q("anon", name) == "f"
    assert q("authenticated", f"{name}__unguarded") == "f" and q("anon", f"{name}__unguarded") == "f"
    assert q("service_role", f"{name}__unguarded") == "t"
    assert _ok(db, f"SELECT prosecdef FROM pg_proc WHERE oid = 'public.{name}({sig})'::regprocedure;") == "t"


def test_nobody_signed_in_can_ask_whether_a_client_year_is_locked(db):
    sig = "public.is_client_fy_locked(uuid,uuid,date)"
    q = lambda role: _ok(db, f"SELECT has_function_privilege('{role}', '{sig}'::regprocedure, 'EXECUTE');")
    assert q("authenticated") == "f" and q("anon") == "f" and q("service_role") == "t"


def test_the_originals_cannot_be_called_by_a_signed_in_user_by_their_new_name(db):
    state, _ = _call(db, "outsider", _partner_row_via("outsider").replace("numbered_document_atomic", "numbered_document_atomic__unguarded"))
    assert state == "42501"      # SQLSTATE 42501 is also "permission denied for function"
    assert _ok(db, f"SELECT count(*) FROM users WHERE auth_user_id = '{AUTH['outsider']}';") == "0"


# ── the negative control ─────────────────────────────────────────────────────
def test_its_own_rollback_puts_the_hole_back(db):
    """Without this the refusals above would pass on a database that never had the hole."""
    r = _psql(db, ROLLBACK.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr
    state, _ = _call(db, "outsider", _partner_row_via("outsider"))
    assert state is None, "the rollback did not restore the unguarded function: the control is vacuous"
    assert _ok(db, f"SELECT count(*) FROM users WHERE auth_user_id = '{AUTH['outsider']}' AND role = 'Partner';") == "1"
    for who in ("reviewer", "exec_u"):
        state, _ = _call(db, who, _edit())
        assert state != "42501", who

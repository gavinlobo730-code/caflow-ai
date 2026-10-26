"""The ledger functions carry the posting person's audit actor for a privileged caller (migration 545, POST-A-317 step 1).

WHAT THIS IS FOR
    Taking the direct database door to the ledger away means the API's posting kernel calls `post_journal_atomic` and
    `settle_receipt_atomic` with its PRIVILEGED client, which has no `auth.uid()`; the audit triggers (`audit_capture`, migrations
    111/336, for every table, and `audit_capture_journal_line`, migration 266, for the lines) write the row-level edit log
    (Companies (Accounts) Rules 2014 Rule 3(1)) only when `auth.uid()` is present, so the journal-entry, journal-line, receipt and
    invoice-settlement rows would vanish from it. Migration 545 lets the two functions carry the posting person's AUTH id for the
    length of their own transaction (`carry_audit_actor` sets the transaction-local setting `app.audit_actor` from the payload's
    reserved key `audit_actor`, the auth id the API reads off the request's own token, or, for a job, from `created_by`, the internal
    user id, and only inside the entry's own firm) and lets both trigger functions read it through `carried_audit_actor()`, and
    only when `auth.uid()` is NULL. An independent review of the first version found that it reached `audit_capture` and not the
    line trigger, and that most postings name no `created_by`; both are held below.

WHAT THIS HOLDS (real Postgres, as each person)
    * A PRIVILEGED CALLER IS AUDITED AS THE PERSON: the service role (and a connection with no JWT) posting a journal, or a
      receipt with its allocation and the invoice it settles, writes `audit_log` rows whose actor is the auth id of the person
      named by `audit_actor` (or, without it, by `created_by`), with their email, and none for a payload that names nobody, names a
      person of another firm, names a value that is not a uuid, or names a person with no auth id.
    * EVERY ROW A SIGNED-IN POSTING AUDITS, A PRIVILEGED ONE AUDITS TOO: the (entity, action) set of a journal and of a receipt
      posted by a Manager equals the set the same posting writes for the service role, journal LINES included.
    * `audit_actor` WINS OVER `created_by`, A WRONG ONE IS NOT REPLACED BY IT, AND THE KEY NEVER REACHES THE UNGUARDED BODY (which
      would refuse an unknown column).
    * A SIGNED-IN CALLER IS NEVER REPLACED: a Manager who posts with another person's id in `created_by` or `audit_actor` (or sets
      the setting by hand) is audited as themselves.
    * A CARRIED ROW SAYS SO: its metadata carries `actor_source: carried`; a signed-in row does not.
    * THE SETTING ENDS WITH THE TRANSACTION and a second posting in the same transaction does not inherit the first one's person.
    * AN UNREADABLE VALUE IS NO ACTOR AND BREAKS NOTHING.
    * THE SHAPE: the carrier and the reader are SECURITY INVOKER and executable by nobody signed in; the four functions are the
      definitions the migrations that LAST defined them wrote (found by scanning the migration directory) plus exactly the added
      lines; the wrappers' grants are the ones 533 gave and are untouched.
    * THE CLOSING CHECK is run alone after each spoiling it is there to catch.
    * THE ROLLBACK restores the four previous definitions exactly and a privileged caller is audited by nobody again; a
      re-apply brings the actor back.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the audit-actor proof requires HARNESS_PG + psql",
)

FIRM = "54500000-0000-0000-0000-000000000001"
OTHER_FIRM = "54500000-0000-0000-0000-000000000002"
CLIENT_A = "54500000-0000-0000-0000-0000000000a1"
CUSTOMER_A = "54500000-0000-0000-0000-0000000000d1"
BANK_A, AR_A = "54500000-0000-0000-0000-0000000000a5", "54500000-0000-0000-0000-0000000000a6"
INVOICE_A = "54500000-0000-0000-0000-0000000000e1"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("54500000-0000-0000-0000-00000000000a", "54500000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("54500000-0000-0000-0000-00000000000b", "54500000-1111-0000-0000-000000000002", "Manager", FIRM),
    "other_firm": ("54500000-0000-0000-0000-000000000010", "54500000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
NO_AUTH_USER = "54500000-0000-0000-0000-000000000013"         # a users row with no auth id (an invited member)
MIGRATION = next(p for p in MIGRATIONS.glob("545_the_ledger_functions_carry_the_posting_persons_audit_actor*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("545_the_ledger_functions_carry_the_posting_persons_audit_actor*_rollback.sql"))
POST = "public.post_journal_atomic(jsonb, jsonb)"
SETTLE = "public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)"
CARRY = "public.carry_audit_actor(text, text, uuid)"
READER = "public.carried_audit_actor()"
AUDIT = "public.audit_capture()"
LINE_AUDIT = "public.audit_capture_journal_line()"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _one(dsn: str, sql: str) -> str:
    return _rows(dsn, sql)[0][0]


def _text(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


def _prefix(who: str) -> str:
    if who == "backend":
        return ""
    if who == "service":
        return "SET ROLE service_role; "
    sub = PEOPLE[who][1]
    return f"SET request.jwt.claims = '{{\"sub\": \"{sub}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _call(dsn: str, who: str, sql: str) -> tuple[bool, str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _prefix(who) + sql], capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _entry(day: str, ref: str, **extra) -> dict:
    return {"firm_id": FIRM, "client_id": CLIENT_A, "entry_date": day, "reference_no": ref, "narration": "t",
            "entry_type": "Journal", "is_posted": True, "status": "posted", **extra}


def _lines(paise: int = 10000) -> list[dict]:
    return [{"account_id": BANK_A, "debit_paise": paise, "credit_paise": 0, "narration": "d"},
            {"account_id": AR_A, "debit_paise": 0, "credit_paise": paise, "narration": "c"}]


def _j(x) -> str:
    return json.dumps(x).replace("'", "''")


def _post(dsn: str, who: str, ref: str, **extra) -> tuple[bool, str]:
    return _call(dsn, who, f"SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', ref, **extra))}'::jsonb, '{_j(_lines())}'::jsonb);")


def _settle(dsn: str, who: str, ref: str, **extra) -> tuple[bool, str]:
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT_A, "customer_id": CUSTOMER_A, "receipt_no": ref,
               "receipt_date": "2025-09-30", "amount_paise": 10000, "tds_paise": 0, "unallocated_paise": 0,
               "payment_mode": "bank", "reference_no": "", "notes": ""}
    alloc = [{"sales_invoice_id": INVOICE_A, "allocated_paise": 10000}]
    return _call(dsn, who, "SELECT public.settle_receipt_atomic('%s'::jsonb, '%s'::jsonb, '%s'::jsonb, '%s'::jsonb);" % (
        _j(receipt), _j(_entry("2025-09-30", ref, entry_type="Receipt", **extra)), _j(_lines()), _j(alloc)))


def _audit(dsn: str, where: str) -> list[list[str]]:
    return _rows(dsn, f"SELECT entity_type, action, actor_id, coalesce(actor_email, '-'), coalesce(metadata->>'actor_source', '-') "
                      f"FROM audit_log WHERE {where} ORDER BY entity_type, action")


def _kinds(dsn: str, where: str) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in _audit(dsn, where)}


# Migration 546 took EXECUTE on the two ledger functions away from signed-in users: the API calls them as the server. This file
# drives the SIGNED-IN branch of the wrappers (the second lock, kept on purpose), so the throwaway database hands the grant back.
# The real grants are asserted in test_546_... and against the migrated template, never against a database handed back to.
HAND_BACK_546 = ("GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated; "
                 "GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO authenticated;")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e545_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        assert _psql(d, HAND_BACK_546).returncode == 0
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{NO_AUTH_USER}', '{FIRM}', NULL, 'invited@t.in', 'invited', 'Manager', true);
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{BANK_A}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset');
            INSERT INTO client_sales_invoices
                (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                VALUES ('{INVOICE_A}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER_A}', 'SINV-1', '2025-04-01', 100000, 'issued', 0, 0);
            DELETE FROM audit_log;
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── a privileged caller is audited as the person it names ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["service", "backend"])
def test_a_privileged_journal_posting_is_audited_as_the_person_named_in_created_by(dsn, who):
    ok, jid = _post(dsn, who, f"A-{who}", created_by=PEOPLE["manager_a"][0], posted_by=PEOPLE["manager_a"][0])
    assert ok, jid
    rows = _audit(dsn, f"entity_id = '{jid}'")
    assert rows == [["journal_entry", "create", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"],
                    ["journal_line", "create", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"],
                    ["journal_line", "create", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"]], rows


def test_a_privileged_receipt_is_audited_with_its_allocation_and_the_invoice_it_settles(dsn):
    ok, out = _settle(dsn, "service", "R-1", created_by=PEOPLE["partner"][0])
    assert ok, out
    rows = _audit(dsn, f"firm_id = '{FIRM}'")
    who = PEOPLE["partner"][1]
    kinds = {(r[0], r[1]) for r in rows}
    assert ("journal_entry", "create") in kinds and ("journal_line", "create") in kinds and ("receipt", "create") in kinds \
        and ("client_sales_invoice", "update") in kinds, rows
    assert {r[2] for r in rows} == {who}, rows


@pytest.mark.parametrize("label,created_by", [
    ("names nobody", None),
    ("names a person of another firm", PEOPLE["other_firm"][0]),
    ("names a person with no auth id", NO_AUTH_USER),
])
def test_a_payload_that_names_no_usable_person_writes_no_audit_row_and_still_posts(dsn, label, created_by):
    extra = {} if created_by is None else {"created_by": created_by}
    ok, jid = _post(dsn, "service", f"N-{abs(hash(label)) % 10**6}", **extra)
    assert ok, (label, jid)
    assert _audit(dsn, f"entity_type = 'journal_entry' AND entity_id = '{jid}'") == [], label


def test_a_value_that_is_not_a_usable_person_is_no_actor_and_the_carrier_does_not_raise(dsn):
    """`created_by` is a uuid column with a foreign key, so the posting itself refuses a value that is not a uuid or names nobody, as
    it always did; the carrier is called first and must not be what breaks. Called directly, as the owner."""
    for bad in ("not-a-uuid", "12345", "", "  ", "54500000-0000-0000-0000-0000000000ee"):
        for first, second in ((f"'{bad}'", "NULL"), ("NULL", f"'{bad}'")):
            ok, out = _call(dsn, "backend", f"SELECT public.carry_audit_actor({first}, {second}, '{FIRM}'::uuid); "
                                            "SELECT 'SETTING=' || coalesce(current_setting('app.audit_actor', true), '');")
            assert ok and out == "SETTING=", (bad, first, second, out)


# ── a signed-in caller is never replaced ─────────────────────────────────────────────────────────────────────────────
def test_a_manager_posting_with_another_persons_id_in_created_by_is_audited_as_themselves(dsn):
    ok, jid = _post(dsn, "manager_a", "S-1", created_by=PEOPLE["partner"][0])
    assert ok, jid
    rows = _audit(dsn, f"entity_type = 'journal_entry' AND entity_id = '{jid}'")
    assert [r[2] for r in rows] == [PEOPLE["manager_a"][1]], rows


def test_a_signed_in_manager_sending_the_reserved_key_is_audited_as_themselves_and_the_posting_succeeds(dsn):
    ok, jid = _post(dsn, "manager_a", "S-2", audit_actor=PEOPLE["partner"][1], created_by=PEOPLE["partner"][0])
    assert ok, jid
    rows = _audit(dsn, f"entity_id = '{jid}'")
    assert {r[2] for r in rows} == {PEOPLE["manager_a"][1]} and {r[4] for r in rows} == {"-"}, rows
    ok, out = _settle(dsn, "manager_a", "S-3", audit_actor=PEOPLE["partner"][1])
    assert ok, out
    rows = _audit(dsn, f"firm_id = '{FIRM}'")
    assert {r[2] for r in rows} == {PEOPLE["manager_a"][1]}, rows


def test_a_signed_in_session_that_sets_the_setting_by_hand_is_still_audited_as_itself(dsn):
    ok, out = _call(dsn, "manager_a", f"""
        BEGIN;
        SELECT set_config('app.audit_actor', '{PEOPLE["partner"][1]}', true);
        UPDATE customers SET name = 'renamed' WHERE id = '{CUSTOMER_A}';
        COMMIT;""")
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer' AND action = 'update'")
    assert rows and {r[2] for r in rows} == {PEOPLE["manager_a"][1]}, rows


def test_a_garbage_setting_for_a_privileged_write_is_no_actor_and_breaks_nothing(dsn):
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT set_config('app.audit_actor', 'not-a-uuid', true);
        UPDATE customers SET name = 'renamed' WHERE id = '{CUSTOMER_A}';
        COMMIT;""")
    assert ok, out
    assert _one(dsn, f"SELECT name FROM customers WHERE id = '{CUSTOMER_A}'") == "renamed"
    assert _audit(dsn, "entity_type = 'customer'") == []


def test_the_setting_ends_with_the_postings_transaction(dsn):
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', 'E-1', created_by=PEOPLE["manager_a"][0]))}'::jsonb, '{_j(_lines())}'::jsonb);
        COMMIT;
        SELECT 'SETTING=' || coalesce(current_setting('app.audit_actor', true), '');""")
    assert ok, out
    assert out == "SETTING=", f"the carried actor outlived the transaction: {out!r}"


def test_a_signed_in_posting_leaves_no_carried_actor_in_its_transaction(dsn):
    """Nothing is carried for a signed-in caller even when its payload names someone: the carrier returns at once, so the setting a
    trigger could read is empty for the rest of the transaction (it would be ignored anyway while auth.uid() is set; this holds the
    carrier to its own rule rather than to the trigger's)."""
    ok, out = _call(dsn, "manager_a", f"""
        BEGIN;
        SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', 'NS-1', audit_actor=PEOPLE["partner"][1], created_by=PEOPLE["partner"][0]))}'::jsonb, '{_j(_lines())}'::jsonb);
        SELECT 'SETTING=' || coalesce(current_setting('app.audit_actor', true), '');""")
    assert ok, out
    assert out == "SETTING=", f"a signed-in posting carried an actor: {out!r}"


def test_a_second_posting_in_one_transaction_does_not_inherit_the_first_ones_person(dsn):
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', 'T-1', created_by=PEOPLE["manager_a"][0]))}'::jsonb, '{_j(_lines())}'::jsonb);
        SELECT public.post_journal_atomic('{_j(_entry('2025-09-30', 'T-2'))}'::jsonb, '{_j(_lines())}'::jsonb);
        COMMIT;""")
    assert ok, out
    first = _one(dsn, "SELECT id FROM journal_entries WHERE reference_no = 'T-1'")
    second = _one(dsn, "SELECT id FROM journal_entries WHERE reference_no = 'T-2'")
    assert {r[2] for r in _audit(dsn, f"entity_id = '{first}'")} == {PEOPLE["manager_a"][1]}
    assert _audit(dsn, f"entity_id = '{second}'") == [], "the second posting was audited as the first one's person"


# ── the audit_actor key: an auth id the API read off the request's own token ──────────────────────────────
@pytest.mark.parametrize("who", ["service", "backend"])
def test_the_audit_actor_key_names_the_person_by_auth_id_for_every_row_and_the_key_is_not_a_column(dsn, who):
    ok, jid = _post(dsn, who, f"K-{who}", audit_actor=PEOPLE["manager_a"][1])
    assert ok, jid                                        # an unstripped key would be an unknown column of the unguarded body
    rows = _audit(dsn, f"entity_id = '{jid}'")
    assert {r[0] for r in rows} == {"journal_entry", "journal_line"} and {r[2] for r in rows} == {PEOPLE["manager_a"][1]}, rows
    assert {r[3] for r in rows} == {"manager_a@t.in"} and {r[4] for r in rows} == {"carried"}
    ok, out = _settle(dsn, who, f"KR-{who}", audit_actor=PEOPLE["manager_a"][1])
    assert ok, out
    assert {r[2] for r in _audit(dsn, f"entity_type IN ('receipt', 'client_sales_invoice') AND firm_id = '{FIRM}'")} == {PEOPLE["manager_a"][1]}


def test_the_audit_actor_key_wins_over_created_by(dsn):
    ok, jid = _post(dsn, "service", "W-1", audit_actor=PEOPLE["partner"][1], created_by=PEOPLE["manager_a"][0])
    assert ok, jid
    assert {r[2] for r in _audit(dsn, f"entity_id = '{jid}'")} == {PEOPLE["partner"][1]}


@pytest.mark.parametrize("label,actor", [
    ("an auth id of another firm", PEOPLE["other_firm"][1]),
    ("an auth id nobody holds", "54500000-1111-0000-0000-0000000000ee"),
    ("a value that is not a uuid", "not-a-uuid"),
])
def test_an_audit_actor_that_is_no_member_of_the_firm_is_no_actor_and_created_by_does_not_replace_it(dsn, label, actor):
    ok, jid = _post(dsn, "service", f"B-{abs(hash(label)) % 10**6}", audit_actor=actor, created_by=PEOPLE["manager_a"][0])
    assert ok, (label, jid)
    assert _audit(dsn, f"entity_id = '{jid}'") == [], label


# ── every row a signed-in posting audits, a privileged one audits too ────────────────────────────────────
def test_a_privileged_journal_posting_audits_every_kind_of_row_a_signed_in_one_does(dsn):
    ok, signed = _post(dsn, "manager_a", "P-S")
    assert ok, signed
    ok, priv = _post(dsn, "service", "P-P", audit_actor=PEOPLE["manager_a"][1])
    assert ok, priv
    mine, theirs = _kinds(dsn, f"entity_id = '{signed}'"), _kinds(dsn, f"entity_id = '{priv}'")
    assert ("journal_line", "create") in mine and mine == theirs, (mine, theirs)
    assert [r[4] for r in _audit(dsn, f"entity_id = '{signed}'")] == ["-"] * 3, "a signed-in row is not labelled carried"


def test_a_privileged_receipt_audits_every_kind_of_row_a_signed_in_one_does(dsn):
    ok, out = _settle(dsn, "manager_a", "RS-S")
    assert ok, out
    signed = _kinds(dsn, f"firm_id = '{FIRM}'")
    _psql(dsn, "DELETE FROM audit_log")
    ok, out = _settle(dsn, "service", "RS-P", audit_actor=PEOPLE["manager_a"][1])
    assert ok, out
    priv = _kinds(dsn, f"firm_id = '{FIRM}'")
    assert {"journal_line", "journal_entry", "receipt", "client_sales_invoice"} <= {k[0] for k in signed} and signed == priv, (signed, priv)


# ── the shape ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _acl(dsn: str, sig: str) -> dict[str, bool]:
    return {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{sig}'::regprocedure, 'EXECUTE')") == "t"
            for r in ("anon", "authenticated", "service_role")}


def test_the_carrier_and_the_reader_are_invoker_and_closed_to_everyone_signed_in(dsn):
    for sig in (CARRY, READER):
        assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{sig}'::regprocedure") == "f", sig
        acl = _acl(dsn, sig)
        assert acl["anon"] is False and acl["authenticated"] is False, (sig, acl)
    # and the call from a signed-in session is refused by the database, not just absent from a list
    ok, msg = _call(dsn, "manager_a", f"SELECT public.carry_audit_actor(NULL, '{PEOPLE['partner'][0]}', '{FIRM}'::uuid);")
    assert not ok and "permission denied" in msg, msg
    ok, msg = _call(dsn, "manager_a", "SELECT public.carried_audit_actor();")
    assert not ok and "permission denied" in msg, msg


def test_the_carrier_and_the_reader_pin_their_search_path(dsn):
    for sig, want in ((CARRY, "search_path=public, pg_temp"), (READER, "search_path=pg_catalog")):
        assert want in _text(dsn, f"SELECT coalesce(array_to_string(proconfig, '|'), '') FROM pg_proc WHERE oid = '{sig}'::regprocedure"), sig


def test_the_carrier_and_the_reader_are_closed_even_where_the_platform_grants_new_functions_to_the_signed_in(dsn):
    """On Supabase a function created in `public` is granted to anon and authenticated by default privileges; this database has none,
    so the migration's REVOKE would pass unseen. Give it the platform's default, drop both functions and apply the migration again."""
    assert _psql(dsn, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;").returncode == 0
    assert _psql(dsn, f"DROP FUNCTION {CARRY}; DROP FUNCTION {READER};").returncode == 0
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for sig in (CARRY, READER):
        acl = _acl(dsn, sig)
        assert acl["anon"] is False and acl["authenticated"] is False, (sig, acl)


# (migration 546 took the wrappers' signed-in grant away; the grants are asserted in test_546_..., not here, where the fixture
# hands the grant back so the signed-in branch can still be driven)


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _function_body(text: str, name: str) -> str:
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(", text)
    assert m, name
    k = text.index("AS ", m.start())
    tag = re.match(r"AS (\$\w*\$)", text[k:]).group(1)
    start = k + 3 + len(tag)
    return text[start:text.index(tag + ";", start)]


def _last_definer(name: str) -> Path:
    """The highest-numbered migration before this one that defines the function (not a rollback): found by scanning the directory, so
    it cannot be pointed at a stale ancestor. (`\\(p_` for the two wrappers keeps their `__unguarded` bodies out.)"""
    cands = sorted(p for p in MIGRATIONS.glob("*.sql")
                   if not p.name.endswith("_rollback.sql") and p.name < MIGRATION.name
                   and re.search(rf"CREATE (?:OR REPLACE )?FUNCTION\s+public\.{name}\s*\((?:p_|\))", p.read_text()))
    return cands[-1]


# what each of the four functions adds to its ancestor, as it reads in the LIVE source once whitespace is folded and comments are gone
READ_ADDED = r"IF v_actor IS NULL THEN v_actor := public\.carried_audit_actor\(\); v_carried := v_actor IS NOT NULL; END IF; "
DECL_ADDED = r" v_carried boolean := false;"
META_ADDED = r" \|\| CASE WHEN v_carried THEN jsonb_build_object\('actor_source', 'carried'\) ELSE '\{\}'::jsonb END"


LATER_546 = {          # migration 546's block in each wrapper, as it reads once whitespace is folded and comments are gone
    "post_journal_atomic": r"IF auth\.uid\(\) IS NULL AND NOT EXISTS \( SELECT 1 FROM public\.clients c WHERE c\.id = v_client AND c\.firm_id = v_firm\) THEN "
    r"RAISE EXCEPTION 'post_journal_atomic: client % is not a client of firm %', v_client, v_firm USING ERRCODE = '42501'; END IF; ",
    "settle_receipt_atomic": r"IF auth\.uid\(\) IS NULL AND NOT EXISTS \( SELECT 1 FROM public\.clients c WHERE c\.id = NULLIF\(p_journal_entry->>'client_id', ''\)::uuid "
    r"AND c\.firm_id = NULLIF\(p_journal_entry->>'firm_id', ''\)::uuid\) THEN RAISE EXCEPTION 'settle_receipt_atomic: client % is not a client of firm %', "
    r"NULLIF\(p_journal_entry->>'client_id', ''\)::uuid, NULLIF\(p_journal_entry->>'firm_id', ''\)::uuid USING ERRCODE = '42501'; END IF; ",
}


def test_the_four_functions_are_their_last_definition_plus_exactly_the_added_lines(dsn):
    # audit_capture <- 336 ; audit_capture_journal_line <- 266 ; the wrappers <- 533
    assert _last_definer("audit_capture").name.startswith("336_"), _last_definer("audit_capture").name
    assert _last_definer("audit_capture_journal_line").name.startswith("266_")
    assert _last_definer("post_journal_atomic").name.startswith("533_"), _last_definer("post_journal_atomic").name
    assert _last_definer("settle_receipt_atomic").name.startswith("533_"), _last_definer("settle_receipt_atomic").name
    for sig, name in ((AUDIT, "audit_capture"), (LINE_AUDIT, "audit_capture_journal_line")):
        live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure"))
        for pattern in (DECL_ADDED, READ_ADDED, META_ADDED):
            live, n = re.subn(pattern, "", live, count=1)
            assert n == 1, (name, pattern)
        assert live == _norm(_function_body(_last_definer(name).read_text(), name)), name
    for sig, name, carry, strip in (
            (POST, "post_journal_atomic",
             r"PERFORM public\.carry_audit_actor\(p_entry->>'audit_actor', p_entry->>'created_by', v_firm\); ",
             ("p_entry - 'audit_actor'", "p_entry")),
            (SETTLE, "settle_receipt_atomic",
             r"PERFORM public\.carry_audit_actor\(p_journal_entry->>'audit_actor', p_journal_entry->>'created_by', NULLIF\(p_journal_entry->>'firm_id', ''\)::uuid\); ",
             ("p_journal_entry - 'audit_actor'", "p_journal_entry"))):
        live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure"))
        live, n = re.subn(carry, "", live, count=1)
        assert n == 1, f"{name} does not carry the audit actor exactly once"
        live, n = re.subn(LATER_546[name], "", live, count=1)        # migration 546: a privileged call names a client of its firm
        assert n == 1, f"{name} does not carry migration 546's block exactly once"
        assert live.count(strip[0]) == 1, f"{name} does not remove the reserved key exactly once"
        live = live.replace(strip[0], strip[1], 1)
        assert live == _norm(_function_body(_last_definer(name).read_text(), name)), name


# ── the closing check, run alone after each spoiling ──────────────────────────────────────────────────────────
def _closing_block() -> str:
    text = MIGRATION.read_text()
    i = text.rindex("DO $$")
    return text[i:]


def _ancestor_definition(name: str) -> str:
    text = _last_definer(name).read_text()
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(.*?\n(\$\w*\$);", text, re.S)
    assert m, name
    return m.group(0).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _wrapper_stub(fn: str, text: str) -> str:
    args = "p_entry jsonb, p_lines jsonb" if fn == "post_journal_atomic" else "p_receipt jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb"
    ret = "uuid" if fn == "post_journal_atomic" else "jsonb"
    return (f"CREATE OR REPLACE FUNCTION public.{fn}({args}) RETURNS {ret} LANGUAGE plpgsql VOLATILE SECURITY DEFINER "
            f"SET search_path = public, pg_catalog AS $x$ BEGIN RAISE EXCEPTION '{text}'; END; $x$;")


SPOILS = [
    ("carry executable by a signed-in user", f"GRANT EXECUTE ON FUNCTION {CARRY} TO authenticated;"),
    ("carry executable by anon", f"GRANT EXECUTE ON FUNCTION {CARRY} TO anon;"),
    ("carry is a definer", f"ALTER FUNCTION {CARRY} SECURITY DEFINER;"),
    ("carry is gone", f"DROP FUNCTION {CARRY} CASCADE;"),
    ("the reader executable by a signed-in user", f"GRANT EXECUTE ON FUNCTION {READER} TO authenticated;"),
    ("the reader executable by anon", f"GRANT EXECUTE ON FUNCTION {READER} TO anon;"),
    ("the reader is a definer", f"ALTER FUNCTION {READER} SECURITY DEFINER;"),
    ("the reader is gone", f"DROP FUNCTION {READER} CASCADE;"),
    ("the post wrapper does not carry", None),
    ("the receipt wrapper does not carry", None),
    ("the post wrapper does not remove the reserved key", _wrapper_stub("post_journal_atomic", "carry_audit_actor")),
    ("the receipt wrapper does not remove the reserved key", _wrapper_stub("settle_receipt_atomic", "carry_audit_actor")),
    ("the post wrapper does not carry but removes the key", _wrapper_stub("post_journal_atomic", "''audit_actor''")),
    ("the receipt wrapper does not carry but removes the key", _wrapper_stub("settle_receipt_atomic", "''audit_actor''")),
    ("audit_capture does not read it", None),
    ("the line trigger function does not read it", None),
    ("a wrapper lost the service role's grant", f"REVOKE EXECUTE ON FUNCTION {POST} FROM service_role;"),
    ("a wrapper gained anon", f"GRANT EXECUTE ON FUNCTION {POST} TO anon;"),
]
SPOIL_RESTORES = {"the post wrapper does not carry": "post_journal_atomic", "the receipt wrapper does not carry": "settle_receipt_atomic",
                  "audit_capture does not read it": "audit_capture", "the line trigger function does not read it": "audit_capture_journal_line"}


@pytest.mark.parametrize("label,spoil", SPOILS, ids=[s[0] for s in SPOILS])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(dsn, label, spoil):
    assert _psql(dsn, _closing_block()).returncode == 0, "the closing check should pass on the migrated database"
    if spoil is None:
        spoil = _ancestor_definition(SPOIL_RESTORES[label])
    assert _psql(dsn, spoil).returncode == 0, label
    r = _psql(dsn, _closing_block())
    # a dropped function makes the check's own regprocedure cast fail first; either way the check does not pass
    assert r.returncode != 0 and ("migration 545" in r.stderr or "does not exist" in r.stderr), (label, r.stderr)


# ── the rollback and the re-apply ─────────────────────────────────────────────────────────────────────────
ALL = (POST, SETTLE, AUDIT, LINE_AUDIT, CARRY, READER)


def _sources(dsn: str, sigs=ALL) -> dict[str, str]:
    out = {}
    for sig in sigs:
        out[sig] = _text(dsn, f"SELECT coalesce((SELECT prosrc FROM pg_proc WHERE oid = to_regprocedure('{sig}')), '-')")
    return out


def test_the_rollback_restores_the_previous_definitions_and_the_actor_is_lost_and_a_reapply_brings_it_back(dsn):
    before = _sources(dsn)
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _one(dsn, "SELECT count(*) FROM pg_proc WHERE proname IN ('carry_audit_actor', 'carried_audit_actor')") == "0"
    for sig, name in ((POST, "post_journal_atomic"), (SETTLE, "settle_receipt_atomic"), (AUDIT, "audit_capture"),
                      (LINE_AUDIT, "audit_capture_journal_line")):
        live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{sig}'::regprocedure"))
        assert "carry_audit_actor" not in live and "app.audit_actor" not in live and "carried_audit_actor" not in live, name
        assert live == _norm(_function_body(_last_definer(name).read_text(), name)), name
    ok, jid = _post(dsn, "service", "RB-1", created_by=PEOPLE["manager_a"][0])
    assert ok and _audit(dsn, f"entity_id = '{jid}'") == [], "after the rollback a privileged caller is audited by nobody"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    for later in sorted(MIGRATIONS.glob("54[67]_*.sql")):       # 545 over a database that carries 546 and 547 gives back 545 alone (547 redefines the reader)
        if not later.name.endswith("_rollback.sql"):
            assert _psql_file(dsn, later).returncode == 0
    ok, jid = _post(dsn, "service", "RB-2", created_by=PEOPLE["manager_a"][0])
    assert ok and {r[2] for r in _audit(dsn, f"entity_id = '{jid}'")} == {PEOPLE["manager_a"][1]}
    assert _sources(dsn) == before, "a rollback and a re-apply must give back the same definitions"


def test_applying_it_twice_changes_nothing(dsn):
    before = _sources(dsn)
    assert _psql_file(dsn, MIGRATION).returncode == 0
    once = _sources(dsn)                                # over a database that carries 546, 545 gives back its own two wrappers
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _sources(dsn) == once, "applying 545 a second time changed something"
    for later in sorted(MIGRATIONS.glob("54[67]_*.sql")):      # 547 redefines the reader again: the chain's definition is 545 then 546 then 547
        if not later.name.endswith("_rollback.sql"):
            assert _psql_file(dsn, later).returncode == 0
    assert _sources(dsn) == before, "545 then 546 then 547 must give back the chain's definitions"

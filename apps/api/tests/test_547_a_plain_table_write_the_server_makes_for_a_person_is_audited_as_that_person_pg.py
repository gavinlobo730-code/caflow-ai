"""A plain table write the server makes for a person is audited as that person (migration 547, POST-A-339 ahead of the change).

WHAT THIS IS FOR
    POST-A-339 takes the signed-in role's grants on the payroll, bank and document tables away, so the API writes them with its
    PRIVILEGED client, which has no `auth.uid()`; the audit triggers record a write only when someone is signed in, so every one of
    those writes would leave the row-level edit log (production: 492 bank-line creates and 789 updates by the trigger in 120 days
    against 58 written by the application). Migration 545 already let the two ledger functions carry the person into the triggers
    through the transaction-local setting `app.audit_actor`; a plain PostgREST write cannot set a setting, so migration 547 lets the
    one reader both triggers ask, `carried_audit_actor()`, also read the person from the request header `x-acting-auth-user`, and
    only when the request runs as `service_role`.

WHAT THIS HOLDS (real Postgres, as each role)
    * THE SERVER'S OWN REQUEST IS AUDITED AS THE PERSON IT NAMES: a `service_role` write with the header writes an `audit_log` row whose
      actor is the auth id in the header, with their email, marked `actor_source: carried`, on an ordinary table and on the document tables
      this change is for.
    * NO HEADER, NO ACTOR: the same write without it writes no row, exactly as before.
    * A LABEL THAT IS NOT A PERSON IS NO ACTOR and breaks nothing: not a uuid, empty, an auth id nobody holds.
    * A SIGNED-IN PERSON IS NEVER REPLACED OR IMPERSONATED: a Manager who sends the header (naming a Partner) is audited as themselves
      and the row is not marked carried; a role that is not `service_role` (the owner connection, `authenticated`) is not believed.
      (A signed-in session cannot become `service_role` to make it count: PostgREST sets the role from the verified key and offers a
      caller no way to issue `SET ROLE`; this harness connects as the superuser, which can, so that is not asserted here.)
    * THE TRANSACTION-LOCAL SETTING OF 545 STILL WINS OVER THE HEADER, and the ledger path of 545 is untouched. An EMPTY setting (what
      545's carrier writes for "no actor", and what a pooled connection leaves behind) is read as no setting, so the header is read:
      that is decided in the migration's header and held here, with a real ledger posting made on a header-carrying request.
    * ONLY THE SERVICE ROLE IS BELIEVED, for every other role: `anon`, `authenticated` with no subject, `authenticated` whose token
      merely CLAIMS role service_role, and the owner connection. Each negative case also asserts the UPDATE touched the row, so an
      empty audit log is a finding and not an update that never happened.
    * WHAT THE LABEL MAY LOOK LIKE: an upper-case, hyphen-less or braced uuid is read as the uuid it is; one wrapped in spaces, and
      request headers that are an array, a scalar, null, a string or empty, are no actor and break nothing.
    * A PERSON OF ANOTHER FIRM, OR A DEACTIVATED ONE, IS ACCEPTED TODAY. That is a known and written-down limit (the reader cannot see
      the row's firm; the migration's header says why), pinned so a later hardening flips it knowingly.
    * THE PROBE SAYS WHAT THE DATABASE SAW: `audit_actor_probe()` returns the role of the request and the header's value (null when there
      is none or the headers are not JSON), is closed to every signed-in role and open to the service role alone, so `/health` can say
      whether the hosted API really passes the header through.
    * THE SHAPE: the reader is still SECURITY INVOKER with a pinned search path and closed to every signed-in role; its body is
      migration 545's plus exactly the added lines; the closing check fails when what it checks is spoiled.
    * THE ROLLBACK restores 545's definition exactly and the header is ignored again; a re-apply brings it back; applying twice changes
      nothing.
    * EVERY SENSITIVE TABLE THAT WAS AUDITED BY THE TRIGGER IS STILL AUDITED BY IT: the seventeen tables the trigger covers are listed, so
      a table whose trigger goes missing is seen before the grant on it is taken away.

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
    reason="the audit-header proof requires HARNESS_PG + psql",
)

FIRM = "54700000-0000-0000-0000-000000000001"
CLIENT_A = "54700000-0000-0000-0000-0000000000a1"
CUSTOMER_A = "54700000-0000-0000-0000-0000000000d1"
REQUEST_A = "54700000-0000-0000-0000-0000000000f1"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("54700000-0000-0000-0000-00000000000a", "54700000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("54700000-0000-0000-0000-00000000000b", "54700000-1111-0000-0000-000000000002", "Manager"),
}
NOBODY = "54700000-1111-0000-0000-0000000000ee"       # an auth id no users row holds
OTHER_FIRM = "54700000-0000-0000-0000-000000000002"
STRANGER = ("54700000-0000-0000-0000-000000000010", "54700000-1111-0000-0000-000000000009")    # a deactivated user of another firm
BANK_A, AR_A = "54700000-0000-0000-0000-0000000000a5", "54700000-0000-0000-0000-0000000000a6"
MIGRATION = next(p for p in MIGRATIONS.glob("547_a_plain_table_write_the_server_makes_for_a_person*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("547_a_plain_table_write_the_server_makes_for_a_person*_rollback.sql"))
READER = "public.carried_audit_actor()"
PROBE = "public.audit_actor_probe()"
HEADER = "x-acting-auth-user"


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


def _headers(value) -> str:
    """The request headers PostgREST hands the database: a JSON object with lower-case names. `value` None sends none of ours."""
    body = {"accept": "application/json", "user-agent": "postgrest-py"}
    if value is not None:
        body[HEADER] = value
    return "SET request.headers = '" + json.dumps(body).replace("'", "''") + "'; "


def _prefix(who: str, header=None) -> str:
    """`service`: the server's own request (role service_role, no sub). `backend`: the owner connection, no role switch.
    `anon`, `authenticated_no_subject`, `authenticated_claiming_service`, `service_with_subject`: the other shapes a request can have.
    A person: a signed-in session with that person's `sub`."""
    if who == "backend":
        return _headers(header)
    if who == "service":
        return _headers(header) + "SET ROLE service_role; "
    if who == "anon":
        return _headers(header) + "SET ROLE anon; "
    if who == "authenticated_no_subject":
        return _headers(header) + "SET ROLE authenticated; "
    if who == "authenticated_claiming_service":     # a token that SAYS role service_role, running as the database role authenticated
        return _headers(header) + "SET request.jwt.claims = '{\"role\": \"service_role\"}'; SET ROLE authenticated; "
    if who == "service_with_subject":                # the service role, on a request that also carries a signed-in subject
        return (_headers(header) + f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE['manager_a'][1]}\", \"role\": \"service_role\"}}'; "
                "SET ROLE service_role; ")
    sub = PEOPLE[who][1]
    return (_headers(header) + f"SET request.jwt.claims = '{{\"sub\": \"{sub}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; ")


def _call(dsn: str, who: str, sql: str, header=None) -> tuple[bool, str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _prefix(who, header) + sql], capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _audit(dsn: str, where: str) -> list[list[str]]:
    return _rows(dsn, f"SELECT entity_type, action, actor_id, coalesce(actor_email, '-'), coalesce(metadata->>'actor_source', '-') "
                      f"FROM audit_log WHERE {where} ORDER BY entity_type, action")


RENAME = f"UPDATE customers SET name = 'renamed-' || substr(md5(random()::text), 1, 6) WHERE id = '{CUSTOMER_A}'"


def _changed(dsn: str) -> None:
    """The UPDATE under test really touched the row (an empty audit log proves nothing if it did not), then the name is put back."""
    name = _one(dsn, f"SELECT name FROM customers WHERE id = '{CUSTOMER_A}'")
    assert name.startswith("renamed-"), f"the UPDATE touched no row, so an empty audit log proves nothing (name is {name!r})"
    assert _psql(dsn, f"UPDATE customers SET name = 'Cust' WHERE id = '{CUSTOMER_A}'").returncode == 0


def _open_customers_to_every_role(dsn: str) -> None:
    """Row security and grants out of the way for `customers`, so that a role under test reaches the audit trigger at all: what is
    under test here is the trigger's reader, not the table's policies."""
    r = _psql(dsn, "ALTER TABLE customers DISABLE ROW LEVEL SECURITY; GRANT SELECT, UPDATE ON customers TO anon, authenticated;")
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e547_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER_A}', '{FIRM}', '{CLIENT_A}', 'Cust');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
                ('{BANK_A}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
                ('{AR_A}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset');
            DELETE FROM audit_log;
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the server's own request is audited as the person it names ───────────────────────────────────────────────────────
def test_a_server_write_that_names_a_person_is_audited_as_that_person_and_says_it_was_carried(dsn):
    ok, out = _call(dsn, "service", RENAME, header=PEOPLE["manager_a"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer' AND action = 'update'")
    assert rows == [["customer", "update", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"]], rows


def test_the_document_tables_this_change_is_for_are_audited_the_same_way(dsn):
    ok, out = _call(dsn, "service",
                    "INSERT INTO document_requests (id, firm_id, client_id, title, status) "
                    f"VALUES ('{REQUEST_A}', '{FIRM}', '{CLIENT_A}', 'Bank statement', 'pending')", header=PEOPLE["partner"][1])
    assert ok, out
    ok, out = _call(dsn, "service", f"UPDATE document_requests SET status = 'fulfilled' WHERE id = '{REQUEST_A}'", header=PEOPLE["partner"][1])
    assert ok, out
    ok, out = _call(dsn, "service", f"DELETE FROM document_requests WHERE id = '{REQUEST_A}'", header=PEOPLE["partner"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'document_request'")
    assert [(r[1], r[2], r[4]) for r in rows] == [("create", PEOPLE["partner"][1], "carried"), ("delete", PEOPLE["partner"][1], "carried"),
                                                  ("update", PEOPLE["partner"][1], "carried")], rows


def test_without_the_header_the_server_write_is_audited_by_nobody_as_before(dsn):
    ok, out = _call(dsn, "service", RENAME)
    assert ok, out
    assert _audit(dsn, "entity_type = 'customer'") == []
    _changed(dsn)


@pytest.mark.parametrize("label,value", [
    ("not a uuid", "not-a-uuid"),
    ("empty", ""),
    ("blank", "   "),
    ("a uuid nobody holds", NOBODY),
    ("a number", "12345"),
])
def test_a_label_that_is_not_a_person_is_no_actor_and_the_write_still_succeeds(dsn, label, value):
    ok, out = _call(dsn, "service", RENAME, header=value)
    assert ok, (label, out)
    assert _audit(dsn, "entity_type = 'customer'") == [], label
    _changed(dsn)


@pytest.mark.parametrize("label,headers", [
    ("not json at all", "not json"),
    ("a json array", "[1, 2]"),
    ("a json number", "5"),
    ("a json string", '"x-acting-auth-user"'),
    ("json null", "null"),
    ("empty", ""),
])
def test_request_headers_of_any_other_shape_are_no_actor_and_break_nothing(dsn, label, headers):
    ok, out = _call(dsn, "service", f"SELECT set_config('request.headers', '{headers}', false); " + RENAME)
    assert ok, (label, out)
    assert _audit(dsn, "entity_type = 'customer'") == [], label
    _changed(dsn)


@pytest.mark.parametrize("label,form", [
    ("upper-case", lambda a: a.upper()),
    ("without hyphens", lambda a: a.replace("-", "")),
    ("in braces", lambda a: "{" + a + "}"),
])
def test_a_uuid_written_another_way_is_read_as_the_uuid_it_is(dsn, label, form):
    ok, out = _call(dsn, "service", RENAME, header=form(PEOPLE["manager_a"][1]))
    assert ok, (label, out)
    rows = _audit(dsn, "entity_type = 'customer'")
    assert rows == [["customer", "update", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"]], (label, rows)
    _changed(dsn)


def test_a_uuid_wrapped_in_spaces_is_no_actor_which_fails_closed(dsn):
    ok, out = _call(dsn, "service", RENAME, header=" " + PEOPLE["manager_a"][1] + " ")
    assert ok, out
    assert _audit(dsn, "entity_type = 'customer'") == []
    _changed(dsn)


def test_a_person_of_another_firm_or_a_deactivated_one_is_accepted_today_and_that_is_the_pinned_limit(dsn):
    """The reader cannot see the row's firm, so it cannot ask whether the person belongs to it (the migration's header says why this
    is accepted and what it would take to change). Pinned so that the day a hardening lands this test flips on purpose."""
    stranger_id, stranger_auth = STRANGER
    seeded = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{stranger_auth}', 'stranger@t.in');
        INSERT INTO firms (id, name, email) VALUES ('{OTHER_FIRM}', 'G', 'g@t.in');
        INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
             VALUES ('{stranger_id}', '{OTHER_FIRM}', '{stranger_auth}', 'stranger@t.in', 'stranger', 'Partner', false);""")
    assert seeded.returncode == 0, seeded.stderr
    ok, out = _call(dsn, "service", RENAME, header=stranger_auth)
    assert ok, out
    assert _audit(dsn, "entity_type = 'customer'") == [["customer", "update", stranger_auth, "stranger@t.in", "carried"]]
    _changed(dsn)


# ── a signed-in person is never replaced or impersonated ─────────────────────────────────────────────────────────────
def test_a_signed_in_manager_who_sends_the_header_is_audited_as_themselves_and_not_marked_carried(dsn):
    ok, out = _call(dsn, "manager_a", RENAME, header=PEOPLE["partner"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer' AND action = 'update'")
    assert rows == [["customer", "update", PEOPLE["manager_a"][1], "manager_a@t.in", "-"]], rows
    _changed(dsn)


@pytest.mark.parametrize("who", ["backend", "anon", "authenticated_no_subject", "authenticated_claiming_service"])
def test_no_request_that_is_not_the_service_role_is_believed_and_its_write_still_happens(dsn, who):
    """The owner connection is not the server's request, and neither is `anon`, `authenticated` without a subject (auth.uid() is
    NULL there, so only the role stands between the header and a row), or `authenticated` with a token that merely CLAIMS role
    service_role (PostgREST sets the database role from the verified key; the claim is not it). Each case proves the UPDATE touched
    the row, so the empty log is the reader's answer and not a write that never happened."""
    _open_customers_to_every_role(dsn)
    ok, out = _call(dsn, who, RENAME, header=PEOPLE["partner"][1])
    assert ok, (who, out)
    assert _audit(dsn, "entity_type = 'customer'") == [], who
    _changed(dsn)


def test_a_service_request_that_also_carries_a_signed_in_subject_is_audited_as_that_subject_and_not_the_header(dsn):
    ok, out = _call(dsn, "service_with_subject", RENAME, header=PEOPLE["partner"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer'")
    assert rows == [["customer", "update", PEOPLE["manager_a"][1], "manager_a@t.in", "-"]], rows
    _changed(dsn)


# ── the setting of migration 545 still wins ──────────────────────────────────────────────────────────────────────────
def test_the_transaction_local_setting_wins_over_the_header(dsn):
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT set_config('app.audit_actor', '{PEOPLE["partner"][1]}', true);
        {RENAME};
        COMMIT;""", header=PEOPLE["manager_a"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer'")
    assert [r[2] for r in rows] == [PEOPLE["partner"][1]], rows
    _changed(dsn)


def test_a_garbage_setting_is_no_actor_and_the_header_is_not_a_fallback_for_it(dsn):
    """545's rule is kept: an unreadable setting is no actor. (The header is read only when there is NO setting at all.)"""
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT set_config('app.audit_actor', 'not-a-uuid', true);
        {RENAME};
        COMMIT;""", header=PEOPLE["manager_a"][1])
    assert ok, out
    assert _audit(dsn, "entity_type = 'customer'") == []
    _changed(dsn)


def test_an_empty_setting_is_read_as_no_setting_so_the_servers_header_is_read(dsn):
    """DECIDED in the migration's header: 545's carrier writes the empty string for "no actor", and so does a pooled connection after
    any earlier transaction, so the two cannot be told apart. On the server's own request the header is the verified person."""
    ok, out = _call(dsn, "service", f"""
        BEGIN;
        SELECT set_config('app.audit_actor', '', true);
        {RENAME};
        COMMIT;""", header=PEOPLE["manager_a"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer'")
    assert rows == [["customer", "update", PEOPLE["manager_a"][1], "manager_a@t.in", "carried"]], rows
    _changed(dsn)


def test_every_statement_of_one_transaction_is_audited_as_the_person(dsn):
    ok, out = _call(dsn, "service", f"BEGIN; {RENAME}; {RENAME}; COMMIT;", header=PEOPLE["partner"][1])
    assert ok, out
    rows = _audit(dsn, "entity_type = 'customer'")
    assert [(r[1], r[2], r[4]) for r in rows] == [("update", PEOPLE["partner"][1], "carried")] * 2, rows
    _changed(dsn)


def _ledger_entry(ref: str) -> str:
    entry = {"firm_id": FIRM, "client_id": CLIENT_A, "entry_date": "2025-09-30", "reference_no": ref, "narration": "t",
             "entry_type": "Journal", "is_posted": True, "status": "posted"}
    lines = [{"account_id": BANK_A, "debit_paise": 10000, "credit_paise": 0, "narration": "d"},
             {"account_id": AR_A, "debit_paise": 0, "credit_paise": 10000, "narration": "c"}]
    esc = lambda x: json.dumps(x).replace("'", "''")      # noqa: E731
    return f"SELECT public.post_journal_atomic('{esc(entry)}'::jsonb, '{esc(lines)}'::jsonb);"


def test_a_ledger_posting_made_on_the_servers_request_names_the_header_person_on_the_entry_and_its_lines(dsn):
    """545's carrier runs inside the posting, decides there is no actor (the payload names nobody) and leaves the empty setting; the
    request's header then names the person, on the entry and on both lines, exactly as it does for a plain table."""
    ok, jid = _call(dsn, "service", _ledger_entry("H-1"), header=PEOPLE["partner"][1])
    assert ok, jid
    rows = _audit(dsn, f"entity_id = '{jid}'")
    assert rows == [["journal_entry", "create", PEOPLE["partner"][1], "partner@t.in", "carried"],
                    ["journal_line", "create", PEOPLE["partner"][1], "partner@t.in", "carried"],
                    ["journal_line", "create", PEOPLE["partner"][1], "partner@t.in", "carried"]], rows
    ok, other = _call(dsn, "service", _ledger_entry("H-2"))
    assert ok, other
    assert _audit(dsn, f"entity_id = '{other}'") == [], "without the header the same posting is audited as before: by nobody"


# ── the trigger still covers every table the signed-in role is losing ────────────────────────────────────────────────
AUDITED = {
    "attendance", "bank_accounts", "bank_matching_rules", "bank_reconciliation_matches", "bank_reconciliations", "bank_statements",
    "bank_transactions", "client_documents", "document_extractions", "document_requests", "document_risks", "documents",
    "entity_documents", "leave_balances", "payroll_employees", "payroll_runs", "salary_structures",
}


def test_the_audit_trigger_covers_the_seventeen_sensitive_tables_it_covered_before(dsn):
    have = {r[0] for r in _rows(dsn, "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                                     "WHERE NOT t.tgisinternal AND t.tgname = 'trg_audit_capture'")}
    assert AUDITED <= have, f"a table the audit trigger covered has lost it: {sorted(AUDITED - have)}"
    # not merely present: switched on, and for all three events (tgtype bits 4 = INSERT, 8 = DELETE, 16 = UPDATE)
    weak = [r[0] for r in _rows(dsn, "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                                     "WHERE NOT t.tgisinternal AND t.tgname = 'trg_audit_capture' "
                                     "AND (t.tgenabled <> 'O' OR (t.tgtype & 28) <> 28)")]
    assert not (set(weak) & AUDITED), f"an audit trigger is disabled or misses an event: {sorted(set(weak) & AUDITED)}"


# ── the probe ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_probe_says_the_role_and_the_header_the_database_saw(dsn):
    ok, out = _call(dsn, "service", "SELECT public.audit_actor_probe();", header="a-label-of-the-apis-own")
    assert ok, out
    assert json.loads(out) == {"role": "service_role", "header": "a-label-of-the-apis-own"}, out


def test_the_probe_says_nothing_was_seen_when_there_is_no_header_and_survives_headers_that_are_not_json(dsn):
    ok, out = _call(dsn, "service", "SELECT public.audit_actor_probe();")
    assert ok and json.loads(out) == {"role": "service_role", "header": None}, out
    ok, out = _call(dsn, "service", "SELECT set_config('request.headers', 'not json', false); SELECT public.audit_actor_probe();")
    assert ok and json.loads(out) == {"role": "service_role", "header": None}, out


def test_the_probe_is_closed_to_every_signed_in_role_and_open_to_the_service_role(dsn):
    acl = _acl(dsn, PROBE)
    assert acl["anon"] is False and acl["authenticated"] is False, acl
    assert _one(dsn, f"SELECT has_function_privilege('service_role', '{PROBE}'::regprocedure, 'EXECUTE')") == "t"
    ok, msg = _call(dsn, "manager_a", "SELECT public.audit_actor_probe();")
    assert not ok and "permission denied" in msg, msg
    assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{PROBE}'::regprocedure") == "f"
    assert "search_path=pg_catalog" in _text(dsn, f"SELECT coalesce(array_to_string(proconfig, '|'), '') FROM pg_proc WHERE oid = '{PROBE}'::regprocedure")


# ── the shape ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _acl(dsn: str, sig: str) -> dict[str, bool]:
    return {r: _one(dsn, f"SELECT has_function_privilege('{r}', '{sig}'::regprocedure, 'EXECUTE')") == "t"
            for r in ("anon", "authenticated")}


def test_the_reader_is_still_invoker_pinned_and_closed_to_everyone_signed_in(dsn):
    assert _one(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{READER}'::regprocedure") == "f"
    assert _one(dsn, f"SELECT provolatile FROM pg_proc WHERE oid = '{READER}'::regprocedure") == "s"
    assert "search_path=pg_catalog" in _text(dsn, f"SELECT coalesce(array_to_string(proconfig, '|'), '') FROM pg_proc WHERE oid = '{READER}'::regprocedure")
    acl = _acl(dsn, READER)
    assert acl["anon"] is False and acl["authenticated"] is False, acl
    ok, msg = _call(dsn, "manager_a", "SELECT public.carried_audit_actor();")
    assert not ok and "permission denied" in msg, msg


def test_the_reader_stays_closed_even_where_the_platform_grants_new_functions_to_the_signed_in(dsn):
    assert _psql(dsn, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;").returncode == 0
    assert _psql(dsn, f"DROP FUNCTION {READER}; DROP FUNCTION {PROBE};").returncode == 0
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for sig in (READER, PROBE):
        acl = _acl(dsn, sig)
        assert acl["anon"] is False and acl["authenticated"] is False, (sig, acl)


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
    """The highest-numbered migration before this one that defines the function (not a rollback), found by scanning the directory."""
    cands = sorted(p for p in MIGRATIONS.glob("*.sql")
                   if not p.name.endswith("_rollback.sql") and p.name < MIGRATION.name
                   and re.search(rf"CREATE (?:OR REPLACE )?FUNCTION\s+public\.{name}\s*\(", p.read_text()))
    return cands[-1]


# what 547 adds to 545's reader, as it reads once whitespace is folded and comments are gone
ADDED = [
    r" v_header text; v_actor uuid;",
    r"IF v_setting IS NULL THEN IF current_setting\('role', true\) = 'service_role' THEN BEGIN "
    r"v_header := nullif\(current_setting\('request\.headers', true\)::json ->> 'x-acting-auth-user', ''\); "
    r"EXCEPTION WHEN others THEN v_header := NULL; END; IF v_header IS NOT NULL THEN BEGIN v_actor := v_header::uuid; "
    r"EXCEPTION WHEN others THEN RETURN NULL; END; IF NOT EXISTS \(SELECT 1 FROM public\.users u WHERE u\.auth_user_id = v_actor\) THEN "
    r"RETURN NULL; END IF; RETURN v_actor; END IF; END IF; END IF; ",
]


def test_the_reader_is_migration_545s_plus_exactly_the_added_lines(dsn):
    assert _last_definer("carried_audit_actor").name.startswith("545_"), _last_definer("carried_audit_actor").name
    live = _norm(_text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure"))
    for pattern in ADDED:
        live, n = re.subn(pattern, "", live, count=1)
        assert n == 1, pattern
    assert live == _norm(_function_body(_last_definer("carried_audit_actor").read_text(), "carried_audit_actor"))


# ── the closing check, run alone after each spoiling ──────────────────────────────────────────────────────────────────
def _closing_block() -> str:
    text = MIGRATION.read_text()
    return text[text.rindex("DO $$"):]


def _ancestor_definition() -> str:
    text = _last_definer("carried_audit_actor").read_text()
    m = re.search(r"CREATE (?:OR REPLACE )?FUNCTION public\.carried_audit_actor\(.*?\n(\$\w*\$);", text, re.S)
    assert m
    return m.group(0)


SPOILS = [
    ("executable by a signed-in user", f"GRANT EXECUTE ON FUNCTION {READER} TO authenticated;"),
    ("executable by anon", f"GRANT EXECUTE ON FUNCTION {READER} TO anon;"),
    ("a definer", f"ALTER FUNCTION {READER} SECURITY DEFINER;"),
    ("545's definition back (the header is not read)", None),
    ("gone", f"DROP FUNCTION {READER} CASCADE;"),
    ("the probe executable by a signed-in user", f"GRANT EXECUTE ON FUNCTION {PROBE} TO authenticated;"),
    ("the probe executable by anon", f"GRANT EXECUTE ON FUNCTION {PROBE} TO anon;"),
    ("the probe closed to the service role", f"REVOKE EXECUTE ON FUNCTION {PROBE} FROM service_role;"),
    ("the reader volatile", f"ALTER FUNCTION {READER} VOLATILE;"),
    ("the reader's search path unpinned", f"ALTER FUNCTION {READER} RESET search_path;"),
    ("the probe a definer", f"ALTER FUNCTION {PROBE} SECURITY DEFINER;"),
    ("the probe volatile", f"ALTER FUNCTION {PROBE} VOLATILE;"),
    ("the probe's search path unpinned", f"ALTER FUNCTION {PROBE} RESET search_path;"),
]


@pytest.mark.parametrize("label,spoil", SPOILS, ids=[s[0] for s in SPOILS])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(dsn, label, spoil):
    assert _psql(dsn, _closing_block()).returncode == 0, "the closing check should pass on the migrated database"
    if spoil is None:
        spoil = _ancestor_definition()
    assert _psql(dsn, spoil).returncode == 0, label
    r = _psql(dsn, _closing_block())
    assert r.returncode != 0 and ("migration 547" in r.stderr or "does not exist" in r.stderr), (label, r.stderr)


# ── the rollback and the re-apply ─────────────────────────────────────────────────────────────────────────────────────
def test_the_rollback_restores_545s_definition_and_the_header_is_ignored_and_a_reapply_brings_it_back(dsn):
    before = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure")
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    live = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure")
    assert "x-acting-auth-user" not in live
    assert _one(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'audit_actor_probe'") == "0"
    assert _norm(live) == _norm(_function_body(_last_definer("carried_audit_actor").read_text(), "carried_audit_actor"))
    ok, out = _call(dsn, "service", RENAME, header=PEOPLE["manager_a"][1])
    assert ok, out
    assert _audit(dsn, "entity_type = 'customer'") == [], "after the rollback the header is not read"
    _changed(dsn)
    acl = _acl(dsn, READER)
    assert acl["anon"] is False and acl["authenticated"] is False
    assert _psql_file(dsn, MIGRATION).returncode == 0
    ok, out = _call(dsn, "service", RENAME, header=PEOPLE["manager_a"][1])
    assert ok, out
    assert [r[2] for r in _audit(dsn, "entity_type = 'customer'")] == [PEOPLE["manager_a"][1]]
    _changed(dsn)
    assert _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure") == before


def test_applying_it_twice_changes_nothing(dsn):
    before = _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure")
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _text(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{READER}'::regprocedure") == before

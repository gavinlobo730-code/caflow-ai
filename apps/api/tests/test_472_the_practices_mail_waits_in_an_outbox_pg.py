"""Migration 472 on real PostgreSQL — the practice's mail waits in an outbox and a bounce marks the address (ops-21).

WHAT IS PROVEN HERE
    * the two tables have exactly the columns the service writes — and none that could hold what a
      message said once it is over beyond the two blanked ones, or a provider's message;
    * the constraints: a status outside the vocabulary, a recipient kind that is not staff or a client's
      own contact (a client's CUSTOMER cannot be stored), a delivery event other than bounced or
      complained, an attempt count below zero, a `max_attempts` outside 1..20, and an un-lowercased
      suppression address are all refused; deleting a firm removes its outbox rows and deleting a user
      keeps the row and forgets who;
    * `claim_email_outbox` hands out due rows once: a pending row is claimed and its `attempts` raised, a
      row due later is not, a row another drainer holds under a live lease is not, a row whose lease has
      expired is handed out again with another attempt spent, the oldest comes first, the batch is
      honoured and a batch or lease outside its range is refused;
    * TWO DRAINERS RACING get DISJOINT rows. Each psql session opens a transaction, claims, holds the
      transaction open for a second and a half and commits, so the second is genuinely running while the
      first still holds its row locks — which is the only way FOR UPDATE SKIP LOCKED is exercised;
    * the tables and the function are the service role's alone: RLS is on with no policy, `anon` and
      `authenticated` hold no privilege on either table and no EXECUTE on the function;
    * the service's INSERT and UPDATE payloads (read from SOURCE) name only columns the tables have.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

API = Path(__file__).resolve().parents[1]
FIRM = "47200000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "47200000-0000-0000-0000-0000000000f2"
USER = "47200000-0000-0000-0000-00000000b001"

OUTBOX_COLUMNS = {
    "id", "firm_id", "origin", "event_type", "recipient_kind", "recipient_user_id", "to_address",
    "subject", "html", "sender_name", "reply_to", "status", "attempts", "max_attempts",
    "next_attempt_at", "lease_expires_at", "last_attempt_at", "sent_at", "provider_message_id",
    "last_status_code", "last_error_code", "final_reason", "delivery_event", "delivery_event_at",
    "log_ids", "created_at", "updated_at",
}
SUPPRESSION_COLUMNS = {"address", "reason", "provider_message_id", "first_event_at", "last_event_at"}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _as_role(dsn: str, role: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET ROLE {role}; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m472_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('47200000-0000-0000-0000-00000000a001', 'p@t.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}', 'F1', 'f1@t.in'), ('{OTHER_FIRM}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{USER}', '{FIRM}', '47200000-0000-0000-0000-00000000a001', 'p@t.in', 'Partner', 'Partner', true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _row(firm=FIRM, to="a@x.test", **over) -> str:
    cols = {"firm_id": f"'{firm}'", "origin": "'practice_notice'", "event_type": "'task_assigned'",
            "to_address": f"'{to}'", "subject": "'s'", "html": "'<p>h</p>'"}
    cols.update({k: str(v) for k, v in over.items()})
    return (f"INSERT INTO public.email_outbox ({', '.join(cols)}) "
            f"VALUES ({', '.join(cols.values())});")


def _claim(dsn, limit=5, lease=300) -> list[dict]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
                        f"SELECT to_jsonb(c) FROM public.claim_email_outbox({limit}, {lease}) c;"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]


# ── the shape ────────────────────────────────────────────────────────────────

def test_the_outbox_has_exactly_the_columns_the_service_writes(db):
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='email_outbox';").split(","))
    assert got == OUTBOX_COLUMNS


def test_the_suppression_list_has_no_firm_and_no_client(db):
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='email_suppressions';").split(","))
    assert got == SUPPRESSION_COLUMNS
    assert "client_id" not in OUTBOX_COLUMNS, "the outbox must not fall under the assignment-scope rule"


def test_the_free_text_columns_of_the_outbox_are_known(db):
    """What could hold a sentence is what has type text. subject and html hold a message while it waits and
    are blanked once it is over; the rest are addresses, labels and short codes."""
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='email_outbox' "
                          "AND data_type = 'text';").split(","))
    assert got == {"origin", "event_type", "recipient_kind", "to_address", "subject", "html",
                   "sender_name", "reply_to", "status", "provider_message_id", "last_error_code",
                   "final_reason", "delivery_event"}


def test_a_minimal_row_inserts_pending_with_its_defaults(db):
    assert _psql(db, _row()).returncode == 0
    assert _scalar(db, "SELECT status || ',' || attempts || ',' || max_attempts || ',' || recipient_kind "
                       "|| ',' || (next_attempt_at IS NOT NULL) || ',' || coalesce(array_length(log_ids,1),0) "
                       "FROM public.email_outbox;") == "pending,0,6,staff,true,0"


@pytest.mark.parametrize("bad", [
    {"status": "'queued'"}, {"recipient_kind": "'client_customer'"}, {"recipient_kind": "'customer'"},
    {"delivery_event": "'opened'"}, {"attempts": -1}, {"max_attempts": 0}, {"max_attempts": 21},
])
def test_a_value_outside_the_vocabulary_is_refused(db, bad):
    r = _psql(db, _row(**bad))
    assert r.returncode != 0 and "violates check constraint" in r.stderr, bad


@pytest.mark.parametrize("ok", [
    {"status": "'sent'"}, {"status": "'failed'"}, {"status": "'cancelled'"}, {"status": "'suppressed'"},
    {"recipient_kind": "'client_contact'"}, {"delivery_event": "'bounced'"},
    {"delivery_event": "'complained'"}, {"max_attempts": 20},
])
def test_the_values_the_service_uses_are_accepted(db, ok):
    r = _psql(db, _row(**ok))
    assert r.returncode == 0, r.stderr


def test_an_outbox_row_needs_a_firm_that_exists(db):
    r = _psql(db, _row(firm="47200000-0000-0000-0000-0000000000ff"))
    assert r.returncode != 0 and "foreign key" in r.stderr


def test_deleting_a_firm_removes_its_outbox_rows(db):
    assert _psql(db, _row(firm=OTHER_FIRM)).returncode == 0
    assert _psql(db, "DELETE FROM firms WHERE id = '" + OTHER_FIRM + "';").returncode == 0
    assert _scalar(db, "SELECT count(*) FROM public.email_outbox;") == "0"


def test_deleting_a_user_keeps_the_row_and_forgets_who(db):
    assert _psql(db, _row(recipient_user_id=f"'{USER}'")).returncode == 0
    assert _psql(db, f"DELETE FROM users WHERE id = '{USER}';").returncode == 0
    assert _scalar(db, "SELECT count(*) || ',' || (recipient_user_id IS NULL) FROM public.email_outbox "
                       "GROUP BY recipient_user_id;") == "1,true"


def test_a_suppressed_address_is_stored_in_lower_case_only(db):
    assert _psql(db, "INSERT INTO public.email_suppressions (address, reason) "
                     "VALUES ('Priya@Gupta-CA.in', 'hard_bounce');").returncode != 0
    assert _psql(db, "INSERT INTO public.email_suppressions (address, reason) "
                     "VALUES ('priya@gupta-ca.in', 'hard_bounce');").returncode == 0
    assert _psql(db, "INSERT INTO public.email_suppressions (address, reason) "
                     "VALUES ('priya@gupta-ca.in', 'complaint');").returncode != 0, "one row per address"
    assert _psql(db, "INSERT INTO public.email_suppressions (address, reason) "
                     "VALUES ('b@x.test', 'unsubscribed');").returncode != 0


# ── the claim ────────────────────────────────────────────────────────────────

def test_a_due_pending_row_is_claimed_once_and_costs_an_attempt(db):
    assert _psql(db, _row()).returncode == 0
    first = _claim(db)
    assert len(first) == 1
    assert (first[0]["status"], first[0]["attempts"]) == ("sending", 1)
    assert first[0]["lease_expires_at"] is not None and first[0]["last_attempt_at"] is not None
    assert _claim(db) == [], "a row held under a live lease is not handed out again"


def test_a_row_due_later_is_not_claimed(db):
    assert _psql(db, _row(next_attempt_at="now() + interval '10 minutes'")).returncode == 0
    assert _claim(db) == []


def test_a_row_whose_lease_has_expired_is_handed_out_again_with_another_attempt_spent(db):
    assert _psql(db, _row()).returncode == 0
    assert len(_claim(db)) == 1
    assert _psql(db, "UPDATE public.email_outbox SET lease_expires_at = now() - interval '1 second';").returncode == 0
    again = _claim(db)
    assert len(again) == 1 and again[0]["attempts"] == 2


@pytest.mark.parametrize("status", ["sent", "failed", "cancelled", "suppressed"])
def test_a_finished_row_is_never_claimed(db, status):
    assert _psql(db, _row(status=f"'{status}'")).returncode == 0
    assert _claim(db) == []


def test_the_oldest_due_row_comes_first_and_the_batch_is_honoured(db):
    for i, ago in enumerate((5, 30, 10, 20)):
        assert _psql(db, _row(to=f"u{i}@x.test", next_attempt_at=f"now() - interval '{ago} minutes'")).returncode == 0
    got = _claim(db, limit=2)
    assert [r["to_address"] for r in got] == ["u1@x.test", "u3@x.test"]
    assert _scalar(db, "SELECT count(*) FROM public.email_outbox WHERE status = 'pending';") == "2"


@pytest.mark.parametrize("limit,lease", [(0, 300), (201, 300), (5, 29), (5, 3601)])
def test_a_batch_or_lease_outside_its_range_is_refused(db, limit, lease):
    r = _psql(db, f"SELECT * FROM public.claim_email_outbox({limit}, {lease});")
    assert r.returncode != 0 and ("batch" in r.stderr or "lease" in r.stderr)


def test_two_drainers_racing_get_disjoint_rows(db):
    for i in range(10):
        assert _psql(db, _row(to=f"u{i}@x.test")).returncode == 0
    procs = []
    for _ in range(2):
        script = ("BEGIN;\nSELECT to_jsonb(c) FROM public.claim_email_outbox(6, 300) c;\n"
                  "SELECT pg_sleep(1.5);\nCOMMIT;\n")
        p = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-f", "-"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p.stdin.write(script)
        p.stdin.close()
        procs.append(p)
    claimed: list[set[str]] = []
    for p in procs:
        out, err = p.stdout.read(), p.stderr.read()
        p.wait(timeout=60)
        assert p.returncode == 0, err
        claimed.append({json.loads(l)["id"] for l in out.splitlines() if l.startswith("{")})
    assert claimed[0].isdisjoint(claimed[1]), "two drainers were handed the same message"
    # The two claims start together, so how the ten rows split is the interleaving's to decide: 6/4
    # when one locks all it wants first, 5/5 when they take alternate rows (a CI run of 2 Oct 2026 saw
    # 5/5 and failed an exact [4, 6]). What SKIP LOCKED guarantees, and so what is asserted, is that
    # nothing is handed out twice, nothing is left behind, and neither passes its own batch of six;
    # a drainer that skipped nothing would have taken rows the other held and shown up in the first line.
    assert len(claimed[0] | claimed[1]) == 10 and all(len(c) <= 6 for c in claimed), (
        "SKIP LOCKED must give the second drainer what the first did not take, not make it wait for it")
    assert _scalar(db, "SELECT count(*) FROM public.email_outbox WHERE status = 'sending' AND attempts = 1;") == "10"


# ── who can touch it ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["email_outbox", "email_suppressions"])
def test_rls_is_on_with_no_policy(db, table):
    assert _scalar(db, f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{table}'::regclass;") == "t"
    assert _scalar(db, f"SELECT count(*) FROM pg_policy WHERE polrelid = 'public.{table}'::regclass;") == "0"


@pytest.mark.parametrize("table", ["email_outbox", "email_suppressions"])
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_a_browser_role_has_no_privilege_on_either_table(db, table, role):
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _scalar(db, f"SELECT has_table_privilege('{role}', 'public.{table}', '{priv}');") == "f", (table, role, priv)
    r = _as_role(db, role, f"SELECT count(*) FROM public.{table};")
    assert r.returncode != 0 and "permission denied" in r.stderr


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_a_browser_role_cannot_execute_the_claim(db, role):
    assert _scalar(db, f"SELECT has_function_privilege('{role}', 'public.claim_email_outbox(integer, integer)', 'EXECUTE');") == "f"


def test_the_service_role_can_claim_and_write(db):
    assert _scalar(db, "SELECT has_function_privilege('service_role', 'public.claim_email_outbox(integer, integer)', 'EXECUTE');") == "t"
    r = _as_role(db, "service_role", _row())
    assert r.returncode == 0, r.stderr
    r = _as_role(db, "service_role", "SELECT count(*) FROM public.claim_email_outbox(5, 300);")
    assert r.returncode == 0, r.stderr


# ── the writer and the schema cannot drift apart ─────────────────────────────

def _literal_keys(method: str) -> set[str]:
    src = (API / "services" / "email_outbox_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PostgrestOutboxStore")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("insert", "update"):
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    keys |= {k.value for k in arg.keys if isinstance(k, ast.Constant)}
    return keys


@pytest.mark.parametrize("method,table,columns", [
    ("insert", "email_outbox", OUTBOX_COLUMNS),
    ("mark_sent", "email_outbox", OUTBOX_COLUMNS),
    ("mark_retry", "email_outbox", OUTBOX_COLUMNS),
    ("mark_final", "email_outbox", OUTBOX_COLUMNS),
    ("set_delivery_event", "email_outbox", OUTBOX_COLUMNS),
    ("suppress", "email_suppressions", SUPPRESSION_COLUMNS),
])
def test_the_services_payloads_name_only_columns_the_tables_have(method, table, columns):
    keys = _literal_keys(method)
    assert keys, f"{method}: the scan found no payload keys, so it would pass vacuously"
    assert keys <= columns, sorted(keys - columns)

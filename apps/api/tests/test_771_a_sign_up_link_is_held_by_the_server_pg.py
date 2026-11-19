"""Migration 771 — a sign-up link is held by the server (POST-A-485, 497).

`public.signup_links` keeps, for each address that asked to start a practice, the HASH of the mailed link's secret, the firm name and the
person's name typed on the sign-up form, and when the link stops working. Proved against real PostgreSQL because the mock suite cannot tell
whether a CHECK bites, whether the unique index makes the second of two first requests lose, whether the statement a later request sends
(an UPDATE naming the address AND the link it read) changes no row once somebody else has written, or who may touch the table. The
statements below are the ones `repositories/signup_link_repository` sends, not the ones a first draft assumed: the "press deletes the
row" and "ON CONFLICT ... send_count + 1" tests that stood here exercised statements the product never issues, and passed vacuously.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
FORWARD = API_ROOT / "migrations" / "771_a_sign_up_link_is_held_by_the_server.sql"
ROLLBACK = API_ROOT / "migrations" / "771_a_sign_up_link_is_held_by_the_server_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 771 proof requires HARNESS_PG + psql",
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m771_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert FORWARD.name not in pg_template.failed, "migration 771 did not apply: everything below would pass vacuously"
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _link(email: str = "new.owner@example.in", firm: str = "Acme & Co", name: str = "A Partner", token: str = HASH_A, send_count: int = 1) -> str:
    return (f"INSERT INTO public.signup_links (email, firm_name, full_name, token_hash, expires_at, send_count) "
            f"VALUES ('{email}', '{firm}', '{name}', '{token}', now() + interval '1 day', {send_count});")


def test_the_columns_exist_with_their_types_and_nullability(db):
    out = _psql(db, "SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' ORDER BY column_name) "
                    "FROM information_schema.columns WHERE table_schema='public' AND table_name='signup_links';", tuples=True)
    assert out.stdout.strip() == (
        "created_at:timestamp with time zone:NO,email:text:NO,expires_at:timestamp with time zone:NO,firm_name:text:NO,"
        "full_name:text:NO,id:uuid:NO,send_count:integer:NO,sent_at:timestamp with time zone:NO,token_hash:text:NO,"
        "window_started_at:timestamp with time zone:NO")


def test_a_link_inserts_and_reads_back(db):
    assert _psql(db, _link()).returncode == 0
    row = _psql(db, "SELECT email || '|' || firm_name || '|' || full_name || '|' || send_count FROM public.signup_links;", tuples=True)
    assert row.stdout.strip() == "new.owner@example.in|Acme & Co|A Partner|1"


@pytest.mark.parametrize("what, sql", [
    ("an address with a capital", _link(email="New.Owner@example.in")),
    ("an address with spaces round it", _link(email=" new.owner@example.in ")),
    ("a blank address", _link(email="")),
    ("a blank firm name", _link(firm="   ")),
    ("a blank person's name", _link(name="")),
    ("a token that is not a hash", _link(token="plain-secret-in-the-clear")),
    ("a send count of zero", _link(send_count=0)),
])
def test_the_database_refuses_what_the_table_is_not_for(db, what, sql):
    refused = _psql(db, sql)
    assert refused.returncode != 0, f"{what} was accepted"
    assert "violates check constraint" in refused.stderr, refused.stderr


def test_one_row_per_address_and_one_row_per_secret(db):
    assert _psql(db, _link()).returncode == 0
    same_address = _psql(db, _link(token=HASH_B))
    assert same_address.returncode != 0 and "uq_signup_links_one_per_address" in same_address.stderr
    same_secret = _psql(db, _link(email="someone.else@example.in"))
    assert same_secret.returncode != 0 and "uq_signup_links_token_hash" in same_secret.stderr


def _claim_update(token_read: str, token_written: str, send_count: int) -> str:
    """The statement `claim` sends for a later request: it names the address AND the link the request read, so it writes only while
    nobody has written since."""
    return ("UPDATE public.signup_links SET firm_name = 'Acme & Co (again)', full_name = 'A Partner', "
            f"token_hash = '{token_written}', expires_at = now() + interval '1 day', sent_at = now(), send_count = {send_count}, "
            "window_started_at = now(), created_at = now() "
            f"WHERE email = 'new.owner@example.in' AND token_hash = '{token_read}' RETURNING send_count;")


def _hold(dsn: str, sql: str, seconds: int) -> subprocess.Popen:
    """A session that runs `sql` inside a transaction and keeps it open for `seconds`, holding whatever it locked."""
    return subprocess.Popen(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", f"BEGIN; {sql} SELECT pg_sleep({seconds}); COMMIT;"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _wait_until_it_holds_its_lock(dsn: str) -> None:
    for _ in range(150):
        n = _psql(dsn, "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'active' "
                       "AND query LIKE '%pg_sleep%' AND pid <> pg_backend_pid();", tuples=True).stdout.strip()
        if n == "1":
            return
        time.sleep(0.1)
    raise AssertionError("the first session never reached the point where it holds its lock")


def test_a_later_request_replaces_the_row_only_while_it_still_holds_the_link_that_was_read(db):
    assert _psql(db, _link()).returncode == 0
    won = _psql(db, _claim_update(HASH_A, HASH_B, 2), tuples=True)
    assert won.returncode == 0 and won.stdout.strip() == "2"
    # A second request that read the row before the first wrote it still names the old link: it changes no row.
    lost = _psql(db, _claim_update(HASH_A, HASH_C, 2), tuples=True)
    assert lost.returncode == 0 and lost.stdout.strip() == "", "a request that read an older row won"
    rows = _psql(db, "SELECT count(*) || '|' || max(token_hash) || '|' || max(send_count) || '|' || max(firm_name) FROM public.signup_links;", tuples=True)
    assert rows.stdout.strip() == f"1|{HASH_B}|2|Acme & Co (again)"
    # The first secret no longer names a row: pressing the button with the old link finds nothing.
    old = _psql(db, f"SELECT count(*) FROM public.signup_links WHERE token_hash = '{HASH_A}';", tuples=True)
    assert old.stdout.strip() == "0"


def test_two_requests_that_overlap_cannot_both_be_let_through(db):
    """The reason the claim is a compare-and-set: while the first request's write is open, the second blocks on the row, and when the
    first commits the second finds the link it read is gone and writes nothing, so it is refused by the cooldown on its next read."""
    assert _psql(db, _link()).returncode == 0
    first = _hold(db, _claim_update(HASH_A, HASH_B, 2), 3)
    try:
        _wait_until_it_holds_its_lock(db)
        began = time.monotonic()
        second = _psql(db, _claim_update(HASH_A, HASH_C, 2), tuples=True)
        waited = time.monotonic() - began
    finally:
        _out, err = first.communicate(timeout=60)
    assert first.returncode == 0, err
    assert second.returncode == 0 and second.stdout.strip() == "", "both overlapping requests wrote"
    assert waited > 0.5, f"the second request did not wait for the first's lock ({waited:.2f}s): the test did not overlap them"
    assert _psql(db, "SELECT token_hash FROM public.signup_links;", tuples=True).stdout.strip() == HASH_B


def test_two_first_requests_for_one_address_cannot_both_insert(db):
    first = _hold(db, _link(token=HASH_A), 3)
    try:
        _wait_until_it_holds_its_lock(db)
        second = _psql(db, _link(token=HASH_B))
    finally:
        _out, err = first.communicate(timeout=60)
    assert first.returncode == 0, err
    assert second.returncode != 0 and "uq_signup_links_one_per_address" in second.stderr and "duplicate key" in second.stderr, second.stderr
    assert _psql(db, "SELECT token_hash FROM public.signup_links;", tuples=True).stdout.strip() == HASH_A


def _put_back(replacing: str, token: str = HASH_A, send_count: int = 1) -> str:
    """The statement `put_back` sends for a mail that did not go, when there was an earlier row: it names the link THIS request wrote."""
    return ("UPDATE public.signup_links SET firm_name = 'Acme & Co', full_name = 'A Partner', "
            f"token_hash = '{token}', expires_at = now() + interval '1 day', sent_at = now(), send_count = {send_count}, "
            "window_started_at = now(), created_at = now() "
            f"WHERE email = 'new.owner@example.in' AND token_hash = '{replacing}' RETURNING send_count;")


def test_a_link_whose_mail_did_not_go_is_put_back_only_while_it_is_the_one_this_request_wrote(db):
    assert _psql(db, _link()).returncode == 0
    assert _psql(db, _claim_update(HASH_A, HASH_B, 2)).returncode == 0                  # this request wrote HASH_B
    assert _psql(db, _claim_update(HASH_B, HASH_C, 3)).returncode == 0                  # a newer request has since replaced it
    undone = _psql(db, _put_back(replacing=HASH_B), tuples=True)
    assert undone.returncode == 0 and undone.stdout.strip() == "", "a failed mail undid a newer request's link"
    assert _psql(db, "SELECT token_hash || '|' || send_count FROM public.signup_links;", tuples=True).stdout.strip() == f"{HASH_C}|3"
    # While the row still holds this request's own link, the earlier one comes back.
    assert _psql(db, _put_back(replacing=HASH_C), tuples=True).stdout.strip() == "1"
    assert _psql(db, "SELECT token_hash || '|' || send_count FROM public.signup_links;", tuples=True).stdout.strip() == f"{HASH_A}|1"


def test_a_first_link_whose_mail_did_not_go_is_removed_only_while_it_is_the_one_this_request_wrote(db):
    assert _psql(db, _link(token=HASH_B)).returncode == 0
    gone = ("DELETE FROM public.signup_links WHERE email = 'new.owner@example.in' AND token_hash = '{h}' RETURNING email;")
    assert _psql(db, gone.format(h=HASH_A), tuples=True).stdout.strip() == "", "removed a link the request did not write"
    assert _psql(db, gone.format(h=HASH_B), tuples=True).stdout.strip() == "new.owner@example.in"
    assert _psql(db, "SELECT count(*) FROM public.signup_links;", tuples=True).stdout.strip() == "0"


def test_creating_the_practice_deletes_that_addresss_row_and_no_other(db):
    assert _psql(db, _link()).returncode == 0
    assert _psql(db, _link(email="someone.else@example.in", token=HASH_B)).returncode == 0
    forgotten = _psql(db, "DELETE FROM public.signup_links WHERE email = 'new.owner@example.in' RETURNING email;", tuples=True)
    assert forgotten.stdout.strip() == "new.owner@example.in"
    assert _psql(db, "SELECT email FROM public.signup_links;", tuples=True).stdout.strip() == "someone.else@example.in"


def test_the_sweep_removes_what_has_expired_and_leaves_what_is_live(db):
    assert _psql(db, _link(token=HASH_A)).returncode == 0
    assert _psql(db, f"INSERT INTO public.signup_links (email, firm_name, full_name, token_hash, expires_at) "
                     f"VALUES ('late@example.in', 'F', 'N', '{HASH_B}', now() - interval '1 minute');").returncode == 0
    swept = _psql(db, "DELETE FROM public.signup_links WHERE expires_at < now() RETURNING email;", tuples=True)
    assert swept.stdout.strip() == "late@example.in"
    assert _psql(db, "SELECT email FROM public.signup_links;", tuples=True).stdout.strip() == "new.owner@example.in"


@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_or_signed_out_browser_can_neither_read_nor_write_it(db, role):
    assert _psql(db, _link()).returncode == 0
    for sql in ("SELECT count(*) FROM public.signup_links;",
                _link(email="x@example.in", token=HASH_B),
                "UPDATE public.signup_links SET firm_name = 'Taken over';",
                "DELETE FROM public.signup_links;"):
        refused = _psql(db, f"SET ROLE {role}; {sql}")
        assert refused.returncode != 0 and "permission denied" in refused.stderr, f"{role} ran: {sql}\n{refused.stderr}"


def test_only_the_privileged_api_client_reads_and_writes_it(db):
    ok = _psql(db, f"SET ROLE service_role; {_link()} SELECT count(*) FROM public.signup_links; "
                   "UPDATE public.signup_links SET send_count = 2; DELETE FROM public.signup_links;")
    assert ok.returncode == 0, ok.stderr


def test_row_security_is_on_and_there_is_no_policy_to_widen_it(db):
    on = _psql(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.signup_links'::regclass;", tuples=True)
    assert on.stdout.strip() == "t"
    policies = _psql(db, "SELECT count(*) FROM pg_policy WHERE polrelid = 'public.signup_links'::regclass;", tuples=True)
    assert policies.stdout.strip() == "0"


def test_the_comments_say_the_secret_is_never_stored(db):
    out = _psql(db, "SELECT obj_description('public.signup_links'::regclass, 'pg_class') || ' | ' || "
                    "col_description('public.signup_links'::regclass, (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.signup_links'::regclass AND attname = 'token_hash'));",
                tuples=True)
    assert "API only" in out.stdout and "never stored" in out.stdout
    assert "uses nothing up" in out.stdout, "the comment must not say the press consumes the link: it does not"
    assert "deletes the row" not in out.stdout.replace("row is deleted", ""), out.stdout


def test_the_migration_can_run_twice(db):
    assert _psql(db, _link()).returncode == 0
    assert _psql_file(db, FORWARD).returncode == 0
    assert _psql(db, "SELECT count(*) FROM public.signup_links;", tuples=True).stdout.strip() == "1", "re-running the migration lost a row"


def test_the_rollback_drops_the_table_and_the_migration_comes_back(db):
    assert _psql_file(db, ROLLBACK).returncode == 0
    gone = _psql(db, "SELECT to_regclass('public.signup_links') IS NULL;", tuples=True)
    assert gone.stdout.strip() == "t"
    assert _psql_file(db, FORWARD).returncode == 0
    assert _psql(db, "SELECT to_regclass('public.signup_links') IS NOT NULL;", tuples=True).stdout.strip() == "t"

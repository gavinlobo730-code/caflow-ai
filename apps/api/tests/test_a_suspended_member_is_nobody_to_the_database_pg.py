"""Migrations 468 and 469 — a suspended or signed-out member is NOBODY to the
database, and a stored file opens only for the staff assigned to its client.

THE BUG THIS PINS (security_privacy-01 and -03)
    `suspend_user` and `force_logout` write `users.is_active` and
    `users.sessions_revoked_at`; one reader looked at either — core/auth.py, on
    the FastAPI path. The browser reads ~83 tables over PostgREST and lists,
    reads and deletes files through Storage, and all of that is authorised by
    RLS, whose helpers selected the caller's `users` row and tested nothing
    else. A dismissed member's JWT went on reading every client's books and
    files, and the refresh token went on minting new ones. Separately the
    Documents bucket asked only for the firm folder, so ANY member could open,
    overwrite or delete ANY client's files regardless of assignment or role.

WHAT IS ASSERTED, AND WHY EACH IS A DATABASE FACT
    * the three helpers answer NULL for a session that is not live, in each of
      the five ways a session can fail to be (inactive, revoked and older,
      revoked with no readable `iat`, a number that is not a number) and answer
      for it in each of the ways it is (no revocation; `iat` equal to or after
      it; reactivated);
    * a real table, read as the member, goes dark and comes back — the helper's
      answer is not the claim, the ROWS are;
    * the two functions that used to read `users` themselves —
      `can_access_client` and `my_permission` — no longer rescue a suspended
      member through an assignment row or a `granted = true` grid row;
    * ONE RULE OVER THE WHOLE CATALOGUE: no RLS policy selects from `users`, and
      no function in `public` does except the ones named here with their reason.
      A list of the two that were found would pass the day a third is written;
    * Storage, evaluated as `supabase_storage_admin` AND as `authenticated`:
      assigned vs unassigned vs Partner, read, write and delete, the other
      firm's folder, the year-end bucket, a suspended member, and — the grant
      the incident in migration 204 is about — that the policies are executable
      by the role storage-api actually connects as.

NEGATIVE CONTROLS (run by hand when written; the failures are what each
assertion exists to catch)
    Revert 468 to 019/073/079's bodies and the `suspended`, `revoked` and
    `grant-does-not-rescue` tests fail while the `live` ones still pass. Revert
    469 to 005's policies and the unassigned-read, unassigned-delete and
    non-Partner-delete tests fail. Drop 469's `GRANT ... TO
    supabase_storage_admin` and every storage test fails with "permission
    denied for function my_permission".

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="the session-liveness and storage proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000468"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000469"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a468"   # the Executive is assigned here
CLIENT_B = "cccccccc-0000-0000-0000-00000000b468"   # ... and NOT here

AUTH_PARTNER = "11111111-1111-1111-1111-111111111468"
AUTH_EXEC = "22222222-2222-2222-2222-222222222468"
AUTH_REVIEWER = "33333333-3333-3333-3333-333333333468"
USER_PARTNER = "bbbbbbbb-0000-0000-0000-00000000a468"
USER_EXEC = "bbbbbbbb-0000-0000-0000-00000000b468"
USER_REVIEWER = "bbbbbbbb-0000-0000-0000-00000000c468"

#: The moment a revocation is stamped, as seconds since the epoch.
REVOKED_AT = 2_000_000_000


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA", "-F", "|"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _claims(auth_user_id: str, iat=None, role: str = "authenticated") -> str:
    parts = [f'"sub": "{auth_user_id}"', f'"role": "{role}"']
    if iat is not None:
        parts.append(f'"iat": {iat}' if isinstance(iat, (int, float)) else f'"iat": "{iat}"')
    return "{" + ", ".join(parts) + "}"


def _as(auth_user_id: str, iat=None, pg_role: str = "authenticated") -> str:
    return (f"SET request.jwt.claims = '{_claims(auth_user_id, iat)}'; "
            f"SET ROLE {pg_role}; ")


@pytest.fixture()
def db(pg_template):
    """One firm, two clients, three staff — a Partner, an Executive assigned to
    client A only, and a Reviewer — plus a file under each client's folder."""
    admin = _ADMIN.strip()
    dbname = f"m468_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_PARTNER}','p468@test.in'),
              ('{AUTH_EXEC}','e468@test.in'),
              ('{AUTH_REVIEWER}','r468@test.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M468 Firm','m468@test.in'),
              ('{OTHER_FIRM}','M468 Other Firm','m468o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) VALUES
              ('{USER_PARTNER}', '{FIRM}','{AUTH_PARTNER}', 'p468@test.in','Partner 468','Partner'),
              ('{USER_EXEC}',    '{FIRM}','{AUTH_EXEC}',    'e468@test.in','Exec 468','Executive'),
              ('{USER_REVIEWER}','{FIRM}','{AUTH_REVIEWER}','r468@test.in','Reviewer 468','Reviewer');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A 468','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B 468','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
              ('{FIRM}','{USER_EXEC}','{CLIENT_A}'),
              ('{FIRM}','{USER_REVIEWER}','{CLIENT_A}');

            -- storage-api connects as supabase_storage_admin and the bootstrap
            -- stub gives that role nothing; real Supabase owns these objects.
            ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
            GRANT USAGE ON SCHEMA storage, auth, public TO supabase_storage_admin;
            GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects
              TO authenticated, supabase_storage_admin;
            GRANT SELECT ON storage.buckets TO authenticated, supabase_storage_admin;
            INSERT INTO storage.buckets (id, name, public)
              VALUES ('year-end-exports','year-end-exports', false) ON CONFLICT DO NOTHING;
            INSERT INTO storage.objects (bucket_id, name) VALUES
              ('Documents',        '{FIRM}/{CLIENT_A}/vault/a.pdf'),
              ('Documents',        '{FIRM}/{CLIENT_B}/vault/b.pdf'),
              ('Documents',        '{OTHER_FIRM}/{CLIENT_A}/vault/foreign.pdf'),
              ('year-end-exports', '{FIRM}/{CLIENT_A}/2025-26/pack-a.pdf'),
              ('year-end-exports', '{FIRM}/{CLIENT_B}/2025-26/pack-b.pdf');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _helpers(dsn: str, auth: str, iat=None) -> tuple[str, str, str]:
    row = _ok(dsn, _as(auth, iat) +
              "SELECT coalesce(public.get_my_firm_id()::text,'-'), "
              "coalesce(public.get_my_role(),'-'), "
              "coalesce(public.get_my_user_id()::text,'-');")
    firm, role, uid = row.split("|")
    return firm, role, uid


def _suspend(dsn: str, user_id: str) -> None:
    _ok(dsn, f"UPDATE users SET is_active = false WHERE id = '{user_id}';")


def _reactivate(dsn: str, user_id: str) -> None:
    _ok(dsn, f"UPDATE users SET is_active = true WHERE id = '{user_id}';")


def _revoke(dsn: str, user_id: str, at: int = REVOKED_AT) -> None:
    _ok(dsn, f"UPDATE users SET sessions_revoked_at = to_timestamp({at}) "
             f"WHERE id = '{user_id}';")


NOBODY = ("-", "-", "-")


# ── the three helpers ────────────────────────────────────────────────────────
def test_a_live_member_is_somebody(db):
    """The premise: with nothing recorded against them every helper answers —
    including with a JWT that carries no `iat` at all, which is every token the
    other real-Postgres tests in this directory present."""
    assert _helpers(db, AUTH_EXEC) == (FIRM, "Executive", USER_EXEC)
    assert _helpers(db, AUTH_EXEC, iat=1) == (FIRM, "Executive", USER_EXEC)


def test_a_suspended_member_is_nobody(db):
    _suspend(db, USER_EXEC)
    assert _helpers(db, AUTH_EXEC, iat=REVOKED_AT + 10) == NOBODY
    # ... and only that member: the rule is about a person, not the firm.
    assert _helpers(db, AUTH_PARTNER) == (FIRM, "Partner", USER_PARTNER)


def test_reactivation_gives_the_member_back(db):
    _suspend(db, USER_EXEC)
    assert _helpers(db, AUTH_EXEC) == NOBODY
    _reactivate(db, USER_EXEC)
    assert _helpers(db, AUTH_EXEC) == (FIRM, "Executive", USER_EXEC)


def test_a_null_is_active_reads_as_active(db):
    """core/auth.py refuses only `is_active is False`, so a row that predates
    the column — NULL — must keep working, here as there."""
    _ok(db, f"ALTER TABLE users ALTER COLUMN is_active DROP NOT NULL; "
            f"UPDATE users SET is_active = NULL WHERE id = '{USER_EXEC}';")
    assert _helpers(db, AUTH_EXEC) == (FIRM, "Executive", USER_EXEC)


@pytest.mark.parametrize("iat,live,why", [
    (REVOKED_AT - 1,        False, "issued BEFORE the revocation"),
    (REVOKED_AT,            True,  "issued at the revocation instant: core/auth.py refuses only `iat <`"),
    (REVOKED_AT + 1,        True,  "issued after it — the member signed in again"),
    (f"{REVOKED_AT + 5}.5", True,  "a numeric string is still a number"),
    (None,                  False, "revoked and the token cannot show when it was issued: fail CLOSED"),
    ("soon",                False, "revoked and `iat` is not a number: fail CLOSED"),
    ("",                    False, "revoked and `iat` is empty: fail CLOSED"),
])
def test_a_revoked_session_is_dead_only_before_the_revocation(db, iat, live, why):
    _revoke(db, USER_EXEC)
    got = _helpers(db, AUTH_EXEC, iat=iat)
    assert (got != NOBODY) is live, f"{why}: got {got}"


def test_with_no_revocation_the_claim_is_never_consulted(db):
    """An `iat` that is garbage is irrelevant when nothing was revoked — the
    common case must not start failing because of a claim nobody needed."""
    assert _helpers(db, AUTH_EXEC, iat="garbage") == (FIRM, "Executive", USER_EXEC)


def test_a_stranger_is_still_nobody(db):
    """The behaviour the new rule reuses: no `users` row, no answer."""
    stranger = "99999999-9999-9999-9999-999999999468"
    _ok(db, f"INSERT INTO auth.users (id, email) VALUES ('{stranger}','s468@test.in');")
    assert _helpers(db, stranger) == NOBODY


# ── the rows, not the helper's answer ────────────────────────────────────────
def _count(dsn: str, auth: str, table: str, iat=None, where: str = "TRUE") -> int:
    return int(_ok(dsn, _as(auth, iat) +
                   f"SELECT count(*) FROM public.{table} WHERE {where};"))


def test_a_suspended_member_reads_no_rows_and_a_reactivated_one_reads_them_again(db):
    assert _count(db, AUTH_EXEC, "clients") == 1            # assigned: A only
    assert _count(db, AUTH_PARTNER, "clients") == 2

    _suspend(db, USER_EXEC)
    assert _count(db, AUTH_EXEC, "clients") == 0
    # A Partner who is suspended loses the firm-wide read the same way.
    _suspend(db, USER_PARTNER)
    assert _count(db, AUTH_PARTNER, "clients") == 0

    _reactivate(db, USER_EXEC)
    assert _count(db, AUTH_EXEC, "clients") == 1


def test_a_signed_out_session_reads_no_rows_until_a_new_token_is_issued(db):
    _revoke(db, USER_EXEC)
    assert _count(db, AUTH_EXEC, "clients", iat=REVOKED_AT - 60) == 0
    assert _count(db, AUTH_EXEC, "clients", iat=REVOKED_AT + 60) == 1


def test_a_suspended_member_cannot_write_either(db):
    """A read path closed and a write path open would be the worse half."""
    _suspend(db, USER_PARTNER)
    r = _psql(db, _as(AUTH_PARTNER) +
              f"INSERT INTO customers (firm_id, client_id, name) "
              f"VALUES ('{FIRM}','{CLIENT_A}','Ghost');")
    assert r.returncode != 0, "a suspended Partner inserted a row"
    assert "row-level security" in r.stderr or "permission denied" in r.stderr, r.stderr


# ── the two functions that read `users` themselves ───────────────────────────
def test_an_assignment_row_does_not_rescue_a_suspended_member(db):
    assert _ok(db, _as(AUTH_EXEC) +
               f"SELECT public.can_access_client('{CLIENT_A}');") == "t"
    assert _ok(db, _as(AUTH_EXEC) +
               f"SELECT public.can_access_client('{CLIENT_B}');") == "f"
    _suspend(db, USER_EXEC)
    assert _ok(db, _as(AUTH_EXEC) +
               f"SELECT public.can_access_client('{CLIENT_A}');") == "f", (
        "the assignment leg still answered for a suspended member — it is "
        "reading `users` inline again")


def test_a_grid_grant_does_not_rescue_a_suspended_member(db):
    """`granted = true` is a per-person decision made while they were staff. It
    must not outlive their being staff."""
    _ok(db, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
            f"VALUES ('{FIRM}','{USER_REVIEWER}','document','write', true);")
    asks = "SELECT coalesce(public.my_permission('document','write','Executive'), false);"
    assert _ok(db, _as(AUTH_REVIEWER) + asks) == "t", "the grant should apply to a live Reviewer"
    _suspend(db, USER_REVIEWER)
    assert _ok(db, _as(AUTH_REVIEWER) + asks) == "f"


# ── one rule over the whole catalogue ────────────────────────────────────────
#: Functions that mention `users` for a reason that is NOT "decide who the
#: caller is". Anything else reading `users` is a second way for a request to
#: become a person, which is exactly how `can_access_client` and `my_permission`
#: came to ignore a suspension. A new entry needs a reason a reviewer accepts.
USERS_READERS_THAT_DO_NOT_AUTHORISE = {
    # The one place a request becomes a person — what this migration hardens.
    "get_my_firm_id", "get_my_role", "get_my_user_id",
    # Resolve the ACTOR'S EMAIL for an audit row after the fact; they decide
    # nothing about what the caller may do.
    "audit_capture", "audit_capture_firm", "audit_capture_journal_line",
    # Read the actor named by the `p_actor` ARGUMENT for the audit record.
    "discard_posted_journal",
    # Counts a firm's users before purging it; platform-admin and service role.
    "platform_purge_firm",
}

_READS_USERS = r"(from|join)[[:space:]]+(public\.)?users([^a-z_]|$)"


def test_no_policy_reads_the_users_table(db):
    offenders = _ok(db, f"""
        SELECT tablename || '.' || policyname FROM pg_policies
         WHERE schemaname IN ('public','storage')
           AND (coalesce(qual,'') || ' ' || coalesce(with_check,'')) ~* '{_READS_USERS}'
         ORDER BY 1;""")
    assert offenders == "", (
        "an RLS policy selects from `users` itself, so a suspension does not "
        "reach it. Ask public.get_my_firm_id()/get_my_role()/get_my_user_id() "
        f"instead: {offenders.splitlines()}")


def test_no_function_reads_the_users_table_to_authorise_except_the_named_ones(db):
    found = set(_ok(db, f"""
        SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname IN ('public','storage')
           AND p.prosrc ~* '{_READS_USERS}'
         ORDER BY 1;""").split())
    unexpected = found - USERS_READERS_THAT_DO_NOT_AUTHORISE
    assert not unexpected, (
        f"{sorted(unexpected)} read `users` directly. A function that decides "
        "what the caller may do must ask get_my_user_id()/get_my_role(), which "
        "know about suspension and revoked sessions (migration 468).")
    # Not vacuous: the three helpers ARE found, so the scan sees what it should.
    assert {"get_my_firm_id", "get_my_role", "get_my_user_id"} <= found


def test_the_rule_is_asked_by_all_three_helpers(db):
    for fn in ("get_my_firm_id", "get_my_role", "get_my_user_id"):
        body = _ok(db, f"SELECT prosrc FROM pg_proc WHERE proname = '{fn}';")
        assert "staff_session_is_live" in body, (
            f"{fn} no longer asks staff_session_is_live, so a suspension no "
            f"longer reaches it")


def test_the_liveness_rule_is_not_callable_by_a_request(db):
    for role in ("anon", "authenticated"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', "
                       f"'public.staff_session_is_live(boolean, timestamptz)', 'EXECUTE');") == "f"


# ── Storage ──────────────────────────────────────────────────────────────────
#: storage-api connects as supabase_storage_admin whatever key the caller
#: presented (migration 204's header); `authenticated` is the role a policy is
#: written TO. A policy that works as one and fails as the other has shipped
#: before, so every storage assertion is made as both.
STORAGE_ROLES = ["supabase_storage_admin", "authenticated"]


def _scoped(dsn: str, auth: str, pg_role: str, bucket: str = "Documents", iat=None) -> list[str]:
    out = _ok(dsn, _as(auth, iat, pg_role) +
              f"SELECT name FROM storage.objects WHERE bucket_id = '{bucket}' ORDER BY name;")
    return out.splitlines()


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_an_assigned_member_lists_only_their_own_clients_files(db, pg_role):
    assert _scoped(db, AUTH_EXEC, pg_role) == [f"{FIRM}/{CLIENT_A}/vault/a.pdf"]


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_partner_lists_every_client_of_their_own_firm_and_no_other_firms(db, pg_role):
    assert _scoped(db, AUTH_PARTNER, pg_role) == [
        f"{FIRM}/{CLIENT_A}/vault/a.pdf",
        f"{FIRM}/{CLIENT_B}/vault/b.pdf",
    ]


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_suspended_member_lists_no_files(db, pg_role):
    _suspend(db, USER_EXEC)
    assert _scoped(db, AUTH_EXEC, pg_role) == []
    _suspend(db, USER_PARTNER)
    assert _scoped(db, AUTH_PARTNER, pg_role) == []


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_signed_out_session_lists_no_files(db, pg_role):
    _revoke(db, USER_EXEC)
    assert _scoped(db, AUTH_EXEC, pg_role, iat=REVOKED_AT - 1) == []
    assert _scoped(db, AUTH_EXEC, pg_role, iat=REVOKED_AT + 1) == [
        f"{FIRM}/{CLIENT_A}/vault/a.pdf"]


def _insert(dsn: str, auth: str, pg_role: str, path: str, bucket: str = "Documents"):
    return _psql(dsn, _as(auth, None, pg_role) +
                 f"INSERT INTO storage.objects (bucket_id, name) VALUES ('{bucket}', '{path}');")


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_an_executive_uploads_for_their_own_client_and_not_for_another(db, pg_role):
    ok = _insert(db, AUTH_EXEC, pg_role, f"{FIRM}/{CLIENT_A}/vault/new.pdf")
    assert ok.returncode == 0, ok.stderr
    refused = _insert(db, AUTH_EXEC, pg_role, f"{FIRM}/{CLIENT_B}/vault/new.pdf")
    assert refused.returncode != 0 and "row-level security" in refused.stderr, refused.stderr


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_nobody_uploads_into_another_firms_folder(db, pg_role):
    r = _insert(db, AUTH_PARTNER, pg_role, f"{OTHER_FIRM}/{CLIENT_A}/vault/x.pdf")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_reviewer_cannot_upload_but_a_per_person_grant_lets_them(db, pg_role):
    """Reviewer holds none of document, accounting or year-end write."""
    r = _insert(db, AUTH_REVIEWER, pg_role, f"{FIRM}/{CLIENT_A}/vault/r.pdf")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr
    # accounting:write alone is enough — the debit-note attachment route's pair.
    _ok(db, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
            f"VALUES ('{FIRM}','{USER_REVIEWER}','accounting','write', true);")
    r = _insert(db, AUTH_REVIEWER, pg_role, f"{FIRM}/{CLIENT_A}/purchase_bill/r.pdf")
    assert r.returncode == 0, r.stderr


def _delete(dsn: str, auth: str, pg_role: str, path: str, bucket: str = "Documents") -> str:
    return _ok(dsn, _as(auth, None, pg_role) +
               f"DELETE FROM storage.objects WHERE bucket_id = '{bucket}' "
               f"AND name = '{path}' RETURNING name;")


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_only_a_partner_deletes_a_file_and_only_for_a_client_they_may_see(db, pg_role):
    mine = f"{FIRM}/{CLIENT_A}/vault/a.pdf"
    # An Executive assigned to that client: the row beneath it is Partner-only
    # to delete (260), so the blob is too. A denied delete is an EMPTY result,
    # not an error — which is what Storage reports to the browser.
    assert _delete(db, AUTH_EXEC, pg_role, mine) == ""
    assert _ok(db, f"SELECT count(*) FROM storage.objects WHERE name = '{mine}';") == "1"
    assert _delete(db, AUTH_PARTNER, pg_role, mine) == mine
    assert _ok(db, f"SELECT count(*) FROM storage.objects WHERE name = '{mine}';") == "0"


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_partner_cannot_delete_another_firms_file(db, pg_role):
    foreign = f"{OTHER_FIRM}/{CLIENT_A}/vault/foreign.pdf"
    assert _delete(db, AUTH_PARTNER, pg_role, foreign) == ""
    assert _ok(db, f"SELECT count(*) FROM storage.objects WHERE name = '{foreign}';") == "1"


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_a_suspended_partner_deletes_nothing(db, pg_role):
    _suspend(db, USER_PARTNER)
    mine = f"{FIRM}/{CLIENT_A}/vault/a.pdf"
    assert _delete(db, AUTH_PARTNER, pg_role, mine) == ""
    assert _ok(db, f"SELECT count(*) FROM storage.objects WHERE name = '{mine}';") == "1"


@pytest.mark.parametrize("pg_role", STORAGE_ROLES)
def test_the_year_end_bucket_is_scoped_the_same_way_and_has_no_member_delete(db, pg_role):
    assert _scoped(db, AUTH_EXEC, pg_role, bucket="year-end-exports") == [
        f"{FIRM}/{CLIENT_A}/2025-26/pack-a.pdf"]
    # A Reviewer may not read a year-end pack: `year_end:read` is Executive+.
    assert _scoped(db, AUTH_REVIEWER, pg_role, bucket="year-end-exports") == []
    ok = _insert(db, AUTH_EXEC, pg_role, f"{FIRM}/{CLIENT_A}/2025-26/new.pdf",
                 bucket="year-end-exports")
    assert ok.returncode == 0, ok.stderr
    refused = _insert(db, AUTH_EXEC, pg_role, f"{FIRM}/{CLIENT_B}/2025-26/new.pdf",
                      bucket="year-end-exports")
    assert refused.returncode != 0, "an unassigned Executive wrote a year-end pack"
    # No delete door for a member at all — not even a Partner. The API never
    # removes an export under a member's token.
    pack = f"{FIRM}/{CLIENT_A}/2025-26/pack-a.pdf"
    assert _delete(db, AUTH_PARTNER, pg_role, pack, bucket="year-end-exports") == ""
    assert _ok(db, f"SELECT count(*) FROM storage.objects WHERE name = '{pack}';") == "1"


def test_the_service_role_policies_are_untouched(db):
    """The backend's own service-key uploads (204, 426) must keep working: the
    storage policies match on the JWT's role claim, not on a users row."""
    claims = '{"role": "service_role"}'
    r = _psql(db, f"SET request.jwt.claims = '{claims}'; SET ROLE supabase_storage_admin; "
                  f"INSERT INTO storage.objects (bucket_id, name) "
                  f"VALUES ('Documents', '{FIRM}/{CLIENT_B}/backend/job.pdf');")
    assert r.returncode == 0, r.stderr
    out = _ok(db, f"SET request.jwt.claims = '{claims}'; SET ROLE supabase_storage_admin; "
                  f"SELECT count(*) FROM storage.objects WHERE bucket_id = 'Documents';")
    assert out == "4"


def test_the_storage_admin_role_can_run_every_function_a_storage_policy_calls(db):
    """The incident migration 204 records, as a rule: 'permission denied for
    function' on every upload because a policy called something the role storage-api
    connects as could not execute."""
    for sig in ("public.get_my_firm_id()", "public.can_access_client(text)",
                "public.my_permission(text, text, text)", "public.my_role_at_least(text)"):
        assert _ok(db, f"SELECT has_function_privilege('supabase_storage_admin', "
                       f"'{sig}', 'EXECUTE');") == "t", sig

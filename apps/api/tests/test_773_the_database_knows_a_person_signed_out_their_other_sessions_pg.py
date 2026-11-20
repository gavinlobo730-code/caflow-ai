"""Migration 773: the database knows "sign out my other sessions" (POST-A-509), proved against real PostgreSQL.

THE FACT. POST-A-486 added two marks to a person's own `users` row, `other_sessions_revoked_at` and `other_sessions_kept_session_id`, and the API's
`get_current_user` refuses a token whose session is not the kept one and began before the instant (`core/auth_time.ended_by_other_sessions_sign_out`).
The database's own question, `public.staff_session_is_live`, asked by `get_my_firm_id`, `get_my_role` and `get_my_user_id` on every request that reaches
a table directly over PostgREST, did not read either mark, so a session the person had signed out that way was refused by the API and still read, through
the database's own door, what a signed-in session can reach there. These tests hold the database equal to the API's rule: the same tokens, the same marks,
the same answer, from one table, and then the rows themselves.

WHAT THEY RUN. Real helpers and real policies on a migrated database: each token is presented to PostgREST's own claim setting (`request.jwt.claims`) as the
`authenticated` role, which is how a request reaches a policy.
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
FORWARD = API_ROOT / "migrations" / "773_the_database_knows_a_person_signed_out_their_other_sessions.sql"
ROLLBACK = API_ROOT / "migrations" / "773_the_database_knows_a_person_signed_out_their_other_sessions_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 773 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000773"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a773"
CLIENT_B = "cccccccc-0000-0000-0000-00000000b773"
AUTH_EXEC = "22222222-2222-2222-2222-222222222773"
USER_EXEC = "bbbbbbbb-0000-0000-0000-00000000b773"
AUTH_PARTNER = "11111111-1111-1111-1111-111111111773"
USER_PARTNER = "bbbbbbbb-0000-0000-0000-00000000a773"

SIGNED_OUT_AT = 2_000_000_000          # the instant the person signed out their other sessions
BEFORE = SIGNED_OUT_AT - 3_600         # a session that began an hour before
AFTER = SIGNED_OUT_AT + 3_600          # a token renewed, or a sign-in made, an hour after
KEPT = "sess-kept-0001"
OTHER = "sess-other-0002"
NOBODY = ("-", "-", "-")
MINE = (FIRM, "Executive", USER_EXEC)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA", "-F", "|"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _claims(auth_user_id: str, iat=None, amr=None, session_id=None) -> str:
    """`amr` is a list of (method, timestamp) pairs or the raw JSON of the claim; `session_id` is the claim's raw JSON when it is not a plain string."""
    parts = [f'"sub": "{auth_user_id}"', '"role": "authenticated"']
    if iat is not None:
        parts.append(f'"iat": {iat}' if isinstance(iat, (int, float)) else f'"iat": "{iat}"')
    if amr is not None:
        parts.append(f'"amr": {amr}' if isinstance(amr, str)
                     else '"amr": [' + ", ".join(f'{{"method": "{m}", "timestamp": {t}}}' for m, t in amr) + "]")
    if session_id is not None:
        parts.append(f'"session_id": {session_id[0]}' if isinstance(session_id, tuple) else f'"session_id": "{session_id}"')
    return "{" + ", ".join(parts) + "}"


def _as(auth_user_id: str, iat=None, amr=None, session_id=None) -> str:
    return f"SET request.jwt.claims = '{_claims(auth_user_id, iat, amr, session_id)}'; SET ROLE authenticated; "


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m773_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert FORWARD.name not in pg_template.failed, "migration 773 did not apply: everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_EXEC}','e773@test.in'), ('{AUTH_PARTNER}','p773@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M773 Firm','m773@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) VALUES
              ('{USER_PARTNER}','{FIRM}','{AUTH_PARTNER}','p773@test.in','Partner 773','Partner'),
              ('{USER_EXEC}','{FIRM}','{AUTH_EXEC}','e773@test.in','Exec 773','Executive');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A 773','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B 773','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}','{USER_EXEC}','{CLIENT_A}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sign_out_others(dsn: str, kept: str | None = KEPT, at: int = SIGNED_OUT_AT, user: str = USER_EXEC) -> None:
    kept_sql = "NULL" if kept is None else f"'{kept}'"
    _ok(dsn, f"UPDATE users SET other_sessions_revoked_at = to_timestamp({at}), other_sessions_kept_session_id = {kept_sql} WHERE id = '{user}';")


def _revoke_all(dsn: str, at: int = SIGNED_OUT_AT, user: str = USER_EXEC) -> None:
    _ok(dsn, f"UPDATE users SET sessions_revoked_at = to_timestamp({at}) WHERE id = '{user}';")


def _helpers(dsn: str, iat=None, amr=None, session_id=None, auth: str = AUTH_EXEC) -> tuple[str, str, str]:
    row = _ok(dsn, _as(auth, iat, amr, session_id) +
              "SELECT coalesce(public.get_my_firm_id()::text,'-'), coalesce(public.get_my_role(),'-'), coalesce(public.get_my_user_id()::text,'-');")
    firm, role, uid = row.split("|")
    return firm, role, uid


def _clients_seen(dsn: str, iat=None, amr=None, session_id=None) -> int:
    return int(_ok(dsn, _as(AUTH_EXEC, iat, amr, session_id) + "SELECT count(*) FROM clients;"))


# ── the facts ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_with_no_mark_every_session_is_live_whatever_its_id(db):
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=OTHER) == MINE
    assert _helpers(db, iat=BEFORE) == MINE


def test_the_session_that_asked_to_stay_is_live_and_every_other_session_is_nobody(db):
    _sign_out_others(db)
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=KEPT) == MINE, "the kept session was ended"
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY, "another session still reads"
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY


def test_the_rows_are_dark_to_the_other_session_and_open_to_the_kept_one(db):
    assert _clients_seen(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == 1, "control: before the mark every session reads"
    _sign_out_others(db)
    assert _clients_seen(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == 0
    assert _clients_seen(db, iat=AFTER, amr=[("password", BEFORE)], session_id=KEPT) == 1


def test_a_renewed_token_of_another_session_is_nobody_and_a_new_sign_in_after_the_mark_is_live(db):
    _sign_out_others(db)
    # the browser renews its token hourly: `iat` is after the mark, the `amr` stamps are the session's, from before
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY
    assert _helpers(db, iat=AFTER, amr=[("password", AFTER)], session_id="sess-new-0003") == MINE


def test_a_code_entered_later_does_not_make_an_old_session_new(db):
    _sign_out_others(db)
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE), ("totp", AFTER)], session_id=OTHER) == NOBODY


def test_a_token_with_no_session_id_cannot_be_the_kept_session(db):
    _sign_out_others(db)
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)]) == NOBODY
    assert _helpers(db, iat=AFTER, amr=[("password", AFTER)]) == MINE, "a sign-in after the mark needs no id"


def test_where_no_session_was_kept_no_session_is_the_kept_one(db):
    for kept in (None, ""):
        _sign_out_others(db, kept=kept)
        assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=KEPT) == NOBODY, f"kept id {kept!r}"
        assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id="") == NOBODY, f"kept id {kept!r}"


def test_a_session_id_that_is_blank_or_not_a_string_is_not_the_kept_one(db):
    _sign_out_others(db, kept=" ")
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=" ") == NOBODY, "the API strips the claim, so a blank id is no id"
    _sign_out_others(db, kept="7")
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=("7",)) == NOBODY, "a number is not a session id"


def test_the_kept_session_is_still_ended_by_a_revocation_of_every_session(db):
    """Both marks apply together, as they do in get_current_user: suspend or force sign-out ends the kept session too."""
    _sign_out_others(db)
    _revoke_all(db)
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=KEPT) == NOBODY
    assert _helpers(db, iat=AFTER, amr=[("password", AFTER)], session_id="sess-new-0003") == MINE


def test_the_kept_session_is_judged_by_its_id_first_as_the_api_does(db):
    """The API returns before it reads `iat` for the kept session, so a kept token with no readable `iat` is not refused by the mark."""
    _sign_out_others(db)
    assert _helpers(db, session_id=KEPT) == MINE
    assert _helpers(db, iat="soon", session_id=KEPT) == MINE
    assert _helpers(db, session_id=OTHER) == NOBODY, "another session with no readable iat fails closed"
    assert _helpers(db, iat="soon", session_id=OTHER) == NOBODY


def test_an_inactive_member_is_dead_whatever_the_marks_say(db):
    _sign_out_others(db)
    _ok(db, f"UPDATE users SET is_active = false WHERE id = '{USER_EXEC}';")
    assert _helpers(db, iat=AFTER, amr=[("password", AFTER)], session_id=KEPT) == NOBODY


def test_another_persons_mark_does_not_end_my_session(db):
    _sign_out_others(db, user=USER_PARTNER)
    assert _helpers(db, iat=BEFORE, amr=[("password", BEFORE)], session_id=OTHER) == MINE


# ── the database judges every token as the API does, from one table ───────────────────────────────────────────────────────
STAMPS = [
    ("no amr, iat after", AFTER, None),
    ("no amr, iat before", BEFORE, None),
    ("no iat", None, [("password", AFTER)]),
    ("an iat that is not a number", "soon", [("password", AFTER)]),
    ("renewed: iat after, session began before", AFTER, [("password", BEFORE)]),
    ("new sign-in", AFTER, [("password", AFTER)]),
    ("code after on an old session", AFTER, [("password", BEFORE), ("totp", AFTER)]),
    ("stamp at the instant", AFTER, [("password", SIGNED_OUT_AT)]),
    ("stamp one second before the instant", AFTER, [("password", SIGNED_OUT_AT - 1)]),
    ("old token, iat before, stamps after", BEFORE, [("password", AFTER)]),
    ("iat at the instant, no amr", SIGNED_OUT_AT, None),
    ("iat at the instant, stamp at the instant", SIGNED_OUT_AT, [("password", SIGNED_OUT_AT)]),
    ("iat one second before the instant, no amr", SIGNED_OUT_AT - 1, None),
    ("iat one second before the instant, stamps after", SIGNED_OUT_AT - 1, [("password", AFTER)]),
    ("an amr that is not a list", AFTER, '"password"'),
    ("a timestamp that is a string", AFTER, '[{"method": "password", "timestamp": "1"}]'),
]
SESSIONS = [("the kept id", KEPT), ("another id", OTHER), ("no id", None), ("a blank id", " "), ("an empty id", ""), ("a number", ("7",))]
MARKS = [("a kept id on file", KEPT), ("no kept id on file", None), ("an empty kept id", "")]


def _payload(iat, amr, session_id) -> dict:
    out: dict = {}
    if iat is not None:
        out["iat"] = iat
    if amr is not None:
        out["amr"] = json.loads(amr) if isinstance(amr, str) else [{"method": m, "timestamp": t} for m, t in amr]
    if session_id is not None:
        out["session_id"] = 7 if isinstance(session_id, tuple) else session_id
    return out


def _the_api_refuses(payload: dict, kept) -> bool:
    """What `core/auth._refuse_a_session_signed_out_from_elsewhere` does with this token: any failure of the comparison refuses it."""
    from core import auth_time
    try:
        return bool(auth_time.ended_by_other_sessions_sign_out(payload, float(SIGNED_OUT_AT), kept))
    except Exception:                                    # noqa: BLE001 — the API answers 401 for a comparison it cannot make
        return True


@pytest.mark.parametrize("session_why,session_id", SESSIONS, ids=[s[0] for s in SESSIONS])
@pytest.mark.parametrize("mark_why,kept", MARKS, ids=[m[0] for m in MARKS])
@pytest.mark.parametrize("why,iat,amr", STAMPS, ids=[s[0] for s in STAMPS])
def test_the_database_judges_every_token_and_mark_as_core_auth_time_does(db, why, iat, amr, mark_why, kept, session_why, session_id):
    _sign_out_others(db, kept=kept)
    refused = _the_api_refuses(_payload(iat, amr, session_id), kept)
    live = _helpers(db, iat=iat, amr=amr, session_id=session_id) != NOBODY
    assert live is (not refused), (
        f"{why} / {mark_why} / token carries {session_why}: the API {'refuses' if refused else 'admits'} the token, "
        f"the database {'admits' if live else 'refuses'} it")


def _the_function_itself(dsn: str, other_at, kept, iat=None, amr=None, session_id=None, revoked_at=None) -> str:
    """What `staff_session_is_live` answers when it is asked DIRECTLY, as the owner (a request cannot call it): `t`, `f`, or `NULL` spelled as `-`.
    The helpers read NULL and false alike as "no row", so a test that goes through them cannot tell a total answer from a three-valued one."""
    other = "NULL" if other_at is None else f"to_timestamp({other_at})"
    every = "NULL" if revoked_at is None else f"to_timestamp({revoked_at})"
    kept_sql = "NULL" if kept is None else f"'{kept}'"
    claims = _claims(AUTH_EXEC, iat, amr, session_id)
    return _ok(dsn, f"SET request.jwt.claims = '{claims}'; "
                            f"SELECT coalesce(public.staff_session_is_live(true, {every}, {other}, {kept_sql})::text, '-');")


@pytest.mark.parametrize("session_why,session_id", SESSIONS, ids=[s[0] for s in SESSIONS])
@pytest.mark.parametrize("mark_why,kept", MARKS, ids=[m[0] for m in MARKS])
@pytest.mark.parametrize("why,iat,amr", STAMPS, ids=[s[0] for s in STAMPS])
def test_the_answer_is_always_true_or_false_and_never_null(db, why, iat, amr, mark_why, kept, session_why, session_id):
    """The review's case: a kept id on file, a token with no `session_id` claim, a token that began before the mark. The kept-session test is
    NULL there, and `FALSE OR NULL OR FALSE` is NULL, which `IF NOT f()` would read as "no refusal"."""
    answer = _the_function_itself(db, SIGNED_OUT_AT, kept, iat=iat, amr=amr, session_id=session_id)
    assert answer in ("true", "false"), f"{why} / {mark_why} / {session_why}: the answer was {answer!r}"
    refused = _the_api_refuses(_payload(iat, amr, session_id), kept)
    assert (answer == "true") is (not refused), f"{why} / {mark_why} / {session_why}: called directly the database said {answer}, the API {'refuses' if refused else 'admits'}"


def test_the_functions_answer_when_nothing_was_ever_revoked_without_reading_a_claim(db):
    assert _the_function_itself(db, None, None) == "true", "no marks and no claims at all"
    assert _ok(db, "SELECT public.token_session_began_at_or_after(NULL)::text;") == "true", "no instant is a session that began after it (migration 767 tested for NULL first)"


# ── the shape of the change ──────────────────────────────────────────────────────────────────────────────────────────────
def test_the_question_is_answered_in_one_place_and_the_old_half_of_it_is_gone(db):
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname = 'staff_session_is_live' AND pronamespace = 'public'::regnamespace;") == "1"
    assert _ok(db, "SELECT pg_get_function_identity_arguments(oid) FROM pg_proc WHERE proname = 'staff_session_is_live' AND pronamespace = 'public'::regnamespace;") == (
        "p_is_active boolean, p_sessions_revoked_at timestamp with time zone, "
        "p_other_sessions_revoked_at timestamp with time zone, p_other_sessions_kept_session_id text")
    for helper in ("get_my_firm_id", "get_my_role", "get_my_user_id"):
        body = _ok(db, f"SELECT prosrc FROM pg_proc WHERE proname = '{helper}' AND pronamespace = 'public'::regnamespace;")
        assert "u.other_sessions_revoked_at" in body and "u.other_sessions_kept_session_id" in body, f"{helper} does not pass the marks"


@pytest.mark.parametrize("fn", [
    "public.staff_session_is_live(boolean, timestamptz, timestamptz, text)",
    "public.token_session_began_at_or_after(timestamptz)",
])
def test_neither_function_is_callable_by_a_request(db, fn):
    for role in ("authenticated", "anon"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE');") == "f", f"{role} may call {fn}"


def test_the_helpers_keep_their_security_definer_and_search_path(db):
    for helper in ("get_my_firm_id", "get_my_role", "get_my_user_id"):
        row = _ok(db, f"SELECT prosecdef::text || '|' || coalesce(array_to_string(proconfig, ','), '') FROM pg_proc WHERE proname = '{helper}' AND pronamespace = 'public'::regnamespace;")
        assert row == "true|search_path=public, pg_catalog", f"{helper}: {row}"


def test_the_migration_can_run_twice(db):
    _sign_out_others(db)
    assert _psql_file(db, FORWARD).returncode == 0
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=KEPT) == MINE
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY


def test_the_rollback_restores_the_earlier_rule_and_the_migration_comes_back(db):
    _sign_out_others(db)
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY
    rolled = _psql_file(db, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    # migration 767's two-argument rule again: the other-sessions mark is the API's alone
    assert _ok(db, "SELECT pg_get_function_identity_arguments(oid) FROM pg_proc WHERE proname = 'staff_session_is_live' AND pronamespace = 'public'::regnamespace;") == (
        "p_is_active boolean, p_sessions_revoked_at timestamp with time zone")
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == MINE
    _revoke_all(db)
    assert _helpers(db, iat=AFTER, amr=[("password", BEFORE)], session_id=OTHER) == NOBODY, "767's rule for sessions_revoked_at survived the rollback"
    assert _psql_file(db, FORWARD).returncode == 0
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname = 'staff_session_is_live' AND pronamespace = 'public'::regnamespace;") == "1"

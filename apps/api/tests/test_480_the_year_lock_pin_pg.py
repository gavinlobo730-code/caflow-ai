"""Migration 480 — the year-lock PIN is a salted hash in a table nobody signed in can read (POST-A-004).

THE BUG THIS PINS
    `firms.lock_pin` held the PIN as typed, and `firms` is readable by every member of the firm over
    PostgREST (migration 033 grants SELECT, UPDATE to `authenticated`; policy `firms_own` is FOR ALL on the
    caller's own firm). A Manager, an Executive or a Reviewer could read the PIN that authorises locking and
    unlocking a financial year from a browser console, and a Partner's session could blank it.

WHAT IS ASSERTED, AND WHY IT IS A DATABASE FACT
    * the backfill carries every existing PIN over as `sha256$<salt>$<hex>`, a fresh salt per firm, and the
      PYTHON verifier (domain/firm/lock_pin) accepts a hash MADE BY THIS FILE'S SQL, a non-ASCII PIN included
      (the SQL/Python contract is the thing a mock test cannot see);
    * a firm with no PIN, or an empty one, gets no row and still reads as "no PIN set";
    * after it, `firms.lock_pin` is NULL for every firm and a CHECK refuses anything else, for a superuser and
      for a Partner's own session alike;
    * as `authenticated` (each role the matrix tries) and as `anon`, `firm_lock_pins` can be neither read nor
      written: the privilege is absent, not merely hidden by row-level security;
    * the API's own service, UNMODIFIED, run as `service_role` over the real schema, adopts a PIN, refuses a
      wrong one, opens with the right one and rewrites the backfill's form as PBKDF2 on first use;
    * 480 is idempotent, and its own rollback puts the hole back (a Reviewer reads the plaintext) — the
      negative control that makes the rest of this file mean something.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
MIGRATION = API_ROOT / "migrations" / "480_the_year_lock_pin_is_a_salted_hash_nobody_signed_in_can_read.sql"
ROLLBACK = API_ROOT / "migrations" / "480_the_year_lock_pin_is_a_salted_hash_nobody_signed_in_can_read_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the year-lock PIN proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000480"
FIRM_B = "aaaaaaaa-0000-0000-0000-000000001480"      # a PIN of non-ASCII characters
FIRM_C = "aaaaaaaa-0000-0000-0000-000000002480"      # an empty PIN
FIRM_D = "aaaaaaaa-0000-0000-0000-000000003480"      # no PIN
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000004480"

PIN_A = "4821"
PIN_B = "piné₹अक"                 # accented, rupee sign, Devanagari: multi-byte in UTF-8

AUTH = {
    "partner": "11111111-1111-1111-1111-111111111480",
    "manager": "22222222-2222-2222-2222-222222222480",
    "exec": "33333333-3333-3333-3333-333333333480",
    "reviewer": "44444444-4444-4444-4444-444444444480",
    "other_partner": "66666666-6666-6666-6666-666666666480",
}
USER = {k: v.replace(v[:8], "bbbbbbbb", 1) for k, v in AUTH.items()}
ROLE = {"partner": "Partner", "manager": "Manager", "exec": "Executive", "reviewer": "Reviewer",
        "other_partner": "Partner"}
MEMBERS_OF_THE_FIRM = ["partner", "manager", "exec", "reviewer"]

_ENV = {**os.environ, "PGCLIENTENCODING": "UTF8"}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True, encoding="utf-8", env=_ENV)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, role: str, sql: str, auth: str | None = None) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": auth, "role": role}) if auth else json.dumps({"role": role})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE {role}; {sql}")


@pytest.fixture()
def db(pg_template):
    """A throwaway database cloned from the fully migrated template, with four members of one firm, a
    Partner of another, and four firms that differ only in what their year-lock PIN was."""
    admin = _ADMIN.strip()
    dbname = f"pin_m480_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m480.test')" for k, v in AUTH.items())
        users = ", ".join(
            f"('{USER[k]}', '{OTHER_FIRM if k == 'other_partner' else FIRM}', '{AUTH[k]}', '{k}@m480.test', "
            f"'{k}', '{ROLE[k]}', true)" for k in AUTH)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M480 Firm','m480@test.in'), ('{FIRM_B}','M480 B','m480b@test.in'),
              ('{FIRM_C}','M480 C','m480c@test.in'), ('{FIRM_D}','M480 D','m480d@test.in'),
              ('{OTHER_FIRM}','M480 Other','m480o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def backfilled(db):
    """The database as it was on the day before 480 (rolled back, plaintext PINs in the readable column), then
    480 applied: the production event, reproduced."""
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    _ok(db, f"""
        UPDATE firms SET lock_pin = '{PIN_A}' WHERE id = '{FIRM}';
        UPDATE firms SET lock_pin = '{PIN_B}' WHERE id = '{FIRM_B}';
        UPDATE firms SET lock_pin = ''        WHERE id = '{FIRM_C}';
    """)
    assert _ok(db, "SELECT count(*) FROM firms WHERE lock_pin IS NOT NULL;") == "3"
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    return db


def _hash_of(dsn: str, firm: str) -> str:
    return _ok(dsn, f"SELECT pin_hash FROM firm_lock_pins WHERE firm_id = '{firm}';")


# ── the backfill ─────────────────────────────────────────────────────────────

def test_every_existing_pin_is_carried_over_as_a_hash_the_python_verifier_accepts(backfilled):
    """The SQL/Python contract. The hash is made by 480's own SQL; the verifier is the API's, unmodified."""
    from domain.firm import lock_pin
    for firm, pin, wrong in ((FIRM, PIN_A, "4822"), (FIRM_B, PIN_B, PIN_B + "x")):
        stored = _hash_of(backfilled, firm)
        assert stored.startswith("sha256$"), stored
        assert pin not in stored
        assert lock_pin.verify(pin, stored) == lock_pin.Verdict(True, True), (firm, stored)
        assert not lock_pin.verify(wrong, stored).ok


def test_each_firm_gets_its_own_salt(backfilled):
    a, b = _hash_of(backfilled, FIRM).split("$")[1], _hash_of(backfilled, FIRM_B).split("$")[1]
    assert a != b and len(a) == len(b) == 32


def test_a_firm_with_no_pin_or_an_empty_one_gets_no_row_and_still_reads_as_unset(backfilled):
    rows = _ok(backfilled, "SELECT firm_id FROM firm_lock_pins ORDER BY firm_id;").splitlines()
    assert rows == [FIRM, FIRM_B]


def test_the_readable_column_is_emptied_for_every_firm(backfilled):
    assert _ok(backfilled, "SELECT count(*) FROM firms WHERE lock_pin IS NOT NULL;") == "0"


def test_nothing_else_on_the_firm_row_is_touched(db, backfilled):
    assert _ok(db, f"SELECT name || '|' || locked_financial_years::text FROM firms WHERE id = '{FIRM}';") == "M480 Firm|{}"


def test_480_is_idempotent(backfilled):
    before = _ok(backfilled, "SELECT firm_id || ':' || pin_hash FROM firm_lock_pins ORDER BY firm_id;")
    for _ in range(2):
        r = _psql(backfilled, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode == 0, r.stderr
    assert _ok(backfilled, "SELECT firm_id || ':' || pin_hash FROM firm_lock_pins ORDER BY firm_id;") == before
    assert _ok(backfilled, "SELECT count(*) FROM pg_constraint WHERE conname = 'firms_lock_pin_retired';") == "1"


# ── who can reach what ───────────────────────────────────────────────────────

@pytest.mark.parametrize("who", MEMBERS_OF_THE_FIRM + ["other_partner"])
def test_a_signed_in_member_reads_nothing_from_the_pin_column_of_firms(backfilled, who):
    r = _as(backfilled, "authenticated",
            f"SELECT count(*) || '|' || count(lock_pin) FROM firms WHERE id = '{FIRM}';", AUTH[who])
    assert r.returncode == 0, r.stderr
    seen, readable = r.stdout.strip().splitlines()[-1].split("|")
    assert readable == "0", f"{who} read a PIN out of firms"
    assert seen == ("0" if who == "other_partner" else "1")


@pytest.mark.parametrize("role,auth", [("authenticated", AUTH[k]) for k in MEMBERS_OF_THE_FIRM + ["other_partner"]]
                         + [("anon", None)])
@pytest.mark.parametrize("statement", [
    "SELECT * FROM firm_lock_pins",
    "SELECT pin_hash FROM firm_lock_pins",
    f"INSERT INTO firm_lock_pins (firm_id, pin_hash) VALUES ('{FIRM_D}', 'sha256$a$b')",
    "UPDATE firm_lock_pins SET pin_hash = 'sha256$a$b'",
    "DELETE FROM firm_lock_pins",
])
def test_no_signed_in_session_and_no_anonymous_one_can_touch_the_pin_table(backfilled, role, auth, statement):
    r = _as(backfilled, role, statement + ";", auth)
    assert r.returncode != 0 and "permission denied for table firm_lock_pins" in r.stderr, (role, statement, r.stderr)


@pytest.mark.parametrize("role", ["authenticated", "anon", "public"])
def test_the_privilege_is_absent_not_merely_hidden_by_row_level_security(backfilled, role):
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "REFERENCES", "TRIGGER", "TRUNCATE"):
        if role == "public":
            sql = f"SELECT has_table_privilege('public', 'public.firm_lock_pins', '{privilege}');"
        else:
            sql = f"SELECT has_table_privilege('{role}', 'public.firm_lock_pins', '{privilege}');"
        assert _ok(backfilled, sql) == "f", (role, privilege)


SUPABASE_DEFAULT_PRIVILEGES = ("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                               "GRANT ALL ON TABLES TO anon, authenticated;")
THE_REVOKE = "REVOKE ALL ON public.firm_lock_pins FROM PUBLIC, anon, authenticated;"


def _create_as_supabase_would(db: str, migration_sql: str) -> None:
    """Hosted Supabase grants every new table in `public` to `anon` and `authenticated` by default; the local
    harness does not. Reproduce that, then create the table by running the migration."""
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _psql(db, SUPABASE_DEFAULT_PRIVILEGES).returncode == 0
    r = _psql(db, migration_sql)
    assert r.returncode == 0, r.stderr


def test_the_revoke_is_what_holds_under_supabases_default_privileges(db):
    """The harness's own defaults would make the privilege tests above pass with the REVOKE deleted. Under the
    grants a hosted project really applies, the REVOKE is the first wall and row-level security the second."""
    _create_as_supabase_would(db, MIGRATION.read_text(encoding="utf-8"))
    for role in ("authenticated", "anon"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _ok(db, f"SELECT has_table_privilege('{role}', 'public.firm_lock_pins', '{privilege}');") == "f"


def test_negative_control_without_the_revoke_the_hosted_defaults_would_hand_the_table_out(db):
    sql = MIGRATION.read_text(encoding="utf-8")
    assert THE_REVOKE in sql
    _create_as_supabase_would(db, sql.replace(THE_REVOKE, ""))
    assert _ok(db, "SELECT has_table_privilege('authenticated', 'public.firm_lock_pins', 'SELECT');") == "t"
    # ... and what is left standing is row-level security alone: no policy, so no row, which is why it is the
    # second wall and not the only one.
    _ok(db, f"INSERT INTO firm_lock_pins (firm_id, pin_hash) VALUES ('{FIRM}', 'sha256$a$b');")
    r = _as(db, "authenticated", "SELECT count(*) FROM firm_lock_pins;", AUTH["partner"])
    assert r.returncode == 0 and r.stdout.strip().splitlines()[-1] == "0"


def test_row_level_security_is_on_with_no_policy_as_the_second_wall(backfilled):
    assert _ok(backfilled, "SELECT relrowsecurity FROM pg_class WHERE relname = 'firm_lock_pins';") == "t"
    assert _ok(backfilled, "SELECT count(*) FROM pg_policies WHERE tablename = 'firm_lock_pins';") == "0"


def test_the_backends_role_reads_and_writes_it(backfilled):
    r = _as(backfilled, "service_role",
            f"SELECT count(*) FROM firm_lock_pins; "
            f"INSERT INTO firm_lock_pins (firm_id, pin_hash) VALUES ('{FIRM_D}', 'pbkdf2_sha256$1$a$b'); "
            f"UPDATE firm_lock_pins SET pin_hash = 'pbkdf2_sha256$1$c$d' WHERE firm_id = '{FIRM_D}'; "
            f"DELETE FROM firm_lock_pins WHERE firm_id = '{FIRM_D}';")
    assert r.returncode == 0, r.stderr


def test_the_hash_column_refuses_a_plaintext_pin(backfilled):
    r = _psql(backfilled, f"INSERT INTO firm_lock_pins (firm_id, pin_hash) VALUES ('{FIRM_D}', '4821');")
    assert r.returncode != 0 and "firm_lock_pins_scheme" in r.stderr


def test_a_pin_row_goes_with_its_firm(backfilled):
    _ok(backfilled, f"DELETE FROM firms WHERE id = '{FIRM_B}';")
    assert _ok(backfilled, "SELECT count(*) FROM firm_lock_pins;") == "1"


# ── the readable place stays empty ───────────────────────────────────────────

def test_a_pin_cannot_be_written_back_into_firms_by_a_superuser(backfilled):
    r = _psql(backfilled, f"UPDATE firms SET lock_pin = '4821' WHERE id = '{FIRM_D}';")
    assert r.returncode != 0 and "firms_lock_pin_retired" in r.stderr
    r = _psql(backfilled, "INSERT INTO firms (id, name, email, lock_pin) "
                          "VALUES ('aaaaaaaa-0000-0000-0000-000000009480', 'x', 'x@x.in', '4821');")
    assert r.returncode != 0 and "firms_lock_pin_retired" in r.stderr


def test_nor_by_a_partners_own_session_which_is_what_old_code_or_a_console_would_do(backfilled):
    r = _as(backfilled, "authenticated",
            f"UPDATE firms SET lock_pin = '4821' WHERE id = '{FIRM}';", AUTH["partner"])
    assert r.returncode != 0 and "firms_lock_pin_retired" in r.stderr, r.stderr


def test_clearing_the_column_is_still_allowed_and_now_switches_nothing_off(backfilled):
    r = _as(backfilled, "authenticated",
            f"UPDATE firms SET lock_pin = NULL WHERE id = '{FIRM}';", AUTH["partner"])
    assert r.returncode == 0, r.stderr
    assert _hash_of(backfilled, FIRM).startswith("sha256$")       # the PIN is where the Partner cannot reach


# ── the API's own service, over the real schema ──────────────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "ARRAY[" + ", ".join(_lit(x) for x in v) + "]::text[]" if v else "'{}'::text[]"
    return "'" + str(v).replace("'", "''") + "'"


class _Query:
    """Just enough of the Supabase builder for year_lock_service, which is called UNMODIFIED. Every call is a
    real statement run as `service_role`, the role the API's service client is."""

    def __init__(self, dsn: str, table: str):
        self._dsn, self._table = dsn, table
        self._op, self._cols, self._row = "select", "*", None
        self._filters: list[tuple[str, object]] = []
        self._limit: int | None = None

    def select(self, cols="*"):
        self._op, self._cols = "select", cols
        return self

    def insert(self, row):
        self._op, self._row = "insert", row
        return self

    def update(self, row):
        self._op, self._row = "update", row
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        where = " AND ".join(f"{c} = {_lit(v)}" for c, v in self._filters)
        where = f" WHERE {where}" if where else ""
        t = self._table
        if self._op == "select":
            inner = f"SELECT {self._cols} FROM {t}{where}" + (f" LIMIT {self._limit}" if self._limit else "")
            sql = f"SELECT coalesce(json_agg(q), '[]'::json) FROM ({inner}) q"
        elif self._op == "insert":
            cols = ", ".join(self._row)
            vals = ", ".join(_lit(v) for v in self._row.values())
            sql = (f"WITH i AS (INSERT INTO {t} ({cols}) VALUES ({vals}) RETURNING *) "
                   f"SELECT coalesce(json_agg(i), '[]'::json) FROM i")
        else:
            sets = ", ".join(f"{c} = {_lit(v)}" for c, v in self._row.items())
            sql = (f"WITH u AS (UPDATE {t} SET {sets}{where} RETURNING *) "
                   f"SELECT coalesce(json_agg(u), '[]'::json) FROM u")
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
                            f"SET ROLE service_role; {sql};"],
                           capture_output=True, text=True, encoding="utf-8", env=_ENV)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("[")]
        return _Result(json.loads(lines[-1]) if lines else [])


class _ServiceDb:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def table(self, name: str) -> _Query:
        return _Query(self._dsn, name)


@pytest.fixture()
def service(backfilled, monkeypatch):
    from domain.firm import lock_pin
    from services import year_lock_service as yls
    monkeypatch.setattr(lock_pin, "ITERATIONS", 1_000)
    monkeypatch.setattr(yls, "log_event", lambda *a, **k: None)
    return yls, _ServiceDb(backfilled)


def test_the_service_opens_a_year_with_a_backfilled_pin_and_rewrites_its_form_as_pbkdf2(service, backfilled):
    from fastapi import HTTPException
    from domain.firm import lock_pin
    yls, api_db = service
    assert yls.get_state(api_db, FIRM) == {"locked_financial_years": [], "pin_set": True}
    with pytest.raises(HTTPException) as e:
        yls.set_lock(api_db, FIRM, "2025-26", True, pin="9999", actor_id=AUTH["partner"])
    assert e.value.status_code == 403
    assert _ok(backfilled, f"SELECT locked_financial_years::text FROM firms WHERE id = '{FIRM}';") == "{}"

    state = yls.set_lock(api_db, FIRM, "2025-26", True, pin=PIN_A, actor_id=AUTH["partner"])
    assert state == {"locked_financial_years": ["2025-26"], "pin_set": True}
    assert _ok(backfilled, f"SELECT locked_financial_years::text FROM firms WHERE id = '{FIRM}';") == "{2025-26}"
    stored = _hash_of(backfilled, FIRM)
    assert stored.startswith("pbkdf2_sha256$1000$"), stored          # the backfill's form, used once, is upgraded
    assert lock_pin.verify(PIN_A, stored).ok
    assert yls.set_lock(api_db, FIRM, "2025-26", False, pin=PIN_A, actor_id=AUTH["partner"])["locked_financial_years"] == []


def test_the_service_opens_with_a_non_ascii_pin_the_sql_hashed(service):
    yls, api_db = service
    state = yls.set_lock(api_db, FIRM_B, "2025-26", True, pin=PIN_B, actor_id=AUTH["partner"])
    assert state["locked_financial_years"] == ["2025-26"]


def test_a_firm_that_never_had_a_pin_adopts_the_first_one_into_the_table(service, backfilled):
    yls, api_db = service
    assert yls.get_state(api_db, FIRM_D)["pin_set"] is False
    state = yls.set_lock(api_db, FIRM_D, "2024-25", True, pin="Tr0ub4dor&3", actor_id=AUTH["partner"])
    assert state["pin_set"] is True
    assert _ok(backfilled, f"SELECT pin_hash LIKE 'pbkdf2_sha256$%' FROM firm_lock_pins WHERE firm_id = '{FIRM_D}';") == "t"
    assert _ok(backfilled, f"SELECT lock_pin IS NULL FROM firms WHERE id = '{FIRM_D}';") == "t"


def test_a_second_first_pin_loses_the_race_with_the_databases_own_key(service):
    from fastapi import HTTPException
    yls, api_db = service
    with pytest.raises(HTTPException) as e:
        yls._adopt_pin(api_db, FIRM, "Another-1")        # FIRM already has a row: the primary key refuses it
    assert e.value.status_code == 409


# ── the negative control ─────────────────────────────────────────────────────

def test_its_own_rollback_puts_the_hole_back_and_a_second_run_closes_it(backfilled):
    """Without 480 a Reviewer reads the plaintext PIN of their own firm out of `firms`; with it re-applied they
    read nothing. Rolled back, the PINs are gone (a hash cannot be reversed), so the control seeds one."""
    r = _psql(backfilled, ROLLBACK.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert _ok(backfilled, "SELECT to_regclass('public.firm_lock_pins') IS NULL;") == "t"
    _ok(backfilled, f"UPDATE firms SET lock_pin = '{PIN_A}' WHERE id = '{FIRM}';")
    read = _as(backfilled, "authenticated", f"SELECT lock_pin FROM firms WHERE id = '{FIRM}';", AUTH["reviewer"])
    assert read.returncode == 0 and PIN_A in read.stdout, "with 480 rolled back the Reviewer reads the PIN"
    assert _psql(backfilled, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    closed = _as(backfilled, "authenticated", f"SELECT lock_pin FROM firms WHERE id = '{FIRM}';", AUTH["reviewer"])
    assert closed.returncode == 0 and PIN_A not in closed.stdout

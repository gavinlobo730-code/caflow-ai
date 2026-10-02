"""Migration 478 — only a Partner may change who is assigned to a client.

THE BUG THIS PINS (found by the role-by-table matrix, security_privacy-34)
    `user_client_assignments` carried one write policy, `partners_manage_assignments`
    (FOR ALL TO authenticated, firm_id = get_my_firm_id(), no role test) — and the
    table is what `can_access_client()` reads to decide which clients a
    non-Partner may see. Any member of the firm could insert a row naming
    themselves and any client, then read that client's books.

WHAT IS ASSERTED, AND WHY IT IS A DATABASE FACT
    * the call the API actually makes — `assignment_repo.create` / `remove` /
      `list_for_*`, UNMODIFIED, over a real session running as `authenticated`
      with a Partner's JWT claim — still creates, lists and deletes an
      assignment. That is the path that must not break, and the approval
      executor (`services/approval_service.py`) goes through the same methods;
    * the same calls with a Reviewer's, an Executive's, a Manager's and a
      suspended Partner's claim are refused, and the refusal is the database's;
    * the exploit itself, end to end: an Executive assigned to nothing cannot
      assign themselves to a client, and still sees none of its rows;
    * the policy asks `my_permission('assignment','write','Partner')`, the
      function `rbac("assignment","write")` resolves through, so a per-person
      grant lets a non-Partner write exactly as the route would, and a denial
      stops a Partner exactly as the route would;
    * a Partner still reaches only their OWN firm's rows;
    * the SELECT policy is untouched (an Executive must read their own rows:
      `core.authz.assigned_client_ids` does, under the caller's JWT);
    * 478 is idempotent, and its own rollback puts the hole back — the
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
MIGRATION = API_ROOT / "migrations" / "478_only_a_partner_may_change_who_is_assigned_to_a_client.sql"
ROLLBACK = API_ROOT / "migrations" / "478_only_a_partner_may_change_who_is_assigned_to_a_client_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the assignment-policy proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000478"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000479"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a478"
CLIENT_B = "cccccccc-0000-0000-0000-00000000b478"
CLIENT_OTHER = "cccccccc-0000-0000-0000-00000000c478"

AUTH = {
    "partner": "11111111-1111-1111-1111-111111111478",
    "manager": "22222222-2222-2222-2222-222222222478",
    "exec": "33333333-3333-3333-3333-333333333478",
    "reviewer": "44444444-4444-4444-4444-444444444478",
    "suspended": "55555555-5555-5555-5555-555555555478",
    "other_partner": "66666666-6666-6666-6666-666666666478",
}
USER = {k: v.replace(v[:8], "bbbbbbbb", 1) for k, v in AUTH.items()}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"rlsmatrix_m478_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m478.test')" for k, v in AUTH.items())
        users = ", ".join(
            f"('{USER[k]}', '{FIRM if k != 'other_partner' else OTHER_FIRM}', '{AUTH[k]}', '{k}@m478.test', "
            f"'{k}', '{role}', {active})"
            for k, role, active in (("partner", "Partner", "true"), ("manager", "Manager", "true"),
                                    ("exec", "Executive", "true"), ("reviewer", "Reviewer", "true"),
                                    ("suspended", "Partner", "false"), ("other_partner", "Partner", "true")))
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M478 Firm','m478@test.in'), ('{OTHER_FIRM}','M478 Other','m478o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B','Private Limited'),
              ('{CLIENT_OTHER}','{OTHER_FIRM}','Client Other','Private Limited');
            INSERT INTO vendors (firm_id, client_id, name) VALUES ('{FIRM}','{CLIENT_B}','Secret Vendor of B');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── the API's own repository, over a real session ───────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Just enough of the Supabase builder for AssignmentRepository, which is
    called UNMODIFIED. Every call is a real statement run as `authenticated`
    with the caller's JWT claim, and a refusal raises, as PostgREST's 4xx does."""

    def __init__(self, dsn: str, auth: str, table: str):
        self._dsn, self._auth, self._table = dsn, auth, table
        self._cols = "*"
        self._filters: list[tuple[str, str]] = []
        self._limit: int | None = None
        self._op = "select"
        self._row: dict | None = None

    def select(self, cols="*"):
        self._cols = cols
        return self

    def eq(self, col, val):
        self._filters.append((col, str(val)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self._op, self._row = "insert", row
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        where = " AND ".join(f"{c} = '{v}'" for c, v in self._filters)
        where = f" WHERE {where}" if where else ""
        t = self._table
        if self._op == "select":
            inner = f"SELECT {self._cols} FROM {t}{where}" + (f" LIMIT {self._limit}" if self._limit else "")
            sql = f"SELECT coalesce(json_agg(q), '[]'::json) FROM ({inner}) q"
        elif self._op == "insert":
            cols = ", ".join(self._row)
            vals = ", ".join(f"'{v}'" for v in self._row.values())
            sql = (f"WITH i AS (INSERT INTO {t} ({cols}) VALUES ({vals}) RETURNING *) "
                   f"SELECT coalesce(json_agg(i), '[]'::json) FROM i")
        else:
            sql = (f"WITH d AS (DELETE FROM {t}{where} RETURNING *) "
                   f"SELECT coalesce(json_agg(d), '[]'::json) FROM d")
        script = (f"SET request.jwt.claims = '{json.dumps({'sub': self._auth, 'role': 'authenticated'})}'; "
                  f"SET ROLE authenticated; {sql};")
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", script],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("[")]
        return _Result(json.loads(lines[-1]) if lines else [])


class _AuthDb:
    def __init__(self, dsn: str, auth: str):
        self._dsn, self._auth = dsn, auth

    def table(self, name: str):
        return _Query(self._dsn, self._auth, name)


@pytest.fixture()
def repo_as(db, monkeypatch):
    """`assignment_repo` as a given member: the real class, the real module
    functions, the production code path (`_USE_MOCK` off, the request client)."""
    import repositories.assignment_repository as repo_mod

    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)

    def _as(member: str):
        monkeypatch.setattr(repo_mod, "_db", lambda: _AuthDb(db, AUTH[member]))
        return repo_mod.assignment_repo

    return _as


def _rows(dsn: str, where: str = "TRUE") -> int:
    return int(_ok(dsn, f"SELECT count(*) FROM user_client_assignments WHERE {where};"))


# ── a Partner still does the job ─────────────────────────────────────────────
def test_a_partner_creates_lists_and_deletes_an_assignment_through_the_repository(db, repo_as):
    repo = repo_as("partner")
    row = repo.create(FIRM, USER["exec"], CLIENT_A)
    assert row["user_id"] == USER["exec"] and row["client_id"] == CLIENT_A and row["firm_id"] == FIRM
    assert _rows(db, f"user_id = '{USER['exec']}' AND client_id = '{CLIENT_A}'") == 1
    assert repo.list_for_user(FIRM, USER["exec"]) == [CLIENT_A]
    assert repo.list_for_client(FIRM, CLIENT_A) == [USER["exec"]]
    assert repo.exists(FIRM, USER["exec"], CLIENT_A) is True
    # create is idempotent: the second call finds the row and writes nothing
    assert repo.create(FIRM, USER["exec"], CLIENT_A)["id"] == row["id"]
    assert _rows(db, f"user_id = '{USER['exec']}'") == 1
    assert repo.remove(FIRM, USER["exec"], CLIENT_A) is True
    assert _rows(db, f"user_id = '{USER['exec']}'") == 0
    assert repo.remove(FIRM, USER["exec"], CLIENT_A) is False


def test_the_approval_executors_calls_work_for_a_partner(db, repo_as):
    """services/approval_service assigns, unassigns and reassigns through the
    same two methods, behind approval:approve (Partner only)."""
    repo = repo_as("partner")
    repo.create(FIRM, USER["reviewer"], CLIENT_A)
    repo.remove(FIRM, USER["reviewer"], CLIENT_A)
    repo.create(FIRM, USER["reviewer"], CLIENT_B)
    assert repo.list_for_user(FIRM, USER["reviewer"]) == [CLIENT_B]


def test_a_partner_can_still_update_a_row_and_cannot_move_it_to_another_firm(db):
    _ok(db, f"INSERT INTO user_client_assignments (id, firm_id, user_id, client_id) "
            f"VALUES ('dddddddd-0000-0000-0000-000000000478','{FIRM}','{USER['exec']}','{CLIENT_A}');")

    def as_partner(sql: str) -> subprocess.CompletedProcess:
        return _psql(db, f"SET request.jwt.claims = '{json.dumps({'sub': AUTH['partner'], 'role': 'authenticated'})}'; "
                         f"SET ROLE authenticated; {sql}")

    ok = as_partner(f"UPDATE user_client_assignments SET client_id = '{CLIENT_B}' "
                    f"WHERE id = 'dddddddd-0000-0000-0000-000000000478';")
    assert ok.returncode == 0, ok.stderr
    assert _rows(db, f"client_id = '{CLIENT_B}'") == 1
    moved = as_partner(f"UPDATE user_client_assignments SET firm_id = '{OTHER_FIRM}' "
                       f"WHERE id = 'dddddddd-0000-0000-0000-000000000478';")
    assert moved.returncode != 0 and "row-level security" in moved.stderr, moved.stderr
    assert _rows(db, f"firm_id = '{OTHER_FIRM}'") == 0


def test_another_firms_partner_neither_sees_nor_writes_this_firms_assignments(db, repo_as):
    repo_as("partner").create(FIRM, USER["exec"], CLIENT_A)
    other = repo_as("other_partner")
    assert other.list_for_client(FIRM, CLIENT_A) == []
    with pytest.raises(RuntimeError, match="row-level security"):
        other.create(FIRM, USER["exec"], CLIENT_B)
    assert other.remove(FIRM, USER["exec"], CLIENT_A) is False
    assert _rows(db, f"user_id = '{USER['exec']}'") == 1


# ── nobody else does ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("member", ["manager", "exec", "reviewer", "suspended"])
def test_no_other_member_can_create_an_assignment(db, repo_as, member):
    with pytest.raises(RuntimeError, match="row-level security"):
        repo_as(member).create(FIRM, USER["exec"], CLIENT_B)
    assert _rows(db) == 0


@pytest.mark.parametrize("member", ["manager", "exec", "reviewer", "suspended"])
def test_no_other_member_can_remove_or_rewrite_a_partners_assignment(db, repo_as, member):
    repo_as("partner").create(FIRM, USER["reviewer"], CLIENT_A)
    assert repo_as(member).remove(FIRM, USER["reviewer"], CLIENT_A) is False
    assert _rows(db, f"user_id = '{USER['reviewer']}'") == 1
    upd = _psql(db, f"SET request.jwt.claims = '{json.dumps({'sub': AUTH[member], 'role': 'authenticated'})}'; "
                    f"SET ROLE authenticated; "
                    f"WITH u AS (UPDATE user_client_assignments SET client_id = '{CLIENT_B}' RETURNING 1) "
                    f"SELECT count(*) FROM u;")
    assert upd.returncode == 0, upd.stderr
    assert _rows(db, f"client_id = '{CLIENT_B}'") == 0


def test_an_executive_assigned_to_nothing_cannot_assign_themselves_and_still_sees_nothing(db, repo_as):
    """The exploit the matrix found, end to end."""
    def visible_vendors() -> int:
        r = _psql(db, f"SET request.jwt.claims = '{json.dumps({'sub': AUTH['exec'], 'role': 'authenticated'})}'; "
                      f"SET ROLE authenticated; SELECT count(*) FROM vendors WHERE client_id = '{CLIENT_B}';")
        assert r.returncode == 0, r.stderr
        return int(r.stdout.strip().splitlines()[-1])

    assert visible_vendors() == 0
    with pytest.raises(RuntimeError, match="row-level security"):
        repo_as("exec").create(FIRM, USER["exec"], CLIENT_B)
    assert visible_vendors() == 0


# ── the same question the route asks ─────────────────────────────────────────
def _grant(db: str, member: str, granted: bool) -> None:
    _ok(db, f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
            f"VALUES ('{FIRM}','{USER[member]}','assignment','write', {str(granted).lower()});")


def test_a_per_person_grant_lets_a_non_partner_write_exactly_as_the_route_would(db, repo_as):
    with pytest.raises(RuntimeError, match="row-level security"):
        repo_as("manager").create(FIRM, USER["exec"], CLIENT_A)
    _grant(db, "manager", True)
    assert repo_as("manager").create(FIRM, USER["exec"], CLIENT_A)["client_id"] == CLIENT_A
    assert repo_as("manager").remove(FIRM, USER["exec"], CLIENT_A) is True


def test_a_per_person_denial_stops_a_partner_exactly_as_the_route_would(db, repo_as):
    _grant(db, "partner", False)
    with pytest.raises(RuntimeError, match="row-level security"):
        repo_as("partner").create(FIRM, USER["exec"], CLIENT_A)
    assert _rows(db) == 0


# ── the shape ────────────────────────────────────────────────────────────────
def test_the_policies_are_one_select_and_three_partner_writes(db):
    rows = _ok(db, "SELECT policyname || '|' || cmd || '|' || permissive || '|' || roles::text "
                   "FROM pg_policies WHERE tablename = 'user_client_assignments' ORDER BY policyname;").splitlines()
    assert rows == [
        "firm_members_see_assignments|SELECT|PERMISSIVE|{authenticated}",
        "partners_delete_assignments|DELETE|PERMISSIVE|{authenticated}",
        "partners_insert_assignments|INSERT|PERMISSIVE|{authenticated}",
        "partners_update_assignments|UPDATE|PERMISSIVE|{authenticated}",
    ], rows
    for name in ("partners_insert_assignments", "partners_update_assignments", "partners_delete_assignments"):
        body = _ok(db, f"SELECT coalesce(qual,'') || ' ' || coalesce(with_check,'') FROM pg_policies "
                       f"WHERE policyname = '{name}';")
        assert "get_my_firm_id" in body and "my_permission" in body and "'assignment'" in body, (name, body)


def test_the_select_policy_is_untouched_so_a_member_still_reads_their_own_rows(db, repo_as):
    repo_as("partner").create(FIRM, USER["exec"], CLIENT_A)
    assert repo_as("exec").list_for_user(FIRM, USER["exec"]) == [CLIENT_A]


def test_478_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text())
        assert r.returncode == 0, r.stderr
    assert _ok(db, "SELECT count(*) FROM pg_policies WHERE tablename = 'user_client_assignments';") == "4"


def test_its_own_rollback_puts_the_hole_back_and_a_second_run_closes_it(db, repo_as):
    """The negative control: without 478 an Executive assigned to nothing
    assigns themselves; with it re-applied they cannot."""
    r = _psql(db, ROLLBACK.read_text())
    assert r.returncode == 0, r.stderr
    policy = _ok(db, "SELECT cmd FROM pg_policies WHERE policyname = 'partners_manage_assignments';")
    assert policy == "ALL"
    row = repo_as("exec").create(FIRM, USER["exec"], CLIENT_B)
    assert row["client_id"] == CLIENT_B, "with 478 rolled back the Executive assigned themselves"
    _ok(db, "DELETE FROM user_client_assignments;")
    assert _psql(db, MIGRATION.read_text()).returncode == 0
    with pytest.raises(RuntimeError, match="row-level security"):
        repo_as("exec").create(FIRM, USER["exec"], CLIENT_B)

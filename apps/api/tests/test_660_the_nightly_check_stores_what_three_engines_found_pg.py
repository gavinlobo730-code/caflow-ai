"""Migration 660 on a real database: the nightly results are read by the members assigned to the client and written by the API only
(POST-A-050).

WHAT ONLY POSTGRES CAN PROVE
    * the shape: one row per (client, engine); a `not_computed` row with a count, an amount or no reason is refused, as is a
      `computed` row with no count or a reason, an unknown engine and an unknown status, so a row can never read as a zero it did
      not measure;
    * the privileges: the signed-in role reads and holds no write (table or column), anon holds nothing, the service role writes;
    * the policies, as each person: a Partner reads every client's rows; a Manager assigned to A reads A's and no other; a member
      assigned to nothing and a Partner of another firm read none; the internal practice's rows are a Partner's;
    * the forgeries: a signed-in insert, update and delete are refused and the rows stay;
    * the migration runs twice and its rollback removes the table, after which it applies again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
# Named in full: "660_*.sql" matches the rollback too, and which of the two a directory listing gives first depends on the machine
# (the real-database job once ran the rollback as "the migration" and the table was gone; POST-A-574).
MIGRATION = API_ROOT / "migrations" / "660_the_nightly_check_stores_what_three_engines_found_for_each_client.sql"
ROLLBACK = API_ROOT / "migrations" / "660_the_nightly_check_stores_what_three_engines_found_for_each_client_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

T = "public.nightly_exception_results"
FIRM, OTHER_FIRM = "66000000-0000-0000-0000-000000000001", "66000000-0000-0000-0000-000000000002"
CLIENT_A, CLIENT_B = "66000000-0000-0000-0000-0000000000a1", "66000000-0000-0000-0000-0000000000b2"
INTERNAL, FOREIGN = "66000000-0000-0000-0000-0000000000c3", "66000000-0000-0000-0000-0000000000d4"
STRANGER = "66000000-1111-0000-0000-0000000000ff"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("66000000-0000-0000-0000-00000000000a", "66000000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("66000000-0000-0000-0000-00000000000b", "66000000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_internal": ("66000000-0000-0000-0000-00000000000d", "66000000-1111-0000-0000-000000000004", "Manager", FIRM),
    "manager_none": ("66000000-0000-0000-0000-00000000000c", "66000000-1111-0000-0000-000000000003", "Manager", FIRM),
    "other_firm": ("66000000-0000-0000-0000-000000000010", "66000000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _sub(who: str) -> str:
    return STRANGER if who == "stranger" else PEOPLE[who][1]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{_sub(who)}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _rows_as(dsn: str, who: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
                        _as(who) + f"SELECT engine || ':' || client_id::text FROM {T} ORDER BY 1;"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _refused_as(dsn: str, who: str, dml: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + dml], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr


def _insert(dsn: str, client: str, engine: str, status: str, count: str, reason: str, *, firm: str = FIRM, amount: str = "NULL") -> subprocess.CompletedProcess:
    return _psql(dsn, f"INSERT INTO {T} (firm_id, client_id, engine, status, as_of_date, count, amount_paise, reason) "
                      f"VALUES ('{firm}', '{client}', '{engine}', '{status}', current_date, {count}, {amount}, {reason});")


def _seed_rows(d: str) -> None:
    for client, firm in ((CLIENT_A, FIRM), (CLIENT_B, FIRM), (INTERNAL, FIRM), (FOREIGN, OTHER_FIRM)):
        assert _insert(d, client, "duplicate_bills", "computed", "0", "NULL", firm=firm).returncode == 0


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e660_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items()) + f", ('{STRANGER}', 'employee@t.in')"
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        _ok(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship'),
                ('{FOREIGN}', '{OTHER_FIRM}', 'X', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
                ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["manager_internal"][0]}', '{INTERNAL}');
        """)
        _seed_rows(d)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_nil_is_never_a_zero_and_the_vocabulary_is_closed(dsn):
    ok = lambda *a, **k: _insert(dsn, *a, **k).returncode == 0
    assert not ok(CLIENT_A, "gstr_2b", "not_computed", "0", "'x'")                  # a zero that was not measured
    assert not ok(CLIENT_A, "gstr_2b", "not_computed", "NULL", "NULL")             # no reason
    assert not ok(CLIENT_A, "gstr_2b", "not_computed", "NULL", "'  '")             # a blank reason
    assert not ok(CLIENT_A, "gstr_2b", "not_computed", "NULL", "'x'", amount="5")  # an amount it did not measure
    assert not ok(CLIENT_A, "gstr_2b", "computed", "NULL", "NULL")                 # computed with no count
    assert not ok(CLIENT_A, "gstr_2b", "computed", "-1", "NULL")                   # a negative count
    assert not ok(CLIENT_A, "gstr_2b", "computed", "1", "'x'")                     # computed with a reason
    assert not ok(CLIENT_A, "rule_37a", "computed", "1", "NULL")                   # the engine with no data source
    assert not ok(CLIENT_A, "gstr_2b", "maybe", "1", "NULL")
    assert ok(CLIENT_A, "gstr_2b", "not_computed", "NULL", "'No 2B reconciled'")
    assert ok(CLIENT_A, "recurring_journals", "computed", "3", "NULL", amount="NULL")


def test_one_row_per_client_and_engine(dsn):
    r = _insert(dsn, CLIENT_A, "duplicate_bills", "computed", "1", "NULL")
    assert r.returncode != 0 and "nightly_exception_results_one_per_client_and_engine" in r.stderr


def test_the_engines_the_check_allows_are_the_modules(dsn):
    from domain.practice import nightly_results as nr
    defn = _val(dsn, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'nightly_exception_results_engine_is_known'")
    assert tuple(re.findall(r"'([a-z_0-9]+)'::text", defn)) == nr.ENGINES


def test_the_signed_in_role_reads_and_holds_no_write_anon_holds_nothing_and_the_service_role_writes(dsn):
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        for role in ("authenticated", "anon"):
            assert _val(dsn, f"SELECT has_table_privilege('{role}', '{T}', '{verb}')") == "f", (role, verb)
    for verb in ("INSERT", "UPDATE"):
        assert _val(dsn, f"SELECT has_any_column_privilege('authenticated', '{T}', '{verb}')") == "f", verb
    assert _val(dsn, f"SELECT has_table_privilege('authenticated', '{T}', 'SELECT')") == "t"
    assert _val(dsn, f"SELECT has_table_privilege('anon', '{T}', 'SELECT')") == "f"
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _val(dsn, f"SELECT has_table_privilege('service_role', '{T}', '{verb}')") == "t", verb
    assert _val(dsn, f"SELECT relrowsecurity FROM pg_class WHERE oid = '{T}'::regclass") == "t"


def test_each_person_reads_the_rows_of_the_clients_they_may_see_and_no_other(dsn):
    mine = lambda c: f"duplicate_bills:{c}"
    assert _rows_as(dsn, "partner") == sorted([mine(CLIENT_A), mine(CLIENT_B), mine(INTERNAL)])
    assert _rows_as(dsn, "manager_a") == [mine(CLIENT_A)]
    assert _rows_as(dsn, "manager_internal") == []                        # the internal practice is a Partner's
    assert _rows_as(dsn, "manager_none") == []
    assert _rows_as(dsn, "other_firm") == [mine(FOREIGN)]
    assert _rows_as(dsn, "stranger") == []


def test_a_signed_in_member_can_neither_insert_nor_rewrite_nor_delete_a_row(dsn):
    for who in ("partner", "manager_a"):
        assert _refused_as(dsn, who, f"INSERT INTO {T} (firm_id, client_id, engine, status, as_of_date, count) "
                                     f"VALUES ('{FIRM}', '{CLIENT_A}', 'gstr_2b', 'computed', current_date, 0);")
        assert _refused_as(dsn, who, f"UPDATE {T} SET count = 99 WHERE client_id = '{CLIENT_A}';")
        assert _refused_as(dsn, who, f"DELETE FROM {T} WHERE client_id = '{CLIENT_A}';")
    assert _val(dsn, f"SELECT count(*) FROM {T} WHERE firm_id = '{FIRM}'") == "3"


def test_a_row_naming_another_firms_client_is_refused_by_the_firm_check(dsn):
    r = _insert(dsn, FOREIGN, "gstr_2b", "computed", "0", "NULL")           # a FIRM row naming OTHER_FIRM's client
    assert r.returncode != 0 and "belong to another firm" in r.stderr, r.stderr


def test_the_migration_runs_twice_and_its_rollback_removes_the_table_which_then_applies_again(dsn):
    _run(dsn, MIGRATION)
    assert _val(dsn, f"SELECT count(*) FROM {T}") == "4"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, "SELECT to_regclass('public.nightly_exception_results') IS NULL") == "t"
    _run(dsn, MIGRATION)
    assert _insert(dsn, CLIENT_A, "gstr_2b", "computed", "0", "NULL").returncode == 0

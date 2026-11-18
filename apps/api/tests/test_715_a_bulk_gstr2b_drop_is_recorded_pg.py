"""Migration 715 on a real database: a bulk GSTR-2B drop and what it did to each file are written and read by the API only (POST-A-057).

WHAT ONLY POSTGRES CAN PROVE
    * the shape: a file row's status is one the service answers; a reconciled row has counts and a refused one has a sentence and no
      counts; a month is MMYYYY; the problems are a list;
    * the tenancy: a file row names a drop of its own firm (the composite key) and a client of its own firm (the firm trigger), and a
      drop names a member of its own firm;
    * the privileges: neither the signed-in role nor anon holds any privilege on either table, the service role writes both, and a
      signed-in select, insert, update and delete are refused;
    * the migration runs twice and its rollback removes both tables, after which it applies again.

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
MIGRATION = next(p for p in API_ROOT.glob("migrations/715_*.sql") if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/715_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

DROPS, FILES = "public.gstr2b_bulk_drops", "public.gstr2b_bulk_drop_files"
FIRM, OTHER_FIRM = "71500000-0000-0000-0000-000000000001", "71500000-0000-0000-0000-000000000002"
CLIENT_A, FOREIGN = "71500000-0000-0000-0000-0000000000a1", "71500000-0000-0000-0000-0000000000d4"
DROP, FOREIGN_DROP = "71500000-0000-0000-0000-0000000000e1", "71500000-0000-0000-0000-0000000000e2"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("71500000-0000-0000-0000-00000000000a", "71500000-1111-0000-0000-000000000001", "Partner", FIRM),
    "other_firm": ("71500000-0000-0000-0000-000000000010", "71500000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
ME = PEOPLE["partner"][0]


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


def _as(who: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; "
            "SET ROLE authenticated; ")


def _refused_as(dsn: str, who: str, sql: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + sql], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr


def _file(dsn: str, *, status: str = "reconciled", summary: str = "'{\"matched_count\": 1}'", reason: str = "NULL",
          client: str = CLIENT_A, firm: str = FIRM, drop: str = DROP, period: str = "'062026'",
          problems: str = "'[]'") -> subprocess.CompletedProcess:
    client_sql = "NULL" if client is None else f"'{client}'"
    return _psql(dsn, f"INSERT INTO {FILES} (firm_id, drop_id, client_id, name, status, reason, gstin, period, summary, problems) "
                      f"VALUES ('{firm}', '{drop}', {client_sql}, 'a.json', '{status}', {reason}, '27AAAAA0000A1Z5', {period}, "
                      f"{summary}, {problems});")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e715_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        _ok(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{FOREIGN}', '{OTHER_FIRM}', 'X', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO {DROPS} (id, firm_id, created_by) VALUES ('{DROP}', '{FIRM}', '{ME}'),
                ('{FOREIGN_DROP}', '{OTHER_FIRM}', '{PEOPLE["other_firm"][0]}');
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_row_says_what_it_is(dsn):
    assert _file(dsn).returncode == 0
    assert _file(dsn, status="unmatched_gstin", summary="NULL", reason="'No client of yours holds it.'", client=None).returncode == 0
    assert _file(dsn, summary="NULL").returncode != 0                                         # reconciled with no counts
    assert _file(dsn, status="refused", summary="NULL").returncode != 0                       # refused with no sentence
    assert _file(dsn, status="refused", summary="NULL", reason="'  '").returncode != 0        # a blank sentence
    assert _file(dsn, status="refused", reason="'why'").returncode != 0                       # refused with counts
    assert _file(dsn, status="maybe", summary="NULL", reason="'x'").returncode != 0
    assert _file(dsn, period="'132026'").returncode != 0
    assert _file(dsn, problems="'{}'").returncode != 0


def test_the_statuses_the_check_allows_are_the_services(dsn):
    from services import gst_2b_bulk_service as bulk
    defn = _val(dsn, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'gstr2b_bulk_drop_files_status_is_known'")
    assert tuple(re.findall(r"'([a-z_]+)'::text", defn)) == bulk.STATUSES


def test_a_file_row_names_a_drop_and_a_client_of_its_own_firm(dsn):
    r = _file(dsn, drop=FOREIGN_DROP)                                     # a FIRM row in OTHER_FIRM's drop
    assert r.returncode != 0 and "gstr2b_bulk_drop_files_drop_of_its_firm" in r.stderr, r.stderr
    r = _file(dsn, client=FOREIGN)                                        # a FIRM row naming OTHER_FIRM's client
    assert r.returncode != 0 and "belong to another firm" in r.stderr, r.stderr
    r = _psql(dsn, f"INSERT INTO {DROPS} (firm_id, created_by) VALUES ('{FIRM}', '{PEOPLE['other_firm'][0]}');")
    assert r.returncode != 0, "a drop naming another firm's member was stored"


def test_the_rows_answer_in_the_order_they_were_written(dsn):
    for _ in range(3):
        assert _file(dsn).returncode == 0
    seqs = _val(dsn, f"SELECT string_agg(seq::text, ',' ORDER BY created_at, seq) FROM {FILES}").split(",")
    assert [int(s) for s in seqs] == sorted(int(s) for s in seqs) and len(set(seqs)) == 3


def test_nothing_signed_in_reaches_either_table_and_the_service_role_writes(dsn):
    for t in (DROPS, FILES):
        for role in ("authenticated", "anon"):
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert _val(dsn, f"SELECT has_table_privilege('{role}', '{t}', '{verb}')") == "f", (t, role, verb)
            for verb in ("SELECT", "INSERT", "UPDATE"):
                assert _val(dsn, f"SELECT has_any_column_privilege('{role}', '{t}', '{verb}')") == "f", (t, role, verb)
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _val(dsn, f"SELECT has_table_privilege('service_role', '{t}', '{verb}')") == "t", (t, verb)
        assert _val(dsn, f"SELECT relrowsecurity FROM pg_class WHERE oid = '{t}'::regclass") == "t"
    assert _file(dsn).returncode == 0
    assert _refused_as(dsn, "partner", f"SELECT * FROM {FILES};")
    assert _refused_as(dsn, "partner", f"SELECT * FROM {DROPS};")
    assert _refused_as(dsn, "partner", f"INSERT INTO {DROPS} (firm_id, created_by) VALUES ('{FIRM}', '{ME}');")
    assert _refused_as(dsn, "partner", f"UPDATE {FILES} SET status = 'failed';")
    assert _refused_as(dsn, "partner", f"DELETE FROM {FILES};")
    assert _val(dsn, f"SELECT count(*) FROM {FILES}") == "1"


def test_the_migration_runs_twice_and_its_rollback_removes_both_tables_which_then_apply_again(dsn):
    assert _file(dsn).returncode == 0
    _run(dsn, MIGRATION)
    assert _val(dsn, f"SELECT count(*) FROM {FILES}") == "1"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, f"SELECT to_regclass('{FILES}') IS NULL AND to_regclass('{DROPS}') IS NULL") == "t"
    _run(dsn, MIGRATION)
    _ok(dsn, f"INSERT INTO {DROPS} (id, firm_id, created_by) VALUES ('{DROP}', '{FIRM}', '{ME}');")
    assert _file(dsn).returncode == 0


def test_a_drop_counts_its_unrecorded_files_from_nil_and_never_below(dsn):
    assert _val(dsn, f"SELECT unrecorded_files FROM {DROPS} WHERE id = '{DROP}'") == "0"
    _ok(dsn, f"UPDATE {DROPS} SET unrecorded_files = unrecorded_files + 2 WHERE id = '{DROP}';")
    assert _val(dsn, f"SELECT unrecorded_files FROM {DROPS} WHERE id = '{DROP}'") == "2"
    r = _psql(dsn, f"UPDATE {DROPS} SET unrecorded_files = -1 WHERE id = '{DROP}';")
    assert r.returncode != 0 and "gstr2b_bulk_drops_unrecorded_is_a_count" in r.stderr

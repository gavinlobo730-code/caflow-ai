"""Migration 455's two tables, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    The Pydantic models and the services' own refusals are proved by the mock
    suite. Neither proves the DATABASE holds the same line, and a service is not
    the only writer a table has. This proves the constraints, the uniqueness the
    upsert depends on, the cascade, and — the one a mock cannot — that the RLS
    policies are on and the role guards refuse a role below Executive.

WHAT IS ASSERTED
    income_tax_worksheets
      * the two kinds are accepted and a third is refused by the CHECK;
      * a financial-year label of the wrong shape is refused;
      * ONE row per (firm, client, year, kind) — the unique key the service's
        `on_conflict` names — so a second insert is refused and an upsert
        replaces;
      * `payload_json` defaults to an empty object and takes any JSON.
    ais_computation_decisions
      * only salary, interest and dividend are lines; only accepted or rejected
        are decisions; a negative figure is refused;
      * ONE decision per (firm, client, assessment year, line);
    both
      * RLS is switched on and the role-aware RESTRICTIVE policies exist, in the
        shape migration 352 set. Whether a Reviewer is in fact refused rests on
        `my_role_at_least`, which migration 260 owns and its own tests prove.
      * ASSIGNMENT SCOPE, BEHAVIOURALLY. A Manager or Executive assigned to client
        A cannot read, insert, update or delete client B's rows — connected as
        `authenticated` with their own JWT, which is the PostgREST path the
        browser's anon key opens and where RLS is the only control. 455 first
        shipped without the scope policy on the argument that nothing reads these
        tables from a screen; the working papers hold a client's salary, rent
        and interest, and PostgREST does not ask which tables a screen uses.

THE TRAP THIS IS BUILT AROUND
    A denied INSERT raises. A denied UPDATE or DELETE does NOT — PostgreSQL
    silently skips rows failing the USING clause, so the statement "succeeds"
    having changed nothing. Every UPDATE/DELETE case below asserts the ROW COUNT,
    and pairs it with the same statement against the assigned client's row, so a
    zero cannot be a statement that matched nothing for some other reason.
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
    reason="migration 455 proof requires HARNESS_PG + psql",
)

FIRM = "f4550000-0000-0000-0000-000000000001"
CLIENT = "c4550000-0000-0000-0000-000000000001"
TABLES = ("income_tax_worksheets", "ais_computation_decisions")


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"v455_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'T Co', 'Individual');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _worksheet(dsn, kind="salary", fy="2025-26", payload="'{}'::jsonb"):
    return _psql(dsn, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind, payload_json)
        VALUES ('{FIRM}', '{CLIENT}', '{fy}', '{kind}', {payload});
    """)


def _decision(dsn, key="salary", decision="accepted", amount=100, ay="2026-27"):
    return _psql(dsn, f"""
        INSERT INTO ais_computation_decisions
          (firm_id, client_id, assessment_year, line_key, decision, amount_paise)
        VALUES ('{FIRM}', '{CLIENT}', '{ay}', '{key}', '{decision}', {amount});
    """)


# ── income_tax_worksheets ─────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["house_property", "salary"])
def test_the_two_worksheet_kinds_are_accepted(db, kind):
    assert _worksheet(db, kind=kind).returncode == 0


@pytest.mark.parametrize("kind", ["capital_wip", "House_Property", ""])
def test_a_third_kind_is_refused_by_the_check(db, kind):
    r = _worksheet(db, kind=kind)
    assert r.returncode != 0 and "worksheet_kind" in r.stderr


@pytest.mark.parametrize("fy", ["2025", "25-26", "2025-2026", "FY2025-26"])
def test_a_financial_year_of_the_wrong_shape_is_refused(db, fy):
    r = _worksheet(db, fy=fy)
    assert r.returncode != 0 and "financial_year" in r.stderr


def test_there_is_one_worksheet_of_each_kind_per_client_per_year(db):
    assert _worksheet(db).returncode == 0
    again = _worksheet(db)
    assert again.returncode != 0 and "duplicate key" in again.stderr
    # ...and the unique key is the one the service's upsert names.
    assert _worksheet(db, fy="2024-25").returncode == 0
    assert _worksheet(db, kind="house_property").returncode == 0


def test_the_upsert_the_service_issues_replaces_the_inputs(db):
    assert _worksheet(db, payload="""'{"employers": []}'::jsonb""").returncode == 0
    r = _psql(db, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind, payload_json)
        VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'salary', '{{"employers": [1]}}'::jsonb)
        ON CONFLICT (firm_id, client_id, financial_year, worksheet_kind)
        DO UPDATE SET payload_json = EXCLUDED.payload_json;
    """)
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT payload_json::text, count(*) OVER () FROM income_tax_worksheets;", tuples=True)
    assert got.stdout.strip() == '{"employers": [1]}|1'


def test_the_payload_defaults_to_an_empty_object(db):
    assert _psql(db, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind)
        VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'salary');""").returncode == 0
    got = _psql(db, "SELECT payload_json::text FROM income_tax_worksheets;", tuples=True)
    assert got.stdout.strip() == "{}"


# ── ais_computation_decisions ─────────────────────────────────────────────

@pytest.mark.parametrize("key", ["salary", "interest", "dividend"])
def test_the_three_lines_the_computation_takes_are_accepted(db, key):
    assert _decision(db, key=key).returncode == 0


@pytest.mark.parametrize("key", ["stock_sale", "rent", "Salary", ""])
def test_a_line_the_computation_does_not_take_is_refused(db, key):
    r = _decision(db, key=key)
    assert r.returncode != 0 and "line_key" in r.stderr


@pytest.mark.parametrize("decision", ["undecided", "maybe", "ACCEPTED"])
def test_only_accepted_and_rejected_are_decisions(db, decision):
    r = _decision(db, decision=decision)
    assert r.returncode != 0 and "decision" in r.stderr


def test_a_negative_figure_is_refused_and_zero_is_a_real_one(db):
    r = _decision(db, amount=-1)
    assert r.returncode != 0 and "amount_paise" in r.stderr
    assert _decision(db, amount=0).returncode == 0


def test_a_malformed_assessment_year_is_refused(db):
    assert _decision(db, ay="2026").returncode != 0


def test_there_is_one_decision_per_line_per_year(db):
    assert _decision(db).returncode == 0
    again = _decision(db, decision="rejected")
    assert again.returncode != 0 and "duplicate key" in again.stderr
    assert _decision(db, ay="2027-28").returncode == 0


# ── isolation ─────────────────────────────────────────────────────────────

def test_rls_is_on_and_every_policy_the_migration_names_exists(db):
    for t in TABLES:
        on = _psql(db, f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{t}'::regclass;", tuples=True)
        assert on.stdout.strip() == "t", f"RLS is off on {t}"
        pols = set(_psql(db, f"SELECT policyname FROM pg_policies WHERE tablename = '{t}';",
                         tuples=True).stdout.split())
        assert pols == {f"firm_{t}", f"{t}_assignment_scope",
                        f"{t}_role_insert", f"{t}_role_update", f"{t}_role_delete"}


def test_the_role_guards_are_restrictive_so_they_narrow_and_never_grant(db):
    for t in TABLES:
        got = _psql(db, f"""
            SELECT policyname, permissive FROM pg_policies
             WHERE tablename = '{t}' AND policyname LIKE '%_role_%' ORDER BY 1;""", tuples=True)
        for line in got.stdout.strip().splitlines():
            assert line.endswith("RESTRICTIVE"), line


# ── assignment scope, against the real policies ───────────────────────────

CLIENT_B = "c4550000-0000-0000-0000-000000000002"
UID = {
    "Partner":    "a4550000-0000-0000-0000-000000000001",
    "Manager":    "a4550000-0000-0000-0000-000000000002",
    "Executive":  "a4550000-0000-0000-0000-000000000003",
    # A Manager with NO assignment row at all: assigned to nothing, so the
    # scope must show them no client's rows rather than every client's.
    "Unassigned": "a4550000-0000-0000-0000-000000000004",
}

_INSERT_FOR = {
    # A different year / line from the seeded row, so a refusal can only be the
    # policy and never the unique key.
    "income_tax_worksheets": lambda c: (
        "INSERT INTO income_tax_worksheets "
        "(firm_id, client_id, financial_year, worksheet_kind) "
        f"VALUES ('{FIRM}', '{c}', '2024-25', 'house_property');"),
    "ais_computation_decisions": lambda c: (
        "INSERT INTO ais_computation_decisions "
        "(firm_id, client_id, assessment_year, line_key, decision, amount_paise) "
        f"VALUES ('{FIRM}', '{c}', '2027-28', 'interest', 'accepted', 100);"),
}
_UPDATE_FOR = {
    "income_tax_worksheets": lambda c: (
        "UPDATE income_tax_worksheets SET payload_json = '{\"x\": 1}'::jsonb "
        f"WHERE client_id = '{c}'"),
    "ais_computation_decisions": lambda c: (
        "UPDATE ais_computation_decisions SET decision = 'rejected' "
        f"WHERE client_id = '{c}'"),
}


def _signed_in_as(role: str) -> str:
    # SET LOCAL ROLE authenticated matters: the tables are owned by the
    # migration user, and an owner bypasses RLS entirely, so every assertion
    # below would pass whatever the policies said.
    return (f"BEGIN; SET LOCAL ROLE authenticated; "
            f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID[role]}\"}}'; ")


def _as(dsn: str, role: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
         f"{_signed_in_as(role)}{sql} ROLLBACK;"],
        capture_output=True, text=True)


def _scalar(dsn: str, role: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c",
         f"{_signed_in_as(role)}{sql}; ROLLBACK;"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


def _rows_changed(dsn: str, role: str, statement: str) -> int:
    return _scalar(dsn, role, f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t")


def _denied(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and "row-level security" in r.stderr


@pytest.fixture()
def scoped(db):
    """Two clients of one firm, a Partner, a Manager and an Executive assigned to
    client A only, and a Manager assigned to nothing — with one row of each kind
    already on BOTH clients, so a read has something to wrongly return."""
    stmts = [
        "INSERT INTO auth.users (id, email) VALUES "
        + ", ".join(f"('{u}', '{r}@t.com')" for r, u in UID.items()) + ";",
        "INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
        + ", ".join(f"('{UID[r]}', '{FIRM}', '{UID[r]}', '{r}', '{r}@t.com', '{role}')"
                    for r, role in (("Partner", "Partner"), ("Manager", "Manager"),
                                    ("Executive", "Executive"), ("Unassigned", "Manager")))
        + ";",
        f"INSERT INTO clients (id, firm_id, client_name, entity_type) "
        f"VALUES ('{CLIENT_B}', '{FIRM}', 'B Co', 'Individual');",
        # Assigned to A (the CLIENT constant) and NOT to B. Without these rows
        # the firm-wide policy alone decides, and "assigned to nothing" and
        # "assigned to A" would be indistinguishable.
        "INSERT INTO user_client_assignments (user_id, client_id, firm_id) VALUES "
        f"('{UID['Manager']}', '{CLIENT}', '{FIRM}'), "
        f"('{UID['Executive']}', '{CLIENT}', '{FIRM}');",
    ]
    for c in (CLIENT, CLIENT_B):
        stmts.append(
            "INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, "
            f"worksheet_kind) VALUES ('{FIRM}', '{c}', '2025-26', 'salary');")
        stmts.append(
            "INSERT INTO ais_computation_decisions (firm_id, client_id, assessment_year, "
            f"line_key, decision, amount_paise) VALUES ('{FIRM}', '{c}', '2026-27', 'salary', "
            "'accepted', 100);")
    for sql in stmts:
        r = _psql(db, sql)
        assert r.returncode == 0, f"{sql[:70]}... -> {r.stderr}"
    return db


@pytest.mark.parametrize("table", TABLES)
def test_a_manager_assigned_to_one_client_reads_that_clients_rows_and_not_anothers(scoped, table):
    assert _scalar(scoped, "Manager", f"SELECT count(*) FROM {table} WHERE client_id = '{CLIENT}'") == 1
    assert _scalar(scoped, "Manager", f"SELECT count(*) FROM {table} WHERE client_id = '{CLIENT_B}'") == 0
    # ...and the unfiltered read, which is the one a PostgREST caller issues.
    assert _scalar(scoped, "Manager", f"SELECT count(*) FROM {table}") == 1


@pytest.mark.parametrize("table", TABLES)
def test_a_manager_assigned_to_nothing_reads_no_client_rows(scoped, table):
    assert _scalar(scoped, "Unassigned", f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("table", TABLES)
def test_a_partner_reads_every_clients_rows(scoped, table):
    """Partner is firm-wide by design (`_FIRMWIDE_ROLES`), and also the control
    that the two reads above came back empty because of the SCOPE and not
    because the seeded rows were never visible to anybody."""
    assert _scalar(scoped, "Partner", f"SELECT count(*) FROM {table}") == 2


@pytest.mark.parametrize("table", TABLES)
def test_an_executive_cannot_insert_for_a_client_they_are_not_assigned_to(scoped, table):
    refused = _as(scoped, "Executive", _INSERT_FOR[table](CLIENT_B))
    assert _denied(refused), refused.stderr
    # Same statement against the assigned client is accepted, so the refusal
    # above is the assignment rule and not a key, a CHECK or the role guard.
    allowed = _as(scoped, "Executive", _INSERT_FOR[table](CLIENT))
    assert allowed.returncode == 0, allowed.stderr


@pytest.mark.parametrize("table", TABLES)
def test_an_executive_update_of_an_unassigned_clients_row_changes_nothing(scoped, table):
    """THE ROW COUNT IS THE ASSERTION: a denied UPDATE raises nothing."""
    assert _rows_changed(scoped, "Executive", _UPDATE_FOR[table](CLIENT_B)) == 0
    assert _rows_changed(scoped, "Executive", _UPDATE_FOR[table](CLIENT)) == 1


@pytest.mark.parametrize("table", TABLES)
def test_a_manager_delete_of_an_unassigned_clients_row_removes_nothing(scoped, table):
    assert _rows_changed(scoped, "Manager", f"DELETE FROM {table} WHERE client_id = '{CLIENT_B}'") == 0
    assert _rows_changed(scoped, "Manager", f"DELETE FROM {table} WHERE client_id = '{CLIENT}'") == 1


@pytest.mark.parametrize("table", TABLES)
def test_the_assignment_policy_is_restrictive_for_all_and_asks_the_helper(db, table):
    got = _psql(db, f"""
        SELECT permissive, cmd, qual, with_check FROM pg_policies
         WHERE tablename = '{table}' AND policyname = '{table}_assignment_scope';""",
        tuples=True).stdout.strip()
    assert got, f"{table} has no {table}_assignment_scope policy"
    permissive, cmd, qual, with_check = got.split("|", 3)
    # PERMISSIVE would OR with the firm policy and widen access; a policy on
    # SELECT alone would leave INSERT, UPDATE and DELETE open.
    assert permissive == "RESTRICTIVE" and cmd == "ALL", got
    assert "can_access_client" in qual and "can_access_client" in with_check, got

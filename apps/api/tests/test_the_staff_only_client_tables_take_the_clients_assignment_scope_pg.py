"""Eleven client tables only the API uses take the client's assignment scope and the internal practice's Partner-only guard,
five tables follow the row they hang from (two of them are among the eleven, three have no client of their own: fourteen
tables in all), and the internal-practice guard of three tables with a nullable client learns that a row with no client is
not the practice's (migration 528, POST-A-299 first tranche).

WHAT WAS WRONG
    `ais_uploads`, `ais_records`, `ais_reconciliations`, `income_tax_asset_blocks`, `schedule_iii_ratio_explanations`,
    `schedule_iii_ratio_inputs`, `schedule_iii_unbilled_reviews`, `properties`, `recurring_invoice_templates`,
    `onboarding_checklists` and `tally_migration_jobs` carried a client and a firm policy (and a role tier on writes for
    some) and nothing per client; `tally_migration_items`, `onboarding_checklist_steps`, `recurring_invoice_runs` and the
    two AIS children read their parent's row through the same bare firm policy. A member of the firm assigned to no
    client could read, change and delete another client's rows over PostgREST, and insert into a client they are not
    assigned to.

WHAT THIS HOLDS (for each of the fourteen tables, the proof is the same)
    * THE POLICIES: the twenty-seven exist, RESTRICTIVE and FOR ALL, in the once-per-query form of migrations 525 to 527.
    * WHO SEES WHAT: a Partner reads the rows of client A, client B and the firm's internal practice; a Manager and an
      Executive assigned to A read A's and nothing else; a Manager assigned to nothing, a suspended Partner and a Partner
      of another firm read none of them; a Manager assigned to the internal practice as well still does not read its rows.
      A row with NO client (`properties`, `tally_migration_jobs`, and the items of such a job) stays open to the firm.
    * WHO CHANGES WHAT: an assigned Manager inserts, updates and deletes the rows of their own client; an insert for a
      client they are not assigned to is refused by the database, as is an update that MOVES a row to such a client or a
      child onto such a parent; an update or a delete of another client's row matches nothing. A Partner does all of it
      for every client, the internal practice included (the WITH CHECK keeps the Partner branch).
    * A ROW WITH NO CLIENT is open to the firm WHETHER OR NOT THE FIRM HAS AN INTERNAL PRACTICE: `NULL IS DISTINCT FROM NULL`
      is false, so a guard without a `client_id IS NULL OR` branch hid the row from, and refused it to, every non-Partner of
      a firm that never provisioned its practice. `properties`, `tally_migration_jobs` (and the items under such a job) and
      `knowledge_articles` (migration 079's guard, altered in place) are held in both states.
    * THE GUARD AND THE SCOPE ARE EXERCISED BY SOMEONE WHO IS NOT A PARTNER on an insert: a Manager assigned to the practice
      is refused its rows by the guard alone, and a client they cannot see by the scope alone, even on a parent that is theirs.
    * THE REFUSALS ARE THE POLICY'S: a unique key that would have refused a move for the wrong reason is cleared as the
      admin first (a replay with the migration rolled back gave the same `err` for six tables before that).
    * THE ROLLBACK returns the firm-wide behaviour exactly (and 079's expression on `knowledge_articles`), and a re-apply
      hides the rows again; a second run changes nothing; and the plan asks the caller's clients once per query.

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
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the staff-only client tables proof requires HARNESS_PG + psql",
)

FIRM = "52800000-0000-0000-0000-000000000001"
OTHER_FIRM = "52800000-0000-0000-0000-000000000002"
CLIENT_A = "52800000-0000-0000-0000-0000000000a1"
CLIENT_B = "52800000-0000-0000-0000-0000000000b2"
INTERNAL = "52800000-0000-0000-0000-0000000000c3"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("52800000-0000-0000-0000-00000000000a", "52800000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("52800000-0000-0000-0000-00000000000b", "52800000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("52800000-0000-0000-0000-00000000000c", "52800000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("52800000-0000-0000-0000-00000000000e", "52800000-1111-0000-0000-000000000004", "Executive", FIRM),
    "suspended": ("52800000-0000-0000-0000-00000000000f", "52800000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("52800000-0000-0000-0000-000000000010", "52800000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
PARTNER_ID = PEOPLE["partner"][0]

MIGRATION = next(p for p in MIGRATIONS.glob("528_the_staff_only_client_tables_take_the_clients_assignment_scope*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("528_the_staff_only_client_tables_take_the_clients_assignment_scope*_rollback.sql"))

_F = f"'{FIRM}'"

# ── one entry per table, in dependency order ────────────────────────────────────────────────────────────────────────
#   seed(client, tag)   an admin INSERT of one row for that client (children read their parent with a SELECT)
#   insert(client, parent)   a FRESH row for that client, as the person under test; `parent` is the id of the parent row
#   parent              (parent table, the column that points at it) for a table that hangs from another
#   own_client          the table carries a client_id of its own
#   null_row            also seed one row with NO client
#   clear               the seeded rows of A and B are removed (as the admin) before an insert is tried, because the
#                       table's unique key would refuse the second row for the wrong reason
#   collides            the table's unique key holds the client, so a row moved to a client that has one already would be
#                       refused for the wrong reason: the target's seeded row is removed first
#   parent_collides     the same for a move onto another parent (a unique key that holds the parent)
#   aux                 a row the insert must name that the person under test could not read for themselves (a customer)
#   before_delete       the dependants that block the row's delete (a foreign key without a cascade), removed as the admin
SPECS: dict[str, dict] = {}


def _spec(table: str, **kw) -> None:
    SPECS[table] = {"own_client": True, "null_row": False, "clear": False, "collides": False, "parent_collides": False,
                    "parent": None, "aux": None, "before_delete": None, **kw}


def _cl(client: str) -> str:
    return f"'{client}'"


_spec(
    "ais_uploads",
    seed=lambda c, t: f"INSERT INTO ais_uploads (firm_id, client_id, assessment_year, file_name) VALUES ({_F}, {_cl(c)}, '2025-26', 'ais-{t}.json')",
    insert=lambda c, p: f"INSERT INTO ais_uploads (firm_id, client_id, assessment_year) VALUES ({_F}, {_cl(c)}, '2026-27')",
)
_spec(
    "ais_records",
    seed=lambda c, t: (f"INSERT INTO ais_records (firm_id, client_id, upload_id, assessment_year) "
                       f"SELECT {_F}, client_id, id, '2025-26' FROM ais_uploads WHERE client_id = {_cl(c)}"),
    insert=lambda c, p: f"INSERT INTO ais_records (firm_id, client_id, upload_id, assessment_year) VALUES ({_F}, {_cl(c)}, '{p}', '2025-26')",
    parent=("ais_uploads", "upload_id"),
)
_spec(
    "ais_reconciliations",
    seed=lambda c, t: (f"INSERT INTO ais_reconciliations (firm_id, client_id, record_id, assessment_year) "
                       f"SELECT {_F}, client_id, id, '2025-26' FROM ais_records WHERE client_id = {_cl(c)}"),
    insert=lambda c, p: f"INSERT INTO ais_reconciliations (firm_id, client_id, record_id, assessment_year) VALUES ({_F}, {_cl(c)}, '{p}', '2025-26')",
    parent=("ais_records", "record_id"),
    clear=True,
)
_spec(
    "income_tax_asset_blocks",
    collides=True,
    seed=lambda c, t: (f"INSERT INTO income_tax_asset_blocks (firm_id, client_id, financial_year, block_key, rate_percent, opening_wdv_paise) "
                       f"VALUES ({_F}, {_cl(c)}, '2025-26', 'plant', 15, 100)"),
    insert=lambda c, p: (f"INSERT INTO income_tax_asset_blocks (firm_id, client_id, financial_year, block_key, rate_percent, opening_wdv_paise) "
                         f"VALUES ({_F}, {_cl(c)}, '2025-26', 'furniture', 10, 100)"),
)
_spec(
    "schedule_iii_ratio_explanations",
    collides=True,
    seed=lambda c, t: (f"INSERT INTO schedule_iii_ratio_explanations (firm_id, client_id, fy_label, ratio_key, explanation) "
                       f"VALUES ({_F}, {_cl(c)}, '2025-26', 'current_ratio', 'x')"),
    insert=lambda c, p: (f"INSERT INTO schedule_iii_ratio_explanations (firm_id, client_id, fy_label, ratio_key, explanation) "
                         f"VALUES ({_F}, {_cl(c)}, '2025-26', 'debt_equity', 'y')"),
)
_spec(
    "schedule_iii_ratio_inputs",
    collides=True,
    seed=lambda c, t: f"INSERT INTO schedule_iii_ratio_inputs (firm_id, client_id, fy_label) VALUES ({_F}, {_cl(c)}, '2025-26')",
    insert=lambda c, p: f"INSERT INTO schedule_iii_ratio_inputs (firm_id, client_id, fy_label) VALUES ({_F}, {_cl(c)}, '2026-27')",
)
_spec(
    "schedule_iii_unbilled_reviews",
    collides=True,
    seed=lambda c, t: f"INSERT INTO schedule_iii_unbilled_reviews (firm_id, client_id) VALUES ({_F}, {_cl(c)})",
    insert=lambda c, p: f"INSERT INTO schedule_iii_unbilled_reviews (firm_id, client_id) VALUES ({_F}, {_cl(c)})",
    clear=True,
)
_spec(
    "properties",
    seed=lambda c, t: f"INSERT INTO properties (firm_id, client_id, address) VALUES ({_F}, {'NULL' if c is None else _cl(c)}, 'p-{t}')",
    insert=lambda c, p: f"INSERT INTO properties (firm_id, client_id, address) VALUES ({_F}, {_cl(c)}, 'new')",
    null_row=True,
)
_spec(
    "recurring_invoice_templates",
    seed=lambda c, t: (f"INSERT INTO recurring_invoice_templates (firm_id, client_id, customer_id, title, frequency, start_date, next_run_date) "
                       f"SELECT {_F}, {_cl(c)}, id, 'tpl-{t}', 'monthly', '2026-04-01', '2026-05-01' FROM customers WHERE client_id = {_cl(c)}"),
    insert=lambda c, p: (f"INSERT INTO recurring_invoice_templates (firm_id, client_id, customer_id, title, frequency, start_date, next_run_date) "
                         f"VALUES ({_F}, {_cl(c)}, '{p}', 'new', 'monthly', '2026-04-01', '2026-05-01')"),
    aux=lambda c: f"SELECT id FROM customers WHERE client_id = '{c}' LIMIT 1",
)
_spec(
    "recurring_invoice_runs",
    seed=lambda c, t: (f"INSERT INTO recurring_invoice_runs (firm_id, template_id, occurrence_date) "
                       f"SELECT {_F}, id, '2026-05-01' FROM recurring_invoice_templates WHERE client_id = {_cl(c)}"),
    insert=lambda c, p: f"INSERT INTO recurring_invoice_runs (firm_id, template_id, occurrence_date) VALUES ({_F}, '{p}', '2026-06-01')",
    parent=("recurring_invoice_templates", "template_id"),
    own_client=False,
    parent_collides=True,
)
_spec(
    "onboarding_checklists",
    seed=lambda c, t: f"INSERT INTO onboarding_checklists (firm_id, client_id) VALUES ({_F}, {_cl(c)})",
    insert=lambda c, p: f"INSERT INTO onboarding_checklists (firm_id, client_id) VALUES ({_F}, {_cl(c)})",
)
_spec(
    "onboarding_checklist_steps",
    seed=lambda c, t: (f"INSERT INTO onboarding_checklist_steps (firm_id, workflow_id, step_number) "
                       f"SELECT {_F}, id, 1 FROM onboarding_checklists WHERE client_id = {_cl(c)}"),
    insert=lambda c, p: f"INSERT INTO onboarding_checklist_steps (firm_id, workflow_id, step_number) VALUES ({_F}, '{p}', 2)",
    parent=("onboarding_checklists", "workflow_id"),
    own_client=False,
)
_spec(
    "tally_migration_jobs",
    seed=lambda c, t: (f"INSERT INTO tally_migration_jobs (firm_id, client_id, name, source_file_name, target_financial_year, created_by) "
                       f"VALUES ({_F}, {'NULL' if c is None else _cl(c)}, 'job-{t}', 'f.xml', '2025-26', '{PARTNER_ID}')"),
    insert=lambda c, p: (f"INSERT INTO tally_migration_jobs (firm_id, client_id, name, source_file_name, target_financial_year, created_by) "
                         f"VALUES ({_F}, {_cl(c)}, 'new', 'f.xml', '2025-26', '{PARTNER_ID}')"),
    null_row=True,
    before_delete=lambda c: f"DELETE FROM tally_migration_items WHERE job_id IN (SELECT id FROM tally_migration_jobs WHERE client_id = '{c}')",
)
_spec(
    "tally_migration_items",
    seed=lambda c, t: (f"INSERT INTO tally_migration_items (firm_id, job_id, item_type) "
                       f"SELECT {_F}, id, 'ledger' FROM tally_migration_jobs WHERE client_id {'IS NULL' if c is None else '= ' + _cl(c)}"),
    insert=lambda c, p: f"INSERT INTO tally_migration_items (firm_id, job_id, item_type) VALUES ({_F}, '{p}', 'customer')",
    parent=("tally_migration_jobs", "job_id"),
    own_client=False,
    null_row=True,
)

#: Tables a signed-in session no longer writes at all (the API writes them as the server): the write proofs below have nothing to try
#: on them, and what keeps them closed is test_562_..._pg.py. The READ proofs still run.
NOT_WRITABLE_BY_A_SIGNED_IN_SESSION = {"recurring_invoice_templates"}
CLIENT_TABLES = [t for t, s in SPECS.items() if t not in {"ais_records", "ais_reconciliations", "tally_migration_items",
                                                          "onboarding_checklist_steps", "recurring_invoice_runs"}]
CHILD_TABLES = {t: s["parent"] for t, s in SPECS.items() if t not in CLIENT_TABLES}
POLICIES = {t: [f"{t}_assignment_scope", f"{t}_internal_partner_only"] for t in CLIENT_TABLES}
POLICIES.update({t: [f"{t}_parent_visible"] for t in CHILD_TABLES})


def _expected_reads(table: str) -> dict:
    if SPECS[table]["null_row"]:   # the row with no client is open to the firm, as it was
        return {"partner": 4, "manager_a": 2, "manager_none": 1, "executive_a": 2, "suspended": 0, "other_firm": 0}
    return {"partner": 3, "manager_a": 1, "manager_none": 0, "executive_a": 1, "suspended": 0, "other_firm": 0}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _count_as(dsn: str, who: str, table: str) -> int:
    return int(_lines_as(dsn, who, f"SELECT count(*) FROM {table};")[-1])


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err'; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _where_client(table: str, client: str) -> str:
    """The predicate that selects one client's seeded row of `table`, written so that it is the same for a client table and
    for a child (a child is selected through its parent, which is selected through its own client)."""
    spec = SPECS[table]
    if spec["own_client"]:
        return f"client_id = '{client}'"
    parent, col = spec["parent"]
    return f"{col} IN (SELECT id FROM {parent} WHERE {_where_client(parent, client)})"


def _parent_id(dsn: str, table: str, client: str) -> str | None:
    """The id the insert must name: the row the table hangs from, or the auxiliary row (a customer) it refers to."""
    aux = SPECS[table]["aux"]
    if aux:
        return _rows(dsn, aux(client))[0][0]
    parent = SPECS[table]["parent"]
    if not parent:
        return None
    return _rows(dsn, f"SELECT id FROM {parent[0]} WHERE {_where_client(parent[0], client)} LIMIT 1")[0][0]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e528_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
        members = ", ".join(
            f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', {'false' if n == 'suspended' else 'true'})"
            for n, (i, a, r, f) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                 VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}');
            INSERT INTO customers (firm_id, client_id, name)
                 VALUES ('{FIRM}', '{CLIENT_A}', 'cust A'), ('{FIRM}', '{CLIENT_B}', 'cust B'), ('{FIRM}', '{INTERNAL}', 'cust I');
        """)
        assert seed.returncode == 0, seed.stderr
        for table, spec in SPECS.items():
            clients = [(CLIENT_A, "A"), (CLIENT_B, "B"), (INTERNAL, "I")] + ([(None, "N")] if spec["null_row"] else [])
            for client, tag in clients:
                done = _psql(d, spec["seed"](client, tag))
                assert done.returncode == 0, f"seeding {table} for {tag}: {done.stderr}"
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE POLICIES ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", list(SPECS))
def test_the_policies_are_restrictive_for_all_and_ask_the_callers_clients_once_per_query(dsn, table):
    for name in POLICIES[table]:
        got = _rows(dsn, f"""SELECT p.polpermissive, p.polcmd, regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\\s+', ' ', 'g'),
                                    regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\\s+', ' ', 'g')
                               FROM pg_policy p WHERE p.polrelid = 'public.{table}'::regclass AND p.polname = '{name}'""")
        assert got, f"{table} has no {name} policy"
        permissive, cmd, qual, check = got[0]
        assert permissive == "f" and cmd == "*", f"{name} is not RESTRICTIVE FOR ALL: {got[0]}"
        assert qual and check, f"{name} has no USING or no WITH CHECK"
        assert "can_access_client" not in qual + check, f"{name} calls can_access_client once per row"
        if name.endswith("_assignment_scope"):
            assert "my_assigned_client_ids" in qual and "my_assigned_client_ids" in check, got[0]
            assert "Partner" in qual and "Partner" in check, f"{name}: a Partner's branch is missing from the USING or the WITH CHECK"
        if name.endswith("_internal_partner_only"):
            assert "my_internal_client_id" in qual and "Partner" in qual, got[0]
            assert "my_internal_client_id" in check and "Partner" in check, f"{name}: the WITH CHECK lost the guard or the Partner branch"
        if name.endswith("_parent_visible"):
            parent, col = CHILD_TABLES[table]
            assert parent in qual and parent in check and col in qual and col in check, got[0]


def test_the_template_lines_already_follow_their_template(dsn):
    """`recurring_invoice_template_lines` is not changed here because its own policy reads the template as the caller, so it
    follows the template's new scope. The migration's header says so; this keeps the sentence true."""
    got = _rows(dsn, "SELECT regexp_replace(string_agg(pg_get_expr(polqual, polrelid), ' '), '\\s+', ' ', 'g') FROM pg_policy "
                     "WHERE polrelid = 'public.recurring_invoice_template_lines'::regclass AND polpermissive")
    assert got and "recurring_invoice_templates" in got[0][0], got


# ── WHO SEES WHAT ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", list(SPECS))
def test_each_person_reads_only_the_rows_of_the_clients_they_may_see(dsn, table):
    seen = {who: _count_as(dsn, who, table) for who in PEOPLE}
    assert seen == _expected_reads(table), f"{table}: {seen}"


@pytest.mark.parametrize("table", list(SPECS))
def test_the_internal_practice_is_a_partners_even_for_a_person_assigned_to_it(dsn, table):
    assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                      f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    assert _count_as(dsn, "manager_a", table) == _expected_reads(table)["manager_a"], (
        f"{table}: an assignment to the internal practice opened its rows to a Manager")
    assert _count_as(dsn, "partner", table) == _expected_reads(table)["partner"]


# ── WHO CHANGES WHAT ────────────────────────────────────────────────────────────

def _clear_for_insert(dsn: str, table: str) -> None:
    """A table whose unique key would refuse a second row for A or B gives an `err` for the wrong reason: remove the seeded
    rows of A and B first, as the admin, so that only a policy can refuse the insert. Done for the child tables that hang
    from a cleared table too."""
    if SPECS[table]["clear"]:
        done = _psql(dsn, f"DELETE FROM {table} WHERE {_where_client(table, CLIENT_A)} OR {_where_client(table, CLIENT_B)}")
        assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("table", list(SPECS))
def test_an_assigned_manager_inserts_for_their_client_and_is_refused_for_another(dsn, table):
    if table in NOT_WRITABLE_BY_A_SIGNED_IN_SESSION:
        pytest.skip(f"{table}: the signed-in role holds no write on it (migration 562), so there is no write to scope; the effective privileges are held by test_562")
    spec = SPECS[table]
    parent_a, parent_b = _parent_id(dsn, table, CLIENT_A), _parent_id(dsn, table, CLIENT_B)
    _clear_for_insert(dsn, table)
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_A, parent_a)) == "1", (
        f"an assigned Manager cannot add a row to {table} for their own client")
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_B, parent_b)) == "err", (
        f"a row was added to {table} for a client the Manager is not assigned to")
    if spec["own_client"] and spec["parent"]:
        # the client of the Manager's own, hung from another client's parent: the parent is not theirs
        assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_A, parent_b)) == "err", (
            f"a row of the Manager's client was written onto another client's parent in {table}")
    assert _count_op(dsn, "manager_none", spec["insert"](CLIENT_A, parent_a)) == "err", (
        f"a Manager assigned to nothing added a row to {table}")


@pytest.mark.parametrize("table", list(SPECS))
def test_an_update_cannot_move_a_row_to_a_client_or_a_parent_the_person_may_not_see(dsn, table):
    spec = SPECS[table]
    if spec["collides"] or spec["clear"] or spec["parent_collides"]:
        # a unique key that holds the client or the parent would refuse the move for the wrong reason (it did, for six tables,
        # and the refusal read the same with the policy removed): take the target's rows away, as the admin, so that only a
        # policy can refuse the move
        assert _psql(dsn, f"DELETE FROM {table} WHERE {_where_client(table, CLIENT_B)}").returncode == 0
    if spec["own_client"]:
        assert _count_op(dsn, "manager_a", f"UPDATE {table} SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "err", (
            f"an assigned Manager moved a {table} row to a client they are not assigned to")
    if spec["parent"]:
        _parent_table, col = spec["parent"]
        parent_b = _parent_id(dsn, table, CLIENT_B)
        assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {col} = '{parent_b}' WHERE {_where_client(table, CLIENT_A)}") == "err", (
            f"an assigned Manager moved a {table} row onto another client's parent")


@pytest.mark.parametrize("table", list(SPECS))
def test_an_update_or_a_delete_of_another_clients_row_matches_nothing_and_of_their_own_matches(dsn, table):
    if table in NOT_WRITABLE_BY_A_SIGNED_IN_SESSION:
        pytest.skip(f"{table}: the signed-in role holds no write on it (migration 562), so there is no write to scope; the effective privileges are held by test_562")
    where_a, where_b = _where_client(table, CLIENT_A), _where_client(table, CLIENT_B)
    touch = "firm_id = firm_id"      # an update that changes nothing is still judged by the policy's USING and WITH CHECK
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE {where_b}") == "0", f"updated another client's {table} row"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE {where_b}") == "0", f"deleted another client's {table} row"
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE {where_a}") == "1", f"cannot update their own client's {table} row"
    if SPECS[table]["before_delete"]:
        for client in (CLIENT_A, CLIENT_B):
            assert _psql(dsn, SPECS[table]["before_delete"](client)).returncode == 0
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE {where_a}") == "1", f"cannot delete their own client's {table} row"
    assert _count_op(dsn, "manager_none", f"DELETE FROM {table} WHERE {where_a}") == "0", "a person assigned to nothing deleted a row"
    assert _count_op(dsn, "manager_none", f"UPDATE {table} SET {touch} WHERE {where_a}") == "0", "a person assigned to nothing updated a row"
    assert _count_op(dsn, "partner", f"DELETE FROM {table} WHERE {where_b}") == "1", f"a Partner cannot delete a client's {table} row"


@pytest.mark.parametrize("table", list(SPECS))
def test_a_person_assigned_to_the_practice_is_still_refused_its_rows_and_a_client_they_cannot_see(dsn, table):
    """The WITH CHECK of the internal-practice guard and of the assignment scope, exercised by someone who is not a Partner.
    The reads of a person assigned to the practice are counted elsewhere; an insert is the other half: the scope admits the
    practice's client to them (they are assigned), so only the guard can refuse it, and a client they cannot see is refused by
    the scope alone even on a parent that is theirs."""
    spec = SPECS[table]
    assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                      f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    args = {c: _parent_id(dsn, table, c) for c in (CLIENT_A, CLIENT_B, INTERNAL)}
    _clear_for_insert(dsn, table)
    if spec["clear"]:
        assert _psql(dsn, f"DELETE FROM {table} WHERE {_where_client(table, INTERNAL)}").returncode == 0
    assert _count_op(dsn, "manager_a", spec["insert"](INTERNAL, args[INTERNAL])) == "err", (
        f"a Manager assigned to the practice added a {table} row for it")
    if spec["own_client"] and spec["parent"]:
        assert _count_op(dsn, "manager_a", spec["insert"](INTERNAL, args[CLIENT_A])) == "err", (
            f"the practice's client was written onto a parent of the Manager's own in {table}: only the table's own guard can refuse it")
        assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_B, args[CLIENT_A])) == "err", (
            f"a client the Manager cannot see was written onto a parent of their own in {table}: only the table's own scope can refuse it")


@pytest.mark.parametrize("table", list(SPECS))
def test_a_partner_inserts_for_every_client_the_internal_practice_included(dsn, table):
    if table in NOT_WRITABLE_BY_A_SIGNED_IN_SESSION:
        pytest.skip(f"{table}: the signed-in role holds no write on it (migration 562), so there is no write to scope; the effective privileges are held by test_562")
    """The WITH CHECK keeps the Partner branch: a slip that dropped it from the scope or the guard would lock the owner out of
    adding a row to every client but the first, straight after the deploy."""
    spec = SPECS[table]
    args = {c: _parent_id(dsn, table, c) for c in (CLIENT_A, CLIENT_B, INTERNAL)}
    _clear_for_insert(dsn, table)
    if spec["clear"]:       # the internal practice's seeded row would collide as well
        assert _psql(dsn, f"DELETE FROM {table} WHERE {_where_client(table, INTERNAL)}").returncode == 0
    for client, tag in ((CLIENT_A, "A"), (CLIENT_B, "B"), (INTERNAL, "I")):
        assert _count_op(dsn, "partner", spec["insert"](client, args[client])) == "1", f"a Partner cannot add a {table} row for {tag}"


@pytest.mark.parametrize("table", [t for t, s in SPECS.items() if s["own_client"]])
def test_a_partner_moves_a_row_to_another_client_and_to_the_internal_practice(dsn, table):
    if table in NOT_WRITABLE_BY_A_SIGNED_IN_SESSION:
        pytest.skip(f"{table}: the signed-in role holds no write on it (migration 562), so there is no write to scope; the effective privileges are held by test_562")
    for client in (CLIENT_B, INTERNAL):
        if SPECS[table]["collides"]:
            assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{client}'").returncode == 0
    assert _count_op(dsn, "partner", f"UPDATE {table} SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "1", (
        f"a Partner cannot move a {table} row to another client")
    assert _count_op(dsn, "partner", f"UPDATE {table} SET client_id = '{INTERNAL}' WHERE client_id = '{CLIENT_A}'") == "1", (
        f"a Partner cannot move a {table} row to the internal practice")


def test_a_row_with_no_client_stays_open_to_the_firm_and_a_person_cannot_blank_another_clients_row(dsn):
    """`properties` and `tally_migration_jobs` may carry no client: the unassigned Manager reads that row and no other, and an
    update by a person who cannot see a client's row matches nothing, so it cannot give that row no client at all."""
    for table in ("properties", "tally_migration_jobs"):
        assert _count_as(dsn, "manager_none", table) == 1
        assert _count_op(dsn, "manager_none", f"UPDATE {table} SET client_id = NULL WHERE client_id = '{CLIENT_A}'") == "0", (
            f"{table}: a person who cannot see a client's row blanked its client")


@pytest.mark.parametrize("table", ["properties", "tally_migration_jobs", "tally_migration_items"])
def test_a_row_with_no_client_is_open_to_the_firm_where_no_internal_practice_is_set_up(dsn, table):
    """A firm whose onboarding never provisioned its internal practice has `firms.internal_client_id` NULL (migration 405
    measured one of two firms in that state). The internal-practice guard compares the row's client with it, and NULL IS
    DISTINCT FROM NULL is FALSE, so on a table whose client may be NULL the guard hid the client-less row from, and refused
    it to, every non-Partner of that firm. `properties` and `tally_migration_jobs` (and the items of a client-less job) say
    `client_id IS NULL OR` for that reason. The fourteen-table fixture always sets the internal practice; this is the other
    state."""
    assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    assert {who: _count_as(dsn, who, table) for who in ("partner", "manager_a", "manager_none", "executive_a")} == {
        "partner": 4, "manager_a": 2, "manager_none": 1, "executive_a": 2}, f"{table}: the client-less row is not open to the firm"
    # the rows of a client stay behind the assignment scope with no internal practice set up, and the guard has not widened them
    assert _count_op(dsn, "manager_none", SPECS[table]["insert"](CLIENT_A, _parent_id(dsn, table, CLIENT_A))) == "err"


@pytest.mark.parametrize("table", ["properties", "tally_migration_jobs"])
def test_a_manager_can_add_a_row_with_no_client_where_no_internal_practice_is_set_up(dsn, table):
    assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    row = {
        "properties": f"INSERT INTO properties (firm_id, client_id, address) VALUES ({_F}, NULL, 'firm level')",
        "tally_migration_jobs": (f"INSERT INTO tally_migration_jobs (firm_id, client_id, name, source_file_name, target_financial_year, created_by) "
                                 f"VALUES ({_F}, NULL, 'firm level', 'f.xml', '2025-26', '{PARTNER_ID}')"),
    }[table]
    for who in ("manager_a", "manager_none"):
        assert _count_op(dsn, who, row) == "1", f"{who} cannot add a client-less row to {table} in a firm with no internal practice"


def _knowledge_seed(dsn: str) -> None:
    done = _psql(dsn, f"INSERT INTO knowledge_articles (firm_id, client_id, scope, title) VALUES "
                      f"({_F}, NULL, 'firm', 'firm-wide'), ({_F}, '{CLIENT_A}', 'client', 'A article'), "
                      f"({_F}, '{CLIENT_B}', 'client', 'B article'), ({_F}, '{INTERNAL}', 'client', 'practice article')")
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("provisioned", [True, False])
def test_a_firm_wide_article_is_read_and_added_by_a_manager_whether_or_not_the_firm_has_an_internal_practice(dsn, provisioned):
    """Migration 079's guard on `knowledge_articles` had the same NULL IS DISTINCT FROM NULL defect: a firm-wide article carries
    no client, and in a firm whose onboarding never provisioned its internal practice the guard hid every one of them from the
    Managers and Executives its own assignment policy admits them to. 528 gives it the branch. The practice's own articles
    stay a Partner's whichever way the firm is set up."""
    _knowledge_seed(dsn)
    if not provisioned:
        assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    for who in ("manager_a", "manager_none", "executive_a"):
        got = _lines_as(dsn, who, "SELECT title FROM knowledge_articles WHERE client_id IS NULL;")
        assert got == ["firm-wide"], f"{who} reads {got} (internal practice set up: {provisioned})"
        assert _count_op(dsn, who, f"INSERT INTO knowledge_articles (firm_id, client_id, scope, title) VALUES ({_F}, NULL, 'firm', 'new')"
                         ) == ("1" if who != "executive_a" else "err"), f"{who}: a firm-wide article insert answered otherwise"
    if provisioned:
        # with the practice set up, its articles are a Partner's: a Manager assigned to the practice does not read them
        assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                          f"VALUES ('{FIRM}', '{PEOPLE['manager_none'][0]}', '{INTERNAL}');").returncode == 0
        assert "practice article" not in _lines_as(dsn, "manager_none", "SELECT title FROM knowledge_articles;")
        assert "practice article" in _lines_as(dsn, "partner", "SELECT title FROM knowledge_articles;")


# ── THE ROLLBACK, AND THE PLAN ──────────────────────────────────────────────────

def test_the_rollback_returns_the_firm_wide_read_and_a_reapply_hides_the_rows_again(dsn):
    before = {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in SPECS}
    assert all(v["manager_none"] == _expected_reads(t)["manager_none"] for t, v in before.items()), before

    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    for table in SPECS:
        total = _expected_reads(table)["partner"]
        assert _count_as(dsn, "manager_none", table) == total, f"after the rollback {table} is not firm-wide again"
        assert not _rows(dsn, f"SELECT 1 FROM pg_policy WHERE polrelid = 'public.{table}'::regclass AND polname = ANY(ARRAY{POLICIES[table]})")

    guard = ("SELECT pg_get_expr(polqual, polrelid) ~* 'client_id IS NULL' FROM pg_policy "
             "WHERE polrelid = 'public.knowledge_articles'::regclass AND polname = 'knowledge_articles_internal_partner_only'")
    assert _rows(dsn, guard) == [["f"]], "the rollback left the NULL branch on the knowledge_articles guard"

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in SPECS} == before
    assert _rows(dsn, guard) == [["t"]], "the migration did not give the knowledge_articles guard its NULL branch"


def test_a_second_run_of_the_migration_changes_nothing(dsn):
    def snapshot() -> list:
        return _rows(dsn, "SELECT c.relname, p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                          "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                          f"WHERE c.relname = ANY(ARRAY{list(SPECS) + ['knowledge_articles']}) ORDER BY 1, 2")
    first = snapshot()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == first


@pytest.mark.parametrize("table", list(SPECS))
def test_a_signed_in_scan_asks_the_callers_clients_once(dsn, table):
    plan = "\n".join(_lines_as(dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {table};"))
    assert "can_access_client" not in plan, plan
    if SPECS[table]["own_client"]:
        assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
    else:       # a child with no client of its own reads its parent, which asks the set
        assert "SubPlan" in plan, plan

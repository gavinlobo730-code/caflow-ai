"""Migration 543 — the cached stock figures of an item are written by the API only, and three tables nothing uses are closed to the
signed-in role (POST-A-327, POST-A-333).

WHAT WAS WRONG
    `service_catalogue.stock_qty_units`, `avg_cost_paise` and `stock_version` are a copy of the stock ledger's last row, rewritten by
    every movement, and the signed-in role held UPDATE on the table with only the assignment scope between a member and the row. A
    member assigned to the client could set the copy to any figure over PostgREST (the catalogue's Stock column, the product form's
    gate, the item ledger's item block and the reconciliation read it; the register, the reorder check and the next movement's cost
    read the ledger). The same member could DELETE an item, and the stock ledger's foreign key cascades, so the item's stock history
    went with it. `activity_logs`, `ai_evidence` and `ai_signals` have no reader and no writer anywhere, yet the signed-in role held
    every write verb on all three.

WHAT THIS HOLDS (a real database, as each person)
    * THE CACHE: a Manager (and a Partner: the trigger judges everybody signed in) is refused a change of each of the three columns
      with the trigger's own sentence and the row is left as it was; the privileged client and the database owner change them freely;
      a statement that names a column and sends the value the row already holds is not a change, and an edit of any other column
      (the name, the rate, the reorder level) passes; an item cannot be CREATED with a figure other than the default (a negative one
      included), by an INSERT or by the insert candidate of an upsert; the anonymous role is judged as well (made reachable in a
      worst case); the functions are closed to a signed-in role even when the platform granted them first and pin their search path.
    * THE DELETE: a signed-in session cannot delete an item that has a stock ledger row (the row and its history are left), may
      delete one with none (the API's own rule), and the privileged client, the owner and the firm purge are not judged.
    * THE THREE TABLES: the signed-in and anonymous roles hold no privilege on them at all, table or column, through PUBLIC or not,
      even where the platform's defaults had granted everything first; the service role keeps its four; migration 540's triggers on
      them are still there and, with the privilege handed back, still refuse a Manager clearing the client (the second lock).
    * THE MIGRATION: the table lock is waited for WITHOUT queueing (a writer is waited for and the file then applies; a reader is
      not a reason to wait), the statements that take it run inside one block in both files and the migration drops no trigger, a
      second run changes nothing, and the rollback brings the forgery back (the negative control) and a re-apply ends it.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the cached-stock proof requires HARNESS_PG + psql",
)

_STEM = "543_the_items_cached_stock_figures_are_written_by_the_api_only_and_three_tables_nothing_uses_are_closed_to_the_signed_in_role"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
FUNCTION = "refuse_a_signed_in_edit_of_the_items_cached_stock"
TRIGGER = "an_items_cached_stock_is_not_edited_from_a_signed_in_session"
FUNCTION2 = "refuse_a_signed_in_delete_of_an_item_with_stock_history"
TRIGGER2 = "an_item_with_stock_history_is_not_deleted_from_a_signed_in_session"
CACHE = ("stock_qty_units", "avg_cost_paise", "stock_version")
CLOSED = ("activity_logs", "ai_evidence", "ai_signals")

FIRM = "54300000-0000-0000-0000-000000000001"
CLIENT_A = "54300000-0000-0000-0000-0000000000a1"
CLIENT_B = "54300000-0000-0000-0000-0000000000b2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("54300000-0000-0000-0000-00000000000a", "54300000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("54300000-0000-0000-0000-00000000000b", "54300000-1111-0000-0000-000000000002", "Manager"),
    "reviewer_a": ("54300000-0000-0000-0000-00000000000f", "54300000-1111-0000-0000-000000000005", "Reviewer"),
}
_F = f"'{FIRM}'"


def _q(value) -> str:
    return "NULL" if value is None else f"'{value}'"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    if who in ("service_role", "owner"):
        return "SET request.jwt.claims = '{\"role\": \"service_role\"}'; " + ("SET ROLE service_role; " if who == "service_role" else "")
    if who == "anon":
        return "SET request.jwt.claims = '{\"role\": \"anon\"}'; SET ROLE anon; "
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE> <message>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _by_the_trigger(outcome: str) -> bool:
    """Refused by THIS trigger (a privilege or row-security refusal is also 42501, with another sentence)."""
    return outcome.startswith("err:42501") and "cached stock of an item" in outcome


def _wrote(outcome: str) -> bool:
    return outcome == "1"


# ── THE SEED ─────────────────────────────────────────────────────────────────

class World:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.item = ""            # an item with a stock ledger row
        self.plain = ""           # an item with none

    def owner(self, sql: str) -> list[list[str]]:
        return _rows(self.dsn, "SET session_replication_role = replica; " + sql)


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e543s_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create the seeded database")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        assigned = ", ".join(f"('{FIRM}', '{PEOPLE[n][0]}', '{CLIENT_A}')" for n in ("manager_a", "reviewer_a"))
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
        """)
        assert seed.returncode == 0, seed.stderr
        w = World(d)
        got = w.owner(f"INSERT INTO service_catalogue (firm_id, client_id, name, kind, stock_qty_units, avg_cost_paise, stock_version, "
                      f"reorder_level_units) VALUES ({_F}, '{CLIENT_A}', 'Widget', 'good', 5, 100, 2, 3) RETURNING id;")
        w.item = [r[0] for r in got if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0]
        plain = w.owner(f"INSERT INTO service_catalogue (firm_id, client_id, name, kind) VALUES ({_F}, '{CLIENT_A}', 'Unused item', 'good') RETURNING id;")
        w.plain = [r[0] for r in plain if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0]
        assert w.owner(f"INSERT INTO inventory_stock_ledger (firm_id, client_id, service_catalogue_id, movement_date, movement_type, quantity_delta, "
                       f"unit_cost_paise, value_delta_paise, running_qty_units, running_avg_cost_paise, running_value_paise) "
                       f"VALUES ({_F}, '{CLIENT_A}', '{w.item}', '2026-04-01', 'opening', 5, 100, 500, 5, 100, 500) RETURNING id;")
        # one row in each of the three closed tables, so a refusal is of a row that exists
        for table, extra in (("activity_logs", "action, description"), ("ai_evidence", "evidence_type"), ("ai_signals", "signal_type")):
            values = {"activity_logs": "'client_created', 'log'", "ai_evidence": "'e'", "ai_signals": "'s'"}[table]
            assert w.owner(f"INSERT INTO {table} (firm_id, client_id, {extra}) VALUES ({_F}, '{CLIENT_A}', {values}) RETURNING id;")
        yield name, (w.item, w.plain)
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def world(seeded):
    template, (item, plain) = seeded
    admin = _ADMIN.strip()
    name = f"e543_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.item, w.plain = item, plain
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _figures(world: World) -> list[str]:
    return _rows(world.dsn, f"SELECT stock_qty_units::text, avg_cost_paise::text, stock_version::text FROM service_catalogue WHERE id = '{world.item}'")[0]


def _new_item(name: str, **cache) -> str:
    cols = {"firm_id": _F, "client_id": _q(CLIENT_A), "name": _q(name), "kind": "'good'", **cache}
    return f"INSERT INTO service_catalogue ({', '.join(cols)}) VALUES ({', '.join(cols.values())})"


# ── THE CACHE: UPDATE ────────────────────────────────────────────────────────

def test_the_seed_is_what_the_tests_below_assume(world):
    assert _figures(world) == ["5.000", "100", "2"] or _figures(world) == ["5", "100", "2"]
    assert _op(world.dsn, "manager_a", f"UPDATE service_catalogue SET name = 'Widget' WHERE id = '{world.item}'") == "1", "the Manager does not reach the item"


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("column,value", [("stock_qty_units", "999"), ("avg_cost_paise", "1"), ("stock_version", "77")])
def test_a_signed_in_member_is_refused_a_change_of_each_cached_column_and_the_row_is_left_as_it_was(world, who, column, value):
    before = _figures(world)
    out = _op(world.dsn, who, f"UPDATE service_catalogue SET {column} = {value} WHERE id = '{world.item}'")
    assert _by_the_trigger(out), out
    assert "cannot be changed from a signed-in session" in out
    assert _figures(world) == before


def test_a_statement_that_changes_one_of_several_columns_is_refused_whole(world):
    out = _op(world.dsn, "manager_a", f"UPDATE service_catalogue SET name = 'Gadget', stock_version = stock_version + 1 WHERE id = '{world.item}'")
    assert _by_the_trigger(out), out
    assert _rows(world.dsn, f"SELECT name FROM service_catalogue WHERE id = '{world.item}'") == [["Widget"]]


@pytest.mark.parametrize("who", ["service_role", "owner"])
@pytest.mark.parametrize("column,value", [("stock_qty_units", "999"), ("avg_cost_paise", "1"), ("stock_version", "77")])
def test_the_privileged_client_and_the_owner_change_the_cache_freely(world, who, column, value):
    assert _wrote(_op(world.dsn, who, f"UPDATE service_catalogue SET {column} = {value} WHERE id = '{world.item}'"))


def test_a_statement_that_names_the_columns_and_sends_the_values_they_hold_is_not_a_change(world):
    """A whole-row re-save (the product form) names every column; only a different figure is a change."""
    out = _op(world.dsn, "manager_a", f"UPDATE service_catalogue SET stock_qty_units = stock_qty_units, avg_cost_paise = avg_cost_paise, "
                                      f"stock_version = stock_version, name = 'Renamed' WHERE id = '{world.item}'")
    assert _wrote(out), out


@pytest.mark.parametrize("assignment", ["name = 'Gadget'", "default_rate_paise = 12300", "reorder_level_units = 9", "description = 'x'",
                                        "is_active = false", "hsn_sac = '8471'", "gst_rate_bps = 1800", "opening_qty_units = 4"])
def test_an_edit_of_anything_else_about_the_item_passes(world, assignment):
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE service_catalogue SET {assignment} WHERE id = '{world.item}'")), assignment


# ── THE CACHE: INSERT AND UPSERT ─────────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("cache", [{"stock_qty_units": "5"}, {"avg_cost_paise": "100"}, {"stock_version": "3"},
                                   {"stock_qty_units": "5", "avg_cost_paise": "100", "stock_version": "1"}])
def test_an_item_cannot_be_created_with_a_forged_figure(world, who, cache):
    out = _op(world.dsn, who, _new_item("Forged", **cache))
    assert _by_the_trigger(out) and "cannot be set from a signed-in session" in out, out


@pytest.mark.parametrize("cache", [{"stock_qty_units": "-1"}, {"avg_cost_paise": "-5"}, {"stock_version": "-1"}, {"stock_qty_units": "0.001"}])
def test_a_negative_or_fractional_forged_figure_is_refused_too(world, cache):
    """The check is 'anything other than the default', not 'anything positive': an oversold item carries a negative quantity."""
    out = _op(world.dsn, "manager_a", _new_item("Forged", **cache))
    assert _by_the_trigger(out), out
    column, value = next(iter(cache.items()))
    assert _by_the_trigger(_op(world.dsn, "manager_a", f"UPDATE service_catalogue SET {column} = {value} WHERE id = '{world.plain}'"))


@pytest.mark.parametrize("cache", [{}, {"stock_qty_units": "0", "avg_cost_paise": "0", "stock_version": "0"}])
def test_an_item_is_created_with_the_defaults_as_before(world, cache):
    assert _wrote(_op(world.dsn, "manager_a", _new_item("Plain", **cache)))


def test_an_upsert_that_would_write_the_cache_is_refused_whether_it_inserts_or_updates(world):
    """The opening-stock batch's old shape: INSERT ... ON CONFLICT (id) DO UPDATE. The insert candidate carries the figures, so the
    INSERT trigger refuses it even though the statement would resolve to an UPDATE; a candidate with defaults that sets the
    columns in its DO UPDATE is refused by the UPDATE trigger."""
    candidate = (f"INSERT INTO service_catalogue (id, firm_id, client_id, name, stock_qty_units, avg_cost_paise) "
                 f"VALUES ('{world.item}', {_F}, '{CLIENT_A}', 'Widget', 50, 7) ON CONFLICT (id) DO UPDATE SET "
                 f"stock_qty_units = EXCLUDED.stock_qty_units, avg_cost_paise = EXCLUDED.avg_cost_paise")
    assert _by_the_trigger(_op(world.dsn, "manager_a", candidate))
    defaults = (f"INSERT INTO service_catalogue (id, firm_id, client_id, name) VALUES ('{world.item}', {_F}, '{CLIENT_A}', 'Widget') "
                f"ON CONFLICT (id) DO UPDATE SET stock_qty_units = 50")
    assert _by_the_trigger(_op(world.dsn, "manager_a", defaults))
    assert _figures(world)[1:] == ["100", "2"]


@pytest.mark.parametrize("who", ["service_role", "owner"])
def test_the_privileged_client_and_the_owner_create_an_item_with_figures_and_upsert_them(world, who):
    assert _wrote(_op(world.dsn, who, _new_item("Seeded", stock_qty_units="10", avg_cost_paise="500", stock_version="1")))
    upsert = (f"INSERT INTO service_catalogue (id, firm_id, client_id, name, stock_qty_units, avg_cost_paise) "
              f"VALUES ('{world.item}', {_F}, '{CLIENT_A}', 'Widget', 50, 7) ON CONFLICT (id) DO UPDATE SET "
              f"stock_qty_units = EXCLUDED.stock_qty_units, avg_cost_paise = EXCLUDED.avg_cost_paise")
    assert _wrote(_op(world.dsn, who, upsert))


def test_the_anonymous_role_is_judged_as_well(world):
    """Production's platform defaults grant `anon` every privilege on a public table and row security is all that keeps it out. The
    worst case: `anon` is granted the writes and row security is off, so the trigger is the only thing between it and the cache."""
    done = _psql(world.dsn, "GRANT SELECT, INSERT, UPDATE ON service_catalogue TO anon; ALTER TABLE service_catalogue DISABLE ROW LEVEL SECURITY;")
    assert done.returncode == 0, done.stderr
    assert _wrote(_op(world.dsn, "anon", f"UPDATE service_catalogue SET name = 'x' WHERE id = '{world.item}'")), "the worst case was not made"
    assert _by_the_trigger(_op(world.dsn, "anon", f"UPDATE service_catalogue SET stock_qty_units = 1 WHERE id = '{world.item}'"))
    assert _by_the_trigger(_op(world.dsn, "anon", _new_item("Forged", stock_version="9")))


def test_a_reviewer_who_cannot_write_the_catalogue_is_refused_before_the_trigger(world):
    out = _op(world.dsn, "reviewer_a", f"UPDATE service_catalogue SET stock_qty_units = 1 WHERE id = '{world.item}'")
    assert not _wrote(out), out


def test_the_signed_in_member_still_reads_the_item_and_its_figures(world):
    out = subprocess.run(["psql", world.dsn, "-X", "-tA", "-c", _as("manager_a") + f"SELECT stock_qty_units, avg_cost_paise FROM service_catalogue WHERE id = '{world.item}';"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "100" in out.stdout, out.stderr


# ── THE FUNCTION AND THE TRIGGER ─────────────────────────────────────────────

@pytest.mark.parametrize("function", [FUNCTION, FUNCTION2])
def test_the_function_is_not_executable_by_a_signed_in_role_even_when_the_platform_granted_it_first(world, function):
    fn = f"public.{function}()"
    probe = f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE'), has_function_privilege('anon', '{fn}', 'EXECUTE')"
    assert _rows(world.dsn, probe) == [["f", "f"]]
    assert _psql(world.dsn, f"GRANT EXECUTE ON FUNCTION {fn} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _rows(world.dsn, probe) == [["t", "t"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["f", "f"]]


def test_the_trigger_is_the_one_written(world):
    got = _rows(world.dsn, f"SELECT t.tgtype::text, t.tgenabled::text, p.proname, "
                           f"(SELECT string_agg(a.attname, ',' ORDER BY a.attname) FROM unnest(t.tgattr) k(n) JOIN pg_attribute a ON a.attrelid = t.tgrelid AND a.attnum = k.n) "
                           f"FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid WHERE t.tgrelid = 'public.service_catalogue'::regclass "
                           f"AND t.tgname = '{TRIGGER}' AND NOT t.tgisinternal")
    assert got == [["23", "O", FUNCTION, "avg_cost_paise,stock_qty_units,stock_version"]], got       # ROW, BEFORE, INSERT, UPDATE OF three
    delete = _rows(world.dsn, f"SELECT t.tgtype::text, t.tgenabled::text, p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
                              f"WHERE t.tgrelid = 'public.service_catalogue'::regclass AND t.tgname = '{TRIGGER2}' AND NOT t.tgisinternal")
    assert delete == [["11", "O", FUNCTION2]], delete                                                 # ROW, BEFORE, DELETE


@pytest.mark.parametrize("function", [FUNCTION, FUNCTION2])
def test_the_functions_run_as_their_owner_with_a_pinned_search_path(world, function):
    """A SECURITY DEFINER function with no search path is a function a caller can point at their own objects."""
    got = _rows(world.dsn, f"SELECT prosecdef::text, coalesce(array_to_string(proconfig, ','), '') FROM pg_proc WHERE proname = '{function}'")
    assert got and got[0][0] == "true" and "search_path=" in got[0][1], got


def test_the_service_roles_four_privileges_are_granted_explicitly_not_inherited(world):
    """In the harness the service role holds its privileges directly, so a migration that forgot the explicit GRANT would pass; take
    them away first and see the migration give them back."""
    assert _psql(world.dsn, "REVOKE ALL ON public.activity_logs, public.ai_evidence, public.ai_signals FROM service_role;").returncode == 0
    assert _rows(world.dsn, "SELECT has_table_privilege('service_role', 'public.ai_signals', 'INSERT')") == [["f"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for table in CLOSED:
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _rows(world.dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{priv}')") == [["t"]], (table, priv)


# ── THE THREE TABLES ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", CLOSED)
def test_the_signed_in_and_anonymous_roles_hold_nothing_on_the_table(world, table):
    for role in ("authenticated", "anon"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert _rows(world.dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{priv}')") == [["f"]], (role, priv)
        assert _rows(world.dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', 'SELECT, INSERT, UPDATE, REFERENCES')") == [["f"]]


@pytest.mark.parametrize("table", CLOSED)
def test_the_service_role_keeps_its_four(world, table):
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _rows(world.dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{priv}')") == [["t"]], priv


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table", CLOSED)
def test_nobody_signed_in_reads_or_writes_the_table(world, table, who):
    for dml in (f"SELECT 1 FROM {table} LIMIT 1", f"UPDATE {table} SET client_id = client_id", f"DELETE FROM {table}"):
        out = _op(world.dsn, who, dml)
        assert out.startswith("err:42501") and "permission denied" in out, (dml, out)


@pytest.mark.parametrize("table", CLOSED)
def test_where_the_platforms_defaults_granted_everything_first_the_migration_closes_it(world, table):
    done = _psql(world.dsn, f"GRANT ALL ON public.{table} TO authenticated, anon, PUBLIC;")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'UPDATE'), has_table_privilege('anon', 'public.{table}', 'TRUNCATE')") == [["t", "t"]]
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _rows(world.dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'UPDATE'), has_table_privilege('anon', 'public.{table}', 'TRUNCATE')") == [["f", "f"]]


@pytest.mark.parametrize("table", CLOSED)
def test_migration_540s_trigger_is_still_the_second_lock_when_the_privilege_is_handed_back(world, table):
    row = _rows(world.dsn, f"SELECT id FROM {table} LIMIT 1")[0][0]
    assert _psql(world.dsn, f"GRANT SELECT, UPDATE ON {table} TO authenticated;").returncode == 0
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET client_id = NULL WHERE id = '{row}'")
    assert out.startswith("err:42501") and "Only a Partner" in out, out


def test_the_service_role_still_works_on_the_three_tables(world):
    for table in CLOSED:
        assert _op(world.dsn, "service_role", f"UPDATE {table} SET client_id = client_id") == "1", table


def test_the_firm_purge_still_removes_the_firms_rows_from_the_three_tables_and_the_catalogue(world):
    """The one statement that removes a firm: SECURITY DEFINER, executable by the service role only. Run as the backend runs it,
    after the revoke and with the delete trigger in place (the purge runs with triggers off, and an item with stock history goes)."""
    for table in (*CLOSED, "service_catalogue", "inventory_stock_ledger"):
        assert int(_rows(world.dsn, f"SELECT count(*) FROM {table} WHERE firm_id = '{FIRM}'")[0][0]) >= 1, table
    purge = _psql(world.dsn, "SET request.jwt.claims = '{\"role\": \"service_role\"}'; SET ROLE service_role; "
                             f"SELECT public.platform_purge_firm('{FIRM}');")
    assert purge.returncode == 0, purge.stderr
    for table in (*CLOSED, "service_catalogue", "inventory_stock_ledger"):
        assert _rows(world.dsn, f"SELECT count(*) FROM {table} WHERE firm_id = '{FIRM}'") == [["0"]], table


# ── THE DELETE ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "partner"])
def test_a_signed_in_member_cannot_delete_an_item_that_has_stock_history(world, who):
    before = _rows(world.dsn, f"SELECT (SELECT count(*) FROM service_catalogue WHERE id = '{world.item}'), "
                              f"(SELECT count(*) FROM inventory_stock_ledger WHERE service_catalogue_id = '{world.item}')")
    assert before == [["1", "1"]]
    out = _op(world.dsn, who, f"DELETE FROM service_catalogue WHERE id = '{world.item}'")
    assert out.startswith("err:42501") and "cannot be deleted from a signed-in session" in out and "stock ledger would go with it" in out, out
    assert _rows(world.dsn, f"SELECT (SELECT count(*) FROM service_catalogue WHERE id = '{world.item}'), "
                            f"(SELECT count(*) FROM inventory_stock_ledger WHERE service_catalogue_id = '{world.item}')") == before


def test_a_signed_in_member_still_deletes_an_item_with_no_stock_history(world):
    """What the API route does for an unused preset."""
    assert _wrote(_op(world.dsn, "manager_a", f"DELETE FROM service_catalogue WHERE id = '{world.plain}'"))


@pytest.mark.parametrize("who", ["service_role", "owner"])
def test_the_privileged_client_and_the_owner_delete_an_item_and_its_history(world, who):
    assert _wrote(_op(world.dsn, who, f"DELETE FROM service_catalogue WHERE id = '{world.item}'"))


def test_the_anonymous_role_is_judged_on_the_delete_too(world):
    done = _psql(world.dsn, "GRANT SELECT, DELETE ON service_catalogue TO anon; ALTER TABLE service_catalogue DISABLE ROW LEVEL SECURITY;")
    assert done.returncode == 0, done.stderr
    assert _wrote(_op(world.dsn, "anon", f"DELETE FROM service_catalogue WHERE id = '{world.plain}'")), "the worst case was not made"
    out = _op(world.dsn, "anon", f"DELETE FROM service_catalogue WHERE id = '{world.item}'")
    assert out.startswith("err:42501") and "stock movements" in out, out


def test_a_cascade_into_the_catalogue_is_not_judged(world):
    """A delete made by a foreign-key action runs one trigger level deeper than a statement. (No signed-in route reaches one today:
    migration 540 refuses a signed-in delete of a client.) Shown with a throwaway parent so the depth rule is what is tested."""
    done = _psql(world.dsn, "CREATE TABLE public.zz_parent (id uuid PRIMARY KEY); ALTER TABLE public.service_catalogue ADD COLUMN zz_parent uuid "
                            "REFERENCES public.zz_parent(id) ON DELETE CASCADE; GRANT SELECT, DELETE ON public.zz_parent TO authenticated;")
    assert done.returncode == 0, done.stderr
    parent = [r[0] for r in world.owner("INSERT INTO zz_parent (id) VALUES (gen_random_uuid()) RETURNING id;") if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0]
    world.owner(f"UPDATE service_catalogue SET zz_parent = '{parent}' WHERE id = '{world.item}'")
    out = _op(world.dsn, "partner", f"DELETE FROM zz_parent WHERE id = '{parent}'")
    assert _wrote(out), out


# ── THE LOCK WAIT, THE BLOCK, THE SECOND RUN, THE ROLLBACK ───────────────────

def _outside_the_bodies(sql: str) -> str:
    return re.sub(r"\$(\w*)\$.*?\$\1\$", " ", sql, flags=re.S)


def _bodies(sql: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"\$(\w*)\$(.*?)\$\1\$", sql, flags=re.S)]


@pytest.mark.parametrize("path, creates", [(MIGRATION, True), (ROLLBACK, False)], ids=["migration", "rollback"])
def test_the_statements_that_lock_the_table_run_inside_one_block(path, creates):
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    left = re.findall(r"\b(?:CREATE(?:\s+OR\s+REPLACE)?|DROP)\s+TRIGGER\b[^;]*|\bLOCK\s+TABLE\b[^;]*", _outside_the_bodies(sql), flags=re.I)
    assert left == [], f"a statement that takes a table lock stands at the top level: {left[:2]}"
    holders = [b for b in _bodies(sql) if re.search(r"\b(?:CREATE(?:\s+OR\s+REPLACE)?|DROP)\s+TRIGGER\b", b, flags=re.I)]
    assert len(holders) == 1, len(holders)
    lock = re.findall(r"\bLOCK TABLE\b([^;]*);", holders[0])
    assert len(lock) == 1 and "public.service_catalogue" in lock[0] and "NOWAIT" in lock[0], lock
    assert "lock_not_available" in holders[0] and "pg_sleep" in holders[0]
    # the migration never DROPs a trigger it is about to create (DROP takes ACCESS EXCLUSIVE, which on a re-apply queues behind every
    # reader); the rollback drops both
    assert len(re.findall(r"\bCREATE OR REPLACE TRIGGER\b", holders[0])) == (2 if creates else 0)
    assert len(re.findall(r"\bCREATE TRIGGER\b", holders[0])) == 0
    assert len(re.findall(r"\bDROP TRIGGER\b", holders[0])) == (0 if creates else 2)


@pytest.mark.parametrize("path, mode", [(MIGRATION, "ROW EXCLUSIVE"), (ROLLBACK, "ACCESS SHARE")], ids=["migration", "rollback"])
def test_a_busy_table_is_waited_for_and_the_file_then_applies(world, path, mode):
    holder = subprocess.Popen(["psql", world.dsn, "-X", "-q", "-c", f"BEGIN; LOCK TABLE public.service_catalogue IN {mode} MODE; SELECT pg_sleep(4); COMMIT;"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(40):
        held = _rows(world.dsn, "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.relation = 'public.service_catalogue'::regclass "
                                "AND l.granted AND a.query LIKE 'BEGIN; LOCK TABLE%'")
        if held[0][0] != "0":
            break
        time.sleep(0.25)
    else:
        holder.kill()
        raise AssertionError("the holder never took its lock")
    started = time.monotonic()
    done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True, timeout=60)
    holder.wait(timeout=60)
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - started >= 2.0, "it did not wait for the holder"


def _closing_check() -> str:
    """The migration's last DO block, the one that checks what the rest did."""
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    blocks = re.findall(r"DO \$\$.*?END \$\$;", sql, flags=re.S)
    assert len(blocks) == 2 and "has_table_privilege" in blocks[-1], len(blocks)
    return blocks[-1]


def test_the_closing_check_passes_on_what_the_migration_made(world):
    done = _psql(world.dsn, _closing_check())
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("spoil, says", [
    ("GRANT UPDATE ON public.ai_signals TO authenticated", "still UPDATE public.ai_signals"),
    ("GRANT SELECT ON public.activity_logs TO anon", "still SELECT public.activity_logs"),
    ("GRANT TRUNCATE ON public.ai_evidence TO PUBLIC", "still TRUNCATE public.ai_evidence"),
    ("GRANT UPDATE (client_id) ON public.ai_evidence TO authenticated", "column privilege on public.ai_evidence"),
    ("GRANT SELECT (id) ON public.activity_logs TO anon", "column privilege on public.activity_logs"),
    ("REVOKE UPDATE ON public.ai_signals FROM service_role", "lost UPDATE on public.ai_signals"),
    (f"ALTER TABLE public.service_catalogue DISABLE TRIGGER {TRIGGER}", "cached-stock trigger"),
    (f"ALTER TABLE public.service_catalogue DISABLE TRIGGER {TRIGGER2}", "stock-history delete trigger"),
    (f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}() TO authenticated", "can execute a trigger function"),
    (f"GRANT EXECUTE ON FUNCTION public.{FUNCTION2}() TO anon", "can execute a trigger function"),
    # a trigger of the same name that is NOT the one written: another event, another column list, another function
    (f"CREATE OR REPLACE TRIGGER {TRIGGER} BEFORE UPDATE OF stock_qty_units, avg_cost_paise, stock_version ON public.service_catalogue "
     f"FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()", "cached-stock trigger"),
    (f"CREATE OR REPLACE TRIGGER {TRIGGER} BEFORE INSERT OR UPDATE OF stock_qty_units, avg_cost_paise ON public.service_catalogue "
     f"FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()", "cached-stock trigger"),
    (f"CREATE OR REPLACE TRIGGER {TRIGGER2} BEFORE DELETE ON public.service_catalogue FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()",
     "stock-history delete trigger"),
    (f"CREATE OR REPLACE TRIGGER {TRIGGER2} AFTER DELETE ON public.service_catalogue FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION2}()",
     "stock-history delete trigger"),
])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(world, spoil, says):
    """Run alone after one spoiling statement each: a check that cannot fail is not a check."""
    assert _psql(world.dsn, spoil).returncode == 0
    done = _psql(world.dsn, _closing_check())
    assert done.returncode != 0 and says in done.stderr, done.stderr


def test_a_re_apply_does_not_wait_for_a_reader_nor_make_one_wait(world):
    """With the triggers present, a transaction that has only READ the table (ACCESS SHARE) is not a reason for the migration to
    wait: nothing in it asks for a lock that conflicts with a read. A DROP TRIGGER would have queued behind it, blocked every later
    read and write, and deadlocked a transaction that reads and then writes (the review's repro)."""
    holder = subprocess.Popen(["psql", world.dsn, "-X", "-q", "-c", "BEGIN; LOCK TABLE public.service_catalogue IN ACCESS SHARE MODE; SELECT pg_sleep(6); COMMIT;"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(40):
        held = _rows(world.dsn, "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.relation = 'public.service_catalogue'::regclass "
                                "AND l.granted AND a.query LIKE 'BEGIN; LOCK TABLE%'")
        if held[0][0] != "0":
            break
        time.sleep(0.25)
    else:
        holder.kill()
        raise AssertionError("the holder never took its lock")
    started = time.monotonic()
    try:
        done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(MIGRATION)], capture_output=True, text=True, timeout=60)
        elapsed = time.monotonic() - started
        probe = _psql(world.dsn, "SET lock_timeout = '1500ms'; BEGIN; LOCK TABLE public.service_catalogue IN ROW EXCLUSIVE MODE; COMMIT;")
    finally:
        holder.wait(timeout=60)
    assert done.returncode == 0, done.stderr
    assert elapsed < 4, f"the re-apply waited {elapsed:.1f}s for a reader"
    assert probe.returncode == 0, probe.stderr


def test_a_table_that_stays_busy_fails_the_migration_after_fifteen_seconds_in_its_own_words_and_changes_nothing(world):
    before = _catalogue(world.dsn)
    holder = subprocess.Popen(["psql", world.dsn, "-X", "-q", "-c", "BEGIN; LOCK TABLE public.service_catalogue IN ROW EXCLUSIVE MODE; SELECT pg_sleep(40); COMMIT;"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(40):
            held = _rows(world.dsn, "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.relation = 'public.service_catalogue'::regclass "
                                    "AND l.granted AND a.query LIKE 'BEGIN; LOCK TABLE%'")
            if held[0][0] != "0":
                break
            time.sleep(0.25)
        else:
            raise AssertionError("the holder never took its lock")
        started = time.monotonic()
        done = _psql_file(world.dsn, MIGRATION)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode != 0 and "could not lock public.service_catalogue in 15 seconds" in done.stderr, done.stderr
    assert 13 <= waited <= 25, waited
    assert _catalogue(world.dsn) == before


def _catalogue(dsn: str) -> list:
    return _rows(dsn, "SELECT tgrelid::regclass::text, tgname, tgenabled::text, tgtype::text FROM pg_trigger "
                      f"WHERE tgname IN ('{TRIGGER}', '{TRIGGER2}') AND NOT tgisinternal ORDER BY 2") + _rows(
        dsn, f"SELECT 'f', proname, prosecdef::text, md5(prosrc), coalesce(array_to_string(proacl, ','), '') FROM pg_proc WHERE proname IN ('{FUNCTION}', '{FUNCTION2}') ORDER BY 2") + _rows(
        dsn, "SELECT relname, coalesce(relacl::text, '') FROM pg_class WHERE relname IN ('activity_logs', 'ai_evidence', 'ai_signals') AND relkind = 'r' ORDER BY 1")


def test_a_second_run_of_the_migration_changes_nothing(world):
    before = _catalogue(world.dsn)
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _catalogue(world.dsn) == before


def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it(world):
    forge = f"UPDATE service_catalogue SET stock_qty_units = 999 WHERE id = '{world.item}'"
    erase = f"DELETE FROM service_catalogue WHERE id = '{world.item}'"
    assert _by_the_trigger(_op(world.dsn, "manager_a", forge))
    assert _op(world.dsn, "manager_a", erase).startswith("err:42501")
    done = _psql_file(world.dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_trigger WHERE tgname IN ('{TRIGGER}', '{TRIGGER2}') AND NOT tgisinternal") == [["0"]]
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_proc WHERE proname IN ('{FUNCTION}', '{FUNCTION2}')") == [["0"]]
    assert _wrote(_op(world.dsn, "manager_a", forge)), "the negative control: with the migration rolled back the forgery works"
    assert _wrote(_op(world.dsn, "manager_a", erase)), "the negative control: with the migration rolled back the item and its history can be deleted"
    for table in CLOSED:
        assert _rows(world.dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'UPDATE')") == [["t"]], table
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _by_the_trigger(_op(world.dsn, "manager_a", forge))
    for table in CLOSED:
        assert _rows(world.dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'UPDATE')") == [["f"]], table

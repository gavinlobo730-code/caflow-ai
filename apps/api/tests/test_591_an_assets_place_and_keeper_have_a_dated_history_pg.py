"""Migration 591 on a real database: an asset's place and keeper have a dated history, written in one transaction with the asset
(POST-A-112, its first half).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_an_assets_place_and_keeper_have_a_dated_history.py`) holds the routes and the service. Here:
    * `record_fixed_asset_movement` stores the movement with the asset's own place and keeper as "before" and moves the asset, in one
      transaction, normalising the spacing; and refuses, leaving the asset as it was, an asset that is not the client's, a deleted or a
      disposed one, a date after India's today, before the purchase or before the latest movement, and a movement that moves nothing;
    * the privileges: the signed-in role reads the table and holds no write, may not execute the function, anon holds nothing, the
      service role executes it;
    * the policies, as each person: a Partner reads every client's movements, a Manager assigned to A reads A's alone, the internal
      practice's are a Partner's, a member assigned to nothing and a principal with no member row read none;
    * the firm checks of 565 and 566 refuse a row naming another firm's client or author; the keeper is one line of at most 200;
    * the migration runs twice and its rollback removes the table, the function and the column, after which it applies again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(API_ROOT.glob("migrations/591_an_assets_place_and_keeper_have_a_dated_history.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/591_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

T = "public.fixed_asset_movements"
FN = "public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid)"
FIRM, OTHER_FIRM = "91000000-0000-0000-0000-000000000001", "91000000-0000-0000-0000-000000000002"
CLIENT_A, CLIENT_B = "91000000-0000-0000-0000-0000000000a1", "91000000-0000-0000-0000-0000000000b2"
INTERNAL, FOREIGN = "91000000-0000-0000-0000-0000000000c3", "91000000-0000-0000-0000-0000000000d4"
STRANGER = "91000000-1111-0000-0000-0000000000ff"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("91000000-0000-0000-0000-00000000000a", "91000000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("91000000-0000-0000-0000-00000000000b", "91000000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_internal": ("91000000-0000-0000-0000-00000000000d", "91000000-1111-0000-0000-000000000004", "Manager", FIRM),
    "manager_none": ("91000000-0000-0000-0000-00000000000c", "91000000-1111-0000-0000-000000000003", "Manager", FIRM),
    "other_firm": ("91000000-0000-0000-0000-000000000010", "91000000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
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
                        _as(who) + f"SELECT to_location FROM {T} ORDER BY to_location;"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _refused_as(dsn: str, who: str, dml: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + dml], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr




ASSET_A, ASSET_B, ASSET_INT, ASSET_FOREIGN = (f"91000000-0000-0000-0000-00000000{n}" for n in ("0e01", "0e02", "0e03", "0e04"))


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e591_{uuid.uuid4().hex[:12]}"
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
            INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category, purchase_date, purchase_cost_paise, location)
            VALUES ('{ASSET_A}', '{FIRM}', '{CLIENT_A}', 'Lathe', 'Plant & Machinery', '2024-04-10', 10000000, 'Factory'),
                   ('{ASSET_B}', '{FIRM}', '{CLIENT_B}', 'Van', 'Vehicle', '2024-04-10', 10000000, 'Depot'),
                   ('{ASSET_INT}', '{FIRM}', '{INTERNAL}', 'Laptop', 'Computer', '2024-04-10', 10000000, 'Office'),
                   ('{ASSET_FOREIGN}', '{OTHER_FIRM}', '{FOREIGN}', 'Desk', 'Furniture', '2024-04-10', 10000000, 'Shop');
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


_NOW = object()   # the form opened on the register as it is now (the place and keeper read off the asset in the same statement)


def _lit(v) -> str:
    return "NULL" if v is None else f"$v${v}$v$"


def _call(asset: str, client: str, day, place, keeper, *, firm: str = FIRM, note=None, by: str = "partner", seen=_NOW) -> str:
    if seen is _NOW:
        was = (f"(SELECT location FROM fixed_assets WHERE id = '{asset}')", f"(SELECT custodian FROM fixed_assets WHERE id = '{asset}')")
    else:
        was = (_lit(seen[0]), _lit(seen[1]))
    return (f"public.record_fixed_asset_movement('{firm}', '{client}', '{asset}', {_lit(day)}::date, {was[0]}, {was[1]}, "
            f"{_lit(place)}, {_lit(keeper)}, {_lit(note)}, '{PEOPLE[by][0]}')")


def _move(dsn: str, asset: str, client: str, day, place, keeper, **kw) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SELECT id FROM {_call(asset, client, day, place, keeper, **kw)};")


def _sqlstate(dsn: str, asset: str, client: str, day, place, keeper, **kw) -> str:
    """The SQLSTATE the function raises for this call, or 'none'."""
    r = _psql(dsn, f"DO $$ BEGIN PERFORM {_call(asset, client, day, place, keeper, **kw)}; RAISE NOTICE 'state=none'; "
                   f"EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'state=%', SQLSTATE; END $$;")
    return r.stderr.split("state=")[-1].strip()


def _asset(dsn: str, asset: str) -> str:
    return _val(dsn, f"SELECT coalesce(location, '-') || '|' || coalesce(custodian, '-') FROM fixed_assets WHERE id = '{asset}'")


def test_a_movement_is_stored_with_the_assets_own_before_and_moves_the_asset_in_one_step(dsn):
    r = _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "  Warehouse   2 ", "Stores team", note="Shifted for repairs")
    assert r.returncode == 0, r.stderr
    assert _asset(dsn, ASSET_A) == "Warehouse 2|Stores team"
    assert _val(dsn, f"SELECT from_location || '|' || to_location || '|' || coalesce(from_custodian, '-') || '|' || to_custodian "
                     f"|| '|' || moved_on || '|' || note FROM {T} WHERE asset_id = '{ASSET_A}'") == \
        "Factory|Warehouse 2|-|Stores team|2025-06-01|Shifted for repairs"
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Warehouse 2", "R. Iyer").returncode == 0   # the same day, the keeper alone
    assert _val(dsn, f"SELECT count(*) FROM {T} WHERE asset_id = '{ASSET_A}'") == "2"
    assert _asset(dsn, ASSET_A) == "Warehouse 2|R. Iyer"


@pytest.mark.parametrize("why, call, says", [
    ("another client's asset", lambda d: _move(d, ASSET_B, CLIENT_A, "2025-06-01", "X", None), "Asset not found"),
    ("another firm's asset", lambda d: _move(d, ASSET_FOREIGN, FOREIGN, "2025-06-01", "X", None), "Asset not found"),
    ("a day not yet come", lambda d: _move(d, ASSET_A, CLIENT_A, "2099-01-01", "X", None), "has not come yet"),
    ("before the purchase", lambda d: _move(d, ASSET_A, CLIENT_A, "2024-04-09", "X", None), "before the asset was bought"),
    ("nothing moved", lambda d: _move(d, ASSET_A, CLIENT_A, "2025-06-01", " Factory ", None), "Nothing moved"),
    ("no date", lambda d: _move(d, ASSET_A, CLIENT_A, None, "X", None), "enter the date the asset moved"),
    ("a keeper too long", lambda d: _move(d, ASSET_A, CLIENT_A, "2025-06-01", "X", "k" * 201), "at most 200 characters"),
])
def test_what_cannot_be_a_movement_is_refused_and_the_asset_is_left_as_it_was(dsn, why, call, says):
    r = call(dsn)
    assert r.returncode != 0 and says in r.stderr, (why, r.stderr)
    assert _asset(dsn, ASSET_A) == "Factory|-" and _val(dsn, f"SELECT count(*) FROM {T}") == "0"


def test_a_movement_before_the_latest_one_is_refused(dsn):
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Warehouse", None).returncode == 0
    r = _move(dsn, ASSET_A, CLIENT_A, "2025-05-31", "Factory", None)
    assert r.returncode != 0 and "latest movement is dated 01 Jun 2025" in r.stderr
    assert _asset(dsn, ASSET_A) == "Warehouse|-"


def test_a_deleted_or_disposed_asset_cannot_be_moved(dsn):
    _ok(dsn, f"UPDATE fixed_assets SET deleted_at = now() WHERE id = '{ASSET_A}';")
    assert "Asset not found" in _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "X", None).stderr
    _ok(dsn, f"UPDATE fixed_assets SET deleted_at = NULL, is_disposed = true, disposal_date = '2025-05-01' WHERE id = '{ASSET_A}';")
    assert "has been disposed of" in _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "X", None).stderr


def test_a_form_opened_before_the_asset_last_moved_is_refused_and_records_nothing(dsn):
    # Two people open the form on Factory; the first records a move to Bay 3; the second only meant to name a keeper, and would
    # otherwise put the asset back in the Factory without a word.
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Bay 3", None, seen=("Factory", None)).returncode == 0
    r = _move(dsn, ASSET_A, CLIENT_A, "2025-06-02", "Factory", "R. Iyer", seen=("Factory", None))
    assert r.returncode != 0 and "has moved since this was opened: the register now has it at Bay 3, kept by nobody named" in r.stderr
    assert _sqlstate(dsn, ASSET_A, CLIENT_A, "2025-06-02", "Factory", "R. Iyer", seen=("Factory", None)) == "55000"
    assert _asset(dsn, ASSET_A) == "Bay 3|-" and _val(dsn, f"SELECT count(*) FROM {T}") == "1"
    # A keeper the register no longer holds is as stale as a place.
    r = _move(dsn, ASSET_A, CLIENT_A, "2025-06-02", "Bay 3", "R. Iyer", seen=("Bay 3", "Somebody"))
    assert r.returncode != 0 and "has moved since this was opened" in r.stderr
    # The form opened on the register as it is now (spaced differently, which is the same place) records the move.
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-02", "Bay 3", "R. Iyer", seen=(" Bay  3", None)).returncode == 0
    assert _asset(dsn, ASSET_A) == "Bay 3|R. Iyer"


def test_a_place_stored_with_stray_spaces_is_the_same_place_and_makes_no_movement_out_of_nothing(dsn):
    _ok(dsn, f"UPDATE fixed_assets SET location = E'Head  Office \\t' WHERE id = '{ASSET_A}';")   # written before 591
    r = _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Head Office", None)
    assert r.returncode != 0 and "Nothing moved" in r.stderr, r.stderr
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Head Office", "R. Iyer").returncode == 0      # the keeper alone moved
    assert _val(dsn, f"SELECT from_location || '|' || to_location FROM {T} WHERE asset_id = '{ASSET_A}'") == "Head Office|Head Office"
    assert _asset(dsn, ASSET_A) == "Head Office|R. Iyer"


def test_a_movement_stamps_the_asset_as_updated_and_a_blank_note_is_none(dsn):
    _ok(dsn, f"UPDATE fixed_assets SET updated_at = '2020-01-01' WHERE id = '{ASSET_A}';")
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "Bay 2", None, note="\n \t ").returncode == 0
    assert _val(dsn, f"SELECT updated_at > now() - interval '1 minute' FROM fixed_assets WHERE id = '{ASSET_A}'") == "t"
    assert _val(dsn, f"SELECT note IS NULL FROM {T} WHERE asset_id = '{ASSET_A}'") == "t"


def test_the_day_a_movement_may_not_pass_is_indias(dsn):
    # Only the five and a half hours after 18:30 UTC tell the two clocks apart, so the definition the database holds is read.
    src = _val(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FN}'::regprocedure")
    assert "(now() AT TIME ZONE 'Asia/Kolkata')::date" in src and "'UTC'" not in src


@pytest.mark.parametrize("why, kw, state", [
    ("not found", dict(asset=ASSET_B, client=CLIENT_A), "P0002"),
    ("a stale form", dict(seen=("Elsewhere", None)), "55000"),
    ("nothing moved", dict(place="Factory"), "23514"),
])
def test_each_refusal_carries_the_code_the_api_answers_by(dsn, why, kw, state):
    call = dict(asset=ASSET_A, client=CLIENT_A, day="2025-06-01", place="X", keeper=None)
    call.update(kw)
    asset, client, day, place, keeper = (call.pop(k) for k in ("asset", "client", "day", "place", "keeper"))
    assert _sqlstate(dsn, asset, client, day, place, keeper, **call) == state, why


def test_the_signed_in_role_reads_holds_no_write_and_cannot_call_the_function_and_the_service_role_can(dsn):
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        for role in ("authenticated", "anon"):
            assert _val(dsn, f"SELECT has_table_privilege('{role}', '{T}', '{verb}')") == "f", (role, verb)
    assert _val(dsn, f"SELECT has_table_privilege('authenticated', '{T}', 'SELECT')") == "t"
    assert _val(dsn, f"SELECT has_table_privilege('anon', '{T}', 'SELECT')") == "f"
    for role, can in (("authenticated", "f"), ("anon", "f"), ("service_role", "t")):
        assert _val(dsn, f"SELECT has_function_privilege('{role}', '{FN}', 'EXECUTE')") == can, role
    assert _val(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{FN}'::regprocedure") == "f"   # it runs as its caller
    call = (f"SELECT public.record_fixed_asset_movement('{FIRM}', '{CLIENT_A}', '{ASSET_A}', '2025-06-01', 'Factory', NULL, 'X', "
            f"NULL, NULL, NULL);")
    assert _refused_as(dsn, "partner", call)
    assert _asset(dsn, ASSET_A) == "Factory|-"


def test_each_person_reads_the_movements_of_the_clients_they_may_see_and_no_other(dsn):
    for asset, client, place in ((ASSET_A, CLIENT_A, "A2"), (ASSET_B, CLIENT_B, "B2"), (ASSET_INT, INTERNAL, "P2")):
        assert _move(dsn, asset, client, "2025-06-01", place, None).returncode == 0
    r = _move(dsn, ASSET_FOREIGN, FOREIGN, "2025-06-01", "F2", None, firm=OTHER_FIRM)       # its author is of another firm
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    assert _move(dsn, ASSET_FOREIGN, FOREIGN, "2025-06-01", "F2", None, firm=OTHER_FIRM, by="other_firm").returncode == 0
    assert _rows_as(dsn, "partner") == ["A2", "B2", "P2"]
    assert _rows_as(dsn, "manager_a") == ["A2"]
    assert _rows_as(dsn, "manager_internal") == []
    assert _rows_as(dsn, "manager_none") == []
    assert _rows_as(dsn, "other_firm") == ["F2"]
    assert _rows_as(dsn, "stranger") == []


def test_a_signed_in_member_can_neither_insert_nor_rewrite_nor_delete_a_movement(dsn):
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "A2", None).returncode == 0
    for who in ("partner", "manager_a"):
        assert _refused_as(dsn, who, f"INSERT INTO {T} (firm_id, client_id, asset_id, moved_on, to_location) "
                                     f"VALUES ('{FIRM}', '{CLIENT_A}', '{ASSET_A}', '2025-06-02', 'Forged');")
        assert _refused_as(dsn, who, f"UPDATE {T} SET to_location = 'Forged';")
        assert _refused_as(dsn, who, f"DELETE FROM {T};")
    assert _val(dsn, f"SELECT string_agg(to_location, ',') FROM {T}") == "A2"


def test_a_row_naming_another_firms_client_or_author_is_refused_and_the_keeper_is_one_line(dsn):
    r = _psql(dsn, f"INSERT INTO {T} (firm_id, client_id, asset_id, moved_on, to_location) "
                   f"VALUES ('{FIRM}', '{FOREIGN}', '{ASSET_A}', '2025-06-01', 'Cross-firm');")
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    r = _psql(dsn, f"INSERT INTO {T} (firm_id, client_id, asset_id, moved_on, to_location, created_by) "
                   f"VALUES ('{FIRM}', '{CLIENT_A}', '{ASSET_A}', '2025-06-01', 'By a stranger', '{PEOPLE['other_firm'][0]}');")
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    assert _psql(dsn, f"UPDATE fixed_assets SET custodian = '' WHERE id = '{ASSET_A}';").returncode != 0
    assert _psql(dsn, f"UPDATE fixed_assets SET custodian = '{'k' * 201}' WHERE id = '{ASSET_A}';").returncode != 0
    assert _psql(dsn, f"UPDATE fixed_assets SET custodian = 'Ok' WHERE id = '{ASSET_A}';").returncode == 0


def test_the_migration_runs_twice_and_its_rollback_removes_it_which_then_applies_again(dsn):
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-01", "A2", "K").returncode == 0
    # Supabase hands a new function to the signed-in roles by default, and this database does not, so the grant is made here and the
    # migration run again must take it away (it re-creates the function, which keeps an existing grant, and then revokes).
    _ok(dsn, f"GRANT EXECUTE ON FUNCTION {FN} TO authenticated, anon; GRANT INSERT, UPDATE (note) ON {T} TO authenticated;")
    _run(dsn, MIGRATION)
    for role in ("authenticated", "anon"):
        assert _val(dsn, f"SELECT has_function_privilege('{role}', '{FN}', 'EXECUTE')") == "f", role
    assert _val(dsn, f"SELECT has_any_column_privilege('authenticated', '{T}', 'UPDATE')") == "f"
    assert _val(dsn, f"SELECT count(*) FROM {T}") == "1"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, f"SELECT to_regclass('{T}') IS NULL") == "t"
    assert _val(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'record_fixed_asset_movement'") == "0"
    assert _val(dsn, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'fixed_assets' AND column_name = 'custodian'") == "0"
    assert _asset_location(dsn) == "A2"
    _run(dsn, MIGRATION)
    assert _move(dsn, ASSET_A, CLIENT_A, "2025-06-02", "A3", "K").returncode == 0


def _asset_location(dsn: str) -> str:
    return _val(dsn, f"SELECT location FROM fixed_assets WHERE id = '{ASSET_A}'")

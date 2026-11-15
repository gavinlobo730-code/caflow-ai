"""Migration 592 on a real database: a physical count of a client's fixed assets is a dated session with a finding per asset
(POST-A-112, its second half).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_an_assets_physical_verification_is_a_working_paper.py`) holds the routes and the service. Here:
    * `fixed_asset_held_on` says which assets a count must account for, and agrees with its mock-mode twin
      (`domain.fixed_assets.verification.held_on`) case by case;
    * `record_fixed_asset_finding` stores each of the four findings beside the register's place and keeper (tidied), replaces an
      asset's earlier finding in the same count, and refuses, storing nothing, a count or an asset that is not the client's, a closed
      count, an asset not held on the day counted, a finding that is not one of the four, "found elsewhere" with no place, and text over
      its length, each with the SQLSTATE the API answers by;
    * `close_fixed_asset_verification` refuses while an asset held on the day has no finding, naming how many, closes once each has one,
      and never again; a closed count takes no finding; a client has one open count at a time;
    * the privileges: the signed-in role reads both tables and holds no table or column write, may execute neither function, anon holds
      nothing, the service role executes both; the policies, as each person; the firm checks of 565 and 566;
    * the migration runs twice, takes a stray grant away, and its rollback removes it, after which it applies again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.fixed_assets.verification import held_on

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(API_ROOT.glob("migrations/592_an_assets_physical_verification_is_a_dated_session_with_a_finding_per_asset.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/592_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

COUNTS, FINDINGS = "public.fixed_asset_verifications", "public.fixed_asset_verification_findings"
FN_FIND = "public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid)"
FN_CLOSE = "public.close_fixed_asset_verification(uuid, uuid, uuid, uuid)"
FN_HELD = "public.fixed_asset_held_on(public.fixed_assets, date)"
FIRM, OTHER_FIRM = "92000000-0000-0000-0000-000000000001", "92000000-0000-0000-0000-000000000002"
CLIENT_A, CLIENT_B = "92000000-0000-0000-0000-0000000000a1", "92000000-0000-0000-0000-0000000000b2"
INTERNAL, FOREIGN = "92000000-0000-0000-0000-0000000000c3", "92000000-0000-0000-0000-0000000000d4"
STRANGER = "92000000-1111-0000-0000-0000000000ff"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("92000000-0000-0000-0000-00000000000a", "92000000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("92000000-0000-0000-0000-00000000000b", "92000000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_internal": ("92000000-0000-0000-0000-00000000000d", "92000000-1111-0000-0000-000000000004", "Manager", FIRM),
    "manager_none": ("92000000-0000-0000-0000-00000000000c", "92000000-1111-0000-0000-000000000003", "Manager", FIRM),
    "other_firm": ("92000000-0000-0000-0000-000000000010", "92000000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
DAY = "2026-03-31"
# Client A's assets, and whether each was held on DAY.
A1, A2, A_LATE, A_GONE, A_SOLD_AFTER, A_SOLD_ON = (f"92000000-0000-0000-0000-00000000{n}" for n in
                                                   ("0e01", "0e02", "0e03", "0e04", "0e05", "0e06"))
B1, INT1, FOREIGN1 = (f"92000000-0000-0000-0000-00000000{n}" for n in ("0e11", "0e12", "0e13"))
C_A, C_B, C_INT, C_FOREIGN = (f"92000000-0000-0000-0000-0000000c{n}" for n in ("00a1", "00b2", "00c3", "00d4"))


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


def _rows_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _refused_as(dsn: str, who: str, sql: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + sql], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr


def _lit(v) -> str:
    return "NULL" if v is None else f"$v${v}$v$"


def _find_call(count: str, asset: str, finding, *, client: str = CLIENT_A, firm: str = FIRM, found_in=None, note=None,
               by: str = "partner") -> str:
    return (f"public.record_fixed_asset_finding('{firm}', '{client}', '{count}', '{asset}', {_lit(finding)}, {_lit(found_in)}, "
            f"{_lit(note)}, '{PEOPLE[by][0]}')")


def _find(dsn: str, count: str, asset: str, finding, **kw) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SELECT id FROM {_find_call(count, asset, finding, **kw)};")


def _close(dsn: str, count: str, *, client: str = CLIENT_A, firm: str = FIRM) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SELECT status FROM public.close_fixed_asset_verification('{firm}', '{client}', '{count}', "
                      f"'{PEOPLE['partner'][0]}');")


def _state(dsn: str, call: str) -> str:
    """The SQLSTATE a call raises, or 'none'."""
    r = _psql(dsn, f"DO $$ BEGIN PERFORM {call}; RAISE NOTICE 'state=none'; "
                   f"EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'state=%', SQLSTATE; END $$;")
    return r.stderr.split("state=")[-1].strip()


ASSETS = {   # id: (client, firm, purchase_date, location, custodian, disposed_on, deleted)
    A1: (CLIENT_A, FIRM, "2024-04-10", "Factory", None, None, False),
    A2: (CLIENT_A, FIRM, "2024-04-10", "Head  Office \t", "R.  Iyer", None, False),
    A_LATE: (CLIENT_A, FIRM, "2026-04-01", "Factory", None, None, False),
    A_GONE: (CLIENT_A, FIRM, "2024-04-10", "Factory", None, "2025-01-01", False),
    A_SOLD_AFTER: (CLIENT_A, FIRM, "2024-04-10", "Depot", None, "2026-04-15", False),
    A_SOLD_ON: (CLIENT_A, FIRM, "2024-04-10", "Depot", None, DAY, False),
    B1: (CLIENT_B, FIRM, "2024-04-10", "Depot", None, None, False),
    INT1: (INTERNAL, FIRM, "2024-04-10", "Office", None, None, False),
    FOREIGN1: (FOREIGN, OTHER_FIRM, "2024-04-10", "Shop", None, None, False),
}
HELD_A = {A1, A2, A_SOLD_AFTER}


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e592_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items()) + f", ('{STRANGER}', 'employee@t.in')"
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        assets = ", ".join(
            f"('{i}', '{f}', '{c}', 'Asset {i[-4:]}', 'Plant & Machinery', '{bought}', 10000000, {_lit(place)}, {_lit(keeper)}, "
            f"{'true' if gone else 'false'}, {_lit(gone)})"
            for i, (c, f, bought, place, keeper, gone, _deleted) in ASSETS.items())
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
            INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category, purchase_date, purchase_cost_paise, location,
                                      custodian, is_disposed, disposal_date) VALUES {assets};
            INSERT INTO {COUNTS} (id, firm_id, client_id, verified_on, counted_by, created_by) VALUES
                ('{C_A}', '{FIRM}', '{CLIENT_A}', '{DAY}', 'Stores team', '{PEOPLE["partner"][0]}'),
                ('{C_B}', '{FIRM}', '{CLIENT_B}', '{DAY}', 'Stores team', '{PEOPLE["partner"][0]}'),
                ('{C_INT}', '{FIRM}', '{INTERNAL}', '{DAY}', 'Office manager', '{PEOPLE["partner"][0]}'),
                ('{C_FOREIGN}', '{OTHER_FIRM}', '{FOREIGN}', '{DAY}', 'Shop', '{PEOPLE["other_firm"][0]}');
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_which_assets_a_count_accounts_for_is_one_rule_in_both_places(dsn):
    for asset, (client, _f, bought, _place, _keeper, gone, _d) in ASSETS.items():
        if client != CLIENT_A:
            continue
        sql_says = _val(dsn, f"SELECT {FN_HELD.split('(')[0]}(a, '{DAY}') FROM fixed_assets a WHERE id = '{asset}'") == "t"
        python_says = held_on({"purchase_date": bought, "is_disposed": bool(gone), "disposal_date": gone, "deleted_at": None}, DAY)
        assert sql_says == python_says == (asset in HELD_A), asset
    _ok(dsn, f"UPDATE fixed_assets SET deleted_at = now() WHERE id = '{A1}';")
    assert _val(dsn, f"SELECT public.fixed_asset_held_on(a, '{DAY}') FROM fixed_assets a WHERE id = '{A1}'") == "f"
    assert held_on({"purchase_date": "2024-04-10", "deleted_at": "2026-01-01T00:00:00+00:00"}, DAY) is False


def test_each_finding_is_stored_beside_the_registers_place_and_keeper_tidied_and_a_second_replaces_the_first(dsn):
    assert _find(dsn, C_A, A1, "found").returncode == 0
    assert _find(dsn, C_A, A2, "found_elsewhere", found_in="  Bay   3 ", note="Moved for the audit").returncode == 0
    assert _find(dsn, C_A, A_SOLD_AFTER, "not_found").returncode == 0
    got = _val(dsn, f"SELECT finding || '|' || coalesce(found_in, '-') || '|' || coalesce(register_location, '-') || '|' "
                    f"|| coalesce(register_custodian, '-') || '|' || coalesce(note, '-') FROM {FINDINGS} WHERE asset_id = '{A2}'")
    assert got == "found_elsewhere|Bay 3|Head Office|R. Iyer|Moved for the audit"
    # A second finding of the same asset in the same count replaces the first; a place given for another finding is not kept.
    assert _find(dsn, C_A, A2, "damaged", found_in="Bay 3").returncode == 0
    assert _val(dsn, f"SELECT count(*) || '|' || string_agg(finding || ':' || coalesce(found_in, '-'), ',') FROM {FINDINGS} "
                     f"WHERE asset_id = '{A2}'") == "1|damaged:-"
    # A finding moves nothing in the register.
    assert _val(dsn, f"SELECT location = E'Head  Office \\t' FROM fixed_assets WHERE id = '{A2}'") == "t"


def test_the_register_beside_a_finding_is_the_register_on_the_day_counted_not_after_a_later_movement(dsn):
    assert _find(dsn, C_A, A1, "found_elsewhere", found_in="Bay 3").returncode == 0
    # The movement the screen suggests, dated after the count (591's own function, as the API records it).
    r = _psql(dsn, f"SELECT id FROM public.record_fixed_asset_movement('{FIRM}', '{CLIENT_A}', '{A1}', '2026-04-02', 'Factory', NULL, "
                   f"'Bay 3', NULL, NULL, '{PEOPLE['partner'][0]}');")
    assert r.returncode == 0, r.stderr
    # And a second one after it: the register on the count day is still the first later movement's "before", never the latest's.
    r = _psql(dsn, f"SELECT id FROM public.record_fixed_asset_movement('{FIRM}', '{CLIENT_A}', '{A1}', '2026-04-10', 'Bay 3', NULL, "
                   f"'Bay 5', 'Stores team', NULL, '{PEOPLE['partner'][0]}');")
    assert r.returncode == 0, r.stderr
    assert _find(dsn, C_A, A1, "found", note="Moved after the count").returncode == 0
    assert _val(dsn, f"SELECT finding || '|' || register_location || '|' || coalesce(register_custodian, '-') FROM {FINDINGS} "
                     f"WHERE asset_id = '{A1}'") == "found|Factory|-"
    # A later count, after the move, reads the asset where it now is.
    for asset in HELD_A:
        assert _find(dsn, C_A, asset, "found").returncode == 0
    assert _close(dsn, C_A).returncode == 0
    _ok(dsn, f"INSERT INTO {COUNTS} (id, firm_id, client_id, verified_on, counted_by) VALUES "
             f"('92000000-0000-0000-0000-0000000c00e1', '{FIRM}', '{CLIENT_A}', '2026-04-30', 'Stores team');")
    assert _find(dsn, "92000000-0000-0000-0000-0000000c00e1", A1, "found").returncode == 0
    assert _val(dsn, f"SELECT register_location FROM {FINDINGS} WHERE asset_id = '{A1}' "
                     f"AND verification_id = '92000000-0000-0000-0000-0000000c00e1'") == "Bay 5"


@pytest.mark.parametrize("why, call, says, state", [
    ("another client's count", lambda: _find_call(C_B, A1, "found"), "Verification not found", "P0002"),
    ("another firm's count", lambda: _find_call(C_FOREIGN, FOREIGN1, "found", client=FOREIGN, firm=FIRM), "Verification not found",
     "P0002"),
    ("another client's asset", lambda: _find_call(C_A, B1, "found"), "Asset not found", "P0002"),
    ("bought after the day", lambda: _find_call(C_A, A_LATE, "found"), "was not held on 31 Mar 2026", "23514"),
    ("disposed of before the day", lambda: _find_call(C_A, A_GONE, "found"), "was not held on 31 Mar 2026", "23514"),
    ("disposed of on the day", lambda: _find_call(C_A, A_SOLD_ON, "found"), "was not held on 31 Mar 2026", "23514"),
    ("not one of the four", lambda: _find_call(C_A, A1, "missing"), "one of found, found elsewhere", "23514"),
    ("no finding", lambda: _find_call(C_A, A1, None), "one of found, found elsewhere", "23514"),
    ("elsewhere with no place", lambda: _find_call(C_A, A1, "found_elsewhere", found_in="   "), "say where the asset was found",
     "23514"),
    ("a place too long", lambda: _find_call(C_A, A1, "found_elsewhere", found_in="p" * 201), "at most 200 characters", "23514"),
    ("a note too long", lambda: _find_call(C_A, A1, "found", note="n" * 501), "at most 500 characters", "23514"),
])
def test_what_cannot_be_a_finding_is_refused_with_its_code_and_stores_nothing(dsn, why, call, says, state):
    r = _psql(dsn, f"SELECT id FROM {call()};")
    assert r.returncode != 0 and says in r.stderr, (why, r.stderr)
    assert _state(dsn, call()) == state, why
    assert _val(dsn, f"SELECT count(*) FROM {FINDINGS}") == "0"


def test_a_count_closes_only_once_every_asset_held_on_the_day_has_a_finding_and_then_takes_no_finding_and_stays_closed(dsn):
    assert _find(dsn, C_A, A1, "found").returncode == 0
    r = _close(dsn, C_A)
    assert r.returncode != 0 and "2 assets held on 31 Mar 2026 have no finding yet" in r.stderr, r.stderr
    assert _find(dsn, C_A, A2, "found").returncode == 0
    r = _close(dsn, C_A)
    assert r.returncode != 0 and "1 asset held on 31 Mar 2026 has no finding yet" in r.stderr, r.stderr
    assert _state(dsn, f"public.close_fixed_asset_verification('{FIRM}', '{CLIENT_A}', '{C_A}', NULL)") == "23514"
    assert _find(dsn, C_A, A_SOLD_AFTER, "not_found").returncode == 0
    assert _close(dsn, C_A).returncode == 0
    assert _val(dsn, f"SELECT status || '|' || (closed_at IS NOT NULL) || '|' || closed_by FROM {COUNTS} WHERE id = '{C_A}'") == \
        f"closed|true|{PEOPLE['partner'][0]}"
    r = _find(dsn, C_A, A1, "damaged")
    assert r.returncode != 0 and "was closed on" in r.stderr and "cannot change" in r.stderr
    assert _state(dsn, _find_call(C_A, A1, "damaged")) == "55000"
    assert _val(dsn, f"SELECT finding FROM {FINDINGS} WHERE asset_id = '{A1}'") == "found"
    assert _state(dsn, f"public.close_fixed_asset_verification('{FIRM}', '{CLIENT_A}', '{C_A}', NULL)") == "55000"
    assert _state(dsn, f"public.close_fixed_asset_verification('{FIRM}', '{CLIENT_B}', '{C_A}', NULL)") == "P0002"
    # Another client's assets do not count against this one: the practice's count asks for its one asset alone.
    r = _close(dsn, C_INT, client=INTERNAL)
    assert r.returncode != 0 and "1 asset held on 31 Mar 2026 has no finding yet" in r.stderr, r.stderr
    assert _find(dsn, C_INT, INT1, "found", client=INTERNAL).returncode == 0
    assert _close(dsn, C_INT, client=INTERNAL).returncode == 0


def test_a_client_has_one_open_count_at_a_time_and_a_closed_one_does_not_count_against_it(dsn):
    r = _psql(dsn, f"INSERT INTO {COUNTS} (firm_id, client_id, verified_on, counted_by) VALUES ('{FIRM}', '{CLIENT_A}', '{DAY}', 'X');")
    assert r.returncode != 0 and "uq_fixed_asset_verifications_one_open" in r.stderr
    for asset in HELD_A:
        assert _find(dsn, C_A, asset, "found").returncode == 0
    assert _close(dsn, C_A).returncode == 0
    _ok(dsn, f"INSERT INTO {COUNTS} (firm_id, client_id, verified_on, counted_by) VALUES ('{FIRM}', '{CLIENT_A}', '{DAY}', 'X');")
    r = _psql(dsn, f"UPDATE {COUNTS} SET status = 'closed' WHERE id = '{C_B}';")
    assert r.returncode != 0 and "closed_has_its_time" in r.stderr


def test_the_signed_in_role_reads_holds_no_write_and_calls_neither_function_and_the_service_role_calls_both(dsn):
    for t in (COUNTS, FINDINGS):
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            for role in ("authenticated", "anon"):
                assert _val(dsn, f"SELECT has_table_privilege('{role}', '{t}', '{verb}')") == "f", (t, role, verb)
        assert _val(dsn, f"SELECT has_table_privilege('authenticated', '{t}', 'SELECT')") == "t"
        assert _val(dsn, f"SELECT has_table_privilege('anon', '{t}', 'SELECT')") == "f"
    for fn in (FN_FIND, FN_CLOSE, FN_HELD):
        for role, can in (("authenticated", "f"), ("anon", "f"), ("service_role", "t")):
            assert _val(dsn, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE')") == can, (fn, role)
    for fn in (FN_FIND, FN_CLOSE):
        assert _val(dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{fn}'::regprocedure") == "f"   # each runs as its caller
    assert _refused_as(dsn, "partner", f"SELECT {_find_call(C_A, A1, 'found')};")
    assert _refused_as(dsn, "partner", f"SELECT public.close_fixed_asset_verification('{FIRM}', '{CLIENT_A}', '{C_A}', NULL);")
    for who in ("partner", "manager_a"):
        assert _refused_as(dsn, who, f"INSERT INTO {COUNTS} (firm_id, client_id, verified_on, counted_by) "
                                     f"VALUES ('{FIRM}', '{CLIENT_A}', '{DAY}', 'Forged');")
        assert _refused_as(dsn, who, f"UPDATE {COUNTS} SET status = 'closed', closed_at = now();")
        assert _refused_as(dsn, who, f"DELETE FROM {FINDINGS};")
    assert _val(dsn, f"SELECT count(*) FROM {FINDINGS}") == "0"


def test_each_person_reads_the_counts_and_findings_of_the_clients_they_may_see_and_no_other(dsn):
    for count, asset, client in ((C_A, A1, CLIENT_A), (C_B, B1, CLIENT_B), (C_INT, INT1, INTERNAL)):
        assert _find(dsn, count, asset, "found", client=client).returncode == 0
    assert _find(dsn, C_FOREIGN, FOREIGN1, "found", client=FOREIGN, firm=OTHER_FIRM, by="other_firm").returncode == 0
    names = {C_A: "A", C_B: "B", C_INT: "P", C_FOREIGN: "F"}
    as_names = lambda rows: sorted(names[r] for r in rows)
    for who, sees in (("partner", ["A", "B", "P"]), ("manager_a", ["A"]), ("manager_internal", []), ("manager_none", []),
                      ("other_firm", ["F"]), ("stranger", [])):
        assert as_names(_rows_as(dsn, who, f"SELECT id FROM {COUNTS};")) == sees, who
        assert as_names(_rows_as(dsn, who, f"SELECT verification_id FROM {FINDINGS};")) == sees, who


def test_a_row_naming_another_firms_client_or_member_is_refused(dsn):
    # Closed counts, so the one-open rule is not what refuses them.
    r = _psql(dsn, f"INSERT INTO {COUNTS} (firm_id, client_id, verified_on, counted_by, status, closed_at) "
                   f"VALUES ('{FIRM}', '{FOREIGN}', '{DAY}', 'X', 'closed', now());")
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    r = _psql(dsn, f"INSERT INTO {COUNTS} (firm_id, client_id, verified_on, counted_by, created_by, status, closed_at) "
                   f"VALUES ('{FIRM}', '{CLIENT_B}', '2026-04-01', 'X', '{PEOPLE['other_firm'][0]}', 'closed', now());")
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    r = _find(dsn, C_A, A1, "found", by="other_firm")                       # the recorder is a member of another firm
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr


def test_the_migration_runs_twice_takes_a_stray_grant_away_and_its_rollback_removes_it_which_then_applies_again(dsn):
    assert _find(dsn, C_A, A1, "found").returncode == 0
    # Supabase hands a new function and table to the signed-in roles by default, and this database does not, so the grants are made
    # here and the migration run again must take them away.
    _ok(dsn, f"GRANT EXECUTE ON FUNCTION {FN_FIND}, {FN_CLOSE}, {FN_HELD} TO authenticated, anon; "
             f"GRANT INSERT, UPDATE (note) ON {COUNTS}, {FINDINGS} TO authenticated;")
    _run(dsn, MIGRATION)
    for fn in (FN_FIND, FN_CLOSE, FN_HELD):
        for role in ("authenticated", "anon"):
            assert _val(dsn, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE')") == "f", (fn, role)
    for t in (COUNTS, FINDINGS):
        assert _val(dsn, f"SELECT has_any_column_privilege('authenticated', '{t}', 'UPDATE')") == "f", t
    assert _val(dsn, f"SELECT count(*) FROM {FINDINGS}") == "1"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, f"SELECT to_regclass('{COUNTS}') IS NULL AND to_regclass('{FINDINGS}') IS NULL") == "t"
    assert _val(dsn, "SELECT count(*) FROM pg_proc WHERE proname IN ('record_fixed_asset_finding', "
                     "'close_fixed_asset_verification', 'fixed_asset_held_on')") == "0"
    _run(dsn, MIGRATION)
    assert _val(dsn, f"SELECT to_regclass('{COUNTS}') IS NOT NULL") == "t"

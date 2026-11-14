"""Migration 588: the database's latest stock-ledger row per item equals the Python twin's, exactly, and only the API can ask (POST-A-435).

WHY THIS FILE
    `public.stock_latest_rows` answers the stock register where the rows are, one probe per item. `domain/inventory/latest_rows`
    has to survive for the in-memory suite, which makes two implementations of one rule; they are safe only while something proves
    they agree. The rows are declared once and fed to both.

WHAT ONLY POSTGRES CAN PROVE
    * "latest" is the newest `created_at` as an INSTANT and then the larger `id` as a uuid, and the twin's text and time comparisons
      agree with Postgres's ordering of both (two rows recorded in one statement share `now()`, so the tie is real);
    * another firm's and another client's rows are never the answer, an item not asked for is not returned, and an item with no row is
      absent rather than a row of zeros;
    * the posting chain's own read (`_last_ledger_row`, run on the database) picks the same row;
    * the function returns ONE value (a set of rows is cut at PostgREST's db-max-rows) and states its tie-break;
    * EXECUTE is refused to `authenticated` and `anon` and allowed to `service_role`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from tests._cross_tenant_rows import LEGACY_ROWS_ALLOWED

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.inventory.latest_rows import latest_rows  # noqa: E402

FIRM = "f5880000-0000-0000-0000-000000000001"
OTHER_FIRM = "f5880000-0000-0000-0000-0000000000ff"
CLIENT = "c5880000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c5880000-0000-0000-0000-000000000002"
FAR_CLIENT = "c5880000-0000-0000-0000-0000000000ff"
ITEM = {k: f"15880000-0000-0000-0000-00000000000{n}" for n, k in enumerate(["tied", "plain", "never", "elsewhere", "unasked"], 1)}

#: (row id, item, firm, client, recorded at, running qty). "tied" has two rows in one instant: the larger uuid is the answer.
ROWS = [
    ("05880000-0000-0000-0000-00000000000a", "tied", FIRM, CLIENT, "2025-04-01 10:00:00+00", 4),
    ("05880000-0000-0000-0000-00000000000b", "tied", FIRM, CLIENT, "2025-04-01 15:30:00+05:30", 6),
    ("05880000-0000-0000-0000-000000000001", "tied", FIRM, CLIENT, "2025-03-31 10:00:00+00", 9),
    ("05880000-0000-0000-0000-000000000002", "plain", FIRM, CLIENT, "2025-01-01 00:00:00+00", 2),
    ("05880000-0000-0000-0000-000000000003", "plain", FIRM, CLIENT, "2025-02-01 00:00:00+00", 3),
    ("05880000-0000-0000-0000-000000000004", "elsewhere", FIRM, OTHER_CLIENT, "2025-05-01 00:00:00+00", 50),
    ("05880000-0000-0000-0000-000000000005", "plain", OTHER_FIRM, FAR_CLIENT, "2026-01-01 00:00:00+00", 70),
    ("05880000-0000-0000-0000-000000000006", "unasked", FIRM, CLIENT, "2025-06-01 00:00:00+00", 8),
]
ASKED = [ITEM["tied"], ITEM["plain"], ITEM["never"], ITEM["elsewhere"]]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"latest_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    owner = {CLIENT: FIRM, OTHER_CLIENT: FIRM, FAR_CLIENT: OTHER_FIRM}
    sql = [LEGACY_ROWS_ALLOWED + f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Latest', 'a@latest.in'), ('{OTHER_FIRM}', 'Else', 'b@latest.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT}', '{FIRM}', 'Stock Co', 'Private Limited'), ('{OTHER_CLIENT}', '{FIRM}', 'Other Co', 'Private Limited'),
  ('{FAR_CLIENT}', '{OTHER_FIRM}', 'Far Co', 'Private Limited');"""]
    homes = {"elsewhere": OTHER_CLIENT}
    for key, item_id in ITEM.items():
        client = homes.get(key, CLIENT)
        sql.append(f"INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) "
                   f"VALUES ('{item_id}', '{owner[client]}', '{client}', '{key}', 'good', 'Nos', '8471');")
    for row_id, key, firm, client, at, qty in ROWS:
        sql.append(f"""INSERT INTO inventory_stock_ledger (id, firm_id, client_id, service_catalogue_id, movement_date, movement_type,
  quantity_delta, unit_cost_paise, value_delta_paise, running_qty_units, running_avg_cost_paise, running_value_paise, created_at)
VALUES ('{row_id}', '{firm}', '{client}', '{ITEM[key]}', '{at[:10]}', 'adjustment', {qty}, 100, {qty * 100}, {qty}, 100, {qty * 100},
  '{at}');""")
    seeded = _psql(dsn, "\n".join(sql))
    assert seeded.returncode == 0, seeded.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql(dsn, firm=FIRM, client=CLIENT, items=ASKED) -> dict:
    arr = "ARRAY[" + ",".join(f"'{i}'::uuid" for i in items) + "]::uuid[]"
    r = _psql(dsn, f"SELECT public.stock_latest_rows('{firm}', '{client}', {arr});", tuples=True)
    assert r.returncode == 0, r.stderr
    return {row["service_catalogue_id"]: {"running_qty_units": str(row["running_qty_units"]).split(".")[0],
                                          "running_value_paise": int(row["running_value_paise"])}
            for row in json.loads(r.stdout.strip())}


def _python(firm=FIRM, client=CLIENT, items=ASKED) -> dict:
    rows = [{"id": rid, "service_catalogue_id": ITEM[key], "firm_id": f, "client_id": c, "created_at": at.replace(" ", "T") + (":00" if at.endswith(("+00", "+05")) else ""),
             "running_qty_units": str(qty), "running_value_paise": qty * 100, "running_avg_cost_paise": 100}
            for rid, key, f, c, at, qty in ROWS]
    got = latest_rows(rows, firm, client, items)
    return {k: {"running_qty_units": v["running_qty_units"], "running_value_paise": int(v["running_value_paise"])} for k, v in got.items()}


@pytest.mark.parametrize("firm,client", [(FIRM, CLIENT), (FIRM, OTHER_CLIENT), (OTHER_FIRM, FAR_CLIENT), (OTHER_FIRM, CLIENT)])
def test_the_database_and_the_twin_give_the_same_rows(db, firm, client):
    assert _sql(db, firm, client) == _python(firm, client)


def test_the_parity_is_about_something(db):
    got = _sql(db)
    assert got == {ITEM["tied"]: {"running_qty_units": "6", "running_value_paise": 600},
                   ITEM["plain"]: {"running_qty_units": "3", "running_value_paise": 300}}, \
        "the tie went to the larger id, another firm's newer row and the unasked item were not the answer, and no row was invented"


def test_the_posting_chains_own_read_picks_the_same_row(db):
    """`_last_ledger_row` (the row the next movement costs from), through a client that runs it on the database. It reads by item
    alone, so this is asked of the item whose rows are all its own client's: the posting's item check keeps it that way."""
    from domain import inventory_service
    from tests._signed_in_postgrest import SignedInDb
    chained = inventory_service._last_ledger_row(SignedInDb(db, role="service_role"), ITEM["tied"])
    assert str(chained["running_qty_units"]).split(".")[0] == "6"


def test_the_answer_is_one_value_and_the_tie_break_is_in_the_definition(db):
    """PostgREST cuts a set of rows at db-max-rows without a word (migration 265 measured it), so the function returns ONE value. And
    the index already hands rows back in id order, so a definition that dropped `id DESC` would still pass the parity above: the
    order it states is read from the definition."""
    r = _psql(db, "SELECT proretset, pg_get_functiondef(oid) FROM pg_proc WHERE proname = 'stock_latest_rows';", tuples=True)
    assert r.returncode == 0, r.stderr
    retset, definition = r.stdout.split("|", 1)
    assert retset.strip() == "f", "a set-returning function is cut at 1,000 rows by PostgREST"
    assert "ORDER BY l.created_at DESC, l.id DESC" in definition


def test_only_the_service_role_can_ask(db):
    call = f"SELECT count(*) FROM public.stock_latest_rows('{FIRM}', '{CLIENT}', ARRAY['{ITEM['plain']}'::uuid]);"
    for role in ("authenticated", "anon"):
        r = _psql(db, f"SET ROLE {role}; {call}")
        assert r.returncode != 0 and "permission denied" in r.stderr, (role, r.stderr)
    ok = _psql(db, f"SET ROLE service_role; {call}", tuples=True)
    assert ok.returncode == 0 and ok.stdout.strip() == "1", ok.stderr

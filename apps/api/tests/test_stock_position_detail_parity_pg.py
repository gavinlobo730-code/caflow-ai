"""Migration 398 — the SQL detail position must equal the Python one, exactly,
AND must total to what `stock_position_as_at` returns (INV-03a).

TWO CLAIMS, AND THE SECOND IS THE ONE THAT MATTERS

    The first is the ordinary one this repository makes of every SQL/Python
    pair: `public.stock_position_detail_as_at` and
    `domain/reporting/stock_position.position_detail` are two implementations
    of one rule, and they are safe only while something proves they agree —
    exactly as `test_stock_position_parity_pg.py` proves it for the item-level
    function.

    The second is new and is why the detail function was written as a SECOND
    function rather than as a change to the first: it sums the SAME deltas over
    the SAME rows, grouped one grain finer, so its total is
    `stock_position_as_at`'s total BY CONSTRUCTION. Two aggregates over one
    table that can disagree is how a register stops tying to its own ledger,
    and the only place that can be proved is against a real Postgres.

WHAT ONLY POSTGRES CAN PROVE HERE
      * NULL godown and NULL batch GROUP. Postgres treats NULLs as equal in
        GROUP BY and distinct in a unique index, and the whole "unallocated is
        a real row" claim rests on the first.
      * the ORDER BY with NULLS FIRST on the godown and the batch number and
        NULLS LAST on the expiry date, which the Python twin transcribes.
      * the LEFT JOINs to `godowns` and `inventory_batches`, so a movement
        whose godown was deleted still appears rather than vanishing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.reporting import stock_position  # noqa: E402

FIRM = "f3980000-0000-0000-0000-000000000001"
CLIENT = "c3980000-0000-0000-0000-000000000001"
ITEMS = {
    "widget": "13980000-0000-0000-0000-000000000001",
    "bracket": "13980000-0000-0000-0000-000000000002",
}
GODOWNS = {
    "bhiwandi": ("93980000-0000-0000-0000-000000000001", "27", "27AAACA1234A1Z5"),
    "hosur": ("93980000-0000-0000-0000-000000000002", "29", "29AAACA1234A1Z2"),
}
BATCHES = {
    "L-1": ("b3980000-0000-0000-0000-000000000001", "widget", "2027-06-30"),
    "L-2": ("b3980000-0000-0000-0000-000000000002", "widget", None),
}


class Mv:
    """One ledger row, declared once and fed to both halves."""

    def __init__(self, item, when, qty, value, *, godown=None, batch=None):
        self.item, self.when, self.qty, self.value = item, when, qty, value
        self.godown, self.batch = godown, batch

    def as_row(self) -> dict:
        """The shape PostgREST hands back — bigints and numerics as strings."""
        return {
            "service_catalogue_id": ITEMS[self.item],
            "movement_date": self.when,
            "quantity_delta": str(self.qty),
            "value_delta_paise": str(self.value),
            "godown_id": GODOWNS[self.godown][0] if self.godown else None,
            "batch_id": BATCHES[self.batch][0] if self.batch else None,
        }


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _seed_sql(movements: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Detail Parity', 'a@d.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
VALUES ('{CLIENT}', '{FIRM}', 'Detail Co', 'Private Limited');
"""]
    for name, item_id in ITEMS.items():
        out.append(
            "INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit) "
            f"VALUES ('{item_id}', '{FIRM}', '{CLIENT}', '{name}', 'good', 'Nos');")
    for name, (gid, state, gstin) in GODOWNS.items():
        out.append(
            "INSERT INTO godowns (id, firm_id, client_id, name, state_code, gstin) "
            f"VALUES ('{gid}', '{FIRM}', '{CLIENT}', '{name}', '{state}', '{gstin}');")
    for no, (bid, item, expiry) in BATCHES.items():
        exp = f"DATE '{expiry}'" if expiry else "NULL"
        out.append(
            "INSERT INTO inventory_batches (id, firm_id, client_id, "
            "service_catalogue_id, batch_no, expiry_date) "
            f"VALUES ('{bid}', '{FIRM}', '{CLIENT}', '{ITEMS[item]}', '{no}', {exp});")
    for i, m in enumerate(movements):
        row = m.as_row()
        god = f"'{row['godown_id']}'" if row["godown_id"] else "NULL"
        bat = f"'{row['batch_id']}'" if row["batch_id"] else "NULL"
        out.append(f"""
INSERT INTO inventory_stock_ledger
  (firm_id, client_id, service_catalogue_id, movement_date, movement_type,
   quantity_delta, unit_cost_paise, value_delta_paise,
   running_qty_units, running_avg_cost_paise, running_value_paise,
   godown_id, batch_id, created_at)
VALUES ('{FIRM}', '{CLIENT}', '{ITEMS[m.item]}', '{m.when}', 'adjustment',
        {m.qty}, 0, {m.value}, -999, 0, -999, {god}, {bat},
        NOW() + interval '{i} seconds');""")
    return "\n".join(out)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"stkdet_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_detail(dsn: str, as_of: str, item: str | None = None) -> dict:
    arg = f"'{item}'::uuid" if item else "NULL::uuid"
    r = _psql(dsn, f"""
        SELECT public.stock_position_detail_as_at(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{as_of}'::date, {arg});
    """, tuples=True)
    assert r.returncode == 0, f"stock_position_detail_as_at failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _sql_coarse(dsn: str, as_of: str) -> dict:
    r = _psql(dsn, f"""
        SELECT public.stock_position_as_at(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{as_of}'::date, NULL::uuid);
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def _python_detail(movements: list, as_of: str, item: str | None = None) -> dict:
    rows = [m.as_row() for m in movements
            if item is None or ITEMS[m.item] == item]
    names = {v: {"name": k, "unit": "Nos"} for k, v in ITEMS.items()}
    godowns = {gid: {"name": n, "state_code": s, "gstin": g}
               for n, (gid, s, g) in GODOWNS.items()}
    batches = {bid: {"batch_no": no, "expiry_date": exp}
               for no, (bid, _item, exp) in BATCHES.items()}
    return stock_position.position_detail(rows, as_of, names, godowns, batches)


def _normalise(doc: dict) -> dict:
    """Compares the numbers, not their spelling: Postgres renders
    NUMERIC(10,3) as '120.000' and Python's Decimal as '120'."""
    out = dict(doc)
    out["rows"] = [
        {k: (str(Decimal(str(v)).normalize()) if k == "qty_units" else v)
         for k, v in r.items()}
        for r in doc.get("rows") or []
    ]
    return out


def _both(dsn, movements, as_of, **kw):
    assert _psql(dsn, _seed_sql(movements)).returncode == 0
    return _normalise(_sql_detail(dsn, as_of, **kw)), \
        _normalise(_python_detail(movements, as_of, **kw))


# ── the two halves agree ────────────────────────────────────────────────────

SCENARIOS = {
    "one godown one batch": [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi", batch="L-1"),
    ],
    "two godowns": [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi"),
        Mv("widget", "2026-02-01", 40, 60000, godown="hosur"),
    ],
    "two batches in one godown": [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi", batch="L-1"),
        Mv("widget", "2026-02-01", 50, 60000, godown="bhiwandi", batch="L-2"),
    ],
    # THE ONE THAT PROVES NULLs GROUP. Every movement before migration 398 has
    # neither, and dropping them would make the detail sum to less than the
    # total with nothing saying why.
    "unallocated movements": [
        Mv("widget", "2026-01-01", 100, 100000),
        Mv("widget", "2026-02-01", 30, 30000),
        Mv("widget", "2026-03-01", 20, 25000, godown="bhiwandi"),
    ],
    "issues as well as receipts": [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi", batch="L-1"),
        Mv("widget", "2026-02-01", -40, -40000, godown="bhiwandi", batch="L-1"),
    ],
    "a lot fully issued nets to nothing": [
        Mv("widget", "2026-01-01", 10, 10000, godown="bhiwandi", batch="L-1"),
        Mv("widget", "2026-02-01", -10, -10000, godown="bhiwandi", batch="L-1"),
    ],
    "an oversold godown goes negative": [
        Mv("widget", "2026-01-01", 5, 5000, godown="hosur"),
        Mv("widget", "2026-02-01", -8, -8000, godown="hosur"),
    ],
    "two items, mixed allocation": [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi", batch="L-1"),
        Mv("bracket", "2026-01-01", 7, 7000, godown="hosur"),
        Mv("bracket", "2026-02-01", 3, 3300),
    ],
    "fractional quantities": [
        Mv("widget", "2026-01-01", "12.345", 12345, godown="bhiwandi"),
        Mv("widget", "2026-02-01", "-0.345", -345, godown="bhiwandi"),
    ],
}


@pytest.mark.parametrize("label", sorted(SCENARIOS))
def test_the_two_halves_agree(db, label):
    sql, py = _both(db, SCENARIOS[label], "2026-12-31")
    assert sql == py, f"{label}: SQL and Python disagree"


@pytest.mark.parametrize("label", sorted(SCENARIOS))
def test_the_detail_totals_to_the_item_level_position(db, label):
    """THE CLAIM THE SECOND FUNCTION EXISTS TO KEEP. One SUM over one set of
    deltas, grouped differently — so the two totals are one number, and a
    register that stops tying to its own ledger is impossible by
    construction rather than by care."""
    movements = SCENARIOS[label]
    assert _psql(db, _seed_sql(movements)).returncode == 0
    coarse = _sql_coarse(db, "2026-12-31")
    detail = _sql_detail(db, "2026-12-31")
    assert detail["total_value_paise"] == coarse["total_value_paise"]


def test_an_as_at_date_cuts_both_the_same_way(db):
    movements = [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi"),
        Mv("widget", "2026-06-01", 50, 50000, godown="hosur"),
    ]
    sql, py = _both(db, movements, "2026-03-31")
    assert sql == py
    assert sql["total_value_paise"] == 100000


def test_one_item_can_be_asked_for(db):
    movements = [
        Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi"),
        Mv("bracket", "2026-01-01", 7, 7000, godown="hosur"),
    ]
    sql, py = _both(db, movements, "2026-12-31", item=ITEMS["widget"])
    assert sql == py
    assert {r["service_catalogue_id"] for r in sql["rows"]} == {ITEMS["widget"]}


def test_a_deleted_godown_does_not_make_its_stock_vanish(db):
    """The LEFT JOIN. A row whose godown row is gone still carries its value —
    otherwise the detail would silently stop totalling to the item position."""
    movements = [Mv("widget", "2026-01-01", 100, 100000, godown="bhiwandi")]
    assert _psql(db, _seed_sql(movements)).returncode == 0
    gid = GODOWNS["bhiwandi"][0]
    assert _psql(db, f"DELETE FROM godowns WHERE id = '{gid}';").returncode == 0
    detail = _sql_detail(db, "2026-12-31")
    assert detail["total_value_paise"] == 100000
    # ON DELETE SET NULL on the ledger column, so it reads as unallocated.
    assert detail["rows"][0]["godown_id"] is None


def test_the_batch_expiry_travels_with_the_row(db):
    """So the expiry report is built from the position rather than from a
    second read of the ledger."""
    movements = [Mv("widget", "2026-01-01", 100, 100000,
                    godown="bhiwandi", batch="L-1")]
    sql, py = _both(db, movements, "2026-12-31")
    assert sql == py
    assert sql["rows"][0]["expiry_date"] == "2027-06-30"
    assert sql["rows"][0]["batch_no"] == "L-1"

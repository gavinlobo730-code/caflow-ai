"""
Migration 363 — the SQL stock position must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    public.stock_position_as_at aggregates where the rows already are: the
    answer is one line per item and the input is every movement the client has
    ever made, so CLAUDE.md's reporting rule puts it in the database.
    domain/reporting/stock_position.py has to survive anyway — mock mode, local
    dev and the in-memory suite have no DATABASE_URL and no SQL functions —
    which creates the thing CLAUDE.md warns about: two implementations of one
    rule, which drift.

    They are safe only while something proves they agree. Every scenario below
    is declared ONCE, as a list of movements, and fed to both halves.

WHAT ONLY POSTGRES CAN PROVE
      * `round(numeric)` and Python's Decimal ROUND_HALF_UP must agree on the
        derived average cost. Postgres rounds half AWAY FROM ZERO on numeric,
        which is half-up for positives and differs for negatives — a stock
        position can be negative after an oversell, so the .5 cases are here
        on purpose.
      * NUMERIC(10,3) round-trips through PostgREST as a string; the Python
        half must not turn it into a float anywhere.
      * the function is SECURITY DEFINER with the RLS restated in its body
        (migration 279's lesson), and access control can only be exercised
        against a real `authenticated` caller.
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

FIRM = "f3630000-0000-0000-0000-000000000001"
CLIENT = "c3630000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c3630000-0000-0000-0000-000000000002"
OTHER_FIRM = "f3630000-0000-0000-0000-0000000000ff"
AUTH = "a3630000-0000-0000-0000-000000000001"
USER = "e3630000-0000-0000-0000-000000000001"

ITEMS = {
    "widget": "13630000-0000-0000-0000-000000000001",
    "bracket": "13630000-0000-0000-0000-000000000002",
    "sprocket": "13630000-0000-0000-0000-000000000003",
}


class Mv:
    """One inventory_stock_ledger row, declared once for both halves.

    `running_*` are deliberately set to nonsense in some scenarios: the whole
    claim of migration 363 is that the position is summed from the DELTAS and
    never reads those columns, and a scenario where the two disagree is the
    only scenario that proves it.
    """

    def __init__(self, item, when, qty, value, *, client=CLIENT, firm=FIRM,
                 running_qty="-999", running_value=-999, seq=0):
        self.item, self.when, self.qty, self.value = item, when, qty, value
        self.client, self.firm = client, firm
        self.running_qty, self.running_value, self.seq = running_qty, running_value, seq

    def as_row(self) -> dict:
        """The shape PostgREST hands back: bigints as strings, numerics too."""
        return {
            "service_catalogue_id": ITEMS[self.item],
            "movement_date": self.when,
            "quantity_delta": str(self.qty),
            "value_delta_paise": str(self.value),
        }


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _seed_sql(movements: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES
  ('{FIRM}', 'Stock Parity', 'a@parity.in'),
  ('{OTHER_FIRM}', 'Someone Else', 'b@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT}', '{FIRM}', 'Stock Co', 'Private Limited'),
  ('{OTHER_CLIENT}', '{FIRM}', 'Other Co', 'Private Limited');
"""]
    for name, item_id in ITEMS.items():
        out.append(
            "INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) "
            f"VALUES ('{item_id}', '{FIRM}', '{CLIENT}', '{name}', 'good', 'Nos', '8471');")
    for i, m in enumerate(movements):
        out.append(f"""
INSERT INTO inventory_stock_ledger
  (firm_id, client_id, service_catalogue_id, movement_date, movement_type,
   quantity_delta, unit_cost_paise, value_delta_paise,
   running_qty_units, running_avg_cost_paise, running_value_paise, created_at)
VALUES ('{m.firm}', '{m.client}', '{ITEMS[m.item]}', '{m.when}', 'adjustment',
        {m.qty}, 0, {m.value},
        {m.running_qty}, 0, {m.running_value},
        NOW() + interval '{i} seconds');""")
    return "\n".join(out)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"stkpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_position(dsn: str, as_of: str, client: str = CLIENT, firm: str = FIRM,
                  item: str | None = None) -> dict:
    arg = f"'{item}'::uuid" if item else "NULL::uuid"
    r = _psql(dsn, f"""
        SELECT public.stock_position_as_at(
            '{firm}'::uuid, '{client}'::uuid, '{as_of}'::date, {arg});
    """, tuples=True)
    assert r.returncode == 0, f"stock_position_as_at failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _python_position(movements: list, as_of: str, client: str = CLIENT,
                     firm: str = FIRM, item: str | None = None) -> dict:
    rows = [m.as_row() for m in movements
            if m.client == client and m.firm == firm
            and (item is None or ITEMS[m.item] == item)]
    names = {v: {"name": k, "unit": "Nos", "hsn_sac": "8471"} for k, v in ITEMS.items()}
    return stock_position.position(rows, as_of, names)


def _normalise(doc: dict) -> dict:
    """Compares the numbers, not their spelling. Postgres renders NUMERIC(10,3)
    as '120.000' and Python's Decimal as '120'; both mean 120 units, and a
    parity test that fails on the trailing zeros is a parity test people
    learn to ignore."""
    out = dict(doc)
    out["items"] = [
        {**r, "qty_units": str(Decimal(str(r["qty_units"])).normalize())}
        for r in doc.get("items") or []
    ]
    return out


def _both(dsn, movements, as_of, **kw):
    assert _psql(dsn, _seed_sql(movements)).returncode == 0
    return _normalise(_sql_position(dsn, as_of, **kw)), \
        _normalise(_python_position(movements, as_of, **kw))


# ── The scenarios ────────────────────────────────────────────────────────────

BACKDATED = [
    # The finding's own case: a 10 July sale recorded first, then a 1 July
    # purchase recorded after it. The stored running columns are the ones the
    # perpetual chain produced and they disagree with the date order.
    Mv("widget", "2026-06-01", 100, 100_000, running_qty="100", running_value=100_000),
    Mv("widget", "2026-07-10", -10, -10_000, running_qty="90", running_value=90_000),
    Mv("widget", "2026-07-01", 20, 20_000, running_qty="110", running_value=110_000),
]

MIXED = BACKDATED + [
    Mv("bracket", "2026-05-15", 3, 1_000),        # 333.33/unit — rounds
    Mv("sprocket", "2026-04-01", 7, 2_345),       # 335.0 — the .5 case
    Mv("sprocket", "2026-04-02", -7, -2_345),     # ...then nil, so no unit cost
]

OVERSOLD = [
    Mv("widget", "2026-04-01", 5, 5_000),
    Mv("widget", "2026-04-02", -8, -5_000),       # oversold: negative quantity
]

FOREIGN = MIXED + [
    Mv("widget", "2026-06-01", 999, 999_000, client=OTHER_CLIENT),
    Mv("bracket", "2026-06-01", 888, 888_000, firm=OTHER_FIRM, client=OTHER_CLIENT),
]


@pytest.mark.parametrize("as_of", [
    "2026-03-31",   # before everything
    "2026-04-01", "2026-04-02",
    "2026-05-15",
    "2026-06-01", "2026-06-30",
    "2026-07-01",   # the backdated purchase's own date
    "2026-07-05", "2026-07-10", "2026-07-31",
    "2029-12-31",   # long after
])
def test_every_date_gives_the_same_answer_on_both_halves(db, as_of):
    sql, py = _both(db, MIXED, as_of)
    assert sql == py


def test_the_backdated_purchase_counts_on_its_own_date_on_both_halves(db):
    sql, py = _both(db, BACKDATED, "2026-07-01")
    assert sql == py
    assert Decimal(sql["items"][0]["qty_units"]) == Decimal("120")
    # ...and NOT the 110 the stored running column on that row carries.


def test_a_negative_position_gives_no_unit_cost_on_either_half(db):
    sql, py = _both(db, OVERSOLD, "2026-04-30")
    assert sql == py
    assert Decimal(sql["items"][0]["qty_units"]) == Decimal("-3")
    assert sql["items"][0]["avg_cost_paise"] == 0


def test_another_client_and_another_firm_are_not_in_the_answer(db):
    sql, py = _both(db, FOREIGN, "2026-07-31")
    assert sql == py
    assert sql["total_value_paise"] == _normalise(
        _python_position(MIXED, "2026-07-31"))["total_value_paise"]


def test_one_item_can_be_asked_for_alone(db):
    sql, py = _both(db, MIXED, "2026-07-31", item=ITEMS["widget"])
    assert sql == py
    assert len(sql["items"]) == 1


def test_the_total_is_not_the_sum_of_the_rounded_averages(db):
    """1,000 paise over 3 units is 333.33; three times the rounded 333 is 999.
    Both halves must total 1,000 — the figure that ties to the Inventory
    control account."""
    sql, py = _both(db, [Mv("bracket", "2026-05-15", 3, 1_000)], "2026-05-31")
    assert sql == py
    assert sql["total_value_paise"] == 1_000
    assert sql["items"][0]["avg_cost_paise"] == 333


# ── Access control ───────────────────────────────────────────────────────────

def _seed_caller(dsn: str, role: str = "Partner") -> None:
    r = _psql(dsn, f"""
        INSERT INTO auth.users (id) VALUES ('{AUTH}') ON CONFLICT DO NOTHING;
        INSERT INTO users (id, firm_id, full_name, email, role, auth_user_id)
          VALUES ('{USER}','{FIRM}','P','p@parity.in','{role}','{AUTH}');""")
    assert r.returncode == 0, r.stderr


def test_it_is_security_definer(db):
    """Migration 279's lesson, applied at the start rather than after an
    outage: as INVOKER the per-row policy cascade on a movement table is what
    made cash_flow_report hit the statement timeout."""
    r = _psql(db, """
        SELECT p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname='public' AND p.proname='stock_position_as_at';""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t"


def test_another_firms_position_is_refused(db):
    assert _psql(db, _seed_sql(MIXED)).returncode == 0
    _seed_caller(db)
    r = _psql(db, f"""
        SET LOCAL ROLE authenticated;
        SET LOCAL request.jwt.claims = '{{"sub":"{AUTH}"}}';
        SELECT public.stock_position_as_at(
            '{OTHER_FIRM}'::uuid, '{CLIENT}'::uuid, '2026-07-31'::date, NULL::uuid);
    """, tuples=True)
    assert r.returncode != 0
    assert "is not the caller" in r.stderr


def test_anon_cannot_execute_it(db):
    r = _psql(db, """
        SELECT has_function_privilege('anon',
            'public.stock_position_as_at(uuid,uuid,date,uuid)', 'EXECUTE');
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f"

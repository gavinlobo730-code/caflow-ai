"""Migration 408 — the SQL stock ageing must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    `public.stock_ageing_as_at` aggregates where the rows already are: the
    answer is one line per item and the input is every movement the client has
    ever made, so CLAUDE.md's reporting rule puts it in the database.
    `domain/reporting/stock_ageing.py` has to survive anyway — mock mode, local
    dev and the in-memory suite have no DATABASE_URL and no SQL functions —
    which creates the thing CLAUDE.md warns about: two implementations of one
    rule, which drift. They are safe only while something proves they agree, so
    every scenario below is declared ONCE and fed to both halves.

WHAT ONLY POSTGRES CAN PROVE
      * **The FIFO layer ORDER.** The SQL breaks ties on (movement_date,
        created_at, id) inside a window function; the Python sorts on the same
        three. `SAME_DATE_SAME_SECOND` is that case — two receipts on one date
        written in one transaction, so only the id separates them.

        WHAT IT ACTUALLY PROVES IS NARROWER THAN IT LOOKS, and saying so is
        the point: two receipts sharing a movement_date share a BAND by
        construction, so whichever is consumed first, the band quantities and
        the pro-rated value are identical. The tie-break cannot move a figure
        today. It is pinned anyway because the two halves must walk the SAME
        layers — a later change that does make the layer identity matter (a
        layer's own cost, say) would otherwise make them disagree silently.
      * **The largest-remainder tie-break.** Postgres ranks with a window
        function and Python with `sorted`, and the two agree only because the
        SQL spells the youngest-to-oldest band order out rather than letting
        alphabetical order on the band key stand in for it — 'd0_30' sorts
        AFTER 'd181_365' alphabetically, so the alphabetical reading would put
        the extra paisa in a different band. `ODD_PAISE` is that case.
      * NUMERIC(10,3) round-trips through PostgREST as a string; the Python
        half must not turn it into a float anywhere.
      * The function is SECURITY DEFINER with the RLS restated in its body
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

from domain.reporting import stock_ageing  # noqa: E402

FIRM = "f4080000-0000-0000-0000-000000000001"
CLIENT = "c4080000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c4080000-0000-0000-0000-000000000002"
OTHER_FIRM = "f4080000-0000-0000-0000-0000000000ff"

ITEMS = {
    "widget": "14080000-0000-0000-0000-000000000001",
    "bracket": "14080000-0000-0000-0000-000000000002",
    "sprocket": "14080000-0000-0000-0000-000000000003",
}
ROW_IDS: dict[int, str] = {}


class Mv:
    """One inventory_stock_ledger row, declared once for both halves.

    `running_*` are deliberately nonsense: migration 408 sums the DELTAS like
    363 before it, and a scenario where the stored running columns disagree is
    the only scenario that proves it never reads them.
    """

    def __init__(self, item, when, qty, value, *, client=CLIENT, firm=FIRM,
                 same_second=False):
        self.item, self.when, self.qty, self.value = item, when, qty, value
        self.client, self.firm = client, firm
        self.same_second = same_second

    def as_row(self, i: int) -> dict:
        """The shape PostgREST hands back: numerics and bigints as strings."""
        return {
            "id": ROW_IDS[i],
            "service_catalogue_id": ITEMS[self.item],
            "movement_date": self.when,
            "quantity_delta": str(self.qty),
            "value_delta_paise": str(self.value),
            "created_at": _created_at(i, self.same_second),
        }


def _created_at(i: int, same_second: bool) -> str:
    """The SAME expression the seed uses, so the two halves sort identically."""
    secs = 0 if same_second else i
    return f"2020-01-01T00:00:{secs:02d}+00:00"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _seed_sql(movements: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES
  ('{FIRM}', 'Ageing Parity', 'a@ageing.in'),
  ('{OTHER_FIRM}', 'Someone Else', 'b@ageing.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT}', '{FIRM}', 'Ageing Co', 'Private Limited'),
  ('{OTHER_CLIENT}', '{FIRM}', 'Other Co', 'Private Limited');
"""]
    for name, item_id in ITEMS.items():
        out.append(
            "INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) "
            f"VALUES ('{item_id}', '{FIRM}', '{CLIENT}', '{name}', 'good', 'Nos', '8471');")
    ROW_IDS.clear()
    for i, m in enumerate(movements):
        # The id is FIXED rather than generated, because it is the third FIFO
        # sort key and both halves have to agree on it.
        ROW_IDS[i] = f"a4080000-0000-0000-0000-{i:012d}"
        out.append(f"""
INSERT INTO inventory_stock_ledger
  (id, firm_id, client_id, service_catalogue_id, movement_date, movement_type,
   quantity_delta, unit_cost_paise, value_delta_paise,
   running_qty_units, running_avg_cost_paise, running_value_paise, created_at)
VALUES ('{ROW_IDS[i]}', '{m.firm}', '{m.client}', '{ITEMS[m.item]}', '{m.when}',
        'adjustment', {m.qty}, 0, {m.value},
        -999, 0, -999,
        '{_created_at(i, m.same_second)}'::timestamptz);""")
    return "\n".join(out)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"agepar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_ageing(dsn: str, as_of: str, client: str = CLIENT, firm: str = FIRM,
                item: str | None = None) -> dict:
    arg = f"'{item}'::uuid" if item else "NULL::uuid"
    r = _psql(dsn, f"""
        SELECT public.stock_ageing_as_at(
            '{firm}'::uuid, '{client}'::uuid, '{as_of}'::date, {arg});
    """, tuples=True)
    assert r.returncode == 0, f"stock_ageing_as_at failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _python_ageing(movements: list, as_of: str, client: str = CLIENT,
                   firm: str = FIRM, item: str | None = None) -> dict:
    rows = [m.as_row(i) for i, m in enumerate(movements)
            if m.client == client and m.firm == firm
            and (item is None or ITEMS[m.item] == item)]
    names = {v: {"name": k, "unit": "Nos"} for k, v in ITEMS.items()}
    return stock_ageing.ageing(rows, as_of, names)


def _q(v) -> str:
    """'120.000' and '120' are one quantity; `3E+1` is not a way to write 30.

    `Decimal.normalize()` alone produces scientific notation for a trailing
    zero, so the comparison is fixed-point throughout.
    """
    return format(Decimal(str(v)).normalize(), "f")


def _normalise(doc: dict) -> dict:
    """Compares the numbers, not their spelling: Postgres renders
    NUMERIC(10,3) as '120.000' and Python's Decimal as '120'. A parity test
    that fails on trailing zeros is a parity test people learn to ignore."""
    out = dict(doc)
    out["items"] = [
        {**r,
         "qty_units": _q(r["qty_units"]),
         "band_qty": {k: _q(v) for k, v in (r.get("band_qty") or {}).items()}}
        for r in doc.get("items") or []
    ]
    out["total_qty_by_band"] = {
        k: _q(v) for k, v in (doc.get("total_qty_by_band") or {}).items()}
    # PRESENTATION IS NOT A FIGURE, and only the figures are being pinned. The
    # Python half carries the four caveats and the band LABELS; the SQL carries
    # neither and does not need to, because `stock_ageing_service` attaches
    # them to whichever half produced the numbers. Emitting English from a SQL
    # function would be a second copy of a vocabulary the domain module owns —
    # the Schedule III caption lesson.
    out.pop("notes", None)
    out.pop("band_labels", None)
    return out


def _both(dsn, movements, as_of, **kw):
    assert _psql(dsn, _seed_sql(movements)).returncode == 0
    return _normalise(_sql_ageing(dsn, as_of, **kw)), \
        _normalise(_python_ageing(movements, as_of, **kw))


# ── The scenarios ────────────────────────────────────────────────────────────

# An item that keeps turning over and is STILL carrying three-year-old stock
# behind it: the case the finding is about, and the case Last Moved / Days Idle
# cannot see, because the item moved last month.
STILL_SELLING = [
    Mv("widget", "2023-06-01", 100, 1_000_000),
    Mv("widget", "2026-08-20", 50, 600_000),
    Mv("widget", "2026-09-01", -30, -320_000),
]

# FIFO eats the oldest first: 120 out of 150 leaves 30 of the NEWEST.
EATEN_THROUGH = [
    Mv("widget", "2023-06-01", 100, 1_000_000),
    Mv("widget", "2026-08-20", 50, 600_000),
    Mv("widget", "2026-09-01", -120, -1_280_000),
]

OVERSOLD = [
    Mv("bracket", "2026-04-01", 5, 5_000),
    Mv("bracket", "2026-04-02", -8, -5_000),
]

EXACTLY_NIL = [
    Mv("sprocket", "2026-04-01", 10, 10_000),
    Mv("sprocket", "2026-04-02", -10, -10_000),
]

# TWO RECEIPTS ON ONE DATE IN ONE TRANSACTION. Same movement_date, same
# created_at — so only the id breaks the tie, and only if both halves use it.
SAME_DATE_SAME_SECOND = [
    Mv("widget", "2024-01-01", 10, 10_000, same_second=True),
    Mv("widget", "2024-01-01", 10, 90_000, same_second=True),
    Mv("widget", "2026-09-01", -15, -50_000),
]

# A carrying amount that does not divide: 1 paisa over two bands.
ODD_PAISE = [
    Mv("widget", "2023-01-01", 1, 0),
    Mv("widget", "2026-09-01", 2, 1),
]

MIXED = STILL_SELLING + OVERSOLD + EXACTLY_NIL

FOREIGN = MIXED + [
    Mv("widget", "2026-06-01", 999, 999_000, client=OTHER_CLIENT),
    Mv("bracket", "2026-06-01", 888, 888_000, firm=OTHER_FIRM, client=OTHER_CLIENT),
]


@pytest.mark.parametrize("as_of", [
    "2023-05-31",   # before everything
    "2023-06-01", "2024-01-01",
    "2026-04-01", "2026-04-02",
    "2026-08-20", "2026-09-01", "2026-09-18",
    "2029-12-31",   # long after, so everything falls in the last band
])
def test_every_date_gives_the_same_answer_on_both_halves(db, as_of):
    sql, py = _both(db, MIXED, as_of)
    assert sql == py


def test_an_item_that_keeps_selling_still_shows_its_old_stock(db):
    """THE FINDING, AS A NUMBER. Last Moved says 1 September — seventeen days
    ago — and 70 of the 120 units on hand have been there since June 2023."""
    sql, py = _both(db, STILL_SELLING, "2026-09-18", item=ITEMS["widget"])
    assert sql == py
    row = sql["items"][0]
    assert _q(row["qty_units"]) == "120"
    assert _q(row["band_qty"]["d365_plus"]) == "70"
    assert _q(row["band_qty"]["d0_30"]) == "50"
    assert row["oldest_holding_date"] == "2023-06-01"


def test_fifo_consumes_the_oldest_layer_first(db):
    sql, py = _both(db, EATEN_THROUGH, "2026-09-18", item=ITEMS["widget"])
    assert sql == py
    row = sql["items"][0]
    assert _q(row["band_qty"]["d365_plus"]) == "0", (
        "120 units out of 150 must consume the whole three-year-old layer")
    assert _q(row["band_qty"]["d0_30"]) == "30"


def test_the_bands_foot_to_the_quantity_and_the_carrying_amount(db):
    """The report's one hard invariant. The quantity bands sum to the position
    migration 363 reports and the value bands to the carrying amount that ties
    to the Inventory control account — otherwise somebody foots it and finds a
    stock ageing report that disagrees with the balance sheet."""
    sql, py = _both(db, STILL_SELLING, "2026-09-18", item=ITEMS["widget"])
    assert sql == py
    row = sql["items"][0]
    assert sum(Decimal(v) for v in row["band_qty"].values()) == Decimal(row["qty_units"])
    assert sum(row["band_value_paise"].values()) == row["value_paise"]


def test_an_odd_paisa_lands_in_the_same_band_on_both_halves(db):
    """Largest remainder, and the tie-break has to agree. Postgres ranks with a
    window function and Python with `sorted`; they agree only because the SQL
    spells the band ORDER out rather than letting alphabetical order on the key
    stand in — 'd0_30' sorts after 'd181_365' alphabetically."""
    sql, py = _both(db, ODD_PAISE, "2026-09-18", item=ITEMS["widget"])
    assert sql == py
    row = sql["items"][0]
    assert sum(row["band_value_paise"].values()) == 1 == row["value_paise"]


def test_two_receipts_in_one_second_order_the_same_on_both_halves(db):
    """Same date, same created_at: only the id breaks the tie. Without a third
    sort key the two halves pick different layers as oldest, which is the one
    thing this report exists to say."""
    sql, py = _both(db, SAME_DATE_SAME_SECOND, "2026-09-18", item=ITEMS["widget"])
    assert sql == py
    row = sql["items"][0]
    assert _q(row["qty_units"]) == "5"
    # 15 out of 20 consumes the first row whole and half the second, so the
    # value that survives is a quarter of the pair — which is only stable if
    # both halves agreed which row was first.
    assert sum(row["band_value_paise"].values()) == row["value_paise"]


def test_nothing_on_hand_is_flagged_rather_than_shown_as_empty_bands(db):
    """Six zeroes beside a negative quantity read as 'no old stock here', which
    is the opposite of what an oversold item is telling the CA."""
    sql, py = _both(db, OVERSOLD, "2026-04-30", item=ITEMS["bracket"])
    assert sql == py
    row = sql["items"][0]
    assert _q(row["qty_units"]) == "-3"
    assert row["nothing_on_hand"] is True
    assert all(Decimal(v) == 0 for v in row["band_qty"].values())
    assert row["oldest_holding_date"] is None


def test_an_item_that_netted_to_nil_is_still_reported(db):
    """Migration 363's rule: dropping nil lines is a display choice, and a
    report that silently omits rows cannot be tied to a control account by
    somebody who does not know which rows it dropped."""
    sql, py = _both(db, EXACTLY_NIL, "2026-04-30", item=ITEMS["sprocket"])
    assert sql == py
    assert len(sql["items"]) == 1
    assert sql["items"][0]["nothing_on_hand"] is True


def test_another_firms_and_another_clients_rows_are_not_in_the_answer(db):
    sql, py = _both(db, FOREIGN, "2026-09-18")
    assert sql == py
    assert Decimal(sql["total_qty_by_band"]["d91_180"]) == 0, (
        "the other client's 999 units must not appear under any band")


def test_the_python_half_never_reads_the_costing_policy():
    """AGEING IS FIFO WHATEVER THE CLIENT'S COST FORMULA IS, and the two must
    not learn about each other: a batch or a policy leaking into costing would
    make specific identification (AS-2 paragraph 13) a third cost formula by
    accident, and a cost formula leaking into ageing would make the report
    answer a different question per client."""
    import ast
    import inspect

    from domain.inventory import costing

    # THE CODE, NOT THE PROSE. Both modules EXPLAIN the separation at length in
    # their docstrings, so a plain substring scan fails on the sentence that
    # states the very rule it is checking. That is the seventh time in this
    # codebase a guard has matched a spelling and tripped on writing that
    # obeys it; strip the docstrings and assert the rule.
    def _code_only(mod) -> str:
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    node.body = body[1:] or [ast.Pass()]
        return ast.unparse(tree)

    ageing_code = _code_only(stock_ageing)
    for forbidden in ("inventory_costing_method", "CostingPolicy", "costing."):
        assert forbidden not in ageing_code, (
            f"stock_ageing READS {forbidden}: ageing is a physical question "
            f"about the godown, not a cost assignment")
    costing_code = _code_only(costing)
    assert "stock_ageing" not in costing_code
    assert "d365_plus" not in costing_code
    # And the scan is not vacuous: the module does have a body to look at.
    assert len(ageing_code) > 2000 and len(costing_code) > 2000

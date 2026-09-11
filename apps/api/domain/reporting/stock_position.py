"""
Closing stock as at a date, and a movement ledger whose balance column foots.

WHAT THIS IS
    Two answers built from one rule. "What did this client hold on 31 March and
    what was it worth" is the stock statement that ties to the Inventories line
    on the balance sheet and is the quantitative-details working paper a §44AB
    audit expects. "What does this item's movement history look like between
    two dates" is the drill-down behind it. They are the same arithmetic read
    two ways, so they are one module and cannot disagree.

WHY IT SUMS THE DELTAS AND NEVER READS THE RUNNING COLUMNS
    `inventory_stock_ledger` carries both a per-movement delta and a stored
    running total, and only the delta can answer a question about a DATE.

    The running totals are chained in INSERTION order. `_last_ledger_row` in
    domain/inventory_service.py orders by `created_at` and explains why at
    length: a bill dated 1 July received on 15 July, after a 10 July sale was
    already recorded, must not fall out of the chain. That is correct for a
    perpetual system, and it means the stored running total on a row is the
    position as at the moment that row was RECORDED — not as at its
    movement_date. Reading it off the last row on or before a date answers a
    question nobody asked.

    Addition commutes, so the deltas have no such problem. Σ quantity_delta and
    Σ value_delta_paise over `movement_date <= D` are the same numbers whatever
    order the rows went in.

    They are also the RIGHT numbers, and not by coincidence:
    `post_cogs_journal_entry` and `post_inventory_journal_entry` post exactly
    `value_delta_paise`, dated exactly `movement_date`. So Σ value_delta_paise
    to D IS the movement on the Inventory control account to D. The statement
    and the balance sheet tie by construction.

WHY THE DRILL-DOWN'S BALANCE COLUMN DID NOT FOOT
    `get_stock_ledger` returns rows ordered by (movement_date, created_at) and
    the screen rendered the STORED running columns beside them. With a document
    entered late those two orders disagree, so the column showed +20 against a
    balance of 110 sitting above −10 against a balance of 90: neither row adds
    up, and a CA reconciling stock cannot tell why. Migration 250 had already
    found the stored totals drifted on 303 of 315 items in production and
    rebuilt them in DISPLAY order, which is not the order new movements chain
    in — so the two have been disagreeing about the current position as well.

    The fix is not to change the chain. The chain is load-bearing: the
    service_catalogue cache and every future movement's cost come off it. The
    fix is that a BALANCE COLUMN IS A PROPERTY OF THE ORDER IT IS SHOWN IN, so
    it is derived at display time from the deltas, in the order displayed, from
    an opening balance as at the day before the range. Then every row foots,
    the closing figure equals the as-at-date position, and over an item's whole
    history it equals the stored running total too — because `_compute_stock_out`
    force-closes on the last unit and says "the deltas always sum to the running
    value".

WHY THIS FILE EXISTS BESIDE THE SQL
    public.stock_position_as_at (migration 363) is what production runs: the
    answer is one row per item and the input is every movement for years, so
    CLAUDE.md's reporting rule puts the aggregation in the database. This is the
    identical rule for everything with no DATABASE_URL — mock mode, local dev,
    the in-memory suite — and tests/test_stock_position_parity_pg.py runs every
    scenario through both and asserts the documents are equal.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional


def _as_int(v) -> int:
    """PostgREST hands a bigint back as a string. Never float: a rupee figure
    that has been through a float is a rupee figure nobody can reconcile."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    return int(Decimal(str(v)))


def _as_qty(v) -> Decimal:
    """NUMERIC(10,3) on the line tables. Decimal, for the same reason."""
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _round_paise(v: Decimal) -> int:
    """Half-up, matching domain/inventory_service._round_paise and SQL's
    round(numeric), so the average cost is the same integer on both paths."""
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _avg_cost_paise(qty: Decimal, value_paise: int) -> int:
    """Derived at the end, never accumulated — an average of averages is not an
    average. A nil or negative quantity has no meaningful unit cost, and one
    computed by dividing by a negative would put a negative cost on the working
    paper, so it is reported as zero rather than invented."""
    if qty <= 0:
        return 0
    return _round_paise(Decimal(value_paise) / qty)


def position(movements: Iterable[dict], as_of: str,
             names: Optional[dict] = None) -> dict:
    """Closing stock per item as at `as_of`, in the shape
    public.stock_position_as_at returns.

    `movements` is every `inventory_stock_ledger` row for the client — this
    function filters by date itself so the caller cannot filter it a second,
    different way. `names` maps service_catalogue_id to its catalogue row.
    """
    names = names or {}
    by_item: dict[str, dict] = {}

    for m in movements:
        when = str(m.get("movement_date") or "")[:10]
        if not when or when > as_of:
            continue
        item_id = m.get("service_catalogue_id")
        if not item_id:
            continue
        acc = by_item.setdefault(str(item_id), {
            "qty": Decimal("0"), "value_paise": 0,
            "last_movement_date": None, "movements": 0,
        })
        acc["qty"] += _as_qty(m.get("quantity_delta"))
        acc["value_paise"] += _as_int(m.get("value_delta_paise"))
        acc["movements"] += 1
        if acc["last_movement_date"] is None or when > acc["last_movement_date"]:
            acc["last_movement_date"] = when

    items = []
    for item_id, acc in by_item.items():
        cat = names.get(item_id) or {}
        items.append({
            "service_catalogue_id": item_id,
            # A movement can outlive its catalogue row (ON DELETE CASCADE means
            # it cannot, today — but the SQL LEFT JOINs and so does this, so the
            # two agree if that ever changes).
            "name": cat.get("name") or "(deleted item)",
            "unit": cat.get("unit"),
            "hsn_sac": cat.get("hsn_sac"),
            "qty_units": str(acc["qty"]),
            "value_paise": acc["value_paise"],
            "avg_cost_paise": _avg_cost_paise(acc["qty"], acc["value_paise"]),
            "last_movement_date": acc["last_movement_date"],
            "movements": acc["movements"],
        })

    items.sort(key=lambda r: (r["name"] or "", r["service_catalogue_id"]))
    return {
        "as_of": as_of,
        "items": items,
        # Summed from the deltas, not from the rounded per-item averages:
        # qty * avg_cost re-rounds an already-rounded average and drifts a few
        # paise per item, which across a register no longer ties to the
        # Inventory control account.
        "total_value_paise": sum(r["value_paise"] for r in items),
        "total_items": len(items),
    }


def ledger_with_balances(rows: Iterable[dict], opening_qty: Decimal,
                         opening_value_paise: int) -> list[dict]:
    """Adds `balance_qty_units` and `balance_value_paise` to each row, running
    forward from the opening figure IN THE ORDER GIVEN.

    New keys rather than overwriting `running_qty_units` / `running_value_paise`:
    those columns hold the perpetual chain, every future movement's cost comes
    off them, and a response that relabelled them would be telling the screen
    something the database does not hold.
    """
    qty = Decimal(opening_qty)
    value = int(opening_value_paise)
    out = []
    for r in rows:
        qty += _as_qty(r.get("quantity_delta"))
        value += _as_int(r.get("value_delta_paise"))
        line = dict(r)
        line["balance_qty_units"] = str(qty)
        line["balance_value_paise"] = value
        out.append(line)
    return out

"""Each stock item's latest stock-ledger row: the running totals the register shows and the next movement chains from (POST-A-435).

WHY THIS MODULE
    `public.stock_latest_rows` (migration 588) answers this where the rows are, one probe per item. This is its mock-mode twin, held
    identical to it by `tests/test_stock_latest_rows_parity_pg.py`, and the one place that says which row is "latest":

    * newest `created_at` first, because the running totals are chained in the order rows were RECORDED (`_last_ledger_row` explains
      why that and not `movement_date`);
    * then the larger `id`, so two rows recorded in one instant resolve the same way every time, in the database and here, and the
      register shows the row the next movement will cost from;
    * only the items asked for, of this firm and this client; an item with no row is absent (it has received nothing), never a zero
      row invented for it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

COLUMNS = ("service_catalogue_id", "running_qty_units", "running_avg_cost_paise", "running_value_paise")


def latest_rows(rows: Iterable[dict], firm_id: str, client_id: str, items: Iterable[str]) -> dict[str, dict]:
    """{item id: its latest row, cut to COLUMNS} for the asked items that have a row of this firm and client."""
    wanted = {str(i) for i in items}
    best: dict[str, dict] = {}
    for r in rows:
        item = str(r.get("service_catalogue_id"))
        if item not in wanted or str(r.get("firm_id")) != str(firm_id) or str(r.get("client_id")) != str(client_id):
            continue
        held = best.get(item)
        if held is None or _order(r) > _order(held):
            best[item] = r
    return {item: {c: r.get(c) for c in COLUMNS} for item, r in best.items()}


_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def _order(row: dict) -> tuple[datetime, str]:
    """(recorded at, id), compared as an instant and not as text, so two offsets naming one moment are one moment, as in the database."""
    raw = row.get("created_at")
    try:
        at = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        at = _EARLIEST
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc), str(row.get("id") or ""))

"""
Fetches what `domain/inventory/reorder` decides. It decides nothing itself.

NO SQL FUNCTION, AND THAT IS THE REPORTING RULE OBEYED RATHER THAN DODGED.
CLAUDE.md forbids a report whose read is proportional to TRANSACTION volume.
This one's read is proportional to the number of ITEMS, which is the size of
the answer — one row per good — and the on-hand figure comes from
`stock_position_service.position`, which is already the SQL aggregate
`stock_position_as_at` in production. So the expensive half is aggregated
server-side and the cheap half is a catalogue scan that cannot grow with the
ledger.

THE ON-HAND FIGURE IS THE LEDGER'S AND NOT `service_catalogue.stock_qty_units`.
Migration 188 documents that column as a cached running total whose
authoritative source is `inventory_stock_ledger`, and a purchasing prompt
computed off a drifted cache is wrong in the direction that costs money: it
says there is stock there is not.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.db_paging import fetch_all
from domain.inventory import reorder

_logger = logging.getLogger("caflow.reorder")


def _catalogue(db, firm_id: str, client_id: str) -> list:
    # The projection is written out here rather than reached through a name:
    # test_backend_columns_exist_pg.py parses every select list as a STRING and
    # a constant it has to resolve counts against the unreadable budget with
    # its columns unchecked.
    # `fetch_all` takes a CALLABLE returning a FRESH builder, and a builder
    # handed in directly raises `TypeError: '_Query' object is not callable` on
    # the first page. That is what this was, so `assess` could not run at all
    # against a real database — `routers/inventory.reorder_report` caught it
    # and answered "Unable to load the reorder report", and the whole feature
    # was dead from the day it shipped. The mock suite could not see it: the
    # router's `_USE_MOCK` branch passes `db=None`, which short-circuits to an
    # empty answer before this function is reached.
    def one_page():
        return (
            db.table("service_catalogue")
            .select("id, name, unit, kind, category, is_active, reorder_level_units, "
                    "alternate_unit, units_per_alternate")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")
        )

    return fetch_all(one_page, label="reorder:service_catalogue")


def _positions(db, firm_id: str, client_id: str, as_of: Optional[str]) -> dict:
    from services import stock_position_service
    pos = stock_position_service.position(db, firm_id, client_id, as_of)
    out = {}
    for item in (pos or {}).get("items") or []:
        # `service_catalogue_id` / `qty_units` are the SQL function's own keys
        # (migration 363) and the Python twin's. Read, never defaulted: a
        # rename would silently read every item as nil on hand and prompt the
        # CA to reorder the whole register, so a test pins both spellings.
        key = str(item.get("service_catalogue_id") or "")
        if key:
            out[key] = item.get("qty_units", 0)
    return out


def _serialise(answer: dict) -> dict:
    return {
        "groups": [
            {
                "group": g.group,
                "below_count": g.below_count,
                "not_set_count": g.not_set_count,
                "lines": [
                    {
                        "service_catalogue_id": ln.item_id,
                        "name": ln.name,
                        "unit": ln.unit,
                        "group": ln.group,
                        "on_hand_units": str(ln.on_hand_units),
                        "reorder_level_units": (
                            None if ln.reorder_level_units is None
                            else str(ln.reorder_level_units)),
                        "state": ln.state,
                        "shortfall_units": str(ln.shortfall_units),
                        "note": ln.note,
                    }
                    for ln in g.lines
                ],
            }
            for g in answer["groups"]
        ],
        "to_reorder": answer["to_reorder"],
        "no_level_recorded": answer["no_level_recorded"],
        "items_considered": answer["items_considered"],
        "note_when_no_level": answer["note_when_no_level"],
    }


def assess(db, firm_id: str, client_id: str, as_of: Optional[str] = None) -> dict:
    """What is at or below its reorder level, grouped by item group."""
    if db is None:
        return _serialise(reorder.assess([], {}))
    items = _catalogue(db, firm_id, client_id)
    return _serialise(reorder.assess(items, _positions(db, firm_id, client_id, as_of)))


def item_groups(db, firm_id: str, client_id: str) -> list:
    """The distinct item groups this client already uses, most-used first.

    Served so the picker offers what EXISTS rather than a free text box: two
    spellings of one group are two groups in every report, and `category` has
    been free text with no picker since migration 180. It is a suggestion and
    never a constraint — a CA typing a new group is how the first one gets
    created.
    """
    if db is None:
        return []
    counts: dict = {}
    labels: dict = {}
    for row in _catalogue(db, firm_id, client_id):
        label = (row.get("category") or "").strip()
        if not label:
            continue
        key = " ".join(label.split()).lower()
        labels.setdefault(key, label)
        counts[key] = counts.get(key, 0) + 1
    return [{"group": labels[k], "items": c}
            for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

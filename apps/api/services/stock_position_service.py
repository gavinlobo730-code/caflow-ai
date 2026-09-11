"""
Closing stock as at a date, and the drill-down that foots (INV-01).

Two paths, one rule. public.stock_position_as_at (migration 363) is what
production runs — the answer is one row per item and the input is every
movement for years, so CLAUDE.md's reporting rule puts the aggregation in the
database. domain/reporting/stock_position.py is the identical rule for
everything with no DATABASE_URL, and tests/test_stock_position_parity_pg.py
holds the two identical.

The fallback is deliberate and not free: it reads the client's whole movement
history into Python, which is exactly what the rule forbids in production. It
exists because mock mode and local dev have no SQL functions at all, it logs
loudly when it is reached, and it is the reason the parity test exists.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import ist_today
from domain.reporting import stock_position

_logger = logging.getLogger("caflow.stock_position")

# Column lists are written out AT THE CALL rather than held in a constant.
# test_backend_columns_exist_pg.py parses every select list and checks it
# against the real schema, and it can only read a literal — a name it has to
# resolve counts against the "unreadable" budget instead, columns unchecked.
# Of all the selects to leave unchecked, one feeding a stock statement that
# ties to the balance sheet is a poor candidate.

_PAGE = 1000


def _as_of(as_of: Optional[str]) -> str:
    """Today in IST when unasked. A stock statement dated by the server's UTC
    clock is dated yesterday for five and a half hours every night, which is
    the difference between including and excluding a 31 March movement."""
    if not as_of:
        return ist_today().isoformat()
    text = str(as_of)[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"as_of must be YYYY-MM-DD, got {as_of!r}")
    return text


def _fetch_movements(db, firm_id: str, client_id: str, as_of: str,
                     item_id: Optional[str] = None) -> list[dict]:
    """Every movement up to the date. OFFSET-paged for the same reason
    get_stock_ledger is: an un-paged PostgREST read silently caps at ~1000
    rows, and a truncated stock statement is a wrong stock statement that
    looks right."""
    def q():
        base = (db.table("inventory_stock_ledger").select("service_catalogue_id, movement_date, quantity_delta, value_delta_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .lte("movement_date", as_of))
        if item_id:
            base = base.eq("service_catalogue_id", item_id)
        return base.order("movement_date").order("created_at")

    if not hasattr(q(), "range"):
        return q().execute().data or []
    out: list[dict] = []
    offset = 0
    while True:
        rows = q().range(offset, offset + _PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        offset += _PAGE
    return out


def _fetch_catalogue(db, firm_id: str, client_id: str) -> dict[str, dict]:
    rows = (db.table("service_catalogue").select("id, name, unit, hsn_sac, kind, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("kind", "good").execute().data) or []
    return {str(r["id"]): r for r in rows}


def position(db, firm_id: str, client_id: str, as_of: Optional[str] = None,
             item_id: Optional[str] = None) -> dict:
    """Closing stock per item as at a date. Tries the SQL aggregate first."""
    if not client_id:
        raise HTTPException(status_code=422,
                            detail="client_id is required — stock is client-owned")
    at = _as_of(as_of)

    if db is None:
        # No database at all — mock mode. An empty register in the right shape,
        # never a fabricated one.
        return {"as_of": at, "items": [], "total_value_paise": 0, "total_items": 0}

    if hasattr(db, "rpc"):
        try:
            res = db.rpc("stock_position_as_at", {
                "p_firm": firm_id, "p_client": client_id,
                "p_as_of": at, "p_item": item_id,
            }).execute()
            out = getattr(res, "data", None)
            if isinstance(out, dict) and "items" in out:
                return out
            raise ValueError(
                f"stock_position_as_at returned {type(out).__name__}, not a position")
        except Exception as e:                              # noqa: BLE001
            _logger.error("stock_position_as_at failed (%s %s %s) — falling back "
                          "to the Python rule: %s", firm_id, client_id, at, e)

    return stock_position.position(
        _fetch_movements(db, firm_id, client_id, at, item_id),
        at,
        _fetch_catalogue(db, firm_id, client_id),
    )


def opening_for_item(db, firm_id: str, client_id: str, item_id: str,
                     before: Optional[str]) -> tuple[Decimal, int]:
    """The item's quantity and value as at the day BEFORE `before`, which is
    what the drill-down's balance column runs forward from.

    No `before` means no opening: the range starts at the beginning of the
    item's history, so the opening is nil rather than the whole position.
    """
    if not before:
        return Decimal("0"), 0
    day = str(before)[:10]
    try:
        prior = (date.fromisoformat(day).toordinal() - 1)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"start_date must be YYYY-MM-DD, got {before!r}")
    at = date.fromordinal(prior).isoformat()

    out = position(db, firm_id, client_id, at, item_id)
    for row in out.get("items") or []:
        if str(row.get("service_catalogue_id")) == str(item_id):
            return (Decimal(str(row.get("qty_units") or "0")),
                    int(row.get("value_paise") or 0))
    return Decimal("0"), 0

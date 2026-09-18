"""
How long has the stock ON HAND been held (INV-04).

Two paths, one rule, and it is `stock_position_service`'s arrangement exactly.
`public.stock_ageing_as_at` (migration 408) is what production runs — the
answer is one row per item and the input is every movement for years, so
CLAUDE.md's reporting rule puts the aggregation in the database.
`domain/reporting/stock_ageing.py` is the identical rule for everything with no
DATABASE_URL, and `tests/test_stock_ageing_parity_pg.py` holds the two
identical.

The fallback is deliberate and not free: it reads the client's whole movement
history into Python, which is exactly what the rule forbids in production. It
exists because mock mode and local dev have no SQL functions at all, it logs
loudly when it is reached, and it is the reason the parity test exists.

THE PROSE IS ATTACHED HERE AND NOT EMITTED BY EITHER HALF. The bands' LABELS
and the four caveats are one vocabulary and `domain/reporting/stock_ageing.py`
owns it; a SQL function emitting English would be a second copy of it, which is
the Schedule III caption lesson. So whichever half produced the FIGURES, the
words come from the same place — and the parity test can compare the numbers
without tripping on prose only one side carries.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import ist_today
from domain.reporting import stock_ageing

_logger = logging.getLogger("caflow.stock_ageing")

# Column lists are written out AT THE CALL rather than held in a constant.
# test_backend_columns_exist_pg.py parses every select list against the real
# schema and can only read a literal; a name it has to resolve counts against
# the "unreadable" budget instead, columns unchecked.

_PAGE = 1000


def _as_of(as_of: Optional[str]) -> str:
    """Today in IST when unasked, `stock_position_service._as_of`'s reason: a
    report dated by the server's UTC clock is dated yesterday for five and a
    half hours every night, which is the difference between including and
    excluding a 31 March movement."""
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
    """Every movement up to the date.

    `id` and `created_at` are in the projection because they are the SECOND and
    THIRD FIFO sort keys. They make the layer walk DETERMINISTIC rather than
    change any figure — two receipts sharing a movement_date share a band by
    construction, so which of them is consumed first cannot move a number — and
    they keep the SQL twin, which breaks the same tie on `id`, walking the same
    layers.

    OFFSET-paged for `get_stock_ledger`'s reason: an un-paged PostgREST read
    silently caps at ~1000 rows, and a truncated ageing report is a wrong
    ageing report that looks right.
    """
    def q():
        base = (db.table("inventory_stock_ledger").select("id, service_catalogue_id, movement_date, created_at, quantity_delta, value_delta_paise")
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


def _with_words(out: dict) -> dict:
    """The band labels and the four caveats, from the one vocabulary."""
    out = dict(out)
    out["band_labels"] = dict(stock_ageing.BAND_LABELS)
    out["notes"] = [
        stock_ageing.BANDS_ARE_A_CONVENTION,
        stock_ageing.AGEING_IS_FIFO_WHATEVER_THE_POLICY,
        stock_ageing.VALUE_IS_PRO_RATED,
        stock_ageing.NO_PROVISION_IS_COMPUTED,
    ]
    return out


def ageing(db, firm_id: str, client_id: str, as_of: Optional[str] = None,
           item_id: Optional[str] = None) -> dict:
    """Stock ageing per item as at a date. Tries the SQL aggregate first."""
    if not client_id:
        raise HTTPException(status_code=422,
                            detail="client_id is required — stock is client-owned")
    at = _as_of(as_of)

    if db is None:
        # No database at all — mock mode. An empty register in the right shape,
        # never a fabricated one.
        return _with_words({
            "as_of": at, "bands": list(stock_ageing.BAND_KEYS), "items": [],
            "total_qty_by_band": {k: "0" for k in stock_ageing.BAND_KEYS},
            "total_value_by_band": {k: 0 for k in stock_ageing.BAND_KEYS},
            "total_value_paise": 0, "total_items": 0,
        })

    if hasattr(db, "rpc"):
        try:
            res = db.rpc("stock_ageing_as_at", {
                "p_firm": firm_id, "p_client": client_id,
                "p_as_of": at, "p_item": item_id,
            }).execute()
            out = getattr(res, "data", None)
            if isinstance(out, dict) and "items" in out:
                return _with_words(out)
            raise ValueError(
                f"stock_ageing_as_at returned {type(out).__name__}, not an ageing")
        except Exception as e:                              # noqa: BLE001
            _logger.error("stock_ageing_as_at failed (%s %s %s) — falling back "
                          "to the Python rule: %s", firm_id, client_id, at, e)

    return _with_words(stock_ageing.ageing(
        _fetch_movements(db, firm_id, client_id, at, item_id),
        at,
        _fetch_catalogue(db, firm_id, client_id),
    ))

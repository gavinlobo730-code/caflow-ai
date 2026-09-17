"""
The client's CGST s.2(6) aggregate turnover, per financial year (GST-17).

WHY THIS EXISTS
    Notification 78/2020-Central Tax sets the minimum HSN digits on GSTR-1
    Table 12 from the taxpayer's aggregate turnover in the PRECEDING financial
    year. Nothing held that figure, so every build sent `0` — a real turnover
    meaning "below every threshold" — and every client was silently told HSN
    was optional. `public.client_gst_turnover` (migration 401) holds it and
    this reads and writes it.

WHAT IT REFUSES TO DO
    It never DERIVES the figure. CGST s.2(6) aggregate turnover is computed on
    the PAN, ALL-INDIA, and includes exempt supplies, exports and inter-State
    supplies between distinct persons — a second registration's supplies count
    toward it, and this product holds one client's books. Summing this client's
    outward supplies would produce a smaller number that looks authoritative,
    which is the failure mode the whole finding is about.

    An absent row therefore answers `None`, never 0. The two are different
    facts: 0 is a client who turned over nothing, None is nobody having said.
"""
from __future__ import annotations

from typing import Optional

from core.ist_clock import normalise_fy_label
from domain.gst import hsn_digits

TABLE = "client_gst_turnover"


def _rows(db, firm_id: str, client_id: str, financial_year: Optional[str] = None):
    q = (db.table(TABLE)
         .select("id, firm_id, client_id, financial_year, "
                 "aggregate_turnover_paise, source_note, recorded_by, updated_at")
         # firm_id explicitly, not RLS alone — the service-role key bypasses
         # RLS and the app-layer filter is the primary isolation control.
         .eq("firm_id", firm_id)
         .eq("client_id", client_id))
    if financial_year:
        q = q.eq("financial_year", financial_year)
    return q.order("financial_year", desc=True).execute().data or []


def list_for_client(db, firm_id: str, client_id: str) -> list[dict]:
    """Every year recorded for this client, newest first."""
    return _rows(db, firm_id, client_id)


def turnover_for_fy(db, firm_id: str, client_id: str,
                    financial_year: str) -> Optional[int]:
    """The recorded aggregate turnover for one financial year, or None.

    None means NO ROW — nobody has recorded one. It is never 0, because a
    client who genuinely turned over nothing is a different answer and the
    caller has to be able to tell them apart.
    """
    rows = _rows(db, firm_id, client_id, normalise_fy_label(financial_year))
    if not rows:
        return None
    return int(rows[0].get("aggregate_turnover_paise") or 0)


def turnover_governing_period(db, firm_id: str, client_id: str,
                              period_start: str) -> Optional[int]:
    """The figure that governs a return for this period — the PRECEDING year's.

    The hop is `hsn_digits.governing_financial_year`, so the rule about which
    year applies lives with the rule that reads it and not in each caller.
    """
    fy = hsn_digits.governing_financial_year(period_start)
    return turnover_for_fy(db, firm_id, client_id, fy)


def record(db, firm_id: str, client_id: str, financial_year: str,
           aggregate_turnover_paise: int, *, source_note: Optional[str] = None,
           recorded_by: Optional[str] = None) -> dict:
    """Record or replace one year's figure.

    UPSERT on (client_id, financial_year), which is migration 401's unique key:
    a CA correcting last year's figure is correcting it, not adding a second
    one, and two rows for one year would make `turnover_for_fy` depend on
    insertion order.
    """
    fy = normalise_fy_label(financial_year)
    if aggregate_turnover_paise < 0:
        raise ValueError("aggregate turnover cannot be negative")
    existing = _rows(db, firm_id, client_id, fy)
    payload = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": fy,
        "aggregate_turnover_paise": int(aggregate_turnover_paise),
        "source_note": source_note,
        "recorded_by": recorded_by,
    }
    if existing:
        res = (db.table(TABLE).update(
            {k: v for k, v in payload.items()
             if k not in ("firm_id", "client_id", "financial_year")})
            .eq("id", existing[0]["id"]).eq("firm_id", firm_id).execute())
        return (res.data or [payload])[0]
    res = db.table(TABLE).insert(payload).execute()
    return (res.data or [payload])[0]

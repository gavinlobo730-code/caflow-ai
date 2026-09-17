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
from domain.gst import hsn_digits, irn_scope

#: The table, for a caller that wants to name it. Every query below writes the
#: name out as a LITERAL instead of reaching through this: a dynamic table name
#: makes every filter and every projection on that chain invisible to
#: `tests/test_backend_columns_exist_pg.py`, which checks them against the real
#: schema as strings — and on a brand-new table a typo has nothing else to
#: catch it. Same reason `routers/firms.py` stopped joining `COLUMNS`.
TABLE = "client_gst_turnover"


# The two reads below are TWO COMPLETE CHAINS rather than one built up through
# a local `q` with an `if`, and the repetition is the point: a filter applied to
# a variable is attributed to no table, so the whole chain goes unread by the
# schema check above. Two literals cost one duplicated projection and keep both
# reads verified — `routers/firms.py` made the same trade.
def list_for_client(db, firm_id: str, client_id: str) -> list[dict]:
    """Every year recorded for this client, newest first."""
    return (db.table("client_gst_turnover")
            .select("id, firm_id, client_id, financial_year, "
                    "aggregate_turnover_paise, source_note, recorded_by, updated_at")
            # firm_id explicitly, not RLS alone — the service-role key bypasses
            # RLS and the app-layer filter is the primary isolation control.
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .order("financial_year", desc=True)
            .execute().data or [])


def _rows_for_fy(db, firm_id: str, client_id: str, financial_year: str) -> list[dict]:
    return (db.table("client_gst_turnover")
            .select("id, firm_id, client_id, financial_year, "
                    "aggregate_turnover_paise, source_note, recorded_by, updated_at")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("financial_year", financial_year)
            .order("financial_year", desc=True)
            .execute().data or [])


def turnover_for_fy(db, firm_id: str, client_id: str,
                    financial_year: str) -> Optional[int]:
    """The recorded aggregate turnover for one financial year, or None.

    None means NO ROW — nobody has recorded one. It is never 0, because a
    client who genuinely turned over nothing is a different answer and the
    caller has to be able to tell them apart.
    """
    rows = _rows_for_fy(db, firm_id, client_id, normalise_fy_label(financial_year))
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


def highest_turnover_within_rule_48_4(db, firm_id: str, client_id: str,
                                      invoice_date: str) -> Optional[int]:
    """The highest aggregate turnover that can bring this client within Rule 48(4).

    THIS IS NOT `turnover_governing_period` AND THE DIFFERENCE IS THE WHOLE
    POINT. Notification 78/2020 (the HSN digit rule above) reads on the
    turnover "in the PRECEDING Financial Year" — one year, and a client who
    shrinks falls back down a band. CGST Rule 48(4) reads on the turnover "in
    ANY PRECEDING FINANCIAL YEAR FROM 2017-18 ONWARDS", so e-invoicing LATCHES:
    a client who crossed ₹20 crore in FY 2022-23 and has turned over ₹4 crore
    every year since is still within it. Reusing the preceding-year hop here
    would let them out, and Rule 48(5) makes the invoice they then issue
    without an IRN not an invoice at all.

    So this takes the MAXIMUM across every qualifying year, not the latest.
    `domain.gst.irn_scope` owns which years those are; this only fetches them.

    None means NO ROW IN ANY of those years — nobody has recorded a figure. It
    is never 0, for `turnover_for_fy`'s reason: 0 is a client who turned over
    nothing and None is nobody having said, and `irn_scope.assess` resolves the
    two differently.
    """
    years = irn_scope.qualifying_financial_years(invoice_date)
    if not years:
        # An invoice inside FY 2017-18 itself has no PRECEDING year the rule
        # can reach, so there is nothing to fetch and `.in_` on an empty list
        # is a query with no meaning rather than a query with no rows.
        return None
    rows = (db.table("client_gst_turnover")
            .select("id, firm_id, client_id, financial_year, "
                    "aggregate_turnover_paise, source_note, recorded_by, updated_at")
            # firm_id explicitly, not RLS alone — the service-role key bypasses
            # RLS and the app-layer filter is the primary isolation control.
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            # `.in_` over the named years rather than a gte/lte range: the
            # column is TEXT, so '2019-20' > '2017-18' happens to sort right
            # only because every label is the same width and starts with the
            # year — a range would still be an ordering this rule never asked
            # for. The same reasoning `gstr9_builder` records for MMYYYY.
            .in_("financial_year", years)
            .order("financial_year", desc=True)
            .execute().data or [])
    if not rows:
        return None
    return max(int(r.get("aggregate_turnover_paise") or 0) for r in rows)


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
    existing = _rows_for_fy(db, firm_id, client_id, fy)
    # Both payloads are written INLINE rather than built above and passed by
    # name. A dict reached through a variable names no columns the schema check
    # can read, and on a table this new a typo has nothing else to catch it —
    # the same trade `services/purchase_cycle_service` and `routers/firms.py`
    # made. The update omits the three the row is KEYED on: it was found by
    # them, so re-sending them could only ever move a row to another year.
    if existing:
        res = (db.table("client_gst_turnover").update({
            "aggregate_turnover_paise": int(aggregate_turnover_paise),
            "source_note": source_note,
            "recorded_by": recorded_by,
        }).eq("id", existing[0]["id"]).eq("firm_id", firm_id).execute())
    else:
        res = db.table("client_gst_turnover").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": fy,
            "aggregate_turnover_paise": int(aggregate_turnover_paise),
            "source_note": source_note,
            "recorded_by": recorded_by,
        }).execute()
    if res.data:
        return res.data[0]
    # A driver that returns no representation: re-read rather than echo a dict
    # assembled here, which would be a third copy of the column list and the
    # one nobody checks.
    rows = _rows_for_fy(db, firm_id, client_id, fy)
    return rows[0] if rows else {}

"""
The real date span of a client's posted ledger.

WHY THIS EXISTS
    "All Time" on the reporting screens resolved to a placeholder span of
    1900-01-01 → 2999-12-31, because the browser has no way to know when a
    client's books actually start. That made "Display columns by: Quarterly"
    a silent no-op on All Time: splitting eleven centuries into quarters is
    ~4,400 columns, so the frontend collapsed any very wide range back to a
    single Total column — correctly, but without saying so. The control stayed
    enabled and appeared broken.

    Given the true first and last posted entry dates, All Time becomes a real
    range and the split works: two years of books is eight quarterly columns,
    which is the view a CA actually wants for spotting a seasonal trend.

COST
    Two indexed single-row lookups (ORDER BY entry_date LIMIT 1, each
    direction) rather than an aggregate over the whole table. Deliberately not
    min()/max() through PostgREST: this reuses the same
    (firm_id, client_id, is_posted) index path the reporting queries already
    rely on, and returns two rows instead of scanning.

WHAT COUNTS
    Posted, non-deleted entries only — the same filter the Trial Balance, P&L
    and Balance Sheet use (domain/reporting/sources.py). A draft or reversed-out
    entry must not stretch the reporting window past where the numbers actually
    start, or the first column of every report would be empty.
"""
from typing import Any, Optional


def _edge(db, firm_id: str, client_ids: Optional[list[str]], *, newest: bool) -> Optional[str]:
    """The oldest (or newest) posted entry_date, or None when there are none."""
    q = (db.table("journal_entries").select("entry_date")
         .eq("firm_id", firm_id)
         .eq("is_posted", True)
         .is_("deleted_at", "null"))
    if client_ids is not None:
        q = q.in_("client_id", client_ids)
    rows = q.order("entry_date", desc=newest).limit(1).execute().data or []
    return (rows[0].get("entry_date") or None) if rows else None


def ledger_span(db, firm_id: str,
                client_ids: Optional[list[str]] = None) -> dict[str, Any]:
    """{"first_entry_date", "last_entry_date"} — both None for an empty ledger.

    `client_ids` None means every client in the firm; the caller narrows it to
    the caller's assigned clients first. An EMPTY list means "scoped to no
    clients", which can only ever produce an empty span, so it short-circuits
    before touching the database — and avoids `.in_("client_id", [])`, whose
    behaviour is not something to depend on when the wrong answer is "the whole
    firm".
    """
    if client_ids is not None and not client_ids:
        return {"first_entry_date": None, "last_entry_date": None}

    first = _edge(db, firm_id, client_ids, newest=False)
    last = _edge(db, firm_id, client_ids, newest=True)

    # A one-sided span is not a range anything can be split by. Rather than let
    # a half-answer reach the UI (where it would silently become "today"), treat
    # it as no span at all — the caller falls back to the financial year.
    if not first or not last:
        return {"first_entry_date": None, "last_entry_date": None}
    return {"first_entry_date": first[:10], "last_entry_date": last[:10]}

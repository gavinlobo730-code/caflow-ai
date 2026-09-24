"""What each hub tile's number actually is — the fetch, and nothing it decides.

`domain/hub/tiles.py` is the authority for what a tile ASKS. This module is the
only place that knows which table answers it. The split is the ordinary one in
this codebase, and here it earns its keep twice: the questions were reviewable
before any query existed, and the two scopes (firm hub, client hub) ask the
same fifteen questions through one code path.

── ONE ENDPOINT, NOT FIFTEEN ────────────────────────────────────────────────

`apps/api` runs in Singapore and Postgres is in Mumbai, so fifteen browser
fetches would be fifteen cross-region round trips for a screen that shows
fifteen numbers. The hub is one request. CLAUDE.md's reporting rule states the
other half: what crosses the wire is proportional to the ANSWER, so every query
below is a COUNT or a bounded aggregate and none of them returns rows.

── A TILE THAT FAILS DOES NOT FAIL THE HUB ──────────────────────────────────

Each signal is computed inside `_safely`, which answers None on any exception
and logs it. That is the THIRD state `describe()` already models — a null
signal on an ANSWERABLE tile — and it exists because the alternative is a hub
that renders nothing because one module's table was slow. A CA opening the hub
to see what is due should not lose the other fourteen figures to Inventory.

⚠️ It is deliberately NOT a blanket `except Exception` around the whole build:
that would turn a firm-scoping bug into an empty hub rather than an error, and
`effective_client_ids` returning the wrong set is exactly the failure that must
be loud.

── SCOPE IS RESOLVED ONCE, AT THE TOP ───────────────────────────────────────

`core.authz.effective_client_ids` answers None for a Partner (no restriction)
and a SET for everyone else — and an EMPTY set means nothing, never "no
filter", which is the distinction `routers/accounting.py` records. Resolving it
once and passing the id list down is what keeps a tile from re-deriving it and
getting it wrong; `_client_filter` is the one place that turns it into a
predicate.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from core.authz import effective_client_ids
from core.supabase_client import get_service_supabase
from domain.banking import entry as bank_entry
from domain.hub.tiles import describe, tiles_for_scope

logger = logging.getLogger("caflow.hub")

# ── The vocabularies, read from the CHECK rather than remembered ────────────
#
# Written out per tile rather than shared, because "not finished" is a
# DIFFERENT word in each of these and a shared set would silently adopt a
# fifth value added to one CHECK. Every list below was read off the live
# constraint on 24-09-2026, and four of the first nine written from memory
# were wrong — `documents` filters `review_status` and not `status`, and
# `year_end_engagements` allows draft/in_review/approved/locked rather than
# the not_started/in_progress/review that sounded right.
#
# A tile asks for what is NOT DONE, so each list is the complement of the
# finished states. Naming the finished ones and complementing is deliberate:
# a value added to a CHECK is almost always a new intermediate state, and it
# then joins the outstanding count automatically rather than being dropped.

_JOURNAL_DONE = ("posted", "void")
_PAYROLL_DONE = ("finalized", "paid")          # PAY-04's `_PAYROLL_RELEASED`
_GST_RETURN_DONE = ("submitted",)
_ITR_DONE = ("filed",)
_COMPLIANCE_DONE = ("Filed", "Completed")
_YEAR_END_DONE = ("locked",)

_ALL = {
    "journal_entries": ("draft", "posted", "void"),
    "payroll_runs": ("draft", "review", "finalized", "paid"),
    "gst_returns": ("draft", "validated", "ca_approved", "submitted"),
    "itr_filings": ("draft", "review", "partner_review", "ready_for_filing", "filed"),
    "compliance_records": ("Not Started", "Awaiting Documents", "In Progress",
                           "Ready For Review", "Ready To File", "Filed",
                           "Completed", "Overdue"),
    "year_end_engagements": ("draft", "in_review", "approved", "locked"),
}


def _outstanding(table_key: str, done: tuple[str, ...]) -> list[str]:
    """Every status of that CHECK that is not one of the finished ones."""
    return [v for v in _ALL[table_key] if v not in done]


def _db():
    return get_service_supabase()


def _safely(name: str, fn: Callable[[], Optional[int]]) -> Optional[int]:
    """One tile's figure, or None if it could not be read.

    See the module docstring: a tile that fails loses its own number and
    nothing else. The exception is logged with the tile's name so a hub that
    is quietly missing one figure is diagnosable from the logs rather than by
    guessing.
    """
    try:
        return fn()
    except Exception:                                   # noqa: BLE001 - see above
        logger.exception("caflow.hub: tile %s could not be read", name)
        return None


def _count(table: str, firm_id: str, client_ids: Optional[list[str]],
           *, eq: Optional[dict] = None, in_: Optional[tuple[str, list]] = None,
           gt: Optional[tuple[str, int]] = None, is_null: Optional[str] = None) -> int:
    """A COUNT, never a row set.

    `select("id", count="exact").limit(1)` is the idiom this codebase settled
    on (see bank_entry_service's note on why the count is decided at the table
    rather than after): PostgREST returns the count in the header and at most
    one row on the wire.
    """
    q = _db().table(table).select("id", count="exact").eq("firm_id", firm_id)
    if client_ids is not None:
        q = q.in_("client_id", client_ids)
    for col, val in (eq or {}).items():
        q = q.eq(col, val)
    if in_:
        q = q.in_(in_[0], in_[1])
    if gt:
        q = q.gt(gt[0], gt[1])
    if is_null:
        q = q.is_(is_null, "null")
    return int(q.limit(1).execute().count or 0)


def _sum_paise(table: str, column: str, firm_id: str,
               client_ids: Optional[list[str]], *, gt_zero: bool = True,
               extra_is_null: Optional[str] = None) -> int:
    """A total in paise.

    PostgREST has no SUM, so this reads the column for the rows that carry a
    balance and adds them here. That is proportional to the number of OPEN
    documents rather than to the ledger — migration 278 made `outstanding_paise`
    a generated column precisely so the filter could move into the query — and
    it is bounded by `core.db_paging.fetch_all`'s page size through the same
    keyset rule every other reader uses.
    """
    from core.db_paging import fetch_all

    def build(q):
        q = q.eq("firm_id", firm_id)
        if client_ids is not None:
            q = q.in_("client_id", client_ids)
        if extra_is_null:
            q = q.is_(extra_is_null, "null")
        return q.gt(column, 0) if gt_zero else q

    rows = fetch_all(_db().table(table), f"id,{column}", build)
    return sum(int(r.get(column) or 0) for r in rows)


def hub(current_user: dict, client_id: Optional[str] = None) -> dict:
    """Every tile the hub at this scope shows, with its figure.

    `client_id` None is the firm hub. A client hub passes one id and gets the
    same questions asked of that client alone — plus the two firm-level tiles
    dropped, which `tiles_for_scope` decides.
    """
    firm_id = current_user.get("firm_id")
    if not firm_id:
        raise ValueError("hub: the caller has no firm")

    if client_id is not None:
        scope: Optional[list[str]] = [client_id]
    else:
        eff = effective_client_ids(current_user)
        # None means no restriction (a Partner). An EMPTY set means this person
        # is assigned to nothing, which is NOT the same as "show everything" —
        # the distinction routers/accounting.py records, and the one that turns
        # a scoping bug into a cross-client read if it is collapsed.
        scope = None if eff is None else sorted(eff)

    signals = _signals(firm_id, scope)
    return {
        "scope": "client" if client_id else "firm",
        "client_id": client_id,
        "tiles": [
            describe(t, signals.get(t.id), client_id)
            for t in tiles_for_scope(client_id)
        ],
    }


def _signals(firm_id: str, scope: Optional[list[str]]) -> dict[str, Optional[int]]:
    """One figure per tile that has one at this scope. Each is independently
    recoverable — see `_safely`."""
    out: dict[str, Optional[int]] = {
        "compliance": _safely("compliance", lambda: _count(
            "compliance_records", firm_id, scope,
            in_=("status", _outstanding("compliance_records", _COMPLIANCE_DONE)))),
        "gst": _safely("gst", lambda: _count(
            "gstr1_returns", firm_id, scope,
            in_=("status", _outstanding("gst_returns", _GST_RETURN_DONE)))
            + _count("gstr3b_returns", firm_id, scope,
                     in_=("status", _outstanding("gst_returns", _GST_RETURN_DONE)))),
        # `entry_state`'s own vocabulary, from `domain/banking/entry`. OPEN_STATES
        # is that module's definition of a line still needing a person, so the
        # tile cannot drift from the queue it links to.
        "banking": _safely("banking", lambda: _count(
            "bank_transactions", firm_id, scope,
            in_=("entry_state", list(bank_entry.OPEN_STATES)))),
        "accounting": _safely("accounting", lambda: _count(
            "journal_entries", firm_id, scope,
            in_=("status", _outstanding("journal_entries", _JOURNAL_DONE)))),
        "sales": _safely("sales", lambda: _sum_paise(
            "client_sales_invoices", "outstanding_paise", firm_id, scope)),
        "purchases": _safely("purchases", lambda: _sum_paise(
            "purchase_bills", "outstanding_paise", firm_id, scope)),
        # Deducted and NOT YET DEPOSITED. `challan_no` is what a deposit
        # records, so its absence is the outstanding half — summing every
        # deduction would report a deductor who has paid everything over as
        # owing the whole year.
        "tds": _safely("tds", lambda: _sum_paise(
            "tds_deductions", "tds_paise", firm_id, scope, extra_is_null="challan_no")),
        "payroll": _safely("payroll", lambda: _count(
            "payroll_runs", firm_id, scope,
            in_=("status", _outstanding("payroll_runs", _PAYROLL_DONE)))),
        "income_tax": _safely("income_tax", lambda: _count(
            "itr_filings", firm_id, scope,
            in_=("status", _outstanding("itr_filings", _ITR_DONE)))),
        "fixed_assets": _safely("fixed_assets", lambda: _count(
            "fixed_assets", firm_id, scope, is_null="depreciation_posted_through")),
        "year_end": _safely("year_end", lambda: _count(
            "year_end_engagements", firm_id, scope,
            in_=("status", _outstanding("year_end_engagements", _YEAR_END_DONE)))),
        # `documents.review_status`, NOT `status` — the column this guessed
        # wrong first, and PostgREST answers 42703 on a column that is not
        # there rather than nothing, so it would have been a failed tile
        # rather than a wrong number. Still worth naming.
        "documents": _safely("documents", lambda: _count(
            "documents", firm_id, scope, eq={"review_status": "pending_review"})),
    }
    return out

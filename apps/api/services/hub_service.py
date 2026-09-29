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
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from core.authz import effective_client_ids
from core.supabase_client import get_service_supabase
from domain.banking import entry as bank_entry
from domain.hub.tiles import describe, tiles_for_scope

logger = logging.getLogger("caflow.hub")

# Bounded worker pool for the hub's independent per-tile reads — same pattern
# and the same justification as domain/reporting/sources.py's
# _MAX_PARALLEL_FETCHES: httpx.Client (which supabase-py/postgrest-py wrap) is
# documented thread-safe for concurrent requests, so sharing one client
# instance across these workers is safe, and each fetch here is a read with
# no shared mutable state beyond that. Comfortably above the ~14 tiles this
# module computes today, so every one of them gets its own worker rather than
# queueing behind another tile.
_MAX_PARALLEL_TILE_FETCHES = 16

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

# ── The two MONEY tiles ask a different question of their documents ─────────
#
# Not "which are unfinished" but "which are REAL": a document that was never
# issued (a draft) or was withdrawn (cancelled) is owed by nobody, and a
# soft-deleted row is one created by mistake. `outstanding_paise` is GENERATED
# (migration 278) from the money columns alone and knows nothing about either,
# so a cancelled ₹7 lakh bill kept its whole face value as "outstanding" and
# the Purchases tile counted it (accounting-hub-1-02). These are the ageing
# screens' own words — `vendor_statement_service._DEAD_BILL` and
# `customer_statement_service._DEAD_INVOICE` — so the tile and the screen a CA
# checks it against agree about which documents exist.
#
# NAMED AND EXCLUDED rather than listing the live ones, `_outstanding()`'s
# rule turned round: a status added to either CHECK is almost always a new
# LIVE state (a disputed bill is still owed), and it then joins the figure
# rather than silently leaving it. `status` is NOT NULL on both tables, so the
# SQL `NOT IN` cannot drop a row either. Migration 432 transcribes this and
# `tests/test_the_firm_hub_tiles_land_somewhere.py` holds the transcription.
_DEAD_DOCUMENT = ("draft", "cancelled")

_ALL = {
    "journal_entries": ("draft", "posted", "void"),
    "payroll_runs": ("draft", "review", "finalized", "paid"),
    "gst_returns": ("draft", "validated", "ca_approved", "submitted"),
    "itr_filings": ("draft", "review", "partner_review", "ready_for_filing", "filed"),
    "compliance_records": ("Not Started", "Awaiting Documents", "In Progress",
                           "Ready For Review", "Ready To File", "Filed",
                           "Completed", "Overdue"),
    "year_end_engagements": ("draft", "in_review", "approved", "locked"),
    # Held so the `_pg` guard can prove `_DEAD_DOCUMENT` names real states of
    # BOTH checks — a dead state spelled wrong would exclude nothing, silently.
    "client_sales_invoices": ("draft", "issued", "partially_paid", "paid", "cancelled"),
    "purchase_bills": ("draft", "received", "partially_paid", "paid", "cancelled"),
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
               extra_is_null: Optional[str] = None,
               live_documents_only: bool = False) -> int:
    """A total in paise.

    PostgREST has no SUM, so this reads the column for the rows that carry a
    balance and adds them here. That is proportional to the number of OPEN
    documents rather than to the ledger — migration 278 made `outstanding_paise`
    a generated column precisely so the filter could move into the query — and
    it is bounded by `core.db_paging.fetch_all`'s page size through the same
    keyset rule every other reader uses.

    `live_documents_only` is the sales and purchase document rule — not a
    draft, not cancelled, not soft-deleted; see `_DEAD_DOCUMENT`. Both are
    FILTERS, so the projection stays `id,<column>`: a tile reads the one column
    it sums and nothing else.
    """
    from core.db_paging import fetch_all

    # `fetch_all` takes a CALLABLE that returns a FRESH builder — builders are
    # stateful, so handing it one instance accumulates each page's filters on
    # top of the last. The projection goes inside, and must carry `id` because
    # that is the keyset cursor.
    def one_page():
        q = _db().table(table).select(f"id,{column}").eq("firm_id", firm_id)
        if client_ids is not None:
            q = q.in_("client_id", client_ids)
        if extra_is_null:
            q = q.is_(extra_is_null, "null")
        if live_documents_only:
            # `.not_` is a PROPERTY on the builder, never a call — see
            # tests/test_not_is_a_property_of_a_query_and_is_never_called.py.
            q = q.is_("deleted_at", "null").not_.in_("status", list(_DEAD_DOCUMENT))
        return q.gt(column, 0) if gt_zero else q

    rows = fetch_all(one_page, label=f"hub:{table}.{column}")
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

    signals = _signals(firm_id, scope, client_id)
    return {
        "scope": "client" if client_id else "firm",
        "client_id": client_id,
        "tiles": [
            describe(t, signals.get(t.id), client_id)
            for t in tiles_for_scope(client_id)
        ],
    }


def _signals(firm_id: str, scope: Optional[list[str]],
             client_id: Optional[str] = None) -> dict[str, Optional[int]]:
    """One figure per tile that has one at this scope. Each is independently
    recoverable — see `_safely`.

    `client_id` is taken rather than re-derived from `scope`, because the two
    answer different questions: `scope` is the client filter (a Partner's is
    None), and `client_id` is whether this is the CLIENT hub. A tile with a
    figure at one scope and not the other — `inventory` is the only one —
    needs the second, and reading it off the first would ask a Partner's firm
    hub for a per-client figure the moment they had exactly one client.

    apex-overview-practice-07(b): every one of the ~14 fetches below is
    independent of every other (a different table, no shared state), and
    `_safely` already isolates a tile's own failure from the rest — which is
    exactly what makes them safe to run CONCURRENTLY as well as isolatedly.
    They used to run one after another, each a Singapore-to-Mumbai round
    trip; run through a ThreadPoolExecutor instead, the same pattern
    `domain/reporting/sources.py`'s `_base()` already uses for its own
    independent top-level fetches, so the wall-clock cost drops from "the sum
    of every tile" to "roughly the slowest single tile"."""
    # Each value is a CALLABLE (never called yet) so building this dict does
    # no I/O — only submitting it to the executor below does.
    tasks: dict[str, Callable[[], Optional[int]]] = {
        "compliance": lambda: _count(
            "compliance_records", firm_id, scope,
            in_=("status", _outstanding("compliance_records", _COMPLIANCE_DONE))),
        "gst": lambda: _count(
            "gstr1_returns", firm_id, scope,
            in_=("status", _outstanding("gst_returns", _GST_RETURN_DONE)))
            + _count("gstr3b_returns", firm_id, scope,
                     in_=("status", _outstanding("gst_returns", _GST_RETURN_DONE))),
        # `entry_state`'s own vocabulary, from `domain/banking/entry`. OPEN_STATES
        # is that module's definition of a line still needing a person, so the
        # tile cannot drift from the queue it links to.
        "banking": lambda: _count(
            "bank_transactions", firm_id, scope,
            in_=("entry_state", list(bank_entry.OPEN_STATES))),
        "accounting": lambda: _count(
            "journal_entries", firm_id, scope,
            in_=("status", _outstanding("journal_entries", _JOURNAL_DONE))),
        # What the clients' CUSTOMERS owe them and what they owe their
        # SUPPLIERS — over live documents only, the ageing screens' rule.
        # ⚠️ Both questions say "Overdue" and both figures are everything
        # still OUTSTANDING, due or not; whether to filter on `due_date` or
        # reword the question is an open owner decision, deliberately not
        # taken here.
        "sales": lambda: _sum_paise(
            "client_sales_invoices", "outstanding_paise", firm_id, scope,
            live_documents_only=True),
        "purchases": lambda: _sum_paise(
            "purchase_bills", "outstanding_paise", firm_id, scope,
            live_documents_only=True),
        # Deducted and NOT YET DEPOSITED. `challan_no` is what a deposit
        # records, so its absence is the outstanding half — summing every
        # deduction would report a deductor who has paid everything over as
        # owing the whole year.
        "tds": lambda: _sum_paise(
            "tds_deductions", "tds_paise", firm_id, scope, extra_is_null="challan_no"),
        "payroll": lambda: _count(
            "payroll_runs", firm_id, scope,
            in_=("status", _outstanding("payroll_runs", _PAYROLL_DONE))),
        "income_tax": lambda: _count(
            "itr_filings", firm_id, scope,
            in_=("status", _outstanding("itr_filings", _ITR_DONE))),
        "fixed_assets": lambda: _count(
            "fixed_assets", firm_id, scope, is_null="depreciation_posted_through"),
        "year_end": lambda: _count(
            "year_end_engagements", firm_id, scope,
            in_=("status", _outstanding("year_end_engagements", _YEAR_END_DONE))),
        # `documents.review_status`, NOT `status` — the column this guessed
        # wrong first, and PostgREST answers 42703 on a column that is not
        # there rather than nothing, so it would have been a failed tile
        # rather than a wrong number. Still worth naming.
        "documents": lambda: _count(
            "documents", firm_id, scope, eq={"review_status": "pending_review"}),
    }
    # ── The one tile with a figure at one scope and not the other ──────────
    #
    # `Tile.no_firm_signal_because` has always SAID the client hub answers
    # this, and nothing computed it — so the payload carried `answerable:
    # true` with a null signal, which `describe()` defines as *the fetch for
    # this tile failed*. Nobody had asked. A null that misreports which KIND
    # of null it is, on the hub's own three-state contract.
    #
    # It is the only tile that delegates instead of issuing its own query, and
    # that is deliberate: what is at or below a reorder level is on-hand stock
    # against a per-item level, `domain/inventory/reorder` owns both halves of
    # that rule, and `service_catalogue.stock_qty_units` — the column a cheap
    # COUNT would have to read — is documented by migration 188 as a CACHE
    # whose authority is the ledger. A prompt to buy, computed off a drifted
    # cache, is wrong in the direction that costs money.
    #
    # ⚠️ COST: `reorder_service.assess` reads one row per GOOD and one position
    # per item, so it is proportional to the CATALOGUE and not to the ledger —
    # which is what CLAUDE.md's reporting rule actually forbids. It is still
    # the heaviest thing on this screen, for one integer. A
    # `reorder_count_as_at` SQL function beside migration 363's
    # `stock_position_as_at` would return that integer server-side; it is a
    # migration, so it is named here rather than taken as a side effect of a
    # hub. `_safely` already means a slow one costs this tile and no other,
    # and running it alongside every other tile's own fetch (rather than
    # strictly after them, as it used to) no longer adds its cost on top.
    #
    # ⚠️ AND ITS FALLBACK IS LEDGER-PROPORTIONAL, which is named rather than
    # hidden because an unnamed unbounded read is what the reporting rule
    # exists to stop. `stock_position_service.position` tries migration 363's
    # SQL aggregate and, if that RPC raises, falls back to the Python twin,
    # which pages EVERY movement up to the date. The blast radius is bounded
    # three ways — ONE client (the firm hub computes no inventory figure at
    # all), only while the SQL function is broken, and contained by `_safely`
    # — and the reorder report already takes that same fallback today. It is
    # a degradation, not a wrong number. The `reorder_count_as_at` function
    # above removes it.
    if client_id is not None:
        tasks["inventory"] = lambda: _reorder_count(firm_id, client_id)

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_TILE_FETCHES) as ex:
        futures = {name: ex.submit(_safely, name, fn) for name, fn in tasks.items()}
        return {name: f.result() for name, f in futures.items()}


def _reorder_count(firm_id: str, client_id: str) -> int:
    """How many items are at or below their reorder level.

    `to_reorder` is `domain/inventory/reorder.assess`'s own count, read rather
    than re-derived from the groups: the rule that an ABSENT level is not zero
    lives in that module, and counting the lines here would be a second,
    quieter implementation of it that puts every item with no level recorded
    into the buy list.
    """
    from services import reorder_service

    return int(reorder_service.assess(_db(), firm_id, client_id).get("to_reorder") or 0)

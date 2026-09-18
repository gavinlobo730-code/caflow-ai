"""
Inventory — stock register, per-item movement ledger, and manual stock
adjustment for kind='good' Product/Service catalogue items (migration 188;
costing engine in domain/inventory_service.py). Most stock movements are
written as a side effect of issuing a sales invoice, receiving a purchase
bill, issuing a credit/debit note (routers/sales_invoices.py,
routers/purchase_bills.py, routers/credit_notes.py, routers/debit_notes.py),
or seeding an opening balance (routers/service_catalogue.py) — never
directly through this router. The one exception is POST .../adjust below:
a CA-initiated physical-count correction, damage, theft, destruction or
free-sample giveaway, the only movement with no other document to attach to.
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from models.common import api_response
from models.inventory import (StockAdjustmentIn, NrvWritedownIn,
                              StockCountOpenIn, StockCountSaveIn,
                              CostingPolicyIn)
from core.permissions import rbac
from core.authz import assert_client_access
from services.audit_service import log_event
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.inventory")

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


# One page is 1000 ledger rows, and the scan is bounded to this many of them.
# Every round trip is Singapore→Mumbai (CLAUDE.md, "Reporting performance"), so
# the cap is what stops a pathological client turning a register load into a
# walk of its whole movement history. Hit, it is logged rather than swallowed —
# a register missing an item's running totals shows 0, which is
# indistinguishable from "never received stock", and that must not happen
# silently.
_LEDGER_SCAN_PAGES = 8

#: Rows per page. A named constant rather than a literal so the cap above can be
#: reached in a test without ten thousand fixture rows.
_LEDGER_PAGE_SIZE = 1000


def _last_ledger_rows(db, firm_id: str, client_id: str, item_ids: set[str]) -> dict[str, dict]:
    """Each item's current (most-recently-inserted) ledger row — the same
    running_qty_units/running_avg_cost_paise/running_value_paise every new
    movement chains from (domain/inventory_service.py::_last_ledger_row) —
    fetched in bulk for the whole stock register instead of one row per item.

    THE DOCSTRING USED TO CLAIM this "stops as soon as every item has been
    seen, rather than scanning the client's entire movement history", and that
    is precisely what it did not do (INV-07). `remaining` is seeded from every
    `kind='good'` catalogue row, INCLUDING items that have never had a
    movement — and an item with no ledger row can never be found, so
    `while remaining` stayed true and the loop paged to the end of the ledger
    every time. One catalogue item created and never received was enough. The
    query was also unfiltered, so each of those pages was a full-width read of
    rows belonging to items already found.

    Both are fixed by filtering the query to the items still WANTED and
    re-issuing it as that set shrinks. Two consequences worth stating:

      * `range` restarts at 0 whenever the filter narrows, because a narrowed
        filter is a different result set and an offset into the old one indexes
        nothing meaningful. Offset only advances while the filter is unchanged
        — the case where a single item's rows fill a whole page.
      * a page that returns nothing means the remaining items have no ledger
        rows AT ALL, which is the terminating answer the old loop could never
        reach. It is not an error: the caller renders 0, which is correct for
        an item that has never received stock.

    Ordering is `created_at desc`, matching `_last_ledger_row`'s exactly —
    which is INSERTION order, not `movement_date` order, and deliberately so:
    these are the chained running totals, and the chain is built in the order
    rows were written. A position AS AT a date is a different question and has
    its own answer (`public.stock_position_as_at`, migration 363).
    """
    found: dict[str, dict] = {}
    remaining = set(item_ids)
    page_size = _LEDGER_PAGE_SIZE      # module attribute, so a test can shrink it
    offset = 0
    filtered_for: Optional[frozenset] = None
    pages = 0
    while remaining and pages < _LEDGER_SCAN_PAGES:
        wanted = frozenset(remaining)
        if wanted != filtered_for:
            offset = 0                      # a new filter is a new result set
            filtered_for = wanted
        resp = (
            db.table("inventory_stock_ledger")
            .select("service_catalogue_id, running_qty_units, running_avg_cost_paise, running_value_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("service_catalogue_id", sorted(wanted))
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        pages += 1
        page = resp.data or []
        if not page:
            break                           # the rest have no ledger rows
        for row in page:
            sid = row["service_catalogue_id"]
            if sid in remaining:
                found[sid] = row
                remaining.discard(sid)
        if len(page) < page_size:
            break
        if frozenset(remaining) == filtered_for:
            # A full page and not one new item: every row belonged to items
            # already found, so page past them rather than re-reading the same
            # rows under an unchanged filter for ever.
            offset += page_size
    if remaining and pages >= _LEDGER_SCAN_PAGES:
        _logger.warning(
            "stock register scan hit its %d-page cap for client %s with %d item(s) "
            "unresolved — their running totals will render as zero",
            _LEDGER_SCAN_PAGES, client_id, len(remaining))
    return found


@router.get("/items")
def list_stock_items(
    client_id: str = Query(..., description="CA client ID — stock is client-owned, same as the catalogue"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Stock register: every kind='good' catalogue item for this client, with
    its current on-hand quantity, moving-average cost, and stock value —
    read from inventory_stock_ledger's running totals (the authoritative
    figures every posting chains from), not recomputed from
    service_catalogue's cache. qty * avg_cost re-rounds an already-rounded
    average cost at display time, which can drift a few paise per item from
    the ledger's exact cumulative value and, summed across the whole
    register, no longer ties to the Balance Sheet Inventory account. Items
    with no ledger history yet (never received a stock-in movement) show 0,
    same as before."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            return api_response(True, [])

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("service_catalogue")
            .select("id, name, description, hsn_sac, unit, kind, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")
            .order("name").order("id")
            .execute().data
        ) or []
        last_rows = _last_ledger_rows(db, firm_id, client_id, {r["id"] for r in rows})
        for r in rows:
            last = last_rows.get(r["id"])
            qty = float(last["running_qty_units"]) if last else 0.0
            avg = int(last["running_avg_cost_paise"]) if last else 0
            value = int(last["running_value_paise"]) if last else 0
            r["stock_qty_units"] = qty
            r["avg_cost_paise"] = avg
            r["stock_value_paise"] = value
        return api_response(True, rows)
    except Exception as e:
        _logger.error("list_stock_items: %s", e)
        return api_response(False, None, "Unable to load the stock register. Please try again.")


@router.get("/stock-summary")
def stock_summary(
    client_id: str = Query(..., description="CA client ID — stock is client-owned"),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today in IST"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Closing stock as at a date — the statement that ties to the Inventories
    line on the balance sheet, and the quantitative-details working paper a
    §44AB audit expects.

    Distinct from GET /items, which is the CURRENT position and takes no date.
    The two deliberately answer different questions: /items reads each item's
    latest running totals (the perpetual chain every future movement costs
    off), this sums the DELTAS up to a date. Over an item's whole history the
    two agree exactly — `_compute_stock_out` force-closes so that the deltas
    sum to the running value — and as at any earlier date only this one can
    answer at all, because the running totals are chained in INSERTION order.
    See migration 363 and domain/reporting/stock_position.py."""
    assert_client_access(current_user, client_id)
    try:
        from services import stock_position_service
        if _USE_MOCK:
            return api_response(True, stock_position_service.position(
                None, current_user.get("firm_id"), client_id, as_of))

        from core.supabase_client import get_supabase
        return api_response(True, stock_position_service.position(
            get_supabase(), current_user.get("firm_id"), client_id, as_of))
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("stock_summary: %s", e)
        return api_response(False, None, "Unable to load the stock summary. Please try again.")


@router.get("/stock-ageing")
def stock_ageing(
    client_id: str = Query(..., description="CA client ID — stock is client-owned"),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today in IST"),
    service_catalogue_id: Optional[str] = Query(None, description="One item, or the whole register"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """How long has the stock ON HAND been held (INV-04, migration 408).

    A DIFFERENT QUESTION FROM DAYS IDLE, which this router already answers.
    Days Idle is about the ITEM — when did it last move — and an item selling
    steadily has a recent answer while still carrying units bought three years
    ago behind the ones that keep turning over. Those units are the
    obsolescence AS-2 paragraph 24 makes the CA write down to net realisable
    value, and `/items/{id}/writedown` has offered the write-down since it was
    written with nothing to decide it on.

    Ageing assumes goods leave oldest-first for EVERY client, whatever cost
    formula their books use: AS-2 paragraph 14's choice governs what an issue
    is valued at, not which carton was carried out. The value in each band is
    the item's own carrying amount split in proportion to quantity — not the
    cost of the units in that band — because under the weighted average the
    layer costs would not sum to the carrying amount and the report would not
    foot to the Inventories line. Every answer says so.

    Computes and writes nothing: no provision, no percentage. AS-2 paragraph
    21 makes net realisable value an estimate of selling price less the costs
    to complete and sell, which is a fact about the market no ledger holds.
    """
    assert_client_access(current_user, client_id)
    try:
        from services import stock_ageing_service
        if _USE_MOCK:
            return api_response(True, stock_ageing_service.ageing(
                None, current_user.get("firm_id"), client_id, as_of,
                service_catalogue_id))

        from core.supabase_client import get_supabase
        return api_response(True, stock_ageing_service.ageing(
            get_supabase(), current_user.get("firm_id"), client_id, as_of,
            service_catalogue_id))
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("stock_ageing: %s", e)
        return api_response(False, None, "Unable to load the stock ageing. Please try again.")


@router.get("/items/{service_catalogue_id}/ledger")
def get_item_stock_ledger(
    service_catalogue_id: str,
    client_id: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Movement history for one stock item — mirrors the accounting Ledger
    view's shape (opening/running balance per row)."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            return api_response(True, {"item": None, "lines": []})

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import get_stock_ledger
        from domain.reporting import stock_position
        from services import stock_position_service
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, name, unit, stock_qty_units, avg_cost_paise")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")

        lines = get_stock_ledger(db, service_catalogue_id, start_date, end_date)

        # ── THE BALANCE COLUMN IS A PROPERTY OF THE ORDER IT IS SHOWN IN ─────
        # `lines` come back ordered by (movement_date, created_at) while each
        # row's STORED running totals were chained in insertion order — see
        # _last_ledger_row, which explains why the chain must stay that way.
        # The two orders disagree the moment a document is entered late, and
        # the screen rendered the stored columns beside the date order, so
        # neither row footed: +20 against a balance of 110 sitting above -10
        # against a balance of 90.
        #
        # So the balance shown is DERIVED here, from the deltas, in the order
        # displayed, running forward from the position as at the day before the
        # range. Added as new keys rather than overwriting running_qty_units /
        # running_value_paise: those are what the database holds and what every
        # future movement costs off, and relabelling them in the response would
        # tell the screen something untrue.
        opening_qty, opening_value = stock_position_service.opening_for_item(
            db, firm_id, client_id, service_catalogue_id, start_date)
        lines = stock_position.ledger_with_balances(lines, opening_qty, opening_value)
        closing_qty = lines[-1]["balance_qty_units"] if lines else str(opening_qty)
        closing_value = lines[-1]["balance_value_paise"] if lines else opening_value

        return api_response(True, {
            "item": item_resp.data[0],
            "lines": lines,
            "opening": {"qty_units": str(opening_qty),
                        "value_paise": opening_value,
                        "as_at": start_date or None},
            "closing": {"qty_units": closing_qty,
                        "value_paise": closing_value,
                        "as_at": end_date or None},
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_item_stock_ledger: %s", e)
        return api_response(False, None, "Unable to load the stock ledger. Please try again.")


@router.post("/items/{service_catalogue_id}/adjust")
def adjust_stock(
    service_catalogue_id: str,
    data: StockAdjustmentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Manual stock adjustment — physical count correction, damage, theft,
    destruction, or free samples given away. The CA explicitly confirms both
    the quantity/direction and whether it triggers an ITC reversal (CGST Act
    §17(5)(h)) before this posts; never inferred or auto-triggered."""
    assert_client_access(current_user, data.client_id)
    try:
        if data.direction == "increase" and data.reverse_itc:
            raise HTTPException(
                status_code=422,
                detail="ITC reversal only applies to a decrease (loss/write-off), not a surplus.",
            )
        if _USE_MOCK:
            return api_response(True, None)

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import apply_stock_adjustment
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, kind")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", data.client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")
        if item_resp.data[0].get("kind") != "good":
            raise HTTPException(status_code=422, detail="Only stock-tracked products can be adjusted.")

        period_validation_service.validate_posting_date(firm_id or "", data.adjustment_date)

        reference_no = data.reference_no or f"ADJ-{data.adjustment_date}"
        movement = apply_stock_adjustment(
            db, firm_id=firm_id or "", client_id=data.client_id, service_catalogue_id=service_catalogue_id,
            movement_date=data.adjustment_date, quantity=data.quantity, direction=data.direction,
            reverse_itc=data.reverse_itc, reference_no=reference_no,
            itc_reversal_is_interstate=data.itc_reversal_is_interstate,
            # journal_entries.created_by FK references users(id), not auth_user_id.
            created_by=current_user.get("id"),
        )
        log_event(
            firm_id or "", "inventory_adjustment", service_catalogue_id, "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={
                "direction": data.direction, "quantity": data.quantity, "reason": data.reason,
                "reverse_itc": data.reverse_itc,
                "itc_reversal_is_interstate": data.itc_reversal_is_interstate,
                "notes": data.notes,
            },
        )
        return api_response(True, movement)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("adjust_stock: %s", e)
        return api_response(False, None, "Unable to record the stock adjustment. Please try again.")


@router.post("/items/{service_catalogue_id}/writedown")
def writedown_stock_to_nrv(
    service_catalogue_id: str,
    data: NrvWritedownIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Write inventory down to net realisable value when NRV has fallen
    below the current moving-average cost (AS-2 / Ind AS 2 / ICDS-II:
    inventory must be carried at the LOWER of cost or NRV). No quantity
    change — value only. A no-op (200, data=null) if NRV is already >= the
    current average cost, or the item has no stock yet."""
    assert_client_access(current_user, data.client_id)
    try:
        if _USE_MOCK:
            return api_response(True, None)

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import apply_nrv_writedown
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, kind")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", data.client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")
        if item_resp.data[0].get("kind") != "good":
            raise HTTPException(status_code=422, detail="Only stock-tracked products can be written down.")

        period_validation_service.validate_posting_date(firm_id or "", data.writedown_date)

        reference_no = data.reference_no or f"NRV-{data.writedown_date}"
        movement = apply_nrv_writedown(
            db, firm_id=firm_id or "", client_id=data.client_id, service_catalogue_id=service_catalogue_id,
            movement_date=data.writedown_date, nrv_per_unit_paise=data.nrv_per_unit_paise,
            # journal_entries.created_by FK references users(id), not auth_user_id.
            reference_no=reference_no, created_by=current_user.get("id"),
        )
        log_event(
            firm_id or "", "inventory_nrv_writedown", service_catalogue_id, "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={"nrv_per_unit_paise": data.nrv_per_unit_paise, "notes": data.notes, "applied": bool(movement)},
        )
        return api_response(True, movement)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("writedown_stock_to_nrv: %s", e)
        return api_response(False, None, "Unable to record the write-down. Please try again.")


# ── The physical count (INV-08) ──────────────────────────────────────────────
# Stock-taking at 31 March produces a sheet with a hundred variances, and
# `POST /items/{id}/adjust` above takes ONE item per call. These four routes
# are the round trip the finding names: open a sheet, key the counted
# quantities back, see the variance list, post one batch under one reference.
#
# NOTHING HERE POSTS DIRECTLY. `services/stock_count_service.post_session`
# calls `domain/inventory_service.apply_stock_adjustment` once per varying
# line — the same function the single-item path above calls. One write path.
# CA REVIEW REQUIRED — the variance list is confirmed before it posts.

def _count_plan_response(session: dict, plan) -> dict:
    return {
        "session": {
            "id": session["id"],
            "client_id": session["client_id"],
            "count_date": str(session["count_date"])[:10],
            "reference_no": session["reference_no"],
            "status": session["status"],
            "notes": session.get("notes"),
            "posted_at": session.get("posted_at"),
        },
        "lines": [{
            "service_catalogue_id": p.line.service_catalogue_id,
            "item_name": p.line.item_name,
            "unit": p.line.unit,
            # The figure the sheet was printed against, and the one the
            # variance is measured against now. Both, because they can differ
            # and the CA needs to see that they did.
            "system_qty_units": str(p.line.system_qty_units),
            "current_qty_units": str(p.line.current_qty_units),
            "counted_qty_units": (None if p.line.counted_qty_units is None
                                  else str(p.line.counted_qty_units)),
            "variance_qty_units": (None if p.line.variance_qty_units is None
                                   else str(p.line.variance_qty_units)),
            "direction": p.direction,
            "reason": p.reason,
            "reverse_itc": p.line.reverse_itc,
            "itc_reversal_is_interstate": p.line.itc_reversal_is_interstate,
            "will_post": p.will_post,
            "gaps": p.gaps,
            "caveats": p.caveats,
            "notes": p.line.notes,
        } for p in plan.lines],
        "counted_count": plan.counted_count,
        "variance_count": plan.variance_count,
        "postable_count": len(plan.postable),
        "blocked_count": plan.blocked_count,
        "gaps": plan.gaps,
    }


@router.post("/count-sessions")
def open_count_session(
    data: StockCountOpenIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Open a count sheet with one line per stock item and the books' figure
    as at the COUNT DATE — not as at today, which would give the CA a variance
    against a position the count was never taken against."""
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, {"id": "mock-session", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import stock_count_service
    return api_response(True, stock_count_service.open_session(
        get_supabase(), firm_id=current_user.get("firm_id"), client_id=data.client_id,
        count_date=data.count_date, reference_no=data.reference_no,
        notes=data.notes, created_by=current_user.get("id")))


@router.get("/count-sessions")
def list_count_sessions(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, [])
    from core.supabase_client import get_supabase
    # Spelled out rather than passed as the service's SESSION_COLUMNS: the
    # column guard reads every `.select()` against the real schema and can
    # only do so on a literal. A test holds the two identical.
    rows = (get_supabase().table("stock_count_sessions").select(
                "id, firm_id, client_id, count_date, reference_no, status, notes, "
                "created_at, created_by, posted_at, posted_by")
            .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id)
            .order("count_date", desc=True).execute().data) or []
    return api_response(True, rows)


@router.get("/count-sessions/{session_id}")
def get_count_session(
    session_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The sheet and what it will post. The variance is recomputed here, never
    stored — see domain/inventory/count_session.py."""
    if _USE_MOCK:
        return api_response(True, {"session": None, "lines": []})
    from core.supabase_client import get_supabase
    from services import stock_count_service
    db = get_supabase()
    session, plan = stock_count_service.read_plan(
        db, firm_id=current_user.get("firm_id"), session_id=session_id)
    assert_client_access(current_user, session["client_id"])
    return api_response(True, _count_plan_response(session, plan))


@router.patch("/count-sessions/{session_id}")
def save_count_session(
    session_id: str,
    data: StockCountSaveIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """The counted quantities and the s.17(5)(h) decisions, in one call.

    Bulk by design: the whole point of the session is that a hundred-line
    sheet is one round trip rather than a hundred.
    """
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, {"saved": len(data.entries)})
    from core.supabase_client import get_supabase
    from services import stock_count_service
    db = get_supabase()
    session, _ = stock_count_service.read_plan(
        db, firm_id=current_user.get("firm_id"), session_id=session_id)
    if session["client_id"] != data.client_id:
        raise HTTPException(status_code=404, detail="Count sheet not found.")
    saved = stock_count_service.save_counts(
        db, firm_id=current_user.get("firm_id"), session_id=session_id,
        entries=[e.model_dump(exclude_unset=True) for e in data.entries])
    session, plan = stock_count_service.read_plan(
        db, firm_id=current_user.get("firm_id"), session_id=session_id)
    return api_response(True, {"saved": saved, **_count_plan_response(session, plan)})


@router.post("/count-sessions/{session_id}/post")
def post_count_session(
    session_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Post every varying line, under the session's own reference.

    # CA REVIEW REQUIRED — the CA confirms the variance list before this runs.
    """
    if _USE_MOCK:
        return api_response(True, {"session_id": session_id, "posted_count": 0,
                                   "posted": [], "failed": [], "failed_count": 0})
    from core.supabase_client import get_supabase
    from services import stock_count_service
    db = get_supabase()
    session, _ = stock_count_service.read_plan(
        db, firm_id=current_user.get("firm_id"), session_id=session_id)
    assert_client_access(current_user, session["client_id"])
    result = stock_count_service.post_session(
        db, firm_id=current_user.get("firm_id"), session_id=session_id,
        actor_id=current_user.get("id"))
    log_event(current_user.get("firm_id") or "", "stock_count_session", session_id, "post",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"reference_no": result["reference_no"],
                        "posted_count": result["posted_count"],
                        "failed_count": result["failed_count"]})
    return api_response(True, result)



# ── Which cost formula the books are kept on (AS-2 paragraph 14, INV-02) ─────
# The engine is `domain/inventory/costing.py` and the reads are
# `services/inventory_costing_policy_service.py`. Nothing is decided here.


@router.get("/costing-policy")
def get_costing_policy(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The client's cost formula, the alternatives, and what a change means.

    Also answers for a client with NOTHING recorded, which is the common case
    and is not the same as having no answer: every book in this product has
    been kept on the weighted average because it was the only formula there
    was, so the response says which formula is in force AND that nobody has
    chosen it.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, None)
    from core.supabase_client import get_supabase
    from services import inventory_costing_policy_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id") or ""
    data = svc.read_policy(db, firm_id=firm_id, client_id=client_id)
    data["methods_used"] = svc.ledger_methods_used(
        db, firm_id=firm_id, client_id=client_id)
    return api_response(True, data)


@router.put("/costing-policy")
def put_costing_policy(
    data: CostingPolicyIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Record the client's cost formula.

    A CHANGE IS A CHANGE IN ACCOUNTING POLICY (AS-5 paragraph 29) and it is
    PROSPECTIVE: nothing already priced is re-costed, so the server refuses a
    date stock has already moved on or after rather than quietly restating a
    closing stock figure that is in a filed return. The refusal is a 422
    carrying the sentence, because the CA has something to do about it — pick
    the start of the next period — and an opaque failure would send them to
    the database.
    """
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, None)
    from core.supabase_client import get_supabase
    from services import inventory_costing_policy_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id") or ""
    result = svc.set_policy(
        db, firm_id=firm_id, client_id=data.client_id,
        method=data.method, effective_from=data.effective_from,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    log_event(
        firm_id, "client", data.client_id, "update",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"inventory_costing_method": result.get("method"),
                  "effective_from": data.effective_from},
    )
    return api_response(True, result)


# ═══════════════════════════════════════════════════════════════════════════
# WHERE THE STOCK IS, AND WHICH LOT IT CAME FROM (INV-03a, migration 398)
# ═══════════════════════════════════════════════════════════════════════════
# `domain/inventory/location.py` decides whether a transfer is a supply,
# `domain/inventory/batches.py` decides what is expiring, and
# `services/inventory_location_service.py` fetches. Nothing below decides
# either — in particular nothing here knows Schedule I paragraph 2, and nothing
# here buckets an expiry date.

from datetime import date as _date  # noqa: E402 — module already imported above

from pydantic import BaseModel as _BaseModel, Field as _Field, field_validator  # noqa: E402


def _a_date(value: str, what: str) -> str:
    try:
        _date.fromisoformat(str(value)[:10])
    except Exception:
        raise ValueError(f"{what} must be a date, as YYYY-MM-DD.")
    return str(value)[:10]


class GodownIn(_BaseModel):
    """A place a client keeps stock.

    `state_code` and `gstin` are OPTIONAL and not derived from each other: a
    client with one registration needs neither, and a client with several needs
    both — CGST s.25(1) requires a registration in every State a taxable supply
    is made from, and which of them a warehouse operates under is a fact about
    the business rather than about its postcode.
    """
    client_id: str
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    gstin: Optional[str] = None
    is_default: bool = False
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def has_a_name(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Name the godown — it is what a CA reads on the "
                             "stock statement.")
        return v.strip()

    @field_validator("state_code")
    @classmethod
    def two_digits(cls, v):
        if v in (None, ""):
            return None
        value = str(v).strip()
        if len(value) != 2 or not value.isdigit():
            raise ValueError("A state code is the two digits a GSTIN starts "
                             "with, e.g. 27 for Maharashtra.")
        return value

    @field_validator("gstin")
    @classmethod
    def a_real_gstin(cls, v):
        if v in (None, ""):
            return None
        # THE CHECK DIGIT, not a shape regex. A valid-shaped wrong GSTIN on a
        # godown decides whether a stock transfer is a supply between distinct
        # persons — see domain/gst/gstin.py and the GST-29 bullet in CLAUDE.md.
        from domain.gst.gstin import problem_with
        value = str(v).strip().upper()
        problem = problem_with(value)
        if problem:
            raise ValueError(problem)
        return value


class BatchIn(_BaseModel):
    """One lot of one item.

    `expiry_date` is OPTIONAL with no default: plenty of stock does not expire,
    and a batch with none recorded is NAMED as having none rather than assumed
    sound.
    """
    client_id: str
    service_catalogue_id: str
    batch_no: str
    manufactured_on: Optional[str] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("batch_no")
    @classmethod
    def has_a_number(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("A batch needs the lot number on the carton.")
        return v.strip()

    @field_validator("manufactured_on", "expiry_date")
    @classmethod
    def dates_are_dates(cls, v):
        return _a_date(v, "The date") if v else v


class TransferIn(_BaseModel):
    client_id: str
    service_catalogue_id: str
    from_godown_id: str
    to_godown_id: str
    quantity: str
    movement_date: str
    batch_id: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("movement_date")
    @classmethod
    def moved_on_a_date(cls, v: str) -> str:
        return _a_date(v, "The date the stock moved")


def _loc():
    from services import inventory_location_service as svc
    return svc


def _loc_db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("/godowns")
def list_godowns(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Every place this client keeps stock, and which one a movement defaults to."""
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        from domain.inventory import location as _loc_domain
        return api_response(True, {"godowns": [], "default_godown_id": None,
                                   "unallocated_means": _loc_domain.UNALLOCATED_MEANS})
    return api_response(True, _loc().list_godowns(
        _loc_db(), firm_id=current_user.get("firm_id") or "", client_id=client_id))


@router.post("/godowns")
def create_godown(
    data: GodownIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, {"id": "mock-godown", **data.model_dump()})
    firm_id = current_user.get("firm_id") or ""
    row = _loc().create_godown(
        _loc_db(), firm_id=firm_id, client_id=data.client_id, name=data.name,
        code=data.code, address=data.address, state_code=data.state_code,
        gstin=data.gstin, is_default=data.is_default, notes=data.notes,
        actor_id=current_user.get("id"))
    log_event(firm_id, "godown", str(row.get("id") or ""), "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/godowns/{godown_id}")
def close_godown(
    godown_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Close a godown. Refused while it still holds stock."""
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {"ok": True, "closed": True})
    firm_id = current_user.get("firm_id") or ""
    result = _loc().close_godown(_loc_db(), firm_id=firm_id,
                                 client_id=client_id, godown_id=godown_id)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    log_event(firm_id, "godown", godown_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"))
    return api_response(True, result)


@router.get("/batches")
def list_batches(
    client_id: str = Query(...),
    service_catalogue_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, [])
    return api_response(True, _loc().list_batches(
        _loc_db(), firm_id=current_user.get("firm_id") or "",
        client_id=client_id, service_catalogue_id=service_catalogue_id))


@router.post("/batches")
def create_batch(
    data: BatchIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, {"id": "mock-batch", **data.model_dump()})
    firm_id = current_user.get("firm_id") or ""
    row = _loc().create_batch(
        _loc_db(), firm_id=firm_id, client_id=data.client_id,
        service_catalogue_id=data.service_catalogue_id,
        batch_no=data.batch_no, manufactured_on=data.manufactured_on,
        expiry_date=data.expiry_date, notes=data.notes,
        actor_id=current_user.get("id"))
    log_event(firm_id, "inventory_batch", str(row.get("id") or ""), "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.get("/position-detail")
def position_detail(
    client_id: str = Query(...),
    as_of: str = Query(..., description='"YYYY-MM-DD"'),
    service_catalogue_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Closing stock per item PER GODOWN PER BATCH, as at a date.

    The same deltas `stock_position_as_at` sums, grouped one grain finer, so
    the totals agree by construction.
    """
    assert_client_access(current_user, client_id)
    try:
        when = _date.fromisoformat(as_of[:10])
    except Exception:
        raise HTTPException(status_code=422, detail="The date must be YYYY-MM-DD.")
    if _USE_MOCK:
        return api_response(True, {"as_of": when.isoformat(), "rows": [],
                                   "total_value_paise": 0})
    return api_response(True, _loc().position_detail(
        _loc_db(), firm_id=current_user.get("firm_id") or "",
        client_id=client_id, as_of=when,
        service_catalogue_id=service_catalogue_id))


@router.get("/expiry")
def expiry_report(
    client_id: str = Query(...),
    as_of: str = Query(..., description='"YYYY-MM-DD"'),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What has expired and what is about to, by lot."""
    assert_client_access(current_user, client_id)
    try:
        when = _date.fromisoformat(as_of[:10])
    except Exception:
        raise HTTPException(status_code=422, detail="The date must be YYYY-MM-DD.")
    if _USE_MOCK:
        from domain.inventory import batches as _b
        return api_response(True, _b.expiry_report([], as_of=when).as_dict())
    return api_response(True, _loc().expiry_report(
        _loc_db(), firm_id=current_user.get("firm_id") or "",
        client_id=client_id, as_of=when))


@router.get("/transfer-preview")
def transfer_preview(
    client_id: str = Query(...),
    from_godown_id: str = Query(...),
    to_godown_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Whether moving stock between these two godowns is a supply.

    ASKED BEFORE THE MOVE and on its own, because between two registrations it
    needs a tax invoice — a decision about a document, not about stock.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        from domain.inventory import location as _loc_domain
        return api_response(True, {"is_supply": None,
                                   "reason": _loc_domain.REGISTRATION_NOT_RECORDED,
                                   "same_registration": None, "gaps": []})
    result = _loc().transfer_preview(
        _loc_db(), firm_id=current_user.get("firm_id") or "",
        client_id=client_id, from_godown_id=from_godown_id,
        to_godown_id=to_godown_id)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    return api_response(True, result)


@router.post("/transfer")
def transfer_stock(
    data: TransferIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Move stock from one godown to another. Posts no journal.

    Within one entity the stock is worth what it was worth before it was
    carried across the yard, and the two ledger rows carry equal and opposite
    value — so every total that already ties still ties. A cross-registration
    move IS a supply and the answer says so; the tax invoice is the CA's.
    """
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        return api_response(True, {"ok": True, "quantity": data.quantity,
                                   "value_paise": 0, "decision": {}})
    firm_id = current_user.get("firm_id") or ""
    result = _loc().transfer(
        _loc_db(), firm_id=firm_id, client_id=data.client_id,
        service_catalogue_id=data.service_catalogue_id,
        from_godown_id=data.from_godown_id, to_godown_id=data.to_godown_id,
        quantity=data.quantity, movement_date=data.movement_date,
        batch_id=data.batch_id, reference_no=data.reference_no,
        notes=data.notes, actor_id=current_user.get("id"))
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    log_event(firm_id, "inventory_transfer", data.service_catalogue_id, "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=result)
    return api_response(True, result)

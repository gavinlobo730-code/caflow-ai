"""
Inventory costing engine — moving-average valuation for stock-tracked
(kind='good') Product/Service catalogue items.

Moving-average costing: every stock-IN movement (purchase, opening balance)
recomputes the average cost per unit from the exact total value in (never
re-derived from a rounded per-unit figure — see _compute_stock_in). Every
stock-OUT movement (sale, adjustment) prices the outgoing units at the
CURRENT average cost — this is the defining trait of moving-average costing
versus FIFO/LIFO, which track cost by batch instead.

inventory_stock_ledger (migration 188) is the authoritative, append-only
audit trail: each row's running_qty_units / running_value_paise are computed
from the PREVIOUS row's running totals plus this movement's delta — never
from service_catalogue's cached stock_qty_units/avg_cost_paise, which exist
only for fast reads and are kept in sync as a side effect of each insert
here. This avoids rounding drift accumulating across many small movements
(see the "force-close at zero" comment in _compute_stock_out).

All money is integer paise (CLAUDE.md). Quantity uses Decimal (matching the
NUMERIC(10,3) columns) — quantity is not money, but Decimal still avoids the
float-imprecision class of bug for the same reason paise avoids it for money.

Stock-tracking failures must NEVER block the sale/purchase they're attached
to — record_stock_out never raises, even for an item with no stock history
yet (it records the movement as "oversold" from a zero baseline instead of
skipping; see record_stock_out's own docstring). The core sales-invoice /
purchase-bill posting flows this plugs into were live production code
before inventory existed; nothing here may regress them.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

_logger = logging.getLogger("caflow.inventory")


def _round_paise(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_stock_in(prev_qty: Decimal, prev_value_paise: int, quantity: Decimal, total_cost_paise: int) -> dict:
    """Pure moving-average math for a stock-IN movement. No I/O.

    new average = (prior value + this movement's exact total cost) / new qty
    — computed from the exact total, never from qty * a rounded unit cost,
    so the average never drifts across repeated stock-ins.

    task #103 (oversold absorb + COGS true-up): while prev_qty <= 0 — an
    oversold position, force-closed to prev_value_paise == 0 by
    _compute_stock_out — this stock-in is at least partly REPLENISHING units
    that were already sold at an assumed cost (Rs 0, since the sale had
    nothing to price them at) before their real cost was known. That
    covering portion's cost must NOT become "value on hand": the quantity it
    corresponds to is already gone. It comes back out as `trueup_paise` —
    the real cost of those already-sold units — for the caller to post as a
    Dr COGS correcting entry (mirroring mainstream ERPs: QuickBooks assigns
    Rs 0 average cost to an oversold item, then "posts... an adjustment
    entry to both COGS and inventory assets" once the bill arrives;
    Microsoft Dynamics names this exact mechanism "Adjusting Transaction for
    the Oversold Inventory Item" — reverse the estimated-cost posting,
    repost at the real cost). Only the portion of this stock-in beyond what
    clears the deficit is genuine new on-hand stock, valued at its own real
    cost — this mirrors _compute_stock_out's existing force-close invariant
    (qty <= 0 always pairs with value == 0) instead of contradicting it.
    """
    if quantity <= 0:
        raise ValueError("Stock-in quantity must be positive.")
    if total_cost_paise < 0:
        raise ValueError("Stock-in cost cannot be negative.")
    new_qty = prev_qty + quantity
    unit_cost = _round_paise(total_cost_paise / quantity)

    deficit_qty = min(quantity, -prev_qty) if prev_qty < 0 else Decimal(0)
    trueup_paise = _round_paise(unit_cost * deficit_qty) if deficit_qty > 0 else 0

    if new_qty <= 0:
        # Still oversold (or exactly zeroed out) after this stock-in — the
        # whole movement covers the deficit; none of it is value on hand.
        return {
            "quantity_delta": quantity,
            "unit_cost_paise": unit_cost,
            "value_delta_paise": 0,
            "running_qty_units": new_qty,
            "running_avg_cost_paise": 0,
            "running_value_paise": 0,
            "trueup_paise": total_cost_paise,
        }

    # Any deficit is now fully cleared; the remainder is genuine new stock.
    # prev_value_paise is always 0 here whenever prev_qty <= 0 (force-close
    # invariant), so when there was no deficit at all (prev_qty >= 0,
    # deficit_qty == 0, trueup_paise == 0) this reduces to exactly the
    # original formula: new_value = prev_value_paise + total_cost_paise.
    excess_value = total_cost_paise - trueup_paise
    new_value = prev_value_paise + excess_value
    new_avg = _round_paise(new_value / new_qty)
    return {
        "quantity_delta": quantity,
        "unit_cost_paise": unit_cost,
        "value_delta_paise": excess_value,
        "running_qty_units": new_qty,
        "running_avg_cost_paise": new_avg,
        "running_value_paise": new_value,
        "trueup_paise": trueup_paise,
    }


def _compute_stock_out(prev_qty: Decimal, prev_value_paise: int, prev_avg_paise: int, quantity: Decimal) -> dict:
    """Pure moving-average math for a stock-OUT movement. No I/O. Prices the
    outgoing units at the CURRENT moving-average cost.

    Force-closes the running value to exactly 0 once quantity reaches zero
    (or goes negative, i.e. oversold beyond recorded stock) rather than
    subtracting quantity * prev_avg — many small sales at a rounded per-unit
    cost would otherwise leave a stray nonzero value hanging off a
    zero/negative quantity forever.
    """
    if quantity <= 0:
        raise ValueError("Stock-out quantity must be positive.")
    new_qty = prev_qty - quantity
    out_value = _round_paise(quantity * prev_avg_paise)
    # Force-close: when the quantity is exhausted (or oversold), the movement
    # relieves EXACTLY what was on the books — value_delta = -prev_value, not
    # -(qty × avg). The two differ by the rounding residue (or, on an
    # oversell, by the whole phantom cost of units that never had value), and
    # value_delta drives the COGS journal — the old -(qty × avg) delta posted
    # COGS for value the ledger never held, driving the Inventory GL negative
    # while the ledger's running value force-closed to 0. With this, the
    # deltas always sum to the running value.
    if new_qty <= 0:
        out_value = prev_value_paise
    new_value = 0 if new_qty <= 0 else prev_value_paise - out_value
    new_avg = _round_paise(new_value / new_qty) if new_qty > 0 else 0
    return {
        "quantity_delta": -quantity,
        "unit_cost_paise": prev_avg_paise,
        "value_delta_paise": -out_value,
        "running_qty_units": new_qty,
        "running_avg_cost_paise": new_avg,
        "running_value_paise": new_value,
    }


def _last_ledger_row(db, service_catalogue_id: str) -> Optional[dict]:
    """The row every new movement chains its running totals from.

    INSERTION order (created_at), NOT movement_date: each row's running
    totals are computed once, at insert time, from the row inserted before
    it. Ordering by movement_date here made a BACKDATED document — a bill
    dated July 1 received on July 15, after a July-10 sale was already
    recorded — permanently fall out of the chain: the next movement's
    "previous row" was still the July-10 sale (later movement_date), so the
    backdated purchase's quantity and value vanished from every future
    running total (and from the service_catalogue cache) while its journal
    stayed on the GL. Late entry of documents is routine for CAs; chaining
    strictly by when each movement was RECORDED keeps the running ledger,
    the cache, and the GL consistent — the standard perpetual-system
    behaviour (cost applied as at time of recording). movement_date remains
    the document's own "as of" date for display/filtering."""
    resp = (
        db.table("inventory_stock_ledger")
        .select("running_qty_units, running_value_paise, running_avg_cost_paise")
        .eq("service_catalogue_id", service_catalogue_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _insert_and_cache(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    movement_type: str, calc: dict, source_type: Optional[str], source_id: Optional[str],
    reference_no: Optional[str], created_by: Optional[str],
) -> dict:
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "service_catalogue_id": service_catalogue_id,
        "movement_date": movement_date,
        "movement_type": movement_type,
        "quantity_delta": str(calc["quantity_delta"]),
        "unit_cost_paise": calc["unit_cost_paise"],
        "value_delta_paise": calc["value_delta_paise"],
        "running_qty_units": str(calc["running_qty_units"]),
        "running_avg_cost_paise": calc["running_avg_cost_paise"],
        "running_value_paise": calc["running_value_paise"],
        "source_type": source_type,
        "source_id": source_id,
        "reference_no": reference_no,
        "created_by": created_by,
        # Stamped explicitly (not left to the DB default) because
        # _last_ledger_row chains running totals by insertion order — an
        # explicit microsecond timestamp keeps that ordering deterministic
        # and identical between production and the in-memory test doubles.
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    inserted = db.table("inventory_stock_ledger").insert(row).execute()
    db.table("service_catalogue").update({
        "stock_qty_units": str(calc["running_qty_units"]),
        "avg_cost_paise": calc["running_avg_cost_paise"],
    }).eq("id", service_catalogue_id).execute()
    return inserted.data[0] if inserted.data else row


def _set_ledger_journal_entry_id(db, ledger_row_id: Optional[str], journal_entry_id: Optional[str]) -> None:
    """Backfill inventory_stock_ledger.journal_entry_id once the COGS/
    Inventory/return journal for this movement (or batch of movements) is
    known — the column exists from migration 188 but a movement is always
    recorded BEFORE its journal is posted, so it can only be set after the
    fact. Best-effort: a failure here never affects the movement or journal
    that already succeeded, it only degrades this cross-reference."""
    if not ledger_row_id or not journal_entry_id:
        return
    try:
        db.table("inventory_stock_ledger").update(
            {"journal_entry_id": journal_entry_id}
        ).eq("id", ledger_row_id).execute()
    except Exception as e:
        _logger.warning("Failed to backfill journal_entry_id on ledger row %s: %s", ledger_row_id, e)


def seed_opening_balance(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    opening_qty, opening_cost_paise, created_by: Optional[str] = None,
) -> Optional[dict]:
    """Idempotent — a no-op if an opening row already exists for this item
    (the product form may re-save without changing opening stock) or if
    opening qty/cost are not both set. Also posts (and links, via
    _set_ledger_journal_entry_id) a Dr Inventory / Cr Opening Balance Equity
    journal for the movement — see post_opening_stock_journal_entry."""
    if opening_qty is None or opening_cost_paise is None:
        return None
    qty = Decimal(str(opening_qty))
    if qty <= 0:
        return None
    existing = (
        db.table("inventory_stock_ledger").select("id")
        .eq("service_catalogue_id", service_catalogue_id).eq("movement_type", "opening")
        .limit(1).execute()
    )
    if existing.data:
        return None
    # Chain from the CURRENT running totals, not a hardcoded zero baseline —
    # an opening balance added AFTER movements already exist (e.g. the item
    # was sold/oversold before the CA set up its opening stock) previously
    # recorded running_qty = opening qty alone and overwrote the cache with
    # it, silently discarding the prior movements from the running position.
    prev = _last_ledger_row(db, service_catalogue_id)
    prev_qty = Decimal(str(prev["running_qty_units"])) if prev else Decimal("0")
    prev_value = int(prev["running_value_paise"]) if prev else 0
    calc = _compute_stock_in(prev_qty, prev_value, qty, int(opening_cost_paise))
    row = _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type="opening", calc=calc,
        source_type=None, source_id=None, reference_no=None, created_by=created_by,
    )
    journal_id = post_opening_stock_journal_entry(
        db, firm_id=firm_id, client_id=client_id, movement_date=movement_date,
        value_paise=int(calc["value_delta_paise"]), item_count=1, created_by=created_by,
        trueup_paise=int(calc.get("trueup_paise", 0)),
    )
    _set_ledger_journal_entry_id(db, row.get("id") if row else None, journal_id)
    return row


def seed_opening_balances_batch(
    db, *, firm_id: str, created_by: Optional[str], rows: list[dict],
) -> None:
    """Batched equivalent of seed_opening_balance for a batch of BRAND-NEW
    service_catalogue rows (bulk import only — see bulk_create_services).
    Every row here was just assigned a fresh uuid a moment ago in this same
    request, so — unlike the single-row path — there is no possible
    pre-existing ledger row to guard against, which is what let
    seed_opening_balance get away with 4 sequential round trips per item
    (existing-check, ledger insert, cache update... twice for anything that
    also re-reads). Collapsing that per-row loop to one ledger batch insert
    and one cache batch upsert is what actually fixes the multi-minute bulk
    import hang: 300+ products no longer means 1,000+ round trips, it means
    2. Never raises — a seeding failure here is logged and simply leaves
    those items without a seeded opening balance, matching
    seed_opening_balance's own never-block guarantee for the CSV import UX
    (a bad opening balance must never fail the whole product/service batch).

    Also posts ONE combined Dr Inventory / Cr Opening Balance Equity journal
    PER CLIENT in the batch (see post_opening_stock_journal_entry) — posted
    BEFORE the ledger insert so journal_entry_id can be written directly on
    each ledger row in that same insert, with no separate per-row backfill
    UPDATE needed (the per-document movement types above post their journal
    AFTER the ledger row because they don't know its value until
    record_stock_in/out computes it; here every row's value is already known
    from pure Python math, so the ordering can just be flipped)."""
    ledger_rows: list[dict] = []
    cache_rows: list[dict] = []
    fallback_date = datetime.now(timezone.utc).date().isoformat()
    totals_by_client: dict = {}

    for row in rows:
        if row.get("kind") != "good":
            continue
        opening_qty = row.get("opening_qty_units")
        opening_cost_paise = row.get("opening_cost_paise")
        if opening_qty is None or opening_cost_paise is None:
            continue
        qty = Decimal(str(opening_qty))
        if qty <= 0:
            continue
        # opening_balance_date, when the key is present at all, is the
        # caller's RESOLVED "as of" date (see routers/service_catalogue.py's
        # _resolve_opening_balance_date) — an explicit None/blank there means
        # the resolved date fell in a locked financial year, so this row's
        # seeding is skipped rather than silently falling back to today.
        # Callers that never resolved a date at all (the key is absent) keep
        # the old created_at/today fallback for backward compatibility.
        if "opening_balance_date" in row:
            movement_date = row.get("opening_balance_date")
            if not movement_date:
                continue
        else:
            movement_date = (row.get("created_at") or "")[:10] or fallback_date
        calc = _compute_stock_in(Decimal("0"), 0, qty, int(opening_cost_paise))
        client_id = row.get("client_id")
        ledger_rows.append({
            "firm_id": firm_id,
            "client_id": client_id,
            "service_catalogue_id": row["id"],
            "movement_date": movement_date,
            # created_at stamped explicitly — see _insert_and_cache: the
            # running-total chain orders by insertion time.
            "created_at": datetime.now(timezone.utc).isoformat(),
            "movement_type": "opening",
            "quantity_delta": str(calc["quantity_delta"]),
            "unit_cost_paise": calc["unit_cost_paise"],
            "value_delta_paise": calc["value_delta_paise"],
            "running_qty_units": str(calc["running_qty_units"]),
            "running_avg_cost_paise": calc["running_avg_cost_paise"],
            "running_value_paise": calc["running_value_paise"],
            "source_type": None,
            "source_id": None,
            "reference_no": None,
            "created_by": created_by,
        })
        cache_rows.append({
            "id": row["id"],
            # RLS's WITH CHECK for service_catalogue (firm_id = get_my_firm_id(),
            # can_access_client(client_id)) is evaluated against the row an
            # upsert WOULD insert, even when the row already exists and the
            # statement resolves to an UPDATE via ON CONFLICT — a payload with
            # only {id, stock_qty_units, avg_cost_paise} leaves firm_id/
            # client_id NULL on that candidate row and gets rejected with
            # "new row violates row-level security policy" before the UPDATE
            # ever runs. name is also NOT NULL with no column default, so it's
            # included too. All three are re-written to their EXISTING values
            # (never touched by the actual UPDATE for a row that already
            # matches), just present so the phantom insert candidate is valid.
            "firm_id": firm_id,
            "client_id": client_id,
            "name": row.get("name"),
            "stock_qty_units": str(calc["running_qty_units"]),
            "avg_cost_paise": calc["running_avg_cost_paise"],
        })
        totals = totals_by_client.setdefault(client_id, {"value_paise": 0, "movement_date": movement_date, "count": 0})
        totals["value_paise"] += int(calc["value_delta_paise"])
        totals["count"] += 1

    if not ledger_rows:
        return

    journal_id_by_client: dict = {}
    for client_id, totals in totals_by_client.items():
        journal_id_by_client[client_id] = post_opening_stock_journal_entry(
            db, firm_id=firm_id, client_id=client_id, movement_date=totals["movement_date"],
            value_paise=totals["value_paise"], item_count=totals["count"], created_by=created_by,
        )
    for lr in ledger_rows:
        lr["journal_entry_id"] = journal_id_by_client.get(lr["client_id"])

    try:
        db.table("inventory_stock_ledger").insert(ledger_rows).execute()
    except Exception as e:
        _logger.error("seed_opening_balances_batch: ledger batch insert failed for %d rows: %s", len(ledger_rows), e, exc_info=True)
        return
    try:
        db.table("service_catalogue").upsert(cache_rows, on_conflict="id").execute()
    except Exception as e:
        _logger.error("seed_opening_balances_batch: cache batch upsert failed for %d rows: %s", len(cache_rows), e, exc_info=True)


def record_stock_in(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    quantity, total_cost_paise: int, movement_type: str = "purchase",
    source_type: Optional[str] = None, source_id: Optional[str] = None,
    reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> dict:
    prev = _last_ledger_row(db, service_catalogue_id)
    prev_qty = Decimal(str(prev["running_qty_units"])) if prev else Decimal("0")
    prev_value = int(prev["running_value_paise"]) if prev else 0
    calc = _compute_stock_in(prev_qty, prev_value, Decimal(str(quantity)), int(total_cost_paise))
    row = _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type=movement_type, calc=calc,
        source_type=source_type, source_id=source_id, reference_no=reference_no, created_by=created_by,
    )
    # task #103: surfaced separately from the ledger row (no DB column for
    # it) — apply_purchase_to_inventory uses this to post a Dr COGS true-up
    # for the portion of this stock-in that covered a prior oversold
    # deficit; see _compute_stock_in's docstring.
    row["trueup_paise"] = calc.get("trueup_paise", 0)
    return row


def record_stock_out_at_value(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    quantity, value_paise: int, movement_type: str,
    source_type: Optional[str] = None, source_id: Optional[str] = None,
    reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> dict:
    """Stock-OUT at an EXPLICIT value instead of the current moving average —
    used by cancellation reversals, which must remove exactly the value the
    original movement added (the journal side reverses the original entry at
    its original value; pricing the reversal at the CURRENT average instead
    permanently split the Inventory GL from the stock ledger whenever the
    average had moved between receive and cancel). The value is clamped to
    what's actually on the books so a reversal can never drive the running
    value negative; the mismatch case logs a warning for the CA."""
    prev = _last_ledger_row(db, service_catalogue_id)
    prev_qty = Decimal(str(prev["running_qty_units"])) if prev else Decimal("0")
    prev_value = int(prev["running_value_paise"]) if prev else 0
    qty = Decimal(str(quantity))
    if qty <= 0:
        raise ValueError("Stock-out quantity must be positive.")
    new_qty = prev_qty - qty
    out_value = prev_value if new_qty <= 0 else min(int(value_paise), prev_value)
    if out_value != int(value_paise):
        _logger.warning(
            "record_stock_out_at_value: service_catalogue_id=%s requested value %d clamped to %d (books held less)",
            service_catalogue_id, int(value_paise), out_value,
        )
    new_value = prev_value - out_value
    new_avg = _round_paise(new_value / new_qty) if new_qty > 0 else 0
    calc = {
        "quantity_delta": -qty,
        "unit_cost_paise": _round_paise(Decimal(out_value) / qty) if qty else 0,
        "value_delta_paise": -out_value,
        "running_qty_units": new_qty,
        "running_avg_cost_paise": new_avg,
        "running_value_paise": new_value if new_qty > 0 else 0,
    }
    return _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type=movement_type, calc=calc,
        source_type=source_type, source_id=source_id, reference_no=reference_no, created_by=created_by,
    )


def record_stock_out(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    quantity, movement_type: str = "sale",
    source_type: Optional[str] = None, source_id: Optional[str] = None,
    reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> dict:
    """Prices the outgoing units at the CURRENT moving-average cost. If this
    item has no stock history at all yet (no opening balance, no prior
    purchase), starts from a zero baseline instead of skipping — the
    movement still records (quantity goes negative, i.e. "oversold", at
    Rs 0 cost) so a CA sees on the Inventory page that this item needs its
    opening stock set up, rather than the sale leaving no trace anywhere.
    Cost stays 0 until a real purchase/opening balance establishes an
    average; the oversold quantity self-corrects the next time stock comes
    in, exactly like any other stock-in blending into the running average."""
    prev = _last_ledger_row(db, service_catalogue_id)
    if prev is None:
        _logger.warning(
            "record_stock_out: no stock history for service_catalogue_id=%s — recording as oversold at Rs 0 cost until stock is set up",
            service_catalogue_id,
        )
    prev_qty = Decimal(str(prev["running_qty_units"])) if prev else Decimal("0")
    prev_value = int(prev["running_value_paise"]) if prev else 0
    prev_avg = int(prev["running_avg_cost_paise"]) if prev else 0
    calc = _compute_stock_out(prev_qty, prev_value, prev_avg, Decimal(str(quantity)))
    if calc["running_qty_units"] < 0:
        _logger.warning(
            "record_stock_out: service_catalogue_id=%s oversold by %s units — stock now negative",
            service_catalogue_id, abs(calc["running_qty_units"]),
        )
    return _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type=movement_type, calc=calc,
        source_type=source_type, source_id=source_id, reference_no=reference_no, created_by=created_by,
    )


def get_stock_ledger(db, service_catalogue_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
    def base_q():
        q = db.table("inventory_stock_ledger").select("*").eq("service_catalogue_id", service_catalogue_id)
        if start_date:
            q = q.gte("movement_date", start_date)
        if end_date:
            q = q.lte("movement_date", end_date)
        return q.order("movement_date").order("created_at")

    # OFFSET-paged, not keyset (task #221): an un-paged .execute() silently
    # capped at PostgREST's ~1000-row limit for a high-turnover SKU with years
    # of daily movements, truncating the running balance shown to the CA.
    # Keyset-by-id isn't usable here — running_qty_units/running_avg_cost_paise
    # are STORED at insert time in (movement_date, created_at) order, so that
    # exact display order must be preserved; offset is simplest and safe at
    # this per-item (not whole-tenant) row count.
    if not hasattr(base_q(), "range"):
        return base_q().execute().data or []
    out: list[dict] = []
    page = 1000
    offset = 0
    while True:
        rows = base_q().range(offset, offset + page - 1).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        offset += page
    return out


# ── COGS / Inventory journal postings ────────────────────────────────────────
# Deliberately posted as SEPARATE journal entries alongside the sales-invoice
# / purchase-bill's own (unmodified, already-tested) entry, rather than
# threading extra lines into that existing posting code — this keeps the
# already-live invoice/bill journal logic completely untouched, so an
# inventory-posting failure can never affect it. Both functions swallow
# every exception and return None on failure (never raise): quantity
# tracking (record_stock_in/out above) already happened regardless, and a
# missing Inventory/COGS control account is a setup gap for the firm to fix
# later via the Chart of Accounts, not a reason to fail an already-issued
# sale or already-received purchase.

def post_cogs_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, reference_no: str, source_type: Optional[str] = None,
    source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Cost of Goods Sold / Cr Inventory for one sale's worth of stock-out
    value. CGST Act is silent on COGS (a financial-statement concept, not a
    GST one) — this only affects the P&L/Balance Sheet, never a GST return."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        cogs_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Cost of Goods Sold%", system_key="cogs")
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-COGS", narration=f"Cost of goods sold — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": cogs_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"COGS — {item_name}"},
                {"account_id": inventory_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Inventory reduction — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_cogs_journal_entry skipped (%s): %s", reference_no, e)
        return None


def post_inventory_receipt_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    reference_no: str, items: list[dict],
    source_type: Optional[str] = None, source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Inventory (one combined total) / Cr [each line's own resolved
    expense account, grouped] — a reclassification that moves EVERY
    stock-tracked line on this document OUT of the expense account(s) it
    landed on by default and INTO Inventory, posted as ONE journal entry for
    the whole document (not one per line — a per-line journal would share
    this document's reference_no across all its calls, and
    _create_journal's idempotency guard, keyed on
    firm+client+reference_no+entry_date, would mistake lines 2+ for
    duplicate postings of line 1 and silently drop their value from the
    General Ledger while the stock ledger still recorded them correctly).
    Resolves each line's credit side with the SAME fallback order
    journal_for_purchase_bill itself uses (explicit expense_account_id →
    "%Purchase%" → "%Expense%"), grouped by resolved account exactly like
    journal_for_purchase_bill's own by_account grouping, so this always nets
    against whatever account(s) actually received the debit.

    items: [{"value_paise": int, "expense_account_id": Optional[str]}, ...]
    — one entry per qualifying stock-in line on this document."""
    total_value = sum(int(i["value_paise"]) for i in items if int(i["value_paise"]) > 0)
    if total_value <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        try:
            purchases_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Purchase%")
        except ValueError:
            purchases_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")

        by_account: dict = {}
        for i in items:
            value_paise = int(i["value_paise"])
            if value_paise <= 0:
                continue
            acc = i.get("expense_account_id") or purchases_id
            by_account[acc] = by_account.get(acc, 0) + value_paise

        lines = [
            {"account_id": inventory_id, "debit_paise": total_value, "credit_paise": 0, "narration": f"Inventory — {item_name}"},
        ]
        lines.extend(
            {"account_id": acc, "debit_paise": 0, "credit_paise": amt, "narration": f"Reclassify from expense — {item_name}"}
            for acc, amt in by_account.items()
        )
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-INV", narration=f"Capitalise purchase as inventory — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=lines,
        )
    except Exception as e:
        _logger.warning("post_inventory_receipt_journal_entry skipped (%s): %s", reference_no, e)
        return None


def post_inventory_trueup_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    reference_no: str, items: list[dict],
    source_type: Optional[str] = None, source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Cost of Goods Sold (one combined total) / Cr [each line's own
    resolved expense account, grouped] — task #103's oversold-replenishment
    true-up. For the portion of a stock-in that covers units already sold
    while the item was oversold (COGS assumed Rs 0 at sale time, since the
    real cost wasn't known yet — see _compute_stock_in), this corrects that
    estimate to the now-known real cost. Mirrors
    post_inventory_receipt_journal_entry's account-resolution/grouping
    exactly, but the debit lands on COGS instead of Inventory: this cost was
    already consumed by an earlier sale, it was never going to sit on the
    balance sheet as on-hand stock.

    items: [{"value_paise": int, "expense_account_id": Optional[str]}, ...]
    — one entry per stock-in line that had a true-up (deficit-covering)
    portion; a line whose stock-in was entirely genuine new stock (no prior
    deficit) simply contributes 0 here and is skipped."""
    total_value = sum(int(i["value_paise"]) for i in items if int(i["value_paise"]) > 0)
    if total_value <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        cogs_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Cost of Goods Sold%", system_key="cogs")
        try:
            purchases_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Purchase%")
        except ValueError:
            purchases_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")

        by_account: dict = {}
        for i in items:
            value_paise = int(i["value_paise"])
            if value_paise <= 0:
                continue
            acc = i.get("expense_account_id") or purchases_id
            by_account[acc] = by_account.get(acc, 0) + value_paise

        lines = [
            {"account_id": cogs_id, "debit_paise": total_value, "credit_paise": 0,
             "narration": f"Cost of goods sold — oversold true-up — {item_name}"},
        ]
        lines.extend(
            {"account_id": acc, "debit_paise": 0, "credit_paise": amt,
             "narration": f"Reclassify from expense — oversold true-up — {item_name}"}
            for acc, amt in by_account.items()
        )
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-COGSTRUEUP", narration=f"Oversold cost true-up — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=lines,
        )
    except Exception as e:
        _logger.warning("post_inventory_trueup_journal_entry skipped (%s): %s", reference_no, e)
        return None


def post_opening_stock_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, value_paise: int,
    item_count: int, created_by: Optional[str] = None, trueup_paise: int = 0,
) -> Optional[str]:
    """Dr Inventory / Cr Opening Balance Equity for opening stock brought
    onto the books — the SAME contra ACCOUNT opening_balance_service already
    uses for customers'/vendors'/bank accounts' opening positions, so the
    Trial Balance and Balance Sheet reconcile with what the Inventory page
    shows instead of silently omitting it. This was the one inventory
    movement type with no journal at all: purchase receipts, sales/COGS,
    sale/purchase returns, write-offs and NRV write-downs above all post
    their own entry; seed_opening_balance / seed_opening_balances_batch only
    ever wrote the ledger row and the service_catalogue cache.

    source_type is DELIBERATELY NOT "Opening" (services/opening_balance_
    service.py's OPENING_SOURCE) even though entry_type is — that constant
    is the identity marker services/opening_balance_service.py's
    _current_opening_net() uses to find "the auto-maintained AR/AP/Bank
    opening family it manages, per its own module docstring ("A user's own
    manually-created 'Opening' entry uses source_type='manual', so it is
    never touched by this service"). _plan_opening() deltas EVERY account
    appearing in that family against its AR/AP/Bank targets, including ones
    it has no target for (Inventory isn't one) — so an inventory-opening
    entry tagged source_type="Opening" gets silently zeroed out (or double-
    posted) the next time ANY customer/vendor/bank opening balance changes,
    corrupting the Inventory account. Confirmed live: importing 40 vendors'
    opening balances against a client that already had an inventory opening
    balance posted a combined delta entry that credited Inventory by its
    FULL original value on top of an otherwise-correct AR/AP adjustment.

    ONE combined entry for `item_count` items/value_paise, not one per item
    — Inventory is a single control account regardless of which item the
    value belongs to (the same reason opening_balance_service posts one
    Trade Receivables line for every customer's opening balance combined,
    not one per customer); the per-item breakdown already lives in
    service_catalogue / inventory_stock_ledger, not the journal. Callers
    seeding many items in one batch should sum value_paise across the whole
    batch and call this ONCE — calling it per item would reintroduce the
    same per-row round-trip cost seed_opening_balances_batch exists to avoid.

    trueup_paise (task #103): opening stock entered for an item ALREADY
    oversold in the ledger (a sale recorded before its opening balance was
    set up — see seed_opening_balance's docstring) corrects part of that
    earlier sale's assumed-Rs-0 COGS to its now-known real cost, per
    _compute_stock_in's oversold-absorb split. That portion is Dr Cost of
    Goods Sold instead of Dr Inventory — it was never going to sit on the
    balance sheet as on-hand stock — but still nets against the same Opening
    Balance Equity contra as the rest of this entry.

    Never raises — a missing chart-of-accounts entry degrades the journal
    (the opening quantity/cost is still recorded in the ledger either way),
    not a reason to fail whatever created the item(s)."""
    total = int(value_paise) + int(trueup_paise)
    if total <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        obe_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Opening Balance Equity%")
        reference_no = f"OPENING-STOCK-{uuid.uuid4().hex[:8].upper()}"
        narration = (
            f"Opening stock brought forward — {item_count} item{'s' if item_count != 1 else ''}"
        )
        lines = []
        if value_paise > 0:
            inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
            lines.append({"account_id": inventory_id, "debit_paise": int(value_paise), "credit_paise": 0, "narration": "Opening stock"})
        if trueup_paise > 0:
            cogs_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Cost of Goods Sold%", system_key="cogs")
            lines.append({"account_id": cogs_id, "debit_paise": int(trueup_paise), "credit_paise": 0,
                          "narration": "Cost of goods sold — oversold true-up on opening stock"})
        lines.append({"account_id": obe_id, "debit_paise": 0, "credit_paise": total, "narration": "Opening balance contra"})
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=reference_no, narration=narration,
            entry_type="Opening", source_type="InventoryOpening", source_id=None, created_by=created_by,
            lines=lines,
        )
    except Exception as e:
        _logger.warning("post_opening_stock_journal_entry skipped (value=%d, trueup=%d, items=%d): %s", value_paise, trueup_paise, item_count, e)
        return None


# ── Per-document orchestration ───────────────────────────────────────────────
# One call per issued sales invoice / received purchase bill. Both catch
# every exception internally and never raise — called AFTER the invoice/bill
# itself is already committed, so a failure here must never surface as a
# failure of the sale or purchase that triggered it.

def apply_sale_to_inventory(db, *, firm_id: str, client_id: str, invoice: dict, created_by: Optional[str] = None) -> None:
    try:
        lines = (
            db.table("client_sales_invoice_lines")
            .select("id, description, quantity, service_catalogue_id")
            .eq("sales_invoice_id", invoice["id"])
            .execute().data
        ) or []
        catalogue_ids = list({l["service_catalogue_id"] for l in lines if l.get("service_catalogue_id")})
        if not catalogue_ids:
            return
        items = (
            db.table("service_catalogue").select("id, kind, name")
            .in_("id", catalogue_ids).execute().data
        ) or []
        goods_by_id = {i["id"]: i for i in items if i.get("kind") == "good"}
        invoice_no = invoice.get("invoice_no") or invoice["id"]
        total_value = 0
        movement_ids = []
        for line in lines:
            item = goods_by_id.get(line.get("service_catalogue_id"))
            qty = line.get("quantity")
            if not item or not qty or float(qty) <= 0:
                continue
            movement = record_stock_out(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=item["id"],
                movement_date=invoice.get("invoice_date"), quantity=qty, movement_type="sale",
                source_type="sales_invoice", source_id=invoice["id"], reference_no=invoice.get("invoice_no"),
                created_by=created_by,
            )
            total_value += abs(int(movement["value_delta_paise"]))
            if movement and movement.get("id"):
                movement_ids.append(movement["id"])
        # ONE combined COGS journal for the WHOLE invoice, not one per line —
        # every line shares the same reference_no, and _create_journal's
        # idempotency guard (keyed on firm+client+reference_no+entry_date)
        # would otherwise mistake lines 2+ for duplicate postings of line 1
        # and silently drop their value from the General Ledger while the
        # stock ledger still records them correctly. A movement with no cost
        # basis (Rs 0, "oversold") contributes nothing here; total_value<=0
        # then skips posting entirely until a real average cost exists.
        if total_value > 0:
            journal_id = post_cogs_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=invoice.get("invoice_date"),
                item_name=f"invoice {invoice_no}", value_paise=total_value,
                reference_no=invoice_no,
                source_type="sales_invoice", source_id=invoice["id"], created_by=created_by,
            )
            for mid in movement_ids:
                _set_ledger_journal_entry_id(db, mid, journal_id)
    except Exception as e:
        _logger.error("apply_sale_to_inventory failed for invoice %s: %s", invoice.get("id"), e, exc_info=True)


def apply_purchase_to_inventory(db, *, firm_id: str, client_id: str, bill: dict, created_by: Optional[str] = None) -> None:
    try:
        lines = (
            db.table("purchase_bill_lines")
            .select("id, description, quantity, taxable_amount_paise, expense_account_id, service_catalogue_id")
            .eq("bill_id", bill["id"])
            .execute().data
        ) or []
        catalogue_ids = list({l["service_catalogue_id"] for l in lines if l.get("service_catalogue_id")})
        if not catalogue_ids:
            return
        items = (
            db.table("service_catalogue").select("id, kind, name")
            .in_("id", catalogue_ids).execute().data
        ) or []
        goods_by_id = {i["id"]: i for i in items if i.get("kind") == "good"}
        # Stock-ledger rows keep the human-facing bill number; the JOURNAL
        # reference must be system-unique (vendor bill numbers collide across
        # vendors — see phase2_journal_service.purchase_bill_journal_ref).
        reference_no = bill.get("bill_no") or bill.get("our_reference") or bill["id"]
        from services.phase2_journal_service import purchase_bill_journal_ref
        journal_ref = purchase_bill_journal_ref(bill["id"])
        receipt_items = []
        trueup_items = []
        movement_ids = []
        for line in lines:
            item = goods_by_id.get(line.get("service_catalogue_id"))
            qty = line.get("quantity")
            cost_paise = int(line.get("taxable_amount_paise") or 0)
            if not item or not qty or float(qty) <= 0 or cost_paise <= 0:
                continue
            movement = record_stock_in(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=item["id"],
                movement_date=bill.get("bill_date"), quantity=qty, total_cost_paise=cost_paise,
                movement_type="purchase", source_type="purchase_bill", source_id=bill["id"],
                reference_no=reference_no, created_by=created_by,
            )
            receipt_items.append({
                "value_paise": int(movement["value_delta_paise"]),
                "expense_account_id": line.get("expense_account_id"),
            })
            # task #103: a stock-in that (fully or partly) covers a prior
            # oversold deficit splits its cost between real on-hand value
            # (receipt_items above) and a COGS true-up (this) — see
            # _compute_stock_in / post_inventory_trueup_journal_entry.
            trueup_paise = int(movement.get("trueup_paise") or 0)
            if trueup_paise > 0:
                trueup_items.append({
                    "value_paise": trueup_paise,
                    "expense_account_id": line.get("expense_account_id"),
                })
            if movement and movement.get("id"):
                movement_ids.append(movement["id"])
        # ONE combined journal for the WHOLE bill (grouped by resolved expense
        # account — see post_inventory_receipt_journal_entry's docstring),
        # not one per line — every line shares the same reference_no, and
        # _create_journal's idempotency guard (keyed on firm+client+
        # reference_no+entry_date) would otherwise mistake lines 2+ for
        # duplicate postings of line 1 and silently drop their value from the
        # General Ledger while the stock ledger still records them correctly.
        if receipt_items:
            journal_id = post_inventory_receipt_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=bill.get("bill_date"),
                item_name=f"purchase bill {reference_no}", reference_no=journal_ref,
                items=receipt_items,
                source_type="purchase_bill", source_id=bill["id"], created_by=created_by,
            )
            for mid in movement_ids:
                _set_ledger_journal_entry_id(db, mid, journal_id)
        # Separate COGS true-up journal (own reference suffix, see
        # post_inventory_trueup_journal_entry) — posted independently of the
        # receipt journal above since a bill fully absorbed into a prior
        # deficit has trueup_items but no receipt_items at all.
        if trueup_items:
            post_inventory_trueup_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=bill.get("bill_date"),
                item_name=f"purchase bill {reference_no}", reference_no=journal_ref,
                items=trueup_items,
                source_type="purchase_bill", source_id=bill["id"], created_by=created_by,
            )
    except Exception as e:
        _logger.error("apply_purchase_to_inventory failed for bill %s: %s", bill.get("id"), e, exc_info=True)


# ── Reversal on cancellation ─────────────────────────────────────────────────
# cancel_invoice / cancel_purchase_bill reverse the document's main journal
# entry but know nothing about inventory — these two functions are the stock
# side of that same cancellation, called alongside it. A reversal is NOT a
# rewind to the original state: it adds/removes the original quantity at the
# CURRENT moving average (via the same record_stock_in/record_stock_out used
# for a normal movement) since other transactions may have happened in
# between — the same principle a real moving-average ledger uses everywhere
# else. Idempotent (checked via the sale_reversal/purchase_reversal rows
# themselves) and never raises: a cancellation must succeed even if its
# inventory reversal hits a problem.

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def reverse_sale_stock(db, *, firm_id: str, client_id: str, invoice_id: str, invoice_no: str, created_by: Optional[str] = None) -> None:
    try:
        already = (
            db.table("inventory_stock_ledger").select("id")
            .eq("source_type", "sales_invoice").eq("source_id", invoice_id).eq("movement_type", "sale_reversal")
            .limit(1).execute().data
        )
        if already:
            return
        original_moves = (
            db.table("inventory_stock_ledger").select("*")
            .eq("source_type", "sales_invoice").eq("source_id", invoice_id).eq("movement_type", "sale")
            .execute().data
        ) or []
        today = _today()
        movement_ids = []
        for mv in original_moves:
            qty = abs(Decimal(str(mv["quantity_delta"])))
            value = abs(int(mv["value_delta_paise"]))
            if qty <= 0:
                continue
            movement = record_stock_in(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=mv["service_catalogue_id"],
                movement_date=today, quantity=qty, total_cost_paise=value, movement_type="sale_reversal",
                source_type="sales_invoice", source_id=invoice_id, reference_no=invoice_no, created_by=created_by,
            )
            if movement and movement.get("id"):
                movement_ids.append(movement["id"])

        from services.phase2_journal_service import phase2_journal_service
        # Same invoice_no-or-id fallback apply_sale_to_inventory used when it
        # POSTED the COGS journal — an invoice with no invoice_no otherwise
        # posted "{id}-COGS" but this reverse path searched "-COGS" and never
        # found it (stock restored, COGS journal left standing).
        cogs_ref = f"{invoice_no or invoice_id}-COGS"
        jr = (
            db.table("journal_entries").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("reference_no", cogs_ref).eq("is_posted", True)
            .limit(1).execute().data
        )
        if jr:
            jrnl_id = jr[0]["id"]
            already_reversed = (
                db.table("journal_entries").select("id").eq("firm_id", firm_id).eq("reversal_of", jrnl_id)
                .limit(1).execute().data
            )
            if not already_reversed:
                reversal_id = phase2_journal_service.reverse_entry(
                    db, firm_id, jrnl_id, today,
                    narration=f"Cancellation of invoice {invoice_no} — inventory reversal",
                    created_by=created_by,
                )
                for mid in movement_ids:
                    _set_ledger_journal_entry_id(db, mid, reversal_id)
    except Exception as e:
        _logger.error("reverse_sale_stock failed for invoice %s: %s", invoice_id, e, exc_info=True)


def post_sale_return_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, reference_no: str, source_type: Optional[str] = None,
    source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Inventory / Cr Cost of Goods Sold — the mirror of
    post_cogs_journal_entry, for the returned-goods value on a credit note.
    Goods coming back into stock reverse the COGS that was posted when they
    were originally sold."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        cogs_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Cost of Goods Sold%", system_key="cogs")
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-INVRET", narration=f"Inventory restored — sales return {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": inventory_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Inventory — {item_name}"},
                {"account_id": cogs_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"COGS reversed — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_sale_return_journal_entry skipped (%s): %s", reference_no, e)
        return None


def post_purchase_return_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, reference_no: str, source_type: Optional[str] = None,
    source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr [Purchases/Expense] / Cr Inventory — the mirror of
    post_inventory_receipt_journal_entry, for the returned-goods value on a
    debit note. Resolves the debit side with the SAME fallback order
    journal_for_debit_note itself uses ("%Purchase%" then "%Expense%") since
    a debit note line carries no per-line expense_account_id override."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        try:
            expense_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Purchase%")
        except ValueError:
            expense_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-INVRET", narration=f"Inventory reduced — purchase return {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": expense_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Reclassify to expense — {item_name}"},
                {"account_id": inventory_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Inventory — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_purchase_return_journal_entry skipped (%s): %s", reference_no, e)
        return None


def _sale_unit_cost_for_return(db, service_catalogue_id: str, invoice_id: Optional[str]) -> Optional[int]:
    """Cost basis for goods coming BACK into stock on a sales return: the
    unit cost the original sale relieved them at (the invoice's own 'sale'
    ledger rows), so the return restores exactly what the sale took out.
    None when the CN isn't linked to an invoice or the invoice had no sale
    movement for this item — the caller falls back to the current average."""
    if not invoice_id:
        return None
    rows = (
        db.table("inventory_stock_ledger").select("unit_cost_paise")
        .eq("source_type", "sales_invoice").eq("source_id", invoice_id)
        .eq("service_catalogue_id", service_catalogue_id).eq("movement_type", "sale")
        .limit(1).execute().data
    ) or []
    return int(rows[0]["unit_cost_paise"]) if rows else None


def apply_credit_note_to_inventory(db, *, firm_id: str, client_id: str, credit_note: dict, created_by: Optional[str] = None) -> None:
    """Sales return: goods physically return to stock AT COST — the original
    sale's unit cost when the credit note references its invoice, else the
    item's current moving average — never at the credit note's taxable
    (SELLING) value. AS-2/Ind AS 2: inventory is carried at cost; restocking
    at the selling price inflated inventory by the sales margin and
    over-credited COGS (a full-margin return produced phantom negative
    COGS). A separate Dr Inventory / Cr COGS journal posts for the same
    realized total. Called AFTER the credit note is already issued and its
    own GL journal + AR sub-ledger application have committed
    (routers/credit_notes.py) — fail-soft, never raises."""
    try:
        cn_id = credit_note.get("id")
        cn_no = credit_note.get("credit_note_no") or cn_id
        invoice_id = credit_note.get("sales_invoice_id")
        lines = (
            db.table("credit_note_lines")
            .select("id, description, quantity, taxable_amount_paise, service_catalogue_id")
            .eq("credit_note_id", cn_id)
            .execute().data
        ) or []
        catalogue_ids = list({l["service_catalogue_id"] for l in lines if l.get("service_catalogue_id")})
        if not catalogue_ids:
            return
        items = (
            db.table("service_catalogue").select("id, kind, name")
            .in_("id", catalogue_ids).execute().data
        ) or []
        goods_by_id = {i["id"]: i for i in items if i.get("kind") == "good"}
        total_value = 0
        movement_ids = []
        for line in lines:
            item = goods_by_id.get(line.get("service_catalogue_id"))
            qty = line.get("quantity")
            if not item or not qty or float(qty) <= 0:
                continue
            unit_cost = _sale_unit_cost_for_return(db, item["id"], invoice_id)
            if unit_cost is None:
                prev = _last_ledger_row(db, item["id"])
                unit_cost = int(prev["running_avg_cost_paise"]) if prev else 0
            value = _round_paise(Decimal(str(qty)) * unit_cost)
            movement = record_stock_in(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=item["id"],
                movement_date=credit_note.get("credit_note_date"), quantity=qty, total_cost_paise=value,
                movement_type="sale_return", source_type="credit_note", source_id=cn_id,
                reference_no=cn_no, created_by=created_by,
            )
            total_value += value
            if movement and movement.get("id"):
                movement_ids.append(movement["id"])
        if total_value > 0:
            journal_id = post_sale_return_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=credit_note.get("credit_note_date"),
                item_name=f"credit note {cn_no}", value_paise=total_value, reference_no=cn_no,
                source_type="credit_note", source_id=cn_id, created_by=created_by,
            )
            for mid in movement_ids:
                _set_ledger_journal_entry_id(db, mid, journal_id)
    except Exception as e:
        _logger.error("apply_credit_note_to_inventory failed for CN %s: %s", credit_note.get("id"), e, exc_info=True)


def apply_debit_note_to_inventory(db, *, firm_id: str, client_id: str, debit_note: dict, created_by: Optional[str] = None) -> None:
    """Purchase return: goods physically leave stock. Stock-OUT at the
    CURRENT moving-average cost (same convention as a sale), plus a
    separate Dr Expense / Cr Inventory journal entry for the realised
    value. Called AFTER the debit note is already issued and its own GL
    journal + AP sub-ledger application have committed
    (routers/debit_notes.py) — fail-soft, never raises."""
    try:
        dn_id = debit_note.get("id")
        dn_no = debit_note.get("debit_note_no") or dn_id
        lines = (
            db.table("debit_note_lines")
            .select("id, description, quantity, service_catalogue_id")
            .eq("debit_note_id", dn_id)
            .execute().data
        ) or []
        catalogue_ids = list({l["service_catalogue_id"] for l in lines if l.get("service_catalogue_id")})
        if not catalogue_ids:
            return
        items = (
            db.table("service_catalogue").select("id, kind, name")
            .in_("id", catalogue_ids).execute().data
        ) or []
        goods_by_id = {i["id"]: i for i in items if i.get("kind") == "good"}
        total_value = 0
        movement_ids = []
        for line in lines:
            item = goods_by_id.get(line.get("service_catalogue_id"))
            qty = line.get("quantity")
            if not item or not qty or float(qty) <= 0:
                continue
            movement = record_stock_out(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=item["id"],
                movement_date=debit_note.get("debit_note_date"), quantity=qty, movement_type="purchase_return",
                source_type="debit_note", source_id=dn_id, reference_no=dn_no, created_by=created_by,
            )
            total_value += abs(int(movement["value_delta_paise"]))
            if movement.get("id"):
                movement_ids.append(movement["id"])
        if total_value > 0:
            journal_id = post_purchase_return_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=debit_note.get("debit_note_date"),
                item_name=f"debit note {dn_no}", value_paise=total_value, reference_no=dn_no,
                source_type="debit_note", source_id=dn_id, created_by=created_by,
            )
            for mid in movement_ids:
                _set_ledger_journal_entry_id(db, mid, journal_id)
    except Exception as e:
        _logger.error("apply_debit_note_to_inventory failed for DN %s: %s", debit_note.get("id"), e, exc_info=True)


def reverse_purchase_stock(db, *, firm_id: str, client_id: str, bill_id: str, bill_reference: str, created_by: Optional[str] = None) -> None:
    try:
        already = (
            db.table("inventory_stock_ledger").select("id")
            .eq("source_type", "purchase_bill").eq("source_id", bill_id).eq("movement_type", "purchase_reversal")
            .limit(1).execute().data
        )
        if already:
            return
        original_moves = (
            db.table("inventory_stock_ledger").select("*")
            .eq("source_type", "purchase_bill").eq("source_id", bill_id).eq("movement_type", "purchase")
            .execute().data
        ) or []
        today = _today()
        movement_ids = []
        for mv in original_moves:
            qty = abs(Decimal(str(mv["quantity_delta"])))
            if qty <= 0:
                continue
            # Reverse at the ORIGINAL received value, not the current moving
            # average — the journal side reverses the original "-INV" entry at
            # its original value, and the two sides must remove the same
            # amount or Inventory GL permanently drifts from the stock ledger.
            movement = record_stock_out_at_value(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=mv["service_catalogue_id"],
                movement_date=today, quantity=qty, value_paise=abs(int(mv["value_delta_paise"])),
                movement_type="purchase_reversal",
                source_type="purchase_bill", source_id=bill_id, reference_no=bill_reference, created_by=created_by,
            )
            if movement.get("id"):
                movement_ids.append(movement["id"])

        from services.phase2_journal_service import phase2_journal_service, purchase_bill_journal_ref
        # New receipts post the capitalisation journal under the system-unique
        # PB-{id} base ref; receipts from before that fix used the vendor's
        # bill number — try both so old bills stay reversible.
        jr = None
        for inv_ref in (f"{purchase_bill_journal_ref(bill_id)}-INV", f"{bill_reference}-INV"):
            jr = (
                db.table("journal_entries").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("reference_no", inv_ref).eq("is_posted", True)
                .limit(1).execute().data
            )
            if jr:
                break
        if jr:
            jrnl_id = jr[0]["id"]
            already_reversed = (
                db.table("journal_entries").select("id").eq("firm_id", firm_id).eq("reversal_of", jrnl_id)
                .limit(1).execute().data
            )
            if not already_reversed:
                reversal_id = phase2_journal_service.reverse_entry(
                    db, firm_id, jrnl_id, today,
                    narration=f"Cancellation of purchase bill {bill_reference} — inventory reversal",
                    created_by=created_by,
                )
                for mid in movement_ids:
                    _set_ledger_journal_entry_id(db, mid, reversal_id)

        # task #103: also reverse any oversold COGS true-up posted alongside
        # this bill's receipt (post_inventory_trueup_journal_entry) —
        # cancelling the bill withdraws the "real cost" that correction was
        # based on, so leaving it standing would permanently correct an
        # earlier oversold sale's COGS using a cost from a bill that no
        # longer exists. Independent of the -INV journal above: a bill that
        # was ENTIRELY a true-up (fully absorbed into a prior deficit, no
        # excess) never posts a -INV journal at all.
        trueup_ref = f"{purchase_bill_journal_ref(bill_id)}-COGSTRUEUP"
        tjr = (
            db.table("journal_entries").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("reference_no", trueup_ref).eq("is_posted", True)
            .limit(1).execute().data
        )
        if tjr:
            tjrnl_id = tjr[0]["id"]
            already_reversed_trueup = (
                db.table("journal_entries").select("id").eq("firm_id", firm_id).eq("reversal_of", tjrnl_id)
                .limit(1).execute().data
            )
            if not already_reversed_trueup:
                phase2_journal_service.reverse_entry(
                    db, firm_id, tjrnl_id, today,
                    narration=f"Cancellation of purchase bill {bill_reference} — oversold true-up reversal",
                    created_by=created_by,
                )
    except Exception as e:
        _logger.error("reverse_purchase_stock failed for bill %s: %s", bill_id, e, exc_info=True)


# ── Manual stock adjustment ──────────────────────────────────────────────────
# The only movement not driven by a sales invoice / purchase bill / credit
# note / debit note — a CA-initiated physical-count correction, damage,
# theft, destruction or free-sample giveaway (routers/inventory.py). CGST
# Act §17(5)(h): ITC must be reversed for goods lost, stolen, destroyed,
# written off, or given away as gifts/free samples — never for a favourable
# count surplus. Whether reverse_itc applies is a CA judgment call passed in
# by the caller, never inferred here (see models/inventory.py's docstring).

def _movement_journal_ref(prefix: str, movement_id) -> str:
    """System-unique journal reference for a manual inventory movement
    (adjustment / NRV write-down) — same fix as purchase_bill_journal_ref
    (services/phase2_journal_service.py). routers/inventory.py defaults its
    reference_no to just the adjustment/writedown DATE when the CA doesn't
    supply one, which has no uniqueness guarantee: two same-day adjustments
    (different items, or the same item twice) produced identical journal
    reference_no values, and _create_journal's (firm, client, reference_no,
    entry_date) idempotency guard silently deduped the second journal onto
    the first — its value never posted to the General Ledger even though the
    stock ledger recorded it correctly. The ledger row's own DB-generated id
    is unique per movement, so the journal reference derives from it; the
    human-facing reference_no stays on the stock ledger row for the CA to
    read (record_stock_adjustment/record_nrv_writedown, called separately
    above)."""
    return f"{prefix}-{str(movement_id)[:8].upper()}"

def record_stock_adjustment(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    quantity, direction: str, reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> dict:
    """direction="increase": stock-IN valued at the CURRENT average cost —
    keeps the average stable rather than diluting/inflating it with an
    assumed cost for stock whose origin is unknown (a physical count found
    more than the books show). direction="decrease": stock-OUT, priced at
    the current average like a sale (record_stock_out's own zero-baseline
    behavior applies unchanged if this item somehow has no history yet)."""
    if direction == "increase":
        prev = _last_ledger_row(db, service_catalogue_id)
        prev_avg = int(prev["running_avg_cost_paise"]) if prev else 0
        total_cost_paise = _round_paise(Decimal(str(quantity)) * prev_avg)
        return record_stock_in(
            db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
            movement_date=movement_date, quantity=quantity, total_cost_paise=total_cost_paise,
            movement_type="adjustment", source_type="adjustment", source_id=None,
            reference_no=reference_no, created_by=created_by,
        )
    return record_stock_out(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, quantity=quantity, movement_type="adjustment",
        source_type="adjustment", source_id=None, reference_no=reference_no, created_by=created_by,
    )


def post_stock_writeoff_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, gst_rate_bps: int, reverse_itc: bool, reference_no: str,
    source_type: Optional[str] = None, source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Stock Write-off Expense / Cr Inventory for the item's carrying
    value, plus — when reverse_itc is True — an additional Dr [same
    write-off account] / Cr GST Input Tax Credit line reversing the ITC
    originally claimed on that value (CGST Act §17(5)(h)). The ITC amount
    is APPROXIMATED using this item's own gst_rate_bps (the rate it's
    classified/sold at) — a CA should verify against the actual purchase
    invoice(s) for a high-value write-off; this is a starting figure, not
    an authoritative GSTR-3B reversal computation."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        try:
            writeoff_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Write%off%")
        except ValueError:
            try:
                writeoff_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Loss%")
            except ValueError:
                writeoff_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")

        lines = [
            {"account_id": writeoff_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Stock write-off — {item_name}"},
            {"account_id": inventory_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Inventory reduced — {item_name}"},
        ]
        if reverse_itc and gst_rate_bps:
            itc_reversed = _round_paise(Decimal(value_paise) * gst_rate_bps / Decimal(10000))
            if itc_reversed > 0:
                gst_input_id = phase2_journal_service._find_account(db, firm_id, client_id, "%GST Input%", system_key="gst_input")
                lines.append({"account_id": writeoff_id, "debit_paise": itc_reversed, "credit_paise": 0, "narration": f"ITC reversed (CGST Act §17(5)(h)) — {item_name}"})
                lines.append({"account_id": gst_input_id, "debit_paise": 0, "credit_paise": itc_reversed, "narration": f"GST input credit reversed — {item_name}"})

        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-WOFF", narration=f"Stock write-off — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=lines,
        )
    except Exception as e:
        _logger.warning("post_stock_writeoff_journal_entry skipped (%s): %s", reference_no, e)
        return None


def post_stock_surplus_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, reference_no: str, source_type: Optional[str] = None,
    source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Inventory / Cr Miscellaneous Income — a physical count found MORE
    stock than the books show. No GST/ITC implication: CGST Act §17(5)(h)
    governs credit reversal on lost/destroyed/gifted goods, not a
    favourable count."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        try:
            income_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Miscellaneous Income%")
        except ValueError:
            income_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Other Income%")
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-SURP", narration=f"Stock surplus — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": inventory_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Inventory increased — {item_name}"},
                {"account_id": income_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Stock surplus — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_stock_surplus_journal_entry skipped (%s): %s", reference_no, e)
        return None


def apply_stock_adjustment(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    quantity, direction: str, reverse_itc: bool = False, reference_no: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Optional[dict]:
    """One call per manual stock adjustment (routers/inventory.py). Fail-soft
    — never raises; a missing chart-of-accounts entry degrades the journal,
    never the stock movement itself. Returns the ledger row, or None if the
    item can't be found (the router already 404s on that case, so this is
    only a defensive fallback)."""
    try:
        items = (
            db.table("service_catalogue").select("id, name, gst_rate_bps")
            .eq("id", service_catalogue_id).limit(1).execute().data
        ) or []
        if not items:
            return None
        item = items[0]
        item_name = item.get("name") or "item"

        movement = record_stock_adjustment(
            db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
            movement_date=movement_date, quantity=quantity, direction=direction,
            reference_no=reference_no, created_by=created_by,
        )
        value_paise = abs(int(movement["value_delta_paise"]))
        journal_ref = _movement_journal_ref("ADJ", movement.get("id"))
        if direction == "decrease":
            journal_id = post_stock_writeoff_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=movement_date,
                item_name=item_name, value_paise=value_paise, gst_rate_bps=int(item.get("gst_rate_bps") or 0),
                reverse_itc=reverse_itc, reference_no=journal_ref,
                source_type="adjustment", source_id=movement.get("id"), created_by=created_by,
            )
        else:
            journal_id = post_stock_surplus_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=movement_date,
                item_name=item_name, value_paise=value_paise, reference_no=journal_ref,
                source_type="adjustment", source_id=movement.get("id"), created_by=created_by,
            )
        _set_ledger_journal_entry_id(db, movement.get("id"), journal_id)
        return movement
    except Exception as e:
        _logger.error("apply_stock_adjustment failed for item %s: %s", service_catalogue_id, e, exc_info=True)
        return None


# ── Lower-of-cost-or-NRV write-down ──────────────────────────────────────────
# AS-2 / Ind AS 2 / ICDS-II: inventory must be carried at the LOWER of cost
# or net realisable value. A VALUE-only movement — quantity never changes —
# distinct from a manual stock adjustment (which always represents a
# quantity change). movement_type='nrv_writedown' (migration 191).

def _compute_nrv_writedown(prev_qty: Decimal, prev_value_paise: int, nrv_per_unit_paise: int) -> Optional[dict]:
    """Pure math, no I/O. Returns None when NRV is already >= the current
    carrying value — no write-down needed, inventory stays at cost (the
    normal case)."""
    if prev_qty <= 0:
        return None
    new_value = _round_paise(prev_qty * nrv_per_unit_paise)
    if new_value >= prev_value_paise:
        return None
    new_avg = _round_paise(Decimal(new_value) / prev_qty)
    return {
        "quantity_delta": Decimal("0"),
        "unit_cost_paise": nrv_per_unit_paise,
        "value_delta_paise": new_value - prev_value_paise,  # negative
        "running_qty_units": prev_qty,
        "running_avg_cost_paise": new_avg,
        "running_value_paise": new_value,
    }


def record_nrv_writedown(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    nrv_per_unit_paise: int, reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[dict]:
    """Returns None if this item has no stock (nothing to write down) or if
    the supplied NRV is already >= the current average cost — both
    legitimate no-ops, never an error."""
    prev = _last_ledger_row(db, service_catalogue_id)
    if prev is None:
        return None
    prev_qty = Decimal(str(prev["running_qty_units"]))
    prev_value = int(prev["running_value_paise"])
    calc = _compute_nrv_writedown(prev_qty, prev_value, nrv_per_unit_paise)
    if calc is None:
        return None
    return _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type="nrv_writedown", calc=calc,
        source_type="nrv_writedown", source_id=None, reference_no=reference_no, created_by=created_by,
    )


def post_nrv_writedown_journal_entry(
    db, *, firm_id: str, client_id: str, movement_date: str, item_name: str,
    value_paise: int, reference_no: str, source_type: Optional[str] = None,
    source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Inventory Write-down Expense / Cr Inventory for the shortfall
    between cost and net realisable value (AS-2 / Ind AS 2 / ICDS-II)."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        try:
            writedown_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Write%down%")
        except ValueError:
            try:
                writedown_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Write%off%")
            except ValueError:
                try:
                    writedown_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Loss%")
                except ValueError:
                    writedown_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")

        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-NRV", narration=f"Inventory write-down to net realisable value — {item_name}",
            entry_type="Journal", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": writedown_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"NRV write-down — {item_name}"},
                {"account_id": inventory_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Inventory reduced to NRV — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_nrv_writedown_journal_entry skipped (%s): %s", reference_no, e)
        return None


def apply_nrv_writedown(
    db, *, firm_id: str, client_id: str, service_catalogue_id: str, movement_date: str,
    nrv_per_unit_paise: int, reference_no: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[dict]:
    """One call per manual NRV write-down (routers/inventory.py). Fail-soft
    — never raises. Returns None when there's no stock to write down or NRV
    is already >= cost (both legitimate no-ops, not failures)."""
    try:
        items = (
            db.table("service_catalogue").select("id, name")
            .eq("id", service_catalogue_id).limit(1).execute().data
        ) or []
        item_name = items[0].get("name") if items else "item"

        movement = record_nrv_writedown(
            db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
            movement_date=movement_date, nrv_per_unit_paise=nrv_per_unit_paise,
            reference_no=reference_no, created_by=created_by,
        )
        if not movement:
            return None
        write_down_paise = abs(int(movement["value_delta_paise"]))
        journal_ref = _movement_journal_ref("NRV", movement.get("id"))
        journal_id = post_nrv_writedown_journal_entry(
            db, firm_id=firm_id, client_id=client_id, movement_date=movement_date,
            item_name=item_name, value_paise=write_down_paise, reference_no=journal_ref,
            source_type="nrv_writedown", source_id=movement.get("id"), created_by=created_by,
        )
        _set_ledger_journal_entry_id(db, movement.get("id"), journal_id)
        return movement
    except Exception as e:
        _logger.error("apply_nrv_writedown failed for item %s: %s", service_catalogue_id, e, exc_info=True)
        return None

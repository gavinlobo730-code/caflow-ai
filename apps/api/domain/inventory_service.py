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
    """
    if quantity <= 0:
        raise ValueError("Stock-in quantity must be positive.")
    if total_cost_paise < 0:
        raise ValueError("Stock-in cost cannot be negative.")
    new_qty = prev_qty + quantity
    new_value = prev_value_paise + total_cost_paise
    new_avg = _round_paise(new_value / new_qty) if new_qty > 0 else 0
    unit_cost = _round_paise(total_cost_paise / quantity)
    return {
        "quantity_delta": quantity,
        "unit_cost_paise": unit_cost,
        "value_delta_paise": total_cost_paise,
        "running_qty_units": new_qty,
        "running_avg_cost_paise": new_avg,
        "running_value_paise": new_value,
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
    resp = (
        db.table("inventory_stock_ledger")
        .select("running_qty_units, running_value_paise, running_avg_cost_paise")
        .eq("service_catalogue_id", service_catalogue_id)
        .order("movement_date", desc=True)
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
    opening qty/cost are not both set."""
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
    calc = _compute_stock_in(Decimal("0"), 0, qty, int(opening_cost_paise))
    return _insert_and_cache(
        db, firm_id=firm_id, client_id=client_id, service_catalogue_id=service_catalogue_id,
        movement_date=movement_date, movement_type="opening", calc=calc,
        source_type=None, source_id=None, reference_no=None, created_by=created_by,
    )


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
    q = db.table("inventory_stock_ledger").select("*").eq("service_catalogue_id", service_catalogue_id)
    if start_date:
        q = q.gte("movement_date", start_date)
    if end_date:
        q = q.lte("movement_date", end_date)
    return q.order("movement_date").order("created_at").execute().data or []


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
            entry_type="COGS", source_type=source_type, source_id=source_id, created_by=created_by,
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
    value_paise: int, expense_account_id: Optional[str], reference_no: str,
    source_type: Optional[str] = None, source_id: Optional[str] = None, created_by: Optional[str] = None,
) -> Optional[str]:
    """Dr Inventory / Cr [the account this purchase-bill line's own journal
    entry debited] — a reclassification that moves a restocked line's value
    OUT of the expense account it landed on by default and INTO Inventory,
    so a purchased good is capitalised rather than expensed until it sells.
    Resolves the credit side with the SAME fallback order
    journal_for_purchase_bill itself uses (explicit expense_account_id →
    "%Purchase%" → "%Expense%"), so this always nets against whatever
    account actually received the debit."""
    if value_paise <= 0:
        return None
    try:
        from services.phase2_journal_service import phase2_journal_service

        inventory_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Inventor%", system_key="inventory")
        if expense_account_id:
            from_account_id = expense_account_id
        else:
            try:
                from_account_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Purchase%")
            except ValueError:
                from_account_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Expense%")
        return phase2_journal_service._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=movement_date,
            reference_no=f"{reference_no}-INV", narration=f"Capitalise purchase as inventory — {item_name}",
            entry_type="Inventory", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": inventory_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Inventory — {item_name}"},
                {"account_id": from_account_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Reclassify from expense — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_inventory_receipt_journal_entry skipped (%s): %s", reference_no, e)
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
            # A movement with no cost basis (Rs 0, "oversold") has nothing to
            # recognise as COGS yet — post_cogs_journal_entry's own value_paise
            # <= 0 guard skips it cleanly until a real average cost exists.
            journal_id = post_cogs_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=invoice.get("invoice_date"),
                item_name=item.get("name") or line.get("description") or "item",
                value_paise=abs(int(movement["value_delta_paise"])),
                reference_no=invoice.get("invoice_no") or invoice["id"],
                source_type="sales_invoice", source_id=invoice["id"], created_by=created_by,
            )
            _set_ledger_journal_entry_id(db, movement.get("id"), journal_id)
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
        reference_no = bill.get("bill_no") or bill.get("our_reference") or bill["id"]
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
            journal_id = post_inventory_receipt_journal_entry(
                db, firm_id=firm_id, client_id=client_id, movement_date=bill.get("bill_date"),
                item_name=item.get("name") or line.get("description") or "item",
                value_paise=int(movement["value_delta_paise"]), expense_account_id=line.get("expense_account_id"),
                reference_no=reference_no, source_type="purchase_bill", source_id=bill["id"], created_by=created_by,
            )
            _set_ledger_journal_entry_id(db, movement.get("id"), journal_id)
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
        cogs_ref = f"{invoice_no}-COGS"
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
            entry_type="Inventory", source_type=source_type, source_id=source_id, created_by=created_by,
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
            entry_type="Inventory", source_type=source_type, source_id=source_id, created_by=created_by,
            lines=[
                {"account_id": expense_id, "debit_paise": value_paise, "credit_paise": 0, "narration": f"Reclassify to expense — {item_name}"},
                {"account_id": inventory_id, "debit_paise": 0, "credit_paise": value_paise, "narration": f"Inventory — {item_name}"},
            ],
        )
    except Exception as e:
        _logger.warning("post_purchase_return_journal_entry skipped (%s): %s", reference_no, e)
        return None


def apply_credit_note_to_inventory(db, *, firm_id: str, client_id: str, credit_note: dict, created_by: Optional[str] = None) -> None:
    """Sales return: goods physically return to stock. Stock-IN at the
    returned line's own taxable value (same convention a purchase receipt
    uses to value its stock-in), plus a separate Dr Inventory / Cr COGS
    journal entry for the same total. Called AFTER the credit note is
    already issued and its own GL journal + AR sub-ledger application have
    committed (routers/credit_notes.py) — fail-soft, never raises."""
    try:
        cn_id = credit_note.get("id")
        cn_no = credit_note.get("credit_note_no") or cn_id
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
            value = int(line.get("taxable_amount_paise") or 0)
            if not item or not qty or float(qty) <= 0 or value <= 0:
                continue
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
            movement = record_stock_out(
                db, firm_id=firm_id, client_id=client_id, service_catalogue_id=mv["service_catalogue_id"],
                movement_date=today, quantity=qty, movement_type="purchase_reversal",
                source_type="purchase_bill", source_id=bill_id, reference_no=bill_reference, created_by=created_by,
            )
            if movement.get("id"):
                movement_ids.append(movement["id"])

        from services.phase2_journal_service import phase2_journal_service
        inv_ref = f"{bill_reference}-INV"
        jr = (
            db.table("journal_entries").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("reference_no", inv_ref).eq("is_posted", True)
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
                    narration=f"Cancellation of purchase bill {bill_reference} — inventory reversal",
                    created_by=created_by,
                )
                for mid in movement_ids:
                    _set_ledger_journal_entry_id(db, mid, reversal_id)
    except Exception as e:
        _logger.error("reverse_purchase_stock failed for bill %s: %s", bill_id, e, exc_info=True)

"""The purchase cycle before the bill — the reads, the writes, the match.

`domain/purchases/order_cycle.py` is the commercial chain and
`domain/purchases/three_way_match.py` is the comparison and the two statutes it
settles. This module fetches and writes; it decides nothing either of them
decides.

THREE THINGS IT WILL NOT DO
    * It posts NO journal. A purchase order commits the client to buy and a
      goods receipt records an arrival; the expense, the input tax credit and
      the payable all arise when the BILL is received, which is the existing
      path and is untouched.
    * It moves NO stock. INV-05a costs a receipt at the BILL's taxable value
      plus its s.17(5)-blocked tax, so moving stock here would cost it at a
      price the supplier has not yet invoiced — or move it twice.
    * It BLOCKS no bill. A supplier who short-ships or over-charges has still
      sent one, and the CA still has to book what arrived.

NOTE ON THE PROJECTIONS, which are written out at every call site rather than
shared through a module constant: `tests/test_backend_columns_exist_pg.py`
resolves NO variable names, so a `.select(_ORDER_COLS)` is invisible to it —
and invisible on four brand-new tables is where a typo survives longest.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_now
from domain.gst import compensation_cess
from domain.gst import discount as gst_discount
from domain.purchases import order_cycle as oc
from domain.purchases import three_way_match as twm
from domain.sales.line_tax import compute_line_gst

_logger = logging.getLogger("caflow.purchase_cycle")

PAGE = 1000


# ── Line arithmetic ──────────────────────────────────────────────────────────

def compute_lines(lines: list, *, is_inter_state: bool) -> tuple:
    """Priced order lines and the header totals, in integer paise.

    The SAME GST function the sales side and the invoice path use
    (`domain/sales/line_tax`, which `shared/gst-parity-vectors.json` pins to
    the browser mirror). A purchase order carries no CGST s.15(3)(a) discount
    of its own — a discount a SUPPLIER gives is on the supplier's invoice and
    is their document's particular, not the buyer's order — so the discount
    authority is called with no document-level figure and each line's own
    gross stands.
    """
    rows = list(lines or [])
    if not rows:
        return [], {"taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
                    "igst_paise": 0, "cess_paise": 0, "total_paise": 0}

    gross = [int(_num(ln.get("quantity"), Decimal(1))
                 * int(ln.get("rate_paise") or 0)) for ln in rows]
    try:
        discounts = gst_discount.apply_to_lines(
            [{"gross_paise": g} for g in gross])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    priced: list = []
    totals = {"taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
              "igst_paise": 0, "cess_paise": 0, "total_paise": 0}
    for i, (ln, d) in enumerate(zip(rows, discounts)):
        taxable = int(d["taxable_paise"])
        bps = int(round(float(ln.get("gst_rate_percent") or 0) * 100))
        cgst, sgst, igst = compute_line_gst(taxable, bps, is_inter_state)
        cess = compensation_cess.line_cess(
            taxable_paise=taxable,
            quantity=_num(ln.get("quantity"), Decimal(1)),
            cess_rate_bps=int(ln.get("cess_rate_bps") or 0),
            cess_specific_paise_per_unit=int(
                ln.get("cess_specific_paise_per_unit") or 0),
        ).cess_paise
        priced.append({
            "line_order": i,
            "description": str(ln.get("description") or "").strip(),
            "hsn_sac": ln.get("hsn_sac"),
            "quantity": str(_num(ln.get("quantity"), Decimal(1))),
            "unit": ln.get("unit") or "NOS",
            "rate_paise": int(ln.get("rate_paise") or 0),
            "gst_rate_percent": float(ln.get("gst_rate_percent") or 0),
            "is_service": bool(ln.get("is_service")),
            "service_catalogue_id": ln.get("service_catalogue_id"),
            "expense_account_id": ln.get("expense_account_id"),
            # CGST s.17(5), decided on the ORDER and carried to the bill.
            "itc_eligible": bool(ln.get("itc_eligible", True)),
            "blocked_credit_reason": ln.get("blocked_credit_reason"),
            "tds_applicable": bool(ln.get("tds_applicable")),
            "cess_rate_bps": int(ln.get("cess_rate_bps") or 0),
            "cess_specific_paise_per_unit": int(
                ln.get("cess_specific_paise_per_unit") or 0),
            "taxable_amount_paise": taxable,
            "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
            "line_cess_paise": cess,
        })
        totals["taxable_paise"] += taxable
        totals["cgst_paise"] += cgst
        totals["sgst_paise"] += sgst
        totals["igst_paise"] += igst
        totals["cess_paise"] += cess
    totals["total_paise"] = (totals["taxable_paise"] + totals["cgst_paise"]
                             + totals["sgst_paise"] + totals["igst_paise"]
                             + totals["cess_paise"])
    return priced, totals


def _num(value, default: Decimal) -> Decimal:
    if value is None or value == "":
        return default
    return Decimal(str(value))


# ── Reads ────────────────────────────────────────────────────────────────────

def list_orders(db, firm_id: str, client_id: str,
                only_open: bool = False) -> list:
    def q():
        b = (db.table("purchase_orders").select(
            "id, firm_id, client_id, vendor_id, document_no, document_date, "
            "expected_date, status, vendor_name, vendor_gstin, "
            "place_of_supply, is_inter_state, currency, taxable_paise, "
            "cgst_paise, sgst_paise, igst_paise, cess_paise, total_paise, "
            "notes, created_at, created_by, updated_at")
            .eq("firm_id", firm_id).eq("client_id", client_id))
        return b.in_("status", list(oc.ORDER_OPEN_STATUSES)) if only_open else b
    rows = fetch_all(q, key="id", label="purchase_cycle.orders")
    rows.sort(key=lambda r: (str(r.get("document_date") or ""),
                             str(r.get("document_no") or "")), reverse=True)
    return rows


def order_lines(db, firm_id: str, order_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("purchase_order_lines").select(
            "id, firm_id, client_id, order_id, line_order, description, "
            "hsn_sac, quantity, unit, rate_paise, gst_rate_percent, "
            "is_service, service_catalogue_id, expense_account_id, "
            "itc_eligible, blocked_credit_reason, tds_applicable, "
            "cess_rate_bps, cess_specific_paise_per_unit, "
            "taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, "
            "line_cess_paise, created_at")
        .eq("firm_id", firm_id).eq("order_id", order_id),
        key="id", label="purchase_cycle.order_lines")
    return sorted(rows, key=lambda r: (int(r.get("line_order") or 0),
                                       str(r.get("id"))))


def list_receipts(db, firm_id: str, client_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("goods_receipt_notes").select(
            "id, firm_id, client_id, vendor_id, order_id, document_no, "
            "received_on, status, objection_raised_on, objection_removed_on, "
            "vendor_name, vendor_challan_no, vendor_challan_date, "
            "transporter_name, vehicle_no, notes, created_at, created_by, "
            "updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="purchase_cycle.receipts")
    rows.sort(key=lambda r: (str(r.get("received_on") or ""),
                             str(r.get("document_no") or "")), reverse=True)
    return rows


def receipt_lines(db, firm_id: str, receipt_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("goods_receipt_lines").select(
            "id, firm_id, client_id, receipt_id, order_line_id, line_order, "
            "description, hsn_sac, quantity, unit, rejected_qty, "
            "rejection_reason, service_catalogue_id, created_at")
        .eq("firm_id", firm_id).eq("receipt_id", receipt_id),
        key="id", label="purchase_cycle.receipt_lines")
    return sorted(rows, key=lambda r: (int(r.get("line_order") or 0),
                                       str(r.get("id"))))


def _one_order(db, firm_id: str, order_id: str) -> dict:
    res = (db.table("purchase_orders").select(
        "id, firm_id, client_id, vendor_id, document_no, document_date, "
        "expected_date, status, vendor_name, vendor_gstin, place_of_supply, "
        "is_inter_state, currency, taxable_paise, cgst_paise, sgst_paise, "
        "igst_paise, cess_paise, total_paise, notes, created_at, created_by, "
        "updated_at")
        .eq("firm_id", firm_id).eq("id", order_id).limit(1).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404,
                            detail="That purchase order was not found.")
    return rows[0]


# ── What an order still has open ─────────────────────────────────────────────

def order_open_position(db, firm_id: str, order_id: str) -> dict:
    """Per order line: ordered, received, billed, and what is left of each.

    DERIVED, never stored. The received quantities come from goods-receipt
    lines read `.in_` over THIS order's line ids — never every receipt line
    for the firm, which is a read proportional to transaction volume — and
    each row's PARENT status is read too, because a cancelled receipt has
    delivered nothing.

    THE REJECTED QUANTITY IS TAKEN OFF. CGST s.16(2)(b) conditions the credit
    on goods RECEIVED and MSMED s.2(b) on goods ACCEPTED; stock rejected on
    arrival was received and not accepted, and what the order still owes is
    measured on what was kept.
    """
    order = _one_order(db, firm_id, order_id)
    lines = order_lines(db, firm_id, order_id)
    line_ids = [str(ln.get("id")) for ln in lines]

    received: dict = {}
    if line_ids:
        rows = fetch_all(
            lambda: db.table("goods_receipt_lines")
            .select("id, receipt_id, order_line_id, quantity, rejected_qty")
            .eq("firm_id", firm_id).in_("order_line_id", line_ids),
            key="id", label="purchase_cycle.received")
        receipt_ids = sorted({str(r.get("receipt_id")) for r in rows
                              if r.get("receipt_id")})
        live: set = set()
        if receipt_ids:
            for g in fetch_all(
                    lambda: db.table("goods_receipt_notes")
                    .select("id, status").eq("firm_id", firm_id)
                    .in_("id", receipt_ids),
                    key="id", label="purchase_cycle.received_parents"):
                if str(g.get("status")) != "cancelled":
                    live.add(str(g.get("id")))
        for r in rows:
            if str(r.get("receipt_id")) not in live:
                continue
            lid = str(r.get("order_line_id"))
            kept = (oc.to_decimal(r.get("quantity"))
                    - oc.to_decimal(r.get("rejected_qty")))
            received[lid] = oc.to_decimal(received.get(lid)) + kept

    billed: dict = {}
    if line_ids:
        # `purchase_bill_lines` CARRIES NO firm_id — it is scoped through its
        # parent bill, which is the one table in this module's reach that is.
        # So the tenant check happens at the PARENT read below, and it is the
        # same guarantee: a line survives only if its bill belongs to this
        # firm. Writing `.eq("firm_id", …)` here would name a column
        # production does not have, which is PGRST204 and NO read — the whole
        # figure silently nil.
        rows = fetch_all(
            lambda: db.table("purchase_bill_lines")
            .select("id, bill_id, purchase_order_line_id, quantity")
            .in_("purchase_order_line_id", line_ids),
            key="id", label="purchase_cycle.billed")
        bill_ids = sorted({str(r.get("bill_id")) for r in rows
                           if r.get("bill_id")})
        live_bills: set = set()
        if bill_ids:
            for b in fetch_all(
                    lambda: db.table("purchase_bills")
                    .select("id, status").eq("firm_id", firm_id)
                    .in_("id", bill_ids),
                    key="id", label="purchase_cycle.billed_parents"):
                if str(b.get("status")) != "cancelled":
                    live_bills.add(str(b.get("id")))
        for r in rows:
            if str(r.get("bill_id")) not in live_bills:
                continue
            lid = str(r.get("purchase_order_line_id"))
            billed[lid] = (oc.to_decimal(billed.get(lid))
                           + oc.to_decimal(r.get("quantity")))

    open_lines = oc.open_quantities(lines, received, billed)
    return {
        "order": order,
        "lines": [ln.as_dict() for ln in open_lines],
        "status_would_be": oc.order_status_for(open_lines,
                                               str(order.get("status") or "")),
        "posts_nothing": oc.POSTS_NOTHING,
    }


# ── The three-way match ──────────────────────────────────────────────────────

def match_bill(db, firm_id: str, bill_id: str) -> dict:
    """One bill against its purchase order and its goods receipts.

    # CA REVIEW REQUIRED — this reports. It blocks nothing and posts nothing.
    """
    res = (db.table("purchase_bills")
           .select("id, firm_id, client_id, vendor_id, bill_no, bill_date, "
                   "status, purchase_order_id")
           .eq("firm_id", firm_id).eq("id", bill_id).limit(1).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="That bill was not found.")
    bill = rows[0]
    order_id = bill.get("purchase_order_id")

    # Scoped through the bill, which was read above with the firm filter —
    # `purchase_bill_lines` has no firm_id of its own.
    bill_lines = fetch_all(
        lambda: db.table("purchase_bill_lines")
        .select("id, bill_id, description, quantity, rate_paise, "
                "purchase_order_line_id")
        .eq("bill_id", bill_id),
        key="id", label="purchase_cycle.match_bill_lines")
    for ln in bill_lines:
        ln["order_line_id"] = ln.get("purchase_order_line_id")

    o_lines: list = []
    received: dict = {}
    receipt_dates: list = []
    objection_removed = None
    if order_id:
        o_lines = order_lines(db, firm_id, str(order_id))
        position = order_open_position(db, firm_id, str(order_id))
        for ln in position["lines"]:
            received[ln["order_line_id"]] = Decimal(ln["received_qty"])
        for g in fetch_all(
                lambda: db.table("goods_receipt_notes")
                .select("id, received_on, status, objection_removed_on")
                .eq("firm_id", firm_id).eq("order_id", str(order_id)),
                key="id", label="purchase_cycle.match_receipts"):
            if str(g.get("status")) == "cancelled":
                continue
            receipt_dates.append(g.get("received_on"))
            # The LATEST removal stands: MSMED s.2(b)'s second limb runs the
            # clock from the day the objection was removed, and an order with
            # two objections is accepted when the last is settled.
            removed = g.get("objection_removed_on")
            if removed and (objection_removed is None
                            or str(removed) > str(objection_removed)):
                objection_removed = removed

    return twm.match(
        bill_id=str(bill_id), bill_lines=bill_lines, order_lines=o_lines,
        received_by_order_line=received, receipt_dates=receipt_dates,
        objection_removed_on=objection_removed).as_dict()


def acceptance_dates_by_bill(db, firm_id: str, client_id: str) -> dict:
    """bill id -> the MSMED s.2(b) day of acceptance, where one is held.

    Read once for the whole client rather than per bill, because
    `services/msme_43bh_service` walks every live bill and a per-bill lookup
    would be a Singapore-to-Mumbai round trip each.

    A bill with no purchase order, or an order with no receipt, is simply
    absent from the answer — `section_43b_h.compute` then falls back to the
    bill date and says so on that bill.
    """
    bills = fetch_all(
        lambda: db.table("purchase_bills").select("id, purchase_order_id")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="purchase_cycle.acceptance_bills")
    by_order: dict = {}
    for b in bills:
        oid = b.get("purchase_order_id")
        if oid:
            by_order.setdefault(str(oid), []).append(str(b.get("id")))
    if not by_order:
        return {}

    dates: dict = {}
    removals: dict = {}
    for g in fetch_all(
            lambda: db.table("goods_receipt_notes")
            .select("id, order_id, received_on, status, objection_removed_on")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("order_id", sorted(by_order)),
            key="id", label="purchase_cycle.acceptance_receipts"):
        if str(g.get("status")) == "cancelled":
            continue
        oid = str(g.get("order_id"))
        if g.get("received_on"):
            dates.setdefault(oid, []).append(str(g["received_on"])[:10])
        removed = g.get("objection_removed_on")
        if removed and (oid not in removals
                        or str(removed) > str(removals[oid])):
            removals[oid] = str(removed)[:10]

    out: dict = {}
    for oid, bill_ids in by_order.items():
        day, _why = twm.acceptance_date(dates.get(oid, []), removals.get(oid))
        if day:
            for bid in bill_ids:
                out[bid] = day
    return out


# ── Writes ───────────────────────────────────────────────────────────────────

def _refuse_duplicate(db, table: str, firm_id: str, client_id: str,
                      document_no: str, exclude_id: Optional[str]) -> None:
    wanted = (document_no or "").strip().upper()
    if table == "purchase_orders":
        res = (db.table("purchase_orders").select("id, document_no")
               .eq("firm_id", firm_id).eq("client_id", client_id).execute())
    else:
        res = (db.table("goods_receipt_notes").select("id, document_no")
               .eq("firm_id", firm_id).eq("client_id", client_id).execute())
    for row in res.data or []:
        if str(row.get("document_no") or "").strip().upper() != wanted:
            continue
        if exclude_id and str(row.get("id")) == str(exclude_id):
            continue
        raise HTTPException(
            status_code=409,
            detail=(f"{document_no} is already used by another document for "
                    f"this client. A serial number identifies one document."))


def create_order(db, firm_id: str, payload: dict,
                 actor_id: Optional[str] = None) -> dict:
    client_id = str(payload["client_id"])
    _refuse_duplicate(db, "purchase_orders", firm_id, client_id,
                      payload["document_no"], None)
    priced, totals = compute_lines(
        payload.get("lines") or [],
        is_inter_state=bool(payload.get("is_inter_state")))
    now = ist_now().isoformat()
    row = (db.table("purchase_orders").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "vendor_id": str(payload["vendor_id"]),
        "document_no": str(payload["document_no"]).strip(),
        "document_date": str(payload["document_date"]),
        "expected_date": payload.get("expected_date"),
        "status": "draft",
        "vendor_name": payload.get("vendor_name"),
        "vendor_gstin": payload.get("vendor_gstin"),
        "place_of_supply": payload.get("place_of_supply"),
        "is_inter_state": bool(payload.get("is_inter_state")),
        "currency": payload.get("currency") or "INR",
        "taxable_paise": totals["taxable_paise"],
        "cgst_paise": totals["cgst_paise"],
        "sgst_paise": totals["sgst_paise"],
        "igst_paise": totals["igst_paise"],
        "cess_paise": totals["cess_paise"],
        "total_paise": totals["total_paise"],
        "notes": payload.get("notes"),
        "created_by": actor_id,
        "created_at": now,
        "updated_at": now,
    }).execute().data or [{}])[0]
    for ln in priced:
        db.table("purchase_order_lines").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "order_id": str(row.get("id")),
            "line_order": ln["line_order"],
            "description": ln["description"],
            "hsn_sac": ln["hsn_sac"],
            "quantity": ln["quantity"],
            "unit": ln["unit"],
            "rate_paise": ln["rate_paise"],
            "gst_rate_percent": ln["gst_rate_percent"],
            "is_service": ln["is_service"],
            "service_catalogue_id": ln["service_catalogue_id"],
            "expense_account_id": ln["expense_account_id"],
            "itc_eligible": ln["itc_eligible"],
            "blocked_credit_reason": ln["blocked_credit_reason"],
            "tds_applicable": ln["tds_applicable"],
            "cess_rate_bps": ln["cess_rate_bps"],
            "cess_specific_paise_per_unit": ln["cess_specific_paise_per_unit"],
            "taxable_amount_paise": ln["taxable_amount_paise"],
            "cgst_paise": ln["cgst_paise"],
            "sgst_paise": ln["sgst_paise"],
            "igst_paise": ln["igst_paise"],
            "line_cess_paise": ln["line_cess_paise"],
            "created_at": now,
        }).execute()
    return row


def create_receipt(db, firm_id: str, payload: dict,
                   actor_id: Optional[str] = None) -> dict:
    """Record that goods arrived.

    THE OVER-RECEIPT REFUSAL IS THE ONE THING THIS PATH BLOCKS. Goods on the
    premises in excess of what was ordered mean the ORDER is wrong, and
    clamping would take the ordered quantity in and lose the rest with no
    record of stock that physically exists.
    """
    client_id = str(payload["client_id"])
    _refuse_duplicate(db, "goods_receipt_notes", firm_id, client_id,
                      payload["document_no"], None)
    lines = list(payload.get("lines") or [])
    order_id = payload.get("order_id")
    problems = _refuse_over_receipt(db, firm_id, order_id, lines)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))

    now = ist_now().isoformat()
    row = (db.table("goods_receipt_notes").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "vendor_id": str(payload["vendor_id"]),
        "order_id": order_id,
        "document_no": str(payload["document_no"]).strip(),
        "received_on": str(payload["received_on"]),
        "status": "draft",
        "objection_raised_on": payload.get("objection_raised_on"),
        "objection_removed_on": payload.get("objection_removed_on"),
        "vendor_name": payload.get("vendor_name"),
        "vendor_challan_no": payload.get("vendor_challan_no"),
        "vendor_challan_date": payload.get("vendor_challan_date"),
        "transporter_name": payload.get("transporter_name"),
        "vehicle_no": payload.get("vehicle_no"),
        "notes": payload.get("notes"),
        "created_by": actor_id,
        "created_at": now,
        "updated_at": now,
    }).execute().data or [{}])[0]
    for i, ln in enumerate(lines):
        db.table("goods_receipt_lines").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "receipt_id": str(row.get("id")),
            "order_line_id": ln.get("order_line_id"),
            "line_order": i,
            "description": str(ln.get("description") or "").strip(),
            "hsn_sac": ln.get("hsn_sac"),
            "quantity": str(_num(ln.get("quantity"), Decimal(1))),
            "unit": ln.get("unit") or "NOS",
            "rejected_qty": str(_num(ln.get("rejected_qty"), Decimal(0))),
            "rejection_reason": ln.get("rejection_reason"),
            "service_catalogue_id": ln.get("service_catalogue_id"),
            "created_at": now,
        }).execute()
    _resettle_order_status(db, firm_id, order_id)
    return row


def _refuse_over_receipt(db, firm_id: str, order_id: Optional[str],
                         lines: list) -> list:
    if not order_id:
        return []
    position = order_open_position(db, firm_id, str(order_id))
    by_id = {str(ln["order_line_id"]): ln for ln in position["lines"]}
    problems: list = []
    for ln in lines:
        lid = str(ln.get("order_line_id") or "")
        if not lid:
            continue
        row = by_id.get(lid)
        if row is None:
            problems.append(
                f"{ln.get('description')}: that order line does not belong to "
                f"this order.")
            continue
        kept = (_num(ln.get("quantity"), Decimal(1))
                - _num(ln.get("rejected_qty"), Decimal(0)))
        problem = oc.over_receipt(
            oc.OpenLine(order_line_id=lid, description=row["description"],
                        ordered_qty=Decimal(row["ordered_qty"]),
                        received_qty=Decimal(row["received_qty"]),
                        billed_qty=Decimal(row["billed_qty"])),
            kept)
        if problem:
            problems.append(problem)
    return problems


def _resettle_order_status(db, firm_id: str, order_id: Optional[str]) -> None:
    if not order_id:
        return
    position = order_open_position(db, firm_id, str(order_id))
    current = str(position["order"].get("status") or "")
    wanted = position["status_would_be"]
    if wanted != current:
        (db.table("purchase_orders")
         .update({"status": wanted, "updated_at": ist_now().isoformat()})
         .eq("firm_id", firm_id).eq("id", str(order_id)).execute())


def update_order(db, firm_id: str, order_id: str, patch: dict) -> dict:
    """Amend a purchase order.

    AN ORDER WITH A RECEIPT AGAINST IT KEEPS ITS LINES: re-pricing them would
    change the quantity a receipt was already checked against for
    over-receipt, and deleting a line out from under a receipt leaves the
    receipt pointing at nothing.
    """
    row = _one_order(db, firm_id, order_id)
    if str(row.get("status")) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="A cancelled purchase order cannot be amended.")
    fields = {k: v for k, v in patch.items() if v is not None and k != "lines"}
    lines = patch.get("lines")
    if lines is not None:
        position = order_open_position(db, firm_id, order_id)
        if any(ln["received_qty"] != "0.000" for ln in position["lines"]):
            raise HTTPException(
                status_code=409,
                detail=("This order already has a goods receipt against it, so "
                        "its lines cannot be re-priced — a receipt was checked "
                        "for over-receipt against the quantity they carry."))
        if not lines:
            raise HTTPException(status_code=422,
                                detail="A purchase order needs at least one line.")
        priced, totals = compute_lines(
            lines,
            is_inter_state=bool(fields.get("is_inter_state",
                                           row.get("is_inter_state"))))
        fields.update(totals)
        now = ist_now().isoformat()
        for old in order_lines(db, firm_id, order_id):
            (db.table("purchase_order_lines").delete()
             .eq("firm_id", firm_id).eq("id", str(old.get("id"))).execute())
        for ln in priced:
            db.table("purchase_order_lines").insert({
                "firm_id": firm_id,
                "client_id": str(row["client_id"]),
                "order_id": order_id,
                "line_order": ln["line_order"],
                "description": ln["description"],
                "hsn_sac": ln["hsn_sac"],
                "quantity": ln["quantity"],
                "unit": ln["unit"],
                "rate_paise": ln["rate_paise"],
                "gst_rate_percent": ln["gst_rate_percent"],
                "is_service": ln["is_service"],
                "service_catalogue_id": ln["service_catalogue_id"],
                "expense_account_id": ln["expense_account_id"],
                "itc_eligible": ln["itc_eligible"],
                "blocked_credit_reason": ln["blocked_credit_reason"],
                "tds_applicable": ln["tds_applicable"],
                "cess_rate_bps": ln["cess_rate_bps"],
                "cess_specific_paise_per_unit": ln["cess_specific_paise_per_unit"],
                "taxable_amount_paise": ln["taxable_amount_paise"],
                "cgst_paise": ln["cgst_paise"],
                "sgst_paise": ln["sgst_paise"],
                "igst_paise": ln["igst_paise"],
                "line_cess_paise": ln["line_cess_paise"],
                "created_at": now,
            }).execute()
    if fields.get("document_no"):
        _refuse_duplicate(db, "purchase_orders", firm_id,
                          str(row["client_id"]), fields["document_no"],
                          order_id)
    fields["updated_at"] = ist_now().isoformat()
    (db.table("purchase_orders").update(fields)
     .eq("firm_id", firm_id).eq("id", order_id).execute())
    return {**row, **fields}


def update_receipt(db, firm_id: str, receipt_id: str, patch: dict) -> dict:
    """Amend a goods receipt — including recording an objection and its removal.

    THE OBJECTION IS THE ONE EDIT THAT MOVES A STATUTORY DATE: MSMED s.2(b)'s
    Explanation runs the fifteen days from the day the objection was removed
    rather than the day of delivery, which is LATER — so it lengthens the
    period and can only remove a s.43B(h) disallowance, never create one.
    """
    res = (db.table("goods_receipt_notes")
           .select("id, firm_id, client_id, vendor_id, order_id, document_no, "
                   "received_on, status, objection_raised_on, "
                   "objection_removed_on, vendor_name, vendor_challan_no, "
                   "vendor_challan_date, transporter_name, vehicle_no, notes, "
                   "created_at, created_by, updated_at")
           .eq("firm_id", firm_id).eq("id", receipt_id).limit(1).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404,
                            detail="That goods receipt was not found.")
    row = rows[0]
    fields = {k: v for k, v in patch.items() if v is not None and k != "lines"}
    removed = fields.get("objection_removed_on")
    raised = fields.get("objection_raised_on") or row.get("objection_raised_on")
    if removed and not raised:
        raise HTTPException(
            status_code=422,
            detail=("MSMED s.2(b)'s Explanation runs the clock from the day an "
                    "objection was REMOVED, so there has to be an objection. "
                    "Record when it was raised."))
    if removed and raised and str(removed) < str(raised):
        raise HTTPException(
            status_code=422,
            detail="An objection cannot be removed before it was raised.")
    if fields.get("document_no"):
        _refuse_duplicate(db, "goods_receipt_notes", firm_id,
                          str(row["client_id"]), fields["document_no"],
                          receipt_id)
    fields["updated_at"] = ist_now().isoformat()
    (db.table("goods_receipt_notes").update(fields)
     .eq("firm_id", firm_id).eq("id", receipt_id).execute())
    _resettle_order_status(db, firm_id, row.get("order_id"))
    return {**row, **fields}

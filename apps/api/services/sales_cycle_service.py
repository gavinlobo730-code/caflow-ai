"""The sales cycle before the tax invoice — the reads, the writes, the chain.

`domain/sales/order_cycle.py` is the commercial rule and
`domain/gst/delivery_challan.py` is CGST Rule 55. This module fetches and
writes; it decides nothing either of them decides.

THREE THINGS THIS MODULE WILL NOT DO, AND THEY ARE THE POINT
    * It posts NO journal. No revenue is earned on an offer and no receivable
      exists (`_create_journal` is not imported and a test asserts that).
    * It touches NO stock. Goods leaving on a delivery challan have not been
      sold, so `inventory_stock_ledger` must not move.
    * It declares NOTHING on a return. GSTR-1 is built from documents that
      make a supply, and none of these does.

WHAT IT DOES DECIDE IS WHOSE DOCUMENT IT IS
    Every read and every write carries `.eq("firm_id", …)`. The service-role
    key bypasses RLS, so that filter is the primary isolation control
    (CLAUDE.md, "Tenancy and access") — not a narrowing convenience.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_now, ist_today
from domain.gst import compensation_cess
from domain.gst import delivery_challan as dc
from domain.gst import discount as gst_discount
from domain.sales import order_cycle as oc
from domain.sales.line_tax import compute_line_gst

_logger = logging.getLogger("caflow.sales_cycle")

PAGE = 1000

# NOTE ON THE PROJECTIONS BELOW, which are long and are written out at every
# call site rather than shared through a module constant.
#
# `tests/test_backend_columns_exist_pg.py` checks every select list against the
# real schema, and it resolves NO variable names — a `.select(_QUOTE_COLS)` is
# invisible to it, and invisible on SIX BRAND-NEW TABLES is where a typo
# survives longest. The first draft of this module did share them, and the
# guard's budget went up by fifteen in one commit. Verbose and checked beats
# tidy and unchecked.


# ── Line arithmetic ──────────────────────────────────────────────────────────

def compute_lines(lines: list, *, is_inter_state: bool,
                  document_percent_bps: Optional[int] = None,
                  document_amount_paise: Optional[int] = None) -> tuple:
    """Priced lines and the document totals, in integer paise.

    ONE implementation, reached through the two authorities the invoice path
    already uses: `domain/gst/discount.apply_to_lines` for CGST s.15(3)(a) —
    including the pro-rata allocation of a document-level discount, which
    cannot be done line by line because GST is charged at each line's own rate
    — and `domain/gst/compensation_cess.line_cess` for the Compensation Act's
    two limbs. The GST heads come from `domain/sales/line_tax`, which is the
    function `shared/gst-parity-vectors.json` pins to the browser.
    """
    rows = list(lines or [])
    if not rows:
        return [], {"taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
                    "igst_paise": 0, "cess_paise": 0, "total_paise": 0}

    # GROSS is quantity x rate, and the Decimal is the quantity's — the
    # invoice path does the same and for the same reason: a quantity is
    # NUMERIC(10,3) and `2.5 * 10000` in binary floating point is not the
    # integer paise this boundary carries.
    gross = [int(_num(ln.get("quantity"), Decimal(1))
                 * int(ln.get("rate_paise") or 0)) for ln in rows]
    try:
        discounts = gst_discount.apply_to_lines(
            [{"gross_paise": g,
              "discount_percent_bps": ln.get("discount_percent_bps"),
              "discount_paise": ln.get("discount_paise")}
             for g, ln in zip(gross, rows)],
            document_percent_bps=document_percent_bps,
            document_amount_paise=document_amount_paise,
        )
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
            "discount_percent_bps": d.get("discount_percent_bps"),
            "discount_paise": int(d["discount_paise"]),
            "cess_rate_bps": int(ln.get("cess_rate_bps") or 0),
            "cess_specific_paise_per_unit": int(
                ln.get("cess_specific_paise_per_unit") or 0),
            "taxable_amount_paise": taxable,
            "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
            "line_cess_paise": cess,
            "quantity_is_provisional": bool(ln.get("quantity_is_provisional")),
            "order_line_id": ln.get("order_line_id"),
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

def list_quotations(db, firm_id: str, client_id: str,
                    kind: Optional[str] = None) -> list:
    def q():
        b = (db.table("sales_quotations").select(
            "id, firm_id, client_id, customer_id, kind, document_no, "
            "document_date, valid_until, status, customer_name, "
            "customer_gstin, place_of_supply, supply_state_code, "
            "is_inter_state, currency, discount_percent_bps, discount_paise, "
            "taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, converted_to_order_id, "
            "converted_to_invoice_id, notes, created_at, created_by, updated_at")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        return b.eq("kind", kind) if kind else b
    rows = fetch_all(q, key="id", label="sales_cycle.quotations")
    rows.sort(key=lambda r: (str(r.get("document_date") or ""),
                             str(r.get("document_no") or "")), reverse=True)
    today = ist_today().isoformat()
    for r in rows:
        # Derived on every read rather than stored: a quotation does not become
        # expired by anyone DOING anything, so a stored status would need a
        # nightly job and would be wrong between runs.
        r["is_expired"] = oc.is_expired(r.get("valid_until"), today)
        r["title"] = oc.KIND_TITLES.get(str(r.get("kind")), "")
    return rows


def quotation_lines(db, firm_id: str, quotation_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("sales_quotation_lines").select(
            "id, firm_id, client_id, quotation_id, line_order, "
            "description, hsn_sac, quantity, unit, rate_paise, "
            "gst_rate_percent, is_service, service_catalogue_id, "
            "discount_percent_bps, discount_paise, cess_rate_bps, "
            "cess_specific_paise_per_unit, taxable_amount_paise, cgst_paise, "
            "sgst_paise, igst_paise, line_cess_paise, created_at")
        .eq("firm_id", firm_id).eq("quotation_id", quotation_id),
        key="id", label="sales_cycle.quotation_lines")
    return sorted(rows, key=lambda r: (int(r.get("line_order") or 0),
                                       str(r.get("id"))))


def list_orders(db, firm_id: str, client_id: str,
                only_open: bool = False) -> list:
    def q():
        b = (db.table("sales_orders").select(
            "id, firm_id, client_id, customer_id, document_no, "
            "document_date, customer_po_no, customer_po_date, "
            "expected_delivery_date, status, quotation_id, customer_name, "
            "customer_gstin, place_of_supply, supply_state_code, "
            "is_inter_state, currency, discount_percent_bps, discount_paise, "
            "taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, notes, created_at, "
            "created_by, updated_at")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        return b.in_("status", list(oc.ORDER_OPEN_STATUSES)) if only_open else b
    rows = fetch_all(q, key="id", label="sales_cycle.orders")
    rows.sort(key=lambda r: (str(r.get("document_date") or ""),
                             str(r.get("document_no") or "")), reverse=True)
    return rows


def order_lines(db, firm_id: str, order_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("sales_order_lines").select(
            "id, firm_id, client_id, order_id, line_order, "
            "description, hsn_sac, quantity, unit, rate_paise, "
            "gst_rate_percent, is_service, service_catalogue_id, "
            "discount_percent_bps, discount_paise, cess_rate_bps, "
            "cess_specific_paise_per_unit, taxable_amount_paise, cgst_paise, "
            "sgst_paise, igst_paise, line_cess_paise, created_at")
        .eq("firm_id", firm_id).eq("order_id", order_id),
        key="id", label="sales_cycle.order_lines")
    return sorted(rows, key=lambda r: (int(r.get("line_order") or 0),
                                       str(r.get("id"))))


def list_challans(db, firm_id: str, client_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("delivery_challans").select(
            "id, firm_id, client_id, customer_id, vendor_id, "
            "document_no, document_date, reason, status, goods_kind, "
            "received_back_on, extended_to, sales_invoice_id, order_id, "
            "consignee_name, consignee_gstin, consignee_address, "
            "transporter_name, transporter_id, vehicle_no, place_of_supply, "
            "is_inter_state, taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, notes, created_at, "
            "created_by, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="sales_cycle.challans")
    rows.sort(key=lambda r: (str(r.get("document_date") or ""),
                             str(r.get("document_no") or "")), reverse=True)
    today = ist_today().isoformat()
    for r in rows:
        r["reason_label"] = dc.REASON_LABELS.get(str(r.get("reason")), "")
        r["clock"] = dc.deemed_supply_clock(
            reason=str(r.get("reason") or ""),
            challan_date=r.get("document_date"),
            as_at=today,
            goods_kind=r.get("goods_kind"),
            received_back_on=r.get("received_back_on"),
            extended_to=r.get("extended_to"),
        ).as_dict()
    return rows


def challan_lines(db, firm_id: str, challan_id: str) -> list:
    rows = fetch_all(
        lambda: db.table("delivery_challan_lines").select(
            "id, firm_id, client_id, challan_id, order_line_id, "
            "line_order, description, hsn_sac, quantity, unit, "
            "quantity_is_provisional, rate_paise, gst_rate_percent, "
            "is_service, service_catalogue_id, taxable_amount_paise, "
            "cgst_paise, sgst_paise, igst_paise, line_cess_paise, created_at")
        .eq("firm_id", firm_id).eq("challan_id", challan_id),
        key="id", label="sales_cycle.challan_lines")
    return sorted(rows, key=lambda r: (int(r.get("line_order") or 0),
                                       str(r.get("id"))))


# ── What an order still has open ─────────────────────────────────────────────

def order_open_position(db, firm_id: str, order_id: str) -> dict:
    """Per order line: ordered, delivered, invoiced, and what is left of each.

    DERIVED, never stored — migration 278's reasoning applied to a quantity: a
    stored delivered figure is wrong the moment a challan is cancelled.

    WHAT CROSSES THE WIRE IS PROPORTIONAL TO THE ANSWER. The delivered
    quantities are read by `.in_("order_line_id", …)` over THIS order's line
    ids, and the challans behind them by `.in_("id", …)` over the ids those
    rows named — never "every challan line for the firm", which is a read
    proportional to transaction volume and is exactly what CLAUDE.md's
    reporting rule forbids. An order has tens of lines; a client has thousands
    of challan lines.

    THE PARENT'S STATUS IS READ, not just the line. A cancelled challan has
    delivered nothing, and a query that forgot that would show a fully
    delivered order for goods that never left.
    """
    order = _one(db, "sales_orders", firm_id, order_id,
                 "sales order")
    lines = order_lines(db, firm_id, order_id)
    line_ids = [str(ln.get("id")) for ln in lines]

    delivered: dict = {}
    if line_ids:
        rows = fetch_all(
            lambda: db.table("delivery_challan_lines")
            .select("id, challan_id, order_line_id, quantity")
            .eq("firm_id", firm_id).in_("order_line_id", line_ids),
            key="id", label="sales_cycle.delivered")
        challan_ids = sorted({str(r.get("challan_id")) for r in rows
                              if r.get("challan_id")})
        live: set = set()
        if challan_ids:
            for c in fetch_all(
                    lambda: db.table("delivery_challans")
                    .select("id, status").eq("firm_id", firm_id)
                    .in_("id", challan_ids),
                    key="id", label="sales_cycle.delivered_parents"):
                if str(c.get("status")) != "cancelled":
                    live.add(str(c.get("id")))
        for r in rows:
            if str(r.get("challan_id")) not in live:
                continue
            lid = str(r.get("order_line_id"))
            delivered[lid] = (oc.to_decimal(delivered.get(lid))
                              + oc.to_decimal(r.get("quantity")))

    # `invoiced` is deliberately EMPTY and says so — see the constant below.
    open_lines = oc.open_quantities(lines, delivered, {})
    return {
        "order": order,
        "lines": [ln.as_dict() for ln in open_lines],
        "status_would_be": oc.order_status_for(open_lines,
                                               str(order.get("status") or "")),
        "gaps": [INVOICED_QUANTITY_IS_NOT_LINKED],
    }


#: Why `invoiced_qty` is always zero today, said out loud rather than left to
#: be discovered. An invoice line has no `sales_order_line_id`, so the only way
#: to pair the two would be to match on description and rate — a guess, and one
#: that silently under-bills an order whose invoice line was reworded. The
#: column is a migration; naming the gap costs nothing and a wrong figure costs
#: the client an unbilled delivery.
INVOICED_QUANTITY_IS_NOT_LINKED = (
    "What has been INVOICED against this order is not tracked: an invoice line "
    "carries no link back to an order line, so the figure shown is zero rather "
    "than a guess made by matching descriptions. What has been DELIVERED is "
    "real — a delivery challan line names the order line it delivers."
)


# ── Writes ───────────────────────────────────────────────────────────────────

def _one(db, table: str, firm_id: str, row_id: str, what: str) -> dict:
    """One row by id, scoped to the firm.

    Three literal branches rather than one parameterised read, for the reason
    at the top of this module: a `db.table(name).select(cols)` with either as a
    variable is invisible to the column guard.
    """
    if table == "sales_quotations":
        res = (db.table("sales_quotations").select(
            "id, firm_id, client_id, customer_id, kind, document_no, "
            "document_date, valid_until, status, customer_name, "
            "customer_gstin, place_of_supply, supply_state_code, "
            "is_inter_state, currency, discount_percent_bps, discount_paise, "
            "taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, converted_to_order_id, "
            "converted_to_invoice_id, notes, created_at, created_by, updated_at")
               .eq("firm_id", firm_id).eq("id", row_id).limit(1).execute())
    elif table == "sales_orders":
        res = (db.table("sales_orders").select(
            "id, firm_id, client_id, customer_id, document_no, "
            "document_date, customer_po_no, customer_po_date, "
            "expected_delivery_date, status, quotation_id, customer_name, "
            "customer_gstin, place_of_supply, supply_state_code, "
            "is_inter_state, currency, discount_percent_bps, discount_paise, "
            "taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, notes, created_at, "
            "created_by, updated_at")
               .eq("firm_id", firm_id).eq("id", row_id).limit(1).execute())
    else:
        res = (db.table("delivery_challans").select(
            "id, firm_id, client_id, customer_id, vendor_id, "
            "document_no, document_date, reason, status, goods_kind, "
            "received_back_on, extended_to, sales_invoice_id, order_id, "
            "consignee_name, consignee_gstin, consignee_address, "
            "transporter_name, transporter_id, vehicle_no, place_of_supply, "
            "is_inter_state, taxable_paise, cgst_paise, sgst_paise, "
            "igst_paise, cess_paise, total_paise, notes, created_at, "
            "created_by, updated_at")
               .eq("firm_id", firm_id).eq("id", row_id).limit(1).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"That {what} was not found.")
    return rows[0]


def _refuse_duplicate(db, table: str, firm_id: str, client_id: str,
                      document_no: str, kind: Optional[str],
                      exclude_id: Optional[str]) -> None:
    """One number per client per kind. Two documents bearing one number is the
    failure a serial number exists to prevent, and the unique index enforces
    it — this turns the 23505 into a sentence naming the other document."""
    wanted = (document_no or "").strip().upper()
    # The firm filter is here even though `client_id` already belongs to
    # exactly one firm: CLAUDE.md's rule is "never write a query that omits
    # it", not "omit it where you can argue it is redundant", and the
    # service-role key bypasses RLS so this filter is the control itself.
    if table == "sales_quotations":
        res = (db.table("sales_quotations").select("id, document_no, kind")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("kind", kind or "").execute())
    elif table == "sales_orders":
        res = (db.table("sales_orders").select("id, document_no")
               .eq("firm_id", firm_id).eq("client_id", client_id).execute())
    else:
        res = (db.table("delivery_challans").select("id, document_no")
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


def create_quotation(db, firm_id: str, payload: dict,
                     actor_id: Optional[str] = None) -> dict:
    client_id = str(payload["client_id"])
    _refuse_duplicate(db, "sales_quotations", firm_id, client_id,
                      payload["document_no"], payload.get("kind"), None)
    priced, totals = compute_lines(
        payload.get("lines") or [],
        is_inter_state=bool(payload.get("is_inter_state")),
        document_percent_bps=payload.get("discount_percent_bps"),
        document_amount_paise=payload.get("discount_paise"))
    now = ist_now().isoformat()
    # The payload is written INLINE rather than built above and inserted by
    # name: the column guard resolves no variable, and an insert it cannot
    # read is a column it cannot check on a table this new.
    row = (db.table("sales_quotations").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "customer_id": str(payload["customer_id"]),
        "kind": str(payload.get("kind") or oc.KIND_QUOTATION),
        "document_no": str(payload["document_no"]).strip(),
        "document_date": str(payload["document_date"]),
        "valid_until": payload.get("valid_until"),
        "status": "draft",
        "customer_name": payload.get("customer_name"),
        "customer_gstin": payload.get("customer_gstin"),
        "place_of_supply": payload.get("place_of_supply"),
        "supply_state_code": payload.get("supply_state_code"),
        "is_inter_state": bool(payload.get("is_inter_state")),
        "currency": payload.get("currency") or "INR",
        "discount_percent_bps": payload.get("discount_percent_bps"),
        "discount_paise": payload.get("discount_paise"),
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
    _write_quotation_lines(db, firm_id, client_id, str(row.get("id")), priced)
    return row


def _write_quotation_lines(db, firm_id: str, client_id: str,
                           quotation_id: str, priced: list) -> None:
    now = ist_now().isoformat()
    for ln in priced:
        db.table("sales_quotation_lines").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "quotation_id": quotation_id,
            "line_order": ln["line_order"],
            "description": ln["description"],
            "hsn_sac": ln["hsn_sac"],
            "quantity": ln["quantity"],
            "unit": ln["unit"],
            "rate_paise": ln["rate_paise"],
            "gst_rate_percent": ln["gst_rate_percent"],
            "is_service": ln["is_service"],
            "service_catalogue_id": ln["service_catalogue_id"],
            "discount_percent_bps": ln["discount_percent_bps"],
            "discount_paise": ln["discount_paise"],
            "cess_rate_bps": ln["cess_rate_bps"],
            "cess_specific_paise_per_unit": ln["cess_specific_paise_per_unit"],
            "taxable_amount_paise": ln["taxable_amount_paise"],
            "cgst_paise": ln["cgst_paise"],
            "sgst_paise": ln["sgst_paise"],
            "igst_paise": ln["igst_paise"],
            "line_cess_paise": ln["line_cess_paise"],
            "created_at": now,
        }).execute()


def create_order(db, firm_id: str, payload: dict,
                 actor_id: Optional[str] = None) -> dict:
    client_id = str(payload["client_id"])
    _refuse_duplicate(db, "sales_orders", firm_id, client_id,
                      payload["document_no"], None, None)
    priced, totals = compute_lines(
        payload.get("lines") or [],
        is_inter_state=bool(payload.get("is_inter_state")),
        document_percent_bps=payload.get("discount_percent_bps"),
        document_amount_paise=payload.get("discount_paise"))
    now = ist_now().isoformat()
    # The payload is written INLINE rather than built above and inserted by
    # name: the column guard resolves no variable, and an insert it cannot
    # read is a column it cannot check on a table this new.
    row = (db.table("sales_orders").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "customer_id": str(payload["customer_id"]),
        "document_no": str(payload["document_no"]).strip(),
        "document_date": str(payload["document_date"]),
        "customer_po_no": payload.get("customer_po_no"),
        "customer_po_date": payload.get("customer_po_date"),
        "expected_delivery_date": payload.get("expected_delivery_date"),
        "status": "draft",
        "quotation_id": payload.get("quotation_id"),
        "customer_name": payload.get("customer_name"),
        "customer_gstin": payload.get("customer_gstin"),
        "place_of_supply": payload.get("place_of_supply"),
        "supply_state_code": payload.get("supply_state_code"),
        "is_inter_state": bool(payload.get("is_inter_state")),
        "currency": payload.get("currency") or "INR",
        "discount_percent_bps": payload.get("discount_percent_bps"),
        "discount_paise": payload.get("discount_paise"),
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
        db.table("sales_order_lines").insert({
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
            "discount_percent_bps": ln["discount_percent_bps"],
            "discount_paise": ln["discount_paise"],
            "cess_rate_bps": ln["cess_rate_bps"],
            "cess_specific_paise_per_unit": ln["cess_specific_paise_per_unit"],
            "taxable_amount_paise": ln["taxable_amount_paise"],
            "cgst_paise": ln["cgst_paise"],
            "sgst_paise": ln["sgst_paise"],
            "igst_paise": ln["igst_paise"],
            "line_cess_paise": ln["line_cess_paise"],
            "created_at": now,
        }).execute()
    if payload.get("quotation_id"):
        db.table("sales_quotations").update({
            "status": "converted",
            "converted_to_order_id": str(row.get("id")),
            "updated_at": now,
        }).eq("firm_id", firm_id).eq("id", str(payload["quotation_id"])).execute()
    return row


def create_challan(db, firm_id: str, payload: dict,
                   actor_id: Optional[str] = None) -> dict:
    """Issue a Rule 55 delivery challan.

    THE MOVEMENT'S REASON DECIDES WHETHER THE LINES CARRY TAX. Rule 55(1)(vii)
    requires the rate and amount only "where the transportation is for supply
    to the consignee"; a job-work despatch is not a supply, so charging tax on
    it would put an output liability on a movement that creates none. The rate
    is taken from the line, and zeroed where the reason says there is no
    supply — rather than asking the caller to remember, which is a rule a
    caller will get wrong.
    """
    client_id = str(payload["client_id"])
    reason = str(payload["reason"])
    _refuse_duplicate(db, "delivery_challans", firm_id, client_id,
                      payload["document_no"], None, None)

    lines = list(payload.get("lines") or [])
    if reason not in dc.REASONS_THAT_ARE_A_SUPPLY:
        lines = [{**ln, "gst_rate_percent": 0, "cess_rate_bps": 0,
                  "cess_specific_paise_per_unit": 0} for ln in lines]
    priced, totals = compute_lines(
        lines, is_inter_state=bool(payload.get("is_inter_state")))

    over = _refuse_over_delivery(db, firm_id, payload.get("order_id"), priced)
    if over:
        raise HTTPException(status_code=422, detail=" ".join(over))

    now = ist_now().isoformat()
    # The payload is written INLINE rather than built above and inserted by
    # name: the column guard resolves no variable, and an insert it cannot
    # read is a column it cannot check on a table this new.
    row = (db.table("delivery_challans").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "customer_id": payload.get("customer_id"),
        "vendor_id": payload.get("vendor_id"),
        "document_no": str(payload["document_no"]).strip(),
        "document_date": str(payload["document_date"]),
        "reason": reason,
        "status": "draft",
        "goods_kind": payload.get("goods_kind"),
        "extended_to": payload.get("extended_to"),
        "sales_invoice_id": payload.get("sales_invoice_id"),
        "order_id": payload.get("order_id"),
        "consignee_name": payload.get("consignee_name"),
        "consignee_gstin": payload.get("consignee_gstin"),
        "consignee_address": payload.get("consignee_address"),
        "transporter_name": payload.get("transporter_name"),
        "transporter_id": payload.get("transporter_id"),
        "vehicle_no": payload.get("vehicle_no"),
        "place_of_supply": payload.get("place_of_supply"),
        "is_inter_state": bool(payload.get("is_inter_state")),
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
        db.table("delivery_challan_lines").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "challan_id": str(row.get("id")),
            "order_line_id": ln["order_line_id"],
            "line_order": ln["line_order"],
            "description": ln["description"],
            "hsn_sac": ln["hsn_sac"],
            "quantity": ln["quantity"],
            "unit": ln["unit"],
            "quantity_is_provisional": ln["quantity_is_provisional"],
            "rate_paise": ln["rate_paise"],
            "gst_rate_percent": ln["gst_rate_percent"],
            "is_service": ln["is_service"],
            "service_catalogue_id": ln["service_catalogue_id"],
            "taxable_amount_paise": ln["taxable_amount_paise"],
            "cgst_paise": ln["cgst_paise"],
            "sgst_paise": ln["sgst_paise"],
            "igst_paise": ln["igst_paise"],
            "line_cess_paise": ln["line_cess_paise"],
            "created_at": now,
        }).execute()
    _resettle_order_status(db, firm_id, payload.get("order_id"))
    return row


def _refuse_over_delivery(db, firm_id: str, order_id: Optional[str],
                          priced: list) -> list:
    """Delivering more than was ordered is refused, never clamped.

    Clamping would deliver the ordered quantity and lose the excess with no
    record; allowing it would make the order's own figures stop describing the
    agreement. Amending the order is the real answer and the message says so.
    """
    if not order_id:
        return []
    position = order_open_position(db, firm_id, str(order_id))
    by_id = {str(ln["order_line_id"]): ln for ln in position["lines"]}
    problems: list = []
    for ln in priced:
        lid = str(ln.get("order_line_id") or "")
        if not lid:
            continue
        row = by_id.get(lid)
        if row is None:
            problems.append(
                f"{ln['description']}: that order line does not belong to this "
                f"order.")
            continue
        problem = oc.over_delivery(
            oc.OpenLine(order_line_id=lid, description=row["description"],
                        ordered_qty=Decimal(row["ordered_qty"]),
                        delivered_qty=Decimal(row["delivered_qty"]),
                        invoiced_qty=Decimal(row["invoiced_qty"])),
            Decimal(str(ln["quantity"])))
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
        (db.table("sales_orders")
         .update({"status": wanted, "updated_at": ist_now().isoformat()})
         .eq("firm_id", firm_id).eq("id", str(order_id)).execute())


def update_quotation(db, firm_id: str, quotation_id: str, patch: dict) -> dict:
    """Amend a quotation or a proforma invoice.

    A CONVERTED one is refused: its lines are already the order's or the
    invoice's, and editing it afterwards would leave two documents claiming to
    say the same thing while saying different things. Re-raise instead — a
    quotation costs nothing to re-issue, which is the whole reason its
    immutability bar is lower than an invoice's.
    """
    row = _one(db, "sales_quotations", firm_id, quotation_id,
               "quotation")
    if str(row.get("status")) in ("converted", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=(f"This {oc.KIND_TITLES.get(str(row.get('kind')), 'document')} "
                    f"is {row.get('status')} and cannot be amended. Raise a new "
                    f"one — its lines are already carried onto the document it "
                    f"became."))
    fields = {k: v for k, v in patch.items()
              if v is not None and k != "lines"}
    lines = patch.get("lines")
    if lines is not None:
        if not lines:
            raise HTTPException(
                status_code=422,
                detail="A quotation needs at least one line.")
        # THE DOCUMENT-LEVEL DISCOUNT FALLS BACK TO THE STORED ONE. A CA who
        # amends a line and does not re-send the header discount has not
        # withdrawn it — and re-pricing without it would silently raise every
        # figure on the document by the discount, which the customer has
        # already been quoted.
        priced, totals = compute_lines(
            lines,
            is_inter_state=bool(fields.get("is_inter_state",
                                           row.get("is_inter_state"))),
            document_percent_bps=fields.get("discount_percent_bps",
                                            row.get("discount_percent_bps")),
            document_amount_paise=fields.get("discount_paise",
                                             row.get("discount_paise")))
        fields.update(totals)
        # REPLACED, never merged: a line removed from the payload is a line the
        # CA took off the document, and merging would leave it priced into the
        # totals with no row to show for it.
        for old in quotation_lines(db, firm_id, quotation_id):
            (db.table("sales_quotation_lines").delete()
             .eq("firm_id", firm_id).eq("id", str(old.get("id"))).execute())
        _write_quotation_lines(db, firm_id, str(row["client_id"]),
                               quotation_id, priced)
    if fields.get("document_no"):
        _refuse_duplicate(db, "sales_quotations", firm_id,
                          str(row["client_id"]), fields["document_no"],
                          str(row.get("kind")), quotation_id)
    fields["updated_at"] = ist_now().isoformat()
    (db.table("sales_quotations").update(fields)
     .eq("firm_id", firm_id).eq("id", quotation_id).execute())
    return {**row, **fields}


def update_order(db, firm_id: str, order_id: str, patch: dict) -> dict:
    """Amend a sales order.

    AN ORDER WITH A DELIVERY AGAINST IT KEEPS ITS LINES. Re-pricing them would
    change the quantity a challan was already checked against for
    over-delivery, and a line deleted out from under a challan leaves the
    challan pointing at nothing. The header is still correctable.
    """
    row = _one(db, "sales_orders", firm_id, order_id,
               "sales order")
    if str(row.get("status")) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="A cancelled order cannot be amended. Raise a new one.")
    fields = {k: v for k, v in patch.items()
              if v is not None and k != "lines"}
    lines = patch.get("lines")
    if lines is not None:
        position = order_open_position(db, firm_id, order_id)
        if any(ln["delivered_qty"] != "0.000" for ln in position["lines"]):
            raise HTTPException(
                status_code=409,
                detail=("This order already has a delivery against it, so its "
                        "lines cannot be re-priced — a challan was checked for "
                        "over-delivery against the quantity they carry. Amend "
                        "the header, or cancel and re-raise."))
        if not lines:
            raise HTTPException(status_code=422,
                                detail="A sales order needs at least one line.")
        # The stored document discount stands unless the patch replaces it —
        # see `update_quotation`.
        priced, totals = compute_lines(
            lines,
            is_inter_state=bool(fields.get("is_inter_state",
                                           row.get("is_inter_state"))),
            document_percent_bps=fields.get("discount_percent_bps",
                                            row.get("discount_percent_bps")),
            document_amount_paise=fields.get("discount_paise",
                                             row.get("discount_paise")))
        fields.update(totals)
        for old in order_lines(db, firm_id, order_id):
            (db.table("sales_order_lines").delete()
             .eq("firm_id", firm_id).eq("id", str(old.get("id"))).execute())
        now = ist_now().isoformat()
        for ln in priced:
            db.table("sales_order_lines").insert({
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
                "discount_percent_bps": ln["discount_percent_bps"],
                "discount_paise": ln["discount_paise"],
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
        _refuse_duplicate(db, "sales_orders", firm_id, str(row["client_id"]),
                          fields["document_no"], None, order_id)
    fields["updated_at"] = ist_now().isoformat()
    (db.table("sales_orders").update(fields)
     .eq("firm_id", firm_id).eq("id", order_id).execute())
    return {**row, **fields}


def update_challan(db, firm_id: str, challan_id: str, patch: dict) -> dict:
    """Amend a challan, including recording the goods coming back.

    `received_back_on` is the one field here that changes what is OWED — it
    stops the s.143 clock — so it is the field `record_goods_back` exists for,
    and this path routes through the same write.
    """
    row = _one(db, "delivery_challans", firm_id, challan_id,
               "delivery challan")
    fields = {k: v for k, v in patch.items()
              if v is not None and k != "lines"}
    if fields.get("goods_kind") and str(row.get("reason")) != dc.REASON_JOB_WORK:
        raise HTTPException(
            status_code=422,
            detail=("Only a job-work movement carries a kind of goods: CGST "
                    "s.143 reaches goods sent to a job worker and nothing "
                    "else."))
    if fields.get("extended_to") and str(row.get("reason")) != dc.REASON_JOB_WORK:
        raise HTTPException(
            status_code=422,
            detail=("An extension under the proviso to s.143(1) applies to a "
                    "job-work movement only."))
    if fields.get("document_no"):
        _refuse_duplicate(db, "delivery_challans", firm_id,
                          str(row["client_id"]), fields["document_no"], None,
                          challan_id)
    if fields.get("received_back_on") and not fields.get("status"):
        fields["status"] = "received_back"
    fields["updated_at"] = ist_now().isoformat()
    (db.table("delivery_challans").update(fields)
     .eq("firm_id", firm_id).eq("id", challan_id).execute())
    return {**row, **fields}


def record_goods_back(db, firm_id: str, challan_id: str,
                      received_back_on: str) -> dict:
    """Stop the s.143 clock. The one update that changes what is owed."""
    row = _one(db, "delivery_challans", firm_id, challan_id,
               "delivery challan")
    (db.table("delivery_challans")
     .update({"received_back_on": str(received_back_on),
              "status": "received_back",
              "updated_at": ist_now().isoformat()})
     .eq("firm_id", firm_id).eq("id", challan_id).execute())
    return {**row, "received_back_on": str(received_back_on),
            "status": "received_back"}


# ── The Rule 55 face of one challan ──────────────────────────────────────────

def challan_particulars(db, firm_id: str, challan_id: str,
                        *, consigner: Optional[dict] = None) -> dict:
    """What Rule 55 requires on this challan, and what it is missing.

    # CA REVIEW REQUIRED — this prepares a document. Nothing is transmitted.
    """
    row = _one(db, "delivery_challans", firm_id, challan_id,
               "delivery challan")
    lines = challan_lines(db, firm_id, challan_id)
    src = consigner or {}
    rows = dc.particulars(
        challan_no=str(row.get("document_no") or ""),
        challan_date=str(row.get("document_date") or ""),
        consigner_name=src.get("legal_name"),
        consigner_gstin=src.get("gstin"),
        consigner_address=src.get("address"),
        consignee_name=row.get("consignee_name"),
        consignee_gstin=row.get("consignee_gstin"),
        consignee_address=row.get("consignee_address"),
        reason=str(row.get("reason") or ""),
        is_inter_state=bool(row.get("is_inter_state")),
        place_of_supply=row.get("place_of_supply"),
        lines=lines)
    clock = dc.deemed_supply_clock(
        reason=str(row.get("reason") or ""),
        challan_date=row.get("document_date"),
        as_at=ist_today().isoformat(),
        goods_kind=row.get("goods_kind"),
        received_back_on=row.get("received_back_on"),
        extended_to=row.get("extended_to"))
    return {
        "challan": row,
        "lines": lines,
        "rule": "CGST Rule 55",
        "reason_label": dc.REASON_LABELS.get(str(row.get("reason")), ""),
        "particulars": [p.as_dict() for p in rows],
        "missing": dc.missing_particulars(rows),
        "copies": [{"copy": c, "legend": legend} for c, legend in dc.COPIES],
        "clock": clock.as_dict(),
        "rule_55_5": {
            "steps": list(dc.RULE_55_5_STEPS),
            "gaps": dc.rule_55_5_gaps(
                reason=str(row.get("reason") or ""),
                invoice_id=row.get("sales_invoice_id"),
                is_first_consignment=None),
        },
        "itc_04": dc.itc_04_period(),
        "ca_review_required": True,
    }

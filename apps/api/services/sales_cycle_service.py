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
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_now, ist_today
from services import named_row_ownership
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
            status=r.get("status"),
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

def order_open_position(db, firm_id: str, order_id: str, *, with_drafts: bool = False) -> dict:
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

    THE PARENT'S STATUS IS READ, not just the line. Goods count as delivered
    once they have LEFT: on an issued challan, or one whose goods have since
    come back (`delivery_challan.GOODS_HAVE_LEFT`). A cancelled challan has
    delivered nothing, and a DRAFT is not recorded as issued (POST-A-398), so
    neither counts; a query that forgot the parent would show a fully
    delivered order for goods that never left.

    `with_drafts` asks the other question, "what challans hang from these lines?": a draft is a challan whose goods are not out, and it still points at an order line, so the order's lines
    are not re-priced or deleted from under it (`update_order`). The default answers what has been delivered.
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
                if str(c.get("status")) in (dc.GOODS_HAVE_LEFT + ((dc.STATUS_DRAFT,) if with_drafts else ())):
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


def row_of_client(db, table: str, firm_id: str, row_id: str, client_id: str, what: str) -> dict:
    """The quotation, order or challan, or the 404 "That <what> was not found." unless it is THIS client's.

    For a route that takes the client from the request and the document from the path. `assert_client_access` on the client the
    caller named proves only that THEY may act on that client; these routes read and write through the privileged client by firm
    and id, so a document of another client of the same firm was reached by naming one's own client beside the other's id (to read
    its lines or position, amend it, or stop a challan's s.143 clock). A missing document and one of another client answer with the
    same words. `client_id` has no default."""
    row = _one(db, table, firm_id, row_id, what)
    if str(row.get("client_id")).lower() != str(client_id).lower():
        raise HTTPException(status_code=404, detail=f"That {what} was not found.")
    return row


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
    # THE CUSTOMER IS THIS CLIENT'S (POST-A-338): the foreign key is not client-aware.
    named_row_ownership.customer_is_the_clients(db, firm_id, client_id, payload.get("customer_id"))
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
    named_row_ownership.customer_is_the_clients(db, firm_id, client_id, payload.get("customer_id"))
    if payload.get("quotation_id"):
        # THE QUOTATION THIS ORDER CONVERTS IS THIS CLIENT'S (POST-A-338): it is marked converted below, by firm and id.
        row_of_client(db, "sales_quotations", firm_id, str(payload["quotation_id"]), client_id, "quotation")
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


def _consignee_of_party(db, firm_id: str, client_id: str, customer_id, vendor_id) -> dict:
    """The name, GSTIN and address of the party a challan names as its consignee (a customer, or a vendor who is the job worker), or `{}`. Read for a challan that types no consignee of its own."""
    cols = {"name": None, "gstin": None, "address": None}
    if customer_id:
        rows = (db.table("customers").select("id, name, gstin, address, city, state, pincode")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("id", str(customer_id)).limit(1).execute().data) or []
    elif vendor_id:
        rows = (db.table("vendors").select("id, name, gstin, address, city, state, pincode")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("id", str(vendor_id)).limit(1).execute().data) or []
    else:
        rows = []
    if not rows:
        return cols
    r = rows[0]
    return {"name": r.get("name"), "gstin": r.get("gstin"),
            "address": ", ".join(str(b).strip() for b in (r.get("address"), r.get("city"), r.get("state"), r.get("pincode")) if (b or "").strip()) or None}


def create_challan(db, firm_id: str, payload: dict,
                   actor_id: Optional[str] = None) -> dict:
    """Make a Rule 55 delivery challan, as a DRAFT (POST-A-398): `issue_challan` is what records that the goods left on it.

    THE CONSIGNEE THE CHALLAN NAMES FILLS ITS CONSIGNEE PARTICULARS WHEN NONE WERE TYPED. The screen offers "Consignee (customer)" and the Rule 55(1)(iii) clause reads the typed name, address
    and GSTIN, so a challan made by picking the customer alone held none of them and could not be issued. If the payload types none of the three, the named customer's (or the job worker's) are
    copied; if it types any, the typed ones stand and nothing is mixed in (a typed branch name with the head office's GSTIN is a wrong document).

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
    # EVERY ROW THE CHALLAN NAMES IS THIS CLIENT'S (POST-A-338), asked before `_refuse_over_delivery` reads the order's position.
    named_row_ownership.customer_is_the_clients(db, firm_id, client_id, payload.get("customer_id"))
    named_row_ownership.vendor_is_the_clients(db, firm_id, client_id, payload.get("vendor_id"))
    named_row_ownership.sales_invoice_is_the_clients(db, firm_id, client_id, payload.get("sales_invoice_id"))
    if payload.get("order_id"):
        row_of_client(db, "sales_orders", firm_id, str(payload["order_id"]), client_id, "sales order")
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

    typed = [(payload.get(k) or "").strip() for k in ("consignee_name", "consignee_gstin", "consignee_address")]
    party = {} if any(typed) else _consignee_of_party(db, firm_id, client_id, payload.get("customer_id"), payload.get("vendor_id"))
    # The STRIPPED typed values decide (a space typed in a box is a blank, and is not stored beside the customer's GSTIN and address).
    consignee_name, consignee_gstin, consignee_address = (typed[0] or party.get("name") or None, typed[1] or party.get("gstin") or None, typed[2] or party.get("address") or None)

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
        "consignee_name": consignee_name,
        "consignee_gstin": consignee_gstin,
        "consignee_address": consignee_address,
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
    # No re-settle of the order here: a challan is made as a DRAFT, and goods are delivered against an order only once they have left (issued or received back), so making one moves
    # neither the order's position nor its status. `issue_challan` and the amendment door re-settle it when that changes.
    return row


def _refuse_over_delivery(db, firm_id: str, order_id: Optional[str],
                          priced: list) -> list:
    """Delivering more than was ordered is refused, never clamped.

    Clamping would deliver the ordered quantity and lose the excess with no
    record; allowing it would make the order's own figures stop describing the
    agreement. Amending the order is the real answer and the message says so.
    """
    if not order_id:
        # A LINE CANNOT NAME AN ORDER LINE WHEN THE CHALLAN NAMES NO ORDER (POST-A-338): the position readers count delivered
        # quantity by order-line id alone, so another client's order would show this challan's goods as delivered against it.
        return [f"{ln.get('description')}: this line names an order line but the challan names no order."
                for ln in priced if ln.get("order_line_id")]
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
        position = order_open_position(db, firm_id, order_id, with_drafts=True)
        if any(ln["delivered_qty"] != "0.000" for ln in position["lines"]):
            raise HTTPException(
                status_code=409,
                detail=("This order already has a delivery challan against it, so its "
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


def _earliest_recorded_return(db, firm_id: str, client_id: str, challan_id: str) -> Optional[date]:
    """The earliest day a lot of this challan's goods was recorded as back on FORM GST ITC-04 (`delivery_challan_returns`), or None (PRE-A-015, seventeenth slice)."""
    rows = (db.table("delivery_challan_returns").select("returned_on")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("challan_id", challan_id)
            .order("returned_on").limit(1).execute().data) or []
    return date.fromisoformat(str(rows[0]["returned_on"])[:10]) if rows else None


def _latest_returned_on(db, firm_id: str, client_id: str, challan_id: str) -> Optional[date]:
    """The latest day goods were recorded as RETURNED on FORM GST ITC-04 against this challan (`delivery_challan_returns`), or None (POST-A-383): the day the WHOLE challan came back is
    the day its last goods did, so it cannot be before this one. A row that records only quantity lost or wasted (migration 462 allows one) is not goods returned and is not counted:
    whether scrap counts as received back for s.143 is not a judgement this product takes."""
    rows = (db.table("delivery_challan_returns").select("returned_on, quantity_returned")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("challan_id", challan_id)
            .order("returned_on", desc=True).execute().data) or []
    for r in rows:
        raw = str(r.get("quantity_returned") or "0").strip()
        # NUMERIC(10,3) comes back as a plain decimal; a value that is not one is not goods returned (no exception handler here: the service holds exactly one, and it is not around a read).
        if re.fullmatch(r"\d+(\.\d+)?", raw) and Decimal(raw) > 0:
            return date.fromisoformat(str(r["returned_on"])[:10])
    return None


def _latest_lot_recorded_on(db, firm_id: str, client_id: str, challan_id: str) -> Optional[date]:
    """The latest day ANY lot was recorded against this challan on FORM GST ITC-04 (goods returned, or lost or wasted), or None (POST-A-398). The cancel guard asks this and not
    `_latest_returned_on`: a lot of waste alone leaves the challan's balance larger (waste is never subtracted from it), and a cancelled challan's balance is not listed, so cancelling one with
    such a lot would drop a deemed supply out of the statement."""
    rows = (db.table("delivery_challan_returns").select("returned_on")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("challan_id", challan_id)
            .order("returned_on", desc=True).limit(1).execute().data) or []
    return date.fromisoformat(str(rows[0]["returned_on"])[:10]) if rows else None


def _refuse_a_status_or_day_that_cannot_stand(row: dict, fields: dict) -> None:
    """The refusals about a challan's status and its back day, in the order that says the unfixable one first (POST-A-383). Nothing is written before any of them."""
    stops_the_clock = bool(fields.get("received_back_on")) or fields.get("status") == "received_back"
    # The status the patch LEAVES: the one it gives, or "received back" when it gives a day alone (the write does that), or the one stored.
    after_status = fields.get("status") or ("received_back" if fields.get("received_back_on") else row.get("status"))
    # The unfixable one first: goods cannot come back on a cancelled challan, whether it is cancelled already or this very patch cancels it.
    if stops_the_clock and "cancelled" in (str(row.get("status")), str(after_status)):
        raise HTTPException(status_code=409, detail=dc.not_issued_sentence(row.get("document_no"), "cancelled"))
    # Goods come back on a challan they left on (POST-A-398): a DRAFT has had nothing leave, and the door that makes it issued is Issue challan, not this patch.
    if stops_the_clock and str(row.get("status")) == dc.STATUS_DRAFT:
        raise HTTPException(status_code=409, detail=dc.not_issued_sentence(row.get("document_no"), dc.STATUS_DRAFT))
    if fields.get("status") == "received_back" and not (fields.get("received_back_on") or row.get("received_back_on")):
        raise HTTPException(status_code=422, detail=dc.whole_challan_back_needs_a_day(row.get("reason")))
    # A challan with a back day IS received back: this patch cannot leave the day beside a status that says the goods have not come back.
    after_day = fields.get("received_back_on") or row.get("received_back_on")
    if ("status" in fields or "received_back_on" in fields) and after_day and str(after_status) != "received_back":
        raise HTTPException(status_code=422, detail=dc.a_back_day_needs_a_status_that_says_so_problem(
            row.get("document_no"), str(after_day)[:10], after_status))
    # What is left of the life of a challan (draft, issued, received back or cancelled): a status this patch may not give is refused in a sentence, before anything is written.
    if fields.get("status"):
        problem = dc.status_change_problem(row.get("document_no"), row.get("status"), fields["status"])
        if problem:
            raise HTTPException(status_code=409, detail=problem)


def _refuse_a_day_that_is_out_of_order(db, firm_id: str, row: dict, challan_id: str, fields: dict) -> None:
    """The order of the days: the goods cannot have come back before they went out, or on a day that has not come (PRE-A-015, seventeenth slice), and the whole challan's day is not
    before goods already returned under ITC-04 (POST-A-383). The request model has judged each day alone; the day they went out is the challan's own, or the one this same amendment gives it."""
    if not (fields.get("received_back_on") or fields.get("document_date")):
        return
    sent = date.fromisoformat(str(fields.get("document_date") or row["document_date"])[:10])
    problem = None
    if fields.get("received_back_on"):
        back_on = date.fromisoformat(str(fields["received_back_on"])[:10])
        problem = dc.goods_back_problem(sent, back_on, ist_today())
        if not problem:
            # The whole challan's day is the day its LAST goods came back, so it is not before a lot of goods already returned under ITC-04.
            problem = dc.whole_challan_back_before_a_lot_problem(
                row.get("document_no"), back_on, _latest_returned_on(db, firm_id, str(row["client_id"]), challan_id))
    if not problem and fields.get("document_date"):
        # The day they went out is amended, and that can leave the pair the wrong way round: it is compared with the days already recorded as back, the whole challan's (unless this
        # same patch gives another) and the earliest lot's (a lot recorded under ITC-04 leaves `received_back_on` empty until every line is back). Those days were judged when they
        # were recorded, so here they are asked only for their ORDER (a day is never after itself, so `back` stands for today), and an edit of something else never gets here, so a
        # row stored from before this rule is not made unsaveable by it. Asked whether or not the patch also gives a back day: the pair is wrong either way.
        recorded_days = [_earliest_recorded_return(db, firm_id, str(row["client_id"]), challan_id)]
        if not fields.get("received_back_on"):
            recorded_days.insert(0, row.get("received_back_on"))
        for recorded in recorded_days:
            if recorded:
                back = date.fromisoformat(str(recorded)[:10])
                problem = dc.goods_back_problem(sent, back, back)
                if problem:
                    break
    if problem:
        raise HTTPException(status_code=422, detail=problem)


def update_challan(db, firm_id: str, challan_id: str, patch: dict) -> dict:
    """Amend a challan, including recording the goods coming back.

    `received_back_on` and the status "received back" are the two fields here that change what is OWED — each stops the s.143 clock (`itc_04.balances` skips a challan with either) —
    so the day it is given is judged by the rule the ITC-04 door asks (`delivery_challan.goods_back_problem`) before it is written.

    THE STATUS "received back" IS NEVER SET WITHOUT THE DAY (POST-A-383): a status alone named no day and the clock stopped on a figure nobody could read back. A CANCELLED challan has no
    goods in transit to come back, so a patch that stops the clock on one, or leaves one cancelled with a back day, is refused in the ITC-04 lot door's own sentence, judged on the status
    the patch LEAVES and not only on the one stored (`{"status": "cancelled", "received_back_on": D}` is one request); the sentence for the cancelled challan comes before the one for the
    missing day, because the missing day cannot be fixed on it. A challan given a back day IS received back, so a patch that gives one beside another status is refused. The whole
    challan's day is not earlier than a lot of goods returned on ITC-04, and an amended day they went out is compared with the days already recorded as back whether or not the patch
    gives a back day too. A DRAFT IS REFUSED A BACK DAY since POST-A-398: the product has a door that issues a challan (`issue_challan`), so a draft is a challan nothing has left on, and goods
    can only come back on an issued one (the same sentence as the FORM GST ITC-04 lot door). The status is not set to `issued` here either: that is the issue door's, which asks what a
    challan must hold when the goods leave (`delivery_challan.status_change_problem`).
    """
    row = _one(db, "delivery_challans", firm_id, challan_id,
               "delivery challan")
    fields = {k: v for k, v in patch.items()
              if v is not None and k != "lines"}
    # THE LINES OF A DRAFT ARE CORRECTED HERE (POST-A-417): their description and HSN code, judged before anything is written; anything else on a line, and any line of a challan that is not a draft, is refused
    # in a sentence (this door used to drop `lines` whole and report a success). The write that follows is held to a draft by the same compare-and-set as a status.
    fixes = patch.get("lines")
    if fixes is not None and fields.get("status"):
        raise HTTPException(status_code=422, detail=dc.LINES_ARE_CORRECTED_ALONE)
    own_lines = challan_lines(db, firm_id, challan_id) if fixes is not None else []
    if fixes is not None:
        problem = dc.draft_line_corrections_problem(row.get("document_no"), row.get("status"), fixes, [ln["id"] for ln in own_lines])
        if problem:
            raise HTTPException(status_code=422 if str(row.get("status")) == dc.STATUS_DRAFT else 409, detail=problem)
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
    # THE INVOICE A CHALLAN IS RE-POINTED AT IS THIS CLIENT'S (POST-A-338): the one named row the update door still accepts.
    named_row_ownership.sales_invoice_is_the_clients(db, firm_id, str(row["client_id"]), fields.get("sales_invoice_id"))
    _refuse_a_status_or_day_that_cannot_stand(row, fields)
    if fields.get("status") == dc.STATUS_CANCELLED and str(row.get("status")) != dc.STATUS_CANCELLED:
        # a lot already recorded against this challan hangs from it (POST-A-398): it is finished by recording the rest, not cancelled
        recorded = _latest_lot_recorded_on(db, firm_id, str(row["client_id"]), challan_id)
        if recorded is not None:
            raise HTTPException(status_code=409, detail=dc.cancel_after_goods_came_back_sentence(row.get("document_no"), recorded.isoformat()))
    _refuse_a_day_that_is_out_of_order(db, firm_id, row, challan_id, fields)
    if fields.get("received_back_on") and not fields.get("status"):
        fields["status"] = "received_back"
    # AN ISSUED CHALLAN KEEPS WHAT ISSUING ASKED OF IT (POST-A-398): an empty string blanks a field and a date can be moved, so the fields this patch touches are asked again of the row it would
    # leave. Only what it touches: a row stored before this rule is not made unsaveable by an edit of something else.
    if str(fields.get("status") or row.get("status")) in dc.GOODS_HAVE_LEFT:
        problem = dc.issued_challan_problem(row.get("document_no"), row={**row, **fields}, today=ist_today(), touched=set(fields))
        if problem:
            raise HTTPException(status_code=422, detail=problem)
    fields["updated_at"] = ist_now().isoformat()
    # A STATUS IS WRITTEN OVER THE ONE THIS PATCH JUDGED (POST-A-398): an issue, a cancel, an amendment or a lot's stamp that got in between has changed what the rules above were asked about, so
    # this write matches nothing and says so, and a challan at its end (cancelled, received back) is not written over by a request that read it before it got there. A patch that gives no
    # status is held to no status (a note or a transporter is a correction to what the document says). One statement, so the writers of this table stay countable.
    expected = [row.get("status")] if "status" in fields else ([dc.STATUS_DRAFT] if fixes else list(oc.CHALLAN_STATUSES))
    done = (db.table("delivery_challans").update(fields)
            .eq("firm_id", firm_id).eq("id", challan_id).in_("status", expected).execute())
    if not (done.data or []):
        raise HTTPException(status_code=409, detail=f"Challan {row.get('document_no')} was changed while it was being amended. Reload it and look at its status.")
    # The two columns are written as a literal pair (the column guard reads a literal write and not a variable one), each from the correction or, where it gives none, from the line as it was read.
    was = {str(ln["id"]): ln for ln in own_lines}
    for fix in fixes or []:
        changes, line = dc.draft_line_changes(fix), was[str(fix["id"]).strip()]
        (db.table("delivery_challan_lines")
         .update({"description": changes.get("description", line.get("description")), "hsn_sac": changes["hsn_sac"] if "hsn_sac" in changes else line.get("hsn_sac")})
         .eq("firm_id", firm_id).eq("client_id", str(row["client_id"])).eq("challan_id", challan_id).eq("id", str(fix["id"]).strip()).execute())
    if "status" in fields:
        _resettle_order_status(db, firm_id, row.get("order_id"))      # a cancelled (or received-back) challan changes what is delivered against its order
    return {**row, **fields}


def record_goods_back(db, firm_id: str, challan_id: str,
                      received_back_on: str) -> dict:
    """Stop the s.143 clock. The one update that changes what is owed.

    It writes the day it is given. Its only caller, `itc_04_service.record_return`, has judged every lot's day (`delivery_challan.goods_back_problem`) before this stamps the largest,
    and `update_challan` judges the day it is given before it writes its own; a new caller must judge a day with that rule first (a test pins that there is only the one).

    The stamp is written over an ISSUED challan only (a compare-and-set): the lot is inserted first and this second, in two statements, so a cancel that got in between is not written over, and the
    sentence says that what was recorded stands. One transaction for both is POST-A-419.
    """
    row = _one(db, "delivery_challans", firm_id, challan_id,
               "delivery challan")
    # Written over an ISSUED challan only (POST-A-398): the lot door asked for that before it recorded the lot, and a cancel that got in since is not written over with "received back".
    done = (db.table("delivery_challans")
            .update({"received_back_on": str(received_back_on),
                     "status": "received_back",
                     "updated_at": ist_now().isoformat()})
            .eq("firm_id", firm_id).eq("id", challan_id).eq("status", dc.STATUS_ISSUED).execute())
    if not (done.data or []):
        raise HTTPException(status_code=409, detail=(
            f"Challan {row.get('document_no')} was changed by another request while its goods were being recorded back, so this request did not mark it received back. "
            "What was recorded stands. Reload the challan and look at its status."))
    return {**row, "received_back_on": str(received_back_on),
            "status": "received_back"}


def consigner_of(db, firm_id: str, client_id: str) -> Optional[dict]:
    """Rule 55(1)(ii)'s consigner: the CLIENT whose goods are moving, not the CA firm. SALES-01 was exactly this mistake on the tax invoice: the PDF named the practice as the supplier,
    with the practice's own GSTIN, on the client's outward document. Read for the challan's Rule 55 face and for the issue door, which asks the same particulars."""
    res = (db.table("clients")
           .select("id, client_name, legal_name, trade_name, gstin, "
                   "address_line1, address_line2, city, state, pincode")
           .eq("firm_id", firm_id).eq("id", client_id)
           .limit(1).execute())
    if not res.data:
        return None
    row = res.data[0]
    return {
        "legal_name": row.get("legal_name") or row.get("trade_name") or row.get("client_name"),
        "gstin": row.get("gstin"),
        "address": ", ".join(
            str(b).strip() for b in (row.get("address_line1"), row.get("address_line2"),
                                     row.get("city"), row.get("state"), row.get("pincode")) if (b or "").strip()),
    }


def issue_challan(db, firm_id: str, challan_id: str, *, client_id: str, consigner: Optional[dict] = None) -> dict:
    """Issue a draft challan: the goods leave on it (POST-A-398). The ONE door that makes a challan `issued`.

    Issuing RECORDS THAT THE GOODS LEFT on the challan's own date. That is what a period is run from (s.143 for job work, s.31(7) for goods on approval: `deemed_supply_clock` runs for an issued
    challan only, and counts from the challan's date, so issuing does not move the day it counts from), what makes a job-work challan a row of FORM GST ITC-04 (`itc_04.SENT_STATUSES`), what counts
    its goods as delivered against an order (`GOODS_HAVE_LEFT`), and what lets goods come back on it (the lot door and the whole-challan day both refuse a draft). Nothing was ever issued before
    this door: `create_challan` writes a draft, and a draft was the state every challan made in the product stayed in.

    WHAT IT ASKS, in the order a person can fix them, before anything is written: that the challan is a draft (an issued, received-back or cancelled one is not issued again), that it has goods on it,
    that its date has come (the goods cannot have left on a day that has not), that Rule 55(1) has every particular it requires of THIS challan (`delivery_challan.missing_particulars`: the consigner
    is the client, read here as the detail screen reads it), for job work what is sent (the period differs by a factor of three and is none for tools, so a challan issued without the answer would be
    listed on FORM GST ITC-04 while running no clock), and that its goods are not more than the order it names still has undelivered. The write is a compare-and-set on the status, so two requests
    (or an issue and a cancel) cannot both win.

    THE CHALLAN IS THE NAMED CLIENT'S, ASKED HERE AND CARRIED BY THE WRITE: `client_id` has no default, a challan of another client of the firm is the 404 a missing one gives, and the update
    names the client as well as the firm and the id, so a door that is ever called with the wrong pair writes nothing
    (`tests/test_a_route_that_asserts_a_client_does_not_write_a_row_by_the_firm_alone.py` holds the second half).

    # CA REVIEW REQUIRED — this prepares a document and records that it was issued. Nothing is transmitted.
    """
    row = row_of_client(db, "delivery_challans", firm_id, challan_id, client_id, "delivery challan")
    no = row.get("document_no")
    if str(row.get("status")) != dc.STATUS_DRAFT:
        raise HTTPException(status_code=409, detail=dc.only_a_draft_is_issued_sentence(no, row.get("status")))
    lines = challan_lines(db, firm_id, challan_id)
    if not lines:
        raise HTTPException(status_code=422, detail=dc.an_empty_challan_is_not_issued_sentence(no))
    sent = dc.sent_on(row.get("document_date"))
    if sent is not None and sent > ist_today():
        raise HTTPException(status_code=422, detail=(
            f"Challan {no} is dated {sent.isoformat()}, which has not come, so the goods cannot have left on it. A challan is issued on or after its date."))
    src = consigner or {}
    parts = dc.particulars(
        challan_no=str(no or ""), challan_date=str(row.get("document_date") or ""),
        consigner_name=src.get("legal_name"), consigner_gstin=src.get("gstin"), consigner_address=src.get("address"),
        consignee_name=row.get("consignee_name"), consignee_gstin=row.get("consignee_gstin"), consignee_address=row.get("consignee_address"),
        reason=str(row.get("reason") or ""), is_inter_state=bool(row.get("is_inter_state")),
        place_of_supply=row.get("place_of_supply"), lines=lines)
    missing = dc.missing_particulars(parts)
    if missing:
        raise HTTPException(status_code=422, detail=dc.issue_needs_the_particulars_sentence(no, missing))
    if str(row.get("reason")) == dc.REASON_JOB_WORK and not row.get("goods_kind"):
        raise HTTPException(status_code=422, detail=dc.issue_needs_the_kind_of_goods_sentence(no))
    # Goods count as DELIVERED against an order when they have left (this challan is not counted yet: it is a draft), so the check that a delivery is not more than the order still has
    # undelivered is made here, where they leave, and not when the draft is made: two drafts of the whole order are drafts, and only the first to be issued is a delivery.
    over = _refuse_over_delivery(db, firm_id, row.get("order_id"), lines)
    if over:
        raise HTTPException(status_code=422, detail=" ".join(over))
    now = ist_now().isoformat()
    done = (db.table("delivery_challans").update({"status": dc.STATUS_ISSUED, "updated_at": now})
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("id", challan_id).eq("status", dc.STATUS_DRAFT).execute())
    if not (done.data or []):
        # another request changed the challan between the read and the write (an issue, a cancel): say so, and write nothing more
        raise HTTPException(status_code=409, detail=f"Challan {no} was changed while it was being issued. Reload it and look at its status.")
    _resettle_order_status(db, firm_id, row.get("order_id"))      # the goods on it are delivered against its order from now
    return {**row, "status": dc.STATUS_ISSUED, "updated_at": now}


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
        extended_to=row.get("extended_to"),
        status=row.get("status"))
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

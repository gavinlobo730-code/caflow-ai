"""Reading and recording what else the goods cost to get here (INV-05).

This module FETCHES and WRITES; `domain/inventory/landed_cost.py` DECIDES. It
picks no basis, splits nothing and words no refusal.

WHAT IT IS RESPONSIBLE FOR THAT THE DOMAIN MODULE IS NOT

  THE PREVIEW. A CA needs to see what each line will carry BEFORE receiving
  the bill, because after the receipt the journal is posted and migration 251
  makes it immutable. The preview runs the same `apportion_many` the receipt
  runs, over the same goods lines, so what is shown is what will happen.

  THE BILL OF ENTRY CARRY-OVER. Migration 389 posts basic customs duty and
  the social welfare surcharge to an expense account and its own module says
  in terms that they are not apportioned "because the basis for that ... is a
  judgement nothing here holds". Migration 396 is that judgement, so the duty
  now becomes a landed cost on the purchase bill the Bill of Entry names — one
  row, written by the system, and `UNIQUE (bill_id, bill_of_entry_id)` is what
  stops a second one on an edit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from core.db_paging import fetch_all
from domain.gst import bill_of_entry as boe_domain
from domain.inventory import landed_cost as landed


def _blocked_tax(line: dict) -> int:
    """The line's §17(5)-blocked tax — INV-05a's rule, not a second copy."""
    from domain.inventory_service import _blocked_tax_on_line
    return _blocked_tax_on_line(line)


def read_for_bill(db, *, firm_id: str, client_id: str, bill_id: str) -> dict:
    """The charges on this bill, the basis in force, and the split they make."""
    bill_rows = (
        db.table("purchase_bills")
        .select("id, bill_no, our_reference, status, landed_cost_basis")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("id", bill_id).limit(1).execute().data
    ) or []
    if not bill_rows:
        return {"found": False, "charges": [], "gaps": ["That bill is not in this firm."]}
    bill = bill_rows[0]

    client_rows = (
        db.table("clients").select("id, landed_cost_basis")
        .eq("firm_id", firm_id).eq("id", client_id).limit(1).execute().data
    ) or []
    client_basis = client_rows[0].get("landed_cost_basis") if client_rows else None
    basis = landed.basis_for(client_basis, bill.get("landed_cost_basis"))

    charges = fetch_all(
        lambda: db.table("purchase_bill_landed_costs")
        .select("id, description, amount_paise, expense_account_id, source, "
                "bill_of_entry_id, applied_at, notes")
        .eq("firm_id", firm_id).eq("bill_id", bill_id),
        key="id", label="landed_cost.charges")

    lines = fetch_all(
        lambda: db.table("purchase_bill_lines")
        .select("id, description, quantity, taxable_amount_paise, "
                "service_catalogue_id, itc_eligible, cgst_paise, sgst_paise, "
                "igst_paise, cess_paise")
        .eq("bill_id", bill_id),
        key="id", label="landed_cost.lines")
    goods_ids = [l["service_catalogue_id"] for l in lines if l.get("service_catalogue_id")]
    goods: set = set()
    if goods_ids:
        items = fetch_all(
            lambda: db.table("service_catalogue").select("id, kind, name")
            .in_("id", list({str(g) for g in goods_ids})),
            key="id", label="landed_cost.items")
        goods = {str(i["id"]) for i in items if i.get("kind") == "good"}
        names = {str(i["id"]): i.get("name") for i in items}
    else:
        names = {}

    goods_lines = [
        landed.Line(
            line_id=str(l["id"]),
            service_catalogue_id=str(l.get("service_catalogue_id") or ""),
            cost_paise=int(l.get("taxable_amount_paise") or 0) + _blocked_tax(l),
            quantity=Decimal(str(l.get("quantity") or 0)),
        )
        for l in lines if str(l.get("service_catalogue_id") or "") in goods
    ]

    # THE PREVIEW IS OVER THE UNAPPLIED CHARGES ONLY — an applied one is
    # already in the ledger and showing it again as "will be added" would
    # invite the CA to expect it twice.
    pending = [c for c in charges if not c.get("applied_at")]
    split = landed.apportion_many(
        goods_lines,
        [(str(c["id"]), int(c.get("amount_paise") or 0)) for c in pending],
        basis=basis,
    )
    by_line = split.by_line

    out = split.as_dict()
    out.update({
        "found": True,
        "bill_id": bill_id,
        "bill_no": bill.get("bill_no") or bill.get("our_reference"),
        "bill_status": bill.get("status"),
        "client_basis": client_basis,
        "bill_basis": bill.get("landed_cost_basis"),
        "basis_is_recorded": bool(client_basis or bill.get("landed_cost_basis")),
        "bases": [{"value": b, "label": landed.BASIS_LABELS[b]} for b in landed.BASES],
        "charges": [
            {**c,
             "is_applied": bool(c.get("applied_at")),
             # A charge recorded after the receipt is the one thing a CA has to
             # act on, so it carries the sentence rather than the screen.
             "why_not_in_cost": (landed.RECORDED_AFTER_THE_RECEIPT
                                 if not c.get("applied_at")
                                 and str(bill.get("status")) == "received" else None)}
            for c in charges
        ],
        "lines": [
            {"line_id": l.line_id,
             "item_name": names.get(l.service_catalogue_id) or "",
             "own_cost_paise": l.cost_paise,
             "quantity": str(l.quantity),
             "landed_cost_paise": by_line.get(l.line_id, 0),
             "total_cost_paise": l.cost_paise + by_line.get(l.line_id, 0)}
            for l in goods_lines
        ],
        "weight_and_volume_refused": landed.WEIGHT_AND_VOLUME_REFUSED,
        "freight_outward_is_not_cost": landed.FREIGHT_OUTWARD_IS_NOT_COST,
    })
    if not out["basis_is_recorded"]:
        out["notes"] = list(out.get("notes") or []) + [landed.UNRECORDED_MEANS]
    return out


def add_charge(db, *, firm_id: str, client_id: str, bill_id: str, description: str,
               amount_paise: int, expense_account_id: Optional[str],
               notes: Optional[str], actor_id: Optional[str]) -> dict:
    """Record a manual landed cost against a bill."""
    inserted = db.table("purchase_bill_landed_costs").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "bill_id": bill_id,
        "description": description,
        "amount_paise": int(amount_paise),
        "expense_account_id": expense_account_id,
        "source": "manual",
        "bill_of_entry_id": None,
        "notes": notes,
        "created_by": actor_id,
    }).execute()
    return (inserted.data or [{}])[0]


def remove_charge(db, *, firm_id: str, charge_id: str,
                  bill_id: Optional[str] = None) -> dict:
    """Delete a charge that has NOT reached a receipt.

    An APPLIED one is refused: its value is in the stock ledger and in a
    posted journal, so deleting the row would leave a cost in the books that
    nothing explains — the same reason the rollback refuses.
    """
    # `bill_id` is the bill the CALLER addressed, and the router has already
    # resolved that bill's own client. Matching on it as well means a charge
    # id guessed from another bill cannot be deleted through this door.
    q = (db.table("purchase_bill_landed_costs")
         .select("id, applied_at, source")
         .eq("firm_id", firm_id).eq("id", charge_id))
    if bill_id:
        q = q.eq("bill_id", bill_id)
    rows = q.limit(1).execute().data or []
    if not rows:
        return {"ok": False, "refusal": "That charge is not in this firm."}
    if rows[0].get("applied_at"):
        return {"ok": False, "refusal": (
            "This charge is already in the cost of the stock — its value is in "
            "the stock ledger and in a posted journal, and a posted entry "
            "cannot be rewritten. Reverse the goods receipt if it has to come "
            "back out.")}
    d = db.table("purchase_bill_landed_costs").delete().eq(
        "firm_id", firm_id).eq("id", charge_id)
    if bill_id:
        d = d.eq("bill_id", bill_id)
    d.execute()
    return {"ok": True, "removed": True}


def set_basis(db, *, firm_id: str, client_id: str, basis: Optional[str],
              bill_id: Optional[str] = None) -> dict:
    """Record the basis on the client, or override it on one bill.

    `basis` of None CLEARS a bill override (back to the client's). It does not
    clear the client's own — an accounting policy is un-recorded only once.
    """
    if basis is not None:
        refusal = landed.basis_refusal(basis)
        if refusal:
            return {"ok": False, "refusal": refusal}
        basis = basis.strip().lower()
    if bill_id:
        db.table("purchase_bills").update({"landed_cost_basis": basis}).eq(
            "firm_id", firm_id).eq("client_id", client_id).eq("id", bill_id).execute()
        return {"ok": True, "scope": "bill", "basis": basis}
    if basis is None:
        return {"ok": False, "refusal": (
            "A client's basis is an accounting policy and is not cleared once "
            "recorded — change it to the other basis instead.")}
    db.table("clients").update({"landed_cost_basis": basis}).eq(
        "firm_id", firm_id).eq("id", client_id).execute()
    return {"ok": True, "scope": "client", "basis": basis}


def carry_over_from_bill_of_entry(db, *, firm_id: str, row: dict,
                                  actor_id: Optional[str]) -> Optional[dict]:
    """Make the Bill of Entry's non-creditable duty a landed cost on its bill.

    Basic customs duty and the social welfare surcharge are recoverable from
    nobody, so AS-2 paragraph 6 puts them in the cost of the goods — which
    `domain/gst/bill_of_entry` says and could not do, having no line detail and
    no basis. Both now exist.

    NOTHING HAPPENS WITHOUT A LINKED BILL. `bills_of_entry.purchase_bill_id`
    is nullable because the duty is owed to customs whether or not the
    supplier's invoice has been entered; with no bill there are no lines to
    apportion over, and inventing a link would attach a duty to goods nobody
    said it was for. Returns None, and the Bill of Entry's own caveat still
    names the duty as cost.

    Never raises: a failure here must not fail the Bill of Entry, which is a
    statutory document and the input-credit side of it is the urgent half.
    """
    bill_id = row.get("purchase_bill_id")
    if not bill_id:
        return None
    try:
        duty = boe_domain.assessment_of(row).non_creditable_duty_paise
        if duty <= 0:
            return None
        existing = (
            db.table("purchase_bill_landed_costs").select("id")
            .eq("firm_id", firm_id).eq("bill_id", bill_id)
            .eq("bill_of_entry_id", row["id"]).limit(1).execute().data
        ) or []
        if existing:
            # An EDIT to an unapplied row re-states the duty; an applied one is
            # left alone, because its value is already in a posted journal.
            db.table("purchase_bill_landed_costs").update({
                "amount_paise": duty,
                "expense_account_id": row.get("duty_expense_account_id"),
            }).eq("firm_id", firm_id).eq("id", existing[0]["id"]).is_(
                "applied_at", "null").execute()
            return {"id": existing[0]["id"], "amount_paise": duty}
        inserted = db.table("purchase_bill_landed_costs").insert({
            "firm_id": firm_id,
            "client_id": row.get("client_id"),
            "bill_id": bill_id,
            "description": f"Customs duty — Bill of Entry {row.get('be_number') or ''}".strip(),
            "amount_paise": duty,
            "expense_account_id": row.get("duty_expense_account_id"),
            "source": "bill_of_entry",
            "bill_of_entry_id": row["id"],
            "notes": None,
            "created_by": actor_id,
        }).execute()
        return (inserted.data or [{}])[0]
    except Exception:  # noqa: BLE001 — never fail the Bill of Entry
        import logging
        logging.getLogger("caflow.inventory").warning(
            "carry_over_from_bill_of_entry failed for be=%s", row.get("id"),
            exc_info=True)
        return None


def unapplied_across_client(db, *, firm_id: str, client_id: str) -> list:
    """Charges recorded against a bill that has already been received.

    These are the ones AS-2 paragraph 6 says belong in the cost and which are
    NOT in it, because the receipt's journal was posted before they were
    recorded. Surfaced so they are a list somebody works through rather than a
    silence.
    """
    charges = fetch_all(
        lambda: db.table("purchase_bill_landed_costs")
        .select("id, bill_id, description, amount_paise, applied_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .is_("applied_at", "null"),
        key="id", label="landed_cost.unapplied")
    if not charges:
        return []
    bill_ids = sorted({str(c["bill_id"]) for c in charges})
    bills = fetch_all(
        lambda: db.table("purchase_bills").select("id, bill_no, our_reference, status")
        .eq("firm_id", firm_id).in_("id", bill_ids),
        key="id", label="landed_cost.unapplied_bills")
    by_id = {str(b["id"]): b for b in bills}
    out = []
    for c in charges:
        bill = by_id.get(str(c["bill_id"])) or {}
        if str(bill.get("status")) != "received":
            continue          # still ahead of the receipt — it will be included
        out.append({
            **c,
            "bill_no": bill.get("bill_no") or bill.get("our_reference"),
            "why": landed.RECORDED_AFTER_THE_RECEIPT,
        })
    return out

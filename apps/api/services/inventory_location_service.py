"""Godowns, batches and the per-location position (INV-03a, migration 398).

This module FETCHES and WRITES; `domain/inventory/location.py` and
`domain/inventory/batches.py` DECIDE. It buckets no expiry, resolves no default
and does not know what Schedule I paragraph 2 says.

TWO THINGS IT IS RESPONSIBLE FOR THAT NEITHER DOMAIN MODULE IS

  THE DETAIL POSITION reads `public.stock_position_detail_as_at` on a real
  database and `domain/reporting/stock_position.position_detail` in mock mode,
  the same split `stock_position_as_at` has had since migration 363 — and for
  the same reason: a report must not fetch rows proportional to transaction
  volume, and the answer here is one row per (item, godown, batch), not one per
  movement.

  THE TRANSFER, which moves stock between godowns and posts NOTHING. Within one
  entity the value of the stock does not change, so there is no journal to
  raise; where the two godowns are under different registrations it is a supply
  and the CA raises the tax invoice, because Rule 28's valuation option is not
  recorded anywhere here.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from core.db_paging import fetch_all
from domain.inventory import batches as batch_domain
from domain.inventory import location as loc

_logger = logging.getLogger("caflow.inventory")


def _live(rows: list) -> list:
    """Soft-deleted rows excluded IN PYTHON, so a row lacking the key reads as
    live — the direction every other reader in this codebase takes."""
    return [r for r in rows if not r.get("deleted_at")]


def _godown_rows(db, *, firm_id: str, client_id: str) -> list:
    return _live(fetch_all(
        lambda: db.table("godowns")
        .select("id, name, code, address, state_code, gstin, is_default, "
                "is_active, notes, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="inventory.godowns"))


def _as_godown(row: dict) -> loc.Godown:
    return loc.Godown(
        godown_id=str(row["id"]), name=row.get("name") or "",
        state_code=row.get("state_code"), gstin=row.get("gstin"),
        is_default=bool(row.get("is_default")),
        is_active=row.get("is_active") is not False)


def list_godowns(db, *, firm_id: str, client_id: str) -> dict:
    rows = _godown_rows(db, firm_id=firm_id, client_id=client_id)
    chosen = loc.default_godown([_as_godown(r) for r in rows])
    return {
        "godowns": rows,
        # WHICH ONE A MOVEMENT LANDS IN WITH NOTHING CHOSEN, resolved by the
        # domain module: the marked default, or the only active one, and None
        # where a client has several and has marked none. Never "the first".
        "default_godown_id": chosen.godown_id if chosen else None,
        "unallocated_means": loc.UNALLOCATED_MEANS,
    }


def create_godown(db, *, firm_id: str, client_id: str, name: str,
                  code: Optional[str], address: Optional[str],
                  state_code: Optional[str], gstin: Optional[str],
                  is_default: bool, notes: Optional[str],
                  actor_id: Optional[str]) -> dict:
    """Record a place this client keeps stock.

    ONE DEFAULT AT A TIME. Migration 398's partial unique index enforces it,
    and the previous default is cleared here rather than letting the insert
    fail — a CA marking a new warehouse as the default means that one, and a
    constraint violation would be a worse way to say so.
    """
    if is_default:
        db.table("godowns").update({"is_default": False}).eq(
            "firm_id", firm_id).eq("client_id", client_id).eq(
            "is_default", True).execute()
    rows = db.table("godowns").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "name": name,
        "code": code,
        "address": address,
        "state_code": state_code,
        "gstin": gstin,
        "is_default": bool(is_default),
        "is_active": True,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def close_godown(db, *, firm_id: str, client_id: str, godown_id: str) -> dict:
    """Close a godown. Stock still recorded there is REPORTED, not moved.

    Moving it would invent a transfer nobody made, and on a cross-registration
    pair that transfer would be a supply — so the refusal names what is still
    there and the CA transfers it deliberately.
    """
    rows = (db.table("godowns").select("id, name, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("id", godown_id).limit(1).execute().data) or []
    if not rows:
        return {"ok": False, "refusal": "That godown is not this client's."}
    held = _held_at(db, firm_id=firm_id, client_id=client_id, godown_id=godown_id)
    if held:
        return {"ok": False, "refusal": (
            f"{rows[0].get('name')} still holds stock "
            f"({len(held)} item(s)). Transfer it to another godown first — "
            f"moving it automatically would invent a transfer nobody made, and "
            f"between two registrations that transfer is a supply.")}
    db.table("godowns").update({
        "is_active": False,
        "is_default": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("firm_id", firm_id).eq("client_id", client_id).eq("id", godown_id).execute()
    return {"ok": True, "closed": True}


def _held_at(db, *, firm_id: str, client_id: str, godown_id: str) -> list:
    """Items with a non-zero position at one godown, as at today."""
    detail = position_detail(db, firm_id=firm_id, client_id=client_id,
                             as_of=date.today())
    return [r for r in detail.get("rows", [])
            if str(r.get("godown_id") or "") == str(godown_id)
            and Decimal(str(r.get("qty_units") or 0)) != 0]


# ── batches ─────────────────────────────────────────────────────────────────

def list_batches(db, *, firm_id: str, client_id: str,
                 service_catalogue_id: Optional[str] = None) -> list:
    # TWO SPELLED-OUT BRANCHES rather than one query built up in a variable:
    # `scan` in tests/_backend_query_parser resolves no names, so a select
    # whose receiver is a local is a blind spot to the column check.
    if service_catalogue_id:
        return _live(fetch_all(
            lambda: db.table("inventory_batches")
            .select("id, service_catalogue_id, batch_no, manufactured_on, "
                    "expiry_date, notes, deleted_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("service_catalogue_id", service_catalogue_id),
            key="id", label="inventory.batches"))
    return _live(fetch_all(
        lambda: db.table("inventory_batches")
        .select("id, service_catalogue_id, batch_no, manufactured_on, "
                "expiry_date, notes, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="inventory.batches"))


def create_batch(db, *, firm_id: str, client_id: str, service_catalogue_id: str,
                 batch_no: str, manufactured_on: Optional[str],
                 expiry_date: Optional[str], notes: Optional[str],
                 actor_id: Optional[str]) -> dict:
    rows = db.table("inventory_batches").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "service_catalogue_id": service_catalogue_id,
        "batch_no": batch_no,
        "manufactured_on": manufactured_on,
        # NULLABLE AND NOT DEFAULTED. Plenty of stock does not expire, and a
        # batch with no date is NAMED as having none rather than assumed sound.
        "expiry_date": expiry_date,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


# ── the position, one grain finer ───────────────────────────────────────────

def position_detail(db, *, firm_id: str, client_id: str, as_of: date,
                    service_catalogue_id: Optional[str] = None) -> dict:
    """Per (item, godown, batch) as at a date.

    THE SQL FUNCTION ON A REAL DATABASE, the Python twin in mock mode — the
    same split `stock_position_as_at` has had since migration 363, pinned by a
    parity test. Reading the ledger here and summing in Python would fetch rows
    proportional to transaction volume for an answer proportional to the number
    of (item, godown, batch) combinations, which is the rule CLAUDE.md states.
    """
    try:
        resp = db.rpc("stock_position_detail_as_at", {
            "p_firm": firm_id, "p_client": client_id,
            "p_as_of": as_of.isoformat(),
            "p_item": service_catalogue_id,
        }).execute()
        data = getattr(resp, "data", None)
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001 — mock mode has no SQL functions
        _logger.debug("stock_position_detail_as_at unavailable; using the twin",
                      exc_info=True)

    from domain.reporting import stock_position as sp
    movements = fetch_all(
        lambda: db.table("inventory_stock_ledger")
        .select("id, service_catalogue_id, movement_date, quantity_delta, "
                "value_delta_paise, godown_id, batch_id")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="inventory.detail_movements")
    if service_catalogue_id:
        movements = [m for m in movements
                     if str(m.get("service_catalogue_id")) == str(service_catalogue_id)]
    items = fetch_all(
        lambda: db.table("service_catalogue").select("id, name, unit")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="inventory.detail_items")
    godowns = _godown_rows(db, firm_id=firm_id, client_id=client_id)
    bats = list_batches(db, firm_id=firm_id, client_id=client_id)
    return sp.position_detail(
        movements, as_of.isoformat(),
        names={str(i["id"]): i for i in items},
        godowns={str(g["id"]): g for g in godowns},
        batches={str(b["id"]): b for b in bats})


def expiry_report(db, *, firm_id: str, client_id: str, as_of: date) -> dict:
    """What is expiring, and what has — built from the detail position."""
    detail = position_detail(db, firm_id=firm_id, client_id=client_id, as_of=as_of)
    positions = [
        batch_domain.BatchPosition(
            batch_id=r.get("batch_id"),
            batch_no=r.get("batch_no"),
            service_catalogue_id=str(r.get("service_catalogue_id") or ""),
            item_name=r.get("item_name") or "",
            quantity=Decimal(str(r.get("qty_units") or 0)),
            value_paise=int(r.get("value_paise") or 0),
            expiry_date=(date.fromisoformat(str(r["expiry_date"])[:10])
                         if r.get("expiry_date") else None),
            godown_id=r.get("godown_id"),
            godown_name=r.get("godown_name"),
        )
        # ONLY BATCHED ROWS. An item held without a lot has nothing to expire
        # and listing it would bury the batches that do under everything else.
        for r in detail.get("rows", []) if r.get("batch_id")
    ]
    return batch_domain.expiry_report(positions, as_of=as_of).as_dict()


# ── the transfer ────────────────────────────────────────────────────────────

def transfer_preview(db, *, firm_id: str, client_id: str,
                     from_godown_id: str, to_godown_id: str) -> dict:
    """Whether moving stock between these two godowns is a supply.

    ASKED BEFORE THE MOVE and served on its own, because it is the one thing a
    CA must know first: between two registrations the movement needs a tax
    invoice, and that is a decision about a document rather than about stock.
    """
    rows = {str(r["id"]): r for r in
            _godown_rows(db, firm_id=firm_id, client_id=client_id)}
    src, dst = rows.get(str(from_godown_id)), rows.get(str(to_godown_id))
    if not src or not dst:
        return {"ok": False, "refusal": "Both godowns must be this client's."}
    return {"ok": True,
            **loc.transfer_decision(_as_godown(src), _as_godown(dst)).as_dict()}


def transfer(db, *, firm_id: str, client_id: str, service_catalogue_id: str,
             from_godown_id: str, to_godown_id: str, quantity: str,
             movement_date: str, batch_id: Optional[str] = None,
             reference_no: Optional[str] = None, notes: Optional[str] = None,
             actor_id: Optional[str] = None) -> dict:
    """Move stock from one godown to another.

    TWO LEDGER ROWS AND NO JOURNAL. Within one entity the stock is worth what
    it was worth before it was carried across the yard, so there is nothing for
    the general ledger to record — and the two rows carry equal and opposite
    value, so every total that already ties still ties.

    THE VALUE MOVED IS THE SOURCE GODOWN'S OWN. Not the item's average across
    every location: taking the average would move a different number out than
    in if the two godowns hold stock at different costs, and the per-godown
    position would drift from the total it must sum to.

    IT DOES NOT MINT THE TAX INVOICE a cross-registration transfer needs. The
    decision is returned so the caller can show it; Rule 28's valuation option
    is the client's and is recorded nowhere here.
    """
    rows = {str(r["id"]): r for r in
            _godown_rows(db, firm_id=firm_id, client_id=client_id)}
    src, dst = rows.get(str(from_godown_id)), rows.get(str(to_godown_id))
    if not src or not dst:
        return {"ok": False, "refusal": "Both godowns must be this client's."}
    if str(from_godown_id) == str(to_godown_id):
        return {"ok": False, "refusal": "The source and destination are the same godown."}
    for row in (src, dst):
        refusal = loc.refusal_for([_as_godown(r) for r in rows.values()],
                                  str(row["id"]))
        if refusal:
            return {"ok": False, "refusal": refusal}

    qty = Decimal(str(quantity))
    if qty <= 0:
        return {"ok": False, "refusal": "A transfer moves a positive quantity."}

    when = date.fromisoformat(str(movement_date)[:10])
    detail = position_detail(db, firm_id=firm_id, client_id=client_id, as_of=when,
                             service_catalogue_id=service_catalogue_id)
    here = [r for r in detail.get("rows", [])
            if str(r.get("godown_id") or "") == str(from_godown_id)
            and str(r.get("batch_id") or "") == str(batch_id or "")]
    available = sum(Decimal(str(r.get("qty_units") or 0)) for r in here)
    if available < qty:
        return {"ok": False, "refusal": (
            f"Only {available} is held at {src.get('name')} on "
            f"{when.isoformat()}; the transfer moves {qty}. Stock cannot be "
            f"moved out of a godown that does not have it.")}
    value_held = sum(int(r.get("value_paise") or 0) for r in here)
    # Pro-rata on quantity, floored — the remainder stays at the source, which
    # is the direction that cannot move value the source does not have.
    value = int((Decimal(value_held) * qty / available)) if available else 0

    decision = loc.transfer_decision(_as_godown(src), _as_godown(dst))
    # THE RUNNING TOTALS ARE CARRIED FORWARD UNCHANGED, and both parts of that
    # are load-bearing. They are NOT NULL with no default, so omitting them is
    # a write PostgREST rejects outright — a real defect this service had until
    # the payload was written out inline where the insert guard could read it.
    # And unchanged is the RIGHT value: `inventory_stock_ledger`'s running
    # columns are the ITEM's position chained in insertion order
    # (`_last_ledger_row` explains why), and a transfer moves stock between two
    # of the client's own shelves — the item's quantity, value and average cost
    # are exactly what they were. Recomputing them would make the chain
    # disagree with itself across a pair that nets to zero.
    from domain.inventory_service import _last_ledger_row
    previous = _last_ledger_row(db, service_catalogue_id) or {}
    running_qty = previous.get("running_qty_units", "0")
    running_value = int(previous.get("running_value_paise") or 0)
    running_avg = int(previous.get("running_avg_cost_paise") or 0)

    # `unit_cost_paise` is THIS MOVEMENT's own rate, not the item's blended
    # average: the transfer carries the SOURCE godown's cost, and displaying
    # the average beside a value that is not the average's would put two
    # figures on one row that do not multiply out.
    unit_cost = int(Decimal(value) / qty) if qty else 0

    # BOTH ROWS SPELLED OUT IN FULL, and the repetition is deliberate. A
    # `**stamp` spread reads better and is invisible to
    # `tests/test_backend_inserts_supply_every_required_column_pg.py`, which
    # resolves no names — so a column that does not exist in one of them would
    # be a write nobody notices failing, and PostgREST rejects the WHOLE insert
    # on one such column. The same reason `routers/bills_of_entry.py` spells
    # its insert out.
    db.table("inventory_stock_ledger").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "service_catalogue_id": service_catalogue_id,
        "movement_date": when.isoformat(),
        "movement_type": "transfer",
        "reference_no": reference_no,
        "batch_id": batch_id,
        "notes": notes,
        "created_by": actor_id,
        "godown_id": from_godown_id,
        "quantity_delta": str(-qty),
        "value_delta_paise": -value,
        "unit_cost_paise": unit_cost,
        "running_qty_units": running_qty,
        "running_value_paise": running_value,
        "running_avg_cost_paise": running_avg,
    }).execute()
    db.table("inventory_stock_ledger").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "service_catalogue_id": service_catalogue_id,
        "movement_date": when.isoformat(),
        "movement_type": "transfer",
        "reference_no": reference_no,
        "batch_id": batch_id,
        "notes": notes,
        "created_by": actor_id,
        "godown_id": to_godown_id,
        "quantity_delta": str(qty),
        "value_delta_paise": value,
        "unit_cost_paise": unit_cost,
        "running_qty_units": running_qty,
        "running_value_paise": running_value,
        "running_avg_cost_paise": running_avg,
    }).execute()

    return {"ok": True, "quantity": str(qty), "value_paise": value,
            "decision": decision.as_dict()}

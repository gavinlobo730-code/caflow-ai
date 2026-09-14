"""Reading and changing a client's cost formula — AS-2 paragraph 14 (INV-02).

This module FETCHES; `domain/inventory/costing.py` DECIDES. Nothing here
chooses a formula, judges whether a change is permitted, or words a refusal.

WHAT THE CHANGE PATH HAS TO ESTABLISH, and why it is a read rather than a
rule: a change of cost formula is prospective, so it can only take effect from
a date on or after which no stock has moved. That is a fact about the ledger,
which the domain module has no database handle to ask — so it is read here and
handed over, the same split `domain/gst/credit_note_window` and its caller use.
"""
from __future__ import annotations

from typing import Optional

from core.db_paging import fetch_all
from domain.inventory import costing


def read_policy(db, *, firm_id: str, client_id: str) -> dict:
    """What formula this client is on, what the alternatives are, and what a
    change would mean. Reads nothing but the client row."""
    rows = (
        db.table("clients").select("id, inventory_costing_method")
        .eq("firm_id", firm_id).eq("id", client_id).limit(1).execute().data
    ) or []
    recorded = rows[0].get("inventory_costing_method") if rows else None
    policy = costing.policy_for(client_id, recorded)
    return {
        "client_id": client_id,
        "method": policy.method,
        "label": policy.label,
        # WHETHER ANYBODY HAS CHOSEN is a different fact from WHICH formula is
        # in force, and the screen renders them differently: an unrecorded
        # client is on the weighted average and has not said so.
        "is_recorded": bool(recorded),
        "unrecorded_means": None if recorded else costing.UNRECORDED_MEANS,
        "methods": [{"value": m, "label": costing.METHOD_LABELS[m]}
                    for m in costing.METHODS],
        "standard_cost_refused": costing.STANDARD_COST_REFUSED,
        "as5_disclosure": costing.AS5_DISCLOSURE,
        "earliest_date_a_change_can_take_effect":
            _earliest_prospective_date(db, firm_id=firm_id, client_id=client_id),
    }


def _last_movement_date(db, *, firm_id: str, client_id: str) -> Optional[str]:
    rows = (
        db.table("inventory_stock_ledger").select("movement_date")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .order("movement_date", desc=True).limit(1).execute().data
    ) or []
    return (str(rows[0].get("movement_date"))[:10] or None) if rows else None


def _earliest_prospective_date(db, *, firm_id: str, client_id: str) -> Optional[str]:
    """The day after the last recorded movement — what the screen pre-fills.

    A SUGGESTION, not the rule: `costing.switch_refusal` decides, off the
    movement this service reads back at the moment of the change. Offering it
    saves the CA guessing a date the server is going to refuse.
    """
    last = _last_movement_date(db, firm_id=firm_id, client_id=client_id)
    if not last:
        return None
    from datetime import date, timedelta
    y, m, d = (int(x) for x in last.split("-"))
    return (date(y, m, d) + timedelta(days=1)).isoformat()


def movement_on_or_after(db, *, firm_id: str, client_id: str,
                         effective_from: str) -> Optional[str]:
    """The earliest stock movement dated on or after `effective_from`, if any.

    Read as ONE row rather than a count: the refusal names the date, and a
    count would make the CA go looking for it.
    """
    rows = (
        db.table("inventory_stock_ledger").select("movement_date")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .gte("movement_date", effective_from)
        .order("movement_date", desc=False).limit(1).execute().data
    ) or []
    return str(rows[0].get("movement_date"))[:10] if rows else None


def set_policy(db, *, firm_id: str, client_id: str, method: str,
               effective_from: Optional[str]) -> dict:
    """Record the client's cost formula, or say why it cannot be recorded.

    Returns `{"ok": False, "refusal": "..."}` rather than raising, because
    every refusal here is a sentence the CA has to read and act on — a date to
    change, or a formula that is already in force.
    """
    rows = (
        db.table("clients").select("id, inventory_costing_method")
        .eq("firm_id", firm_id).eq("id", client_id).limit(1).execute().data
    ) or []
    if not rows:
        return {"ok": False, "refusal": "That client is not in this firm."}
    current = rows[0].get("inventory_costing_method")

    seen = (movement_on_or_after(db, firm_id=firm_id, client_id=client_id,
                                 effective_from=effective_from)
            if effective_from else None)
    refusal = costing.switch_refusal(
        current=current, wanted=(method or "").strip().lower(),
        effective_from=effective_from, movement_on_or_after=seen,
    )
    if refusal:
        return {"ok": False, "refusal": refusal}

    db.table("clients").update(
        {"inventory_costing_method": method.strip().lower()}
    ).eq("firm_id", firm_id).eq("id", client_id).execute()
    return {"ok": True, **read_policy(db, firm_id=firm_id, client_id=client_id),
            "effective_from": effective_from}


def ledger_methods_used(db, *, firm_id: str, client_id: str) -> list:
    """Which formulas have actually priced this client's movements, earliest
    first — the AS-5 paragraph 32 disclosure, derived rather than remembered.

    `inventory_stock_ledger.costing_method` is stamped on every row, so the
    period a change took effect from is a property of the ledger. Nothing
    stores it, for migration 278's reason: a stored date is wrong the moment a
    backdated document lands.
    """
    rows = fetch_all(
        lambda: db.table("inventory_stock_ledger")
        .select("id, movement_date, costing_method")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="inventory.costing_method_spans")
    spans: dict = {}
    for r in rows:
        m = r.get("costing_method") or costing.METHOD_WHEN_UNRECORDED
        d = str(r.get("movement_date") or "")[:10]
        if not d:
            continue
        cur = spans.get(m)
        spans[m] = (min(cur[0], d), max(cur[1], d)) if cur else (d, d)
    return sorted(
        ({"method": m, "label": costing.METHOD_LABELS.get(m, m),
          "first_movement": lo, "last_movement": hi}
         for m, (lo, hi) in spans.items()),
        key=lambda x: x["first_movement"])

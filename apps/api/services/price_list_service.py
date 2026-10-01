"""Price lists and a default list per customer (accounting-20, migration 459).

The rule is `domain/sales/price_list.py` — read its header first. A price list is
a PRE-FILL source for the rate of an invoice line and nothing more: it changes no
tax and posts nothing, and the sales-invoice create path never reads it, so an
invoice keeps whatever rate it was given. This module keeps the lists and answers
`resolve_rate` when a catalogue item is picked.

Every read and write carries `firm_id` and `client_id`. A list belongs to ONE
client, because a catalogue item is client-owned (migration 182) and a list that
spanned clients would price an item that is not the client's own. The database
refuses an item filed under the wrong client (a composite key); the two facts it
cannot — that the catalogue item and the customer belong to the same client as the
list — are checked here, and answered as "not found", never as "exists elsewhere".

`customers.price_list_id` HAS ONE WRITER, `assign`. The customer form, the import
and the Tally migration do not touch it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_in
from domain.sales import price_list as D

_logger = logging.getLogger("caflow.price_lists")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(err: Exception) -> bool:
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def _audit(firm_id: str, entity: str, entity_id: str, action: str,
           actor: Optional[dict], data: dict) -> None:
    """The edit log. `audit_log.actor_id` takes the AUTH id."""
    try:
        from services.audit_service import log_event
        log_event(firm_id, entity, entity_id, action,
                  actor_id=(actor or {}).get("auth_user_id"), new_data=data,
                  metadata={"source": "price_lists"})
    except Exception:                                      # pragma: no cover - audit never blocks
        _logger.warning("could not write the audit entry for %s %s", entity, entity_id)


# ── Lists ────────────────────────────────────────────────────────────────────

def _get_list(db, firm_id: str, client_id: str, list_id: str) -> dict:
    rows = (db.table("price_lists")
            .select("id, client_id, name, description, is_active, created_at, updated_at")
            .eq("id", list_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Price list not found.")
    return rows[0]


def list_lists(db, firm_id: str, client_id: str, include_archived: bool = False) -> list[dict]:
    def one_page():
        q = (db.table("price_lists")
             .select("id, client_id, name, description, is_active, created_at, updated_at")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        return q if include_archived else q.eq("is_active", True)

    rows = fetch_all(one_page, label="price_lists.lists")
    rows.sort(key=lambda r: str(r.get("name") or "").lower())
    return rows


def _check_name_free(db, firm_id: str, client_id: str, name: str,
                     except_id: Optional[str] = None) -> None:
    rows = fetch_all(lambda: (
        db.table("price_lists").select("id, name")
        .eq("firm_id", firm_id).eq("client_id", client_id)), label="price_lists.names")
    wanted = D.normalise_name(name).lower()
    for r in rows:
        if r["id"] != except_id and D.normalise_name(r.get("name")).lower() == wanted:
            raise HTTPException(status_code=409, detail=(
                f"This client already has a price list called {D.normalise_name(r.get('name'))}."))


def create_list(db, firm_id: str, client_id: str, name: str, description: Optional[str],
                actor: Optional[dict] = None) -> dict:
    problem = D.name_problem(name)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    _check_name_free(db, firm_id, client_id, name)
    try:
        saved = (db.table("price_lists").insert({
            "firm_id": firm_id, "client_id": client_id, "name": D.normalise_name(name),
            "description": (description or "").strip() or None, "is_active": True,
            "created_by": (actor or {}).get("id"),
        }).execute().data) or []
    except Exception as e:
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail=(
                "A price list with that name was just created.")) from e
        raise
    row = saved[0]
    _audit(firm_id, "price_list", row["id"], "create", actor, {"name": row.get("name")})
    return row


def update_list(db, firm_id: str, client_id: str, list_id: str, changes: dict,
                actor: Optional[dict] = None) -> dict:
    """Rename, describe or archive. Archiving does not touch a customer pointing at
    the list: they fall back to the catalogue rate, and the answer says so."""
    current = _get_list(db, firm_id, client_id, list_id)
    name = changes["name"] if "name" in changes else current["name"]
    problem = D.name_problem(name)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if "name" in changes:
        _check_name_free(db, firm_id, client_id, name, except_id=list_id)
    description = changes["description"] if "description" in changes else current.get("description")
    is_active = bool(changes["is_active"]) if "is_active" in changes else current["is_active"]
    try:
        saved = (db.table("price_lists").update({
            "name": D.normalise_name(name),
            "description": (description or "").strip() or None,
            "is_active": is_active, "updated_at": _now(),
        }).eq("id", list_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    except Exception as e:
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail=(
                "A price list with that name already exists.")) from e
        raise
    _audit(firm_id, "price_list", list_id, "update", actor, {"changed": sorted(changes)})
    return saved[0] if saved else {**current, "name": name, "is_active": is_active}


# ── A list's rates ───────────────────────────────────────────────────────────

def list_items(db, firm_id: str, client_id: str, list_id: str) -> dict:
    """A list's rates beside the catalogue's own, so the CA sees what each differs
    from."""
    price_list = _get_list(db, firm_id, client_id, list_id)
    rows = fetch_all(lambda: (
        db.table("price_list_items")
        .select("id, price_list_id, service_catalogue_id, rate_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("price_list_id", list_id)),
        label="price_lists.items")
    catalogue = fetch_all_in(lambda: (
        db.table("service_catalogue")
        .select("id, name, hsn_sac, unit, default_rate_paise, is_active")
        .eq("firm_id", firm_id).eq("client_id", client_id)),
        "id", [r["service_catalogue_id"] for r in rows], label="price_lists.catalogue")
    by_id = {c["id"]: c for c in catalogue}
    items = []
    for r in rows:
        c = by_id.get(r["service_catalogue_id"], {})
        items.append({
            "id": r["id"], "service_catalogue_id": r["service_catalogue_id"],
            "name": c.get("name"), "hsn_sac": c.get("hsn_sac"), "unit": c.get("unit"),
            "is_active": c.get("is_active"),
            "rate_paise": int(r["rate_paise"]),
            "catalogue_rate_paise": int(c.get("default_rate_paise") or 0) or None,
        })
    items.sort(key=lambda i: str(i["name"] or "").lower())
    return {"price_list": price_list, "items": items}


def _check_catalogue_item(db, firm_id: str, client_id: str, service_catalogue_id: str) -> None:
    found = (db.table("service_catalogue").select("id")
             .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", client_id)
             .limit(1).execute().data) or []
    if not found:
        raise HTTPException(status_code=404, detail="Product or service not found.")


def set_item(db, firm_id: str, client_id: str, list_id: str, service_catalogue_id: str,
             rate_paise, actor: Optional[dict] = None) -> dict:
    """Give an item a rate on a list, or change it. One rate per item per list."""
    problem = D.rate_problem(rate_paise)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    _get_list(db, firm_id, client_id, list_id)
    _check_catalogue_item(db, firm_id, client_id, service_catalogue_id)
    existing = (db.table("price_list_items").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("price_list_id", list_id).eq("service_catalogue_id", service_catalogue_id)
                .limit(1).execute().data) or []
    if existing:
        saved = (db.table("price_list_items").update({
            "rate_paise": int(rate_paise), "updated_at": _now(),
        }).eq("id", existing[0]["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
        action = "update_item"
    else:
        try:
            saved = (db.table("price_list_items").insert({
                "firm_id": firm_id, "client_id": client_id, "price_list_id": list_id,
                "service_catalogue_id": service_catalogue_id, "rate_paise": int(rate_paise),
            }).execute().data) or []
        except Exception as e:
            if _is_unique_violation(e):
                raise HTTPException(status_code=409, detail=(
                    "That item was just priced on this list; reload and edit it.")) from e
            raise
        action = "add_item"
    row = saved[0] if saved else {"price_list_id": list_id,
                                  "service_catalogue_id": service_catalogue_id,
                                  "rate_paise": int(rate_paise)}
    _audit(firm_id, "price_list", list_id, action, actor,
           {"service_catalogue_id": service_catalogue_id, "rate_paise": int(rate_paise)})
    return row


def remove_item(db, firm_id: str, client_id: str, list_id: str, service_catalogue_id: str,
                actor: Optional[dict] = None) -> dict:
    """Take an item off a list: the catalogue rate then applies to it."""
    _get_list(db, firm_id, client_id, list_id)
    gone = (db.table("price_list_items").delete()
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("price_list_id", list_id).eq("service_catalogue_id", service_catalogue_id)
            .execute().data) or []
    if not gone:
        raise HTTPException(status_code=404, detail="That item is not on this list.")
    _audit(firm_id, "price_list", list_id, "remove_item", actor,
           {"service_catalogue_id": service_catalogue_id})
    return {"removed": True, "service_catalogue_id": service_catalogue_id}


# ── The customer's default list ──────────────────────────────────────────────

def customer_assignments(db, firm_id: str, client_id: str) -> list[dict]:
    """Each customer of the client and the list they are on, if any."""
    people = fetch_all(lambda: (
        db.table("customers").select("id, name, price_list_id, is_active")
        .eq("firm_id", firm_id).eq("client_id", client_id)), label="price_lists.customers")
    lists = {r["id"]: r for r in list_lists(db, firm_id, client_id, include_archived=True)}
    out = []
    for c in people:
        pl = lists.get(c.get("price_list_id")) if c.get("price_list_id") else None
        out.append({
            "customer_id": c["id"], "customer_name": c.get("name"),
            "is_active": c.get("is_active") is not False,
            "price_list_id": c.get("price_list_id"),
            "price_list_name": pl.get("name") if pl else None,
            "price_list_archived": bool(pl) and not pl.get("is_active"),
        })
    out.sort(key=lambda r: str(r["customer_name"] or "").lower())
    return out


def assign(db, firm_id: str, client_id: str, customer_id: str, price_list_id: Optional[str],
           actor: Optional[dict] = None) -> dict:
    """Set (or clear, with None) a customer's default list. THE one writer of
    `customers.price_list_id`. A list to assign must be this client's and active:
    pointing a customer at an archived list would be a pointer that does nothing."""
    found = (db.table("customers").select("id, name")
             .eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id)
             .limit(1).execute().data) or []
    if not found:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if price_list_id is not None:
        target = _get_list(db, firm_id, client_id, price_list_id)
        if not target["is_active"]:
            raise HTTPException(status_code=409, detail=(
                "That price list is archived. Restore it, or choose another."))
    (db.table("customers").update({"price_list_id": price_list_id})
     .eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id).execute())
    _audit(firm_id, "customer", customer_id, "price_list_assigned", actor,
           {"price_list_id": price_list_id})
    return {"customer_id": customer_id, "customer_name": found[0].get("name"),
            "price_list_id": price_list_id}


# ── The pre-fill ─────────────────────────────────────────────────────────────

def resolve_rate(db, firm_id: str, client_id: str, customer_id: str,
                 service_catalogue_id: str) -> dict:
    """The rate to pre-fill when `service_catalogue_id` is picked for this
    customer, where it came from and why. Reads; writes nothing; and changes no
    invoice — the line keeps whatever rate it ends up with."""
    customer = (db.table("customers").select("id, price_list_id")
                .eq("id", customer_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .limit(1).execute().data) or []
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found.")
    item = (db.table("service_catalogue").select("id, default_rate_paise")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data) or []
    if not item:
        raise HTTPException(status_code=404, detail="Product or service not found.")
    list_id = customer[0].get("price_list_id")
    name, active, list_rate = None, False, None
    if list_id:
        lists = (db.table("price_lists").select("id, name, is_active")
                 .eq("id", list_id).eq("firm_id", firm_id).eq("client_id", client_id)
                 .limit(1).execute().data) or []
        if lists:
            name, active = lists[0].get("name"), bool(lists[0].get("is_active"))
            rates = (db.table("price_list_items").select("rate_paise")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .eq("price_list_id", list_id).eq("service_catalogue_id", service_catalogue_id)
                     .limit(1).execute().data) or []
            list_rate = rates[0].get("rate_paise") if rates else None
        else:
            list_id = None          # a dangling pointer is no list
    return D.resolve(list_id=list_id, list_name=name, list_active=active,
                     list_rate_paise=list_rate,
                     catalogue_rate_paise=item[0].get("default_rate_paise"))

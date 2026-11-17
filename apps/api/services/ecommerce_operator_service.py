"""What an e-commerce operator's sellers supplied through it (GST-25, GSTR-8).

`domain/gst/gstr8.py` is the rule; this fetches and writes the two tables
migration 421 created and the two amendment tables of migration 617, which a
signed-in session cannot even read, so every query of those two is made on the
privileged client. Nothing here decides whether a figure reconciles —
that is the domain module's job, asked by `services.gst_return_service
.gstr8_statement`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.db_provider import privileged_for
from domain.gst.gstr8 import AmendmentRow, UnregisteredAmendmentRow

def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


# ── Table 3 — registered sellers ────────────────────────────────────────────

def list_supplies(db, firm_id: str, client_id: str, gstin: str,
                  period: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("ecommerce_operator_supplies").select(
            "id, firm_id, client_id, gstin, period, supplier_gstin, "
            "place_of_supply, gross_registered_paise, "
            "returns_registered_paise, gross_unregistered_paise, "
            "returns_unregistered_paise, igst_paise, cgst_paise, sgst_paise, "
            "notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("period", period)
        .is_("deleted_at", "null"),
        key="id", label="ecommerce_operator_supplies")


def _existing_supply(db, firm_id: str, client_id: str, gstin: str, period: str,
                     supplier_gstin: str) -> Optional[dict]:
    return _first(db.table("ecommerce_operator_supplies").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("period", period)
                  .eq("supplier_gstin", supplier_gstin)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_supply(db, firm_id: str, client_id: str, *, gstin: str, period: str,
                  supplier_gstin: str, place_of_supply: Optional[str] = None,
                  gross_registered_paise: int = 0,
                  returns_registered_paise: int = 0,
                  gross_unregistered_paise: int = 0,
                  returns_unregistered_paise: int = 0,
                  igst_paise: int = 0, cgst_paise: int = 0, sgst_paise: int = 0,
                  notes: Optional[str] = None,
                  actor_id: Optional[str] = None) -> dict:
    """Record or correct one registered seller's figures for the period.

    A SECOND call for the same (client, operator GSTIN, period, seller GSTIN)
    UPDATES the row rather than adding a duplicate — the unique index migration
    421 declares is the identity of "this seller's entry for this month", and a
    CA revising a figure before the return is finalised should not have to
    delete and re-add it.

    The two dicts below repeat each key literally rather than building one
    payload dict and spreading it into both — a `**payload` spread is a
    computed key `test_backend_columns_exist_pg.py`'s AST scan cannot read at
    all, which would take every column named here out of the schema check
    (CLAUDE.md's `domain/firm/identity.py` note records the same trade and
    takes the same side of it: duplicated keys, not an unreadable write).
    """
    existing = _existing_supply(db, firm_id, client_id, gstin, period, supplier_gstin)
    if existing:
        rows = (privileged_for(db).table("ecommerce_operator_supplies")
                .update({
                    "place_of_supply": place_of_supply,
                    "gross_registered_paise": gross_registered_paise,
                    "returns_registered_paise": returns_registered_paise,
                    "gross_unregistered_paise": gross_unregistered_paise,
                    "returns_unregistered_paise": returns_unregistered_paise,
                    "igst_paise": igst_paise,
                    "cgst_paise": cgst_paise,
                    "sgst_paise": sgst_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = privileged_for(db).table("ecommerce_operator_supplies").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "period": period,
        "supplier_gstin": supplier_gstin,
        "place_of_supply": place_of_supply,
        "gross_registered_paise": gross_registered_paise,
        "returns_registered_paise": returns_registered_paise,
        "gross_unregistered_paise": gross_unregistered_paise,
        "returns_unregistered_paise": returns_unregistered_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_supply(db, firm_id: str, client_id: str, supply_id: str) -> dict:
    """Withdraw an entry of THIS client recorded in error. Soft-deleted, like every other
    document this product keeps an edit trail on. The client is part of the key: the id alone
    names an entry of any client of the firm (POST-A-337)."""
    rows = (privileged_for(db).table("ecommerce_operator_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 3.1 — sellers holding only a Rule 12(1A) Enrolment ID ─────────────

def list_unregistered_supplies(db, firm_id: str, client_id: str, gstin: str,
                               period: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("ecommerce_operator_unregistered_supplies").select(
            "id, firm_id, client_id, gstin, period, enrolment_id, "
            "gross_value_paise, returns_paise, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("period", period)
        .is_("deleted_at", "null"),
        key="id", label="ecommerce_operator_unregistered_supplies")


def _existing_unregistered_supply(db, firm_id: str, client_id: str, gstin: str,
                                  period: str, enrolment_id: str) -> Optional[dict]:
    return _first(db.table("ecommerce_operator_unregistered_supplies").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("period", period)
                  .eq("enrolment_id", enrolment_id)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_unregistered_supply(db, firm_id: str, client_id: str, *, gstin: str,
                               period: str, enrolment_id: str,
                               gross_value_paise: int = 0, returns_paise: int = 0,
                               notes: Optional[str] = None,
                               actor_id: Optional[str] = None) -> dict:
    """Same upsert-by-natural-key shape as `record_supply`, and the same
    reason its two dicts repeat their keys literally rather than spreading a
    shared payload — see that function's docstring."""
    existing = _existing_unregistered_supply(db, firm_id, client_id, gstin,
                                             period, enrolment_id)
    if existing:
        rows = (privileged_for(db).table("ecommerce_operator_unregistered_supplies")
                .update({
                    "gross_value_paise": gross_value_paise,
                    "returns_paise": returns_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = privileged_for(db).table("ecommerce_operator_unregistered_supplies").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "period": period,
        "enrolment_id": enrolment_id,
        "gross_value_paise": gross_value_paise,
        "returns_paise": returns_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_unregistered_supply(db, firm_id: str, client_id: str, supply_id: str) -> dict:
    """Withdraw an unregistered-supply entry of THIS client (POST-A-337)."""
    rows = (privileged_for(db).table("ecommerce_operator_unregistered_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 4 — an amendment of a registered seller's row of an EARLIER month (POST-A-056, migration 617) ───────────────────────────────

def list_amendments(db, firm_id: str, client_id: str, gstin: str, period: str) -> list[dict]:
    """The Table 4 rows declared in `period`'s statement, each naming the earlier month and seller it amends, with the revised figures'
    net as the domain derives it (`net_liable_paise`): the screen shows what the server says and sums nothing itself.

    Every query of the two amendment tables, a READ included, is made on `privileged_for(db)`: migration 617 leaves a signed-in
    session no privilege on them at all, so under `USE_USER_JWT` the caller's own session is refused 42501. The privileged client
    carries no row security, so the firm and the client are named on every query; the routes assert the caller's access to the
    client before they reach here."""
    rows = fetch_all(
        lambda: privileged_for(db).table("ecommerce_operator_supply_amendments").select(
            "id, firm_id, client_id, gstin, period, original_period, original_supplier_gstin, "
            "original_place_of_supply, supplier_gstin, place_of_supply, gross_registered_paise, "
            "returns_registered_paise, gross_unregistered_paise, returns_unregistered_paise, "
            "igst_paise, cgst_paise, sgst_paise, action, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("period", period)
        .is_("deleted_at", "null"),
        key="id", label="ecommerce_operator_supply_amendments")
    return [{**r, "net_liable_paise": AmendmentRow.from_record(r).net_liable_paise} for r in rows]


def _existing_amendment(db, firm_id: str, client_id: str, gstin: str, period: str, original_period: str,
                        original_supplier_gstin: str, original_place_of_supply: Optional[str]) -> Optional[dict]:
    """The row with this natural key: the utility's own duplicate key (original month + original supplier, and from FY 2025-26 the
    original place of supply), which migration 617's unique index is. A NULL place of supply is a value of the key, not a wildcard."""
    query = (privileged_for(db).table("ecommerce_operator_supply_amendments").select("id")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .eq("gstin", gstin).eq("period", period)
             .eq("original_period", original_period)
             .eq("original_supplier_gstin", original_supplier_gstin)
             .is_("deleted_at", "null"))
    query = (query.eq("original_place_of_supply", original_place_of_supply) if original_place_of_supply
             else query.is_("original_place_of_supply", "null"))
    return _first(query.limit(1).execute().data)


def record_amendment(db, firm_id: str, client_id: str, *, gstin: str, period: str, original_period: str,
                     original_supplier_gstin: str, original_place_of_supply: Optional[str] = None,
                     supplier_gstin: str, place_of_supply: Optional[str] = None,
                     gross_registered_paise: int = 0, returns_registered_paise: int = 0,
                     gross_unregistered_paise: int = 0, returns_unregistered_paise: int = 0,
                     igst_paise: int = 0, cgst_paise: int = 0, sgst_paise: int = 0,
                     action: str, notes: Optional[str] = None, actor_id: Optional[str] = None) -> dict:
    """Record or correct one Table 4 row. A SECOND call for the same amended row (the key above) UPDATES it, as `record_supply` does,
    so a CA revising the figures before the statement is prepared does not delete and re-add. The two dicts repeat each key literally,
    for the reason `record_supply` gives."""
    existing = _existing_amendment(db, firm_id, client_id, gstin, period, original_period,
                                   original_supplier_gstin, original_place_of_supply)
    if existing:
        rows = (privileged_for(db).table("ecommerce_operator_supply_amendments")
                .update({
                    "supplier_gstin": supplier_gstin,
                    "place_of_supply": place_of_supply,
                    "gross_registered_paise": gross_registered_paise,
                    "returns_registered_paise": returns_registered_paise,
                    "gross_unregistered_paise": gross_unregistered_paise,
                    "returns_unregistered_paise": returns_unregistered_paise,
                    "igst_paise": igst_paise,
                    "cgst_paise": cgst_paise,
                    "sgst_paise": sgst_paise,
                    "action": action,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = privileged_for(db).table("ecommerce_operator_supply_amendments").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "period": period,
        "original_period": original_period,
        "original_supplier_gstin": original_supplier_gstin,
        "original_place_of_supply": original_place_of_supply,
        "supplier_gstin": supplier_gstin,
        "place_of_supply": place_of_supply,
        "gross_registered_paise": gross_registered_paise,
        "returns_registered_paise": returns_registered_paise,
        "gross_unregistered_paise": gross_unregistered_paise,
        "returns_unregistered_paise": returns_unregistered_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "action": action,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_amendment(db, firm_id: str, client_id: str, amendment_id: str) -> dict:
    """Withdraw a Table 4 row of THIS client recorded in error (soft-deleted, the client part of the key: POST-A-337)."""
    rows = (privileged_for(db).table("ecommerce_operator_supply_amendments")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", amendment_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 4.1 — an amendment of an Enrolment-ID seller's row ──────────────────────────────────────────────────────────────────────────

def list_unregistered_amendments(db, firm_id: str, client_id: str, gstin: str, period: str) -> list[dict]:
    rows = fetch_all(
        lambda: privileged_for(db).table("ecommerce_operator_unregistered_supply_amendments").select(
            "id, firm_id, client_id, gstin, period, original_period, original_enrolment_id, "
            "enrolment_id, gross_value_paise, returns_paise, action, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("period", period)
        .is_("deleted_at", "null"),
        key="id", label="ecommerce_operator_unregistered_supply_amendments")
    return [{**r, "net_liable_paise": UnregisteredAmendmentRow.from_record(r).net_liable_paise} for r in rows]


def _existing_unregistered_amendment(db, firm_id: str, client_id: str, gstin: str, period: str,
                                     original_period: str, original_enrolment_id: str) -> Optional[dict]:
    return _first(privileged_for(db).table("ecommerce_operator_unregistered_supply_amendments").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("period", period)
                  .eq("original_period", original_period)
                  .eq("original_enrolment_id", original_enrolment_id)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_unregistered_amendment(db, firm_id: str, client_id: str, *, gstin: str, period: str,
                                  original_period: str, original_enrolment_id: str, enrolment_id: str,
                                  gross_value_paise: int = 0, returns_paise: int = 0, action: str,
                                  notes: Optional[str] = None, actor_id: Optional[str] = None) -> dict:
    """Same upsert-by-natural-key shape as `record_amendment`, for Table 4.1."""
    existing = _existing_unregistered_amendment(db, firm_id, client_id, gstin, period,
                                                original_period, original_enrolment_id)
    if existing:
        rows = (privileged_for(db).table("ecommerce_operator_unregistered_supply_amendments")
                .update({
                    "enrolment_id": enrolment_id,
                    "gross_value_paise": gross_value_paise,
                    "returns_paise": returns_paise,
                    "action": action,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = privileged_for(db).table("ecommerce_operator_unregistered_supply_amendments").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "period": period,
        "original_period": original_period,
        "original_enrolment_id": original_enrolment_id,
        "enrolment_id": enrolment_id,
        "gross_value_paise": gross_value_paise,
        "returns_paise": returns_paise,
        "action": action,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_unregistered_amendment(db, firm_id: str, client_id: str, amendment_id: str) -> dict:
    """Withdraw a Table 4.1 row of THIS client recorded in error."""
    rows = (privileged_for(db).table("ecommerce_operator_unregistered_supply_amendments")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", amendment_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]

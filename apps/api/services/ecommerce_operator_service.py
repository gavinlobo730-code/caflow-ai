"""What an e-commerce operator's sellers supplied through it (GST-25, GSTR-8).

`domain/gst/gstr8.py` is the rule; this fetches and writes the two tables
migration 421 created. Nothing here decides whether a figure reconciles —
that is the domain module's job, asked by `services.gst_return_service
.gstr8_statement`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all

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
        rows = (db.table("ecommerce_operator_supplies")
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
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("ecommerce_operator_supplies").insert({
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


def delete_supply(db, firm_id: str, supply_id: str) -> dict:
    """Withdraw an entry recorded in error. Soft-deleted, like every other
    document this product keeps an edit trail on."""
    rows = (db.table("ecommerce_operator_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
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
        rows = (db.table("ecommerce_operator_unregistered_supplies")
                .update({
                    "gross_value_paise": gross_value_paise,
                    "returns_paise": returns_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("ecommerce_operator_unregistered_supplies").insert({
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


def delete_unregistered_supply(db, firm_id: str, supply_id: str) -> dict:
    rows = (db.table("ecommerce_operator_unregistered_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]

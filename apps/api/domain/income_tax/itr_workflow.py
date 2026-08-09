"""
ITR Preparation Workflow — Draft → Review → Partner Review → Ready for Filing → Filed.
Supports ITR-3, ITR-5, ITR-6, ITR-7. Architecture supports future ITR forms.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
All filing workflow transitions require explicit CA confirmation.
IT Act 1961 — Section 139 (Return of Income), Section 140 (Verification of Return).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

_logger = logging.getLogger("caflow.itr.workflow")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_FILINGS: dict[str, dict] = {}
_MOCK_VERSIONS: dict[str, list] = {}

# Valid workflow transitions
_TRANSITIONS: dict[str, list[str]] = {
    "draft":             ["review"],
    "review":            ["draft", "partner_review"],
    "partner_review":    ["review", "ready_for_filing"],
    "ready_for_filing":  ["filed"],
    "filed":             [],  # Terminal — immutable
}


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


def create_itr_filing(
    firm_id: str,
    client_id: str,
    financial_year: str,
    assessment_year: str,
    itr_form: str,
    created_by: str,
    computation_snapshot_id: str | None = None,
    notes: str | None = None,
) -> dict:
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "assessment_year": assessment_year,
            "itr_form": itr_form,
            "status": "draft",
            "computation_snapshot_id": computation_snapshot_id,
            "notes": notes,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_FILINGS[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "assessment_year": assessment_year,
        "itr_form": itr_form,
        "status": "draft",
        "computation_snapshot_id": computation_snapshot_id,
        "notes": notes,
        "created_by": created_by,
    }
    res = sb.table("itr_filings").insert(row).execute()
    return res.data[0] if res.data else row


def list_itr_filings(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [f for f in _MOCK_FILINGS.values()
                if f["firm_id"] == firm_id and f["client_id"] == client_id]
    sb = _supabase()
    res = sb.table("itr_filings").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).order("created_at", desc=True).execute()
    return res.data or []


def get_filing(firm_id: str, filing_id: str) -> dict | None:
    """Fetch a single ITR filing by id, scoped to firm_id. Used by the
    router to resolve the filing's client before checking assignment scope."""
    if _USE_MOCK:
        f = _MOCK_FILINGS.get(filing_id)
        return f if f and f.get("firm_id") == firm_id else None
    sb = _supabase()
    res = sb.table("itr_filings").select("*").eq(
        "id", filing_id
    ).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else None


def transition_itr_status(
    firm_id: str,
    filing_id: str,
    new_status: str,
    actor_id: str,
    notes: str | None = None,
) -> dict:
    """
    Move ITR filing through workflow. Validates transition is allowed.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    if _USE_MOCK:
        filing = _MOCK_FILINGS.get(filing_id)
        if not filing:
            raise ValueError("Filing not found")
        allowed = _TRANSITIONS.get(filing["status"], [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from '{filing['status']}' to '{new_status}'")
        filing["status"] = new_status
        filing["updated_at"] = datetime.now(timezone.utc).isoformat()
        if new_status == "review":
            filing["reviewed_by"] = actor_id
            filing["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        elif new_status == "partner_review":
            filing["partner_reviewed_by"] = actor_id
            filing["partner_reviewed_at"] = datetime.now(timezone.utc).isoformat()
        return filing

    sb = _supabase()
    existing = sb.table("itr_filings").select("status").eq("id", filing_id).eq(
        "firm_id", firm_id
    ).single().execute()
    if not existing.data:
        raise ValueError("Filing not found")

    current = existing.data["status"]
    allowed = _TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"Cannot transition from '{current}' to '{new_status}'")

    update: dict = {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        update["notes"] = notes
    if new_status == "review":
        update["reviewed_by"] = actor_id
        update["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    elif new_status == "partner_review":
        update["partner_reviewed_by"] = actor_id
        update["partner_reviewed_at"] = datetime.now(timezone.utc).isoformat()

    res = sb.table("itr_filings").update(update).eq("id", filing_id).eq(
        "firm_id", firm_id
    ).execute()
    return res.data[0] if res.data else {}


def save_itr_version(
    firm_id: str,
    filing_id: str,
    json_payload: dict,
    created_by: str,
) -> dict:
    """Save an immutable JSON snapshot of the ITR payload."""
    if _USE_MOCK:
        versions = _MOCK_VERSIONS.setdefault(filing_id, [])
        version_num = len(versions) + 1
        ver = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "itr_filing_id": filing_id,
            "version": version_num,
            "json_payload": json_payload,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        versions.append(ver)
        return ver

    sb = _supabase()
    # F4 fix: verify the filing itself belongs to this firm before touching its
    # version history at all -- without this, a firm that merely knew/guessed
    # another firm's filing_id could both read that firm's version count and
    # insert a version row against its filing_id (matches the ownership check
    # transition_itr_status already does above; a version has no owner of its
    # own, so a firm_id-only filter on itr_filing_versions isn't enough).
    filing = sb.table("itr_filings").select("id").eq("id", filing_id).eq(
        "firm_id", firm_id
    ).maybe_single().execute()
    if not filing.data:
        raise ValueError("Filing not found")

    existing = sb.table("itr_filing_versions").select("version").eq(
        "itr_filing_id", filing_id
    ).execute()
    version_num = (max((r["version"] for r in existing.data), default=0) + 1) if existing.data else 1

    row = {
        "firm_id": firm_id,
        "itr_filing_id": filing_id,
        "version": version_num,
        "json_payload": json_payload,
        "created_by": created_by,
    }
    res = sb.table("itr_filing_versions").insert(row).execute()
    return res.data[0] if res.data else row


def record_filing_acknowledgement(
    firm_id: str,
    filing_id: str,
    acknowledgement_number: str,
    filing_date: str,
    actor_id: str,
) -> dict:
    """
    Record ITR filing acknowledgement after CA submits on portal.
    # CA REVIEW REQUIRED — This must only be called after CA manually files on Income Tax Portal
    """
    if _USE_MOCK:
        filing = _MOCK_FILINGS.get(filing_id)
        if filing:
            filing["acknowledgement_number"] = acknowledgement_number
            filing["filing_date"] = filing_date
            filing["status"] = "filed"
        return filing or {}

    sb = _supabase()
    res = sb.table("itr_filings").update({
        "acknowledgement_number": acknowledgement_number,
        "filing_date": filing_date,
        "status": "filed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", filing_id).eq("firm_id", firm_id).execute()
    return res.data[0] if res.data else {}

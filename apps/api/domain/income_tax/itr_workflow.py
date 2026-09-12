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
from typing import Optional
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


def _pinned_snapshot_is_unreviewed(firm_id: str, filing: dict) -> Optional[str]:
    """The refusal sentence, or None (IT-30).

    `itr_filings.computation_snapshot_id` PINS the computation a return is
    built on. Nothing read it. So a filing walked draft → review →
    partner_review → ready_for_filing → filed while the computation behind it
    sat at status "draft" for ever — which it did for every snapshot in the
    product, because `POST /api/itr/snapshots/{id}/review` had no caller at all
    and the only path to "reviewed" was unreachable.

    A FILING THAT PINS NOTHING IS ALLOWED THROUGH, and named rather than
    refused. `computation_snapshot_id` is nullable and always has been: a CA
    who computed outside this product and is recording the return here has no
    snapshot to pin, and refusing them would make the pin mandatory by
    accident. What is refused is the case where a snapshot IS pinned and has
    not been checked — the return is built on a computation nobody has signed
    off, and the CA can sign it off in one click on the computation screen.
    """
    snapshot_id = (filing or {}).get("computation_snapshot_id")
    if not snapshot_id:
        return None
    snapshot = _snapshot_status(firm_id, str(snapshot_id))
    if snapshot is None:
        # The pin points at a row this firm cannot see. Not this function's
        # refusal to make — the FK and RLS are — so it does not invent one.
        return None
    if snapshot == "reviewed":
        return None
    return (
        f"This filing is built on computation snapshot {snapshot_id}, which is "
        f"still '{snapshot}'. Mark the computation reviewed on the Tax "
        "Computation screen before moving the filing on — a return cannot be "
        "reviewed while the figures behind it have not been."
    )


def _snapshot_status(firm_id: str, snapshot_id: str) -> Optional[str]:
    """The pinned snapshot's status, or None where there is no such row."""
    from domain.income_tax import computation_workspace as cw
    if _USE_MOCK:
        snap = cw._MOCK_SNAPSHOTS.get(snapshot_id)
        return str(snap.get("status")) if snap else None
    rows = (_supabase().table("tax_computation_snapshots").select("status")
            .eq("id", snapshot_id).eq("firm_id", firm_id).limit(1)
            .execute().data) or []
    return str(rows[0].get("status")) if rows else None


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
        if filing["status"] == "draft":
            unreviewed = _pinned_snapshot_is_unreviewed(firm_id, filing)
            if unreviewed:
                raise ValueError(unreviewed)
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
    existing = sb.table("itr_filings").select(
        "status, computation_snapshot_id"
    ).eq("id", filing_id).eq("firm_id", firm_id).single().execute()
    if not existing.data:
        raise ValueError("Filing not found")

    current = existing.data["status"]
    allowed = _TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"Cannot transition from '{current}' to '{new_status}'")

    # ONLY ON THE WAY OUT OF DRAFT. Once a filing is in review the snapshot
    # question has been answered, and re-asking it would block the
    # review → draft step a reviewer uses to send a return back.
    if current == "draft":
        unreviewed = _pinned_snapshot_is_unreviewed(firm_id, existing.data)
        if unreviewed:
            raise ValueError(unreviewed)

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

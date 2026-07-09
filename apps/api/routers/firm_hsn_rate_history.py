"""Firm HSN/SAC Rate History (Decision D).

GST rates change by GST Council decision / CBIC notification, so a single
flat rate goes silently stale. This router lets a CA record that history
per code, per effective-date range — WITHOUT Caflow becoming a tax
determination engine:

  - Every row is CA-entered. Caflow ships no seed data here and asserts no
    Caflow-authoritative rate for any code.
  - `GET /resolve` is a PRE-FILL HINT for a form only — the caller (product
    form, invoice line) still requires explicit CA confirmation before the
    value is used anywhere, and the invoice line snapshots its own
    gst_rate_bps exactly as it does today, unaffected by this table.
  - No slab/cess/RCM branching logic. Overlapping or ambiguous ranges are
    the CA's judgement call (recorded via `notes`); this router does not
    try to compute which one applies to a given transaction.
"""
import os
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.firm_hsn_rate_history import FirmHsnRateHistoryIn
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.firm_hsn_rate_history")

router = APIRouter(prefix="/api/firm-hsn-rate-history", tags=["firm_hsn_rate_history"])

# Mock store (used when SUPABASE_URL is not configured).
MOCK_RATE_HISTORY: list[dict] = []


def resolve_rate(rows: list[dict], as_of: date) -> Optional[dict]:
    """Pure resolution: the row covering `as_of`, preferring the most
    recently effective one if ranges somehow overlap. Unit-testable without
    a database. Never called automatically outside an explicit hint request."""
    candidates = [
        r for r in rows
        if str(r.get("effective_from", "")) <= as_of.isoformat()
        and (r.get("effective_to") is None or as_of.isoformat() <= str(r.get("effective_to")))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("effective_from", ""))


@router.get("/")
def list_history(
    firm_hsn_library_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """All recorded rate versions for one library code, newest first."""
    try:
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            rows = [r for r in MOCK_RATE_HISTORY
                    if r.get("firm_id") == firm_id and r.get("firm_hsn_library_id") == firm_hsn_library_id]
            rows = sorted(rows, key=lambda r: r.get("effective_from") or "", reverse=True)
            return api_response(True, rows)

        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("firm_hsn_rate_history").select("*")
            .eq("firm_id", firm_id).eq("firm_hsn_library_id", firm_hsn_library_id)
            .order("effective_from", desc=True)
            .execute().data or []
        )
        return api_response(True, rows)
    except Exception as e:
        _logger.error("list_history: %s", e)
        return api_response(False, None, "Unable to load rate history. Please try again.")


@router.get("/resolve")
def resolve(
    firm_hsn_library_id: str = Query(...),
    as_of: date = Query(..., description="Resolve the rate in effect on this date"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Pre-fill hint only: the rate version covering `as_of`, or null if
    none was recorded. The caller must still let the CA confirm/override —
    this endpoint never writes anywhere and nothing downstream reads it
    without that confirmation step."""
    try:
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            rows = [r for r in MOCK_RATE_HISTORY
                    if r.get("firm_id") == firm_id and r.get("firm_hsn_library_id") == firm_hsn_library_id]
            return api_response(True, resolve_rate(rows, as_of))

        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("firm_hsn_rate_history").select("*")
            .eq("firm_id", firm_id).eq("firm_hsn_library_id", firm_hsn_library_id)
            .execute().data or []
        )
        return api_response(True, resolve_rate(rows, as_of))
    except Exception as e:
        _logger.error("resolve: %s", e)
        return api_response(False, None, "Unable to resolve a rate. Please try again.")


@router.post("/")
def add_rate_version(
    data: FirmHsnRateHistoryIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Record a new CA-entered rate version for a library code."""
    try:
        firm_id = current_user.get("firm_id")
        payload = data.model_dump(mode="json")
        payload["firm_id"] = firm_id
        now = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            from routers.firm_hsn_library import MOCK_LIBRARY
            owned_code = any(
                r for r in MOCK_LIBRARY
                if r.get("id") == payload["firm_hsn_library_id"] and r.get("firm_id") == firm_id
            )
            if not owned_code:
                raise HTTPException(status_code=404, detail="That code is not in your library.")
            payload["id"] = str(uuid.uuid4())
            payload["created_at"] = now
            MOCK_RATE_HISTORY.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned_code = (
            db.table("firm_hsn_library").select("id")
            .eq("id", payload["firm_hsn_library_id"]).eq("firm_id", firm_id)
            .execute().data or []
        )
        if not owned_code:
            raise HTTPException(status_code=404, detail="That code is not in your library.")
        payload["created_at"] = now
        resp = db.table("firm_hsn_rate_history").insert(payload).execute()
        return api_response(True, resp.data[0] if resp.data else payload)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("add_rate_version: %s", e)
        return api_response(False, None, "Unable to record the rate version. Please try again.")


@router.delete("/{rate_history_id}")
def delete_rate_version(
    rate_history_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Remove a mistakenly entered rate version. Hard delete is safe here:
    nothing downstream references rate-history rows (invoice lines snapshot
    their own gst_rate_bps and never join this table)."""
    try:
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            before = len(MOCK_RATE_HISTORY)
            MOCK_RATE_HISTORY[:] = [
                r for r in MOCK_RATE_HISTORY
                if not (r.get("id") == rate_history_id and r.get("firm_id") == firm_id)
            ]
            if len(MOCK_RATE_HISTORY) == before:
                raise HTTPException(status_code=404, detail="Rate version not found.")
            return api_response(True, {"id": rate_history_id})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("firm_hsn_rate_history").select("id")
                 .eq("id", rate_history_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Rate version not found.")
        db.table("firm_hsn_rate_history").delete().eq("id", rate_history_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": rate_history_id})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_rate_version: %s", e)
        return api_response(False, None, "Unable to delete the rate version. Please try again.")

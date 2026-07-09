"""Firm HSN/SAC Library — the CA-owned, CA-curated source of HSN/SAC codes
(HSN/SAC architecture redesign, Phase 2).

Caflow does not ship or expose a shared HSN/SAC master to users. Every code a
firm bills against comes from THIS table: added by manual entry or import,
edited, retired (never hard-deleted). `public.hsn_master` is retained only as
an internal, non-exposed implementation detail and is not read by this
router — this endpoint returns exactly what the firm put in its own library,
nothing else.

The stored GST rate is a CA-entered PRE-FILL HINT ONLY (CGST Rule 46(g)) —
never used in any tax or journal computation. Products/Services and invoice
lines snapshot their own values; nothing joins back to this table for
financial output.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.firm_hsn_library import FirmHsnLibraryIn, FirmHsnLibraryUpdateIn
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.firm_hsn_library")

router = APIRouter(prefix="/api/firm-hsn-library", tags=["firm_hsn_library"])

# Mock store (used when SUPABASE_URL is not configured), mirrors service_catalogue.py.
MOCK_LIBRARY: list[dict] = []

_SAFE_Q = re.compile(r"[^A-Za-z0-9 ]+")


def _rank_library(term: str, rows: list[dict]) -> list[dict]:
    """Relevance-rank a firm's own library rows for a search term (pure,
    unit-testable). A firm's library is small and fully CA-curated, so a
    simple code/description ranking (no synonym/keyword layer) is enough:

      0 exact code      1 code prefix      2 code substring
      3 description prefix   4 description substring
    """
    t = (term or "").strip().lower()

    def rank(idx_row: tuple[int, dict]) -> tuple:
        i, r = idx_row
        code = (r.get("hsn_code") or "").lower()
        desc = (r.get("description") or "").lower()
        if code == t:
            bucket = 0
        elif t and code.startswith(t):
            bucket = 1
        elif t and t in code:
            bucket = 2
        elif t and desc.startswith(t):
            bucket = 3
        elif t and t in desc:
            bucket = 4
        else:
            bucket = 5
        return (bucket, i)

    return [r for _, r in sorted(enumerate(rows), key=rank)]


@router.get("/")
def list_library(
    q: str = Query("", description="Search by code or description"),
    hsn_type: Optional[str] = Query(None, description="Filter: 'goods' or 'services'"),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List/search the firm's own HSN/SAC library. Active-only by default."""
    try:
        term = _SAFE_Q.sub(" ", (q or "").strip()).strip()
        firm_id = current_user.get("firm_id")

        if _USE_MOCK:
            rows = [r for r in MOCK_LIBRARY if r.get("firm_id") == firm_id]
            if not include_archived:
                rows = [r for r in rows if r.get("is_active", True)]
            if hsn_type in ("goods", "services"):
                rows = [r for r in rows if r.get("hsn_type") == hsn_type]
            rows = sorted(rows, key=lambda r: r.get("hsn_code") or "")
            if term:
                t = term.lower()
                rows = [
                    r for r in rows
                    if (r.get("hsn_code") or "").lower().startswith(t)
                    or t in (r.get("description") or "").lower()
                ]
                rows = _rank_library(term, rows)
            return api_response(True, rows[:limit])

        from core.supabase_client import get_supabase
        db = get_supabase()
        query = db.table("firm_hsn_library").select("*").eq("firm_id", firm_id)
        if not include_archived:
            query = query.eq("is_active", True)
        if hsn_type in ("goods", "services"):
            query = query.eq("hsn_type", hsn_type)
        if term:
            query = query.or_(f"hsn_code.ilike.{term}*,description.ilike.*{term}*")
        rows = query.order("hsn_code").limit(limit * 2).execute().data or []
        rows = _rank_library(term, rows) if term else rows
        return api_response(True, rows[:limit])
    except Exception as e:
        _logger.error("list_library: %s", e)
        return api_response(False, None, "Unable to load the HSN/SAC library. Please try again.")


@router.post("/")
def add_code(
    data: FirmHsnLibraryIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Add a code to the firm's library (manual entry, or one row of an
    import — the frontend import flow calls this endpoint once per row with
    source='import', so there is exactly one create path, mirroring the
    sales-invoice bulk-import pattern). Re-adding a code that already exists
    reactivates it if retired, or returns it unchanged with duplicate=True
    if already active — never a second row for the same code."""
    try:
        firm_id = current_user.get("firm_id")
        payload = data.model_dump()
        payload["firm_id"] = firm_id
        now = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            existing = next(
                (r for r in MOCK_LIBRARY
                 if r.get("firm_id") == firm_id and r.get("hsn_code") == payload["hsn_code"]),
                None,
            )
            if existing and existing.get("is_active", True):
                return api_response(True, {**existing, "duplicate": True})
            if existing:
                existing.update(payload, is_active=True, updated_at=now)
                return api_response(True, existing)
            payload["id"] = str(uuid.uuid4())
            payload["is_active"] = True
            payload["created_at"] = now
            payload["updated_at"] = now
            MOCK_LIBRARY.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()
        existing_rows = (
            db.table("firm_hsn_library").select("*")
            .eq("firm_id", firm_id).eq("hsn_code", payload["hsn_code"]).execute().data or []
        )
        existing = existing_rows[0] if existing_rows else None
        if existing and existing.get("is_active", True):
            return api_response(True, {**existing, "duplicate": True})
        if existing:
            patch = {**payload, "is_active": True, "updated_at": now}
            patch.pop("firm_id", None)
            resp = (db.table("firm_hsn_library").update(patch)
                    .eq("id", existing["id"]).execute())
            return api_response(True, resp.data[0] if resp.data else {**existing, **patch})
        payload["created_at"] = now
        payload["updated_at"] = now
        resp = db.table("firm_hsn_library").insert(payload).execute()
        return api_response(True, resp.data[0] if resp.data else payload)
    except Exception as e:
        _logger.error("add_code: %s", e)
        return api_response(False, None, "Unable to add the code to your library. Please try again.")


@router.patch("/{library_id}")
def update_code(
    library_id: str,
    data: FirmHsnLibraryUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Edit a code's description/rate hint/notes, or retire/restore via is_active."""
    try:
        firm_id = current_user.get("firm_id")
        patch = {k: v for k, v in data.model_dump().items() if v is not None}
        if not patch:
            raise HTTPException(status_code=422, detail="No fields to update.")
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((r for r in MOCK_LIBRARY
                        if r.get("id") == library_id and r.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Code not found in your library.")
            row.update(patch)
            return api_response(True, row)

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("firm_hsn_library").select("*")
                 .eq("id", library_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Code not found in your library.")
        resp = (db.table("firm_hsn_library").update(patch)
                .eq("id", library_id).eq("firm_id", firm_id).execute())
        return api_response(True, resp.data[0] if resp.data else {**owned[0], **patch})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_code: %s", e)
        return api_response(False, None, "Unable to update the code. Please try again.")


@router.delete("/{library_id}")
def retire_code(
    library_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Retire a code (is_active=false). Never a hard delete — a retired code
    may still be referenced by historical Products/Services/invoice lines,
    which store their own snapshot regardless."""
    try:
        firm_id = current_user.get("firm_id")
        now = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((r for r in MOCK_LIBRARY
                        if r.get("id") == library_id and r.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Code not found in your library.")
            row["is_active"] = False
            row["updated_at"] = now
            return api_response(True, {"id": library_id, "is_active": False})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("firm_hsn_library").select("id")
                 .eq("id", library_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Code not found in your library.")
        db.table("firm_hsn_library").update(
            {"is_active": False, "updated_at": now}
        ).eq("id", library_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": library_id, "is_active": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("retire_code: %s", e)
        return api_response(False, None, "Unable to retire the code. Please try again.")

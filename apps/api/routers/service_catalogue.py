"""Service Catalogue — reusable, SERVICES-ONLY billing presets (Batch 6).

A CA firm's repeatable services (name + default SAC/HSN, GST rate, unit price)
so the invoice editor can drop a fully pre-priced line in one pick. NOT an
inventory master: no stock, valuation, or quantity — only billing defaults.

Firm-scoped. A preset is a snapshot SOURCE: picking one copies its values onto
the invoice line (invoice lines store their own free-text HSN/rate/amount, no FK
here), so editing/archiving a preset never changes a past invoice. The stored
rate/price are pre-fill hints (CGST Rule 46(g)) — never used in tax/journal math.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.service_catalogue import ServiceCatalogueIn, ServiceCatalogueUpdateIn
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.service_catalogue")

router = APIRouter(prefix="/api/service-catalogue", tags=["service_catalogue"])

# Mock store (used when SUPABASE_URL is not configured), mirrors customers.py.
MOCK_SERVICES: list[dict] = []

_SAFE_Q = re.compile(r"[^A-Za-z0-9 ]+")


def _norm_name(v: Optional[str]) -> str:
    """Case/space-insensitive key for duplicate detection."""
    return re.sub(r"\s+", " ", (v or "").strip()).lower()


def _rank_services(term: str, rows: list[dict]) -> list[dict]:
    """Relevance-rank presets for a search term (pure, unit-testable).

      0 exact name         1 name prefix        2 name substring
      3 SAC/HSN prefix      4 description / notes / hsn substring
      5 no textual match (kept; the DB filter already narrowed)

    Ties preserve the input order, which the caller pre-sorts recency-then-
    frequency — so within a relevance tier the most recent/most used wins,
    giving "recent" and "frequently used" for free.
    """
    t = _norm_name(term)

    def rank(idx_row):
        i, r = idx_row
        name = _norm_name(r.get("name"))
        desc = _norm_name(r.get("description"))
        notes = _norm_name(r.get("notes"))
        hsn = (r.get("hsn_sac") or "").lower()
        if name == t:
            bucket = 0
        elif t and name.startswith(t):
            bucket = 1
        elif t and t in name:
            bucket = 2
        elif t and hsn.startswith(t):
            bucket = 3
        elif t and (t in desc or t in notes or t in hsn):
            bucket = 4
        else:
            bucket = 5
        return (bucket, i)

    return [r for _, r in sorted(enumerate(rows), key=rank)]


def _sort_recent_first(rows: list[dict]) -> list[dict]:
    """Recency-then-frequency ordering (mirrors the DB rank index)."""
    return sorted(
        rows,
        key=lambda r: (r.get("last_used_at") or "", r.get("use_count") or 0),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_services(
    q: str = Query("", description="Search by name, description or SAC/HSN"),
    include_archived: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List/search the firm's presets. Active-only by default; ranked by
    relevance then recency/frequency. Empty query returns the recent/frequent
    presets (the picker's before-you-type list)."""
    try:
        term = _SAFE_Q.sub(" ", (q or "").strip()).strip()
        firm_id = current_user.get("firm_id")

        if _USE_MOCK:
            rows = [s for s in MOCK_SERVICES if s.get("firm_id") == firm_id]
            if not include_archived:
                rows = [s for s in rows if s.get("is_active", True)]
            rows = _sort_recent_first(rows)
            if term:
                rows = [r for r in _rank_services(term, rows) if _matches(term, r)]
            return api_response(True, rows[:limit])

        from core.supabase_client import get_supabase
        db = get_supabase()
        query = db.table("service_catalogue").select("*").eq("firm_id", firm_id)
        if not include_archived:
            query = query.eq("is_active", True)
        if term:
            query = query.or_(
                f"name.ilike.*{term}*,description.ilike.*{term}*,hsn_sac.ilike.{term}*"
            )
        rows = (
            query.order("last_used_at", desc=True)
            .order("use_count", desc=True)
            .order("name")
            .limit(limit * 2)
            .execute()
            .data
            or []
        )
        rows = _rank_services(term, rows) if term else rows
        return api_response(True, rows[:limit])
    except Exception as e:
        _logger.error("list_services: %s", e)
        return api_response(False, None, "Unable to load the service catalogue. Please try again.")


def _matches(term: str, row: dict) -> bool:
    """Mock-mode text filter mirroring the DB or() clause."""
    t = _norm_name(term)
    return (
        t in _norm_name(row.get("name"))
        or t in _norm_name(row.get("description"))
        or (row.get("hsn_sac") or "").lower().startswith(t)
    )


@router.post("/")
def create_service(
    data: ServiceCatalogueIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create a preset. A second ACTIVE preset with the same name (case/space-
    insensitive) is rejected as a duplicate: the existing row is returned with
    duplicate=True and nothing is inserted."""
    try:
        firm_id = current_user.get("firm_id")
        payload = data.model_dump()
        payload["firm_id"] = firm_id
        payload["is_active"] = True
        now = datetime.now(timezone.utc).isoformat()
        payload["created_at"] = now
        payload["updated_at"] = now
        key = _norm_name(payload["name"])

        if _USE_MOCK:
            existing = next(
                (s for s in MOCK_SERVICES
                 if s.get("firm_id") == firm_id and s.get("is_active", True)
                 and _norm_name(s.get("name")) == key),
                None,
            )
            if existing:
                return api_response(True, {**existing, "duplicate": True})
            payload["id"] = str(uuid.uuid4())
            payload["use_count"] = 0
            payload["last_used_at"] = None
            MOCK_SERVICES.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()
        existing_rows = (
            db.table("service_catalogue").select("*")
            .eq("firm_id", firm_id).eq("is_active", True).execute().data or []
        )
        existing = next((s for s in existing_rows if _norm_name(s.get("name")) == key), None)
        if existing:
            return api_response(True, {**existing, "duplicate": True})
        resp = db.table("service_catalogue").insert(payload).execute()
        return api_response(True, resp.data[0] if resp.data else payload)
    except Exception as e:
        _logger.error("create_service: %s", e)
        return api_response(False, None, "Unable to create the service. Please try again.")


@router.patch("/{service_id}")
def update_service(
    service_id: str,
    data: ServiceCatalogueUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Edit a preset, or archive/restore it via is_active. Renaming to an
    existing active name is rejected as a duplicate."""
    try:
        firm_id = current_user.get("firm_id")
        patch = {k: v for k, v in data.model_dump().items() if v is not None}
        if not patch:
            raise HTTPException(status_code=422, detail="No fields to update.")
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((s for s in MOCK_SERVICES
                        if s.get("id") == service_id and s.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Service not found.")
            if "name" in patch:
                key = _norm_name(patch["name"])
                clash = any(
                    s for s in MOCK_SERVICES
                    if s.get("id") != service_id and s.get("firm_id") == firm_id
                    and s.get("is_active", True) and _norm_name(s.get("name")) == key
                )
                if clash:
                    return api_response(False, None, "Another active service already uses that name.")
            row.update(patch)
            return api_response(True, row)

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("service_catalogue").select("*")
                 .eq("id", service_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Service not found.")
        if "name" in patch:
            key = _norm_name(patch["name"])
            others = (db.table("service_catalogue").select("id,name,is_active")
                      .eq("firm_id", firm_id).eq("is_active", True).execute().data or [])
            if any(o for o in others if o["id"] != service_id and _norm_name(o.get("name")) == key):
                return api_response(False, None, "Another active service already uses that name.")
        resp = (db.table("service_catalogue").update(patch)
                .eq("id", service_id).eq("firm_id", firm_id).execute())
        return api_response(True, resp.data[0] if resp.data else {**owned[0], **patch})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_service: %s", e)
        return api_response(False, None, "Unable to update the service. Please try again.")


@router.post("/{service_id}/used")
def record_service_used(
    service_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Fire-and-forget usage bump (use_count += 1, last_used_at = now) so the
    picker can rank recent/frequent presets. Decoupled from invoice posting: the
    editor calls this when a preset is picked; it touches no accounting state."""
    try:
        firm_id = current_user.get("firm_id")
        now = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            row = next((s for s in MOCK_SERVICES
                        if s.get("id") == service_id and s.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Service not found.")
            row["use_count"] = (row.get("use_count") or 0) + 1
            row["last_used_at"] = now
            return api_response(True, {"id": service_id, "use_count": row["use_count"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("service_catalogue").select("use_count")
                 .eq("id", service_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Service not found.")
        next_count = (owned[0].get("use_count") or 0) + 1
        db.table("service_catalogue").update(
            {"use_count": next_count, "last_used_at": now}
        ).eq("id", service_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": service_id, "use_count": next_count})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("record_service_used: %s", e)
        return api_response(False, None, "Unable to record service usage. Please try again.")

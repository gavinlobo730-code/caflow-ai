"""Firm HSN/SAC Library — the CA-owned, CA-curated source of HSN/SAC codes
(HSN/SAC architecture redesign, Phase 2).

Caflow does not ship or expose a shared HSN/SAC master to users. Every code a
firm bills against comes from THIS table: added by manual entry or import,
edited, retired (soft — the default removal path), or permanently deleted
once confirmed unused (see purge_code below). `public.hsn_master` is
retained only as an internal, non-exposed implementation detail and is not
read by this router — this endpoint returns exactly what the firm put in
its own library, nothing else.

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
from pydantic import BaseModel, ValidationError as PydanticValidationError
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


class FirmHsnLibraryBulkIn(BaseModel):
    """Loose body — items are validated individually inside the handler (via
    FirmHsnLibraryIn(**item)) so one malformed CSV row cannot 422 the whole
    batch."""
    codes: list[dict]


@router.post("/bulk")
def bulk_add_codes(
    data: FirmHsnLibraryBulkIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Bulk-import HSN/SAC codes into the firm's library (CSV upload).

    Mirrors service_catalogue.py's bulk_create_services: ONE existing-codes
    snapshot for this firm instead of one query per row, then ONE batch
    insert for every brand-new code — regardless of how many rows are in the
    file. A code that already exists and is ACTIVE is reported as a
    duplicate (same rule as add_code's single-row path); one that exists but
    is RETIRED is reactivated. Reactivation is necessarily a per-row update
    (there's no DB-level unique constraint on (firm_id, hsn_code) to upsert
    against, and resurrecting an already-retired code mid-bulk-import is
    expected to be rare — most rows in a real import are brand-new codes),
    so it doesn't get the same one-call treatment as new-code inserts.
    """
    try:
        firm_id = current_user.get("firm_id")
        items = data.codes or []

        created: list[dict] = []
        reactivated: list[dict] = []
        duplicates: list[dict] = []
        errors: list[dict] = []

        # ── Step 1: per-item validation (in-memory, no DB) ───────────────────
        validated: list[tuple[int, dict]] = []
        for idx, item in enumerate(items):
            item = item if isinstance(item, dict) else {}
            try:
                parsed = FirmHsnLibraryIn(**item)
            except PydanticValidationError as e:
                msgs = "; ".join(err.get("msg", str(err)) for err in e.errors())
                errors.append({"index": idx, "hsn_code": item.get("hsn_code"), "error": msgs})
                continue
            payload = parsed.model_dump()
            payload["firm_id"] = firm_id
            validated.append((idx, payload))

        if not validated:
            return api_response(True, {"created": created, "reactivated": reactivated, "duplicates": duplicates, "errors": errors})

        # ── Step 2: ONE existing-codes snapshot for this firm (active AND
        # retired — a retired match needs reactivation, not a duplicate report). ──
        now = datetime.now(timezone.utc).isoformat()
        db = None
        if _USE_MOCK:
            existing_rows = [r for r in MOCK_LIBRARY if r.get("firm_id") == firm_id]
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            existing_rows = db.table("firm_hsn_library").select("*").eq("firm_id", firm_id).execute().data or []
        existing_by_code = {r.get("hsn_code"): r for r in existing_rows}

        # ── Step 3: classify each row against the snapshot AND rows already
        # accepted earlier in this same batch (catches a duplicate the CSV
        # itself contains, not just one already in the library). ────────────
        seen_in_batch: set = set()
        to_insert: list[tuple[int, dict]] = []
        to_reactivate: list[tuple[int, dict, dict]] = []
        for idx, payload in validated:
            code = payload["hsn_code"]
            if code in seen_in_batch:
                duplicates.append({"index": idx, "hsn_code": code, "error": "Duplicate code within this file."})
                continue
            seen_in_batch.add(code)
            existing = existing_by_code.get(code)
            if existing and existing.get("is_active", True):
                duplicates.append({"index": idx, "hsn_code": code, "existing_id": existing.get("id")})
                continue
            if existing:
                to_reactivate.append((idx, payload, existing))
                continue
            payload["id"] = str(uuid.uuid4())
            payload["is_active"] = True
            payload["created_at"] = now
            payload["updated_at"] = now
            to_insert.append((idx, payload))

        # ── Step 4: ONE batch insert for every brand-new code. ───────────────
        if to_insert:
            if _USE_MOCK:
                for idx, payload in to_insert:
                    MOCK_LIBRARY.append(payload)
                    created.append(payload)
            else:
                resp = db.table("firm_hsn_library").insert([p for _, p in to_insert]).execute()
                created.extend(resp.data or [p for _, p in to_insert])

        # ── Step 5: reactivations — per-row (see docstring: expected rare). ──
        for idx, payload, existing in to_reactivate:
            patch = {**payload, "is_active": True, "updated_at": now}
            patch.pop("firm_id", None)
            patch.pop("hsn_code", None)  # immutable after creation, per FirmHsnLibraryUpdateIn
            if _USE_MOCK:
                existing.update(patch)
                reactivated.append(existing)
            else:
                resp = db.table("firm_hsn_library").update(patch).eq("id", existing["id"]).execute()
                reactivated.append(resp.data[0] if resp.data else {**existing, **patch})

        return api_response(True, {"created": created, "reactivated": reactivated, "duplicates": duplicates, "errors": errors})
    except Exception as e:
        _logger.error("bulk_add_codes: %s", e)
        return api_response(False, None, "Unable to complete the HSN/SAC library import. Please try again.")


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
    """Retire a code (is_active=false) — the default, always-safe removal
    path. See purge_code below for a real, permanent delete."""
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


# ── Permanent delete ─────────────────────────────────────────────────────────
# firm_hsn_library carries no live foreign key from anywhere else — every
# consumer (Products/Services, every invoice/note/bill line type) snapshots
# the hsn_sac STRING at the moment it's picked (see module docstring), so a
# real delete can never orphan a row. But a code that HAS been used is still
# worth keeping visible for audit trail, so usage is checked by string match
# across every place a code can be picked from, and blocks the delete —
# mirrors service_catalogue.py's delete_service guard, generalised to every
# document type since (unlike a Product/Service preset) an HSN/SAC code can
# be picked directly on any line, not just via one picker.

_USAGE_CHECKS = [
    # (human label, table with hsn_sac, parent table for firm_id, or None if direct)
    ("your Product/Service catalogue", "service_catalogue", None),
    ("a sales invoice", "client_sales_invoice_lines", "client_sales_invoices"),
    ("a credit note", "credit_note_lines", "credit_notes"),
    ("a debit note", "debit_note_lines", "debit_notes"),
    ("a purchase bill", "purchase_bill_lines", "purchase_bills"),
    ("a recurring invoice template", "recurring_invoice_template_lines", "recurring_invoice_templates"),
]


def _find_hsn_usage(db, firm_id: str, hsn_code: str) -> list[str]:
    """Where a code is still referenced, checked by exact string match on
    hsn_sac — the only way to detect usage, since nothing joins back to
    firm_hsn_library by id. Returns human-readable labels; empty = unused."""
    found: list[str] = []
    for label, table, parent_table in _USAGE_CHECKS:
        if parent_table is None:
            rows = (
                db.table(table).select("id")
                .eq("firm_id", firm_id).eq("hsn_sac", hsn_code)
                .limit(1).execute().data or []
            )
        else:
            rows = (
                db.table(table).select(f"id, {parent_table}!inner(firm_id)")
                .eq("hsn_sac", hsn_code).eq(f"{parent_table}.firm_id", firm_id)
                .limit(1).execute().data or []
            )
        if rows:
            found.append(label)
    return found


def _find_hsn_usage_mock(hsn_code: str) -> list[str]:
    """Mock-mode equivalent of _find_hsn_usage, mirrors service_catalogue.py's
    delete_service mock branch (deferred import of each router's in-memory
    store to avoid a circular import). Best-effort: recurring invoice
    templates have no mock line store, so they're not checked here — the
    real (Supabase) path above is exhaustive."""
    found: list[str] = []
    from routers.service_catalogue import MOCK_SERVICES
    if any(s.get("hsn_sac") == hsn_code for s in MOCK_SERVICES):
        found.append("your Product/Service catalogue")
    from routers.sales_invoices import MOCK_SALES_INVOICE_LINES
    if any(ln.get("hsn_sac") == hsn_code for ln in MOCK_SALES_INVOICE_LINES):
        found.append("a sales invoice")
    from routers.credit_notes import MOCK_CREDIT_NOTE_LINES
    if any(ln.get("hsn_sac") == hsn_code for ln in MOCK_CREDIT_NOTE_LINES):
        found.append("a credit note")
    from routers.debit_notes import MOCK_DEBIT_NOTE_LINES
    if any(ln.get("hsn_sac") == hsn_code for ln in MOCK_DEBIT_NOTE_LINES):
        found.append("a debit note")
    from routers.purchase_bills import MOCK_PURCHASE_BILL_LINES
    if any(ln.get("hsn_sac") == hsn_code for ln in MOCK_PURCHASE_BILL_LINES):
        found.append("a purchase bill")
    return found


def _blocked_message(used_in: list[str]) -> str:
    return f"This code is used on {', '.join(used_in)} and can't be permanently deleted. Retire it instead."


@router.delete("/{library_id}/purge")
def purge_code(
    library_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Permanently delete a code — only when it has never been used anywhere.
    Unlike retire_code, this actually removes the row; see the module note
    above for why that's safe once usage is confirmed absent."""
    try:
        firm_id = current_user.get("firm_id")

        if _USE_MOCK:
            row = next((r for r in MOCK_LIBRARY
                        if r.get("id") == library_id and r.get("firm_id") == firm_id), None)
            if not row:
                raise HTTPException(status_code=404, detail="Code not found in your library.")
            used_in = _find_hsn_usage_mock(row["hsn_code"])
            if used_in:
                return api_response(False, None, _blocked_message(used_in))
            MOCK_LIBRARY.remove(row)
            return api_response(True, {"id": library_id})

        from core.supabase_client import get_supabase
        db = get_supabase()
        owned = (db.table("firm_hsn_library").select("id, hsn_code")
                 .eq("id", library_id).eq("firm_id", firm_id).execute().data or [])
        if not owned:
            raise HTTPException(status_code=404, detail="Code not found in your library.")
        used_in = _find_hsn_usage(db, firm_id, owned[0]["hsn_code"])
        if used_in:
            return api_response(False, None, _blocked_message(used_in))
        db.table("firm_hsn_library").delete().eq("id", library_id).eq("firm_id", firm_id).execute()
        return api_response(True, {"id": library_id})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("purge_code: %s", e)
        return api_response(False, None, "Unable to permanently delete the code. Please try again.")


class FirmHsnLibraryBulkDeleteIn(BaseModel):
    ids: list[str]


@router.post("/bulk-delete")
def bulk_purge_codes(
    data: FirmHsnLibraryBulkDeleteIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Permanently delete multiple codes in one request — same usage guard as
    purge_code, applied per row so one blocked code doesn't stop the rest."""
    try:
        firm_id = current_user.get("firm_id")
        ids = data.ids or []
        if not ids:
            return api_response(True, {"deleted": [], "blocked": []})

        deleted: list[str] = []
        blocked: list[dict] = []

        if _USE_MOCK:
            for library_id in ids:
                row = next((r for r in MOCK_LIBRARY
                            if r.get("id") == library_id and r.get("firm_id") == firm_id), None)
                if not row:
                    continue
                used_in = _find_hsn_usage_mock(row["hsn_code"])
                if used_in:
                    blocked.append({"id": library_id, "hsn_code": row["hsn_code"], "used_in": used_in})
                    continue
                MOCK_LIBRARY.remove(row)
                deleted.append(library_id)
            return api_response(True, {"deleted": deleted, "blocked": blocked})

        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (db.table("firm_hsn_library").select("id, hsn_code")
                .eq("firm_id", firm_id).in_("id", ids).execute().data or [])
        for row in rows:
            used_in = _find_hsn_usage(db, firm_id, row["hsn_code"])
            if used_in:
                blocked.append({"id": row["id"], "hsn_code": row["hsn_code"], "used_in": used_in})
                continue
            db.table("firm_hsn_library").delete().eq("id", row["id"]).eq("firm_id", firm_id).execute()
            deleted.append(row["id"])
        return api_response(True, {"deleted": deleted, "blocked": blocked})
    except Exception as e:
        _logger.error("bulk_purge_codes: %s", e)
        return api_response(False, None, "Unable to complete the bulk delete. Please try again.")

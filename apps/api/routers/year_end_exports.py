"""
Year End Exports router — Phase 6.
Generates PDFs and stores them in Supabase Storage, with signed download URLs.

Storage path: year-end-exports/{firm_id}/{client_id}/{financial_year}/
All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

_STORAGE_BUCKET = "year-end-exports"

router = APIRouter(prefix="/year-end", tags=["year-end-exports"])

# ── Mock store ────────────────────────────────────────────────────────────────
# engagement_id → list of export records
_MOCK_EXPORTS: dict[str, list[dict]] = {}


def _get_engagement(db, engagement_id: str, firm_id: str) -> dict:
    row = (
        db.table("year_end_engagements")
        .select("*")
        .eq("id", engagement_id)
        .eq("firm_id", firm_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row


def _mock_engagement(engagement_id: str) -> dict:
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        eng = _MOCK_ENGAGEMENTS.get(engagement_id)
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        return eng
    except ImportError:
        return {
            "id": engagement_id,
            "firm_id": "firm-001",
            "client_id": "client-001",
            "financial_year": "2024-25",
            "fy_start": "2024-04-01",
            "fy_end": "2025-03-31",
            "status": "approved",
        }


def _storage_path(firm_id: str, client_id: str, financial_year: str, filename: str) -> str:
    """Build Supabase Storage path for year-end exports."""
    return f"{firm_id}/{client_id}/{financial_year}/{filename}"


# ── Request models ────────────────────────────────────────────────────────────

class ExportRequestIn(BaseModel):
    notes: Optional[str] = None


# ── Internal export helpers ───────────────────────────────────────────────────

def _create_export_record(
    engagement_id: str,
    firm_id: str,
    client_id: str,
    financial_year: str,
    export_type: str,
    storage_path: str,
    file_size_bytes: int,
    actor_id: Optional[str],
    notes: Optional[str],
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id":               str(uuid.uuid4()),
        "engagement_id":    engagement_id,
        "firm_id":          firm_id,
        "client_id":        client_id,
        "financial_year":   financial_year,
        "export_type":      export_type,
        "storage_path":     storage_path,
        "file_size_bytes":  file_size_bytes,
        "notes":            notes,
        "created_by":       actor_id,
        "created_at":       now,
    }


def _get_statements_data(db, eng: dict) -> dict:
    from services.year_end_financial_service import generate_financial_statements
    return generate_financial_statements(
        db,
        client_id=eng["client_id"],
        firm_id=eng["firm_id"],
        fy_start=eng["fy_start"],
        fy_end=eng["fy_end"],
    )


def _get_notes_data(db, engagement_id: str, firm_id: str) -> list:
    if db is None:
        return []
    rows = (
        db.table("notes_to_accounts")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", firm_id)
        .order("sequence_no")
        .execute()
        .data
    )
    return rows or []


def _get_adjustments_data(db, engagement_id: str, firm_id: str) -> list:
    if db is None:
        return []
    rows = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", firm_id)
        .execute()
        .data
    )
    return rows or []


def _upload_and_record(
    db,
    eng: dict,
    export_type: str,
    pdf_bytes: bytes,
    filename: str,
    actor_id: Optional[str],
    actor_email: Optional[str],
    notes: Optional[str],
) -> dict:
    """Upload PDF to Supabase Storage and insert export record."""
    firm_id        = eng["firm_id"]
    client_id      = eng["client_id"]
    financial_year = eng["financial_year"]
    engagement_id  = eng["id"]

    path = _storage_path(firm_id, client_id, financial_year, filename)

    # Upload to Supabase Storage
    try:
        db.storage.from_(_STORAGE_BUCKET).upload(
            path=path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"},
        )
    except Exception as e:
        # Storage upload is non-critical in dev mode — log and continue
        if os.environ.get("APP_ENV") == "development":
            pass
        else:
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}")

    record = _create_export_record(
        engagement_id=engagement_id,
        firm_id=firm_id,
        client_id=client_id,
        financial_year=financial_year,
        export_type=export_type,
        storage_path=path,
        file_size_bytes=len(pdf_bytes),
        actor_id=actor_id,
        notes=notes,
    )
    inserted = db.table("year_end_exports").insert(record).execute().data[0]

    log_event(
        firm_id, "year_end_export", inserted["id"], "create",
        actor_id=actor_id, actor_email=actor_email,
        new_data={"export_type": export_type, "path": path},
    )
    return inserted


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{engagement_id}/exports/financial-statements")
def export_financial_statements(
    engagement_id: str,
    data: ExportRequestIn = ExportRequestIn(),
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Generate financial statements PDF, upload to storage, record export."""
    from services.year_end_pdf_service import generate_financial_statements_pdf
    from services.year_end_financial_service import generate_financial_statements

    if _USE_MOCK:
        eng = _mock_engagement(engagement_id)
        statements = generate_financial_statements(None, eng["client_id"], eng["firm_id"],
                                                    eng["fy_start"], eng["fy_end"])
        pdf_bytes = generate_financial_statements_pdf(eng, statements)
        record = _create_export_record(
            engagement_id=engagement_id,
            firm_id=eng["firm_id"],
            client_id=eng["client_id"],
            financial_year=eng["financial_year"],
            export_type="financial_statements",
            storage_path=_storage_path(eng["firm_id"], eng["client_id"],
                                        eng["financial_year"], f"financial_statements_{engagement_id[:8]}.pdf"),
            file_size_bytes=len(pdf_bytes),
            actor_id=current_user.get("auth_user_id"),
            notes=data.notes,
        )
        _MOCK_EXPORTS.setdefault(engagement_id, []).append(record)
        return api_response(True, record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_engagement(db, engagement_id, current_user["firm_id"])

    try:
        statements = _get_statements_data(db, eng)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    pdf_bytes = generate_financial_statements_pdf(eng, statements)
    filename  = f"financial_statements_{engagement_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    record = _upload_and_record(
        db, eng, "financial_statements", pdf_bytes, filename,
        current_user.get("auth_user_id"), current_user.get("email"), data.notes,
    )
    return api_response(True, record)


@router.post("/{engagement_id}/exports/notes")
def export_notes(
    engagement_id: str,
    data: ExportRequestIn = ExportRequestIn(),
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Generate notes PDF, upload to storage, record export."""
    from services.year_end_pdf_service import generate_notes_pdf

    if _USE_MOCK:
        eng = _mock_engagement(engagement_id)
        from routers.year_end_notes import _MOCK_NOTES
        notes = _MOCK_NOTES.get(engagement_id, [])
        pdf_bytes = generate_notes_pdf(eng, notes)
        record = _create_export_record(
            engagement_id=engagement_id,
            firm_id=eng["firm_id"],
            client_id=eng["client_id"],
            financial_year=eng["financial_year"],
            export_type="notes",
            storage_path=_storage_path(eng["firm_id"], eng["client_id"],
                                        eng["financial_year"], f"notes_{engagement_id[:8]}.pdf"),
            file_size_bytes=len(pdf_bytes),
            actor_id=current_user.get("auth_user_id"),
            notes=data.notes,
        )
        _MOCK_EXPORTS.setdefault(engagement_id, []).append(record)
        return api_response(True, record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_engagement(db, engagement_id, current_user["firm_id"])
    notes = _get_notes_data(db, engagement_id, current_user["firm_id"])
    pdf_bytes = generate_notes_pdf(eng, notes)
    filename  = f"notes_{engagement_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    record = _upload_and_record(
        db, eng, "notes", pdf_bytes, filename,
        current_user.get("auth_user_id"), current_user.get("email"), data.notes,
    )
    return api_response(True, record)


@router.post("/{engagement_id}/exports/complete-pack")
def export_complete_pack(
    engagement_id: str,
    data: ExportRequestIn = ExportRequestIn(),
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Generate complete year-end pack PDF (Cover + BS + P&L + Notes + Adjustments + Approvals)."""
    from services.year_end_pdf_service import generate_complete_pack_pdf
    from services.year_end_financial_service import generate_financial_statements

    if _USE_MOCK:
        eng = _mock_engagement(engagement_id)
        statements = generate_financial_statements(None, eng["client_id"], eng["firm_id"],
                                                    eng["fy_start"], eng["fy_end"])
        from routers.year_end_notes import _MOCK_NOTES
        from routers.year_end_adjustments import _MOCK_ADJUSTMENTS
        notes       = _MOCK_NOTES.get(engagement_id, [])
        adjustments = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        pdf_bytes   = generate_complete_pack_pdf(eng, statements, notes, adjustments)
        record = _create_export_record(
            engagement_id=engagement_id,
            firm_id=eng["firm_id"],
            client_id=eng["client_id"],
            financial_year=eng["financial_year"],
            export_type="complete_pack",
            storage_path=_storage_path(eng["firm_id"], eng["client_id"],
                                        eng["financial_year"], f"complete_pack_{engagement_id[:8]}.pdf"),
            file_size_bytes=len(pdf_bytes),
            actor_id=current_user.get("auth_user_id"),
            notes=data.notes,
        )
        _MOCK_EXPORTS.setdefault(engagement_id, []).append(record)
        return api_response(True, record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_engagement(db, engagement_id, current_user["firm_id"])

    try:
        statements = _get_statements_data(db, eng)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    notes       = _get_notes_data(db, engagement_id, current_user["firm_id"])
    adjustments = _get_adjustments_data(db, engagement_id, current_user["firm_id"])
    pdf_bytes   = generate_complete_pack_pdf(eng, statements, notes, adjustments)
    filename    = f"complete_pack_{engagement_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    record = _upload_and_record(
        db, eng, "complete_pack", pdf_bytes, filename,
        current_user.get("auth_user_id"), current_user.get("email"), data.notes,
    )
    return api_response(True, record)


@router.get("/{engagement_id}/exports")
def list_exports(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        return api_response(True, _MOCK_EXPORTS.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("year_end_exports")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return api_response(True, rows)


@router.get("/{engagement_id}/exports/{export_id}/download")
def get_download_url(
    engagement_id: str,
    export_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """Return a signed download URL with 1-hour expiry."""
    if _USE_MOCK:
        exports = _MOCK_EXPORTS.get(engagement_id, [])
        export  = next((e for e in exports if e["id"] == export_id), None)
        if not export:
            raise HTTPException(status_code=404, detail="Export not found")
        return api_response(True, {
            "export_id":   export_id,
            "download_url":"https://mock-storage.caflow.ai/mock-signed-url",
            "expires_in_seconds": 3600,
        })

    from core.supabase_client import get_supabase
    db = get_supabase()

    export = (
        db.table("year_end_exports")
        .select("*")
        .eq("id", export_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    # Generate signed URL with 1-hour (3600 seconds) expiry
    try:
        signed = db.storage.from_(_STORAGE_BUCKET).create_signed_url(
            path=export["storage_path"],
            expires_in=3600,
        )
        download_url = signed.get("signedURL") or signed.get("signed_url") or ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate signed URL: {e}")

    return api_response(True, {
        "export_id":          export_id,
        "download_url":       download_url,
        "expires_in_seconds": 3600,
        "storage_path":       export["storage_path"],
    })

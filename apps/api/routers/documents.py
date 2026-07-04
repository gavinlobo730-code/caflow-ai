import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from models.common import api_response
from repositories.document_repository import document_repo
from services.activity_service import log_activity
from services.audit_service import log_event
from core.permissions import rbac
from core.authz import assert_client_access
from services.internal_client_service import assert_partner_for_internal_id


def _scope_client(client_id, current_user):
    """Explicit client-scope check for multipart writes (the central JSON guard
    cannot see form-data client_id). Internal-client G1 + assignment (M2)."""
    if client_id:
        assert_partner_for_internal_id(client_id, current_user)
        assert_client_access(current_user, client_id)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")

BUCKET = "Documents"


@router.get("")
def list_documents(
    client_id: str | None = None,
    current_user: dict = Depends(rbac("document", "read")),
):
    docs = document_repo.find_all(firm_id=current_user["firm_id"], client_id=client_id)
    return api_response(True, {"documents": docs, "total": len(docs)})


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    client_id: str = Form(...),
    current_user: dict = Depends(rbac("document", "write")),
):
    """
    Upload a document to Supabase Storage and persist metadata.
    Returns a signed download URL valid for 1 hour.
    """
    _scope_client(client_id, current_user)  # block upload to an unassigned client
    firm_id = current_user["firm_id"]
    file_id = str(uuid.uuid4())
    safe_name = file.filename or "upload"
    storage_path = f"{firm_id}/{client_id}/{document_type}/{file_id}_{safe_name}"

    content = await file.read()

    if _USE_MOCK:
        # In mock mode just store metadata — no real upload
        doc = document_repo.create({
            "client_id": client_id,
            "firm_id": firm_id,
            "document_type": document_type,
            "file_name": safe_name,
            "file_path": storage_path,
            "storage_path": storage_path,
            "file_size_bytes": len(content),
            "review_status": "pending_review",
            "uploaded_by": current_user.get("auth_user_id"),
        })
        # H10: immutable audit_log record for the upload (mock path).
        try:
            log_event(
                firm_id, "document", doc.get("id"), "upload",
                actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
                new_data={"file_name": safe_name, "document_type": document_type,
                          "client_id": client_id},
            )
        except Exception:
            pass
        return api_response(True, {"document": doc, "download_url": None})

    from core.supabase_client import get_supabase
    sb = get_supabase()

    upload_result = sb.storage.from_(BUCKET).upload(
        path=storage_path,
        file=content,
        file_options={"content-type": file.content_type or "application/octet-stream"},
    )

    if hasattr(upload_result, "error") and upload_result.error:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {upload_result.error}")

    doc = document_repo.create({
        "client_id": client_id,
        "firm_id": firm_id,
        "document_type": document_type,
        "file_name": safe_name,
        "file_path": storage_path,
        "storage_path": storage_path,
        "storage_bucket": BUCKET,
        "file_size_bytes": len(content),
        "review_status": "pending_review",
        "uploaded_by": current_user.get("auth_user_id"),
    })

    signed = sb.storage.from_(BUCKET).create_signed_url(storage_path, expires_in=3600)
    download_url = signed.get("signedURL") if isinstance(signed, dict) else None

    log_activity(
        action="document_uploaded",
        description=f"{document_type} uploaded: {safe_name}",
        client_id=client_id,
        entity_type="document",
    )
    # H10: immutable audit_log record for the upload (DB path).
    try:
        log_event(
            firm_id, "document", doc.get("id"), "upload",
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"file_name": safe_name, "document_type": document_type,
                      "client_id": client_id},
        )
    except Exception:
        pass

    return api_response(True, {"document": doc, "download_url": download_url})


@router.get("/{doc_id}/download-url")
def get_download_url(
    doc_id: str,
    current_user: dict = Depends(rbac("document", "read")),
):
    """Generate a fresh signed download URL for a document."""
    doc = document_repo.get_or_raise(doc_id)

    # Hard reject: missing firm_id is also a denial — do not allow NULL bypass
    if doc.get("firm_id") != current_user["firm_id"]:
        raise HTTPException(status_code=404, detail="Document not found")

    if _USE_MOCK or not doc.get("storage_path"):
        return api_response(True, {"download_url": None})

    from core.supabase_client import get_supabase
    sb = get_supabase()
    signed = sb.storage.from_(BUCKET).create_signed_url(doc["storage_path"], expires_in=3600)
    download_url = signed.get("signedURL") if isinstance(signed, dict) else None
    return api_response(True, {"download_url": download_url})


@router.delete("/{doc_id}")
def delete_document(
    doc_id: str,
    current_user: dict = Depends(rbac("document", "write")),
):
    """Soft-delete a document by setting deleted_at and deleted_by. The row is
    kept for audit purposes — no hard deletes on document records."""
    doc = document_repo.get_or_raise(doc_id)

    if doc.get("firm_id") != current_user["firm_id"]:
        raise HTTPException(status_code=404, detail="Document not found")

    document_repo.soft_delete(doc_id, deleted_by=current_user.get("auth_user_id"))

    log_activity(
        action="document_deleted",
        description=f"Document deleted: {doc.get('file_name', doc_id)}",
        client_id=doc.get("client_id"),
        entity_type="document",
    )
    # H10: immutable audit_log record for the delete.
    try:
        log_event(
            current_user["firm_id"], "document", doc_id, "delete",
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={"file_name": doc.get("file_name"),
                      "client_id": doc.get("client_id")},
        )
    except Exception:
        pass

    return api_response(True, {"deleted": True})


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    client_id: str = Form(None),
    current_user: dict = Depends(rbac("document", "write")),
):
    """
    R2.8/F19: this endpoint used to return hardcoded, unconditionally
    fabricated Form16/GST-invoice fields (with a fake confidence_score of
    0.94) for every request — no AI call was ever made. That silently
    fabricated data has been removed rather than left live. Real AI-backed
    extraction lives at /api/document-intelligence-v1/extract-invoice
    (invoices) and /api/document-intelligence-v2/notices/extract (government
    notices); this route now fails honestly instead of inventing content.
    """
    allowed = {"form16": "FORM16", "gst_invoice": "GST_INVOICE",
               "FORM16": "FORM16", "GST_INVOICE": "GST_INVOICE"}
    if document_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported document_type: {document_type}")

    _scope_client(client_id, current_user)  # block parsing against an unassigned client

    return JSONResponse(
        status_code=501,
        content=api_response(
            False, None,
            "Document parsing is not implemented on this endpoint. Use "
            "/api/document-intelligence-v1/extract-invoice for invoices or "
            "/api/document-intelligence-v2/notices/extract for government notices.",
        ),
    )

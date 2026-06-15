import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from models.common import api_response
from repositories.document_repository import document_repo
from services.activity_service import log_activity
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

MOCK_FORM16_EXTRACTION = {
    "employee_name": "Rajesh Kumar Sharma",
    "pan": "ABCRS1234D",
    "employer_name": "TechCorp India Pvt Ltd",
    "employer_tan": "MUMB12345C",
    "assessment_year": "2024-25",
    "financial_year": "2023-24",
    "gross_salary_paise": 120000000,
    "gross_salary_display": "₹12,00,000",
    "total_tds_paise": 18500000,
    "total_tds_display": "₹1,85,000",
    "standard_deduction_paise": 5000000,
    "standard_deduction_display": "₹50,000",
    "net_taxable_income_paise": 115000000,
    "net_taxable_income_display": "₹11,50,000",
}

MOCK_GST_INVOICE_EXTRACTION = {
    "supplier_name": "Hindustan Goods Suppliers Pvt Ltd",
    "gstin": "27AABCH1234B1ZA",
    "invoice_number": "HGS/2024-25/001234",
    "invoice_date": "2024-03-15",
    "taxable_value_paise": 10000000,
    "taxable_value_display": "₹1,00,000",
    "cgst_rate": "9%",
    "cgst_paise": 900000,
    "cgst_display": "₹9,000",
    "sgst_rate": "9%",
    "sgst_paise": 900000,
    "sgst_display": "₹9,000",
    "igst_rate": "0%",
    "igst_paise": 0,
    "igst_display": "₹0",
    "total_amount_paise": 11800000,
    "total_amount_display": "₹1,18,000",
    "hsn_code": "8471",
    "place_of_supply": "Maharashtra (27)",
}

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


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    client_id: str = Form(None),
    current_user: dict = Depends(rbac("document", "write")),
):
    allowed = {"form16": "FORM16", "gst_invoice": "GST_INVOICE",
               "FORM16": "FORM16", "GST_INVOICE": "GST_INVOICE"}
    if document_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported document_type: {document_type}")

    _scope_client(client_id, current_user)  # block parsing against an unassigned client
    doc_type = allowed[document_type]
    fields = MOCK_FORM16_EXTRACTION if doc_type == "FORM16" else MOCK_GST_INVOICE_EXTRACTION

    activity = log_activity(
        action="document_uploaded",
        description=f"{doc_type} parsed: {file.filename}",
        client_id=client_id,
        entity_type="document",
    )

    return api_response(True, {
        "document_type": doc_type,
        "file_name": file.filename,
        "fields": fields,
        "confidence_score": 0.94,
        "review_status": "pending_review",
        "activity": activity,
    })

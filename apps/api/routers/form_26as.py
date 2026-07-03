"""
Form 26AS Reconciliation Module.
IT Act 1961 Section 203AA — Annual Tax Statement.
# CA REVIEW REQUIRED — Reconciliation output must be reviewed before filing
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/form-26as", tags=["form_26as"])
_logger = logging.getLogger("caflow.form26as.router")


class CreateUploadRequest(BaseModel):
    client_id: str
    financial_year: str
    document_id: Optional[str] = None


class ParseRequest(BaseModel):
    raw_text: str


class RunReconRequest(BaseModel):
    client_id: str
    financial_year: str


@router.post("/uploads")
def create_upload(
    req: CreateUploadRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Create 26AS upload record."""
    from domain.income_tax.form26as_service import create_upload
    try:
        upload = create_upload(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            uploaded_by=current_user["id"],
            document_id=req.document_id,
        )
        return api_response(True, upload)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/uploads/{upload_id}/parse")
def parse_upload(
    upload_id: str,
    req: ParseRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Parse Form 26AS text content into structured records.
    Upload the raw text from TRACES portal (PDF → text extraction).
    """
    from domain.income_tax.form26as_service import (
        parse_26as_text, save_parsed_records, _MOCK_UPLOADS
    )
    import os
    use_mock = not os.environ.get("SUPABASE_URL")

    try:
        if use_mock:
            upload = _MOCK_UPLOADS.get(upload_id)
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            res = sb.table("form_26as_uploads").select("*").eq("id", upload_id).eq(
                "firm_id", current_user["firm_id"]
            ).single().execute()
            upload = res.data

        if not upload:
            raise HTTPException(404, detail="Upload not found")

        records = parse_26as_text(req.raw_text)
        result = save_parsed_records(
            firm_id=current_user["firm_id"],
            upload_id=upload_id,
            client_id=upload["client_id"],
            financial_year=upload["financial_year"],
            records=records,
        )
        return api_response(True, {
            "upload": result,
            "records_parsed": len(records),
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.exception("Parse failed")
        raise HTTPException(500, detail=str(e))


@router.get("/uploads")
def list_uploads(
    client_id: str,
    financial_year: Optional[str] = None,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.form26as_service import list_uploads as _list
    return api_response(True, _list(current_user["firm_id"], client_id, financial_year))


@router.post("/reconcile")
def run_reconciliation(
    req: RunReconRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Run 26AS reconciliation against TDS ledger.
    Detects missing credits, mismatches, duplicates.
    Creates AI insight if variance exceeds 1% threshold.
    # CA REVIEW REQUIRED — Review results before acting.
    """
    from domain.income_tax.form26as_service import list_uploads, run_reconciliation as _run

    uploads = list_uploads(current_user["firm_id"], req.client_id, req.financial_year)
    parsed_uploads = [u for u in uploads if u.get("parse_status") == "parsed"]
    if not parsed_uploads:
        raise HTTPException(400, detail="No parsed 26AS upload found for this financial year")

    latest_upload = parsed_uploads[0]
    try:
        result = _run(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            upload_id=latest_upload["id"],
            financial_year=req.financial_year,
            created_by=current_user["id"],
        )
        timeline_service.log(
            client_id=req.client_id,
            category="tax",
            action="26as_reconciled",
            description=f"26AS reconciliation completed for FY {req.financial_year}: "
                        f"{result.get('matched_count',0)} matched, "
                        f"{result.get('mismatch_count',0)} mismatches",
            severity="success" if result.get("mismatch_count", 0) == 0 else "warning",
            metadata=result,
        )
        return api_response(True, {**result, "ca_review_required": True})
    except Exception as e:
        _logger.exception("Reconciliation failed")
        raise HTTPException(500, detail=str(e))


@router.get("/reconciliation")
def get_reconciliation(
    client_id: str,
    financial_year: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    from domain.income_tax.form26as_service import get_reconciliation as _get
    result = _get(current_user["firm_id"], client_id, financial_year)
    return api_response(True, result)


@router.post("/uploads/{upload_id}/uploaded")
def mark_26as_uploaded(
    upload_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Mark that CA has uploaded 26AS from TRACES portal."""
    from domain.income_tax.form26as_service import _MOCK_UPLOADS
    import os
    use_mock = not os.environ.get("SUPABASE_URL")

    if use_mock:
        upload = _MOCK_UPLOADS.get(upload_id, {})
        timeline_service.log(
            client_id=upload.get("client_id", ""),
            category="tax",
            action="26as_uploaded",
            description=f"Form 26AS uploaded for FY {upload.get('financial_year')}",
            severity="info",
            metadata={"upload_id": upload_id},
        )
        return api_response(True, upload)

    from core.supabase_client import get_supabase
    sb = get_supabase()
    res = sb.table("form_26as_uploads").select("*").eq("id", upload_id).eq(
        "firm_id", current_user["firm_id"]
    ).single().execute()
    upload = res.data or {}
    timeline_service.log(
        client_id=upload.get("client_id", ""),
        category="tax",
        action="26as_uploaded",
        description=f"Form 26AS uploaded for FY {upload.get('financial_year')}",
        severity="info",
        metadata={"upload_id": upload_id},
    )
    return api_response(True, upload)

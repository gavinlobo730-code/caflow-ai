"""
GST Portal Read-Only Integration.
CGST Act 2017 — Compliance data retrieval.

READ-ONLY ONLY. No filing. No submission.
# CA REVIEW REQUIRED — All data must be reviewed before acting on it.
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/gst-portal", tags=["gst_portal"])
_logger = logging.getLogger("caflow.gst_portal.router")


class CreateSyncJobRequest(BaseModel):
    client_id: str
    gstin: str
    scope: Optional[list[str]] = None
    sync_type: str = "manual"


class ManualSnapshotRequest(BaseModel):
    client_id: str
    gstin: str
    snapshot_type: str
    data: dict
    financial_year: Optional[str] = None
    period: Optional[str] = None


@router.post("/sync-jobs")
def create_sync_job(
    req: CreateSyncJobRequest,
    current_user: dict = Depends(rbac("gst", "read")),
):
    """Create a GST portal sync job. Read-only — no filing."""
    from domain.gst.portal_service import create_sync_job
    try:
        job = create_sync_job(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            gstin=req.gstin,
            triggered_by=current_user["id"],
            scope=req.scope,
            sync_type=req.sync_type,
        )
        return api_response(True, job)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/sync-jobs/{job_id}/run")
def run_sync_job(
    job_id: str,
    current_user: dict = Depends(rbac("gst", "read")),
):
    """
    Execute GST portal sync. Read-only.
    # CA REVIEW REQUIRED — Data pulled from portal, not submitted.
    """
    from domain.gst.portal_service import run_sync_job as _run, list_sync_jobs
    try:
        result = _run(current_user["firm_id"], job_id)
        timeline_service.log(
            client_id="",  # Firm-level event
            category="compliance",
            action="gst_sync_completed",
            description=f"GST portal sync completed: {result.get('snapshots_created', 0)} snapshots",
            severity="info",
            metadata={"job_id": job_id, **result},
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/sync-jobs")
def list_sync_jobs(
    client_id: str,
    current_user: dict = Depends(rbac("gst", "read")),
):
    from domain.gst.portal_service import list_sync_jobs as _list
    return api_response(True, _list(current_user["firm_id"], client_id))


@router.post("/snapshots")
def save_manual_snapshot(
    req: ManualSnapshotRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save manually uploaded GST portal data."""
    from domain.gst.portal_service import save_manual_snapshot as _save
    try:
        snap = _save(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            gstin=req.gstin,
            snapshot_type=req.snapshot_type,
            data=req.data,
            financial_year=req.financial_year,
            period=req.period,
        )
        return api_response(True, snap)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/snapshots")
def list_snapshots(
    client_id: str,
    snapshot_type: Optional[str] = None,
    current_user: dict = Depends(rbac("gst", "read")),
):
    from domain.gst.portal_service import list_snapshots as _list
    return api_response(True, _list(current_user["firm_id"], client_id, snapshot_type))

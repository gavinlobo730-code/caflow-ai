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
from core.authz import assert_client_access
from models.common import api_response
from services.timeline_service import timeline_service
from models.fy import OptionalFYLabel

router = APIRouter(prefix="/api/gst-portal", tags=["gst_portal"])
_logger = logging.getLogger("caflow.gst_portal.router")

# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# Read-only against the GST portal, but every row here is a named client's
# filing data: sync jobs carry the client's GSTIN, and snapshots hold what the
# portal returned for it. This router imported no authz.
#
# `/sync-jobs/{job_id}/run` is the one addressed by a row rather than naming a
# client, so the job is resolved first — and it must be resolved BEFORE the run,
# because running it writes snapshots into that client's record.


def _assert_job_scope(current_user: dict, job_id: str) -> dict:
    """Resolve a sync job within the firm and check its client."""
    from domain.gst.portal_service import get_sync_job
    job = get_sync_job(current_user["firm_id"], job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    assert_client_access(current_user, job.get("client_id"))
    return job


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
    financial_year: OptionalFYLabel = None
    period: Optional[str] = None


@router.post("/sync-jobs")
def create_sync_job(
    req: CreateSyncJobRequest,
    # was rbac("gst", "read") — this MUTATES (creates / runs a sync job), and
    # save_manual_snapshot in this same file already uses gst:compute.
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Create a GST portal sync job. Read-only — no filing."""
    assert_client_access(current_user, req.client_id)
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
    # was rbac("gst", "read") — this MUTATES (creates / runs a sync job), and
    # save_manual_snapshot in this same file already uses gst:compute.
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Execute GST portal sync. Read-only.
    # CA REVIEW REQUIRED — Data pulled from portal, not submitted.
    """
    from domain.gst.portal_service import run_sync_job as _run, list_sync_jobs
    _assert_job_scope(current_user, job_id)
    try:
        result = _run(current_user["firm_id"], job_id)
        # A failed/partial sync must read as such to the CA, not as a plain
        # "completed" -- see run_sync_job's own status computation.
        status = result.get("status", "completed")
        failed = result.get("failed") or []
        if status == "completed":
            title, severity = "GST portal sync completed", "success"
        elif status == "partial_failure":
            title, severity = "GST portal sync partially failed", "warning"
        else:
            title, severity = "GST portal sync failed", "critical"
        description = f"{result.get('snapshots_created', 0)} snapshot(s) synced"
        if failed:
            description += "; failed: " + ", ".join(f["snap_type"] for f in failed)
        timeline_service.log(
            client_id="",  # Firm-level event
            firm_id=current_user["firm_id"],
            category="compliance",
            title=title,
            description=description,
            severity=severity,
            entity_type="gst_sync_job", entity_id=job_id,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/sync-jobs")
def list_sync_jobs(
    client_id: str,
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    from domain.gst.portal_service import list_sync_jobs as _list
    return api_response(True, _list(current_user["firm_id"], client_id))


@router.post("/snapshots")
def save_manual_snapshot(
    req: ManualSnapshotRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save manually uploaded GST portal data."""
    assert_client_access(current_user, req.client_id)
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
    assert_client_access(current_user, client_id)
    from domain.gst.portal_service import list_snapshots as _list
    return api_response(True, _list(current_user["firm_id"], client_id, snapshot_type))

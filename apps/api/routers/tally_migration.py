"""
Tally Migration System — Import Tally data into CAflow.
Firm-level Migration Center.

Workflow: Upload → Parse → Mapping → Validation → Preview → Import
Dry-run required before actual import. Rollback supported.
Never imports without explicit CA confirmation.
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/tally-migration", tags=["tally_migration"])
_logger = logging.getLogger("caflow.tally.router")


class CreateJobRequest(BaseModel):
    name: str
    source_file_name: str
    target_financial_year: str
    import_types: list[str] = Field(
        default=["ledgers", "journals"],
        description="ledgers|journals|customers|vendors|opening_balances|masters",
    )
    description: Optional[str] = None
    source_file_size_bytes: Optional[int] = None


class ParseXMLRequest(BaseModel):
    xml_content: str


class ExecuteImportRequest(BaseModel):
    is_dry_run: bool = True  # Default to dry-run for safety


@router.post("/jobs")
def create_job(
    req: CreateJobRequest,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create a Tally migration job."""
    from domain.tally.migration_service import create_migration_job
    try:
        job = create_migration_job(
            firm_id=current_user["firm_id"],
            name=req.name,
            source_file_name=req.source_file_name,
            target_financial_year=req.target_financial_year,
            created_by=current_user["id"],
            import_types=req.import_types,
            description=req.description,
            source_file_size_bytes=req.source_file_size_bytes,
        )
        return api_response(True, job)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/jobs")
def list_jobs(
    current_user: dict = Depends(rbac("accounting", "read")),
):
    from domain.tally.migration_service import list_migration_jobs
    return api_response(True, list_migration_jobs(current_user["firm_id"]))


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    from domain.tally.migration_service import get_migration_job
    job = get_migration_job(current_user["firm_id"], job_id)
    if not job:
        raise HTTPException(404, detail="Migration job not found")
    return api_response(True, job)


@router.post("/jobs/{job_id}/parse")
def parse_xml(
    job_id: str,
    req: ParseXMLRequest,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Parse uploaded Tally XML export."""
    from domain.tally.migration_service import (
        parse_tally_xml, validate_migration_data, save_migration_items, get_migration_job
    )
    job = get_migration_job(current_user["firm_id"], job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")

    try:
        parsed = parse_tally_xml(req.xml_content)
        items, errors = validate_migration_data(parsed, job.get("import_types", []))
        save_migration_items(current_user["firm_id"], job_id, items)
        return api_response(True, {
            "job_id": job_id,
            "parsed_counts": {k: len(v) for k, v in parsed.items()},
            "total_items": len(items),
            "validation_errors": errors,
            "can_proceed": len(errors) == 0,
        })
    except Exception as e:
        _logger.exception("Parse failed for job %s", job_id)
        raise HTTPException(500, detail=str(e))


@router.get("/jobs/{job_id}/preview")
def preview_import(
    job_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Preview all items to be imported, grouped by type."""
    from domain.tally.migration_service import get_migration_preview
    try:
        preview = get_migration_preview(current_user["firm_id"], job_id)
        return api_response(True, preview)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/jobs/{job_id}/import")
def execute_import(
    job_id: str,
    req: ExecuteImportRequest,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """
    Execute Tally import. Defaults to dry-run.
    Set is_dry_run=false only after reviewing the preview.
    Never imports without explicit CA confirmation.
    """
    from domain.tally.migration_service import execute_import as _execute
    try:
        result = _execute(
            firm_id=current_user["firm_id"],
            job_id=job_id,
            actor_id=current_user["id"],
            is_dry_run=req.is_dry_run,
        )
        if not req.is_dry_run:
            timeline_service.log(
                client_id="",
                category="accounting",
                action="tally_import_completed",
                description=f"Tally migration completed: {result.get('imported', 0)} records imported",
                severity="success",
                metadata={"job_id": job_id, **result},
            )
        return api_response(True, {
            **result,
            "ca_review_required": True,
            "warning": "Review all items in preview before setting is_dry_run=false",
        })
    except Exception as e:
        _logger.exception("Import failed for job %s", job_id)
        raise HTTPException(500, detail=str(e))


@router.post("/jobs/{job_id}/rollback")
def rollback_import(
    job_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Rollback: delete all records created by this import job."""
    from domain.tally.migration_service import rollback_migration
    try:
        result = rollback_migration(current_user["firm_id"], job_id, current_user["id"])
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

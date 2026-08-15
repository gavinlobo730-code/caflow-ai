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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, filter_by_client
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/tally-migration", tags=["tally_migration"])
_logger = logging.getLogger("caflow.tally.router")


def _assert_job_scope(current_user: dict, job_id: str) -> dict:
    """Fetch the job (firm-scoped) and 404 unless the caller may also access
    its client — jobs are optionally client_id-scoped (ledgers/journals can
    be firm-level; customers/vendors need a target client), and
    can_access_client(user, None) is always True, so a client-less job is
    unaffected. ONE fixed message for both the missing-row and
    hidden-client branches.

    # M2 audit finding: get_job/parse_xml/preview_import/execute_import/
    # rollback_import resolved the job by firm_id alone and never checked
    # its optional client_id against the caller's assignment — an
    # Executive/Reviewer/Manager could reach, parse, preview, actually
    # IMPORT (writing real customers/vendors into the target client's
    # books) or roll back another staff member's assigned client's Tally
    # migration.
    """
    from domain.tally.migration_service import get_migration_job
    job = get_migration_job(current_user["firm_id"], job_id)
    if not job or not can_access_client(current_user, job.get("client_id")):
        raise HTTPException(404, detail="Migration job not found")
    return job


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
    # Target client whose books these are. Required in practice for
    # customer/vendor imports (per-client masters); optional for firm-level
    # ledger/journal migration.
    client_id: Optional[str] = None


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

    # A supplied client_id must belong to the caller's firm AND the caller's
    # own assignment (never trust a request-body id — same guard pattern as
    # every client-scoped router). assert_client_access(user, None) is a
    # no-op, so a firm-level (no client_id) job is unaffected.
    assert_client_access(current_user, req.client_id)

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
            client_id=req.client_id,
        )
        return api_response(True, job)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/jobs")
def list_jobs(
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """M2 audit finding: this returned every job in the firm, unfiltered —
    an Executive/Reviewer/Manager could see which OTHER clients had a Tally
    migration in progress (file names, status) outside their own assigned
    book. filter_by_client keeps client-less (firm-level) jobs unconditionally."""
    from domain.tally.migration_service import list_migration_jobs
    jobs = list_migration_jobs(current_user["firm_id"])
    return api_response(True, filter_by_client(current_user, jobs))


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    job = _assert_job_scope(current_user, job_id)
    return api_response(True, job)


@router.post("/jobs/{job_id}/parse")
def parse_xml(
    job_id: str,
    req: ParseXMLRequest,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Parse uploaded Tally XML export."""
    from domain.tally.migration_service import (
        parse_tally_xml, validate_migration_data, save_migration_items
    )
    job = _assert_job_scope(current_user, job_id)

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
    _assert_job_scope(current_user, job_id)
    try:
        preview = get_migration_preview(current_user["firm_id"], job_id)
        return api_response(True, preview)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/jobs/{job_id}/import")
def execute_import(
    job_id: str,
    req: ExecuteImportRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """
    Execute Tally import. Defaults to dry-run.
    Set is_dry_run=false only after reviewing the preview.
    Never imports without explicit CA confirmation.

    A DRY RUN IS SYNCHRONOUS, A REAL IMPORT IS NOT.

    The dry run writes nothing and returns the report the CA has to read before
    approving, so it stays inline — an answer that arrives later is no use to
    someone deciding whether to proceed.

    The real import is handed to a background task and this returns immediately
    with `status: "importing"`. Poll GET /jobs/{job_id} for progress:
    `imported_items` / `failed_items` / `total_items` advance as it runs, and
    `status` settles on `completed` or `failed`.

    Inline, it could not survive real data. gunicorn runs `--timeout 120` and the
    import costs two round trips per item, so the worker was killed somewhere
    past ~1,200 items — mid-write, with no report. It also occupied the single
    worker throughout, freezing the app for every other user. See
    domain/tally/migration_service.run_import_detached.
    """
    from domain.tally.migration_service import (
        execute_import as _execute, run_import_detached,
    )
    _assert_job_scope(current_user, job_id)

    if not req.is_dry_run:
        # Queued AFTER the scope check above, so an unauthorized caller never
        # starts one. FastAPI runs a sync background task in its threadpool, so
        # this does not block the event loop while it runs.
        background.add_task(
            run_import_detached,
            firm_id=current_user["firm_id"],
            job_id=job_id,
            actor_id=current_user["id"],
        )
        timeline_service.log(
            client_id="",
            category="accounting",
            action="tally_import_started",
            description="Tally migration started",
            severity="info",
            metadata={"job_id": job_id},
        )
        return api_response(True, {
            "job_id": job_id,
            "status": "importing",
            "is_dry_run": False,
            "ca_review_required": True,
            "poll": f"/api/tally-migration/jobs/{job_id}",
            "message": (
                "Import started. It runs in the background — poll the job for "
                "progress. Safe to re-run if it stops partway: items already "
                "imported are skipped, not duplicated."
            ),
        })

    try:
        result = _execute(
            firm_id=current_user["firm_id"],
            job_id=job_id,
            actor_id=current_user["id"],
            is_dry_run=True,
        )
        return api_response(True, {
            **result,
            "ca_review_required": True,
            "warning": "Review all items in preview before setting is_dry_run=false",
        })
    except ValueError as e:
        # Job not found for THIS firm — cross-firm ids must 404, not 500.
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        _logger.exception("Dry run failed for job %s", job_id)
        raise HTTPException(500, detail=str(e))


@router.post("/jobs/{job_id}/rollback")
def rollback_import(
    job_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Rollback: delete all records created by this import job."""
    from domain.tally.migration_service import rollback_migration
    _assert_job_scope(current_user, job_id)
    try:
        result = rollback_migration(current_user["firm_id"], job_id, current_user["id"])
        return api_response(True, result)
    except ValueError as e:
        # Job not found for THIS firm — cross-firm ids must 404, not 500.
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))

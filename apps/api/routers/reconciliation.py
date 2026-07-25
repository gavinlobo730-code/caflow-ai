"""
"Verify Books" — on-demand books-integrity check (task #244).

QuickBooks Desktop ships a first-party Verify/Rebuild tool because books can
drift and a CA needs a way to check, on demand, without waiting for a nightly
job or filing a support ticket. This is that tool: a Partner presses "Verify
Books" for a client and gets back the SAME checks jobs/scheduler.py already
runs nightly (services/reconciliation_service.py — trial balance, missing
COGS/inventory-receipt journals, inventory cache-vs-ledger drift, AR/AP
sub-ledger vs GL), run live.

Partner-only (matching the audit log's own posture — this is
leadership-visibility financial-integrity data, and RLS on
reconciliation_runs/reconciliation_findings, migration 244, already enforces
it at the database layer too).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


class VerifyBooksRequest(BaseModel):
    client_id: str


class ResolveFindingRequest(BaseModel):
    resolution_note: Optional[str] = None


@router.post("/verify")
def verify_books(
    body: VerifyBooksRequest,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Run every reconciliation check for one client, right now, and return
    the findings. Persists the same reconciliation_runs/reconciliation_findings
    rows the nightly scheduled job writes (migration 244) — this is not a
    separate, throwaway preview; it's a real run a CA can come back to later."""
    firm_id = current_user["firm_id"]
    assert_client_access(current_user, body.client_id)

    from core.supabase_client import get_supabase
    from services.reconciliation_service import run_reconciliation

    try:
        result = run_reconciliation(
            get_supabase(), firm_id, body.client_id,
            trigger="manual", triggered_by=current_user.get("id"),
        )
    except Exception as e:
        return api_response(False, None, str(e))

    return api_response(True, result)


@router.get("/runs")
def list_runs(
    client_id: str = Query(...),
    limit: int = Query(20, le=100),
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Run history for a client, most recent first — so a Partner can see
    whether books-integrity findings are new, recurring, or already resolved."""
    firm_id = current_user["firm_id"]
    assert_client_access(current_user, client_id)

    from core.supabase_client import get_supabase

    try:
        runs = (
            get_supabase().table("reconciliation_runs").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .order("started_at", desc=True).limit(limit).execute().data or []
        )
    except Exception as e:
        return api_response(False, None, str(e))

    return api_response(True, {"runs": runs})


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """One run's full detail, including every finding it produced."""
    firm_id = current_user["firm_id"]
    from core.supabase_client import get_supabase
    db = get_supabase()

    try:
        runs = (
            db.table("reconciliation_runs").select("*")
            .eq("id", run_id).eq("firm_id", firm_id).limit(1).execute().data or []
        )
        if not runs:
            raise HTTPException(status_code=404, detail="Not found")
        assert_client_access(current_user, runs[0]["client_id"])

        findings = (
            db.table("reconciliation_findings").select("*")
            .eq("run_id", run_id).eq("firm_id", firm_id)
            .order("created_at").execute().data or []
        )
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))

    return api_response(True, {"run": runs[0], "findings": findings})


@router.post("/findings/{finding_id}/resolve")
def resolve_finding(
    finding_id: str,
    body: ResolveFindingRequest,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Marks a finding reviewed — a record that a Partner looked at it and
    (per the resolution note) actioned it elsewhere. This endpoint never
    itself corrects the underlying discrepancy — see
    reconciliation_findings' own table comment (migration 244) for why a
    genuine finding always needs a deliberate, human-reviewed fix, the same
    way this session's own manual corrections did."""
    firm_id = current_user["firm_id"]
    from core.supabase_client import get_supabase
    db = get_supabase()

    from datetime import datetime, timezone

    try:
        existing = (
            db.table("reconciliation_findings").select("id, client_id")
            .eq("id", finding_id).eq("firm_id", firm_id).limit(1).execute().data or []
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Not found")
        assert_client_access(current_user, existing[0]["client_id"])

        updated = (
            db.table("reconciliation_findings")
            .update({
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolved_by": current_user.get("id"),
                "resolution_note": body.resolution_note,
            })
            .eq("id", finding_id).eq("firm_id", firm_id).execute().data or []
        )
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))

    return api_response(True, {"finding": updated[0] if updated else None})

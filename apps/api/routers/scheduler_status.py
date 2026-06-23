"""
Scheduler health and status endpoints.
GET /api/scheduler/status  — returns scheduler health + recent run history
POST /api/scheduler/run    — manual trigger (same as trigger-scheduler-run)
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status")
def scheduler_status(current_user: dict = Depends(rbac("team", "read"))):
    """Return scheduler health (enabled/running/stale/warnings/last_runs) plus the
    last 10 run records for the caller's firm (recent_runs, kept for backward-compat)."""
    from jobs.scheduler import _USE_MOCK, _MOCK_RUNS, scheduler_health
    from core.supabase_client import get_supabase

    health = scheduler_health()

    recent_runs = []
    if _USE_MOCK:
        # Mock entries may lack started_at — sort with a safe key so this never crashes.
        runs = sorted(
            _MOCK_RUNS,
            key=lambda r: r.get("started_at") or r.get("finished_at") or "",
            reverse=True,
        )
        recent_runs = runs[:10]
    else:
        try:
            result = (
                get_supabase().table("scheduler_runs")
                .select("*")
                .eq("firm_id", current_user["firm_id"])
                .order("started_at", desc=True)
                .limit(10)
                .execute()
            )
            recent_runs = result.data or []
        except Exception:
            pass

    return api_response(True, {
        "enabled": health.get("enabled", False),
        "running": health.get("running", False),
        "stale": health.get("stale", False),
        "warnings": health.get("warnings", []),
        "last_runs": health.get("last_runs", {}),
        "recent_runs": recent_runs,
    })


@router.post("/run")
def trigger_run(
    force: bool = False,
    current_user: dict = Depends(rbac("team", "write")),
):
    """Manually trigger the daily scheduler jobs for the caller's firm.

    Scoped to the caller's firm by default (tenant isolation) — mirrors
    /api/tasks/trigger-scheduler-run. Idempotent per day unless force=true.
    """
    from jobs.scheduler import run_daily_jobs
    firm_id = current_user.get("firm_id")
    results = run_daily_jobs(firm_id=firm_id, force=force)
    return api_response(True, {"results": results})

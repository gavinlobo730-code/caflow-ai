"""
Scheduler health and status endpoints.
GET /api/scheduler/status  — returns scheduler state + recent run history
POST /api/scheduler/run    — manual trigger (same as trigger-scheduler-run)
"""
from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status")
def scheduler_status(current_user: dict = Depends(rbac("team", "read"))):
    """Return scheduler running state and last 10 run records."""
    from jobs.scheduler import _scheduler, _USE_MOCK, _MOCK_RUNS
    from core.supabase_client import get_supabase

    is_running = _scheduler is not None and _scheduler.running if _scheduler else False
    enabled = __import__("os").environ.get("ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes")

    recent_runs = []
    if _USE_MOCK:
        recent_runs = list(reversed(_MOCK_RUNS[-10:]))
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
        "enabled": enabled,
        "running": is_running,
        "recent_runs": recent_runs,
    })


@router.post("/run")
def trigger_run(
    force: bool = False,
    current_user: dict = Depends(rbac("team", "write")),
):
    """Manually trigger the daily scheduler jobs."""
    from jobs.scheduler import run_daily_jobs
    results = run_daily_jobs(force=force)
    return api_response(True, {"results": results})

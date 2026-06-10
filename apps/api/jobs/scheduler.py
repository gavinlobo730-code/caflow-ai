"""
In-process daily scheduler for Phase 1.2 automation.

Runs (per firm, once per day):
  1. Recurring task generation (assignment rules applied inside the service)
  2. Escalation rules (due-soon + overdue)
  3. Invoice overdue transitions (Issued -> Overdue)

Idempotency:
  - recurring generation is idempotent per-day inside the service
    (last_generated_at check)
  - the scheduler additionally records each job run in scheduler_runs and
    skips jobs already completed successfully today, so restarts or multiple
    workers do not double-run

Enable with ENABLE_SCHEDULER=true (off by default so multi-worker gunicorn
deployments can dedicate a single scheduler process, or trigger the same
logic externally via POST /api/tasks/trigger-scheduler-run with a cron).
"""
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger("caflow.jobs")

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_RUNS: list[dict] = []

_scheduler = None


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _already_ran_today(job_name: str, firm_id: Optional[str]) -> bool:
    today = date.today().isoformat()
    if _USE_MOCK:
        return any(
            r["job_name"] == job_name and r["run_date"] == today
            and r.get("firm_id") == firm_id and r["status"] == "success"
            for r in _MOCK_RUNS
        )
    try:
        query = (
            _get_db().table("scheduler_runs").select("id")
            .eq("job_name", job_name).eq("run_date", today).eq("status", "success")
        )
        if firm_id:
            query = query.eq("firm_id", firm_id)
        result = query.limit(1).execute()
        return bool(result.data)
    except Exception as e:
        logger.warning(f"scheduler_runs check failed ({job_name}): {e}")
        return False


def _log_run(job_name: str, firm_id: Optional[str], status: str, detail: dict) -> None:
    record = {
        "job_name": job_name,
        "run_date": date.today().isoformat(),
        "firm_id": firm_id,
        "status": status,
        "detail": detail,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if _USE_MOCK:
        _MOCK_RUNS.append(record)
        return
    try:
        _get_db().table("scheduler_runs").insert(record).execute()
    except Exception as e:
        logger.warning(f"Failed to log scheduler run ({job_name}): {e}")


def _list_firm_ids() -> list[str]:
    if _USE_MOCK:
        from repositories.user_repository import user_repo
        try:
            users = user_repo.find_all()
            return sorted({u["firm_id"] for u in users if u.get("firm_id")})
        except Exception:
            return []
    try:
        result = _get_db().table("firms").select("id").execute()
        return [f["id"] for f in (result.data or [])]
    except Exception as e:
        logger.warning(f"Could not list firms, falling back to distinct task firm_ids: {e}")
        try:
            result = _get_db().table("tasks").select("firm_id").execute()
            return sorted({t["firm_id"] for t in (result.data or []) if t.get("firm_id")})
        except Exception:
            return []


def run_daily_jobs(firm_id: Optional[str] = None, force: bool = False) -> dict:
    """
    Run all daily automation jobs. Safe to call repeatedly — each job is
    skipped if it already succeeded today (unless force=True).
    """
    firm_ids = [firm_id] if firm_id else _list_firm_ids()
    results: dict = {"firms": {}, "ran_at": datetime.now(timezone.utc).isoformat()}

    # Recurring generation handles all firms in one pass when firm_id is None,
    # but we run per-firm so the run log and failures are firm-scoped.
    for fid in firm_ids:
        firm_result: dict = {}

        # 1. Recurring task generation
        if force or not _already_ran_today("recurring_generation", fid):
            try:
                from jobs.recurring_task_job import run_recurring_generation_job
                outcome = run_recurring_generation_job(firm_id=fid)
                firm_result["recurring"] = {"count": outcome.get("count", 0), "error": outcome.get("error")}
                _log_run("recurring_generation", fid,
                         "success" if outcome.get("success") else "failed",
                         {"count": outcome.get("count", 0), "error": outcome.get("error")})
            except Exception as e:
                logger.error(f"Recurring job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring"] = {"error": str(e)}
                _log_run("recurring_generation", fid, "failed", {"error": str(e)})
        else:
            firm_result["recurring"] = {"skipped": "already ran today"}

        # 2. Escalation rules
        if force or not _already_ran_today("escalations", fid):
            try:
                from services.escalation_service import escalation_service
                outcome = escalation_service.run_all_escalations(fid)
                firm_result["escalations"] = outcome
                _log_run("escalations", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Escalation job failed for firm {fid}: {e}", exc_info=True)
                firm_result["escalations"] = {"error": str(e)}
                _log_run("escalations", fid, "failed", {"error": str(e)})
        else:
            firm_result["escalations"] = {"skipped": "already ran today"}

        # 3. Invoice overdue transitions
        if force or not _already_ran_today("invoice_overdue", fid):
            try:
                from services.invoice_lifecycle_service import run_overdue_check
                outcome = run_overdue_check(firm_id=fid)
                firm_result["invoice_overdue"] = outcome
                _log_run("invoice_overdue", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Invoice overdue job failed for firm {fid}: {e}", exc_info=True)
                firm_result["invoice_overdue"] = {"error": str(e)}
                _log_run("invoice_overdue", fid, "failed", {"error": str(e)})
        else:
            firm_result["invoice_overdue"] = {"skipped": "already ran today"}

        results["firms"][fid] = firm_result

    logger.info(f"Daily scheduler run completed for {len(firm_ids)} firm(s)")
    return results


def start_scheduler() -> None:
    """Start the APScheduler background scheduler (called from app startup)."""
    global _scheduler
    if os.environ.get("ENABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
        logger.info("Scheduler disabled (set ENABLE_SCHEDULER=true to enable)")
        return
    if _scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    # 06:00 IST daily — before the Indian working day starts
    _scheduler.add_job(run_daily_jobs, CronTrigger(hour=6, minute=0), id="daily_automation")
    _scheduler.start()
    logger.info("Background scheduler started (daily automation at 06:00 IST)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

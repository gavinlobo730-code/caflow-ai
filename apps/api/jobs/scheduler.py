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
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


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

        # 4. Collections — AR overdue sweep + reminders (Amendment v1.1 Batch 4).
        #    Operates on the firm's internal-client fee invoices. Sweep is
        #    idempotent; reminders are cadence-gated (anti-spam).
        if force or not _already_ran_today("collections", fid):
            try:
                from services.collections_service import sweep_overdue, send_overdue_reminders
                swept = sweep_overdue(fid)
                reminders = send_overdue_reminders(fid)
                outcome = {**swept, **reminders}
                firm_result["collections"] = outcome
                _log_run("collections", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Collections job failed for firm {fid}: {e}", exc_info=True)
                firm_result["collections"] = {"error": str(e)}
                _log_run("collections", fid, "failed", {"error": str(e)})
        else:
            firm_result["collections"] = {"skipped": "already ran today"}

        # 5. Customer payment reminders (Phase 4.2) — emails the firm's CUSTOMERS
        #    an overdue-payment reminder on the 7/14/21-day cadence (capped).
        #    Collections-only: posts no journal and touches no statement/GST/cash
        #    flow. Cadence + anti-spam gated; also runnable manually via the API
        #    so it works whether or not the scheduler is enabled.
        if force or not _already_ran_today("customer_reminders", fid):
            try:
                from services.collections_service import run_due_reminders
                outcome = run_due_reminders(fid)
                firm_result["customer_reminders"] = outcome
                _log_run("customer_reminders", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Customer reminders job failed for firm {fid}: {e}", exc_info=True)
                firm_result["customer_reminders"] = {"error": str(e)}
                _log_run("customer_reminders", fid, "failed", {"error": str(e)})
        else:
            firm_result["customer_reminders"] = {"skipped": "already ran today"}

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


# ── Phase 10B — Workflow Schedule Runner ──────────────────────────────────────

def _compute_next_run(cron_expression: str, timezone_str: str = "Asia/Kolkata") -> str:
    """Compute next run time from a cron expression using croniter."""
    try:
        import pytz
        from croniter import croniter
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        cron = croniter(cron_expression, now)
        next_dt = cron.get_next(datetime)
        return next_dt.astimezone(timezone.utc).isoformat()
    except Exception as e:
        logger.error("Failed to compute next run for cron %s: %s", cron_expression, e)
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


# Re-export as public name for tests and external callers
compute_next_run = _compute_next_run


def run_due_schedules() -> None:
    """
    Workflow scheduler tick — called every minute when ENABLE_SCHEDULER=true.

    Finds all active workflow_schedules with next_run_at <= now, fires the
    corresponding workflow template via the engine, then updates schedule
    metadata (last_run_at, last_run_status, next_run_at).

    NOT safe for multi-worker deployments — use a dedicated single-worker
    process or an external cron job.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    from repositories.workflow_repository import workflow_repo as repo
    from domain.workflow_engine_v2 import workflow_engine as engine

    try:
        schedules = repo.list_schedules_due(now_iso)
    except Exception as e:
        logger.error("Failed to fetch due workflow schedules: %s", e)
        return

    if not schedules:
        return

    logger.info("Workflow scheduler tick: %d due schedule(s)", len(schedules))

    for schedule in schedules:
        firm_id = schedule["firm_id"]
        schedule_id = schedule["id"]
        cron_expr = schedule.get("cron_expression", "0 9 * * *")
        tz_str = schedule.get("timezone", "Asia/Kolkata")

        try:
            engine.fire_trigger(
                firm_id=firm_id,
                trigger_type="scheduled",
                trigger_data={
                    "schedule_id": schedule_id,
                    "schedule_name": schedule.get("name"),
                    "fired_at": now_iso,
                },
                client_id=None,
            )
            run_status = "success"
            logger.info("Workflow schedule %s fired for firm %s", schedule_id, firm_id)
        except Exception as e:
            run_status = "failed"
            logger.error("Workflow schedule %s failed for firm %s: %s", schedule_id, firm_id, e)

        next_run = _compute_next_run(cron_expr, tz_str)
        try:
            repo.update_schedule_run(schedule_id, run_status, next_run)
        except Exception as e:
            logger.error("Failed to update schedule metadata for %s: %s", schedule_id, e)

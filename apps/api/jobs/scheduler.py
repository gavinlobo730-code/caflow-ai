"""
In-process daily scheduler for Phase 1.2 automation.

Runs (per firm, once per day):
  1. Recurring task generation (assignment rules applied inside the service)
  2. Escalation rules (due-soon + overdue)
  3. Invoice overdue transitions (Issued -> Overdue)
  4. Collections — AR overdue sweep + reminders
  5. Customer payment reminders
  6. Recurring invoices (DRAFT generation)
  7. Compliance obligation generation (idempotent; rolls forward near FY end)
  8. Compliance escalations (internal due-soon/overdue notifications)

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

# All per-firm job names recorded in scheduler_runs, in run order. Kept in sync
# with run_daily_jobs() so health reporting can surface every job's last run.
KNOWN_JOBS = [
    "recurring_generation",
    "escalations",
    "invoice_overdue",
    "collections",
    "customer_reminders",
    "recurring_invoices",
    "compliance_generation",
    "compliance_escalations",
]


def _scheduler_enabled() -> bool:
    """Whether the in-process scheduler is enabled via ENABLE_SCHEDULER env
    (same check used by start_scheduler)."""
    return os.environ.get("ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes")


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

        # 6. Recurring invoices (Phase 4.3) — generate DRAFT invoices for due
        #    templates via the existing invoice engine. Drafts only: never
        #    auto-issue, auto-post a journal, or auto-email (locked decisions).
        #    Idempotent (one invoice per template/occurrence); also runnable
        #    manually so it works whether or not the scheduler is enabled.
        if force or not _already_ran_today("recurring_invoices", fid):
            try:
                from services.recurring_invoice_service import generate_due_recurring_invoices
                outcome = generate_due_recurring_invoices(fid)
                firm_result["recurring_invoices"] = outcome
                _log_run("recurring_invoices", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Recurring invoices job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring_invoices"] = {"error": str(e)}
                _log_run("recurring_invoices", fid, "failed", {"error": str(e)})
        else:
            firm_result["recurring_invoices"] = {"skipped": "already ran today"}

        # 7. Compliance obligation generation (H7) — idempotently materialise the
        #    statutory obligations (GST/TDS/ITR/ROC) for every active engagement so
        #    there is always something to escalate. Backed by the engine's unique
        #    index (firm_id, client_id, obligation_type, period_start), so repeated
        #    runs only fill gaps; the _already_ran_today gate prevents same-day
        #    re-runs. Placed BEFORE escalations so freshly-generated obligations can
        #    be escalated in the same run. Near FY end (Jan/Feb/Mar) we also roll
        #    forward into the NEXT FY so April-onward periods exist before the year
        #    turns. Generation only — never files or emails anything.
        if force or not _already_ran_today("compliance_generation", fid):
            try:
                from services.compliance_obligation_service import generate_due, _current_fy
                current_fy = _current_fy()
                gen_detail: dict = {}
                outcome = generate_due(fid, financial_year=current_fy)
                gen_detail["current_fy"] = outcome
                # Roll forward near FY end (31 Mar) so next-FY periods pre-exist.
                if date.today().month in (1, 2, 3):
                    # Match _current_fy()'s format, e.g. "2026-27".
                    start = int(current_fy[:4]) + 1
                    next_fy = f"{start}-{str(start + 1)[2:]}"
                    next_outcome = generate_due(fid, financial_year=next_fy)
                    gen_detail["next_fy"] = next_outcome
                firm_result["compliance_generation"] = gen_detail
                _log_run("compliance_generation", fid, "success", gen_detail)
            except Exception as e:
                logger.error(f"Compliance generation job failed for firm {fid}: {e}", exc_info=True)
                firm_result["compliance_generation"] = {"error": str(e)}
                _log_run("compliance_generation", fid, "failed", {"error": str(e)})
        else:
            firm_result["compliance_generation"] = {"skipped": "already ran today"}

        # 8. Compliance escalations (Phase 4.4) — notify the internal team about
        #    obligations due in 7/3/1 days or overdue. Internal only (never emails
        #    clients); idempotent per (obligation, tier, day). No filing.
        if force or not _already_ran_today("compliance_escalations", fid):
            try:
                from services.compliance_obligation_service import escalate
                outcome = escalate(fid)
                firm_result["compliance_escalations"] = outcome
                _log_run("compliance_escalations", fid, "success", outcome)
            except Exception as e:
                logger.error(f"Compliance escalations job failed for firm {fid}: {e}", exc_info=True)
                firm_result["compliance_escalations"] = {"error": str(e)}
                _log_run("compliance_escalations", fid, "failed", {"error": str(e)})
        else:
            firm_result["compliance_escalations"] = {"skipped": "already ran today"}

        results["firms"][fid] = firm_result

    logger.info(f"Daily scheduler run completed for {len(firm_ids)} firm(s)")
    return results


def start_scheduler() -> None:
    """Start the APScheduler background scheduler (called from app startup)."""
    global _scheduler
    if not _scheduler_enabled():
        logger.info("Scheduler disabled (set ENABLE_SCHEDULER=true to enable)")
        return
    if _scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    # 06:00 IST daily — before the Indian working day starts
    _scheduler.add_job(run_daily_jobs, CronTrigger(hour=6, minute=0), id="daily_automation")
    # Workflow schedule tick (R2.7/F12): run_due_schedules existed but was
    # never registered, so cron workflow schedules silently never fired.
    # Every minute; a fast no-op when nothing is due.
    _scheduler.add_job(run_due_schedules, CronTrigger(minute="*"), id="workflow_schedules")
    _scheduler.start()
    logger.info("Background scheduler started (daily automation at 06:00 IST; "
                "workflow schedule tick every minute)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ── H11 — Scheduler reliability + health visibility ───────────────────────────

# Scheduled trigger hour (IST) — see start_scheduler's CronTrigger(hour=6).
_SCHEDULED_HOUR_IST = 6

_DISABLED_WARNING = (
    "Scheduler is DISABLED (ENABLE_SCHEDULER not set) — compliance reminders and "
    "recurring jobs will not run automatically. Configure an external cron to POST "
    "/api/scheduler/run, or set ENABLE_SCHEDULER=true."
)


def _all_runs_today() -> list[dict]:
    """Every scheduler_runs row for today (mock or DB). Defensive: [] on error."""
    today = date.today().isoformat()
    if _USE_MOCK:
        return [r for r in _MOCK_RUNS if r.get("run_date") == today]
    try:
        result = (
            _get_db().table("scheduler_runs").select("job_name,status,run_date")
            .eq("run_date", today).execute()
        )
        return result.data or []
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"scheduler_runs today lookup failed: {e}")
        return []


def _last_run_for_job(job_name: str) -> Optional[dict]:
    """Most recent run (date + status) for a job, or None. Defensive."""
    if _USE_MOCK:
        rows = [r for r in _MOCK_RUNS if r.get("job_name") == job_name]
        if not rows:
            return None
        latest = rows[-1]
        return {"run_date": latest.get("run_date"), "status": latest.get("status")}
    try:
        result = (
            _get_db().table("scheduler_runs").select("run_date,status")
            .eq("job_name", job_name)
            .order("started_at", desc=True).limit(1).execute()
        )
        if result.data:
            row = result.data[0]
            return {"run_date": row.get("run_date"), "status": row.get("status")}
        return None
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"last-run lookup failed ({job_name}): {e}")
        return None


def _past_scheduled_hour() -> bool:
    """True if the current IST time is at/after the scheduled run hour (06:00 IST).
    Falls back to True (so staleness can still be flagged) if tz lookup fails.

    Delegates to ist_now() (core/ist_clock.py) instead of re-resolving
    ZoneInfo("Asia/Kolkata") locally — identical computation (ist_now() is
    datetime.now(ZoneInfo("Asia/Kolkata"))), single source of truth (Phase 3
    consolidation). Previously used stdlib zoneinfo directly, not pytz — pytz
    was never in requirements.txt (same class of bug as _compute_next_run's
    missing croniter/pytz, R2.7 adversarial-review finding), so this always
    hit the except branch."""
    try:
        from core.ist_clock import ist_now
        return ist_now().hour >= _SCHEDULED_HOUR_IST
    except Exception:  # pragma: no cover - defensive
        return True


def scheduler_health() -> dict:
    """
    Deployment-safe scheduler health snapshot. Does NOT require the in-process
    APScheduler to be running (works behind an external cron too). Fully
    defensive — always returns a dict, never raises.

    Returns: {enabled, running, last_runs, stale, warnings}
    """
    enabled = False
    running = False
    last_runs: dict = {}
    stale = False
    warnings: list[str] = []

    try:
        enabled = _scheduler_enabled()
    except Exception:  # pragma: no cover - defensive
        enabled = False

    try:
        running = bool(_scheduler is not None and getattr(_scheduler, "running", False))
    except Exception:  # pragma: no cover - defensive
        running = False

    try:
        for job_name in KNOWN_JOBS:
            last_runs[job_name] = _last_run_for_job(job_name)
    except Exception:  # pragma: no cover - defensive
        last_runs = {}

    # Staleness: configured but not producing runs today after the scheduled hour.
    try:
        if enabled and _past_scheduled_hour():
            today_runs = _all_runs_today()
            had_run_today = any(r.get("status") == "success" for r in today_runs)
            stale = not had_run_today
    except Exception:  # pragma: no cover - defensive
        stale = False

    if not enabled:
        warnings.append(_DISABLED_WARNING)
    if stale:
        warnings.append(
            "Scheduler appears configured (ENABLE_SCHEDULER=true) but no successful "
            "job run was recorded today after the scheduled hour (06:00 IST). The "
            "scheduler may not be running — check the worker process or trigger "
            "POST /api/scheduler/run."
        )

    return {
        "enabled": enabled,
        "running": running,
        "last_runs": last_runs,
        "stale": stale,
        "warnings": warnings,
    }


def log_scheduler_startup_health() -> dict:
    """
    Startup health hook (wired into app startup by main.py — NOT called at import
    time). Logs a WARNING line per health warning so operators see scheduler
    misconfiguration at boot. Returns the health dict for convenience.
    """
    try:
        health = scheduler_health()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Scheduler health check failed at startup: {e}")
        return {"enabled": False, "running": False, "last_runs": {},
                "stale": False, "warnings": []}
    for warning in health.get("warnings", []):
        logger.warning(warning)
    if not health.get("warnings"):
        logger.info("Scheduler health OK at startup (enabled=%s, running=%s)",
                    health.get("enabled"), health.get("running"))
    return health


# ── Phase 10B — Workflow Schedule Runner ──────────────────────────────────────

def _compute_next_run(cron_expression: str, timezone_str: str = "Asia/Kolkata") -> str:
    """Compute the next run time from a standard 5-field cron expression.

    Uses APScheduler's own CronTrigger.from_crontab (already a hard
    dependency) plus the stdlib zoneinfo — NOT croniter/pytz, which were
    never added to requirements.txt: every call silently hit the except
    branch and fell back to "now + 1 day", so no workflow schedule's cron
    expression was ever actually honored (R2.7 adversarial-review finding).
    """
    try:
        from zoneinfo import ZoneInfo
        from apscheduler.triggers.cron import CronTrigger
        tz = ZoneInfo(timezone_str)
        trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
        now = datetime.now(tz)
        next_dt = trigger.get_next_fire_time(None, now)
        if next_dt is None:
            raise ValueError(f"cron expression '{cron_expression}' has no future fire time")
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
            # Fire the SPECIFIC template this schedule targets
            # (workflow_schedules.template_id), not every active template in
            # the firm whose trigger_type happens to be 'scheduled' — a
            # schedule is "run this exact workflow on this cron", not a
            # firm-wide broadcast (R2.7 adversarial-review finding: the old
            # code fired every 'scheduled'-type template regardless of which
            # schedule was due, and fired ZERO instances for a schedule
            # pointing at a template with any other trigger_type, while
            # still recording that run as a success).
            engine.fire_trigger(
                firm_id=firm_id,
                trigger_type="scheduled",
                trigger_data={
                    "schedule_id": schedule_id,
                    "schedule_name": schedule.get("name"),
                    "fired_at": now_iso,
                },
                client_id=None,
                template_id=schedule.get("template_id"),
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

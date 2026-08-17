"""
Phase 13 — Memory pipeline, run as job #11 of the daily scheduler sweep.

WHY THIS IS NO LONGER ITS OWN THREAD (task #158)
    This module used to start a thread that ran the pipeline immediately and
    then slept 86400 seconds, forever. On a process that lives for weeks, that
    is a nightly job. On Render's free tier it was neither nightly nor cheap:
    the instance spins down about fifteen minutes after the last request and
    cold starts on the next visitor, so the pipeline ran a full firm-wide
    profile recompute on EVERY cold start — while the 24-hour arm never came
    round at all, because no process ever lived that long. A job described as
    nightly was in practice running several times a day and never once on the
    schedule it claimed.

    Nothing could notice, either. Unlike the ten jobs in run_daily_jobs it wrote
    no scheduler_runs row, had no already-ran-today gate, and never appeared in
    scheduler_health() — so "did the memory pipeline run today" had no answer.

    It is now job #11 of run_daily_jobs, which supplies all three: the
    already-ran-today gate, the run log, and the startup catch-up that covers a
    missed 06:00 IST trigger (task #155).
"""
import logging
import os

logger = logging.getLogger("caflow.memory_job")

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _get_pipeline():
    from domain.memory_pipeline import memory_pipeline
    return memory_pipeline


def is_firm_active(firm_id: str) -> bool:
    """Whether the firm is active.

    run_daily_jobs iterates EVERY firm, but the nightly loop this job replaced
    selected firms with is_active = true. The check lives here so folding the
    job into the sweep preserves that scoping instead of silently widening the
    pipeline to deactivated firms — it writes profiles and raises triggers, and
    a firm someone deactivated should not be accumulating either.
    """
    if _USE_MOCK:
        return True
    try:
        result = (
            _get_db().table("firms").select("is_active")
            .eq("id", firm_id).limit(1).execute()
        )
        rows = result.data or []
        return bool(rows) and bool(rows[0].get("is_active"))
    except Exception as e:
        # Fail OPEN. Skipping an active firm's pipeline because one read failed
        # is worse than running one for a firm that turns out to be inactive,
        # and run_daily_jobs records the outcome either way.
        logger.warning("Could not read is_active for firm %s: %s", firm_id, e)
        return True


def run_memory_pipeline_for_firm(firm_id: str) -> dict:
    """Run the full memory pipeline for one firm and summarise the outcome.

    Deliberately does not catch pipeline exceptions: run_daily_jobs wraps the
    call and records a failed run row, exactly as it does for the other ten
    jobs. Per-client errors that run_full_pipeline collects rather than raises
    ride along in "errors", so they land in the scheduler_runs detail and are
    visible from /api/scheduler/status.
    """
    if not is_firm_active(firm_id):
        return {"skipped": "firm inactive"}

    result = _get_pipeline().run_full_pipeline(firm_id)
    summary = {
        "profiles_updated": result.get("profiles_updated", 0),
        "triggers_created": result.get("triggers_created", 0),
        "anomalies_detected": result.get("anomalies_detected", 0),
        "year_end_reports": result.get("year_end_reports", 0),
        "errors": result.get("errors", []),
    }
    logger.info(
        "Memory pipeline for firm %s: %d profiles, %d triggers, %d anomalies",
        firm_id, summary["profiles_updated"], summary["triggers_created"],
        summary["anomalies_detected"],
    )
    return summary

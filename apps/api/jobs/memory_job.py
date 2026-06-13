"""
Phase 13 — Nightly Memory Pipeline Job
Runs every night to refresh all client profiles and detect triggers.
Activated by ENABLE_SCHEDULER=true (runs alongside workflow scheduler).
"""
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger("caflow.memory_job")

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _get_pipeline():
    from domain.memory_pipeline import memory_pipeline
    return memory_pipeline


def get_all_firm_ids() -> list[str]:
    """Fetch all active firm IDs to run pipeline for."""
    if _USE_MOCK:
        return ["firm-001"]  # dev fallback
    try:
        db = _get_db()
        result = db.table("firms").select("id").eq("is_active", True).execute()
        return [row["id"] for row in (result.data or [])]
    except Exception as e:
        logger.error("Failed to fetch firm IDs: %s", e)
        return []


def run_memory_pipeline_for_all_firms():
    """Run the full memory pipeline for every active firm."""
    firms = get_all_firm_ids()
    logger.info("Memory pipeline starting for %d firms", len(firms))

    total_results = {
        "firms_processed": 0,
        "profiles_updated": 0,
        "triggers_created": 0,
        "anomalies_detected": 0,
        "year_end_reports": 0,
        "errors": [],
    }

    pipeline = _get_pipeline()

    for firm_id in firms:
        try:
            result = pipeline.run_full_pipeline(firm_id)
            total_results["firms_processed"] += 1
            total_results["profiles_updated"] += result.get("profiles_updated", 0)
            total_results["triggers_created"] += result.get("triggers_created", 0)
            total_results["anomalies_detected"] += result.get("anomalies_detected", 0)
            total_results["year_end_reports"] += result.get("year_end_reports", 0)
            total_results["errors"].extend(result.get("errors", []))
            logger.info("Firm %s: %d profiles, %d triggers, %d anomalies",
                       firm_id,
                       result.get("profiles_updated", 0),
                       result.get("triggers_created", 0),
                       result.get("anomalies_detected", 0))
        except Exception as e:
            logger.error("Pipeline failed for firm %s: %s", firm_id, e)
            total_results["errors"].append(f"Firm {firm_id}: {e}")

    logger.info("Memory pipeline complete: %s", total_results)
    return total_results


def start_memory_scheduler(interval_seconds: int = 86400):
    """
    Start nightly memory pipeline thread.
    Default: runs every 24 hours.
    Only runs when ENABLE_SCHEDULER=true.
    """
    if not os.environ.get("ENABLE_SCHEDULER", "").lower() == "true":
        return

    import time

    def _loop():
        logger.info("Memory pipeline scheduler started — interval: %ds", interval_seconds)
        # Run immediately on startup then every interval
        while True:
            try:
                run_memory_pipeline_for_all_firms()
            except Exception as e:
                logger.error("Memory pipeline loop error: %s", e)
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True, name="memory-pipeline")
    thread.start()
    logger.info("Memory pipeline thread started")
    return thread

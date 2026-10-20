"""Client health scores, calculated every night for every firm (POST-A-282), as a job of the daily scheduler sweep.

WHY THIS EXISTS
    A client's health score is written only by the Health screen's Calculate and Recalculate buttons, and the executive dashboard, the
    assistant, the memory profile and the Health pages all read what was last stored. So a firm that never pressed the button saw "not
    yet scored" for every client (the honest answer once the roll-ups stopped reading a column that said 100), and one that pressed it
    last month saw last month's scores presented as today's. The scores come from the books, the returns and the obligations, which
    change every day, so they are recalculated every night, by the SAME function the button uses (`routers/health.recalculate_clients`),
    for the same population (`clients_to_score`: live, not archived, never the firm's own practice client).

WHAT IT DOES NOT DO
    * It does not run for a firm someone deactivated (the memory job's rule, and its fail-open read).
    * It does not raise for one client that would not score: that client is counted in `failed` and reported, and the others are
      scored. It raises only when it had clients and scored none, so the run row says `failed` and the sweep retakes the job.
    * It sends nothing to anyone and calls no model: a score is arithmetic on rows already held.
    * It writes the stored score, one `health_score_history` row per client per night and marks the cached dashboard and the clients'
      cached reports stale once, which is what the button does.
"""
import logging
import os

from core import db_provider

logger = logging.getLogger("caflow.health_scores_job")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

_get_db = db_provider.service_db


def run_health_scores_for_firm(firm_id: str) -> dict:
    """Calculate every client's health score for one firm and summarise the outcome."""
    from jobs.memory_job import is_firm_active
    if _USE_MOCK:
        return {"skipped": "no database"}
    if not is_firm_active(firm_id):
        return {"skipped": "firm inactive"}

    import routers.health as health
    db = _get_db()
    clients = health.clients_to_score(db, firm_id)
    outcome = health.recalculate_clients(db, firm_id, clients)
    summary = {"clients": len(clients), **outcome}
    logger.info("Health scores for firm %s: %d clients, %d scored, %d failed",
                firm_id, summary["clients"], summary["updated"], summary["failed"])
    if clients and not outcome["updated"]:
        raise RuntimeError(f"no client of firm {firm_id} could be scored ({outcome['failed']} failed)")
    return summary

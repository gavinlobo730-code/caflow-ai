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
      scored. It raises when most of the clients that could be judged failed, so the run row says `failed` and the sweep retakes the job.
    * It stores nothing for a client with nothing on record at all (POST-A-288): the engine would have called it near 100, so it
      stays "not yet scored", is counted in `unscored` and is not a failure.
    * It sends nothing to anyone and calls no model: a score is arithmetic on rows already held.
    * It writes the stored score, one `health_score_history` row per client per night and marks the cached dashboard and the clients'
      cached reports stale once, which is what the button does.
    * It stops STARTING clients after `SWEEP_BUDGET_SECONDS` and says how many it did not reach (`not_reached`, in the summary and the
      log). The clients are taken the oldest stored score first, never-scored ones before any, so what a night does not reach is exactly
      what the next night begins with and no client waits for ever behind the same thousand (POST-A-289).
    * It removes the stored score of a client that is no longer in the population (archived, deleted, the firm's own practice client), so
      the Health lists and roll-ups, which read the table without asking the client's status, stop showing a frozen figure for it
      (`forgotten` in the summary). Its history rows stay: they are the record of what was shown. A client restored from the archive
      reads "not yet scored" until the next run.
"""
import logging
import os
from time import monotonic

from core import db_provider

logger = logging.getLogger("caflow.health_scores_job")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

_get_db = db_provider.service_db

#: How long one firm's run keeps starting clients. About twenty-five reads per client, one after another across regions, is a few
#: seconds a client, so twenty minutes is several hundred clients a night; a firm larger than that is scored over more than one night,
#: oldest first, and the summary says so. An operating limit and not a statutory figure: nothing depends on its value but how long a
#: night's run may take.
SWEEP_BUDGET_SECONDS = 20 * 60


def run_health_scores_for_firm(firm_id: str) -> dict:
    """Calculate every client's health score for one firm and summarise the outcome."""
    from jobs.memory_job import is_firm_active
    if _USE_MOCK:
        return {"skipped": "no database"}
    if not is_firm_active(firm_id):
        return {"skipped": "firm inactive"}

    import routers.health as health
    from core.db_paging import fetch_all
    db = _get_db()
    clients = health.clients_to_score(db, firm_id)
    stored = fetch_all(
        lambda: db.table("health_scores").select("id, client_id, last_calculated_at").eq("firm_id", firm_id),
        key="id", label="health.sweep_stored_scores")
    clients = oldest_score_first(clients, stored)
    outcome = health.recalculate_clients(db, firm_id, clients, deadline=monotonic() + SWEEP_BUDGET_SECONDS)
    forgotten = forget_scores_of_clients_no_longer_scored(db, firm_id, {str(c["id"]) for c in clients}, stored)
    summary = {"clients": len(clients), **outcome}
    if forgotten:
        summary["forgotten"] = forgotten
    logger.info("Health scores for firm %s: %d clients, %d scored, %d failed, %d with nothing on record",
                firm_id, summary["clients"], summary["updated"], summary["failed"], summary["unscored"])
    if summary.get("not_reached"):
        logger.warning("Health scores for firm %s: the %d-second budget ran out with %d client(s) not reached; the next run starts with them",
                       firm_id, SWEEP_BUDGET_SECONDS, summary["not_reached"])
    # A run in which most of the clients that could be judged failed raises, so the run row says `failed` and the sweep retakes the job
    # (POST-A-289: a run in which almost every client failed used to record success and nothing retried until the next night). The
    # clients that did score stay scored. A firm whose clients have nothing on record yet (all of them `unscored`) is not a failed
    # run, it is a firm with nothing to score, and one client of many failing is reported and counted without failing the run.
    judged = outcome["updated"] + outcome["failed"]
    if outcome["failed"] and outcome["failed"] * 2 > judged:
        raise RuntimeError(
            f"most clients of firm {firm_id} could not be scored ({outcome['failed']} failed of {judged} that could be judged)")
    return summary


def oldest_score_first(clients: list[dict], stored: list[dict]) -> list[dict]:
    """The clients in the order a budgeted run should take them: never scored first, then the oldest stored score, ties by id so the
    order is the same on every run. A client the engine cannot score (nothing on record) has no stored score and so comes first every
    night, which costs one cheap pass and is why `unscored` is not a reason to skip it."""
    calculated = {str(r["client_id"]): str(r.get("last_calculated_at") or "") for r in stored}
    return sorted(clients, key=lambda c: (calculated.get(str(c["id"]), ""), str(c["id"])))


def forget_scores_of_clients_no_longer_scored(db, firm_id: str, scored_ids: set[str], stored: list[dict]) -> int:
    """Delete the stored score of every client the firm no longer scores; return how many. `scored_ids` is the population just read
    (`clients_to_score`), and a read that failed raised before this is reached, so an empty population here is a firm with no live
    client and not a read that found nothing. A delete that fails is reported and the rest are still tried."""
    from core.observability import capture_soft_failure
    forgotten = 0
    for row in stored:
        if str(row["client_id"]) in scored_ids:
            continue
        try:
            db.table("health_scores").delete().eq("firm_id", firm_id).eq("id", row["id"]).execute()
            forgotten += 1
        except Exception as exc:
            capture_soft_failure(exc, operation="health.forget_score_of_a_client_no_longer_scored", firm_id=firm_id, client_id=row.get("client_id"))
    return forgotten

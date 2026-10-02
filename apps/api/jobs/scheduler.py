"""
In-process daily scheduler for Phase 1.2 automation.

Runs (per firm, once per day):
  1. Recurring task generation (assignment rules applied inside the service)
  2. Escalation rules (due-soon + overdue), and the staff MAILS that go with them:
     one per manager for what escalated to them, one per assignee for their own
     overdue tasks (practice_management-03)
  3. Invoice overdue transitions (Issued -> Overdue)
  4. Collections — AR overdue sweep + internal reminder logging (no email)
  5. Recurring invoices (DRAFT generation)
  6. Compliance obligation generation (idempotent; rolls forward near FY end)
  7. Compliance escalations (internal due-soon/overdue notifications, and one
     mail per recipient for the sweep — to STAFF only, never to a client)

Idempotency:
  - recurring generation is idempotent per-day inside the service
    (last_generated_at check)
  - the scheduler additionally records each job run in scheduler_runs and
    skips jobs already completed successfully today, so a restart does not
    run a finished job again
  - and a job is CLAIMED before it runs (jobs/claims.py, migration 471), by one
    atomic statement with an expiring lease, so two instances at once - a rolling
    deploy, a standby - cannot both run it. The select above is only the cheap
    first look; the claim is what refuses the second runner. The per-minute
    workflow tick is claimed per occurrence the same way (ops-14).

Enable with ENABLE_SCHEDULER=true (off by default so a deployment can leave the
daily run to something else: a dedicated process, or an external cron calling
POST /api/internal/scheduler/run-pending with SCHEDULER_TRIGGER_TOKEN, which runs
whatever is pending through the same claims - ops-15).
"""
import logging
import os
import threading
from core.db_paging import fetch_all
from datetime import date, datetime, timezone
from typing import Optional
from core.ist_clock import ist_today
from core import db_provider
from jobs import claims

logger = logging.getLogger("caflow.jobs")

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_RUNS: list[dict] = []

_scheduler = None

# All per-firm job names recorded in scheduler_runs, in run order. Kept in sync
# with run_daily_jobs() so health reporting can surface every job's last run.
#
# It is what catch-up, the external trigger (run_pending_now) and the health page
# all judge "what is still pending" by, so a job missing from it is a job whose
# failure reads as a complete day. `recurring_purchase_bills` and
# `client_period_metrics` ran in the sweep and were missing from it until ops-15;
# tests/test_a_scheduled_job_is_claimed_before_it_runs.py now asserts the list is
# exactly the jobs run_daily_jobs gates, so a job added to one cannot miss the other.
KNOWN_JOBS = [
    "recurring_generation",
    "escalations",
    "invoice_overdue",
    "collections",
    "recurring_invoices",
    "recurring_journals",
    "recurring_purchase_bills",
    "compliance_generation",
    "compliance_escalations",
    "balance_cache_audit",
    "reconciliation_audit",
    "client_period_metrics",
    "bank_trusted_rules",
    "memory_pipeline",
]


def _scheduler_enabled() -> bool:
    """Whether the in-process scheduler is enabled via ENABLE_SCHEDULER env
    (same check used by start_scheduler)."""
    return os.environ.get("ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes")


_get_db = db_provider.service_db


def _already_ran_today(job_name: str, firm_id: Optional[str]) -> bool:
    today = ist_today().isoformat()
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


# ── Claiming a job before it runs (ops-14) ─────────────────────────────────────
#
# `_already_ran_today` above is a SELECT and answers "did a run finish?"; it
# cannot answer "is one running right now?", which is the question a second
# instance asks. `_begin` asks both: the cheap read first (so a day's success
# written before the claim table existed still counts, and a finished job costs
# one read and no claim), then the claim, which is the part that is atomic.
#
# The claim a job holds is kept per THREAD, keyed (job, firm), and ended by
# `_log_run`: every job block already ends by calling it, success or failure,
# so the lock is released in the one place that already knows the outcome, and
# AFTER the run row is written - a process that dies between the two leaves a
# run row (which `_begin` honours) rather than a finished claim with no record.
_held = threading.local()


def _claim_store():
    return claims.store_for(mock=_USE_MOCK, db=lambda: _get_db())


def _state() -> tuple[dict, dict]:
    if not hasattr(_held, "claims"):
        _held.claims, _held.refusals = {}, {}
    return _held.claims, _held.refusals


def _begin(job_name: str, firm_id: Optional[str], force: bool) -> bool:
    """May this process run `job_name` for `firm_id` now? True means it holds the
    claim and MUST end it through `_log_run`; False says why in `_skip_reason`."""
    held, refusals = _state()
    key = (job_name, firm_id)
    refusals.pop(key, None)
    if not force and _already_ran_today(job_name, firm_id):
        refusals[key] = claims.SKIP_TEXT[claims.ALREADY_SUCCEEDED]
        return False
    if firm_id is None:
        # Every job is per firm (run_daily_jobs loops over firms), so a missing
        # one is a caller bug. Claims are keyed on the firm; running unclaimed is
        # what the code did before, and refusing would stop a sweep over a typo.
        return True
    decision = claims.claim(job_name, firm_id, run_date=ist_today(), force=force,
                            heartbeat=True, store=_claim_store())
    if not decision.claimed:
        refusals[key] = decision.skip_text
        return False
    if decision.claim is not None:
        held[key] = decision.claim
    return True


def _skip_reason(job_name: str, firm_id: Optional[str]) -> str:
    _, refusals = _state()
    return refusals.pop((job_name, firm_id), claims.SKIP_TEXT[claims.ALREADY_SUCCEEDED])


def _end_claim(job_name: str, firm_id: Optional[str], status: str) -> None:
    held, _ = _state()
    claim = held.pop((job_name, firm_id), None)
    if claim is not None:
        claim.finish(status == "success")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_run(job_name: str, firm_id: Optional[str], status: str, detail: dict,
             started_at: Optional[str] = None) -> None:
    """Record one job/firm outcome.

    started_at is passed in by the caller, captured BEFORE the job ran (task
    #161). It used to be omitted entirely, which left scheduler_runs.started_at
    to its `NOT NULL DEFAULT now()` — evaluated at INSERT, i.e. after the job
    had already finished. Every row therefore claimed to have started a few
    milliseconds AFTER it finished.

    That was not only cosmetic: routers/scheduler_status.py orders the status
    view by started_at, so it was really ordering by insert time, and the
    duration of a job was unrecoverable from the row.

    Left None it still falls back to the column default rather than failing,
    because losing the whole run record would be a worse outcome than an
    imprecise timestamp on it.
    """
    record = {
        "job_name": job_name,
        "run_date": ist_today().isoformat(),
        "firm_id": firm_id,
        "status": status,
        "detail": detail,
        "finished_at": _now_iso(),
    }
    if started_at:
        record["started_at"] = started_at
    try:
        if _USE_MOCK:
            _MOCK_RUNS.append(record)
            return
        try:
            _get_db().table("scheduler_runs").insert(record).execute()
        except Exception as e:
            logger.warning(f"Failed to log scheduler run ({job_name}): {e}")
    finally:
        # The claim ends AFTER the record is written (see the note above _begin),
        # and in a `finally` so a failing insert cannot leave it held.
        _end_claim(job_name, firm_id, status)


def _list_firm_ids() -> list[str]:
    if _USE_MOCK:
        from repositories.user_repository import user_repo
        try:
            users = user_repo.find_all()
            return sorted({u["firm_id"] for u in users if u.get("firm_id")})
        except Exception:
            return []
    # PAGED, AND THIS IS THE READ THE WHOLE SWEEP ITERATES OVER. PostgREST caps
    # a response at ~1000 rows and says nothing when it does, so the 1001st
    # firm's every daily job — the compliance calendar, recurring tasks,
    # recurring invoices and bills, the trusted-rule sweep, the reminders —
    # simply never runs, with no error anywhere.
    try:
        rows = fetch_all(lambda: _get_db().table("firms").select("id"),
                         label="scheduler.firms")
        return [f["id"] for f in rows]
    except Exception as e:
        logger.warning(f"Could not list firms, falling back to distinct task firm_ids: {e}")
        try:
            # THE FALLBACK IS THE READ THAT WOULD HAVE TRUNCATED FIRST: a row
            # per TASK, not per firm, so a single busy practice fills the cap
            # and the firms whose tasks sort after it vanish from the sweep.
            # The projection carries `id` because that is the cursor — without
            # it the walk reads one page and cannot advance.
            rows = fetch_all(lambda: _get_db().table("tasks").select("id, firm_id"),
                             label="scheduler.tasks_fallback")
            return sorted({t["firm_id"] for t in rows if t.get("firm_id")})
        except Exception:
            return []


def _close_sweep(firm_ids: list) -> None:
    """The end of a sweep. A per-minute workflow schedule leaves a claim row per occurrence, so old days are
    forgotten here, once per run (best effort, and bounded by the store's own retention); then the sweep says
    it finished. Lifted out of `run_daily_jobs` because that function is under the lint ratchet's size cap and
    this is the one part of it that owes nothing to a job."""
    claims.prune(_claim_store())
    logger.info(f"Daily scheduler run completed for {len(firm_ids)} firm(s)")


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
        if _begin("recurring_generation", fid, force):
            t0 = _now_iso()
            try:
                from jobs.recurring_task_job import run_recurring_generation_job
                outcome = run_recurring_generation_job(firm_id=fid)
                firm_result["recurring"] = {"count": outcome.get("count", 0), "error": outcome.get("error")}
                _log_run("recurring_generation", fid,
                         "success" if outcome.get("success") else "failed",
                         {"count": outcome.get("count", 0), "error": outcome.get("error")}, started_at=t0)
            except Exception as e:
                logger.error(f"Recurring job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring"] = {"error": str(e)}
                _log_run("recurring_generation", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["recurring"] = {"skipped": _skip_reason("recurring_generation", fid)}

        # 2. Escalation rules
        if _begin("escalations", fid, force):
            t0 = _now_iso()
            try:
                from services.escalation_service import escalation_service
                outcome = escalation_service.run_all_escalations(fid)
                firm_result["escalations"] = outcome
                _log_run("escalations", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Escalation job failed for firm {fid}: {e}", exc_info=True)
                firm_result["escalations"] = {"error": str(e)}
                _log_run("escalations", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["escalations"] = {"skipped": _skip_reason("escalations", fid)}

        # 3. Invoice overdue transitions
        if _begin("invoice_overdue", fid, force):
            t0 = _now_iso()
            try:
                from services.invoice_lifecycle_service import run_overdue_check
                outcome = run_overdue_check(firm_id=fid)
                firm_result["invoice_overdue"] = outcome
                _log_run("invoice_overdue", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Invoice overdue job failed for firm {fid}: {e}", exc_info=True)
                firm_result["invoice_overdue"] = {"error": str(e)}
                _log_run("invoice_overdue", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["invoice_overdue"] = {"skipped": _skip_reason("invoice_overdue", fid)}

        # 4. Collections — AR overdue sweep + internal follow-up flags
        #    (Amendment v1.1 Batch 4). Operates on the firm's internal-client FEE
        #    invoices and NOTHING ELSE: `_open_invoices` answers [] for a firm
        #    whose `internal_client_id` is NULL rather than widening to every
        #    client, which is what it used to do. Sweep is idempotent; the flag
        #    is cadence-gated (anti-spam) on its own column.
        #
        #    NEITHER STEP EMAILS ANYBODY, which this header has always said and
        #    the code did not: the flag used to advance `reminder_count`, the
        #    column whose number decides whether a real reminder reads as
        #    friendly, second or FINAL. See migration 405.
        if _begin("collections", fid, force):
            t0 = _now_iso()
            try:
                from services.collections_service import (
                    sweep_overdue, flag_overdue_for_internal_followup)
                swept = sweep_overdue(fid)
                flagged = flag_overdue_for_internal_followup(fid)
                outcome = {**swept, **flagged}
                firm_result["collections"] = outcome
                _log_run("collections", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Collections job failed for firm {fid}: {e}", exc_info=True)
                firm_result["collections"] = {"error": str(e)}
                _log_run("collections", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["collections"] = {"skipped": _skip_reason("collections", fid)}

        # 5. Recurring invoices (Phase 4.3) — generate DRAFT invoices for due
        #    templates via the existing invoice engine. Drafts only: never
        #    auto-issue, auto-post a journal, or auto-email (locked decisions).
        #    Idempotent (one invoice per template/occurrence); also runnable
        #    manually so it works whether or not the scheduler is enabled.
        if _begin("recurring_invoices", fid, force):
            t0 = _now_iso()
            try:
                from services.recurring_invoice_service import generate_due_recurring_invoices
                outcome = generate_due_recurring_invoices(fid)
                firm_result["recurring_invoices"] = outcome
                _log_run("recurring_invoices", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Recurring invoices job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring_invoices"] = {"error": str(e)}
                _log_run("recurring_invoices", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["recurring_invoices"] = {"skipped": _skip_reason("recurring_invoices", fid)}

        # 5b. Recurring JOURNALS (ACC-06). Generates DRAFT manual journals for
        #     every due template and never posts one — this product acts
        #     unprompted only where a Manager marked a bank rule trusted. A
        #     template that fails is recorded and does NOT advance, so the
        #     occurrence stays owed rather than being skipped silently.
        if _begin("recurring_journals", fid, force):
            t0 = _now_iso()
            try:
                from services.recurring_journal_service import run_due as _run_journals
                outcome = _run_journals(fid)
                firm_result["recurring_journals"] = outcome
                _log_run("recurring_journals", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Recurring journals job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring_journals"] = {"error": str(e)}
                _log_run("recurring_journals", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["recurring_journals"] = {"skipped": _skip_reason("recurring_journals", fid)}

        # 5c. Recurring PURCHASE BILLS (PUR-26). Generates DRAFT supplier bills
        #     — rent, retainers, utilities — and never RECEIVES one: receiving
        #     is what posts the AP journal, withholds the TDS and claims the
        #     credit. Same catch-up and same non-advancing failure as 5 and 5b.
        #     It matters more than a convenience: most of the s.194 series
        #     charges on the YEAR'S aggregate, so a month nobody entered
        #     changes what the next bill should withhold.
        if _begin("recurring_purchase_bills", fid, force):
            t0 = _now_iso()
            try:
                from services.recurring_purchase_bill_service import generate_due_recurring_bills
                outcome = generate_due_recurring_bills(fid)
                firm_result["recurring_purchase_bills"] = outcome
                _log_run("recurring_purchase_bills", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Recurring purchase bills job failed for firm {fid}: {e}", exc_info=True)
                firm_result["recurring_purchase_bills"] = {"error": str(e)}
                _log_run("recurring_purchase_bills", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["recurring_purchase_bills"] = {"skipped": _skip_reason("recurring_purchase_bills", fid)}

        # 6. Compliance obligation generation (H7) — idempotently materialise the
        #    statutory obligations (GST/TDS/ITR/ROC) for every active engagement so
        #    there is always something to escalate. Backed by the engine's unique
        #    index (firm_id, client_id, obligation_type, period_start), so repeated
        #    runs only fill gaps; the _already_ran_today gate prevents same-day
        #    re-runs. Placed BEFORE escalations so freshly-generated obligations can
        #    be escalated in the same run. Near FY end (Jan/Feb/Mar) we also roll
        #    forward into the NEXT FY so April-onward periods exist before the year
        #    turns. Generation only — never files or emails anything.
        if _begin("compliance_generation", fid, force):
            t0 = _now_iso()
            try:
                from services.compliance_obligation_service import generate_due, _current_fy
                current_fy = _current_fy()
                gen_detail: dict = {}
                outcome = generate_due(fid, financial_year=current_fy)
                gen_detail["current_fy"] = outcome
                # Roll forward near FY end (31 Mar) so next-FY periods pre-exist.
                if ist_today().month in (1, 2, 3):
                    # Match _current_fy()'s format, e.g. "2026-27".
                    start = int(current_fy[:4]) + 1
                    next_fy = f"{start}-{str(start + 1)[2:]}"
                    next_outcome = generate_due(fid, financial_year=next_fy)
                    gen_detail["next_fy"] = next_outcome
                firm_result["compliance_generation"] = gen_detail
                _log_run("compliance_generation", fid, "success", gen_detail, started_at=t0)
            except Exception as e:
                logger.error(f"Compliance generation job failed for firm {fid}: {e}", exc_info=True)
                firm_result["compliance_generation"] = {"error": str(e)}
                _log_run("compliance_generation", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["compliance_generation"] = {"skipped": _skip_reason("compliance_generation", fid)}

        # 7. Compliance escalations (Phase 4.4) — notify the internal team about
        #    obligations due in 7/3/1 days or overdue. Internal only (the mail goes to
        #    the preparer/reviewer/approver and never to a client); idempotent per
        #    (obligation, tier, day) and again per sent mail. No filing.
        if _begin("compliance_escalations", fid, force):
            t0 = _now_iso()
            try:
                from services.compliance_obligation_service import escalate
                outcome = escalate(fid)
                firm_result["compliance_escalations"] = outcome
                _log_run("compliance_escalations", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Compliance escalations job failed for firm {fid}: {e}", exc_info=True)
                firm_result["compliance_escalations"] = {"error": str(e)}
                _log_run("compliance_escalations", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["compliance_escalations"] = {"skipped": _skip_reason("compliance_escalations", fid)}

        # 8. Balance-cache audit (reporting passbook) — re-derive every client's
        #    monthly buckets from scratch and self-heal any drift, so the
        #    incrementally-maintained passbook can never silently diverge from
        #    the ledger. Read-only for reports (it only touches the derived
        #    account_period_balances cache); safe to run whether or not reports
        #    are yet reading the passbook.
        if _begin("balance_cache_audit", fid, force):
            t0 = _now_iso()
            try:
                from services.balance_cache_service import audit_and_heal_firm
                outcome = audit_and_heal_firm(_get_db(), fid)
                firm_result["balance_cache_audit"] = outcome
                _log_run("balance_cache_audit", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Balance-cache audit job failed for firm {fid}: {e}", exc_info=True)
                firm_result["balance_cache_audit"] = {"error": str(e)}
                _log_run("balance_cache_audit", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["balance_cache_audit"] = {"skipped": _skip_reason("balance_cache_audit", fid)}

        # 9. Books-integrity reconciliation (task #244) — trial balance, missing
        #     COGS/inventory-receipt journals, inventory cache-vs-ledger drift,
        #     AR/AP sub-ledger vs GL, for every client. REPORT-ONLY — findings are
        #     persisted (reconciliation_runs/reconciliation_findings, migration
        #     244) for a Partner to review, never auto-corrected (unlike #9's pure
        #     cache heal). This is the standing version of the manual SQL audit
        #     that found the ₹38.14L inventory drift and the ₹15,036.14 missing-
        #     COGS gap on 2026-07-25 — it should never again take a human running
        #     ad hoc queries to notice a books-integrity break.
        if _begin("reconciliation_audit", fid, force):
            t0 = _now_iso()
            try:
                from services.reconciliation_service import run_reconciliation_for_firm
                outcome = run_reconciliation_for_firm(_get_db(), fid)
                firm_result["reconciliation_audit"] = outcome
                _log_run("reconciliation_audit", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Reconciliation audit job failed for firm {fid}: {e}", exc_info=True)
                firm_result["reconciliation_audit"] = {"error": str(e)}
                _log_run("reconciliation_audit", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["reconciliation_audit"] = {"skipped": _skip_reason("reconciliation_audit", fid)}

        # 9b. Per-client period metrics (migration 417, D30) — the aggregates a
        #     cross-client tax benchmark reads. It runs HERE, beside the two
        #     steps above, because those already pay the per-client read and
        #     this is what makes `GET /api/analytics/benchmark` a few dozen
        #     rows instead of every client's whole ledger. Re-DERIVES rather
        #     than accumulating, the same self-healing discipline as the
        #     balance-cache audit: a back-dated journal or a revised return
        #     moves a figure that was already written. Two financial years,
        #     bounded by `client_metrics_service.YEARS_SWEPT`. Writes nothing
        #     a CA sees directly and posts nothing.
        if _begin("client_period_metrics", fid, force):
            t0 = _now_iso()
            try:
                from services.client_metrics_service import refresh_firm
                outcome = refresh_firm(_get_db(), fid)
                firm_result["client_period_metrics"] = outcome
                _log_run("client_period_metrics", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Client period metrics failed for firm {fid}: {e}", exc_info=True)
                firm_result["client_period_metrics"] = {"error": str(e)}
                _log_run("client_period_metrics", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["client_period_metrics"] = {"skipped": _skip_reason("client_period_metrics", fid)}

        # 10b. Bank trusted-rule sweep (migration 322, 09-bank-entries.md) —
        #     pass every ready draft a TRUSTED rule wrote and nobody clicked
        #     for: a statement uploaded and the tab closed, a rule promoted
        #     after the import. Each line posts as the person who trusted the
        #     rule. Before the memory pipeline, so the profile sees the books
        #     as the rules have left them. Bounded per client; the run log
        #     records what was carried over.
        if _begin("bank_trusted_rules", fid, force):
            t0 = _now_iso()
            try:
                from jobs.bank_trusted_rules_job import run_trusted_rules_for_firm
                outcome = run_trusted_rules_for_firm(fid)
                firm_result["bank_trusted_rules"] = outcome
                _log_run("bank_trusted_rules", fid,
                         "success",
                         outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Bank trusted-rule sweep failed for firm {fid}: {e}", exc_info=True)
                firm_result["bank_trusted_rules"] = {"error": str(e)}
                _log_run("bank_trusted_rules", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["bank_trusted_rules"] = {"skipped": _skip_reason("bank_trusted_rules", fid)}

        # 10. Memory pipeline (Phase 13, task #158) — refresh every client's
        #     profile, detect pattern anomalies, raise memory triggers. This used
        #     to run from its own thread in jobs/memory_job.py: immediately on
        #     startup, then time.sleep(86400). On the free tier that is a full
        #     firm-wide recompute on every cold start and a 24-hour arm that never
        #     comes round, with no run log to show either had happened. Folded in
        #     here so it gets the same already-ran-today gate, run log, health
        #     visibility and catch-up as the rest of the sweep. Last in the order
        #     deliberately: it profiles the state the ten jobs above have settled.
        if _begin("memory_pipeline", fid, force):
            t0 = _now_iso()
            try:
                from jobs.memory_job import run_memory_pipeline_for_firm
                outcome = run_memory_pipeline_for_firm(fid)
                firm_result["memory_pipeline"] = outcome
                _log_run("memory_pipeline", fid, "success", outcome, started_at=t0)
            except Exception as e:
                logger.error(f"Memory pipeline job failed for firm {fid}: {e}", exc_info=True)
                firm_result["memory_pipeline"] = {"error": str(e)}
                _log_run("memory_pipeline", fid, "failed", {"error": str(e)}, started_at=t0)
        else:
            firm_result["memory_pipeline"] = {"skipped": _skip_reason("memory_pipeline", fid)}

        results["firms"][fid] = firm_result

    _close_sweep(firm_ids)
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
    # Deliver the practice's queued mail (ops-21). Every minute, one run at a time: a drain
    # takes at most ~45 seconds, and a run that is still going when the next is due is
    # skipped rather than stacked. It sends nothing the practice's mail switch is off for
    # and is safe beside a second instance (rows are claimed with SKIP LOCKED).
    _scheduler.add_job(drain_email_outbox, CronTrigger(minute="*"), id="email_outbox",
                       max_instances=1, coalesce=True)
    _scheduler.start()
    logger.info("Background scheduler started (daily automation at 06:00 IST; "
                "workflow schedule tick and mail outbox drain every minute)")


def drain_email_outbox() -> None:
    """The per-minute tick that delivers queued mail (ops-21). Never raises: a failing drain
    is logged and the next minute tries again."""
    try:
        from services import email_outbox_service
        email_outbox_service.drain()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Mail outbox drain failed: {e}", exc_info=True)


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
    """Every scheduler_runs row for today (mock or DB). Defensive: [] on error.

    firm_id is selected because _pending_jobs_today() needs to know WHICH firm a
    success belongs to, not merely that some firm succeeded — see its docstring.
    """
    today = ist_today().isoformat()
    if _USE_MOCK:
        return [r for r in _MOCK_RUNS if r.get("run_date") == today]
    try:
        # PAGED, AND THE IDEMPOTENCY OF THE WHOLE SWEEP RESTS ON IT. This feeds
        # _pending_jobs_today(), which decides what still needs running — so a
        # read truncated at PostgREST's ~1000 rows makes a job that already
        # SUCCEEDED read as pending, and it runs a second time: duplicate
        # recurring tasks, duplicate recurring invoices, duplicate reminders.
        # One row per (firm, job) per day, and thirteen jobs, so 77 firms is
        # enough. `id` is in the projection because it is fetch_all's cursor.
        return fetch_all(
            lambda: _get_db().table("scheduler_runs")
            .select("id,job_name,status,run_date,firm_id").eq("run_date", today),
            label="scheduler.runs_today")
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


# ── Task #155 — catch up a 06:00 IST run the process was asleep for ───────────
#
# WHY THIS EXISTS
#     run_daily_jobs fires from an in-process APScheduler timer (start_scheduler),
#     so it can only run if the process is ALIVE at 06:00 IST. On Render's free
#     tier it is asleep unless something wakes it, and the only thing that does is
#     a GitHub Actions cron — which GitHub documents as best-effort: it starts
#     late under load and drops runs entirely.
#
#     Miss that window and APScheduler does not catch up. It schedules tomorrow's
#     06:00 and today's compliance reminders, recurring invoices, overdue
#     transitions, collections, and reconciliation audit never run at all.
#
#     scheduler_health() already DETECTS this exact state (stale=True) and did
#     nothing with it but write a warning into logs nobody reads. This acts on it.
#
# WHY IT IS SAFE TO CHECK ON EVERY BOOT
#     Every job in run_daily_jobs is gated by _already_ran_today() and skipped if
#     it already succeeded — which is why that function documents itself as safe
#     to call repeatedly. Catch-up runs only what is actually still missing, so a
#     boot after a healthy 06:00 run does no work beyond two reads.
#
# WHY IT DOES NOT REPLACE THE WAKE WORKFLOW
#     Catch-up runs when the process next starts, which on a free-tier instance
#     is the day's first visitor — 06:00 for a CA who opens the app at 06:00,
#     11:00 for one who doesn't. .github/workflows/wake-before-scheduler.yml is
#     what keeps the ordinary case punctual; this is what stops a late or dropped
#     cron from costing a whole day.

_catchup_started = False


def _pending_jobs_today() -> list[tuple[Optional[str], str]]:
    """(firm_id, job_name) pairs with no SUCCESSFUL run recorded today.

    Per firm AND per job, rather than the cheaper "did anything succeed today":

      - A catch-up can be killed part-way. The free-tier instance spins down
        about fifteen minutes after the request that woke it, which can easily
        be before ten jobs across every firm have finished. Treating one success
        as proof the day is done would abandon the rest until tomorrow — exactly
        the failure this function exists to prevent.
      - A job that FAILED today has a row but no success, so it is retried on the
        next boot. Deliberate: a transient failure at 06:00 otherwise waits a
        full day. _catchup_started bounds the retries to one per process.
    """
    firm_ids = _list_firm_ids()
    if not firm_ids:
        return []
    succeeded = {
        (r.get("firm_id"), r.get("job_name"))
        for r in _all_runs_today()
        if r.get("status") == "success"
    }
    return [
        (firm_id, job_name)
        for firm_id in firm_ids
        for job_name in KNOWN_JOBS
        if (firm_id, job_name) not in succeeded
    ]


def _catchup_worker() -> None:
    """Thread body — run_daily_jobs already logs per-job failures, so this only
    has to make sure a raise cannot escape into a bare thread."""
    try:
        run_daily_jobs()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Scheduler catch-up run failed: {e}", exc_info=True)


def run_catchup_if_stale(*, background: bool = True) -> dict:
    """Run today's outstanding daily jobs if the 06:00 IST trigger was missed.

    Called from app startup (main.py). Returns {"ran", "reason", "pending"} and
    never raises — a catch-up that cannot decide must not stop the app booting.

    background=True runs the jobs on a daemon thread so startup is not blocked.
    The thread is a daemon deliberately: shutdown must not hang waiting on a
    full sweep, and losing one mid-flight is cheap because every job records its
    own scheduler_runs row as it completes — the next boot picks up where this
    one was cut off.
    """
    global _catchup_started

    if not _scheduler_enabled():
        # Not our job to run: ENABLE_SCHEDULER is off precisely when something
        # else (a dedicated worker, an external cron) owns the daily run, and on
        # a multi-worker deploy every worker would otherwise catch up at once.
        return {"ran": False, "reason": "scheduler disabled", "pending": 0}
    if not _past_scheduled_hour():
        return {"ran": False, "reason": "before the scheduled hour", "pending": 0}
    if _catchup_started:
        return {"ran": False, "reason": "already attempted in this process", "pending": 0}

    try:
        pending = _pending_jobs_today()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Scheduler catch-up check failed: {e}")
        return {"ran": False, "reason": f"check failed: {e}", "pending": 0}

    if not pending:
        return {"ran": False, "reason": "today's run is already complete", "pending": 0}

    _catchup_started = True
    logger.warning(
        "Scheduler catch-up: %d job/firm pair(s) have not succeeded today — the "
        "06:00 IST run was missed (instance asleep, or the wake cron ran late). "
        "Running them now.",
        len(pending),
    )

    if not background:
        _catchup_worker()
        return {"ran": True, "reason": "ran inline", "pending": len(pending)}

    threading.Thread(
        target=_catchup_worker, name="scheduler-catchup", daemon=True
    ).start()
    return {"ran": True, "reason": "started in background", "pending": len(pending)}


# ── ops-15 — an external trigger that does not depend on this host being awake ─
#
# WHAT IT IS
#     `run_pending_now` is what the token-protected POST
#     (routers/scheduler_trigger.py) calls: run whatever today's sweep still owes,
#     now, through exactly the claims `run_daily_jobs` takes. An external
#     scheduler (a Render cron job, pg_cron with pg_net, any HTTP caller) that
#     fires at 06:00 IST therefore starts the day's jobs at 06:00 IST whether or
#     not the in-process timer was alive to fire, and wakes a sleeping instance
#     by the act of calling it.
#
# HOW IT DIFFERS FROM `run_catchup_if_stale`
#     Catch-up runs ONCE per process, at boot, and only when ENABLE_SCHEDULER is
#     on. This runs when asked, as often as asked, and does NOT need
#     ENABLE_SCHEDULER: that flag is off precisely when something else owns the
#     daily run, and an external trigger is that something. Asking twice is safe
#     because every job is gated by `_begin`: a finished job is skipped, a job
#     another instance is running is skipped, and a failed one is retried.
#
# WHAT IT DOES NOT DO
#     It does not run before 06:00 IST. A trigger misconfigured to fire at
#     midnight would otherwise run the day's reminders at midnight, so it answers
#     "before the scheduled hour" and runs nothing — the safe direction for a
#     timezone mistake, and the answer says so rather than reporting success.
#     It schedules nothing itself.

_pending_run_lock = threading.Lock()


def _pending_worker() -> None:
    try:
        run_daily_jobs()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"External-trigger run failed: {e}", exc_info=True)
    finally:
        _pending_run_lock.release()


def run_pending_now(*, background: bool = True) -> dict:
    """Run today's still-pending daily jobs now. Never raises.

    Returns {"started": bool, "reason": str, "pending": int}. `background=True`
    runs them on a daemon thread and returns at once, which is what an HTTP
    trigger wants (the sweep can take minutes); a second call while one is still
    running in this process is told so. Across instances the claims decide.
    """
    if not _past_scheduled_hour():
        return {"started": False, "reason": "before the scheduled hour (06:00 IST)", "pending": 0}
    try:
        pending = _pending_jobs_today()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"External-trigger pending check failed: {e}")
        return {"started": False, "reason": f"check failed: {type(e).__name__}", "pending": 0}
    if not pending:
        return {"started": False, "reason": "today's run is already complete", "pending": 0}
    if not _pending_run_lock.acquire(blocking=False):
        return {"started": False, "reason": "a run is already in progress in this process",
                "pending": len(pending)}
    logger.warning("External trigger: %d job/firm pair(s) have not succeeded today; running them.",
                   len(pending))
    if not background:
        _pending_worker()
        return {"started": True, "reason": "ran inline", "pending": len(pending)}
    try:
        threading.Thread(target=_pending_worker,
                         name="scheduler-external-trigger", daemon=True).start()
    except Exception as e:  # pragma: no cover - defensive
        _pending_run_lock.release()
        logger.error(f"External-trigger thread could not start: {e}")
        return {"started": False, "reason": "could not start the run", "pending": len(pending)}
    return {"started": True, "reason": "started in background", "pending": len(pending)}


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

    SAFE FOR MORE THAN ONE INSTANCE (ops-14). This used to say "NOT safe for
    multi-worker deployments", and was not: every instance listed the same due
    schedules and fired each, and `next_run_at` only moved afterwards. Each
    OCCURRENCE (a schedule and the time it was due) is now claimed first, by the
    same atomic claim the daily jobs take (jobs/claims.py), so one instance fires
    it and the others skip it.

    The claim is ended BEFORE the schedule's own metadata is advanced, which is
    what makes a crash between the two harmless: the next tick finds this
    occurrence already `success` and only advances `next_run_at`, never firing it
    again. (A failed advance used to mean the schedule fired AGAIN on the next
    tick; it now cannot.) A holder that dies mid-fire loses its lease within ten
    minutes and the next tick takes the occurrence over, which is at-least-once:
    the narrow window is a death between the engine accepting the trigger and the
    claim being ended.
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

    store = _claim_store()
    for schedule in schedules:
        firm_id = schedule["firm_id"]
        schedule_id = schedule["id"]
        cron_expr = schedule.get("cron_expression", "0 9 * * *")
        tz_str = schedule.get("timezone", "Asia/Kolkata")

        # One claim per OCCURRENCE: the schedule and the time it was due. The key
        # is the due time, which only moves when the schedule is advanced, so a
        # tick that sees the same occurrence again finds the same claim.
        due_at = schedule.get("next_run_at")
        decision = claims.claim(
            "workflow_schedule", firm_id,
            run_date=claims.ist_date_of(due_at, ist_today()),
            claim_key=f"{schedule_id}@{due_at}", store=store)
        if not decision.claimed:
            if decision.reason == claims.ALREADY_SUCCEEDED:
                # A previous holder fired this occurrence and went away before it
                # advanced the schedule. Advance it; never fire it twice.
                logger.warning("Workflow schedule %s was already fired for %s; "
                               "advancing it without firing again", schedule_id, due_at)
                try:
                    repo.update_schedule_run(schedule_id, "success",
                                             _compute_next_run(cron_expr, tz_str))
                except Exception as e:
                    logger.error("Failed to advance schedule %s: %s", schedule_id, e)
            else:
                logger.info("Workflow schedule %s not fired here: %s",
                            schedule_id, decision.skip_text)
            continue

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

        # End the claim BEFORE advancing the schedule (see the docstring).
        if decision.claim is not None:
            decision.claim.finish(run_status == "success")

        next_run = _compute_next_run(cron_expr, tz_str)
        try:
            repo.update_schedule_run(schedule_id, run_status, next_run)
        except Exception as e:
            logger.error("Failed to update schedule metadata for %s: %s", schedule_id, e)

"""
Bank entries — the trusted-rule sweep, job #12 of the daily scheduler run.

WHAT IT DOES
    For every client of the firm that has at least one TRUSTED rule: propose
    for any line nobody has proposed for yet, then pass every ready line a
    trusted rule drafted — each on the authority of the person who trusted the
    rule (journal created_by = rule.trusted_by), stamped posted_by_rule_id.

WHY IT EXISTS WHEN THE SCREEN ALREADY DOES THIS
    The screen passes trusted drafts with a progress bar right after an
    import. But a statement uploaded and the tab closed, or a rule promoted to
    trusted AFTER the import, leaves ready drafts that nobody is looking at.
    "Trusted" means they post without a click; this is what makes that true
    when no one is clicking anything.

WHAT IT NEVER DOES
    Pass a line a trusted rule did not draft. Pass a PROPOSED draft. Retry a
    line whose last pass failed (the refusal is on the row; a human or a
    redraft clears it). Post through anything but bank_posting_service.post.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this posts JOURNALS, which are
    reversible; it files nothing.

BOUNDED
    Chunked like the screen, with a cap per client per run so one client's
    backlog cannot hold the rest of the sweep — and the run log records
    what was left, which the next run picks up.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("caflow.bank_trusted_rules")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Per client per run. At ~5 round trips a post from Singapore to Mumbai this is
# a few minutes at most; a backlog beyond it is carried to the next run.
MAX_PASSES_PER_CLIENT = 500
MAX_REDRAFTS_PER_CLIENT = 2000


def _get_db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _clients_with_trusted_rules(db, firm_id: str) -> list[str]:
    rows = (db.table("bank_matching_rules").select("client_id")
            .eq("firm_id", firm_id).eq("is_active", True).eq("is_trusted", True)
            .execute().data or [])
    return sorted({r["client_id"] for r in rows if r.get("client_id")})


def run_trusted_rules_for_firm(firm_id: str, db=None) -> dict:
    """Returns a per-client summary the scheduler stores in scheduler_runs."""
    if _USE_MOCK and db is None:
        return {"clients": {}, "passed": 0, "failed": 0, "skipped_mock": True}
    from services.bank_entry_service import bank_entry_service, REDRAFT_CHUNK, PASS_CHUNK
    db = db or _get_db()
    out: dict = {"clients": {}, "passed": 0, "failed": 0}
    for client_id in _clients_with_trusted_rules(db, firm_id):
        summary = {"redrafted": 0, "passed": 0, "failed": 0, "remaining": 0}
        # 1. Propose for what nobody has proposed for. Only never-drafted lines:
        #    a forced refresh is the screen's to ask for.
        drafted = 0
        while drafted < MAX_REDRAFTS_PER_CLIENT:
            r = bank_entry_service.redraft(db, firm_id, client_id, limit=REDRAFT_CHUNK)
            drafted += r["drafted"]
            if r["drafted"] == 0 or r["remaining"] == 0:
                break
        summary["redrafted"] = drafted
        # 2. Pass what the trusted rules drafted.
        passed = 0
        while passed < MAX_PASSES_PER_CLIENT:
            r = bank_entry_service.pass_ready(db, firm_id, client_id, limit=PASS_CHUNK,
                                              only_trusted=True)
            passed += r["passed"] + r["failed"] + r["skipped"]
            summary["passed"] += r["passed"]
            summary["failed"] += r["failed"]
            summary["remaining"] = r["remaining"]
            if r["remaining"] == 0 or (r["passed"] + r["failed"] + r["skipped"]) == 0:
                break
        out["clients"][client_id] = summary
        out["passed"] += summary["passed"]
        out["failed"] += summary["failed"]
        if summary["failed"]:
            logger.warning("trusted-rule sweep: %d line(s) refused for client %s — on the rows",
                           summary["failed"], client_id)
    return out

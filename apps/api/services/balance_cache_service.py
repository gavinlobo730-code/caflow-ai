"""
Balance-cache backfill & auditor — the reporting "passbook" (Phase 1).

`recompute_client`  (re)builds a client's monthly buckets from the raw posted
                    ledger and stores them. Idempotent — the stored result is
                    always a pure function of the ledger, so it is safe to run
                    any number of times (the initial backfill, or a repair).

`audit_client`      re-derives the buckets from the raw ledger and compares them
                    to what is stored, returning every paise-level discrepancy.
                    This is the safety net: it guarantees a maintenance bug can
                    never silently corrupt a balance, because a from-scratch
                    recompute is the arbiter. A later phase runs it on a nightly
                    schedule and alerts on any drift.

PHASE 1: nothing in the live report path calls these — reports still use the
existing engine. This module only lets us populate and continuously verify the
store, so the read switch-over (a later phase) can run in shadow mode against a
store already proven correct. Integer paise throughout; never float.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from domain.reporting.balance_cache import Buckets, build_buckets
from domain.reporting.sources import SupabaseLedgerSource

_logger = logging.getLogger("caflow.balance_cache")

_INSERT_CHUNK = 500


def _compute(db, firm_id: str, client_id: str) -> Buckets:
    """The single source of truth for a client's buckets, from the raw ledger.

    Reuses the reporting engine's OWN posted-entry fetch (paginated + retried +
    firm/client scoped) so the bucket definition and the live accrual reports can
    never diverge on what "the posted ledger" is."""
    entries = SupabaseLedgerSource(db)._entries(firm_id, client_id)
    return build_buckets(entries.values())


def recompute_client(db, firm_id: str, client_id: str) -> dict:
    """Rebuild and store this client's buckets.

    Delete-then-insert (not upsert) so a bucket that should no longer exist —
    e.g. its only entry was deleted or moved to another month — cannot linger.
    The whole operation is a pure function of the current ledger."""
    buckets = _compute(db, firm_id, client_id)
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "firm_id": firm_id, "client_id": client_id, "account_id": aid,
            "period_month": month, "debit_paise": dr, "credit_paise": cr,
            "updated_at": now,
        }
        for (aid, month), (dr, cr) in buckets.items()
    ]
    (db.table("account_period_balances").delete()
       .eq("firm_id", firm_id).eq("client_id", client_id).execute())
    for i in range(0, len(rows), _INSERT_CHUNK):
        db.table("account_period_balances").insert(rows[i:i + _INSERT_CHUNK]).execute()
    _logger.info("recompute_client firm=%s client=%s wrote %d buckets", firm_id, client_id, len(rows))
    return {"client_id": client_id, "buckets_written": len(rows)}


def audit_client(db, firm_id: str, client_id: str) -> dict:
    """Compare stored buckets against a fresh recompute.

    An empty discrepancy list means the passbook is exact for this client. A
    non-empty list is a bug in whatever maintains the buckets — the recompute is
    always the arbiter, so the fix is always `recompute_client`."""
    computed = _compute(db, firm_id, client_id)
    stored_rows = (
        db.table("account_period_balances")
        .select("account_id, period_month, debit_paise, credit_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
    )
    stored = {
        (r["account_id"], str(r["period_month"])[:10]): (int(r["debit_paise"] or 0), int(r["credit_paise"] or 0))
        for r in stored_rows
    }
    # build_buckets keys are already ('account', 'YYYY-MM-01') — same shape as the
    # DATE column serialises to, so the two maps compare directly.
    discrepancies = []
    for key in set(stored) | set(computed):
        s = stored.get(key, (0, 0))
        c = computed.get(key, (0, 0))
        if s != c:
            discrepancies.append({
                "account_id": key[0], "period_month": key[1],
                "stored_debit": s[0], "computed_debit": c[0],
                "stored_credit": s[1], "computed_credit": c[1],
            })
    if discrepancies:
        _logger.error("audit_client firm=%s client=%s found %d discrepancies",
                      firm_id, client_id, len(discrepancies))
    return {
        "client_id": client_id,
        "ok": not discrepancies,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies[:100],   # cap the payload; the count is authoritative
    }


def audit_and_heal_client(db, firm_id: str, client_id: str) -> dict:
    """Audit one client and, if the stored buckets drifted, self-heal by
    recomputing them from scratch. A recompute is always correct because it is a
    pure function of the ledger, so this can never make things worse — worst case
    it rewrites already-correct buckets. Drift is logged loudly (audit_client
    already logs at ERROR) so a systematic maintenance bug is visible even though
    the numbers stay right."""
    res = audit_client(db, firm_id, client_id)
    if not res["ok"]:
        recompute_client(db, firm_id, client_id)
        res["healed"] = True
        _logger.warning("audit_and_heal_client firm=%s client=%s healed %d drifted bucket(s)",
                        firm_id, client_id, res["discrepancy_count"])
    return res


def audit_and_heal_firm(db, firm_id: str) -> dict:
    """Audit (and self-heal) every client of a firm — the unit the nightly
    scheduler job runs. Returns a compact summary for the run log."""
    clients = (db.table("clients").select("id").eq("firm_id", firm_id).execute().data or [])
    checked = 0
    healed = 0
    drifted: list[dict] = []
    for c in clients:
        cid = c["id"]
        try:
            r = audit_and_heal_client(db, firm_id, cid)
        except Exception as e:  # one bad client must not abort the whole firm sweep
            _logger.error("audit_and_heal_firm firm=%s client=%s errored: %s", firm_id, cid, e)
            drifted.append({"client_id": cid, "error": str(e)})
            continue
        checked += 1
        if not r["ok"]:
            healed += 1
            drifted.append({"client_id": cid, "discrepancy_count": r["discrepancy_count"]})
    return {"clients_checked": checked, "clients_healed": healed, "drift": drifted}

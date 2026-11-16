"""Computes and stores the three nightly exception results (POST-A-050).

`domain/practice/nightly_results` is the rule and holds the vocabulary; this
module fetches what each engine needs, asks the engine, and replaces the
client's three rows in `nightly_exception_results` (migration 660).

CALLED FROM THE NIGHTLY BOOKS CHECK (`reconciliation_service.run_reconciliation`)
    which has already loaded the client's posted ledger, so the recurring-journal
    engine reads nothing more. GSTR-2B/ITC reads through the §16(4) radar's own
    service (`itc_time_bar_service.radar`), the same per-document §16(2)(aa) pass
    the GSTR-3B build runs, bounded by the months whose 2B exists. Near-duplicate
    bills read the client's live bills of the last ninety days. Every read
    carries the firm and the client.

ONE ENGINE FAILING DOES NOT LOSE THE OTHERS, AND IS NEVER STORED AS A ZERO.
    An engine that raises is stored as `not_computed` with the reason "could not
    be read", so the digest says it does not know rather than showing the last
    good number as today's or a zero as a finding of none. The failure is
    reported (`capture_posting_failure`), not swallowed.

THE WRITE is delete-then-insert per client for the rows being replaced, through
the privileged client the caller holds (the API's service client; a signed-in
session holds no write on the table).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.accounting import opening_documents as _opening
from domain.accounting import recurring_suggestions
from domain.gst import itc_time_bar as bar
from domain.practice import nightly_results as nr

_logger = logging.getLogger("caflow.nightly_exception_results")

#: Why a row is not computed when its read failed. Worded for a CA.
COULD_NOT_READ = "This could not be read during the nightly check, so nothing is known about it."


# ── the three engines ────────────────────────────────────────────────────────

def compute_gstr_2b(db, firm_id: str, client_id: str, as_of: date) -> nr.Result:
    from services import itc_time_bar_service

    radar = itc_time_bar_service.radar(db, firm_id=firm_id, client_id=client_id, as_of=as_of)
    return nr.from_itc_radar(radar, window_months=len(bar.scan_window(as_of).months))


def compute_duplicate_bills(db, firm_id: str, client_id: str, as_of: date) -> nr.Result:
    start = nr.duplicate_scan_start(as_of).isoformat()
    rows = fetch_all(
        lambda: db.table("purchase_bills")
        .select("id, vendor_id, bill_no, bill_date, total_paise, status, deleted_at, is_opening")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .neq("status", "cancelled").is_("deleted_at", "null")
        .gte("bill_date", start),
        label="nightly_results.duplicate_bills")
    return nr.duplicate_bill_pairs(_opening.without_carried_over(rows))


def compute_recurring_journals(entries, client_id: str, as_of: date) -> nr.Result:
    """From the posted ledger the nightly run already holds (a `dict[id, JournalEntry]`)."""
    start = recurring_suggestions.lookback_start(as_of).isoformat()
    posted = [
        {"id": e.id, "client_id": client_id, "narration": e.narration,
         "entry_date": e.entry_date, "entry_type": e.entry_type,
         "lines": [{"account_id": ln.account_id, "debit_paise": ln.debit_paise,
                    "credit_paise": ln.credit_paise} for ln in e.lines]}
        for e in entries.values() if str(e.entry_date) >= start
    ]
    return nr.from_recurring_suggestions(
        recurring_suggestions.suggest(posted, today=as_of), month=as_of.strftime("%Y-%m"))


# ── the run ──────────────────────────────────────────────────────────────────

def compute_all(db, firm_id: str, client_id: str, entries, as_of: date) -> list[nr.Result]:
    """Every engine's result for one client, each isolated from the others'."""
    from core.observability import capture_posting_failure

    jobs = (
        (nr.GSTR_2B, lambda: compute_gstr_2b(db, firm_id, client_id, as_of)),
        (nr.DUPLICATE_BILLS, lambda: compute_duplicate_bills(db, firm_id, client_id, as_of)),
        (nr.RECURRING_JOURNALS, lambda: compute_recurring_journals(entries, client_id, as_of)),
    )
    out: list[nr.Result] = []
    for engine, run in jobs:
        try:
            out.append(run())
        except Exception as exc:                               # noqa: BLE001
            capture_posting_failure(exc, operation=f"nightly_exception_results.{engine}",
                                    firm_id=firm_id, client_id=client_id)
            out.append(nr.not_computed(engine, COULD_NOT_READ))
    return out


def _row(firm_id: str, client_id: str, as_of: date, now: str, r: nr.Result) -> dict:
    return {
        "firm_id": firm_id, "client_id": client_id, "engine": r.engine, "status": r.status,
        "as_of_date": as_of.isoformat(), "count": r.count, "amount_paise": r.amount_paise,
        "reason": r.reason, "details": r.details, "computed_at": now,
    }


def store(db, firm_id: str, client_id: str, results: Iterable[nr.Result], as_of: date) -> int:
    """Replace this client's rows for these engines. Returns the rows written."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [_row(firm_id, client_id, as_of, now, r) for r in results]
    if not rows:
        return 0
    (db.table("nightly_exception_results").delete()
       .eq("firm_id", firm_id).eq("client_id", client_id)
       .in_("engine", [r["engine"] for r in rows]).execute())
    db.table("nightly_exception_results").insert(rows).execute()
    return len(rows)


def refresh_client(db, firm_id: str, client_id: str, entries,
                   as_of: Optional[date] = None) -> int:
    """Compute and store the three results for one client. Never raises: the
    caller is the books check, and a stage after its findings must not turn a
    finished run into a failed one."""
    from core.observability import capture_posting_failure

    day = as_of or ist_today()
    try:
        return store(db, firm_id, client_id, compute_all(db, firm_id, client_id, entries, day), day)
    except Exception as exc:                                   # noqa: BLE001
        capture_posting_failure(exc, operation="nightly_exception_results.store",
                                firm_id=firm_id, client_id=client_id)
        return 0

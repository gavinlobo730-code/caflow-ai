"""
Is this date still open? One answer, for every document type.

WHAT WAS MISSING
    period_validation_service.validate_posting_date enforces the financial-year
    lock, and sales invoices and purchase bills already call it at every write.
    It knows nothing about filed returns — it takes (firm_id, date) and a filed
    return is a fact about a CLIENT.

    So a sales invoice could be created, edited or cancelled inside a period
    whose GSTR-1 had already been filed, and nothing noticed. The return at the
    portal said one thing, the books said another, and no record explained why.

WHY THIS DELEGATES TO SQL
    period_lock_reason (migrations 267 and 361) is the same function the journal
    edit path enforces with, inside the transaction that rewrites posted rows.
    Answering the question a second time in Python would create two definitions
    of "closed" that agree right up until the day one of them is changed.

    There is a Python twin all the same, because mock mode and the in-memory
    test sources have no SQL functions at all. That is CLAUDE.md's own exception
    — MOVE the rule, and where a Python one must survive, pin the two with a
    parity test. tests/test_period_lock_reason_parity_pg.py runs every scenario
    through both halves of both entry points and asserts all four agree.

    It returns the REASON rather than a boolean, because "the year is locked"
    and "GSTR-1 covering this date was filed on 11 Jul 2026" call for different
    actions from the CA — unlock the year, versus reverse and amend in the next
    return. A bare `false` tells them neither.

TWO KINDS OF CLOSED, AND WHY THAT MATTERS HERE
    A CLOSURE is a deliberate act by the CA: they locked the firm's financial
    year, or they finalised this client's year-end. It says "these books are
    finished", it stops every posting, and they can reopen it. `closure_reason`
    is that question, and the posting KERNEL asks it, so no path reaches the
    ledger without it.

    A FILED RETURN is a fact about a document that has gone to the portal. It
    freezes what that return REPORTED — supplies and input tax credit — and it
    cannot be undone. `lock_reason` is that question plus the closures, and it
    is asked where a document that FEEDS a return is written: invoices, bills,
    credit and debit notes, and a manual journal, which can move any account
    including the tax ledgers.

    It is deliberately NOT asked by the kernel, and the calendar is the reason.
    GSTR-1 for June is filed on 11 July and GSTR-3B on the 20th, while June's
    bank reconciliation happens after both — every month, for every client. A
    hard refusal on every posting dated in June would stop June receipts, June
    payments, June bank entries, June depreciation and June payroll accruals
    from 11 July onwards. Migration 361's header carries the full argument.

FAIL CLOSED
    If the check cannot be completed we treat the period as closed. A document
    wrongly allowed into a filed period is not recoverable from the UI: the
    return has already gone to the portal. This mirrors
    manual_journal_service._lock_reason and period_validation_service, both of
    which take the same view for the same reason.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

_logger = logging.getLogger("caflow.period_lock")

# Shown when the check itself failed, rather than when the period is genuinely
# closed. Deliberately different wording from a real lock reason: the CA can act
# on "the year is locked", and all they can do about this one is try again.
UNVERIFIABLE = "Could not confirm this period is open. Please try again."


def closure_reason(db, firm_id: str, client_id: Optional[str],
                   date_str: Optional[str], cache: Optional[dict] = None) -> Optional[str]:
    """The DELIBERATE closures only — the firm's locked year, then this client's
    finalised year-end. NULL when neither applies.

    What the posting kernel asks. See the module docstring for why it asks this
    and not `lock_reason`: a filed return freezes the documents that fed it, not
    the whole ledger, and treating it as a closure would freeze routine July
    work on June for every client in the practice.

    Same cache contract as `lock_reason`, and safe to share a dict with it: the
    two questions have DIFFERENT answers for the same (firm, client, date) — a
    filed June return leaves June open to this one and closed to that one — so
    the memo key carries which question was asked.
    """
    return _reason(db, "period_closure_reason", _closure_from_tables,
                   firm_id, client_id, date_str, cache)


def lock_reason(db, firm_id: str, client_id: Optional[str],
                date_str: Optional[str], cache: Optional[dict] = None) -> Optional[str]:
    """The WHOLE rule — a closure, or a return covering the date has been filed.
    NULL when the date is open, else the sentence explaining why it is not.

    Asked where a document that FEEDS a return is written, and by the manual
    journal, which can move any account including the tax ledgers.

    A missing client_id or date means there is nothing to check — bulk paths and
    drafts legitimately reach here without both — and that is not a lock.

    `cache` is a caller-supplied dict, for a bulk import that asks the SAME
    question for row after row. It is keyed on (firm, client, date) rather than
    on the financial year, because that is the granularity of the answer: a
    filed GSTR-1 closes ONE MONTH, so a year-keyed cache — the shape
    `validate_posting_date_cached` correctly uses for the firm's own FY switch
    — would report March's filed return over an open February.

    Only the OPEN case is cached, the same rule and for the same reason as
    `validate_posting_date_cached`: nothing is remembered about a period that
    turned out to be closed, so a closed period is reported no less accurately
    than before, and `UNVERIFIABLE` — which is a failure to ask, not an answer —
    is never remembered at all. What this removes is the repeated round trip for
    the common case, which is real: `_create_invoice_core` asks once per invoice,
    and a 2,000-row CSV import is 2,000 Singapore-to-Mumbai round trips for at
    most a handful of distinct answers. Pass None (the default) for the
    single-row behaviour — one call, one question, unchanged.

    A lock cannot appear mid-request: nothing in an import files a return or
    finalises a year, so the batch legitimately sees one consistent answer.
    """
    return _reason(db, "period_lock_reason", reason_from_tables,
                   firm_id, client_id, date_str, cache)


def _reason(db, fn_name: str, twin, firm_id: str, client_id: Optional[str],
            date_str: Optional[str], cache: Optional[dict]) -> Optional[str]:
    """The plumbing both questions share: short-circuit, cache, route, fail closed.

    `fn_name` is the SQL function and `twin` its Python equivalent. Keeping this
    in one place is what stops the two questions from drifting in HOW they are
    asked while agreeing on what they mean.
    """
    if not firm_id or not client_id or not date_str:
        return None
    # The QUESTION is part of the key. `closure_reason` and `lock_reason` differ
    # by one branch, so the same (firm, client, date) is open to one and closed
    # to the other; a key without `fn_name` would let a caller who shares one
    # dict between them get whichever was asked first, silently and only when a
    # return has been filed.
    key = (fn_name, firm_id, client_id, str(date_str)[:10])
    if cache is not None and cache.get(key) is True:
        return None
    if not hasattr(db, "rpc"):
        # NOT A POSTGRES-BACKED SOURCE. These are SQL functions, and mock mode
        # and the in-memory test sources have no SQL functions at all —
        # CLAUDE.md's rule for exactly this is a Python twin pinned to the SQL
        # by a parity test, which is what `twin` is. This branch is the ABSENCE
        # of the capability, not its failure: a source that HAS rpc and raises
        # still fails closed below, because that is an outage and an outage must
        # never look like an open period.
        reason = twin(db, firm_id, client_id, date_str)
    else:
        try:
            res = db.rpc(fn_name, {
                "p_firm": firm_id, "p_client": client_id, "p_date": date_str,
            }).execute()
        except Exception as e:
            _logger.warning("%s unavailable (%s) — treating as closed", fn_name, e)
            return UNVERIFIABLE
        reason = res.data or None
    # Only the OPEN answer is remembered. A closed period is refused through a
    # real read every time, and UNVERIFIABLE returns above without reaching
    # here at all — it is a failure to ask, not an answer.
    if reason is None and cache is not None:
        cache[key] = True
    return reason


# ── The Python twins ─────────────────────────────────────────────────────────
#
# THE TWO HALVES ARE PINNED TO THE SQL BY
# tests/test_period_lock_reason_parity_pg.py, which runs every scenario through
# both and asserts they are identical. CLAUDE.md names adding the second
# implementation WITHOUT that test as the thing not to do, because two
# implementations of one rule drift and the one that drifts is the one nobody
# reads.
#
# They mirror migration 361's own shape: `_closure_from_tables` holds the two
# deliberate closures, and `reason_from_tables` CALLS it before adding the filed
# return — so neither Python nor SQL states a branch twice.


def _fy_label(date_str: Optional[str]):
    """(date, "YYYY-YY") for a readable ISO date, else (None, None).

    SQL computes the label as `lpad(((y + 1) % 100)::text, 2, '0')` and this as
    `str(y + 1)[2:]`. They agree everywhere, including the century rollover
    (2099-00, not 2099-100), and the parity test pins that rather than trusting
    it.
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(str(date_str)[:10])
    except (TypeError, ValueError):
        return None, None
    fy_start = d.year if d.month >= 4 else d.year - 1
    return d, f"{fy_start}-{str(fy_start + 1)[2:]}"


def _closure_from_tables(db, firm_id: str, client_id: Optional[str],
                         date_str: Optional[str]) -> Optional[str]:
    """The Python twin of public.period_closure_reason.

    The order of the branches is the order of the REMEDIES, most-reopenable
    first: the firm's locked year (unlock it), then this client's finalised year
    (reopen it). Migration 361 carries the same reasoning.
    """
    d, fy_label = _fy_label(date_str)
    if d is None:
        return None
    try:
        firm = (db.table("firms").select("locked_financial_years")
                .eq("id", firm_id).limit(1).execute().data or [{}])[0]
        if fy_label in (firm.get("locked_financial_years") or []):
            return (f"Financial year {fy_label} is locked. Unlock it, or post a "
                    f"reversal in an open year.")

        locked = (db.table("client_year_locks").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("financial_year", fy_label).limit(1).execute().data) or []
        if locked:
            return (f"FY {fy_label} is closed for this client — its year-end has "
                    f"been finalised. Reopen the year before posting to it.")
    except Exception as e:                                       # noqa: BLE001
        # Same fail-closed rule as the SQL path. A source that cannot answer is
        # not a source saying "open".
        _logger.warning("period closure could not be read from tables (%s)", e)
        return UNVERIFIABLE
    return None


def reason_from_tables(db, firm_id: str, client_id: Optional[str],
                       date_str: Optional[str]) -> Optional[str]:
    """The Python twin of public.period_lock_reason — the closures, then a
    return covering the date.

    A filed return is last because it is the only remedy the CA cannot simply
    undo: telling them to amend a return when all they need to do is reopen a
    year sends them to the portal for nothing.
    """
    d, _ = _fy_label(date_str)
    if d is None:
        return None
    closure = _closure_from_tables(db, firm_id, client_id, date_str)
    if closure is not None:
        return closure

    try:
        # `filings` is read with the date range applied in Python: PostgREST can
        # express `period_start <= d AND period_end >= d`, but the in-memory
        # sources this twin exists for cannot, and one comparison rule for both
        # is worth more here than one fewer row.
        rows = (db.table("filings").select("filing_type, filed_date, period_start, period_end, deleted_at")
                .eq("client_id", client_id).execute().data) or []
        covering = [
            r for r in rows
            if not r.get("deleted_at") and r.get("filed_date")
            and str(r.get("period_start") or "9999")[:10] <= d.isoformat()
            <= str(r.get("period_end") or "0000")[:10]
        ]
        if covering:
            first = min(covering, key=lambda r: str(r.get("filed_date")))
            from datetime import date as _date
            try:
                filed = _date.fromisoformat(str(first["filed_date"])[:10]).strftime("%d %b %Y")
            except (TypeError, ValueError):
                filed = str(first["filed_date"])
            return (f"{first.get('filing_type')} covering this date was filed on "
                    f"{filed}. Correct it with a reversal and an amendment in the "
                    f"next return.")
    except Exception as e:                                       # noqa: BLE001
        _logger.warning("period lock could not be read from tables (%s)", e)
        return UNVERIFIABLE
    return None


def assert_open(db, firm_id: str, client_id: Optional[str],
                date_str: Optional[str], cache: Optional[dict] = None) -> None:
    """Raise 422 carrying the reason, or return quietly.

    422 rather than 403: the request is well-formed and the caller is allowed to
    make it — the period is what refuses. The message is written for the CA and
    is surfaced verbatim, since it names the action that would work.

    `cache` is passed straight through to `lock_reason` — see its docstring for
    what is and is not remembered.
    """
    reason = lock_reason(db, firm_id, client_id, date_str, cache)
    if reason:
        raise HTTPException(status_code=422, detail=reason)

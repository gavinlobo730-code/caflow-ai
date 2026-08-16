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
    period_lock_reason (migration 267) is the same function the journal edit
    path enforces with, inside the transaction that rewrites posted rows.
    Answering the question a second time in Python would create two definitions
    of "closed" that agree right up until the day one of them is changed.

    It returns the REASON rather than a boolean, because "the year is locked"
    and "GSTR-1 covering this date was filed on 11 Jul 2026" call for different
    actions from the CA — unlock the year, versus reverse and amend in the next
    return. A bare `false` tells them neither.

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


def lock_reason(db, firm_id: str, client_id: Optional[str],
                date_str: Optional[str]) -> Optional[str]:
    """NULL when the date is open, else the sentence explaining why it is not.

    A missing client_id or date means there is nothing to check — bulk paths and
    drafts legitimately reach here without both — and that is not a lock.
    """
    if not firm_id or not client_id or not date_str:
        return None
    try:
        res = db.rpc("period_lock_reason", {
            "p_firm": firm_id, "p_client": client_id, "p_date": date_str,
        }).execute()
    except Exception as e:
        _logger.warning("period_lock_reason unavailable (%s) — treating as closed", e)
        return UNVERIFIABLE
    return res.data or None


def assert_open(db, firm_id: str, client_id: Optional[str],
                date_str: Optional[str]) -> None:
    """Raise 422 carrying the reason, or return quietly.

    422 rather than 403: the request is well-formed and the caller is allowed to
    make it — the period is what refuses. The message is written for the CA and
    is surfaced verbatim, since it names the action that would work.
    """
    reason = lock_reason(db, firm_id, client_id, date_str)
    if reason:
        raise HTTPException(status_code=422, detail=reason)

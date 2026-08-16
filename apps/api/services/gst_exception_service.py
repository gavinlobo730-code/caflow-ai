"""
Load what was filed, rebuild what the books say now, and diff them.

The comparison itself lives in domain/gst/exception_report.py and knows nothing
about a database. This module is the two reads that feed it.

WHAT COUNTS AS "WHAT WAS FILED"
    gstr1_returns.payload_json, on a return whose status is 'submitted'. Not the
    draft, and not a recomputation — the frozen GSTN JSON as at submission is the
    only record of what actually went to the portal, and it is what the CA will
    be asked about.

    A return still in draft has nothing to drift from: it is edited freely and
    re-derived from the books every time it is opened. Reporting exceptions
    against a draft would report the CA's own unsaved work back at them.

WHY A MISSING PAYLOAD IS NOT AN EMPTY ONE
    Returns submitted before task #148 wrote payload_json have status
    'submitted' and payload_json NULL. Comparing books against NULL would report
    every invoice in the period as "missing from the return" — a page of alarming
    findings describing nothing but our own past gap. That case is reported as
    what it is: unknown, not clean and not drifted.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.gst.exception_report import compare_payloads

_logger = logging.getLogger("caflow.gst_exceptions")

# Only a submitted return is frozen. Anything else is still being worked on.
_SUBMITTED = "submitted"


def _filed_return(db, firm_id: str, client_id: str, period: str) -> Optional[dict]:
    """The submitted GSTR-1 for this client and period, if there is one."""
    rows = (db.table("gstr1_returns")
            .select("id, period, gstin, status, payload_json, submitted_at, arn")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("period", period)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def gstr1_exceptions(db, firm_id: str, client_id: str, period: str) -> dict:
    """What has moved in `period` since its GSTR-1 was filed.

    Returns a `status` the caller can branch on rather than raising, because
    "this period was never filed" is a perfectly ordinary answer to this
    question and not an error:

        not_filed        — no submitted return for the period
        payload_missing  — submitted, but no frozen payload to compare against
        ok               — compared; see `report`
    """
    filed = _filed_return(db, firm_id, client_id, period)

    if not filed or filed.get("status") != _SUBMITTED:
        return {
            "status": "not_filed",
            "period": period,
            "message": "This period's GSTR-1 has not been filed, so there is nothing "
                       "to compare the books against.",
        }

    payload = filed.get("payload_json")
    if not payload:
        return {
            "status": "payload_missing",
            "period": period,
            "filed_at": filed.get("submitted_at"),
            "arn": filed.get("arn"),
            "message": "This return was marked filed before the submitted payload was "
                       "recorded, so there is nothing to compare against. Anything that "
                       "changed since then cannot be detected automatically for this "
                       "period.",
        }

    # The books as they stand now, through the same builder that produced the
    # frozen payload — so a difference is a real difference and not two
    # different renderings of the same facts.
    from services.gst_return_service import gstr1_from_books
    gstin = filed.get("gstin") or ""
    books = (gstr1_from_books(db, firm_id, client_id, period, gstin) or {}).get("payload") or {}

    report = compare_payloads(payload, books)
    return {
        "status": "ok",
        "period": period,
        "gstin": gstin,
        "filed_at": filed.get("submitted_at"),
        "arn": filed.get("arn"),
        **report,
    }

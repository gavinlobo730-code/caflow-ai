"""
Which purchase bills have gone 180 days unpaid, and what credit that reverses.

WHY THIS MATTERS MORE THAN IT LOOKS
    Rule 37 is not a warning the taxpayer can choose to act on. Credit taken on
    a bill the supplier has not been paid for within 180 days STOPS BEING
    AVAILABLE, whether or not anyone noticed, and interest under §50 runs from
    the date it was availed. A client can be quietly out of compliance for
    months because nothing in their books connects "this vendor is still
    unpaid" to "that credit is no longer ours".

    Nothing in this product connected them either, until now.

WHAT THIS DOES AND DOES NOT DO
    It reports. It does not post the reversal journal and it does not touch a
    return — the figures go in front of the CA, who decides. That is the same
    posture as everything else that would change a filed number, and CLAUDE.md's
    rule about never auto-submitting is the same instinct applied one step
    later.

    The arithmetic lives in domain/gst/itc_reversal.py, unit-tested against the
    rule rather than against a database. This module is the query and nothing
    more.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.ist_clock import ist_today
from domain.gst.itc_reversal import (
    days_outstanding, is_overdue, parse_iso, payment_due_by, reversal_for_bill,
    reversal_period,
)

_logger = logging.getLogger("caflow.itc_reversal")

# A bill only carries credit worth reversing once it is on the books. Drafts
# were never claimed and cancelled bills were undone.
_LIVE_STATUSES = ("received", "partially_paid", "paid")

PAGE = 1000


def _all_bills(db, firm_id: str, client_id: Optional[str]) -> list[dict]:
    """Every live purchase bill for the client, walked by keyset.

    PostgREST caps a read at db-max-rows (1000 here) and returns the truncated
    page without complaint — the failure this codebase has now hit six times.
    A silently short list here would under-report the reversal, which is the
    direction that costs the client interest.
    """
    out: list[dict] = []
    cursor = None
    while True:
        q = (db.table("purchase_bills")
             .select("id, bill_no, bill_date, vendor_id, status, total_paise, "
                     "paid_paise, tds_paise, cgst_paise, sgst_paise, igst_paise")
             .eq("firm_id", firm_id)
             .in_("status", list(_LIVE_STATUSES)))
        if client_id:
            q = q.eq("client_id", client_id)
        if cursor is not None:
            q = q.gt("id", cursor)
        page = q.order("id").limit(PAGE).execute().data or []
        out.extend(page)
        if len(page) < PAGE:
            break
        cursor = page[-1].get("id")
        if cursor is None:
            break
    return out


def rule37_report(db, firm_id: str, client_id: Optional[str] = None,
                  as_of: Optional[str] = None) -> dict:
    """Bills past the 180-day mark with credit still to reverse.

    `as_of` lets the CA ask the question as at a period end rather than today,
    which is how they will actually use it — the reversal belongs in a specific
    return, not in whatever month they happen to open the screen.
    """
    today = parse_iso(as_of) or ist_today()
    rows = _all_bills(db, firm_id, client_id)

    items: list[dict] = []
    totals = {"cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "total_paise": 0}

    for r in rows:
        bill_date = parse_iso(r.get("bill_date"))
        if not bill_date or not is_overdue(bill_date, today):
            continue
        reversal = reversal_for_bill(
            total_paise=int(r.get("total_paise") or 0),
            paid_paise=int(r.get("paid_paise") or 0),
            tds_paise=int(r.get("tds_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
        )
        # Overdue but settled, or overdue with no credit on it, is not a finding.
        # Reporting those would bury the ones that matter.
        if reversal["total_paise"] <= 0:
            continue

        items.append({
            "bill_id": r.get("id"),
            "bill_no": r.get("bill_no"),
            "bill_date": r.get("bill_date"),
            "vendor_id": r.get("vendor_id"),
            "status": r.get("status"),
            "total_paise": int(r.get("total_paise") or 0),
            "paid_paise": int(r.get("paid_paise") or 0),
            "tds_paise": int(r.get("tds_paise") or 0),
            "unpaid_paise": reversal["unpaid_paise"],
            "days_outstanding": days_outstanding(bill_date, today),
            "payment_due_by": payment_due_by(bill_date).isoformat(),
            # Which GSTR-3B this belongs in — Rule 37(1) says the period AFTER
            # the one the 180 days expired in, which is not obvious from the
            # dates and is the usual thing to get wrong.
            "reverse_in_period": reversal_period(bill_date),
            "reversal": {k: v for k, v in reversal.items() if k != "unpaid_paise"},
        })
        for head in totals:
            totals[head] += reversal[head]

    # Longest overdue first: that is the one accruing the most §50 interest and
    # the one the CA wants to see without scrolling.
    items.sort(key=lambda i: (-i["days_outstanding"], str(i["bill_no"] or "")))

    return {
        "as_of": today.isoformat(),
        "rule": "CGST Act §16(2) second proviso; CGST Rule 37",
        "bills": items,
        "bill_count": len(items),
        "totals": totals,
        # CA REVIEW REQUIRED — this reports what the rule requires; it posts
        # nothing and files nothing.
        "ca_review_required": True,
    }

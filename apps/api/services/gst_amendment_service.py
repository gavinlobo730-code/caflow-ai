"""
Everything a period's GSTR-1 has to carry from earlier periods already filed.

A return being prepared for July may need to declare corrections to April, May
and June — CGST Act §37 puts them in the current return's amendment tables, and
there is no other route because a filed return cannot be revised.

So this walks BACK: every submitted return before the target period, run through
the exception report (#151), each finding turned into an amendment entry (#152).

WHY IT LOOKS AT EVERY EARLIER PERIOD AND NOT JUST THE PREVIOUS ONE
    Drift is not discovered in the month it happens. An invoice edited in
    September may belong to a return filed in April, and nothing forces anyone
    to look at April again. If this only checked the immediately preceding
    period, a correction missed once would be missed for ever.

THE DEADLINE THIS DOES NOT ENFORCE
    Amendments close on 30 November following the end of the financial year
    (§37(3), as amended by the Finance Act 2022). After that the correction
    cannot be declared at all. That cutoff is task #154's job; this reports what
    is outstanding without deciding whether it is still in time, because
    silently dropping an out-of-time amendment would hide the very thing the CA
    most needs to see.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.gst.amendment_proposal import propose
from domain.gst.amendments import group_amendments, merge_into_payload
from services.gst_exception_service import gstr1_exceptions

_logger = logging.getLogger("caflow.gst_amendments")

_SUBMITTED = "submitted"
PAGE = 1000


def _sort_key(period: str) -> tuple:
    """MMYYYY as (year, month) so periods order chronologically.

    Sorting the raw string puts '012026' before '062025', which would walk the
    periods in the wrong order and name the wrong month in an `omon`.
    """
    s = str(period or "")
    if len(s) != 6 or not s.isdigit():
        return (0, 0)
    return (int(s[2:]), int(s[:2]))


def _earlier_filed_periods(db, firm_id: str, client_id: str, period: str) -> list[str]:
    """Every submitted GSTR-1 period before `period`, oldest first."""
    rows = (db.table("gstr1_returns").select("period, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("status", _SUBMITTED)
            .limit(PAGE).execute().data) or []
    target = _sort_key(period)
    periods = [r["period"] for r in rows
               if r.get("period") and _sort_key(r["period"]) < target]
    return sorted(set(periods), key=_sort_key)


def outstanding_amendments(db, firm_id: str, client_id: str, period: str) -> dict:
    """Amendments a GSTR-1 for `period` should carry from earlier filed periods.

    Returns the proposals per source period, the grouped GSTN sections ready to
    merge, and the two things that are NOT amendments: documents to carry
    forward into this period's ordinary tables, and cancellations that need the
    CA to decide.
    """
    proposals: list[dict] = []
    entries: list[dict] = []
    carry_forward: list[dict] = []
    needs_decision: list[dict] = []

    for source in _earlier_filed_periods(db, firm_id, client_id, period):
        report = gstr1_exceptions(db, firm_id, client_id, source)
        if report.get("status") != "ok" or report.get("clean"):
            continue
        proposal = propose(report, original_period=source)
        if not any(proposal["counts"].values()):
            continue
        proposals.append(proposal)
        entries.extend(proposal["entries"])
        for item in proposal["carry_forward"]:
            carry_forward.append({**item, "from_period": source})
        for item in proposal["needs_decision"]:
            needs_decision.append({**item, "from_period": source})

    sections = group_amendments(entries)

    return {
        "period": period,
        "source_periods": [p["original_period"] for p in proposals],
        "proposals": proposals,
        # Ready to fold into the target period's payload via
        # apply_amendments(); kept separate so the CA sees the un-amended
        # return alongside what would be added to it.
        "sections": sections,
        "carry_forward": carry_forward,
        "needs_decision": needs_decision,
        "counts": {
            "amendments": len(entries),
            "carry_forward": len(carry_forward),
            "needs_decision": len(needs_decision),
            "source_periods": len(proposals),
        },
        "rule": "CGST Act §37 — corrections to a filed GSTR-1 are declared in a "
                "later period's amendment tables. The window closes on 30 November "
                "following the financial year end.",
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here is added to a
        # return until the CA confirms it.
        "ca_review_required": True,
    }


def apply_amendments(payload: dict, outstanding: Optional[dict]) -> dict:
    """Fold the proposed amendment sections into a period's payload.

    Deliberately a separate call rather than something outstanding_amendments
    does on its way past: adding an amendment to a return is the CA's decision,
    and a function that reported and filed in one step would make the review
    step easy to skip.
    """
    return merge_into_payload(payload, (outstanding or {}).get("sections") or {})

"""Advances received against no invoice — GSTR-1 Tables 11A and 11B.

WHY THIS REPORTS AND DOES NOT COMPUTE
    Table 11A declares an advance on which tax is payable but no invoice has
    been issued. A row needs the place of supply, whether the supply is inter-
    or intra-state, the RATE, and the tax split — all properties of a supply
    that HAS NOT HAPPENED YET. `receipts` holds an amount, a customer and a
    date, and nothing else. There is no honest way to derive a rate from that,
    and a guessed rate on an advance is a guessed tax liability on a filed
    return.

    So this names the advances and leaves the tax to the CA, which is the same
    posture as the Rule 37 report: the figures a CA cannot see for themselves,
    put in front of them, with nothing invented.

WHY A BLANKET RULE WOULD BE WRONG EVEN WITH A RATE
    Notification 66/2017-Central Tax (15 November 2017) exempts a registered
    person from paying tax on an advance received for a supply of GOODS — the
    liability arises at the invoice instead (CGST Act §12(2) proviso). For
    SERVICES it does not: §13(2) puts the time of supply at the earlier of
    invoice or payment, so an advance for services is taxable when received.

    A receipt in this system is not marked goods or services. Two clients with
    identical books can therefore owe different tax on the same advance, and
    which one is which is a fact about their business, not about their ledger.

WHAT IS NOT HERE
    Table 11B — advance adjusted against an invoice issued in this period — is
    only meaningful for an advance whose tax was declared in 11A of an earlier
    period. Nothing has ever been declared in 11A, so there is nothing to
    adjust. The adjustments are still listed, because a CA moving to a platform
    that does support 11A needs to see them.
"""
from __future__ import annotations

import logging
from typing import Optional

_logger = logging.getLogger("caflow.gst_advances")

PAGE = 1000


def _paginate_all(make_query, key: str = "id") -> list:
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        page = q.order(key).limit(PAGE).execute().data or []
        out.extend(page)
        if len(page) < PAGE:
            break
        cursor = page[-1].get(key)
        if cursor is None:
            break
    return out


def _period_bounds(period: str) -> tuple[str, str]:
    """MMYYYY -> (first day, last day) as YYYY-MM-DD."""
    import calendar
    mm, yyyy = int(period[:2]), int(period[2:])
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def advances_report(db, firm_id: str, client_id: str, period: str) -> dict:
    """Advances a GSTR-1 for `period` may have to declare in Table 11.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reports; it computes no
    # tax, writes nothing and files nothing.
    """
    start, end = _period_bounds(period)

    receipts = _paginate_all(lambda: db.table("receipts")
        .select("id, receipt_no, receipt_date, customer_id, amount_paise, "
                "allocated_paise, unallocated_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .gte("receipt_date", start).lte("receipt_date", end))

    cust_ids = {r.get("customer_id") for r in receipts if r.get("customer_id")}
    names: dict = {}
    if cust_ids:
        rows = (db.table("customers").select("id, name, gstin, state_code")
                .eq("firm_id", firm_id).in_("id", list(cust_ids)).execute().data) or []
        names = {c["id"]: c for c in rows}

    unadjusted = []
    total = 0
    for r in receipts:
        left = int(r.get("unallocated_paise") or 0)
        if left <= 0:
            continue
        cust = names.get(r.get("customer_id")) or {}
        total += left
        unadjusted.append({
            "receipt_id": r.get("id"),
            "receipt_no": r.get("receipt_no"),
            "receipt_date": r.get("receipt_date"),
            "customer_name": cust.get("name") or "",
            "customer_gstin": cust.get("gstin"),
            "amount_paise": int(r.get("amount_paise") or 0),
            "unadjusted_paise": left,
        })

    # Longest outstanding first — the one most likely to have been forgotten.
    unadjusted.sort(key=lambda a: (str(a["receipt_date"] or ""), str(a["receipt_no"] or "")))

    return {
        "period": period,
        "unadjusted_advances": unadjusted,
        "count": len(unadjusted),
        "total_unadjusted_paise": total,
        # Stated in the payload, not only in a docstring: a CA reading an empty
        # Table 11 needs to know whether it is empty because there were no
        # advances or because nothing computes it.
        "table_11_computed": False,
        "why": (
            "PracticeSync does not compute GSTR-1 Table 11. A row needs the "
            "place of supply and the tax RATE of a supply that has not "
            "happened yet, and a receipt records only an amount, a customer "
            "and a date. Tax is payable on an advance for SERVICES (CGST Act "
            "§13(2)); Notification 66/2017-Central Tax removed it for GOODS, "
            "where the liability arises at the invoice instead. Which applies "
            "is a fact about the client's business, not about the receipt."
        ),
        "rule": "CGST Act §12(2), §13(2); Notification 66/2017-Central Tax",
        "ca_review_required": True,
    }

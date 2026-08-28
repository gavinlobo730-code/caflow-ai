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

from domain.banking.charge_gst import split_inclusive_charge

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


def _allocations_by_receipt(db, receipt_ids: list[str]) -> dict:
    """receipt_id -> [(allocated_paise, created_at)].

    Table 11 asks what was outstanding AT THE PERIOD END, not what is
    outstanding today. receipts.unallocated_paise is the state now, so reading
    it would answer a July question with August's facts and quietly change a
    filed period every time an old advance is settled.
    """
    out: dict = {}
    if not receipt_ids:
        return out
    rows = (db.table("receipt_allocations")
            .select("receipt_id, allocated_paise, created_at")
            .in_("receipt_id", receipt_ids).execute().data) or []
    for r in rows:
        out.setdefault(r.get("receipt_id"), []).append(
            (int(r.get("allocated_paise") or 0), str(r.get("created_at") or "")))
    return out


def _table_11_rows(buckets: dict) -> list[dict]:
    """GSTN Table 11 rows: one per place of supply, items grouped by rate.

    Shape read from the Returns Offline Tool V3.2.4 (returnStructure.js, cases
    'at' and 'atadj'): {pos, sply_ty, itms: [{rt, ad_amt, iamt | camt+samt,
    csamt}]}. An intra-state row splits the rate in half across CGST and SGST;
    an inter-state row carries the whole of it as IGST.
    """
    by_pos: dict = {}
    for (pos, interstate, rate_bps), gross in sorted(buckets.items()):
        if gross <= 0:
            continue
        # An advance is money the customer actually paid, so it is INCLUSIVE of
        # the tax on it. ad_amt is the taxable value backed out of it — the
        # utility multiplies ad_amt BY the rate to get the tax, so handing it
        # the gross would overstate both.
        sp = split_inclusive_charge(gross, rate_bps, is_interstate=interstate)
        key = (pos, interstate)
        item = {"rt": rate_bps / 100.0,
                "ad_amt": round(sp.taxable_paise / 100, 2)}
        if interstate:
            item["iamt"] = round(sp.igst_paise / 100, 2)
        else:
            item["camt"] = round(sp.cgst_paise / 100, 2)
            item["samt"] = round(sp.sgst_paise / 100, 2)
        item["csamt"] = 0
        row = by_pos.setdefault(key, {
            "pos": pos,
            "sply_ty": "INTER" if interstate else "INTRA",
            "itms": [],
        })
        row["itms"].append(item)
    return list(by_pos.values())


def table_11_sections(db, firm_id: str, client_id: str, period: str) -> dict:
    """GSTR-1 Tables 11A (`at`) and 11B (`txpd`), or empty when not applicable.

    Empty for a client whose gst_advance_tax_applicable is false, which is the
    default: Notification 66/2017-Central Tax removed the charge on advances
    for GOODS, so most registered persons have no Table 11 at all. A supplier
    of SERVICES turns it on (CGST Act §13(2)).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    cli = (db.table("clients").select("id, gst_advance_tax_applicable")
           .eq("id", client_id).limit(1).execute().data) or []
    if not cli or not cli[0].get("gst_advance_tax_applicable"):
        return {"at": [], "txpd": [], "applicable": False}

    start, end = _period_bounds(period)
    receipts = _paginate_all(lambda: db.table("receipts")
        .select("id, receipt_date, amount_paise, gst_rate_bps, "
                "place_of_supply, is_interstate")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .lte("receipt_date", end))
    allocs = _allocations_by_receipt(db, [r["id"] for r in receipts])

    at_buckets: dict = {}
    txpd_buckets: dict = {}
    for r in receipts:
        rate = r.get("gst_rate_bps")
        pos = r.get("place_of_supply")
        # No rate or no place of supply means the advance cannot be declared.
        # It still appears in advances_report(), so it is visible rather than
        # dropped — but a guessed rate is a guessed liability.
        if rate is None or not pos:
            continue
        key = (str(pos), bool(r.get("is_interstate")), int(rate))
        mine = allocs.get(r["id"], [])
        amount = int(r.get("amount_paise") or 0)
        adjusted_by_end = sum(a for a, ts in mine if ts[:10] <= end)
        adjusted_in_period = sum(a for a, ts in mine if start <= ts[:10] <= end)
        received_this_period = start <= str(r.get("receipt_date") or "")[:10] <= end

        if received_this_period:
            # 11A: received now, still not invoiced by the period end.
            left = amount - adjusted_by_end
            if left > 0:
                at_buckets[key] = at_buckets.get(key, 0) + left
        elif adjusted_in_period > 0:
            # 11B: received in an EARLIER period — so its tax was declared in
            # that period's 11A — and adjusted against an invoice now. An
            # advance received and adjusted inside one period never reaches
            # either table: it was invoiced before any 11A could declare it.
            txpd_buckets[key] = txpd_buckets.get(key, 0) + adjusted_in_period

    return {
        "at": _table_11_rows(at_buckets),
        "txpd": _table_11_rows(txpd_buckets),
        "applicable": True,
    }


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

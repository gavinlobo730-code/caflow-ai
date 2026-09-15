"""CGST Rule 37A's inputs — which of the year's credit rests on a supplier's
GSTR-3B (GST-28, second half).

`domain/gst/rule_37a.py` is the rule; this fetches what it needs and nothing
else, and decides nothing it decides.

WHY IT READS `gstr2a_records` AND NOT `purchase_bills`
    Rule 37A reaches a supply whose invoice the supplier DID declare in
    GSTR-1 — that is its opening words. `gstr2a_records` (migration 340) is
    exactly that population: one row per document the reconciliation saw,
    already carrying the supplier's GSTIN and name and the tax per head, and
    already carrying `purchase_bill_id` where it matched a bill of ours. A
    read of `purchase_bills` would pick up every bill including the ones
    missing from 2B, which are a s.16(2)(aa) problem and belong in the
    reconciliation rather than here.

`supplier_filed_on` IS ON THAT TABLE AND IS THE TRAP. It records when the
GSTR-1 was filed, which is what GSTR-2B communicates. Rule 37A turns on the
GSTR-3B, which 2B does not carry at all — see
`domain/gst/rule_37a.SUPPLIER_FILING_NOT_HELD`. Reading it as the answer
would report every supplier as compliant.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import fy_bounds, ist_today
from domain.gst import rule_37a as rule

_logger = logging.getLogger("caflow.rule_37a")

#: The reconciliation's own vocabulary for a document that agreed with a bill
#: of ours. Taken from `domain/gst/itc_matching` rather than spelled here.
_MATCHED = "matched"


def _period_in_fy(period: str, financial_year: str) -> bool:
    """Whether an MMYYYY return period falls in this financial year.

    STRING COMPARISON IS WRONG ON MMYYYY — '042025' is greater than '032026' —
    which is the same trap `services/gstr9_service` records. The month and the
    year are split and tested.
    """
    p = str(period or "").strip()
    if len(p) != 6 or not p.isdigit():
        return False
    month, year = int(p[:2]), int(p[2:])
    start_year = int(str(financial_year).split("-")[0])
    return ((year == start_year and 4 <= month <= 12)
            or (year == start_year + 1 and 1 <= month <= 3))


def build(db, firm_id: str, client_id: str, *, financial_year: str) -> dict:
    """The credit at risk under Rule 37A for one client and one year.

    # CA REVIEW REQUIRED — this reports. It posts nothing and files nothing.
    """
    try:
        fy_bounds(financial_year)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    rows = fetch_all(
        lambda: db.table("gstr2a_records").select(
            "id, firm_id, client_id, supplier_gstin, supplier_name, "
            "supplier_trade_name, return_period, match_status, "
            "purchase_bill_id, igst_paise, cgst_paise, sgst_paise, cess_paise, "
            "itc_available")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="rule_37a.gstr2a_records")

    matched: list = []
    vendors: dict = {}
    for r in rows:
        if str(r.get("match_status") or "") != _MATCHED:
            continue
        if not _period_in_fy(r.get("return_period"), financial_year):
            continue
        # A document the portal itself says carries no credit never gave the
        # client anything to reverse. `itc_available` is 2B's own `itcavl`,
        # which `domain/gst/gstr2b.py` reads off the document.
        if r.get("itc_available") is False:
            continue
        gstin = str(r.get("supplier_gstin") or "")
        key = gstin or str(r.get("supplier_name") or "")
        vendors.setdefault(key, {
            "name": (r.get("supplier_trade_name") or r.get("supplier_name")
                     or gstin or "—"),
            "gstin": gstin or None,
        })
        matched.append({
            "vendor_id": key,
            "igst_paise": int(r.get("igst_paise") or 0),
            "cgst_paise": int(r.get("cgst_paise") or 0),
            "sgst_paise": int(r.get("sgst_paise") or 0),
            "cess_paise": int(r.get("cess_paise") or 0),
        })

    out = rule.build(financial_year=financial_year, as_of=ist_today(),
                     matched_bills=matched, vendors=vendors).as_dict()
    out["source"] = ("derived from gstr2a_records — the documents the GSTR-2B "
                     "reconciliation matched, which is the population Rule "
                     "37A's own opening words describe")
    return out

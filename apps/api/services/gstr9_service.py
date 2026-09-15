"""The annual return's inputs (GST-10).

`domain/gst/gstr9_builder.py` is the rule; this fetches what it needs and
nothing else. CGST Act s.44 with Rule 80(1): the annual return consolidates the
year's own monthly returns, so what is read here is TWENTY-FOUR header rows and
their stored payloads — never a year of transactions. (CLAUDE.md, "Reporting
performance": what crosses the wire is proportional to the ANSWER.)

Nothing is posted, nothing is filed, nothing is transmitted.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.gst import gstr9_builder as g9
from services.gst_return_service import gstr9_fy_periods

_logger = logging.getLogger("caflow.gstr9")


# Both readers below name their table as a LITERAL rather than taking it as a
# parameter: the column scan resolves neither a dynamic table nor a computed
# column, so one shared reader would make every filter in it invisible.


def _gstr1_rows(db, firm_id: str, client_id: str, gstin: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr1_returns").select(
            "id, period, status, return_type, gstin, payload_json, "
            "total_taxable_paise, total_igst_paise, total_cgst_paise, "
            "total_sgst_paise, total_cess_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("gstin", gstin),
        key="id", label="gstr9.gstr1_returns")


def _gstr3b_rows(db, firm_id: str, client_id: str, gstin: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr3b_returns").select(
            "id, period, status, gstin, payload_json, tax_liability_paise, "
            "itc_claimed_paise, net_tax_paise, cash_payable_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("gstin", gstin),
        key="id", label="gstr9.gstr3b_returns")


def _reversals(db, firm_id: str, client_id: str,
               periods: list[str]) -> list[g9.Reversal]:
    """The year's ITC reversals, per statutory GROUND.

    `itc_reversal_register` (migrations 285 and 362) is the only place the
    ground is recorded. GSTR-3B's own Table 4(B) cannot answer Table 7: it has
    two boxes, permanent and reclaimable, and Rules 38, 42, 43 and s.17(5)
    share one.

    THE YEAR IS SELECTED BY `period`, NOT BY A DATE, and that is the rule
    rather than a workaround for a column the table happens not to have. The
    register carries no reversal date at all — migration 285 gives it `period`,
    "MMYYYY of the GSTR-3B this row is declared in", which is exactly what
    Table 7 asks for: s.44 with Rule 80(1) consolidates the returns FURNISHED
    for the year, so a reversal declared in March 2026's GSTR-3B belongs to FY
    2025-26 whichever day the CA posted the journal.

    `.in_(periods)` and never a range: the period is TEXT in MMYYYY, so a
    `gte`/`lte` on it compares strings — '042025' is greater than '032026',
    which would drop the first nine months of every year and keep three that
    belong to the next one.
    """
    rows = fetch_all(
        lambda: db.table("itc_reversal_register").select(
            "id, period, reason_code, igst_paise, cgst_paise, sgst_paise, "
            "cess_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("period", list(periods)),
        key="id", label="gstr9.itc_reversal_register")
    return [
        g9.Reversal(
            reason_code=str(r.get("reason_code") or "other"),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0))
        for r in rows
    ]


#: WHY TABLE 8A IS LEFT FOR THE PORTAL, AND IS NOT A DEFECT.
#:
#: 8A is "ITC as per GSTR-2A / 2B", and GSTN AUTO-POPULATES it from the 2B it
#: issued — the taxpayer does not compute it. This product does hold the year's
#: 2B documents (`gstr2a_records`, one row per document), but summing a year of
#: them is a read proportional to TRANSACTION VOLUME, which CLAUDE.md's
#: reporting rule forbids outright: 8A is four numbers and the read would be
#: thousands of rows for a real client. A stored per-period total on
#: `gstr2b_reconciliations` would make it twelve rows and is the right next
#: step; it is a migration, and a figure that is right only for periods
#: reconciled after it lands would be worse than none.
#:
#: What IS derived is 8B, which is the figure the CA compares 8A against — so
#: the comparison happens on the portal, with both halves known.
TABLE_8A_IS_THE_PORTALS = (
    "Table 8A is auto-populated by the portal from the GSTR-2B it issued. This "
    "product holds the year's 2B documents per period, and totalling a year of "
    "them is a read proportional to transaction volume rather than to the "
    "four-number answer, so it is not done here — 8B is derived, which is the "
    "half the portal cannot supply."
)


def build(db, firm_id: str, client_id: str, *, financial_year: str,
          gstin: str, inputs: Optional[g9.AnnualInputs] = None) -> dict:
    """The annual return's working for one registration and one year.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    try:
        periods = gstr9_fy_periods(financial_year)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    in_fy = set(periods)
    g1 = {str(r.get("period")): r for r in _gstr1_rows(db, firm_id, client_id, gstin)
          if str(r.get("period")) in in_fy
          and (r.get("return_type") or "gstr1") == "gstr1"}
    g3 = {str(r.get("period")): r for r in _gstr3b_rows(db, firm_id, client_id, gstin)
          if str(r.get("period")) in in_fy}

    months = [
        g9.MonthlyReturn(
            period=p,
            gstr1_status=(g1.get(p) or {}).get("status"),
            gstr3b_status=(g3.get(p) or {}).get("status"),
            gstr1_payload=(g1.get(p) or {}).get("payload_json") or None,
            gstr3b_row=g3.get(p))
        for p in periods
    ]

    out = g9.build_gstr9(
        financial_year=financial_year, gstin=gstin, months=months,
        reversals=_reversals(db, firm_id, client_id, periods),
        two_b=None,
        inputs=inputs).as_dict()
    out["not_built"] = {**g9.NOT_BUILT, "8A": TABLE_8A_IS_THE_PORTALS}
    out["source"] = ("consolidated from this client's own filed GSTR-1 and "
                     "GSTR-3B for the year, and the ITC reversal register")
    return out

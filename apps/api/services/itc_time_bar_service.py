"""The §16(4) radar's reads (gst-15). `domain/gst/itc_time_bar` is the rule.

THIS FETCHES; IT DECIDES NOTHING. It reads the client's received bills, the
stored GSTR-2B rows and the reconciliation headers for the months the rule says
to scan, runs the SAME per-document §16(2)(aa) pass the GSTR-3B build runs, and
hands the verdicts to the domain module to lay against the dates.

IT IS THE RETURN'S PASS, NOT A COPY OF IT. The verdicts come from
`rule_36_4.assess` over the same inputs the return builds —
`gst_return_service._two_b_by_document` for the stored rows and
`_documents_the_recon_never_saw` for the bills recorded after their month's
reconciliation — imported by name rather than restated. A second matcher would
disagree with the reconciliation the CA is looking at (rule_36_4's own header),
and a radar that said a credit was safe when the return withholds it, or at risk
when the return claims it, would be worse than none.

PER MONTH, because the pass is. `assess(..., have_2b=True)` on a bill in a month
nobody reconciled would call it `not_in_2b` — a withholding no reconciliation
ever made — so each reconciled month is assessed on its own bills and a month
with no header is reported as a month, not as a list of bills.

BOUNDED BY THE WINDOW. `itc_time_bar.scan_window` limits the read to the
financial years whose §16(4) date has not closed more than sixty days ago (at
most two) and the months whose GSTR-2B exists, in narrow projections and paged
(`fetch_all`). It is not proportional to the ledger's history; it IS
proportional to the bills of those months, because a bill cannot be called
unclaimed without being read. A SQL function returning the withheld bills would
be the shape the reporting rule prefers, and is recorded as the next step rather
than built here: it would put the §16(2)(aa) pass in two languages, and that
rule says to move a rule, never copy it.

FIRM- AND CLIENT-SCOPED in every read: the service-role key bypasses RLS.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.db_paging import fetch_all
from domain.accounting import opening_documents as _opening
from domain.gst import itc_time_bar as bar
from domain.gst import rule_36_4
from services import gst_2b_reconciliation_service as recon
from services import gst_amendment_service
from services import gst_return_service as returns

def _bills(db, firm_id: str, client_id: str, window: bar.ScanWindow) -> list[dict]:
    # A narrow projection, never `*`: what the §16(2)(aa) pass needs of a bill.
    # `is_opening` is in it on purpose — `without_carried_over` reads the key off
    # the row, so a projection that omitted it would make the filter a silent
    # no-op and put a carried-over bill on the radar (it has no 2B counterpart,
    # ever).
    rows = fetch_all(
        lambda: db.table("purchase_bills").select(
            "id, vendor_id, bill_no, our_reference, bill_date, status, "
            "is_opening, is_reverse_charge, created_at, igst_paise, cgst_paise, "
            "sgst_paise, cess_paise, ineligible_itc_igst_paise, "
            "ineligible_itc_cgst_paise, ineligible_itc_sgst_paise, "
            "ineligible_itc_cess_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("status", list(returns._BILL_POSTED))
        .is_("deleted_at", "null")
        .gte("bill_date", window.from_date.isoformat())
        .lte("bill_date", window.to_date.isoformat()),
        key="id", label="itc time bar: bills")
    return _opening.without_carried_over(rows)


def _unbooked_documents(db, firm_id: str, client_id: str,
                        periods: list[str]) -> list[dict]:
    """Stored 2B rows with no bill behind them, for the reconciled months."""
    if not periods:
        return []
    out: list[dict] = []
    # `.in_` over the NAMED months and never a range: MMYYYY is TEXT.
    for i in range(0, len(periods), 24):
        out.extend(fetch_all(
            lambda: db.table("gstr2a_records").select(
                "id, return_period, document_type, supplier_gstin, supplier_name, "
                "invoice_number, invoice_date, igst_paise, cgst_paise, "
                "sgst_paise, cess_paise, itc_available, match_status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("return_period", periods[i:i + 24])
            .eq("match_status", "missing_in_books"),
            key="id", label="itc time bar: unbooked 2B documents"))
    return out


def radar(db, *, firm_id: str, client_id: str, as_of: date) -> dict:
    """The credit not yet claimed, laid against the date it lapses."""
    window = bar.scan_window(as_of)
    filed = gst_amendment_service.annual_returns_filed_safely(db, firm_id, client_id)

    headers = recon.reconciled_at_by_period(db, firm_id=firm_id, client_id=client_id)
    reconciled = [p for p in window.months if p in headers]
    unreconciled = [p for p in window.months if p not in headers]

    bills = [b for b in _bills(db, firm_id, client_id, window)
             if _month_key(b) in set(reconciled)]

    stored = returns._gstr2a_for_periods(db, firm_id, client_id, reconciled) \
        if reconciled else []
    two_b = returns._two_b_by_document(stored)
    unexamined = returns._documents_the_recon_never_saw(bills, headers)
    names = returns._vendor_names(db, firm_id, bills)

    # PER MONTH — see the module docstring.
    verdicts: list[rule_36_4.DocumentVerdict] = []
    for period in reconciled:
        docs = []
        for b in (x for x in bills if _month_key(x) == period):
            docs.append(rule_36_4.BookDocument(
                document_id=str(b.get("id") or "") or None,
                label=str(b.get("bill_no") or b.get("our_reference") or "(unlabelled)"),
                supplier=names.get(b.get("vendor_id"), ""),
                # NET of §17(5): blocked tax was never credit, so it is not "at risk".
                igst_paise=int(b.get("igst_paise") or 0)
                - int(b.get("ineligible_itc_igst_paise") or 0),
                cgst_paise=int(b.get("cgst_paise") or 0)
                - int(b.get("ineligible_itc_cgst_paise") or 0),
                sgst_paise=int(b.get("sgst_paise") or 0)
                - int(b.get("ineligible_itc_sgst_paise") or 0),
                cess_paise=int(b.get("cess_paise") or 0)
                - int(b.get("ineligible_itc_cess_paise") or 0),
                is_reverse_charge=bool(b.get("is_reverse_charge", False)),
                was_examined=str(b.get("id") or "") not in unexamined))
        verdicts.extend(rule_36_4.assess(docs, two_b, True).verdicts)

    bill_dates = {str(b["id"]): str(b.get("bill_date") or "") for b in bills}
    rows, blocked, not_assessed = bar.withheld_rows(
        verdicts, bill_dates, as_of=as_of, filed_by_fy=filed)
    rows += bar.not_booked_rows(
        _unbooked_documents(db, firm_id, client_id, reconciled),
        as_of=as_of, filed_by_fy=filed)

    return bar.radar(
        rows,
        unreconciled=bar.unreconciled_rows(unreconciled, as_of=as_of, filed_by_fy=filed),
        blocked=blocked, unexamined=not_assessed, as_of=as_of,
        scanned_fys=[f"{y - 1}-{str(y)[2:]}" for y in window.fy_ends])


def _month_key(bill: dict) -> str:
    """MMYYYY of a bill's own date — the key every period-scoped table uses."""
    d = str(bill.get("bill_date") or "")
    return f"{d[5:7]}{d[0:4]}" if len(d) >= 7 else ""

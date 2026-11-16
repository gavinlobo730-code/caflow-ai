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

BOUNDED BY THE WINDOW, AND THE DATABASE KEEPS ONLY WHAT COULD BE WITHHELD
(POST-A-062). `itc_time_bar.scan_window` limits the read to the financial
years whose §16(4) date has not closed more than sixty days ago (at most two)
and the months whose GSTR-2B exists. Within them, `public.itc_time_bar_candidates`
(migration 616) joins each bill with the 2B rows matched to it and its month's
reconciliation header IN THE DATABASE and returns only the bills the pass could
withhold, block or leave unassessed, with the inputs the pass needs. The pass
itself stays `rule_36_4.assess`, in Python and nowhere else: the function only
leaves out bills it would allow, and
`tests/test_the_16_4_radar_candidates_parity_pg.py` holds that choice equal to
the pass's. So what crosses the wire is proportional to the answer. Where the
function cannot be called (mock mode, or a database the migration has not
reached) the bills are read and judged here as before, which is the twin the
parity test compares with; the call failing is logged, never silent.

FIRM- AND CLIENT-SCOPED in every read: the service-role key bypasses RLS.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import logging
from dataclasses import dataclass, field

from core.db_paging import fetch_all
from domain.accounting import opening_documents as _opening
from domain.gst import itc_time_bar as bar
from domain.gst import rule_36_4
from services import gst_2b_reconciliation_service as recon
from services import gst_amendment_service
from services import gst_return_service as returns

_logger = logging.getLogger("caflow.itc_time_bar")

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


@dataclass
class _Judged:
    """What the §16(2)(aa) pass is asked of: the bills (heads already net of §17(5)), the 2B figures matched to each, the bills
    nobody has asked yet, and each bill's supplier name and GSTIN. The same shape whichever read produced it."""
    bills: list = field(default_factory=list)
    two_b: dict = field(default_factory=dict)
    unexamined: set = field(default_factory=set)
    names: dict = field(default_factory=dict)
    gstins: dict = field(default_factory=dict)


def _from_the_database(db, firm_id: str, client_id: str, window: bar.ScanWindow,
                       reconciled: list[str]) -> Optional[_Judged]:
    """The candidates `public.itc_time_bar_candidates` keeps (migration 616), or None where it cannot be asked."""
    rpc = getattr(db, "rpc", None)
    if rpc is None:
        return None
    try:
        res = rpc("itc_time_bar_candidates", {
            "p_firm_id": firm_id, "p_client_id": client_id,
            "p_from": window.from_date.isoformat(), "p_to": window.to_date.isoformat(),
            "p_periods": list(reconciled),
        }).execute()
        rows = getattr(res, "data", None)
        if not isinstance(rows, list):
            raise ValueError(f"itc_time_bar_candidates returned {type(rows).__name__}, not a list")
    except Exception as e:                                  # noqa: BLE001
        _logger.error("itc_time_bar_candidates failed (%s %s); reading the bills instead: %s", firm_id, client_id, e)
        return None
    out = _Judged()
    for r in rows:
        bid = str(r.get("id") or "")
        out.bills.append({
            "id": bid, "vendor_id": r.get("vendor_id"), "bill_no": r.get("bill_no"),
            "our_reference": r.get("our_reference"), "bill_date": str(r.get("bill_date") or "")[:10],
            "is_reverse_charge": bool(r.get("is_reverse_charge")),
            **{h: int(r.get(h) or 0) for h in ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise")}})
        if not r.get("examined"):
            out.unexamined.add(bid)
        if r.get("matched"):
            out.two_b[bid] = rule_36_4.TwoBDocument(
                matched=True, itc_available="N" if r.get("blocked") else "Y",
                reason_code=str(r.get("reason_code") or ""),
                igst_paise=int(r.get("filed_igst_paise") or 0), cgst_paise=int(r.get("filed_cgst_paise") or 0),
                sgst_paise=int(r.get("filed_sgst_paise") or 0), cess_paise=int(r.get("filed_cess_paise") or 0))
        if r.get("vendor_id"):
            out.names[r["vendor_id"]] = r.get("vendor_name") or ""
            out.gstins[r["vendor_id"]] = r.get("vendor_gstin") or ""
    return out


def _read_here(db, firm_id: str, client_id: str, window: bar.ScanWindow,
               reconciled: list[str], headers: dict) -> _Judged:
    """The twin: every bill of the reconciled months, with the 2B rows and headers read here (what the radar did before 616)."""
    months = set(reconciled)
    raw = [b for b in _bills(db, firm_id, client_id, window) if _month_key(b) in months]
    stored = returns._gstr2a_for_periods(db, firm_id, client_id, reconciled) if reconciled else []
    out = _Judged(two_b=returns._two_b_by_document(stored),
                  unexamined=returns._documents_the_recon_never_saw(raw, headers))
    for b in raw:
        out.bills.append({
            "id": str(b.get("id") or ""), "vendor_id": b.get("vendor_id"), "bill_no": b.get("bill_no"),
            "our_reference": b.get("our_reference"), "bill_date": str(b.get("bill_date") or "")[:10],
            "is_reverse_charge": bool(b.get("is_reverse_charge", False)),
            # NET of §17(5): blocked tax was never credit, so it is not "at risk".
            **{f"{h}_paise": int(b.get(f"{h}_paise") or 0) - int(b.get(f"ineligible_itc_{h}_paise") or 0)
               for h in ("igst", "cgst", "sgst", "cess")}})
    for v in _vendors(db, firm_id, raw):
        out.names[v["id"]] = v.get("name") or ""
        out.gstins[v["id"]] = v.get("gstin") or ""
    return out


def _vendors(db, firm_id: str, bills: list[dict]) -> list[dict]:
    """The suppliers of these bills: the name the screen shows and the GSTIN a late-furnished document is joined on."""
    ids = sorted({str(b["vendor_id"]) for b in bills if b.get("vendor_id")})
    out: list[dict] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        out.extend(fetch_all(lambda chunk=chunk: db.table("vendors").select("id, name, gstin")
                             .eq("firm_id", firm_id).in_("id", chunk),
                             key="id", label="itc time bar: suppliers"))
    return out


def radar(db, *, firm_id: str, client_id: str, as_of: date) -> dict:
    """The credit not yet claimed, laid against the date it lapses."""
    window = bar.scan_window(as_of)
    filed = gst_amendment_service.annual_returns_filed_safely(db, firm_id, client_id)

    headers = recon.reconciled_at_by_period(db, firm_id=firm_id, client_id=client_id)
    reconciled = [p for p in window.months if p in headers]
    unreconciled = [p for p in window.months if p not in headers]

    judged = (_from_the_database(db, firm_id, client_id, window, reconciled) if reconciled else _Judged())
    if judged is None:
        judged = _read_here(db, firm_id, client_id, window, reconciled, headers)

    # PER MONTH — see the module docstring.
    verdicts: list[rule_36_4.DocumentVerdict] = []
    for period in reconciled:
        docs = []
        for b in (x for x in judged.bills if _month_key(x) == period):
            docs.append(rule_36_4.BookDocument(
                document_id=b["id"] or None,
                label=str(b.get("bill_no") or b.get("our_reference") or "(unlabelled)"),
                supplier=judged.names.get(b.get("vendor_id"), ""),
                igst_paise=b["igst_paise"], cgst_paise=b["cgst_paise"],
                sgst_paise=b["sgst_paise"], cess_paise=b["cess_paise"],
                is_reverse_charge=b["is_reverse_charge"],
                was_examined=b["id"] not in judged.unexamined))
        verdicts.extend(rule_36_4.assess(docs, judged.two_b, True).verdicts)

    bill_dates = {b["id"]: b["bill_date"] for b in judged.bills}
    rows, blocked, not_assessed = bar.withheld_rows(
        verdicts, bill_dates, as_of=as_of, filed_by_fy=filed)
    # A bill a supplier furnished in a LATER month's 2B is joined to that document (POST-A-062), and the document leaves the
    # unbooked list rather than being listed a second time.
    bill_keys = {b["id"]: (judged.gstins.get(b.get("vendor_id"), ""), str(b.get("bill_no") or ""))
                 for b in judged.bills}
    rows, unbooked = bar.join_furnished_later(
        rows, _unbooked_documents(db, firm_id, client_id, reconciled), bill_keys)
    rows += bar.not_booked_rows(unbooked, as_of=as_of, filed_by_fy=filed)

    return bar.radar(
        rows,
        unreconciled=bar.unreconciled_rows(unreconciled, as_of=as_of, filed_by_fy=filed),
        blocked=blocked, unexamined=not_assessed, as_of=as_of,
        scanned_fys=[f"{y - 1}-{str(y)[2:]}" for y in window.fy_ends])


def _month_key(bill: dict) -> str:
    """MMYYYY of a bill's own date — the key every period-scoped table uses."""
    d = str(bill.get("bill_date") or "")
    return f"{d[5:7]}{d[0:4]}" if len(d) >= 7 else ""

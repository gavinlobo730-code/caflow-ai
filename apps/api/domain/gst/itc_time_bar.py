"""The §16(4) time bar, laid out against the credit that is not yet claimed
(gst-15) — a dated radar, nearest lapse first.

WHAT WAS MISSING
    CGST §16(4) takes the credit away: it cannot be availed on an invoice or
    debit note after 30 November following the end of the financial year the
    invoice PERTAINS to, or the furnishing of that year's annual return,
    whichever is earlier. The product had the date — `correction_window` has
    answered it for the §37(3) amendment window since GST-09, and says in its own
    docstring that "one window governs amendments and unclaimed credit alike" —
    and nothing laid it against the credit. A CA could see, bill by bill, that a
    supplier had not filed; nothing said which of those credits would be GONE on
    30 November if they still had not.

THE DATE IS NOT RESTATED HERE
    `correction_window.window_for` is the one place that knows the rule and its
    "whichever is earlier": it reads `compliance_engine.correction_window_closes`
    and honours the GSTR-9 date the books hold. This module calls it with the
    INVOICE's own period and never mentions 30 November — a copy of the rule here
    would be the second implementation the file keeps recording the cost of
    (`november_30_cutoff` alone tells a CA a window is open when an early GSTR-9
    has already shut it).

    THE YEAR IS THE DOCUMENT'S, NOT THE RETURN'S. §16(4) reads "the financial
    year to which such invoice or debit note pertains": a March invoice booked in
    June lapses with FY N-1, and the return it would be claimed in has no say. So
    the key is the bill's own date, and a bill dated 31 March and one dated 1 April
    fall in different years with different lapse dates.

WHAT GOES ON THE RADAR — credit a supplier's action could still rescue
    * `withheld_bill` — a received bill whose credit the per-document §16(2)(aa)
      pass WITHHOLDS (`rule_36_4`): the supplier has not furnished it
      (`not_in_2b`) or furnished it for less (`more_than_2b`, the EXCESS). The
      amount is net of §17(5), which was never credit to begin with.
    * `not_booked` — a document the supplier DID furnish and 2B communicates,
      for which the books hold no bill: credit available and not being claimed,
      and equally lost on the same date if nobody books it.

WHAT DOES NOT
    * a bill the portal has already marked ITC-unavailable (`blocked_by_2b`) —
      waiting will not change what 2B says, so a lapse date beside it would
      promise a rescue that is not on offer. It is COUNTED and named, because it
      is withheld credit the CA should know about; it is just not a deadline.
    * a bill that matched and is claimed, a reverse-charge bill (self-assessed,
      paid in cash) and a bill recorded after its month's reconciliation ran
      (`not_assessed` — nobody has asked §16(2)(aa) of it yet, and the answer is
      to re-run the reconciliation, which is NAMED, not to count it as at risk).
    * a bill in a month with NO reconciliation. §16(2)(aa) has not been asked of
      it, so nothing can be said about its credit — but a month nobody has
      reconciled, inside a window that is closing, is exactly the thing this
      screen exists to surface, so the MONTH is listed with its own lapse date.

A CLOSED WINDOW IS STILL REPORTED. After the date there is no mechanism to take
    the credit, and a CA needs to know what was lost at least as much as what can
    be saved — `correction_window`'s own rule. Only windows that closed within
    `RECENTLY_CLOSED_DAYS` are read at all: older years are not a deadline, and
    reading them would make the read proportional to the ledger.

BOUNDED BY THE WINDOW, NOT BY THE LEDGER (the reporting rule): the scan covers
    the financial years whose window has not closed more than sixty days ago —
    at most two — and only the months whose GSTR-2B has been generated.

WHAT IT DOES NOT DECIDE
    Matching is per MONTH, as the reconciliation's is: a bill is judged against
    its own month's 2B. A supplier who files an April invoice late appears in a
    LATER month's 2B, where the document reads `not_booked` while the bill
    stays `not_in_2b` in April. Both are listed — the credit really is unclaimed
    — and the screen says so; joining them across months is a change to the
    reconciliation, not to this report. Nothing here claims credit, posts or files:
    the radar is read-only and sends nothing to any portal.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from domain.gst import correction_window as cw
from domain.gst import rule_36_4

#: A window that closed longer ago than this is history, not a deadline, and is
#: not read. Sixty days is two return cycles: long enough for "this closed last
#: week" to be said, short enough that the scan stays at two financial years.
RECENTLY_CLOSED_DAYS = 60

#: GSTR-2B for a month is generated on the 14th of the next. `[S]` — the day is
#: read from the portal's published schedule and could not be re-fetched here,
#: and it only decides which recent months are called "not yet reconciled".
GSTR2B_GENERATED_ON_DAY = 14

KIND_WITHHELD = "withheld_bill"
KIND_NOT_BOOKED = "not_booked"

#: The verdicts a supplier's action can still turn into credit.
RESCUABLE_VERDICTS = (rule_36_4.NOT_IN_2B, rule_36_4.MORE_THAN_2B)

BLOCKED_IS_NOT_A_DEADLINE = (
    "These bills are withheld because GSTR-2B itself marks their credit "
    "unavailable. Waiting does not change what the portal says, so they carry no "
    "date here — check the document (see the GSTR-3B working).")

NOT_ASSESSED_IS_NOT_AT_RISK = (
    "These bills were recorded after the GSTR-2B for their month was reconciled, "
    "so §16(2)(aa) has not been asked of them and they are not counted as at "
    "risk. Run the reconciliation for those months again.")

MATCHING_IS_PER_MONTH = (
    "Each bill is judged against the GSTR-2B for its OWN month, as the "
    "reconciliation does. A supplier who files an April invoice late appears in a "
    "later month's GSTR-2B, where it is listed below as a document with no bill, "
    "while the April bill stays unmatched: both are credit not yet claimed, and "
    "the lapse date is the same.")


@dataclass(frozen=True)
class ScanWindow:
    """What the radar reads: the dates, the months and the years."""
    from_date: date
    to_date: date
    #: MMYYYY, oldest first — only months whose GSTR-2B has been generated.
    months: tuple[str, ...]
    #: Calendar year each scanned FY ends in.
    fy_ends: tuple[int, ...]


def _period_of(d: date) -> str:
    return f"{d.month:02d}{d.year:04d}"


def _parse(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _month_add(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def scan_window(as_of: date) -> ScanWindow:
    """The financial years and months the radar reads as at `as_of`.

    Every FY from the latest one (the year `as_of` falls in) back to the oldest
    whose §16(4) window has not closed more than `RECENTLY_CLOSED_DAYS` ago. The
    statutory date is a SUPERSET test — a GSTR-9 can only bring a window in, never
    push it out — so an early annual return cannot hide a year from the scan.
    """
    latest = cw.financial_year_end(_period_of(as_of))
    assert latest is not None
    floor = as_of - timedelta(days=RECENTLY_CLOSED_DAYS)
    earliest = latest
    # The statutory date of the year BEFORE `earliest`, asked of the one window
    # authority through a period in that year (April of its first calendar year).
    while date.fromisoformat(cw.window_for(
            f"04{earliest - 2:04d}", as_of=as_of)["statutory_cutoff"]) >= floor:
        earliest -= 1

    from_date = date(earliest - 1, 4, 1)
    # The last month whose 2B exists: the 14th of the next month is when it is
    # generated, so before the 14th the previous month's is still outstanding.
    back = 1 if as_of.day >= GSTR2B_GENERATED_ON_DAY else 2
    ly, lm = _month_add(as_of.year, as_of.month, -back)
    to_date = date(ly, lm, calendar.monthrange(ly, lm)[1])

    months: list[str] = []
    y, m = from_date.year, from_date.month
    while (y, m) <= (ly, lm):
        months.append(f"{m:02d}{y:04d}")
        y, m = _month_add(y, m, 1)
    return ScanWindow(from_date, to_date, tuple(months),
                      tuple(range(earliest, latest + 1)))


def window_of(document_date: Any, *, as_of: date,
              filed_by_fy: dict[str, date]) -> Optional[dict]:
    """§16(4)'s window for a document dated `document_date`, or None where the
    date cannot be read. The GSTR-9 date is looked up under the document's OWN
    year, one per FY — the periods of one scan straddle two years, and a single
    date applied to both would shorten the wrong one."""
    d = _parse(document_date)
    if d is None:
        return None
    period = _period_of(d)
    return cw.window_for(period, as_of=as_of,
                         annual_return_filed_on=filed_by_fy.get(cw.fy_label(period)))


def _row(kind: str, win: dict, **fields) -> dict:
    return {
        "kind": kind,
        "closes_on": win["closes_on"],
        "days_left": win["days_left"],
        "status": win["status"],
        "financial_year": win["financial_year"],
        "shortened_by_annual_return": win["shortened_by_annual_return"],
        **fields,
    }


def withheld_rows(verdicts: Iterable[rule_36_4.DocumentVerdict],
                  bill_dates: dict[str, str], *, as_of: date,
                  filed_by_fy: dict[str, date]) -> tuple[list[dict], int, int]:
    """(radar rows, bills the portal itself blocked, bills nobody has asked yet).

    `bill_dates` is `{bill id: bill_date}` — the verdict names the bill and the
    bill carries the date §16(4) is measured from.
    """
    rows: list[dict] = []
    blocked = 0
    unexamined = 0
    for v in verdicts:
        if v.verdict == rule_36_4.BLOCKED_BY_2B and v.withheld_total_paise > 0:
            blocked += 1
            continue
        if v.verdict == rule_36_4.NOT_ASSESSED:
            unexamined += 1
            continue
        if v.verdict not in RESCUABLE_VERDICTS or v.withheld_total_paise <= 0:
            continue
        bill_date = bill_dates.get(str(v.document_id or ""))
        win = window_of(bill_date, as_of=as_of, filed_by_fy=filed_by_fy)
        if win is None:
            continue
        rows.append(_row(
            KIND_WITHHELD, win,
            document_id=v.document_id, label=v.label, supplier=v.supplier,
            document_date=str(bill_date)[:10], verdict=v.verdict, reason=v.reason,
            credit_at_risk_paise=v.withheld_total_paise))
    return rows, blocked, unexamined


def not_booked_rows(records: Iterable[dict], *, as_of: date,
                    filed_by_fy: dict[str, date]) -> list[dict]:
    """Documents the supplier furnished and the books have no bill for.

    Invoices and debit notes only — §16(4) is "an invoice or debit note", and a
    credit note reduces credit rather than being any. An import is a bill of
    entry and is neither. A document 2B marks ITC-unavailable is not offered
    (the same reasoning as a blocked bill), and a document with no credit in it
    is nothing to lose.
    """
    rows: list[dict] = []
    for r in records:
        if (r.get("document_type") or "") not in ("invoice", "debit_note"):
            continue
        if (r.get("itc_available") or "").strip().upper() == "N":
            continue
        credit = sum(int(r.get(k) or 0) for k in
                     ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise"))
        if credit <= 0:
            continue
        win = window_of(r.get("invoice_date"), as_of=as_of, filed_by_fy=filed_by_fy)
        if win is None:
            continue
        rows.append(_row(
            KIND_NOT_BOOKED, win,
            document_id=None, label=str(r.get("invoice_number") or ""),
            supplier=str(r.get("supplier_name") or r.get("supplier_gstin") or ""),
            supplier_gstin=str(r.get("supplier_gstin") or ""),
            document_date=str(r.get("invoice_date") or "")[:10],
            return_period=str(r.get("return_period") or ""),
            verdict="not_booked",
            reason=("The supplier furnished this document and GSTR-2B "
                    "communicates it, and the books hold no bill for it. The "
                    "credit is available and is not being claimed — book it, "
                    "or it lapses on the date shown."),
            credit_at_risk_paise=credit))
    return rows


def unreconciled_rows(months: Iterable[str], *, as_of: date,
                      filed_by_fy: dict[str, date]) -> list[dict]:
    """The months in the scan with no GSTR-2B reconciliation, each with the date
    credit on its invoices lapses. A month with nothing reconciled has had
    §16(2)(aa) asked of nothing, so no bill in it is judged — and none is
    called safe."""
    out = []
    for period in months:
        win = cw.window_for(
            period, as_of=as_of,
            annual_return_filed_on=filed_by_fy.get(cw.fy_label(period)))
        if win is None:
            continue
        out.append({
            "period": period, "financial_year": win["financial_year"],
            "closes_on": win["closes_on"], "days_left": win["days_left"],
            "status": win["status"],
            "shortened_by_annual_return": win["shortened_by_annual_return"],
        })
    out.sort(key=lambda r: (r["closes_on"], _sort_period(r["period"])))
    return out


def _sort_period(period: str) -> tuple[int, int]:
    """MMYYYY as (year, month). The raw string sorts '012026' before '062025'."""
    return (int(period[2:]), int(period[:2]))


def radar(items: list[dict], *, unreconciled: list[dict], blocked: int,
          unexamined: int, as_of: date, scanned_fys: Iterable[str]) -> dict:
    """The answer: the rows nearest-lapse first, and the figures that summarise them.

    Sorted by the date credit lapses, then the larger credit first, then the
    older document — so the first row is the one whose loss is nearest and
    biggest. The sort is TOTAL (the last key is the label), so the same register
    reads the same on every call.
    """
    rows = sorted(items, key=lambda r: (
        r["closes_on"], -int(r["credit_at_risk_paise"]),
        r.get("document_date") or "", r.get("label") or ""))

    def total(status: Optional[str] = None) -> int:
        return sum(int(r["credit_at_risk_paise"]) for r in rows
                   if status is None or r["status"] == status)

    years: dict[str, dict] = {}
    for r in rows:
        y = years.setdefault(r["financial_year"], {
            "financial_year": r["financial_year"], "closes_on": r["closes_on"],
            "days_left": r["days_left"], "status": r["status"],
            "shortened_by_annual_return": r["shortened_by_annual_return"],
            "count": 0, "credit_at_risk_paise": 0})
        y["count"] += 1
        y["credit_at_risk_paise"] += int(r["credit_at_risk_paise"])

    notes = [MATCHING_IS_PER_MONTH]
    if blocked:
        notes.append(f"{blocked} bill(s): " + BLOCKED_IS_NOT_A_DEADLINE)
    if unexamined:
        notes.append(f"{unexamined} bill(s): " + NOT_ASSESSED_IS_NOT_AT_RISK)
    if unreconciled:
        notes.append(
            f"{len(unreconciled)} month(s) in this window have no GSTR-2B "
            f"reconciled, so no bill in them has been checked against what the "
            f"supplier furnished. Their credit lapses on the dates listed.")

    return {
        "as_of": as_of.isoformat(),
        "scanned_financial_years": list(scanned_fys),
        "rule": ("CGST Act §16(4): credit cannot be availed after 30 November "
                 "following the financial year the invoice pertains to, or the "
                 "annual return, whichever is earlier."),
        "items": rows,
        "by_financial_year": sorted(years.values(), key=lambda y: y["closes_on"]),
        "periods_not_reconciled": unreconciled,
        "blocked_by_2b_count": blocked,
        "not_assessed_count": unexamined,
        "totals": {
            "credit_at_risk_paise": total(),
            "open_paise": total(cw.OPEN),
            "closing_soon_paise": total(cw.CLOSING_SOON),
            "lapsed_paise": total(cw.CLOSED),
        },
        "closing_soon_days": cw.CLOSING_SOON_DAYS,
        "notes": notes,
    }


"""The stored nightly results of the three exception engines the morning digest
could not cover (POST-A-050).

WHY THESE ARE STORED
    `domain/practice/digest` names on every answer that GSTR-2B, near-duplicate
    bills and recurring-journal suggestions had no stored result, and that
    computing them for every client on every page load would read each client's
    purchase register or three months of every posted entry: a read proportional
    to transaction volume, which the reporting rule forbids. The nightly books
    check already loads each client's posted ledger and runs for every client,
    so it computes these three there and stores ONE ROW PER (CLIENT, ENGINE) in
    `nightly_exception_results` (migration 660). The digest reads those rows.

THE FOURTH ENGINE IS NOT HERE, AND SAYS SO
    Rule 37A (a supplier that did not file its GSTR-3B) needs a fact this
    product does not hold: GSTR-2B is generated from filed GSTR-1s and proves
    nothing about the 3B (`domain/gst/rule_37a`). There is no result to store,
    so no row is ever written for it and the digest keeps naming it as not
    covered.

A ROW HAS TWO STATES, AND THE SECOND IS NEVER A ZERO
    `computed` — the engine looked and this is its count (which may be a true
    zero: it looked and found nothing). `not_computed` — it could not look
    (no GSTR-2B reconciled in the window, or a read failed); `count` is NULL and
    `reason` says why. A digest that printed "0 bills missing in 2B" for a client
    whose 2B was never reconciled would tell a CA their credit is safe on the
    strength of nothing, the `table_4a_gaps` discipline applied to a stored row.
    A zero is a zero only when EVERYTHING it speaks for was looked at: a GSTR-2B
    zero from a window where some month whose credit can still be claimed has no
    reconciliation, or where bills were recorded after their month was
    reconciled, is `not_computed` too, because those bills were never checked. A
    count above zero from such a window is kept (what it found is real) and the
    unchecked months and bills are in the details, which the digest reads to say
    the figure is partial (`left_unchecked`).

Pure: no database, no clock beyond the date the caller passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from domain.gst import correction_window as cw
from domain.gst import itc_time_bar as bar
from domain.purchases import near_duplicate

GSTR_2B = "gstr_2b"
DUPLICATE_BILLS = "duplicate_bills"
RECURRING_JOURNALS = "recurring_journals"

#: Every engine a row can name. Pinned to migration 660's CHECK by a test, so a
#: kind added here without the SQL (or the reverse) fails instead of being
#: refused by the database at midnight.
ENGINES: tuple[str, ...] = (GSTR_2B, DUPLICATE_BILLS, RECURRING_JOURNALS)

COMPUTED, NOT_COMPUTED = "computed", "not_computed"
STATUSES: tuple[str, ...] = (COMPUTED, NOT_COMPUTED)

#: How far back the duplicate-bill scan reads bills. Ninety days: a supplier
#: invoice is keyed within days of arriving (`near_duplicate.DEFAULT_WINDOW_DAYS`
#: is a week), so a pair a quarter apart is not one bill entered twice, and an
#: older pair has been through a return. A heuristic choice, not a limit of law,
#: stated here and in the row's details.
DUPLICATE_SCAN_DAYS = 90

#: At most this many examples are kept in a row's details, so a row stays small
#: however many pairs there are; the count is always over all of them.
MAX_EXAMPLES = 5


@dataclass(frozen=True)
class Result:
    engine: str
    status: str
    count: Optional[int] = None
    amount_paise: Optional[int] = None
    reason: Optional[str] = None
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        assert self.engine in ENGINES and self.status in STATUSES
        if self.status == COMPUTED:
            assert self.count is not None and self.reason is None
        else:
            assert self.count is None and self.amount_paise is None and self.reason


def not_computed(engine: str, reason: str, **details: Any) -> Result:
    return Result(engine, NOT_COMPUTED, reason=reason, details=details)


# ── GSTR-2B / ITC ────────────────────────────────────────────────────────────

#: A statement of what the count is, kept with the row so a screen cannot word
#: it as more.
GSTR_2B_BASIS = (
    "Bills the books hold that no GSTR-2B document matched (or that the portal "
    "marks credit-unavailable on a sum still claimable), and GSTR-2B documents "
    "the books have no bill for, in the months whose 2B was reconciled, with "
    "§16(4)'s date not yet passed. Rule 37A is not included.")


def from_itc_radar(radar: dict, *, window_months: int) -> Result:
    """The §16(4) radar's answer as one stored row.

    `radar` is `services/itc_time_bar_service.radar`'s dict. The count is the
    rows whose credit can still be claimed (open or closing soon); credit whose
    date has already passed is kept in the details and not counted as something
    to act on, because nothing can be done about it but know it.

    What was NOT checked is counted the same way: a month with no GSTR-2B
    reconciled whose credit can still be claimed (a month whose date has passed
    is left out, as its credit is), and the bills recorded after their month was
    reconciled, which §16(2)(aa) has not been asked of. With either present and
    nothing found, the answer is not a zero but `not_computed`."""
    periods = radar.get("periods_not_reconciled") or []
    unreconciled = len(periods)
    reconciled = window_months - unreconciled
    if reconciled <= 0:
        return not_computed(
            GSTR_2B,
            "No GSTR-2B has been reconciled for any month the §16(4) radar scans, "
            "so no bill has been checked against what suppliers furnished.",
            months_scanned=window_months)
    # A period the radar could not date is counted as still open: the direction
    # that cannot call an unchecked month clear.
    months_unchecked = sum(1 for p in periods
                           if not isinstance(p, dict) or p.get("status") != cw.CLOSED)
    not_assessed = int(radar.get("not_assessed_count") or 0)
    live = [r for r in radar.get("items") or []
            if r.get("status") in (cw.OPEN, cw.CLOSING_SOON)]
    if not live and (months_unchecked or not_assessed):
        parts = []
        if months_unchecked:
            parts.append(f"{months_unchecked} month(s) whose credit can still be claimed "
                         "have no GSTR-2B reconciled")
        if not_assessed:
            parts.append(f"{not_assessed} bill(s) were recorded after their month's "
                         "GSTR-2B was reconciled")
        return not_computed(
            GSTR_2B,
            "Nothing was found in what was checked, but " + " and ".join(parts)
            + ", so those bills have not been checked against what suppliers furnished.",
            months_scanned=window_months, months_not_reconciled=unreconciled,
            months_unchecked=months_unchecked, not_assessed=not_assessed)
    lapsed = [r for r in radar.get("items") or [] if r.get("status") == cw.CLOSED]
    return Result(
        GSTR_2B, COMPUTED, count=len(live),
        amount_paise=sum(int(r.get("credit_at_risk_paise") or 0) for r in live),
        details={
            "basis": GSTR_2B_BASIS,
            "months_scanned": window_months,
            "months_not_reconciled": unreconciled,
            "months_unchecked": months_unchecked,
            "bills_not_in_2b": sum(1 for r in live if r.get("kind") == bar.KIND_WITHHELD),
            "documents_not_booked": sum(1 for r in live if r.get("kind") == bar.KIND_NOT_BOOKED),
            "closing_soon": sum(1 for r in live if r.get("status") == cw.CLOSING_SOON),
            "lapsed_count": len(lapsed),
            "lapsed_paise": sum(int(r.get("credit_at_risk_paise") or 0) for r in lapsed),
            "blocked_by_2b": int(radar.get("blocked_by_2b_count") or 0),
            "not_assessed": not_assessed,
            "examples": [{"label": r.get("label"), "supplier": r.get("supplier"),
                          "closes_on": r.get("closes_on"),
                          "credit_at_risk_paise": r.get("credit_at_risk_paise")}
                         for r in live[:MAX_EXAMPLES]],
        })


def left_unchecked(row: dict) -> bool:
    """Whether a stored COMPUTED row's count speaks for less than the whole
    window: a GSTR-2B row whose details name an unchecked month or bill. The
    other engines read everything they count, so they never are. A row without
    its details answers False, which a reader must not take as "fully checked"
    unless it asked for the details."""
    if row.get("engine") != GSTR_2B or row.get("status") != COMPUTED:
        return False
    details = row.get("details") or {}
    return bool(int(details.get("months_unchecked") or 0)
                or int(details.get("not_assessed") or 0))


# ── near-duplicate bills ─────────────────────────────────────────────────────

DUPLICATE_BASIS = (
    f"Pairs of live bills from one supplier, dated within the last "
    f"{DUPLICATE_SCAN_DAYS} days, that share an amount within "
    f"{near_duplicate.DEFAULT_WINDOW_DAYS} days or an invoice number written two ways. "
    "Two lawful bills can look alike (a retainer split across cost centres), so each "
    "is a pair to look at, never a duplicate proved.")


def duplicate_scan_start(today: date) -> date:
    return today - timedelta(days=DUPLICATE_SCAN_DAYS)


def duplicate_bill_pairs(bills: Iterable[dict]) -> Result:
    """Pairs among `bills` (rows with `id, vendor_id, bill_no, bill_date,
    total_paise, status, deleted_at`), each pair once, by the rule the bill form
    uses (`domain/purchases/near_duplicate`).

    A bill with no supplier is not compared (two bills of different suppliers
    for one amount is ordinary) and is counted in the details. A pair is
    measured at its LATER bill, the one that would be the second booking: the
    amount is the sum of those bills' totals, which is what would be counted
    twice."""
    by_vendor: dict[str, list[dict]] = {}
    no_supplier = 0
    for b in bills:
        vendor = b.get("vendor_id")
        if not vendor:
            no_supplier += 1
            continue
        by_vendor.setdefault(str(vendor), []).append(b)

    pairs = 0
    later_ids: dict[str, int] = {}
    examples: list[dict] = []
    for group in by_vendor.values():
        group.sort(key=lambda b: (str(b.get("bill_date") or ""), str(b.get("id") or "")))
        for i, bill in enumerate(group):
            found = near_duplicate.near_duplicates(
                bill_no=bill.get("bill_no"), bill_date=bill.get("bill_date"),
                total_paise=int(bill.get("total_paise") or 0), existing=group[:i])
            for n in found:
                pairs += 1
                later_ids[str(bill.get("id"))] = int(bill.get("total_paise") or 0)
                if len(examples) < MAX_EXAMPLES:
                    examples.append({"bill_no": bill.get("bill_no"),
                                     "other_bill_no": n.bill_no, "reason": n.reason,
                                     "total_paise": int(bill.get("total_paise") or 0)})
    return Result(
        DUPLICATE_BILLS, COMPUTED, count=pairs, amount_paise=sum(later_ids.values()),
        details={"basis": DUPLICATE_BASIS, "scan_days": DUPLICATE_SCAN_DAYS,
                 "bills_scanned": sum(len(g) for g in by_vendor.values()),
                 "bills_without_supplier": no_supplier,
                 "bills_in_a_pair": len(later_ids), "examples": examples})


# ── recurring journal entries missing this month ─────────────────────────────

RECURRING_BASIS = (
    "Patterns of posted entries (the same client, narration and accounts) seen in at least "
    "two earlier months of the last three and not yet this month. It says an entry looks "
    "due, not that it is owed: a seasonal entry or a repaid loan is suggested too.")


def from_recurring_suggestions(suggestions: list[dict], *, month: str) -> Result:
    ranked = sorted(suggestions, key=lambda s: (-int(s.get("occurrences") or 0),
                                                str(s.get("narration") or "")))
    return Result(
        RECURRING_JOURNALS, COMPUTED, count=len(suggestions),
        details={"basis": RECURRING_BASIS, "month": month,
                 "examples": [{"narration": s.get("narration"),
                               "occurrences": s.get("occurrences")}
                              for s in ranked[:MAX_EXAMPLES]]})

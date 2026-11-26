"""Four exceptions read off the posted ledger, each a reason to look and none a
verdict (POST-A-090).

WHAT THIS IS
    The nightly books check (`services/reconciliation_service`) asserts
    invariants — debits equal credits, a sub-ledger foots to its control
    account — and `ledger_anomalies` adds three account-level heuristics. This
    module adds four ENTRY-level ones, each tied to a consequence a CA answers
    for, and each filed as a WARNING with its innocent reading beside the
    guilty one:

      * ROUND_FIGURE_JOURNAL — a one-off manual journal for a large round sum.
        Guilty: a figure written to reach a target rather than taken from a
        document. Innocent: a provision, an estimate, a loan or capital agreed
        in round figures.
      * SUNDAY_JOURNAL — a manual journal dated on a Sunday, for a client whose
        own documents are almost never dated on one. Guilty: an entry made
        outside the ordinary course, which SA 240 tells an auditor to test.
        Innocent: somebody catching up at the weekend, or a date mistyped.
        A journal dated on the FIRST or LAST day of a month is not tested: a
        month-end or year-end accrual or provision is dated on the period's
        last day, and its reversal on the next period's first, whatever day of
        the week that is, so the Sunday there says nothing about when the work
        was done.
      * DEPARTED_MEMBER_ENTRY — an entry that names as its maker a member who
        was suspended BEFORE it was made. Guilty: a departed person's identity
        still in use. Innocent: a recurring template or a scheduled job they
        set up, which goes on posting under their name.
      * RECEIPTS_RISE_OUTPUT_TAX_FALLS — money received rose while the output
        tax charged on sales fell, quarter on quarter. Guilty: sales received
        and never billed, so no tax was charged. Innocent: earlier billing
        being collected, a loan or capital received, an advance for a later
        supply, or exempt or zero-rated sales that carry no output tax.

EACH STAYS QUIET ON THE ORDINARY CASE, and how is the point of the module:
    the round figure must be large AND one-off (a narration and account set
    that recurs in another month is a recurring entry, not a target); the
    Sunday test needs enough of the client's own documents to judge from,
    stands down for a client that trades on Sundays and leaves out a journal
    dated on a month's first or last day; the departed member needs
    a recorded suspension instant and an entry made after it; and the receipts
    test needs a quarter of output tax to fall from and both movements past a
    stated share. Every threshold here is a HEURISTIC chosen for this module —
    none is a rate, limit or date of law, and each says why it is what it is.

WHAT IT DOES NOT DO
    It does not read the documents behind an entry, so it cannot tell a round
    provision supported by a valuation from one that is not; it does not know
    the client's working week or holidays (Saturday is a working day for much
    of Indian business and is deliberately not tested); it has no departure
    date for a member who was never suspended in this product; and the
    receipts test cannot see a sale billed as exempt, so it names that reading
    rather than ruling it out.

Pure: no database, no clock beyond the `as_of` the caller passes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from domain.accounting import journal_source

ROUND_FIGURE_JOURNAL = "journal_round_figure"
SUNDAY_JOURNAL = "journal_dated_on_a_sunday"
DEPARTED_MEMBER_ENTRY = "entry_made_after_its_maker_was_suspended"
RECEIPTS_RISE_OUTPUT_TAX_FALLS = "receipts_rise_while_output_tax_falls"

ALL_KINDS: tuple[str, ...] = (
    ROUND_FIGURE_JOURNAL, SUNDAY_JOURNAL, DEPARTED_MEMBER_ENTRY,
    RECEIPTS_RISE_OUTPUT_TAX_FALLS)

#: How far back the three entry-level tests look. A year: an entry older than
#: that has normally been through a year-end and its review, and repeating it
#: every night would bury this year's.
RECENT_MONTHS = 12

#: A round figure is a multiple of ₹10,000 ...
ROUND_UNIT_PAISE = 10_000_00
#: ... of at least ₹1,00,000. Smaller round sums (a ₹5,000 petty-cash top-up,
#: a ₹20,000 rent) are the ordinary texture of a manual journal and would fire
#: on nearly every client.
ROUND_FLOOR_PAISE = 1_00_000_00

#: The Sunday test needs at least this many of the client's own DOCUMENT
#: entries (not manual journals) in the window to judge its working week from.
MIN_DOCUMENT_ENTRIES = 20
#: ... and stands down when one document entry in this many or more is dated on
#: a Sunday (5%): a shop, a hotel, a clinic trades on Sundays and a Sunday
#: journal there is ordinary.
SUNDAY_TRADING_ONE_IN = 20

#: The receipts test compares the last three COMPLETE calendar months with the
#: three before them. A quarter rather than a month because a single month's
#: billing and collection are routinely out of step.
WINDOW_MONTHS = 3
#: Both movements must exceed a quarter (25%): output tax down by at least a
#: quarter AND money received up by at least a quarter ...
SHIFT_NUMERATOR, SHIFT_DENOMINATOR = 1, 4
#: ... and the rise in money received must be at least ₹1,00,000, so a client
#: whose receipts went from ₹20,000 to ₹30,000 is not called out.
RECEIPTS_RISE_FLOOR_PAISE = 1_00_000_00

#: Entry sources whose output tax is tax charged ON A SALE. A reverse-charge
#: purchase also credits output tax and is not a sale, and a GST payment debits
#: it; neither belongs in "output tax fell".
SALES_SIDE_SOURCES: frozenset[str] = frozenset({
    journal_source.SALES_INVOICE, journal_source.CREDIT_NOTE,
    journal_source.SALES_DEBIT_NOTE})

NOT_CHECKED: tuple[str, ...] = (
    "Whether a round manual journal has a document behind it: the check reads "
    "the ledger, not the papers.",
    "Saturdays and public holidays: Saturday is a working day for much of Indian "
    "business, and no holiday calendar is held.",
    "A manual journal dated on the first or last day of a month, on a Sunday: a "
    "month-end or year-end accrual is dated on the period's last day and its "
    "reversal on the next period's first, so the day of the week says nothing there.",
    "Entries by a member who left without being suspended in this product: there "
    "is no departure date to compare with.",
    "Sales billed as exempt or zero-rated, which carry no output tax: the receipts "
    "test names that reading and cannot rule it out.",
)


@dataclass(frozen=True)
class Exception_:
    """One thing to look at. `entry_id` is None for the receipts test, which is
    about a quarter rather than an entry."""
    kind: str
    summary: str
    also_could_be: str
    amount_paise: Optional[int]
    entry_id: Optional[str] = None
    entry_date: Optional[str] = None
    reference_no: Optional[str] = None
    details: Optional[dict] = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _month_start(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def window_start(as_of: date) -> date:
    """First day of the month RECENT_MONTHS - 1 months before `as_of`'s month."""
    return _month_start(_month_index(as_of) - (RECENT_MONTHS - 1))


def _date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        # Not a date. A DATE or timestamp column always reads back as ISO text, so a stored one never lands here: this is an absent value or text that
        # was never a date, and None says there is none.
        return None


def _instant(value) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        got = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Not a timestamp. A timestamptz column always reads back as ISO text, so a stored instant never lands here: this is an absent value or a
        # hand-built one, and None says there is no instant.
        return None
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def _is_period_boundary(d: date) -> bool:
    """The first or last day of a calendar month: a date an accrual, a provision
    or its reversal takes from the period it belongs to, not from the day the
    entry was keyed."""
    return d.day == 1 or (d + timedelta(days=1)).day == 1


def _debit_total(entry) -> int:
    return sum(int(ln.debit_paise) for ln in entry.lines)


def _pattern(entry) -> tuple:
    return ((entry.narration or "").strip().lower(),
            tuple(sorted({ln.account_id for ln in entry.lines})))


def _reversed_pairs(entries) -> set[str]:
    """Ids of every entry that reverses another and every entry reversed: a pair
    nets to nothing and is a correction, not a figure."""
    out: set[str] = set()
    for e in entries:
        if e.reversal_of:
            out.add(str(e.id))
            out.add(str(e.reversal_of))
    return out


def _recent_manual(entries, as_of: date) -> list:
    start = window_start(as_of)
    skip = _reversed_pairs(entries)
    out = []
    for e in entries:
        d = _date(e.entry_date)
        if (e.source_type == journal_source.MANUAL and d is not None
                and start <= d <= as_of and str(e.id) not in skip):
            out.append(e)
    return out


# ── the tests ────────────────────────────────────────────────────────────────

def round_figure_journals(entries: Iterable, *, as_of: date) -> list[Exception_]:
    entries = list(entries)
    months_by_pattern: dict[tuple, set[str]] = {}
    for e in entries:
        months_by_pattern.setdefault(_pattern(e), set()).add(str(e.entry_date)[:7])
    out = []
    for e in _recent_manual(entries, as_of):
        total = _debit_total(e)
        if total < ROUND_FLOOR_PAISE or total % ROUND_UNIT_PAISE:
            continue
        if len(months_by_pattern.get(_pattern(e), ())) > 1:
            continue                        # recurs in another month: not one-off
        out.append(Exception_(
            ROUND_FIGURE_JOURNAL,
            "A one-off manual journal for a round sum. Check it was taken from a "
            "document and not written to reach a figure.",
            "It may be a provision, an estimate, or a loan or capital agreed in "
            "round figures, which is ordinary when the working is on file.",
            amount_paise=total, entry_id=str(e.id), entry_date=str(e.entry_date)[:10],
            reference_no=e.reference_no))
    return out


def sunday_journals(entries: Iterable, *, as_of: date) -> list[Exception_]:
    entries = list(entries)
    start = window_start(as_of)
    documents = sundays = 0
    for e in entries:
        d = _date(e.entry_date)
        if d is None or not (start <= d <= as_of):
            continue
        if e.source_type in journal_source.ENTRY_IS_THE_RECORD or not e.source_type:
            continue
        documents += 1
        if d.weekday() == 6:
            sundays += 1
    if documents < MIN_DOCUMENT_ENTRIES or sundays * SUNDAY_TRADING_ONE_IN >= documents:
        return []
    out = []
    for e in _recent_manual(entries, as_of):
        d = _date(e.entry_date)
        if d is None or d.weekday() != 6 or _is_period_boundary(d):
            continue
        out.append(Exception_(
            SUNDAY_JOURNAL,
            f"A manual journal dated on a Sunday, for a client whose documents are "
            f"dated on a Sunday {sundays} times in {documents}. Check who made it "
            f"and why it is dated outside the ordinary week.",
            "It may be somebody catching up at the weekend, or a date typed wrongly.",
            amount_paise=_debit_total(e), entry_id=str(e.id),
            entry_date=str(e.entry_date)[:10], reference_no=e.reference_no,
            details={"document_entries": documents, "document_entries_on_sunday": sundays}))
    return out


def departed_member_entries(rows: Iterable[dict], members: Iterable[dict]) -> list[Exception_]:
    """`rows`: journal entries naming a maker (`id, entry_date, created_at,
    created_by, reference_no, amount_paise`). `members`: `users` rows (`id,
    is_active, sessions_revoked_at`). Only a member explicitly suspended
    (`is_active` False) with a recorded revocation instant counts: that instant
    is when `suspend_user` cut them off."""
    cut_off: dict[str, datetime] = {}
    for m in members:
        if m.get("is_active") is False:
            when = _instant(m.get("sessions_revoked_at"))
            if when is not None:
                cut_off[str(m["id"])] = when
    out = []
    for r in rows:
        when = cut_off.get(str(r.get("created_by") or ""))
        made = _instant(r.get("created_at"))
        if when is None or made is None or made <= when:
            continue
        out.append(Exception_(
            DEPARTED_MEMBER_ENTRY,
            "An entry names as its maker a member who had been suspended before it "
            "was made. Check whose hand it was.",
            "It may come from a recurring template or a scheduled job that member "
            "set up, which goes on posting under their name.",
            amount_paise=int(r.get("amount_paise") or 0) or None,
            entry_id=str(r.get("id")), entry_date=str(r.get("entry_date") or "")[:10],
            reference_no=r.get("reference_no"),
            details={"made_at": str(r.get("created_at")),
                     "member_suspended_at": when.isoformat()}))
    return out


def monthly_receipts_and_output_tax(entries: Iterable, *, money_accounts: set[str],
                                    output_accounts: set[str]) -> tuple[dict, dict]:
    """({month: money received}, {month: output tax charged on sales}).

    Money received is the debit to bank and cash on an entry that credits no
    bank or cash account (a transfer between the client's own accounts is not a
    receipt). Output tax is the net credit to the output-tax accounts on a sales
    document (`SALES_SIDE_SOURCES`)."""
    receipts: dict[str, int] = {}
    output: dict[str, int] = {}
    for e in entries:
        month = str(e.entry_date)[:7]
        if not any(ln.account_id in money_accounts and ln.credit_paise for ln in e.lines):
            got = sum(int(ln.debit_paise) for ln in e.lines if ln.account_id in money_accounts)
            if got:
                receipts[month] = receipts.get(month, 0) + got
        if e.source_type in SALES_SIDE_SOURCES:
            tax = sum(int(ln.credit_paise) - int(ln.debit_paise)
                      for ln in e.lines if ln.account_id in output_accounts)
            if tax:
                output[month] = output.get(month, 0) + tax
    return receipts, output


def receipts_against_output_tax(receipts: dict, output: dict, *, as_of: date) -> list[Exception_]:
    last_complete = _month_index(as_of) - 1
    recent = [_month_start(i).strftime("%Y-%m") for i in
              range(last_complete - WINDOW_MONTHS + 1, last_complete + 1)]
    prior = [_month_start(i).strftime("%Y-%m") for i in
             range(last_complete - 2 * WINDOW_MONTHS + 1, last_complete - WINDOW_MONTHS + 1)]
    r_now = sum(receipts.get(m, 0) for m in recent)
    r_before = sum(receipts.get(m, 0) for m in prior)
    t_now = sum(output.get(m, 0) for m in recent)
    t_before = sum(output.get(m, 0) for m in prior)
    n, d = SHIFT_NUMERATOR, SHIFT_DENOMINATOR
    if t_before <= 0:
        return []                                     # nothing to fall from
    tax_fell = t_now * d <= t_before * (d - n)
    receipts_rose = (r_now * d >= r_before * (d + n)
                     and r_now - r_before >= RECEIPTS_RISE_FLOOR_PAISE)
    if not (tax_fell and receipts_rose):
        return []
    return [Exception_(
        RECEIPTS_RISE_OUTPUT_TAX_FALLS,
        f"Money received in {recent[0]} to {recent[-1]} rose against the three months "
        f"before, while the output tax charged on sales fell. Check that every sale "
        f"received was billed.",
        "It may be earlier billing being collected, a loan or capital received, an "
        "advance for a later supply, or exempt or zero-rated sales that carry no "
        "output tax.",
        amount_paise=r_now - r_before,
        details={"months": recent, "months_before": prior,
                 "received_paise": r_now, "received_before_paise": r_before,
                 "output_tax_paise": t_now, "output_tax_before_paise": t_before})]

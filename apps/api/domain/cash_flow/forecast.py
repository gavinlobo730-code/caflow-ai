"""What a client's bank balance is expected to do over the next few months.

WHAT WAS THERE (3b-2). `/reports/cash-flow` was 352 lines of browser
arithmetic, and three things about it were wrong in kind rather than in detail:

  · ITS ONLY INFLOW WAS `fee_invoices` — the PRACTICE'S OWN FEE NOTES to that
    client (migration 014: `engagement_id` to `fee_engagements`, GST at 18% on
    SAC 998211, which is accounting services). So a client turning over crores
    was shown a cash-flow forecast whose entire income was the ₹25,000 a month
    they pay their accountant. Their own receivables — `client_sales_invoices`,
    with a generated `outstanding_paise` since migration 278 — did not appear.
  · ITS OPENING BALANCE WAS TYPED BY THE USER. Every closing figure on the
    report is carried forward from it, so the whole projection hung off a
    number nobody derived, on a client whose bank ledger the product holds.
  · Its only outflow was loan EMIs. No supplier payables at all.

WHAT IS HERE. The opening position comes from the LEDGER, the inflows are the
client's own open receivables and the outflows their own open payables plus
live loan EMIs, and every leg that cannot be priced is NAMED rather than
quietly left at nil. Integer paise throughout; a rupee is never a float.

THE THREE JUDGEMENTS, each of which could reasonably have gone the other way
and each of which is tested:

  1. AN OVERDUE DOCUMENT IS NOT FUTURE CASH. A receivable that fell due in
     March is not money arriving in September, and dropping it into the first
     month — the obvious thing to do with a date already past — makes the
     forecast optimistic exactly where a CA is relying on it. Overdue is
     totalled and reported APART, on both sides, and reaches no month.
  2. A DOCUMENT WITH NO DUE DATE IS NAMED, NOT BUCKETED. `due_date` is
     nullable on both tables. Deriving one from the document date plus the
     party's credit days would put real money in a month nobody agreed to,
     and a forecast is read as a claim about WHEN.
  3. A CARRIED-OVER OPENING DOCUMENT COUNTS. `domain/accounting/
     opening_documents.without_carried_over` filters these out of every
     STATUTORY output, because declaring a supply twice pays the tax twice.
     A forecast is not a statutory output: an opening receivable is money the
     client is still owed, and leaving it out understates the position. The
     reflex in this codebase is to filter, so this says not to.

WHAT IS REFUSED AND WHY, because a nil that means "we could not see it" is not
a nil that means "there is none":

  · STATUTORY OUTFLOWS ARE NOT PRICED. GST, TDS and advance tax are usually
    the largest outflows an Indian business has, and the amounts live on
    returns that exist only once a period is prepared — a return for a month
    that has not happened cannot be priced, and `compliance_calendar` carries
    the schedule with no amount at all. Pricing the months that ARE prepared
    and leaving the rest at nil would be worse than naming the whole leg: the
    forecast would dip in the two months a CA happened to have prepared and
    look clear afterwards.
  · PAYROLL IS NOT PRICED, for the same reason one month further on: a run
    that has not been created has no figures, and last month's net pay is an
    assumption about headcount rather than a fact.
  · NO SEASONALITY, NO AVERAGE-MONTH FILL. Every rupee here is a document
    somebody issued or received, with a date on it. A projection that adds a
    "typical month" is a different product and would have to say so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

#: Every expected flow names which side it is on and what kind of document it
#: came from, so the screen can total by kind without a second vocabulary.
INFLOW_KINDS = ("receivable",)
OUTFLOW_KINDS = ("payable", "loan_emi")

#: The legs this forecast does not price. Emitted on EVERY answer, because a
#: reader has to know the dip they are looking at excludes the tax.
UNPRICED_LEGS: tuple[tuple[str, str], ...] = (
    ("statutory", (
        "GST, TDS and advance tax are not in these figures. The amounts exist "
        "only once a period's return is prepared, and a return for a month "
        "that has not happened yet cannot be priced — so pricing the prepared "
        "months alone would show a dip where the CA happened to have worked "
        "ahead and a clear run afterwards."
    )),
    ("payroll", (
        "Salaries are not in these figures. A payroll run that has not been "
        "created has no amounts, and last month's net pay is an assumption "
        "about headcount rather than a fact about next month."
    )),
)

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class ExpectedFlow:
    """One document's money, on the day it is expected.

    ⚠️ `party` IS FILLED FOR A LOAN AND EMPTY FOR AN INVOICE OR A BILL, and
    that asymmetry is a fact about the tables rather than an omission:
    `loans.lender_name` exists, while `client_sales_invoices` and
    `purchase_bills` hold only `customer_id` and `vendor_id`. Naming the
    counterparty on a document would mean a second read per party for a LABEL,
    when the document's own number is what a CA uses to find it.
    """
    due_on: date
    amount_paise: int
    kind: str
    reference: str
    party: str = ""

    @property
    def is_inflow(self) -> bool:
        return self.kind in INFLOW_KINDS


@dataclass(frozen=True)
class UndatedFlow:
    """A document with money outstanding and no due date. NAMED, never guessed
    into a month — see judgement 2 in the module docstring.

    No `party`: only an invoice or a bill can be undated (a loan EMI is dated
    by construction), and neither of those tables carries a party name.
    """
    amount_paise: int
    kind: str
    reference: str


@dataclass(frozen=True)
class ForecastMonth:
    period: str            # "2026-09", sortable and unambiguous
    label: str             # "Sep 2026", for a person
    opening_paise: int
    inflows_paise: int
    outflows_paise: int
    closing_paise: int
    by_kind: dict[str, int] = field(default_factory=dict)

    @property
    def is_shortfall(self) -> bool:
        return self.closing_paise < 0


@dataclass(frozen=True)
class Forecast:
    as_at: date
    opening_paise: int
    months: list[ForecastMonth]
    overdue_in_paise: int
    overdue_out_paise: int
    undated: list[UndatedFlow]
    unpriced: list[dict]
    gaps: list[str]

    @property
    def first_shortfall(self) -> str | None:
        """The period a CA actually opened this to find."""
        for m in self.months:
            if m.is_shortfall:
                return m.period
        return None


def _period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _label_of(year: int, month_index_0: int) -> str:
    return f"{MONTHS[month_index_0]} {year}"


def month_windows(as_at: date, months: int) -> list[tuple[str, str]]:
    """`months` consecutive (period, label) pairs beginning with `as_at`'s own.

    The FIRST window is the current month and is deliberately not the whole of
    it: `bucket` only counts what falls on or after `as_at`, so an invoice that
    was due on the 3rd when today is the 20th is overdue rather than this
    month's inflow. A forecast that counts money whose date has passed is
    reporting the past as the future.
    """
    if months < 1:
        raise ValueError("a forecast covers at least one month")
    out: list[tuple[str, str]] = []
    year, m0 = as_at.year, as_at.month - 1
    for _ in range(months):
        out.append((f"{year:04d}-{m0 + 1:02d}", _label_of(year, m0)))
        m0 += 1
        if m0 == 12:
            m0, year = 0, year + 1
    return out


def build(
    *,
    as_at: date,
    opening_paise: int,
    flows: list[ExpectedFlow],
    undated: list[UndatedFlow] | None = None,
    months: int = 6,
    gaps: list[str] | None = None,
) -> Forecast:
    """Roll the expected flows into consecutive monthly buckets.

    `as_at` and `opening_paise` are both REQUIRED with no default. The date
    because a rule that reads the clock is untestable and lets two callers
    disagree about which day it is; the opening because it is the figure every
    closing balance is carried forward from, and defaulting it to nil would
    produce a plausible-looking statement of a position nobody measured —
    which is the defect this module replaces.
    """
    windows = month_windows(as_at, months)
    in_period = {p for p, _ in windows}

    inflow: dict[str, int] = {p: 0 for p in in_period}
    outflow: dict[str, int] = {p: 0 for p in in_period}
    by_kind: dict[str, dict[str, int]] = {p: {} for p in in_period}
    overdue_in = overdue_out = 0
    beyond_in = beyond_out = 0

    for f in flows:
        amount = int(f.amount_paise)
        if amount <= 0:
            # A settled or credited document reaches nothing. Not a gap: a
            # nil outstanding is a complete answer.
            continue
        if f.due_on < as_at:
            if f.is_inflow:
                overdue_in += amount
            else:
                overdue_out += amount
            continue
        period = _period_of(f.due_on)
        if period not in in_period:
            # Past the window. Counted so the answer can SAY there is money
            # beyond the horizon rather than implying the client's book ends.
            if f.is_inflow:
                beyond_in += amount
            else:
                beyond_out += amount
            continue
        if f.is_inflow:
            inflow[period] += amount
        else:
            outflow[period] += amount
        by_kind[period][f.kind] = by_kind[period].get(f.kind, 0) + amount

    rows: list[ForecastMonth] = []
    running = int(opening_paise)
    for period, label in windows:
        opening = running
        closing = opening + inflow[period] - outflow[period]
        running = closing
        rows.append(ForecastMonth(
            period=period, label=label,
            opening_paise=opening,
            inflows_paise=inflow[period],
            outflows_paise=outflow[period],
            closing_paise=closing,
            by_kind=dict(sorted(by_kind[period].items())),
        ))

    named = list(gaps or [])
    if beyond_in or beyond_out:
        named.append(
            f"Documents falling due after {windows[-1][1]} are not in these "
            f"months: ₹ in {beyond_in} paise expected, ₹ out {beyond_out} paise."
        )

    return Forecast(
        as_at=as_at,
        opening_paise=int(opening_paise),
        months=rows,
        overdue_in_paise=overdue_in,
        overdue_out_paise=overdue_out,
        undated=list(undated or []),
        unpriced=[{"leg": leg, "why": why} for leg, why in UNPRICED_LEGS],
        gaps=named,
    )


def emi_months(
    *,
    as_at: date,
    months: int,
    disbursed_on: date,
    matures_on: date | None,
) -> list[date]:
    """The forecast months in which a live loan pays an EMI.

    Walking the WINDOWS and testing each is what makes maturity bind — the
    browser version spread the EMI over every month unconditionally, so a loan
    maturing next month still showed five more payments. The comparison is on
    `year * 12 + month` so a mid-month disbursement counts for its own month
    rather than being pushed to the next.

    The day taken is the FIRST of the month, deliberately: an EMI date is a
    fact about the loan agreement and nothing here records one, so putting it
    at the month's start charges it as early as it could fall. On a shortfall
    warning, early is the direction that cannot reassure somebody wrongly.
    """
    start_idx = disbursed_on.year * 12 + (disbursed_on.month - 1)
    end_idx = (matures_on.year * 12 + (matures_on.month - 1)
               if matures_on else None)
    out: list[date] = []
    for period, _ in month_windows(as_at, months):
        year, month = int(period[:4]), int(period[5:7])
        idx = year * 12 + (month - 1)
        if idx < start_idx:
            continue
        if end_idx is not None and idx > end_idx:
            continue
        out.append(date(year, month, 1))
    return out

"""MSMED §16 — what a buyer owes a micro or small supplier for paying late.

⚠️ EVERY SECTION AND EVERY PERIOD HERE IS `[S]`-GRADED. Direct egress is
refused at this environment's proxy, so none of it was read off the Act; each
constant is pinned exactly by
`tests/test_what_paying_a_small_supplier_late_costs.py` so a later correction
is a deliberate edit rather than a drift.

WHAT §16 CHARGES, AND WHY IT IS NOT §43B(h) AGAIN

    §43B(h) is about a DEDUCTION: it moves the expense into the year the sum is
    actually paid. `domain/income_tax/section_43b_h.py` is that rule, and it
    answers a question about the buyer's own taxable income.

    §16 is about a DEBT. It says that where a buyer fails to pay as §15
    requires, the buyer

        "shall, NOTWITHSTANDING anything contained in any agreement between the
         buyer and the supplier or in any law for the time being in force, be
         liable to pay COMPOUND INTEREST WITH MONTHLY RESTS to the supplier on
         that amount from the appointed day or, as the case may be, from the
         date immediately following the date agreed upon, at THREE TIMES OF THE
         BANK RATE notified by the Reserve Bank."

    So it is money the client owes a third party, it cannot be contracted out
    of, and it accrues whether or not anybody raises an invoice for it. A
    working that reports the disallowance and says nothing about the interest
    reports the smaller of the two numbers.

THREE THINGS THE SECTION SETTLES THAT ARE EASY TO GET WRONG

  * **MONTHLY RESTS, not simple interest.** Over a year at a 6.75% bank rate
    the charge is 20.25% nominal; compounded monthly it is about 22.2%. Simple
    interest understates it, and the understatement grows with the delay — so
    it is worst exactly where the exposure matters most.
  * **THE CLOCK STARTS AT THE APPOINTED DAY**, not at the bill date and not at
    the date payment was eventually made. That is the same date §43B(h) already
    computes, so this module TAKES it rather than restating §15 — one
    definition of when a payment became late, used by both.
  * **THREE TIMES the bank rate**, which is the RBI's own Bank Rate and NOT the
    repo rate, the MCLR or any lending rate. They differ, and tripling the
    wrong one is wrong by a multiple.

§23 MAKES THE INTEREST NON-DEDUCTIBLE, WHICH IS THE PART A CA CAN MISS

    "Notwithstanding anything contained in the Income-tax Act, the amount of
    interest payable or paid by any buyer, under or in accordance with the
    provisions of this Act, shall not, for the purposes of the computation of
    income under the Income-tax Act, be allowed as a deduction."

    So the interest is added back IN FULL and, unlike §43B(h), paying it never
    releases it. The two add-backs are therefore INDEPENDENT and are reported
    separately: §43B(h) defers a deduction, §23 denies one outright.

THE RATE IS REFUSED, NOT GUESSED, AND THAT IS THE WHOLE DESIGN

    The RBI Bank Rate moves by notification, partway through a year, and a
    delay spanning a change is governed by more than one rate. This module
    therefore takes the rate as an INPUT and `interest_refusal` returns a
    sentence when none is recorded, the shape `domain/payroll/perquisites.py`
    uses for SBI's Rule 3(7)(i) rate and `public.dtaa_treaty_rates` uses for a
    treaty rate: a figure the product cannot derive is a figure a person reads
    once and records.

    Writing a rate in from memory would be unsafe in BOTH directions and by a
    factor of three: too high tells a client they owe money they do not, too
    low hides a statutory debt that is compounding. Neither is a number to
    guess at.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING
from typing import Optional

#: §16's multiplier. Not a rate — the rate is the RBI's and is an input.
BANK_RATE_MULTIPLE = 3

#: §16 says "with monthly rests", so the compounding period is a month.
RESTS_PER_YEAR = 12

#: Nothing in this repository holds the RBI Bank Rate, deliberately. See the
#: module docstring: it moves by notification and a delay can span a change.
BANK_RATE_IS_NOT_HELD = (
    "MSMED §16 charges compound interest at THREE TIMES the Reserve Bank's Bank "
    "Rate, and no Bank Rate is recorded here. It is not the repo rate and not a "
    "lending rate; it moves by RBI notification partway through a year, so a "
    "delay spanning a change is governed by more than one. Record the rate in "
    "force over the delay and this working computes the charge."
)

SECTION_23_DISALLOWS_IT = (
    "MSMED §23 denies a deduction for this interest outright — \"shall not, for "
    "the purposes of the computation of income under the Income-tax Act, be "
    "allowed as a deduction\" — so it is added back in full and, unlike "
    "§43B(h), PAYING IT NEVER RELEASES IT. The two add-backs are independent: "
    "§43B(h) defers a deduction, §23 denies one."
)

SECTION_22_DISCLOSURE = (
    "MSMED §22 requires the principal and the interest due, the interest paid "
    "and the interest still payable to be disclosed in the annual statement of "
    "accounts. This working is the source for that note; it is not the note."
)

NOTHING_IS_POSTED = (
    "Nothing here is posted. The charge is a liability to the supplier and the "
    "journal raising it is the CA's — this states what §16 charges, on what, "
    "and from when."
)


@dataclass(frozen=True)
class LateAmount:
    """One principal that missed MSMED §15, with the dates the section needs.

    `due_by` is the APPOINTED DAY and is taken from
    `section_43b_h`'s own working rather than recomputed here: when a payment
    became late has one definition and two copies of it would drift.
    """
    bill_id: str
    bill_no: Optional[str]
    vendor_name: str
    principal_paise: int
    #: The appointed day, or the day agreed in writing. Interest runs from the
    #: day AFTER it — §16 says "from the date immediately following".
    due_by: Optional[date]
    #: When the principal was settled. None means still outstanding, and the
    #: clock is still running.
    settled_on: Optional[date] = None


@dataclass(frozen=True)
class InterestOnOneAmount:
    bill_id: str
    bill_no: Optional[str]
    vendor_name: str
    principal_paise: int
    from_date: Optional[str]
    to_date: Optional[str]
    #: Whole months of delay. A part month is a rest that has not fallen due.
    months: int
    #: The days beyond the last whole month, reported and NOT charged.
    part_days: int
    annual_rate_bps: Optional[int]
    interest_paise: Optional[int]
    still_running: bool
    reason: str


@dataclass(frozen=True)
class MsmedInterestResult:
    financial_year: str
    as_at: Optional[str]
    bank_rate_bps: Optional[int]
    charged_rate_bps: Optional[int]
    interest_paise: Optional[int]
    amounts: tuple
    gaps: tuple
    caveats: tuple

    def to_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "as_at": self.as_at,
            "bank_rate_bps": self.bank_rate_bps,
            "charged_rate_bps": self.charged_rate_bps,
            "interest_paise": self.interest_paise,
            "amounts": [
                {
                    "bill_id": a.bill_id, "bill_no": a.bill_no,
                    "vendor_name": a.vendor_name,
                    "principal_paise": a.principal_paise,
                    "from_date": a.from_date, "to_date": a.to_date,
                    "months": a.months, "part_days": a.part_days,
                    "annual_rate_bps": a.annual_rate_bps,
                    "interest_paise": a.interest_paise,
                    "still_running": a.still_running,
                    "reason": a.reason,
                }
                for a in self.amounts
            ],
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
        }


def charged_rate_bps(bank_rate_bps: Optional[int]) -> Optional[int]:
    """§16's rate: three times the Bank Rate. None in, None out."""
    if bank_rate_bps is None:
        return None
    return int(bank_rate_bps) * BANK_RATE_MULTIPLE


def interest_refusal(bank_rate_bps: Optional[int]) -> Optional[str]:
    """The one place that decides whether §16 can be answered at all."""
    return None if bank_rate_bps is not None else BANK_RATE_IS_NOT_HELD


def whole_months_between(start: date, end: date) -> tuple:
    """Whole months from `start` to `end`, and the leftover days.

    A REST IS A MONTH THAT HAS FALLEN DUE. §16 compounds "with monthly rests",
    so a delay of 45 days is one rest and fifteen days of a second that has not
    arrived — charging a proportion of it would be simple interest wearing a
    compound name, and charging a whole extra rest would charge a period that
    has not elapsed.

    Counted on the CALENDAR, anniversary to anniversary, so the answer cannot
    disagree with itself across a leap year — the same arithmetic
    `advance_tax_interest_engine._months_or_part` uses for §234A, and
    deliberately NOT the calendar-month count §201(1A) is administered on.
    """
    if end <= start:
        return 0, 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months and _add_months(start, months) > end:
        months -= 1
    anniversary = _add_months(start, months) if months else start
    return months, (end - anniversary).days


def _add_months(d: date, months: int) -> date:
    """`d` plus `months`, clamped to the month's last day.

    31 January plus one month is 28 February. Clamped against the ORIGINAL day
    on every step, never against the previous one — `domain/recurrence.py`
    records why: clamping against the predecessor walks the whole series
    permanently back to the 28th after one February.
    """
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    last = _days_in_month(year, month)
    return date(year, month, min(d.day, last))


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year + (month // 12), (month % 12) + 1, 1)
            - date(year, month, 1)).days


def compound_interest_paise(principal_paise: int, annual_rate_bps: int,
                            months: int) -> int:
    """Compound interest with monthly rests, rounded UP to the paisa.

    Decimal throughout, never float: this is money one person owes another, and
    CLAUDE.md's first money rule is that a rupee calculation never touches
    floating point. The rate per rest is the annual rate divided by twelve —
    §16 names an annual rate and a monthly rest and gives no other conversion.

    ROUNDED UP, because the charge is a sum the BUYER owes and understating it
    leaves a residual debt to a small supplier the Act exists to protect. Same
    direction as ESI's contribution rounding and §50(1)'s interest, and the
    opposite of the GST discount, which floors because there flooring cannot
    under-declare tax.
    """
    if principal_paise <= 0 or months <= 0 or annual_rate_bps <= 0:
        return 0
    principal = Decimal(int(principal_paise))
    per_rest = Decimal(int(annual_rate_bps)) / Decimal(10_000) / Decimal(RESTS_PER_YEAR)
    grown = principal * (Decimal(1) + per_rest) ** months
    return int((grown - principal).to_integral_value(rounding=ROUND_CEILING))


def late_amounts(bill, outcome) -> list:
    """The amounts §16 charges on, read off the §43B(h) working.

    ONE `LateAmount` PER LATE PAYMENT, plus one for anything still unpaid.
    §16 charges "on that amount ... from the appointed day", so each tranche
    runs its own clock: a bill part-paid one month late and cleared six months
    late owes two different periods of interest, and treating it as one
    principal over the longer period over-charges while using the shorter
    under-charges.

    WHAT COUNTS AS LATE IS NOT RE-DECIDED HERE. `outcome.due_by` is
    `section_43b_h`'s answer, which already applies §15's fifteen days, the
    written agreement, the forty-five day cap and the goods receipt where one
    exists. Restating any of that would be a second definition of the same day.

    A bill the clause does not reach at all (`included` false — a medium or
    large vendor, an unclassified one, a capitalised bill, a year before the
    clause) yields NOTHING. §16 reaches only a "supplier", which MSMED §2(n)
    makes a micro or small enterprise, so the same population answers both.
    """
    if not getattr(outcome, "included", False):
        return []
    due = outcome.due_by
    if isinstance(due, str):
        due = date.fromisoformat(due)
    out: list[LateAmount] = []
    for p in getattr(bill, "payments", ()) or ():
        if p.paid_on is None or due is None or p.paid_on <= due:
            continue
        if int(p.amount_paise or 0) <= 0:
            continue
        out.append(LateAmount(
            bill_id=bill.bill_id, bill_no=bill.bill_no,
            vendor_name=bill.vendor_name,
            principal_paise=int(p.amount_paise),
            due_by=due, settled_on=p.paid_on))
    unpaid = int(getattr(outcome, "unpaid_paise", 0) or 0)
    if unpaid > 0:
        out.append(LateAmount(
            bill_id=bill.bill_id, bill_no=bill.bill_no,
            vendor_name=bill.vendor_name,
            principal_paise=unpaid, due_by=due, settled_on=None))
    return out


def compute(amounts, *, financial_year: str, bank_rate_bps: Optional[int] = None,
            as_at: Optional[date] = None) -> MsmedInterestResult:
    """What §16 charges on each late principal, or why it cannot be said.

    A REFUSED RATE STILL PRODUCES THE WORKING. Every amount comes back with its
    dates and its month count and a NULL charge, because "which bills are
    accruing interest and since when" is useful before anybody looks up a rate,
    and a screen that shows nothing until a figure is recorded teaches the CA
    the feature is broken.
    """
    refusal = interest_refusal(bank_rate_bps)
    rate = charged_rate_bps(bank_rate_bps)
    today = as_at or date.today()

    rows: list[InterestOnOneAmount] = []
    gaps: list[str] = []
    total: Optional[int] = None if refusal else 0

    for a in amounts:
        if a.due_by is None:
            gaps.append(
                f"{a.vendor_name} — {a.bill_no or a.bill_id}: no appointed day "
                f"could be computed, so §16's clock has no start. The charge is "
                f"not stated rather than run from the bill date.")
            rows.append(InterestOnOneAmount(
                bill_id=a.bill_id, bill_no=a.bill_no, vendor_name=a.vendor_name,
                principal_paise=a.principal_paise, from_date=None, to_date=None,
                months=0, part_days=0, annual_rate_bps=rate,
                interest_paise=None, still_running=False,
                reason="No appointed day recorded — MSMED §16 has no start date."))
            continue

        # "from the date immediately following" — §16's own words, so the day
        # the payment became late is not itself a day of delay.
        start = _add_days(a.due_by, 1)
        end = a.settled_on or today
        still_running = a.settled_on is None
        months, part_days = whole_months_between(start, end)
        charge = None if refusal else compound_interest_paise(
            a.principal_paise, rate or 0, months)
        if charge is not None and total is not None:
            total += charge

        if months == 0:
            reason = (f"{part_days} day(s) past the appointed day — no monthly "
                      f"rest has fallen due yet, so §16 charges nothing so far.")
        else:
            reason = (f"{months} monthly rest(s) since {start.isoformat()}"
                      + (f", plus {part_days} day(s) of a rest not yet due"
                         if part_days else "")
                      + ("; still accruing." if still_running else "."))

        rows.append(InterestOnOneAmount(
            bill_id=a.bill_id, bill_no=a.bill_no, vendor_name=a.vendor_name,
            principal_paise=a.principal_paise,
            from_date=start.isoformat(), to_date=end.isoformat(),
            months=months, part_days=part_days, annual_rate_bps=rate,
            interest_paise=charge, still_running=still_running, reason=reason))

    caveats = [SECTION_23_DISALLOWS_IT, SECTION_22_DISCLOSURE, NOTHING_IS_POSTED]
    if refusal:
        gaps.insert(0, refusal)

    return MsmedInterestResult(
        financial_year=financial_year,
        as_at=today.isoformat(),
        bank_rate_bps=bank_rate_bps,
        charged_rate_bps=rate,
        interest_paise=total,
        amounts=tuple(rows),
        gaps=tuple(gaps),
        caveats=tuple(caveats),
    )


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=n)

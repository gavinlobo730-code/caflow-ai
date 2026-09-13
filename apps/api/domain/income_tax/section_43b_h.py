"""IT Act §43B(h) — a sum payable to a micro or small enterprise, paid late.

WHAT THE CLAUSE DOES

    The Finance Act 2023 inserted clause (h) into §43B with effect from
    AY 2024-25 (FY 2023-24). It says a deduction for

        "any sum payable by the assessee to a micro or small enterprise beyond
         the time limit specified in section 15 of the Micro, Small and Medium
         Enterprises Development Act, 2006"

    is allowed only in the previous year in which the sum is ACTUALLY PAID.

    THE FIRST PROVISO TO §43B DOES NOT REACH CLAUSE (h). Every other clause of
    §43B is saved by paying before the §139(1) return date; (h) is expressly
    excluded from that proviso, so a sum paid on 20 June — comfortably before
    the return — is still disallowed in the year it accrued if it missed the
    MSMED §15 limit. That is the single most common mistake with this clause
    and is why it is stated first.

WHAT THE TIME LIMIT IS — MSMED §15, AND IT IS FIFTEEN DAYS BY DEFAULT

    §15 requires payment "on or before the date agreed upon between him and the
    supplier IN WRITING, or, where there is no agreement in this behalf, before
    the appointed day", with a proviso that "in no case shall the period agreed
    upon between the supplier and the buyer in writing exceed forty-five days".

    §2(b) defines the appointed day as the day immediately following the expiry
    of FIFTEEN days from the day of acceptance or the day of deemed acceptance.

    So the limit is FIFTEEN days unless a written agreement says otherwise, and
    at most forty-five even then. Forty-five is the number everybody quotes and
    it is the exception, not the rule — applying it by default would give a
    month's grace the Act does not, and understate the disallowance.

WHO IT REACHES — MICRO AND SMALL ONLY

    §15 protects a "supplier", which §2(n) defines as a micro or small
    enterprise. A MEDIUM enterprise is registered under the MSMED Act and is
    still outside this clause. `vendors.msme_status` carries all four values for
    exactly that reason (migration 303), and an UNCLASSIFIED vendor is reported
    rather than assumed either way — the same refusal Schedule III's payables
    ageing makes.

TWO THINGS THIS MODULE IS HONEST ABOUT RATHER THAN PRECISE ON

  * ⚠️ **The clock starts at ACCEPTANCE, and the books hold the BILL DATE.**
    §15 runs from the day of acceptance or deemed acceptance — delivery, where
    no written objection is raised within fifteen days. Nothing records that,
    so the bill date is the proxy. An acceptance later than the bill date would
    push the due date later, so this proxy gives the EARLIER due date and
    therefore the LARGER disallowance. That is the direction a working should
    err in: it puts the item in front of the CA, who has the delivery note.
  * **TDS withheld counts as paid to the supplier**, the same interpretation
    `domain/gst/itc_reversal.py` already applies to Rule 37: the tax is
    remitted to the government on the supplier's behalf and credited to them
    under §199, so the supply is settled even though less cash moved. Treating
    it as unpaid would disallow a sum that is in substance paid.

WHAT IS DISALLOWED IS THE DEDUCTION, NOT THE PAYMENT

    §15 obliges payment of the whole invoice including tax; §43B disallows a
    DEDUCTION. Creditable GST is not a deduction — it is input tax credit — so
    the amount at risk is the taxable value plus any tax §17(5) blocked (which
    is capitalised or expensed and so IS claimed). Both figures are reported:
    the gross, because that is what §15 measures the timing against, and the
    deductible part, because that is what comes back into taxable income.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

#: MSMED §2(b) — the appointed day is the day immediately following the expiry
#: of fifteen days from acceptance. So payment ON day fifteen is in time.
APPOINTED_DAY_DAYS = 15

#: The proviso to MSMED §15. A written agreement for longer is ineffective
#: beyond this, so a recorded period above it is CAPPED and the capping is said
#: rather than silently applied.
MAX_AGREED_DAYS = 45

#: MSMED §2(n) with §7. A medium enterprise is registered under the Act and is
#: still not a "supplier" for §15, so §43B(h) does not reach it.
COVERED_STATUSES = ("micro", "small")

#: The Finance Act 2023 inserted clause (h) with effect from AY 2024-25.
FIRST_FY = "2023-24"

GAP_MSME_STATUS_NOT_CLASSIFIED = "msme_status_not_classified"

ACCEPTANCE_DATE_NOT_HELD = (
    "MSMED §15 runs from the day of ACCEPTANCE or deemed acceptance — delivery, "
    "where no written objection is raised within fifteen days — and nothing in "
    "the books records that date. The bill date is used instead. An acceptance "
    "later than the bill date would push the due date later, so every due date "
    "here is the earliest it could be and the disallowance is the largest it "
    "could be. Check the delivery note before relying on a marginal item."
)

FIRST_PROVISO_DOES_NOT_APPLY = (
    "The first proviso to §43B — paid before the §139(1) return due date — does "
    "NOT reach clause (h). A sum paid after the MSMED §15 limit is disallowed in "
    "the year it accrued however early in the next year it is paid, and is "
    "allowed only in the year of actual payment."
)


@dataclass(frozen=True)
class Payment:
    """One allocation against a bill: what was paid and WHEN."""
    paid_on: Optional[date]
    amount_paise: int


@dataclass(frozen=True)
class Bill:
    """A purchase bill of a micro or small vendor, as the clause needs it."""
    bill_id: str
    bill_no: Optional[str]
    vendor_id: Optional[str]
    vendor_name: str
    #: 'micro' | 'small' | 'medium' | 'large' | None. None is a GAP.
    msme_status: Optional[str]
    bill_date: Optional[date]
    #: What §15 requires be paid — the whole invoice.
    total_paise: int
    #: What is claimed as a deduction: taxable value plus §17(5)-blocked tax.
    deductible_paise: int
    #: Tax withheld and remitted on the supplier's behalf — counts as paid.
    tds_paise: int = 0
    #: The period agreed with this supplier IN WRITING, if any. None means no
    #: written agreement, and §15's appointed day applies.
    agreed_days: Optional[int] = None
    payments: tuple = ()
    #: True where the bill was capitalised into a fixed asset, so nothing was
    #: deducted and clause (h) has nothing to disallow.
    capitalised: bool = False


@dataclass(frozen=True)
class BillOutcome:
    bill_id: str
    bill_no: Optional[str]
    vendor_name: str
    bill_date: Optional[str]
    #: 15, or the written agreement capped at 45.
    limit_days: Optional[int]
    limit_source: str
    due_by: Optional[str]
    total_paise: int
    deductible_paise: int
    paid_in_time_paise: int
    paid_late_paise: int
    #: The financial year each late payment fell in — the year it becomes
    #: allowable. One bill can have several.
    paid_late_in_fys: tuple
    unpaid_paise: int
    #: The part of the DEDUCTION §43B(h) disallows in the year of accrual.
    disallowed_paise: int
    reason: str
    included: bool


@dataclass(frozen=True)
class Section43BHResult:
    financial_year: str
    #: Disallowed in THIS year: sums that accrued this year and missed §15.
    disallowed_paise: int
    #: Allowed BACK this year: earlier years' disallowances actually paid now.
    allowed_on_payment_paise: int
    bills: tuple
    gaps: tuple
    caveats: tuple
    #: True where the year predates the clause entirely.
    applicable: bool = True

    def to_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "applicable": self.applicable,
            "disallowed_paise": self.disallowed_paise,
            "allowed_on_payment_paise": self.allowed_on_payment_paise,
            "bills": [
                {
                    "bill_id": b.bill_id, "bill_no": b.bill_no,
                    "vendor_name": b.vendor_name, "bill_date": b.bill_date,
                    "limit_days": b.limit_days, "limit_source": b.limit_source,
                    "due_by": b.due_by, "total_paise": b.total_paise,
                    "deductible_paise": b.deductible_paise,
                    "paid_in_time_paise": b.paid_in_time_paise,
                    "paid_late_paise": b.paid_late_paise,
                    "paid_late_in_fys": list(b.paid_late_in_fys),
                    "unpaid_paise": b.unpaid_paise,
                    "disallowed_paise": b.disallowed_paise,
                    "reason": b.reason, "included": b.included,
                }
                for b in self.bills
            ],
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
        }


def limit_days(agreed_days: Optional[int]) -> tuple:
    """The MSMED §15 period for one supplier, and where it came from.

    Returns (days, source-sentence). Fifteen where nothing is agreed in
    writing; the agreed period otherwise, capped at forty-five by the proviso
    with the capping SAID — a contract for sixty days is not void, it is
    ineffective past forty-five, and a CA reading the working needs to know
    which number was used.
    """
    if agreed_days is None:
        return APPOINTED_DAY_DAYS, (
            f"MSMED §2(b) — no written agreement recorded, so the appointed day "
            f"is {APPOINTED_DAY_DAYS} days from acceptance.")
    d = int(agreed_days)
    if d <= 0:
        return APPOINTED_DAY_DAYS, (
            f"A written period of {d} days is not a period; MSMED §2(b)'s "
            f"{APPOINTED_DAY_DAYS} days applied instead.")
    if d > MAX_AGREED_DAYS:
        return MAX_AGREED_DAYS, (
            f"Written agreement records {d} days, capped at {MAX_AGREED_DAYS} "
            f"by the proviso to MSMED §15 — a longer period is ineffective.")
    return d, f"Written agreement: {d} days (MSMED §15)."


def fy_of(d: date) -> str:
    """The Indian financial year a date falls in — April to March."""
    return f"{d.year}-{(d.year + 1) % 100:02d}" if d.month >= 4 \
        else f"{d.year - 1}-{d.year % 100:02d}"


def _fy_bounds(fy: str) -> tuple:
    start_year = int(fy.split("-")[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def compute(bills: Iterable[Bill], *, financial_year: str) -> Section43BHResult:
    """What §43B(h) adds back for one previous year, and what it releases.

    Two figures, and they are about DIFFERENT years' bills:

      * `disallowed_paise` — bills that ACCRUED in this year and whose sums
        were not paid within their own §15 limit. Added to taxable income now.
      * `allowed_on_payment_paise` — bills of EARLIER years that were disallowed
        then and were actually paid during this year. Deducted now.
    """
    fy_start, fy_end = _fy_bounds(financial_year)
    out: list[BillOutcome] = []
    gaps: list[str] = []
    caveats: list[str] = [FIRST_PROVISO_DOES_NOT_APPLY, ACCEPTANCE_DATE_NOT_HELD]

    if financial_year < FIRST_FY:
        return Section43BHResult(
            financial_year=financial_year, disallowed_paise=0,
            allowed_on_payment_paise=0, bills=(), gaps=(),
            caveats=(f"§43B(h) was inserted by the Finance Act 2023 with effect "
                     f"from AY 2024-25, so it does not reach FY "
                     f"{financial_year}.",),
            applicable=False)

    disallowed = 0
    allowed_back = 0

    for b in bills:
        if b.msme_status is None:
            gaps.append(
                f"{b.vendor_name}: MSMED classification not recorded. §43B(h) "
                f"reaches a MICRO or SMALL enterprise only (MSMED §2(n)), and "
                f"whether this supplier is one is a fact about their Udyam "
                f"registration that no ledger holds. Their bills are left out "
                f"until it is recorded.")
            out.append(BillOutcome(
                b.bill_id, b.bill_no, b.vendor_name,
                b.bill_date.isoformat() if b.bill_date else None,
                None, "", None, b.total_paise, b.deductible_paise, 0, 0, (), 0,
                0, GAP_MSME_STATUS_NOT_CLASSIFIED, False))
            continue

        if b.msme_status not in COVERED_STATUSES:
            out.append(BillOutcome(
                b.bill_id, b.bill_no, b.vendor_name,
                b.bill_date.isoformat() if b.bill_date else None,
                None, "", None, b.total_paise, b.deductible_paise, 0, 0, (), 0, 0,
                f"{b.msme_status} — MSMED §2(n) makes a 'supplier' a micro or "
                f"small enterprise, so §15 and §43B(h) do not reach this one.",
                False))
            continue

        if b.bill_date is None:
            gaps.append(f"{b.vendor_name}: a bill with no date, so the §15 "
                        f"period cannot be measured.")
            out.append(BillOutcome(
                b.bill_id, b.bill_no, b.vendor_name, None, None, "", None,
                b.total_paise, b.deductible_paise, 0, 0, (), 0, 0,
                "No bill date.", False))
            continue

        days, source = limit_days(b.agreed_days)
        due = b.bill_date + timedelta(days=days)

        if b.capitalised:
            out.append(BillOutcome(
                b.bill_id, b.bill_no, b.vendor_name, b.bill_date.isoformat(),
                days, source, due.isoformat(), b.total_paise, 0, 0, 0, (), 0, 0,
                "Capitalised into a fixed asset — nothing was deducted, so "
                "there is nothing for §43B(h) to disallow. The MSMED §15 "
                "obligation to pay still stands.", False))
            continue

        # §199 credits the deductee with tax deducted at source, so the supply
        # is settled to that extent on the bill's own date.
        in_time = min(max(0, b.tds_paise), b.total_paise)
        late = 0
        late_fys: list = []
        for p in b.payments:
            amt = max(0, int(p.amount_paise))
            if not amt:
                continue
            if p.paid_on is not None and p.paid_on <= due:
                in_time += amt
            else:
                late += amt
                if p.paid_on is not None:
                    late_fys.append(fy_of(p.paid_on))
        in_time = min(in_time, b.total_paise)
        unpaid = max(0, b.total_paise - in_time - late)

        # The deduction at risk is the proportion of the SUM that missed the
        # limit, applied to the DEDUCTIBLE part. Proportional because a bill
        # part-paid in time is part-allowed: §43B(h) reaches "any sum payable
        # ... beyond the time limit", which is the part still owing at the
        # limit, not the whole invoice.
        missed = late + unpaid
        at_risk = (b.deductible_paise * missed // b.total_paise
                   if b.total_paise > 0 else 0)

        accrued_here = fy_start <= b.bill_date <= fy_end
        released_here = sum(
            1 for f in late_fys if f == financial_year)

        this_years_disallowance = at_risk if accrued_here else 0
        disallowed += this_years_disallowance

        # An earlier year's bill paid (late) during THIS year comes back as a
        # deduction now — §43B allows it "in computing the income ... of that
        # previous year in which such sum is actually paid".
        if not accrued_here and released_here:
            paid_now = sum(max(0, int(p.amount_paise)) for p in b.payments
                           if p.paid_on is not None and p.paid_on > due
                           and fy_of(p.paid_on) == financial_year)
            allowed_back += (b.deductible_paise * paid_now // b.total_paise
                             if b.total_paise > 0 else 0)

        if missed == 0:
            reason = "Paid within the MSMED §15 limit."
        elif unpaid:
            reason = (f"{unpaid} paise still unpaid past {due.isoformat()}.")
        else:
            reason = (f"Paid after {due.isoformat()} — disallowed in the year "
                      f"of accrual and allowed in "
                      f"{', '.join(sorted(set(late_fys))) or 'the year of payment'}.")

        out.append(BillOutcome(
            b.bill_id, b.bill_no, b.vendor_name, b.bill_date.isoformat(),
            days, source, due.isoformat(), b.total_paise, b.deductible_paise,
            in_time, late, tuple(sorted(set(late_fys))), unpaid,
            this_years_disallowance, reason, True))

    return Section43BHResult(
        financial_year=financial_year, disallowed_paise=disallowed,
        allowed_on_payment_paise=allowed_back, bills=tuple(out),
        gaps=tuple(gaps), caveats=tuple(caveats))

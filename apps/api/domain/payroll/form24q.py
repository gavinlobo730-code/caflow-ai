"""
Form 24Q, built from payroll instead of typed in again.

WHAT WAS WRONG

routers/tds.py's compute_24q takes its deductees from the REQUEST BODY. Payroll
computes §192 TDS on every payslip, posts it to the ledger as "TDS Payable -
Salary", and then the CA opens the TDS workspace and keys in every employee's
name, PAN, gross and tax by hand, for every month of the quarter. The two
modules never spoke.

Beyond the labour, re-keying is where the figures diverge: the return stops
agreeing with the books, and the mismatch surfaces months later as a TRACES
default notice, by which time nobody remembers which number was right.

This assembles the deductee rows from the payslips that were finalised and
posted. It computes no tax — the TDS is what payroll deducted and what the
ledger was credited.

WHAT IT REFUSES

  * A deductee without a valid PAN. Not merely a form-filling problem: §206AA
    requires tax at the HIGHER of the specified rate or 20% where PAN is not
    furnished, so filing "PANNOTAVBL" against tax deducted at slab rates
    declares a short deduction. The employer, not the employee, carries that.
  * A quarter with no §192 challan recorded. TDS deducted is a trust; a return
    saying it was deducted with nothing showing it was deposited invites the
    demand it is meant to prevent.

WHAT IT DELIBERATELY LEAVES TO THE CA

Employees paid in the quarter with NIL tax are not written as deductee rows —
Annexure I is a break-up of TDS deducted, and there is nothing to break up — but
they are counted and returned, so the decision is visible rather than silently
made here.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
SECTION_192 = "192"

# Indian FY quarters, and the payroll months that fall in each.
QUARTER_MONTHS = {
    "Q1": (4, 5, 6),
    "Q2": (7, 8, 9),
    "Q3": (10, 11, 12),
    "Q4": (1, 2, 3),
}


@dataclass
class Form24QSource:
    """What payroll can supply for a quarter's return."""
    deductees: list = field(default_factory=list)      # TDSDeducteeRecord
    challans: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    employees_with_nil_tds: int = 0

    @property
    def is_ready(self) -> bool:
        return bool(self.deductees) and not self.problems

    def totals(self) -> dict:
        return {
            "deductees": len(self.deductees),
            "salary_paise": sum(d.payment_amount_paise for d in self.deductees),
            "tds_paise": sum(d.tds_deducted_paise for d in self.deductees),
            "challan_paise": sum(int(c.get("tds_paise") or 0) for c in self.challans),
        }


def months_in_quarter(financial_year: str, quarter: str) -> list[str]:
    """The "YYYY-MM" payroll months a 24Q quarter covers.

    Q4 is the awkward one: January to March of the SECOND calendar year of the
    financial year, so "2026-27" Q4 is 2027-01 to 2027-03.
    """
    start_year = int(financial_year.split("-")[0])
    out = []
    for m in QUARTER_MONTHS[quarter]:
        year = start_year if m >= 4 else start_year + 1
        out.append(f"{year}-{m:02d}")
    return out


def _last_day(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _average_rate_pct(tds_paise: int, salary_paise: int) -> float:
    """§192(1) deducts at the AVERAGE rate of income-tax, not a prescribed one —
    the annual liability spread over the year — so the rate on a 24Q row is
    derived from what was actually deducted rather than looked up."""
    if salary_paise <= 0:
        return 0.0
    return round(tds_paise * 100 / salary_paise, 2)


def build_24q_from_payroll(
    *,
    slips_by_month: dict[str, list[dict]],
    employees_by_id: dict[str, dict],
    challans: list[dict],
    record_cls,
) -> Form24QSource:
    """Assemble deductee rows from finalised payslips.

    `record_cls` is domain.tds.tds_computer.TDSDeducteeRecord, passed in so this
    module stays free of that import and can be tested on its own.
    """
    out = Form24QSource()

    section_192_challans = [c for c in challans
                            if str(c.get("section") or "").strip() in (SECTION_192, "192B", "")]
    out.challans = section_192_challans

    any_tds = False
    for month in sorted(slips_by_month):
        for slip in slips_by_month[month]:
            emp = employees_by_id.get(slip.get("employee_id")) or {}
            name = (emp.get("name") or "").strip()
            label = name or slip.get("employee_id") or "unknown employee"
            tds = int(slip.get("tds_paise") or 0)
            gross = int(slip.get("gross_paise") or 0)

            if tds <= 0:
                out.employees_with_nil_tds += 1
                continue
            any_tds = True

            pan = str(emp.get("pan") or "").strip().upper()
            if not PAN_RE.match(pan):
                out.problems.append(
                    f"{label} ({month}): PAN {pan or 'missing'!r} is not valid. "
                    f"§206AA requires tax at the higher of the specified rate or 20% "
                    f"where PAN is not furnished, so this cannot be filed as a normal "
                    f"deduction — fix the PAN or account for the shortfall."
                )
                continue

            # One challan per quarter is the normal case; where several exist the
            # CA maps them on the portal. The first is carried so the row is not
            # blank, and the mapping stays the CA's.
            challan = section_192_challans[0] if section_192_challans else {}

            out.deductees.append(record_cls(
                deductee_name=name.upper(),
                deductee_pan=pan,
                section=SECTION_192,
                nature_of_payment="Salary",
                payment_date=_last_day(month),
                payment_amount_paise=gross,
                tds_rate_pct=_average_rate_pct(tds, gross),
                tds_deducted_paise=tds,
                tds_deposited_paise=tds,
                challan_no=str(challan.get("challan_no") or ""),
                bsr_code=str(challan.get("bsr_code") or ""),
                challan_date=str(challan.get("payment_date") or ""),
            ))

    if any_tds and not section_192_challans:
        out.problems.append(
            "No §192 challan is recorded for this quarter. TDS deducted from salary "
            "is held in trust and must be deposited before the return is filed; a "
            "return declaring a deduction with no challan behind it invites the "
            "very demand it is meant to prevent. Record the challan first."
        )

    return out

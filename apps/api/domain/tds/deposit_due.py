"""
What TDS is due for deposit for one month, and what being late has cost.

WHY THIS EXISTS (TDS-30)

    On the 5th of the month a CA has to work out, per client and per section,
    how much tax was deducted last month and is due by the 7th. Every one of
    those deductions is already a row in `tds_deductions` — the register
    services/tds_register_service.py keeps in step with the purchase bills —
    and nothing added them up. So the CA exported to Excel, which is the exact
    workflow this product exists to replace.

    Worse, the challan the CA then records took ONE typed number and booked
    all of it as tax (`tds_paise == total_paise`, migration 037's
    `interest_paise` and `penalty_paise` untouched), so a payment that was
    part interest went into the books as if it were all tax — and the next
    reconciliation reported the section as over-deposited.

WHAT THE ANSWER IS SHAPED LIKE

    A challan 281 worksheet: one line per section, because a challan is per
    section, and the CA pays one challan per section per month. Each line
    carries what was deducted, what has been deposited against it, what is
    still outstanding, and the §201(1A)(ii) interest on whatever went late —
    computed row by row rather than on the section total, because the clock
    starts at each deduction's own date and two deductions in one month can be
    days apart.

    "The tax" for both the deposit and the interest is
    `tds_paise + surcharge_paise + cess_paise`. On a resident-section
    deduction the last two are zero by construction; on a §195 remittance they
    are not, and they are as much a part of what must reach the government by
    the 7th as the base rate is.

WHAT IT DOES NOT COVER, AND WHY THAT IS SAID OUT LOUD

    Salary. §192 tax is computed inside payroll and lands on the payroll run,
    never in `tds_deductions` — the register is written only by the purchase
    bill and purchase payment paths. So this worksheet is the NON-SALARY side
    of the month's Rule 30(2) liability, and it says so rather than letting a
    CA read a total as the whole of what they owe. Where a §192 row HAS been
    typed into the register by hand it is named as a gap, because that means
    the same liability is being tracked in two places.

    Rule 30(2) itself is not restated here. `services/compliance_engine.py`
    derives it — the seventh of the following month, except March, which is
    30 April — and the caller passes the answer in.

Integer paise throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.tds import interest as tds_interest

#: A row says it has been deposited but carries no challan date, so there is no
#: date to run §201(1A)(ii) to and no CIN for the statement's challan sheet.
GAP_DEPOSITED_WITH_NO_CHALLAN_DATE = "deposited_with_no_challan_date"
#: A §192 row is in the non-salary register. Salary TDS is computed in payroll
#: and deposited from there, so this one is either a duplicate of a payroll
#: liability or a deduction payroll does not know about.
GAP_SALARY_ROW_IN_THIS_REGISTER = "salary_row_in_this_register"

GAP_MESSAGES: dict[str, str] = {
    GAP_DEPOSITED_WITH_NO_CHALLAN_DATE:
        "These deductions are marked deposited but carry no challan date. "
        "Without one there is no date to compute §201(1A)(ii) interest to and "
        "no CIN for the statement's challan sheet, so they are counted as "
        "still outstanding here.",
    GAP_SALARY_ROW_IN_THIS_REGISTER:
        "A §192 (salary) deduction is in the non-salary register. Salary TDS "
        "is computed in payroll and deposited from there, so this row is "
        "either a duplicate of a payroll liability or a deduction payroll "
        "does not know about. Both are worth resolving before the challan is "
        "paid.",
}

#: Said on every worksheet, because a total that looks like "the month's TDS"
#: and is only part of it is the failure this module is trying to avoid.
SCOPE_NOTE = (
    "This is the NON-SALARY side of the month. §192 tax is computed in "
    "payroll and deposited from there; it never reaches this register, so it "
    "is not in these totals.")


@dataclass(frozen=True)
class SectionLine:
    section: str
    deductee_count: int
    taxable_paise: int
    #: tds + surcharge + cess — the whole of what has to reach the government.
    tax_paise: int
    deposited_paise: int
    outstanding_paise: int
    #: §201(1A)(ii), summed over the section's own rows.
    interest_paise: int
    late_row_count: int
    earliest_deduction_date: Optional[date]
    latest_deduction_date: Optional[date]

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "deductee_count": self.deductee_count,
            "taxable_paise": self.taxable_paise,
            "tax_paise": self.tax_paise,
            "deposited_paise": self.deposited_paise,
            "outstanding_paise": self.outstanding_paise,
            "interest_paise": self.interest_paise,
            "payable_paise": self.outstanding_paise + self.interest_paise,
            "late_row_count": self.late_row_count,
            "earliest_deduction_date": (self.earliest_deduction_date.isoformat()
                                        if self.earliest_deduction_date else None),
            "latest_deduction_date": (self.latest_deduction_date.isoformat()
                                      if self.latest_deduction_date else None),
        }


@dataclass(frozen=True)
class Worksheet:
    month: str
    due_date: date
    as_at: date
    sections: tuple[SectionLine, ...]
    statutory_gaps: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def totals(self) -> dict:
        return {
            "deductee_count": sum(s.deductee_count for s in self.sections),
            "taxable_paise": sum(s.taxable_paise for s in self.sections),
            "tax_paise": sum(s.tax_paise for s in self.sections),
            "deposited_paise": sum(s.deposited_paise for s in self.sections),
            "outstanding_paise": sum(s.outstanding_paise for s in self.sections),
            "interest_paise": sum(s.interest_paise for s in self.sections),
            "payable_paise": sum(s.outstanding_paise + s.interest_paise
                                 for s in self.sections),
            "late_row_count": sum(s.late_row_count for s in self.sections),
        }

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "due_date": self.due_date.isoformat(),
            "due_date_rule": "IT Act Rule 30(2)",
            "as_at": self.as_at.isoformat(),
            "sections": [s.as_dict() for s in self.sections],
            "totals": self.totals,
            "covers": SCOPE_NOTE,
            "statutory_gaps": list(self.statutory_gaps),
        }


def _as_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build(rows, *, month: str, due_date: date, as_at: date) -> Worksheet:
    """One month of `tds_deductions` rows → the challan-281 worksheet.

    `rows` are already filtered to the month and the client; this function
    does no I/O so it runs identically in mock mode and against Postgres.
    A row with no usable `transaction_date` is skipped rather than dated from
    the month — the deduction date is what §201(1A)(ii)'s clock starts on, and
    inventing one would invent an interest figure.
    """
    by_section: dict[str, dict] = {}
    gaps: dict[str, list[str]] = {}

    for row in rows:
        section = str(row.get("section") or "").strip() or "(no section)"
        deducted_on = _as_date(row.get("transaction_date"))
        if deducted_on is None:
            continue
        tax = (int(row.get("tds_paise") or 0)
               + int(row.get("surcharge_paise") or 0)
               + int(row.get("cess_paise") or 0))
        deposited_on = _as_date(row.get("challan_date"))
        status = str(row.get("status") or "").strip().lower()
        if deposited_on is None and status in ("deposited", "filed"):
            gaps.setdefault(GAP_DEPOSITED_WITH_NO_CHALLAN_DATE, []).append(
                str(row.get("deductee_name") or row.get("id") or ""))
        if section.upper().replace(" ", "") in ("192", "SEC192", "S192"):
            gaps.setdefault(GAP_SALARY_ROW_IN_THIS_REGISTER, []).append(
                str(row.get("deductee_name") or row.get("id") or ""))

        line = by_section.setdefault(section, {
            "deductee_count": 0, "taxable_paise": 0, "tax_paise": 0,
            "deposited_paise": 0, "outstanding_paise": 0, "interest_paise": 0,
            "late_row_count": 0, "earliest": None, "latest": None,
        })
        line["deductee_count"] += 1
        line["taxable_paise"] += int(row.get("payment_amount_paise") or 0)
        line["tax_paise"] += tax
        if deposited_on is not None:
            line["deposited_paise"] += tax
        else:
            line["outstanding_paise"] += tax
        if line["earliest"] is None or deducted_on < line["earliest"]:
            line["earliest"] = deducted_on
        if line["latest"] is None or deducted_on > line["latest"]:
            line["latest"] = deducted_on

        # §201(1A)(ii) per ROW. An undeposited row's clock is still running, so
        # it is measured to `as_at`; a deposited one to its challan date. The
        # limb only bites where the money reached the government after the
        # Rule 30(2) date, which is what `due_date` decides.
        charge = tds_interest.interest_on_late_deposit(
            tax_paise=tax, deducted_on=deducted_on, due_date=due_date,
            deposited_on=deposited_on, as_at=as_at)
        if charge.applies:
            line["interest_paise"] += charge.interest_paise
            line["late_row_count"] += 1

    sections = tuple(
        SectionLine(
            section=name,
            deductee_count=v["deductee_count"],
            taxable_paise=v["taxable_paise"],
            tax_paise=v["tax_paise"],
            deposited_paise=v["deposited_paise"],
            outstanding_paise=v["outstanding_paise"],
            interest_paise=v["interest_paise"],
            late_row_count=v["late_row_count"],
            earliest_deduction_date=v["earliest"],
            latest_deduction_date=v["latest"],
        )
        for name, v in sorted(by_section.items())
    )
    statutory_gaps = tuple(
        {"kind": kind, "message": GAP_MESSAGES[kind],
         "deductees": sorted({d for d in names if d})}
        for kind, names in sorted(gaps.items())
    )
    return Worksheet(month=month, due_date=due_date, as_at=as_at,
                     sections=sections, statutory_gaps=statutory_gaps)

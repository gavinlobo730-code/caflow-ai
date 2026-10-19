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

WHERE "DEPOSITED" COMES FROM (found while seeding the demo firm's TDS data, 19-10-2026)

    From the CHALLAN REGISTER, by `domain/tds/challan_mapping`, the same function the quarterly statement asks which
    challan paid which deduction. This module used to read it off each deduction row (`challan_date`, `status`), two
    columns that exist since migration 014 and that nothing in the product writes: recording a challan never touched
    them, so a deposit made on the due date left the worksheet saying the whole month was outstanding and charging
    §201(1A)(ii) interest from the deduction to TODAY, growing every day, on tax that had reached the government on time.
    The columns are kept as the fallback for a row somebody marked by hand (a direct database write is the only way),
    and a row the register covers is judged by the register.

    A deduction that draws on two challans has EACH PART judged by its own challan's date, so the part paid late bears
    interest to the day it was paid (the statement names one challan per deductee row and reports the first; the interest
    cannot). A deduction only partly covered has its covered parts judged by their challans' dates and the rest as unpaid.
    A challan dated before the deduction it was matched to is not counted (the match is by order, not by date) and is
    named as a gap.

Integer paise throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.tds import challan_mapping
from domain.tds import interest as tds_interest

#: A row says it has been deposited but carries no challan date, so there is no
#: date to run §201(1A)(ii) to and no CIN for the statement's challan sheet.
GAP_DEPOSITED_WITH_NO_CHALLAN_DATE = "deposited_with_no_challan_date"
#: A challan the register matched to a deduction is dated BEFORE the deduction. Tax cannot have been paid over before it was
#: deducted, so that challan is not counted as having paid it and the tax stays outstanding until the date is looked at.
GAP_CHALLAN_BEFORE_DEDUCTION = "challan_before_deduction"
#: A §192 row is in the non-salary register. Salary TDS is computed in payroll
#: and deposited from there, so this one is either a duplicate of a payroll
#: liability or a deduction payroll does not know about.
GAP_SALARY_ROW_IN_THIS_REGISTER = "salary_row_in_this_register"

GAP_MESSAGES: dict[str, str] = {
    GAP_CHALLAN_BEFORE_DEDUCTION:
        "A challan was matched to a deduction made AFTER the challan's date. Tax cannot have been paid over before it was "
        "deducted, so that challan is not counted as paying it and the tax is shown as still outstanding. Check the "
        "challan's date, or the deduction's.",
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
    #: What was read to decide what is deposited. Empty when the caller read nothing beyond the rows.
    deposits_read: str = ""

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
            "deposits_read_from": self.deposits_read or None,
            "statutory_gaps": list(self.statutory_gaps),
        }


def _as_date(value) -> Optional[date]:
    return challan_mapping.as_date(value)


def _deposits_of(row: dict, tax: int, deducted_on: date, deposits) -> tuple[list[tuple[int, date]], bool]:
    """([(paise, date paid)] for the part of this row's tax that has been deposited, whether a challan was refused as
    dated before the deduction).

    The register first: each challan `challan_mapping` says the row drew from, with what it drew and the date that challan
    was paid on. A part whose challan has no date is not counted (there is nothing to run the interest to), and neither is
    one whose challan is dated before the deduction. A row the register does not cover at all falls back to its own
    `challan_date`, the column a hand-marked row carries, and then the whole of its tax counts."""
    refused = False
    if deposits is not None:
        parts, refused = challan_mapping.dated_parts(deposits.for_deduction(row.get("id")), deducted_on)
        if parts:
            return parts, refused
    own = _as_date(row.get("challan_date"))
    return ([(tax, own)] if own is not None else []), refused


def _tax_of(row: dict) -> int:
    return (int(row.get("tds_paise") or 0) + int(row.get("surcharge_paise") or 0) + int(row.get("cess_paise") or 0))


def is_salary(section: str) -> bool:
    return section.upper().replace(" ", "") in ("192", "SEC192", "S192")


def mapping_from_register(rows, challans, *, fy: str) -> "challan_mapping.Mapping":
    """Which challan of the register paid which of these deductions, for the quarter the rows and challans belong to.

    `rows` are the quarter's `tds_deductions` up to the end of the month asked about (FIFO needs the earlier months,
    because a short April moves the shortfall to the later deductions); `challans` are the quarter's `tds_challans`.
    The tax a challan paid is its `tds_paise` plus its `surcharge_paise`, which is the amount that left the bank less the
    interest and the penalty (`create_challan` stores `tds_paise` as the remainder, so a cess paid on the challan sits
    inside it: the form has no cess field); the tax a deduction owes is its tax, surcharge and cess. The quarterly
    statement matches the challan's `tds_paise` alone against the deduction's `tds_paise` alone, which agrees for every
    resident section (no surcharge, no cess) and differs for a section 195 payment by exactly the surcharge and cess.
    Interest and penalty are the deductor's own liability and settle no deduction. Salary is not here: it is deposited
    from payroll and neither side of this register carries it.
    """
    events = [{"id": r.get("id"), "section": str(r.get("section") or "").strip() or "(no section)",
               "on_date": str(r.get("transaction_date") or "")[:10], "doc_no": str(r.get("id") or ""),
               "tds_paise": _tax_of(r)}
              for r in rows if not is_salary(str(r.get("section") or ""))]
    paid = [{**c, "tds_paise": int(c.get("tds_paise") or 0) + int(c.get("surcharge_paise") or 0)}
            for c in challans if not is_salary(str(c.get("section") or ""))]
    return challan_mapping.assign(events, paid, fy=fy)


def build(rows, *, month: str, due_date: date, as_at: date,
          deposits: "Optional[challan_mapping.Mapping]" = None, deposits_read: str = "") -> Worksheet:
    """One month of `tds_deductions` rows → the challan-281 worksheet.

    `rows` are already filtered to the month and the client; this function
    does no I/O so it runs identically in mock mode and against Postgres.
    A row with no usable `transaction_date` is skipped rather than dated from
    the month — the deduction date is what §201(1A)(ii)'s clock starts on, and
    inventing one would invent an interest figure.

    `deposits` is the challan register's answer (`mapping_from_register`). Without it a row is judged by its own
    `challan_date` alone, which is what this function did before the register was asked. `deposits_read` is the sentence
    that says WHAT was read to decide it (which challans, for which quarter); it is carried on the answer so that a CA who
    sees tax outstanding can see where "deposited" comes from.
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
        parts, refused = _deposits_of(row, tax, deducted_on, deposits)
        covered = min(tax, sum(paise for paise, _ in parts))
        if refused:
            gaps.setdefault(GAP_CHALLAN_BEFORE_DEDUCTION, []).append(
                str(row.get("deductee_name") or row.get("id") or ""))
        status = str(row.get("status") or "").strip().lower()
        if covered == 0 and status in ("deposited", "filed"):
            gaps.setdefault(GAP_DEPOSITED_WITH_NO_CHALLAN_DATE, []).append(
                str(row.get("deductee_name") or row.get("id") or ""))
        if is_salary(section):
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
        line["deposited_paise"] += covered
        line["outstanding_paise"] += tax - covered
        if line["earliest"] is None or deducted_on < line["earliest"]:
            line["earliest"] = deducted_on
        if line["latest"] is None or deducted_on > line["latest"]:
            line["latest"] = deducted_on

        # §201(1A)(ii) per ROW. An undeposited row's clock is still running, so
        # it is measured to `as_at`; a deposited one to its challan date. The
        # limb only bites where the money reached the government after the
        # Rule 30(2) date, which is what `due_date` decides.
        late = False
        for part, paid_on in [*parts, (tax - covered, None)]:
            if part <= 0:
                continue
            charge = tds_interest.interest_on_late_deposit(
                tax_paise=part, deducted_on=deducted_on, due_date=due_date,
                deposited_on=paid_on, as_at=as_at)
            if charge.applies:
                line["interest_paise"] += charge.interest_paise
                late = True
        if late:
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
                     sections=sections, statutory_gaps=statutory_gaps, deposits_read=deposits_read)

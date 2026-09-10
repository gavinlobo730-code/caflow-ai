"""
Which challan a deduction was actually deposited under.

WHY THIS EXISTS (TDS-06)

    Form 26Q's deductee annexure is physically NESTED under its challan. In the
    NSDL RPU a statement has a challan sheet and an Annexure I, and every
    deductee row carries the serial of the challan row it sits below; the FVU
    cross-checks the two, and Rule 31A(4) reports the deduction and its deposit
    as one record. So each deduction has to name the challan that paid it.

    services/tds_return_service.py named it like this:

        matching_challan = next(
            (c for c in challans if parent_of(c["section"]) == parent_of(section)),
            None)

    — the FIRST challan for the section, in an `.order("id")` order arbitrary
    with respect to time. Rule 30(2) gives a quarter THREE monthly deposits, all
    under the same section, so every June deductee was stamped with April's BSR
    code and serial. That is either a rejected statement or, worse, an accepted
    one whose deductees all show 'U' (unmatched) in their 26AS and who then
    chase the client about it. The salary mirror was blunter still —
    `challans[0]`.

    The deposited COLUMN was wrong in a second way. It apportioned the section's
    whole quarterly deposit across the section's deductions by largest-remainder
    weight, so a deduction fully deposited on 7 May was shown as partly
    deposited whenever the QUARTER as a whole was short. A proportion is not an
    answer to "has this vendor's tax been paid".

FIFO, AND WHY THAT IS THE RIGHT SHAPE RATHER THAN A MONTH

    A first draft of this module gave every challan a deduction MONTH — Rule
    30(2) makes one, and a challan does deposit "tax deducted during the month
    of ___". It was wrong about the artefact. The RPU's challan row has no
    deduction-month field at all: the mapping is deductee-row → challan-row, and
    one challan may legitimately carry a catch-up covering more than one month.
    Forcing a month on it made a single challan paying two months' deductions
    read as leaving the earlier month unpaid, which is a wrong return.

    So the fill is FIFO, and it needs no new column: earliest deduction first,
    earliest challan first, each deduction taking what the challan has left. In
    the ordinary case — three monthly deposits, each matching its month's
    deductions — chronological order aligns them exactly, with no month
    recorded anywhere. In the short case the shortfall lands on the LAST
    deductions of the quarter instead of being smeared across all of them,
    which is both the §201 arrears convention and the answer a CA is actually
    asking for.

    Grouped by PARENT section: a challan records what somebody typed, and a CA
    types "194J" whichever limb the bill was under. Same rule CLAUDE.md states
    for the 2025-Act fork ("challan matching accepts BOTH labels in every
    period"), applied to a clause key. Matching on the exact string would leave
    every §194J(A) deduction with a blank CIN, invisible until FVU validation.

WHY NOT A challan_id ON EVERY DEDUCTION

    Migration 037's own comment says "Add challan_id FK to existing
    tds_deductions table" and the ALTER beneath it adds three other columns.
    It is worth adding when a CA needs to OVERRIDE this mapping — a genuine
    split by choice rather than by amount. Until a screen exists to record that
    choice it would be a column nothing writes, and a column nothing writes is
    one the next reader has to reverse-engineer the meaning of.

Integer paise throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from domain.tds.section_rates import parent_of

#: Deductions exist under a section beyond what the quarter's challans deposit —
#: which is to say the tax has not been paid, or the challan has not been
#: recorded here. §201(1A)(ii) charges 1.5% for every month or part month from
#: the date of DEDUCTION, not from the due date.
GAP_DEDUCTIONS_NOT_DEPOSITED = "deductions_not_deposited"
#: A challan deposits more under a section than the books deducted under it.
#: Either a deduction is missing from the books, or the challan carries interest
#: or penalty booked as tax, or it belongs to another section or period.
GAP_CHALLAN_EXCEEDS_DEDUCTIONS = "challan_exceeds_deductions"

GAP_MESSAGES: dict[str, str] = {
    GAP_DEDUCTIONS_NOT_DEPOSITED:
        "More tax was deducted under this section this quarter than the "
        "recorded challans deposit. Either the deposit has not been made — "
        "§201(1A)(ii) charges 1.5% for every month or part month from the date "
        "of deduction — or the challan has not been recorded here. The "
        "deductees left without a challan are the last of the quarter.",
    GAP_CHALLAN_EXCEEDS_DEDUCTIONS:
        "The challans recorded under this section deposit more than the books "
        "deducted under it. Either a deduction is missing from the books, or "
        "interest or penalty has been booked as tax on the challan, or the "
        "challan belongs to another section or period.",
}


@dataclass(frozen=True)
class Assignment:
    """One deduction's challan, and how much of it that challan actually paid.

    `challan` is the FIRST challan the deduction drew on. A deduction that
    straddles two challans is reported under the first, which is what the RPU
    allows — the alternative is splitting one bill into two deductee rows, and
    26Q's annexure asks for the amount paid or credited on a date, not for a
    payment instalment.
    """
    challan: Optional[dict] = None
    deposited_paise: int = 0


@dataclass
class Mapping:
    by_deduction_id: dict[str, Assignment] = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)

    def for_deduction(self, deduction_id) -> Assignment:
        return self.by_deduction_id.get(str(deduction_id), Assignment())


def _deduction_key(d: dict) -> tuple:
    return (str(d.get("on_date") or ""), str(d.get("doc_no") or ""), str(d.get("id") or ""))


def _challan_key(c: dict) -> tuple:
    return (str(c.get("payment_date") or ""), str(c.get("challan_no") or ""),
            str(c.get("id") or ""))


def assign(deductions: list[dict], challans: list[dict], *,
           fy: Optional[str] = None) -> Mapping:
    """Match each deduction to the challan that deposited it.

    `deductions` are `{id, section, on_date, doc_no, tds_paise}` — a purchase
    bill, an advance payment or a payslip, whichever the return is built from.
    `challans` are `tds_challans` rows; a challan's capacity is its `tds_paise`
    and NOT its `total_paise`, because interest and penalty are the deductor's
    own liability and never appear against a deductee.
    """
    out = Mapping()

    ded_groups: dict[str, list[dict]] = {}
    for d in deductions:
        ded_groups.setdefault(parent_of(d.get("section") or "", fy), []).append(d)

    chl_groups: dict[str, list[dict]] = {}
    for c in challans:
        chl_groups.setdefault(parent_of(c.get("section") or "", fy), []).append(c)

    for section in sorted(set(ded_groups) | set(chl_groups)):
        group = sorted(ded_groups.get(section, []), key=_deduction_key)
        pool = sorted(chl_groups.get(section, []), key=_challan_key)
        remaining = [max(0, int(c.get("tds_paise") or 0)) for c in pool]
        idx = 0
        undeposited = 0
        for d in group:
            need = max(0, int(d.get("tds_paise") or 0))
            covered = 0
            first_challan = None
            while need > 0 and idx < len(pool):
                if remaining[idx] <= 0:
                    idx += 1
                    continue
                take = min(need, remaining[idx])
                if first_challan is None:
                    first_challan = pool[idx]
                remaining[idx] -= take
                covered += take
                need -= take
            undeposited += need
            out.by_deduction_id[str(d.get("id"))] = Assignment(
                challan=first_challan, deposited_paise=covered)
        if undeposited > 0:
            out.gaps.append({
                "code": GAP_DEDUCTIONS_NOT_DEPOSITED,
                "message": GAP_MESSAGES[GAP_DEDUCTIONS_NOT_DEPOSITED],
                "section": section,
                "shortfall_paise": undeposited,
            })
        surplus = sum(remaining)
        if surplus > 0:
            out.gaps.append({
                "code": GAP_CHALLAN_EXCEEDS_DEDUCTIONS,
                "message": GAP_MESSAGES[GAP_CHALLAN_EXCEEDS_DEDUCTIONS],
                "section": section,
                "surplus_paise": surplus,
                "challan_nos": [c.get("challan_no") for c in pool],
            })

    return out

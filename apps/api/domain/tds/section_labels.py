"""The plain-English name of a TDS section, and the sections a challan may be recorded under (POST-A-278).

THE NAMES ARE COSMETIC AND THEY LIVE HERE ONCE. `app/tds/page.tsx` kept a copy of fifteen of them for its dropdowns and its table,
and a copy is a second place to drift: it held neither §194T, which the registry has carried since the section began, nor §195,
which the non-resident engine answers for, so the Add Challan form could not record a deposit under either and a deduction under
one of them read "Not deposited" beside a sentence telling the CA to record the challan. No rate and no threshold is here: those are
`section_rates` and `section_195`, and the names say what the section is about, not what it charges.

A CHALLAN is recorded under the PARENT section a CA would type ("194J" whichever limb the bill was under: `challan_mapping` groups
by `parent_of`), so the list is the registry's parents, in the registry's order, and §195, which the resident registry does not hold
because its answer turns on the nature of the income (`section_195`) and not on a threshold. Salary (§192) is in the registry and so
in the list: payroll computes the tax, the CA deposits it on the same challan 281.
"""
from __future__ import annotations

from typing import Optional

from domain.tds.residency import SECTION_195
from domain.tds.section_rates import parent_of, tds_rates_for

SECTION_LABELS: dict[str, str] = {
    "192":   "Salary",
    "193":   "Interest on securities",
    "194":   "Dividends",
    "194A":  "Interest other than securities",
    "194B":  "Lottery / winnings",
    "194C":  "Contractor payments",
    "194D":  "Insurance commission",
    "194G":  "Commission on lottery tickets",
    "194H":  "Commission / brokerage",
    "194I":  "Rent",
    "194J":  "Professional / technical fees",
    "194K":  "Income from units",
    "194LA": "Compensation on immovable property",
    "194Q":  "Purchase of goods",
    "194T":  "Payments to partners of a firm",
    "195":   "Payments to non-residents",
    "206C":  "TCS on sale of goods",
}


def label_of(section: Optional[str], fy: Optional[str] = None) -> Optional[str]:
    """The name of a section, or of the section a clause key ("194J(A)") belongs to, or None for one with no name here."""
    key = str(section or "").strip().upper()
    if not key:
        return None
    return SECTION_LABELS.get(key) or SECTION_LABELS.get(parent_of(key, fy))


def challan_sections(fy: Optional[str] = None) -> list[dict]:
    """The sections a challan may be recorded under, as `{section, label}`: each parent in the registry for `fy` once, in the
    registry's order, and then §195."""
    seen: list[str] = []
    for key in tds_rates_for(fy).sections:
        parent = parent_of(key, fy)
        if parent not in seen:
            seen.append(parent)
    if SECTION_195 not in seen:
        seen.append(SECTION_195)
    return [{"section": sec, "label": label_of(sec, fy)} for sec in seen]

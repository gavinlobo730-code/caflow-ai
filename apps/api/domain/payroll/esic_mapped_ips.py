"""Does our contribution file match the people ESIC has mapped? (Track F, F1)

WHY THIS IS THE HALF OF F1 WORTH BUILDING

ESIC's own filing manual makes the monthly upload ALL OR NOTHING:

    "successful transaction only when all the Employees' (who are currently
     mapped in the system) details are entered perfectly"

A file missing one insured person does not import that person's row and the
rest — the WHOLE FILE is rejected, after the CA has assembled it, uploaded it
and waited. The portal's own list of mapped IPs is the authority for who must
be in it, and nothing in this product had ever compared the two.

That is the failure F1 set out to stop, and it needs no Excel writer. The
original F1 was written as "emit a `.xls` the portal accepts"; the manual then
forbade emitting our own sheet at all ("only this template should be used, and
refrain from using any other sheet even if prepared in similar looking
format"), which turned F1 into "fill the CA's own downloaded template" — and
that needs a BIFF8 reader and writer.

WHY NO BIFF8, AND THIS IS A DECISION RATHER THAN A GAP

Filling the portal's template needs `xlrd` + `xlwt` + `xlutils`. `xlwt` and
`xlutils` have had no release since 2017, and `xlrd` would be PARSING AN
UNTRUSTED UPLOAD inside the service that holds every client's ledger. Taking on
three unmaintained parsers, one of them on the attack surface, would be a large
standing cost — and the requirement driving it cannot be checked from here: the
manual that says Excel 97-2003 is of unknown vintage and this environment's
egress is blocked, so whether the portal still refuses `.xlsx` in 2026 is
unknown.

So the reconciliation is built and the template filling is not. If the `.xls`
requirement is ever confirmed, this module is unaffected: it compares people,
not file formats, and whatever produces the eventual upload can use it.

WHAT THE CA SUPPLIES

The mapped-IP list, off the portal — insurance numbers, one per line or pasted
from the screen. Deliberately NOT parsed out of a spreadsheet, for the reason
above: a list of numbers is a list of numbers, and asking for one in a specific
file format would reintroduce the dependency this avoids.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: An ESIC insurance number is ten digits. Kept as a SHAPE check and nothing
#: more — the portal is the authority on which numbers exist, and a stricter
#: rule invented here would drop a real person out of the comparison, which is
#: the failure this module exists to prevent.
_DIGITS = re.compile(r"\d{6,}")


@dataclass(frozen=True)
class Reconciliation:
    """Who is in the portal's list, who is in our file, and who is in one only."""
    mapped_count: int
    file_count: int
    #: Mapped at ESIC and NOT in our file — each of these fails the whole upload.
    missing_from_file: list[str]
    #: In our file and not mapped at ESIC — the portal will not know them.
    not_mapped_at_esic: list[str]
    matched: list[str]

    @property
    def would_be_rejected(self) -> bool:
        """The manual's rule, as a property rather than a caller's inference."""
        return bool(self.missing_from_file)

    def to_dict(self) -> dict:
        return {
            "mapped_count": self.mapped_count,
            "file_count": self.file_count,
            "missing_from_file": list(self.missing_from_file),
            "not_mapped_at_esic": list(self.not_mapped_at_esic),
            "matched": list(self.matched),
            "would_be_rejected": self.would_be_rejected,
            "what_it_means": _sentence(self),
        }


def _sentence(r: Reconciliation) -> str:
    if not r.mapped_count:
        return ("No mapped insurance numbers were read from what you pasted. "
                "Copy the list from the ESIC portal's own screen — the upload "
                "is checked against it, not against our records.")
    if r.missing_from_file:
        n = len(r.missing_from_file)
        return (
            f"{n} insured {'person is' if n == 1 else 'people are'} mapped at "
            f"ESIC and not in this month's file. The upload is ALL OR NOTHING — "
            f"the whole file is rejected, not just {'that row' if n == 1 else 'those rows'} "
            f"— so fix this before you upload. Somebody mapped at ESIC with no "
            f"wages this month still needs a row, with a reason code.")
    if r.not_mapped_at_esic:
        n = len(r.not_mapped_at_esic)
        return (
            f"Every mapped person is in the file. {n} "
            f"{'number is' if n == 1 else 'numbers are'} in the file and not in "
            f"the portal's list — check the number, or get them mapped at ESIC "
            f"first; the portal will not accept a row for somebody it does not "
            f"know.")
    return ("Every mapped insured person is in the file and nobody else is. "
            "This is what the portal checks before it accepts the upload.")


def normalise(raw: str) -> list[str]:
    """Insurance numbers out of whatever the CA pasted, in order, deduplicated.

    The portal's screen copies as columns, as newline-separated text, or with
    names beside the numbers depending on how it is selected — so this takes the
    DIGIT RUNS and ignores everything else rather than demanding a format. A CA
    who has to reformat a list before the product will read it goes back to
    doing the comparison by eye, which is the thing being replaced.
    """
    seen: dict[str, None] = {}
    for match in _DIGITS.finditer(raw or ""):
        seen.setdefault(match.group(0), None)
    return list(seen)


def reconcile(*, mapped_raw: str, file_ip_numbers: list[str]) -> Reconciliation:
    """Compare the portal's mapped list against the numbers in our return.

    Order is the PORTAL's for what is missing from the file, and the file's for
    what the portal does not know — each list is read while looking at that
    side, and re-sorting it makes a CA hunt.
    """
    mapped = normalise(mapped_raw)
    mapped_set = set(mapped)

    ours: list[str] = []
    for number in file_ip_numbers:
        cleaned = str(number or "").strip()
        if cleaned and cleaned not in ours:
            ours.append(cleaned)
    ours_set = set(ours)

    return Reconciliation(
        mapped_count=len(mapped),
        file_count=len(ours),
        missing_from_file=[n for n in mapped if n not in ours_set],
        not_mapped_at_esic=[n for n in ours if n not in mapped_set],
        matched=[n for n in mapped if n in ours_set],
    )

"""
The ESIC monthly contribution return.

WHAT THIS PRODUCES

The file an employer uploads at esic.gov.in to declare a month's contributions.
Six columns per insured person:

    IP NUMBER, IP NAME, NO OF DAYS, TOTAL MONTHLY WAGES, REASON CODE,
    LAST WORKING DAY

The IP number is ten digits. Days are a whole number, fractions rounded UP —
ESIC's own instruction, and rounding down would under-declare a part-month.

WHY THE REASON CODE IS NOT DERIVED, AND NOT GUESSED

The reason code explains why an insured person has ZERO working days in a
month — left service, on leave, out of coverage, expired, and so on — and a
"last working day" is required alongside some of them.

Two separate problems, and both point the same way:

  * This system does not record WHY someone had no wages. It knows lop_days and
    an active flag; it does not know that a person resigned on the 12th rather
    than being on unpaid leave. Deriving one from the other would be inventing
    a fact about somebody's employment.
  * The numeric coding could not be confirmed against an authoritative ESIC
    source when this was written. Published guides disagree about which number
    means what.

So no code is invented here. A member with zero wages is reported as a PROBLEM
naming them, for the CA to supply the reason and the last working day, and the
file is withheld until they do. A wrong code on a statutory return is worse
than a return the CA has to complete — it is a false statement about an
employee's service, filed, and hard to unpick afterwards.

`0` is the only value written automatically, and only where wages are positive
and the question does not arise.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits.
#
# TODO(compliance): docs/compliance/04-mca-epfo-esic.md
#   Independent research in Sept 2026 made four targeted attempts at the
#   authoritative numeric reason-code mapping and failed the same way this
#   module records: published guides disagree, and ESIC surfaces the list
#   inside the portal at filing time rather than as a stable document. The
#   refusal above is CONFIRMED correct, not merely cautious.
#
#   And the stakes went up: ESIC issued a circular in October 2025 flagging
#   misuse of monthly filings showing zero-day workers, so zero-day rows are
#   now under active scrutiny. Do not soften this into a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

IP_NUMBER_RE = re.compile(r"^\d{10}$")
NOT_APPLICABLE = "0"


@dataclass(frozen=True)
class ESICMember:
    ip_number: str
    ip_name: str
    days: int
    wages_rupees: int
    reason_code: str = NOT_APPLICABLE
    last_working_day: str = ""

    def as_row(self) -> list[str]:
        return [self.ip_number, self.ip_name, str(self.days),
                str(self.wages_rupees), self.reason_code, self.last_working_day]


@dataclass
class ESICReturn:
    members: list[ESICMember] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def is_filable(self) -> bool:
        return bool(self.members) and not self.problems

    def to_csv(self) -> str:
        header = ["IP Number", "IP Name", "No of Days", "Total Monthly Wages",
                  "Reason Code", "Last Working Day"]
        rows = [header] + [m.as_row() for m in self.members]
        return "\n".join(",".join(_csv_cell(c) for c in r) for r in rows)

    def totals(self) -> dict:
        return {
            "members": len(self.members),
            "wages_rupees": sum(m.wages_rupees for m in self.members),
            "days": sum(m.days for m in self.members),
        }


def _csv_cell(value: str) -> str:
    """Quote a cell that would otherwise break the row.

    A name carrying a comma or a quote splits or corrupts the line, and every
    column after it shifts — the same failure the ECR builder hit with its own
    delimiter, in a different format.
    """
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if '"' in text or "," in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def _rupees(paise: int) -> int:
    return int(paise) // 100


def build_esic_return(
    *,
    slips: list[dict],
    employees_by_id: dict[str, dict],
    days_in_month: int,
) -> ESICReturn:
    """Assemble the monthly contribution return from finalised payslips.

    Members with no ESI contribution and no ESI applicability are left out: the
    return covers insured persons, and someone outside the scheme is not one.
    A member who IS insured but earned nothing this month stays in, as a problem
    until the CA says why.
    """
    out = ESICReturn()

    for slip in slips:
        emp = employees_by_id.get(slip.get("employee_id")) or {}
        name = (emp.get("name") or "").strip()
        label = name or slip.get("employee_id") or "unknown member"

        employee_esi = int(slip.get("esi_employee_paise") or 0)
        employer_esi = int(slip.get("esi_employer_paise") or 0)
        if not emp.get("esi_applicable") and employee_esi == 0 and employer_esi == 0:
            continue

        ip = str(emp.get("esi_number") or "").strip()
        if not ip:
            out.problems.append(
                f"{label}: no ESIC insurance number. The return cannot identify them.")
            continue
        if not IP_NUMBER_RE.match(ip):
            out.problems.append(f"{label}: ESIC number {ip!r} is not 10 digits.")
            continue

        lop = int(slip.get("lop_days") or 0)
        worked = max(0, days_in_month - lop)
        # ESI wages, not gross. ESI Act s.2(22) includes additional remuneration
        # only where "paid at intervals not exceeding two months", so a one-time
        # earning outside that interval — an annual bonus, ex-gratia — is not
        # wages here even though it is in the employee's gross pay. Taking it out
        # is what makes the wages on this return agree with the contribution the
        # run actually deducted, which computed on the same base (migration 331).
        #
        # Subtracted rather than rebuilt from the components: the slip stores
        # both totals precisely so this figure survives the earning rows being
        # edited or deleted after the run.
        one_time_total = int(slip.get("one_time_earnings_paise") or 0)
        one_time_esi = int(slip.get("one_time_esi_wages_paise") or 0)
        wages = _rupees(int(slip.get("gross_paise") or 0)
                        - (one_time_total - one_time_esi))

        if lop < 0 or lop > days_in_month:
            out.problems.append(
                f"{label}: {lop} unpaid days in a {days_in_month}-day month.")
            continue

        if worked == 0 or wages == 0:
            # The one thing this module will not do. See the module docstring:
            # the reason is a fact about someone's employment that this system
            # does not hold, and the numeric coding was not confirmable.
            out.problems.append(
                f"{label}: no wages this month. ESIC needs a reason code and, for "
                f"some reasons, a last working day — neither of which this system "
                f"records. Supply them on the portal, or exclude the member.")
            continue

        out.members.append(ESICMember(
            ip_number=ip,
            ip_name=_csv_cell(name).strip('"').upper(),
            days=worked,
            wages_rupees=wages,
        ))

    return out

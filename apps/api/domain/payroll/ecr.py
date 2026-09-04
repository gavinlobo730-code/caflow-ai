"""
The EPFO Electronic Challan cum Return (ECR) file.

WHAT THIS PRODUCES

ECR 2.0: a plain text file, one line per member, eleven fields separated by
`#~#`, in this order —

    UAN, MEMBER_NAME, GROSS_WAGES, EPF_WAGES, EPS_WAGES, EDLI_WAGES,
    EPF_CONTRI_REMITTED, EPS_CONTRI_REMITTED, EPF_EPS_DIFF_REMITTED,
    NCP_DAYS, REFUND_OF_ADVANCES

Every amount is in WHOLE RUPEES. The portal takes no paise, which is the reason
_compute_pf rounds each contribution to the rupee — 8.33% of the ₹15,000 ceiling
is ₹1,249.50 and the return must say ₹1,250.

WHY IT IS BUILT FROM STORED FIGURES AND COMPUTES NOTHING

Every number here comes off the payslip that was finalised and posted to the
general ledger. This module does not re-derive the EPS split, or re-apply a
ceiling, or recompute a contribution — because a return that disagreed with the
books would be the worst of both, and the two would part company the first time
a ceiling moved. If a figure looks wrong on the ECR, it is wrong in the ledger
too, and that is the correct place to fix it.

The one thing it does compute is EPF_EPS_DIFF_REMITTED, which is definitionally
EPF_CONTRI_REMITTED minus EPS_CONTRI_REMITTED and is on the file only because
EPFO asks for it explicitly.

WHAT IT REFUSES

The portal rejects a malformed file after upload, by which time the CA has lost
the round trip. These are checked here instead, and named per member:

  * UAN missing, or not 12 digits — mandatory in the UAN-based format
  * EPS wages above the ceiling, EDLI wages above the ceiling
  * EPF wages below EPS wages for the same member
  * NCP days negative or beyond the days in the month
  * a member with NCP equal to the whole month showing any contribution
  * the EPS/EPF split not summing to the employer contribution

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This builds a file for a human to
# upload to unifiedportal-emp.epfindia.gov.in. Nothing here transmits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DELIMITER = "#~#"
UAN_RE = re.compile(r"^\d{12}$")


def sanitise_name(raw: str) -> str:
    """Make a member name safe to put in a delimited, line-per-member file.

    A name is free text off the employee master, and two characters in it break
    the format silently rather than loudly:

      * the delimiter itself — "Odd#~#Name" adds a twelfth field, so every
        column after the name shifts by one and the wages land in the
        contribution columns. The portal would accept a well-formed line
        carrying the wrong numbers, which is the worst outcome available.
      * a newline or carriage return — the file is one line per member, so a
        name containing one silently becomes two members, the second malformed.

    Both are stripped and the remaining whitespace collapsed. Nothing else is
    altered: names are transliterated by whoever keys them and it is not this
    module's place to second-guess the spelling.
    """
    cleaned = (raw or "").replace(DELIMITER, " ")
    for ch in ("#", "~", "\r", "\n", "\t"):
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


@dataclass(frozen=True)
class ECRMember:
    """One member's line, in whole rupees as the portal requires."""
    uan: str
    name: str
    gross_wages: int
    epf_wages: int
    eps_wages: int
    edli_wages: int
    epf_contribution: int
    eps_contribution: int
    ncp_days: int
    refund_of_advances: int = 0

    @property
    def epf_eps_difference(self) -> int:
        """EPFO asks for this explicitly; it is not an independent figure."""
        return self.epf_contribution - self.eps_contribution

    def to_line(self) -> str:
        return DELIMITER.join(str(v) for v in (
            self.uan, self.name, self.gross_wages, self.epf_wages,
            self.eps_wages, self.edli_wages, self.epf_contribution,
            self.eps_contribution, self.epf_eps_difference,
            self.ncp_days, self.refund_of_advances,
        ))


@dataclass
class ECRFile:
    members: list[ECRMember] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def is_filable(self) -> bool:
        return bool(self.members) and not self.problems

    def to_text(self) -> str:
        return "\n".join(m.to_line() for m in self.members)

    def totals(self) -> dict:
        return {
            "members": len(self.members),
            "gross_wages": sum(m.gross_wages for m in self.members),
            "epf_wages": sum(m.epf_wages for m in self.members),
            "eps_wages": sum(m.eps_wages for m in self.members),
            "epf_contribution": sum(m.epf_contribution for m in self.members),
            "eps_contribution": sum(m.eps_contribution for m in self.members),
        }


def _rupees(paise: int) -> int:
    """Paise to whole rupees. The figures arriving here are already rounded to
    the rupee by _compute_pf, so this divides exactly; //100 rather than a
    second rounding, so a stray paise would surface as a mismatch in the
    split check below instead of being quietly absorbed."""
    return int(paise) // 100


def build_ecr(
    *,
    slips: list[dict],
    employees_by_id: dict[str, dict],
    days_in_month: int,
    wage_ceiling_paise: int,
) -> ECRFile:
    """Assemble the return from finalised payslips.

    `slips` are payroll_slips rows; `employees_by_id` maps employee_id to the
    payroll_employees row. Members with no PF (pf_applicable false, so no
    contribution) are left out entirely rather than filed as zero rows: the ECR
    is a return of contributions, and a nil member belongs on it only when they
    were contributory and the month produced nothing, which is the NCP case
    handled below.
    """
    out = ECRFile()
    ceiling_rupees = _rupees(wage_ceiling_paise)

    for slip in slips:
        emp = employees_by_id.get(slip.get("employee_id")) or {}
        name = (emp.get("name") or "").strip()
        label = name or slip.get("employee_id") or "unknown member"

        employee_pf = int(slip.get("pf_employee_paise") or 0)
        employer_total = int(slip.get("pf_employer_paise") or 0)
        eps = int(slip.get("pf_employer_eps_paise") or 0)
        epf_employer = int(slip.get("pf_employer_epf_paise") or 0)

        if not emp.get("pf_applicable") and employee_pf == 0 and employer_total == 0:
            continue                      # never contributory: not a member

        uan = str(emp.get("uan") or "").strip()
        if not uan:
            out.problems.append(f"{label}: no UAN. The UAN-based ECR cannot be filed without it.")
            continue
        if not UAN_RE.match(uan):
            out.problems.append(f"{label}: UAN {uan!r} is not 12 digits.")
            continue

        # The split must reconcile to what the ledger was credited. This is the
        # check that catches a slip written before migration 295, where the two
        # halves default to 0 and would otherwise file as a zero contribution
        # against a real employer payment.
        if eps + epf_employer != employer_total:
            out.problems.append(
                f"{label}: EPS {_rupees(eps)} + EPF {_rupees(epf_employer)} does not equal "
                f"the employer contribution {_rupees(employer_total)}. The payslip predates "
                f"the split being stored, or was written by something that does not set it."
            )
            continue

        # EPF Act s.6: PF wages = basic + DA. Plus whichever one-time earnings the
        # CA recorded AS PF wages (migration 331) — in practice arrears of basic
        # and DA, which s.2(b)'s exclusion of "any bonus, commission or any other
        # similar allowance" does not reach, and on which EPFO takes contributions
        # in the month of payment.
        #
        # Read off the slip's stored figure, not re-derived from the earning
        # rows: those can be edited or deleted after a run, and the ECR must
        # agree with the contribution that was actually deducted. Omitting it
        # here would file EPF wages lower than the 12% remitted against them,
        # which the portal reconciles and rejects.
        pf_wages = (int(slip.get("basic_paise") or 0)
                    + int(slip.get("da_paise") or 0)
                    + int(slip.get("one_time_pf_wages_paise") or 0))
        ncp = int(slip.get("lop_days") or 0)

        member = ECRMember(
            uan=uan,
            name=sanitise_name(name).upper(),
            gross_wages=_rupees(slip.get("gross_paise") or 0),
            epf_wages=min(_rupees(pf_wages), ceiling_rupees),
            # EPS wages are nil for a member excluded from the pension scheme —
            # otherwise the file claims pension wages against a zero pension
            # contribution and the portal rejects the line.
            eps_wages=min(_rupees(pf_wages), ceiling_rupees) if eps > 0 else 0,
            edli_wages=min(_rupees(pf_wages), ceiling_rupees),
            # The EMPLOYEE's 12% plus the employer's EPF half. This is what EPFO
            # means by "EPF contribution remitted" — not the employee's alone.
            epf_contribution=_rupees(employee_pf + epf_employer),
            eps_contribution=_rupees(eps),
            ncp_days=ncp,
        )

        if member.eps_wages > ceiling_rupees:
            out.problems.append(f"{label}: EPS wages exceed the ceiling.")
            continue
        if member.edli_wages > ceiling_rupees:
            out.problems.append(f"{label}: EDLI wages exceed the ceiling.")
            continue
        if member.epf_wages < member.eps_wages:
            out.problems.append(
                f"{label}: EPF wages {member.epf_wages} are below EPS wages "
                f"{member.eps_wages}; EPFO rejects that.")
            continue
        if ncp < 0 or ncp > days_in_month:
            out.problems.append(
                f"{label}: {ncp} non-contributory days in a {days_in_month}-day month.")
            continue
        if ncp == days_in_month and (member.epf_contribution or member.eps_contribution):
            out.problems.append(
                f"{label}: absent the whole month but showing a contribution.")
            continue

        out.members.append(member)

    return out

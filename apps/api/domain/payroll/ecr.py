"""
TODO(compliance): docs/compliance/04-mca-epfo-esic.md
    EPFO has no employer API; the ceiling is generate-the-file, human uploads.
    THE FILE THIS BUILDS IS STILL CORRECT — verified 2026-09-04 that the
    revamped ECR did NOT change the format: same .txt, same 11 fields, same
    #~# schema. What changed is everything around it, and none of that
    belongs in this module.

    Two circulars: launch 26-09-2025, FAQs 08-10-2025. From wage month
    September 2025:

      * RETURN AND PAYMENT ARE SEPARATE AND ORDERED. Submit and approve the
        return FIRST, then generate the challan. Two states per month.
      * SEQUENTIAL MONTH-WISE FILING IS ENFORCED BY BLOCKING. You cannot file
        October while September is pending. There was a four-month relaxation
        at launch; it expired around January 2026 and enforcement is live.
        Pending pre-September-2025 months must also go through the new system.
      * THREE RETURN TYPES: Regular (all active members for the month),
        Supplementary (employees registered AFTER that month's Regular was
        approved), Revised (correcting wages/contributions already submitted).
      * s.7Q interest and s.14B damages are AUTO-COMPUTED BY EPFO and shown in
        the Due Deposit Balance Summary. s.7Q is payable with the principal;
        s.14B may be paid forthwith or later.

    The month sequence and the return type ARE now modelled, in
    domain/payroll/ecr_sequence.py with migration 335 behind it: the ECR
    endpoint reports which earlier months are outstanding and whether this month
    needs a Regular, a Supplementary or a Revised return. They live there rather
    than here because they are facts about a CLIENT'S FILING HISTORY, and this
    module is about one month's file. It still emits per run and still knows
    nothing about any other month, which is correct.

    What remains outstanding is the upload itself, and it is not code: EPFO has
    no employer API, so a human takes this file to the portal.

    And never compute s.7Q or s.14B — not here, not in ecr_sequence, not
    anywhere. EPFO computes them and shows them in the Due Deposit Balance
    Summary; a second implementation of a statutory interest calculation drifts,
    and the CA would have two numbers with no way to tell which the portal will
    accept. tests/test_the_ecr_knows_which_months_are_outstanding.py fails if
    any payroll module grows one.

The EPFO Electronic Challan cum Return (ECR) file.

WHAT THIS PRODUCES

ECR 2.0: a plain text file, one line per member, eleven fields separated by
`#~#`, in this order —

    UAN, MEMBER_NAME, GROSS_WAGES, EPF_WAGES, EPS_WAGES, EDLI_WAGES,
    EPF_CONTRI_REMITTED, EPS_CONTRI_REMITTED, EPF_EPS_DIFF_REMITTED,
    NCP_DAYS, REFUND_OF_ADVANCES

THE THREE CONTRIBUTION COLUMNS, AS EPFO'S OWN SAMPLE HAS THEM (POST-A-517)

    column 7  EPF_CONTRI_REMITTED   the EMPLOYEE's contribution alone ("Employee PF Contribution")
    column 8  EPS_CONTRI_REMITTED   the employer's pension share ("Employer EPS Contribution")
    column 9  EPF_EPS_DIFF_REMITTED the employer's PF share ("Employer PF Contribution"), which is column 7 LESS column 8

EPFO's User Manual for the Re-engineered ECR (v3.0, page 8) gives the sample line for a member on Rs 15,000 as
`...#~#15000#~#15000#~#15000#~#15000#~#1800#~#1250#~#550#~#0#~#0`, and its return statement (page 10) shows the same member as
EE 1,800, EPS 1,250, ER 550. The account-1 total the portal raises is the employee column PLUS the employer column (1,800 + 550),
not column 7 alone and not (as this module put it until 19-11-2026) the two already added in column 7, which made every line carry
2,350 where EPFO's sample carries 1,800. The Employees' Provident Funds Scheme, 2026 prescribes the return as Form VII
(para 24(2)(ix)), whose contribution columns come in the same order. Whether the portal's file has changed since the manual is
owner list S48; the layout above is what the manual and the FAQs (questions 2 and 16) say.

Every amount is in WHOLE RUPEES. The portal takes no paise, which is the reason
_compute_pf rounds each contribution to the rupee — 8.33% of the ₹15,000 ceiling
is ₹1,249.50 and the return must say ₹1,250 (and 8.33% of the ₹25,000 ceiling, in
force from 17-09-2026, is ₹2,082.50 and the return must say ₹2,083).

WHY IT IS BUILT FROM STORED FIGURES AND COMPUTES NOTHING

Every number here comes off the payslip that was finalised and posted to the
general ledger. This module does not re-derive the EPS split, or re-apply a
ceiling, or recompute a contribution — because a return that disagreed with the
books would be the worst of both, and the two would part company the first time
a ceiling moved. If a figure looks wrong on the ECR, it is wrong in the ledger
too, and that is the correct place to fix it.

The one thing it does compute is EPF_EPS_DIFF_REMITTED, which is definitionally
EPF_CONTRI_REMITTED minus EPS_CONTRI_REMITTED and is on the file only because
EPFO asks for it explicitly. It is checked, member by member, against the
employer's EPF half the payslip and the ledger hold, so the file and the books
cannot part company: EPFO derives the employer's share from the employee's, so a
slip whose two halves differ cannot be represented and is refused by name.

WHAT IT REFUSES

The portal rejects a malformed file after upload, by which time the CA has lost
the round trip. These are checked here instead, and named per member:

  * UAN missing, or not 12 digits — mandatory in the UAN-based format
  * EPS wages above the ceiling, EDLI wages above the ceiling
  * EPF wages below EPS wages for the same member
  * NCP days negative or beyond the days in the month
  * a member with NCP equal to the whole month showing any contribution
  * the EPS/EPF split not summing to the employer contribution
  * the employee's contribution less the EPS not equal to the employer's EPF
    half the ledger was credited (column 9 would not be the books' figure)
  * a member declared on ACTUAL wages (below) whose election is recorded for an
    employee PF does not apply to, whose payslip holds no PF wage, or whose
    employee contribution is not the contribution rate of the EPF wage declared

PF ON ACTUAL WAGES (payroll-22, migration 477)

A member whose payslip RECORDS that PF was contributed on actual wages above the
ceiling — the employer's election, domain/payroll/pf_wage_election.py, paragraph
9(4) of the Employees' Provident Funds Scheme, 2026 — is declared with the EPF WAGE
column uncapped. EPS wages and EDLI wages stay at the ceiling for every member:
the pension and EDLI schemes keep their own. The flag is read off the SLIP, not
the employee row, which can change after a month is finalised; a member with no
election produces exactly the line this module produced before.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This builds a file for a human to
# upload to unifiedportal-emp.epfindia.gov.in. Nothing here transmits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from domain.payroll import pf_wage_election as pf_election

DELIMITER = "#~#"
# One copy, in domain/payroll/identity.py (PAY-30) — this module enforces it
# at file build and models/payroll.py now enforces it at the create door,
# so two places must not each carry their own idea of the shape.
from domain.payroll.identity import UAN_RE                  # noqa: F401


def ecr_file_name(wage_month: str) -> str:
    """The name the ECR is downloaded under: letters and digits only, and a lower-case `.txt` (POST-A-519).

    EPFO's notice on the upload page (User Manual for the Re-engineered ECR, v3.0, page 7) reads "Please only use alphabets and
    numbers in file names. Remove special characters and spaces from file names", and says the extension must be in small case. The
    product named the file `ECR_202609.txt`; whether the portal really refuses the underscore is not known from the manual, but its
    words are reason enough to take it out, at no cost. `wage_month` is "YYYY-MM" and only its digits are kept.
    """
    digits = "".join(ch for ch in str(wage_month) if ch.isdigit())
    return f"ECR{digits}.txt"


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
    #: Column 7, EPFO's "Employee PF Contribution": the EMPLOYEE's share alone, in whole rupees (POST-A-517). The employer's PF
    #: share is column 9, `epf_eps_difference`. Rows frozen in `epfo_ecr_filings.members` before 19-11-2026 hold the old meaning
    #: (the employee's share PLUS the employer's EPF half); none is a real filing, and the comparison that reads them is the
    #: safe direction (see domain/payroll/ecr_sequence.FiledMember).
    epf_contribution: int
    eps_contribution: int
    ncp_days: int
    refund_of_advances: int = 0
    #: This member is declared on ACTUAL wages above the ceiling by the
    #: employer's recorded election (payroll-22). Not a column of the file —
    #: `to_line` never reads it — it exists so the totals and the handoff can
    #: say how many such members the upload carries.
    on_actual_wages: bool = False

    @property
    def epf_eps_difference(self) -> int:
        """Column 9, the employer's PF share: column 7 less column 8. EPFO asks for it explicitly; it is not an independent figure
        (the 'Present rates of contribution' sheet: the employer's EPF share is "the difference of the EE Share ... and Pension
        Contribution")."""
        return self.epf_contribution - self.eps_contribution

    @property
    def employer_epf_contribution(self) -> int:
        """The same figure under the name the books use for it."""
        return self.epf_eps_difference

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
            # EDLI wages are their own ceiling and, for a member declared on
            # actual wages, no longer the EPF wage — so the handoff cannot say
            # "the portal computes A/c 21 from EPF wages" without this.
            "edli_wages": sum(m.edli_wages for m in self.members),
            # Column 7: the employees' share alone.
            "epf_contribution": sum(m.epf_contribution for m in self.members),
            # Column 8: the employers' pension share (account 10).
            "eps_contribution": sum(m.eps_contribution for m in self.members),
            # Column 9: the employers' PF share, columns 7 less 8.
            "employer_epf_contribution": sum(m.employer_epf_contribution for m in self.members),
            # Account 1 is the employee column PLUS the employer column (EPFO's User Manual v3.0, pages 12 and 22), which the
            # portal raises on the challan; refund of advances is not modelled and is always nil.
            "account_1_contribution": sum(m.epf_contribution + m.employer_epf_contribution for m in self.members),
            "members_on_actual_wages": sum(1 for m in self.members if m.on_actual_wages),
        }


def _rupees(paise: int) -> int:
    """Paise to whole rupees. The figures arriving here are already rounded to
    the rupee by _compute_pf, so this divides exactly; //100 rather than a
    second rounding, so a stray paise would surface as a mismatch in the
    split check below instead of being quietly absorbed."""
    return int(paise) // 100


def _election_refusal(label: str, emp: dict, slip: dict) -> Optional[str]:
    """Why a member whose PF is on ACTUAL wages cannot be filed, or None.

    Two inconsistencies, both about the employer's recorded election
    (domain/payroll/pf_wage_election.py, payroll-22) and neither reachable by a
    member with no election, whose line is therefore byte-identical to before:

      * the employee master carries an election for somebody PF does not apply
        to — the database refuses that combination, so this is the second line
        for a row that predates the constraint or arrived another way;
      * the slip says the contribution was on actual wages but does not hold
        the PF wage it was computed on (a slip older than migration 334 cannot
        say so), so there is no figure to declare as the EPF wage.

    Asked BEFORE the never-contributory skip: an election beside PF off is the
    one case where "not a member" would hide it.
    """
    if emp.get(pf_election.ELECTION) is True and not emp.get("pf_applicable"):
        return (f"{label}: an election to contribute PF on actual wages above "
                f"the ceiling is recorded, but PF does not apply to this "
                f"employee. Withdraw the election or switch PF on before "
                f"filing.")
    if slip.get("pf_on_actual_wages") and slip.get("pf_wages_paise") is None:
        return (f"{label}: this payslip records PF on actual wages but does "
                f"not hold the PF wage it was computed on, so the EPF wage "
                f"cannot be declared. Recompute the month.")
    return None


def _elected_contribution_mismatch(label: str, member: "ECRMember",
                                   employee_pf_paise: int,
                                   rate_bps: Optional[int]) -> Optional[str]:
    """A declared EPF wage the slip's own contribution does not follow, or None.

    Only for a member declared on actual wages: that is the one line where the
    EPF wage is above what a capped computation would have produced, so a slip
    computed on the ceiling and flagged as elected — or edited afterwards —
    would declare a wage 12% of which was never deducted. The check is one
    rupee wide because the file carries whole rupees and the slip rounds the
    contribution; it is a tie-out of two figures already on the slip, not a
    second computation of the contribution. Skipped where the caller supplied
    no rate, which is how every call written before payroll-22 behaves.
    """
    if not member.on_actual_wages or not rate_bps:
        return None
    expected = member.epf_wages * rate_bps // 10000
    declared = _rupees(employee_pf_paise)
    if abs(declared - expected) <= 1:
        return None
    # The rate as a sentence, in integer arithmetic: 1200 bps -> "12", 833 -> "8.33".
    percent = f"{rate_bps // 100}.{rate_bps % 100:02d}".rstrip("0").rstrip(".")
    return (f"{label}: declared on actual wages of {member.epf_wages}, but the "
            f"employee's contribution {declared} is not {percent}% of "
            f"that (about {expected}). The payslip's contribution and its PF "
            f"wage disagree; recompute the month before filing.")


def build_ecr(
    *,
    slips: list[dict],
    employees_by_id: dict[str, dict],
    days_in_month: int,
    wage_ceiling_paise: int,
    employee_rate_bps: Optional[int] = None,
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

        election_problem = _election_refusal(label, emp, slip)
        if election_problem:
            out.problems.append(election_problem)
            continue

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

        # THE PF WAGE BASE, READ OFF THE SLIP AND NOT RE-DERIVED.
        #
        # EPF Act s.6 made PF wages basic + DA, and that was right until
        # 21-11-2025. From the commencement of the four Labour Codes the Code on
        # Social Security subsumed the EPF Act and adopts its own
        # definition of wages (s.2(88)), which caps the listed exclusions at half of total
        # remuneration and deems the excess to be wages — so the base the
        # contribution is actually deducted on can be well above basic + DA.
        # routers/payroll.py computes it through domain/payroll/wage_base.py and
        # stores it as pf_wages_paise (migration 334).
        #
        # This module re-derived basic + DA instead, and that is the one figure
        # on the file that MUST tie to the contribution beside it: an employee on
        # 10,000 basic + 18,000 HRA contributes on a 14,000 base, so EPS of 1,166
        # was declared against EPF wages of 10,000 — 11.66% where EPFO validates
        # 8.33%. The portal either rejects the line or accepts a false wage
        # declaration, and the second is worse.
        #
        # NULL means the slip predates migration 334, which deliberately did not
        # backfill: those rows were computed on basic + DA and must be declared
        # on basic + DA, because the ECR states what was remitted.
        #
        # Plus whichever one-time earnings the CA recorded AS PF wages
        # (migration 331) — in practice arrears of basic and DA, which s.2(b)'s
        # exclusion of "any bonus, commission or any other similar allowance"
        # does not reach, and on which EPFO takes contributions in the month of
        # payment. Added here rather than left to the earning rows: those can be
        # edited or deleted after a run, and the ECR must agree with the
        # contribution that was actually deducted.
        stored_pf_wages = slip.get("pf_wages_paise")
        pf_wages = (int(stored_pf_wages) if stored_pf_wages is not None
                    else int(slip.get("basic_paise") or 0)
                    + int(slip.get("da_paise") or 0))
        pf_wages += int(slip.get("one_time_pf_wages_paise") or 0)
        ncp = int(slip.get("lop_days") or 0)

        # ONLY THE EPF WAGE COLUMN CAN EXCEED THE CEILING, and only for a member
        # whose payslip RECORDS that the contribution was on actual wages
        # (payroll-22, migration 477) — read off the slip like every other
        # figure here, never off the employee row, which can change after a
        # month is finalised. EPS wages and EDLI wages keep their own ceilings
        # for everybody, elected or not: the pension scheme and the EDLI scheme
        # each have one, and the portal validates both (see the module note).
        on_actual_wages = bool(slip.get("pf_on_actual_wages"))
        wage_rupees = _rupees(pf_wages)
        at_ceiling = min(wage_rupees, ceiling_rupees)

        member = ECRMember(
            uan=uan,
            name=sanitise_name(name).upper(),
            gross_wages=_rupees(slip.get("gross_paise") or 0),
            epf_wages=wage_rupees if on_actual_wages else at_ceiling,
            # EPS wages are nil for a member excluded from the pension scheme —
            # otherwise the file claims pension wages against a zero pension
            # contribution and the portal rejects the line.
            eps_wages=at_ceiling if eps > 0 else 0,
            edli_wages=at_ceiling,
            # Column 7 is the EMPLOYEE's contribution alone, as EPFO's own sample has it (1,800 for a Rs 15,000 member), and
            # column 9 is that less column 8 (POST-A-517). Until 19-11-2026 this added the employer's EPF half here, which put
            # 2,350 where EPFO's sample has 1,800 and made the portal's account-1 total come to 3,450 for the same member.
            epf_contribution=_rupees(employee_pf),
            eps_contribution=_rupees(eps),
            ncp_days=ncp,
            on_actual_wages=on_actual_wages,
        )

        mismatch = _elected_contribution_mismatch(
            label, member, employee_pf, employee_rate_bps)
        if mismatch:
            out.problems.append(mismatch)
            continue

        # COLUMN 9 IS THE BOOKS' FIGURE, OR THE FILE IS REFUSED. EPFO derives the employer's PF share from the employee's
        # (column 7 less the pension share), so the file can carry only a slip whose employer EPF half is exactly that. The
        # ledger was credited with `epf_employer` (the payroll accrual); a difference means the file would declare one
        # employer share to EPFO and the books another, which is the disagreement this module exists to prevent.
        if member.epf_eps_difference != _rupees(epf_employer):
            out.problems.append(
                f"{label}: the file would declare an employer PF share of {member.epf_eps_difference} (the employee's "
                f"{member.epf_contribution} less the pension share {member.eps_contribution}), but the payslip and the ledger "
                f"hold {_rupees(epf_employer)}. EPFO's file derives the employer's share from the employee's, so the two cannot "
                f"differ; recompute the month.")
            continue

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

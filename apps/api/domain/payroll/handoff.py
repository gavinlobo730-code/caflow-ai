"""The handoff: what a CA types, where, with the portal open beside this screen.

WHY THIS EXISTS (Track F, phase F3)

Of the seven steps between "the books are right" and "the obligation is closed"
— compute, emit the artefact, pre-flight, HAND OFF, file, capture the
acknowledgement, reconcile and lock — exactly one belongs to the government
(step 5, and only because there is no API a CA firm can hold). Six are ours,
and step 4 was the one nothing did.

What that costs is not abstract. A CA settling one client-month opens the
payroll register for the figures, Setup for the establishment code, Outputs for
the file, the EPFO portal, the ESIC portal, the state's own site, and a
spreadsheet to keep track of which of the three are done — then types numbers
from one into another and has nowhere to put the challan number that comes back.
The figures are all computed correctly and the files are all built correctly;
what is missing is the one screen that says, in the portal's own order, what
goes in which box.

WHAT IT IS NOT, AND THIS IS THE PART TO READ

It has NO credential field, NO OTP field and NO embedded portal frame, and none
of those is an oversight:

  * A password box in this product is a credential-capture surface whatever it
    is labelled, and whatever the intention behind it. The same rule already
    governs the GST filing demo and the Account Aggregator consent flow, for
    the same reason.
  * An OTP is typed on the portal, never in the software that prepared the
    return. Even where a real filing integration exists one day, the second
    factor stays where the statute put it.
  * Nothing here transmits. Every panel ends in "download this, upload it
    there, then tell us what came back" — because there IS no API for EPFO,
    ESIC or any state professional-tax portal, and there is no registration
    waiting to be granted that would change that. See
    docs/compliance/08-government-api-access-the-verified-position.md.

WHY IT IS ASSEMBLED IN apps/api RATHER THAN IN THE SCREEN

Which obligations arise from a month, in what order, with which warnings, is a
statutory judgement and not a layout. Professional tax has no due date this
product will state (each state fixes its own), ESI's period is not the wage
month, and EPFO's blocking rule can make a perfectly correct file unacceptable
today. A browser assembling that from four endpoints would be deciding it.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing in this module transmits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

EPF = "epf"
ESIC = "esic"
PROFESSIONAL_TAX = "professional_tax"

#: Where the CA actually goes. Named, not linked from a stored config, because
#: a portal hostname that can be edited is a phishing target: a handoff screen
#: that sends a CA to a host somebody typed into a settings table is worse than
#: one that sends them nowhere.
PORTALS: dict[str, tuple[str, str]] = {
    EPF: ("EPFO Unified Portal (Employer)", "unifiedportal-emp.epfindia.gov.in"),
    ESIC: ("ESIC Employer Portal", "esic.gov.in"),
    # Deliberately not a hostname. Professional tax is levied by twenty-two
    # states and each runs its own site — mgstd.gov.in, ctax.kar.nic.in and
    # twenty more. Naming one would send a CA in Karnataka to Maharashtra's.
    PROFESSIONAL_TAX: ("the state commercial-tax portal", ""),
}

#: ESIC's own manual, of a contribution already submitted: "No way contribution
#: amount submitted during monthly contribution will reduce." A supplementary
#: return can only INCREASE it. An over-declaration therefore has no ordinary
#: route back, which makes the confirm-before-submit moment on the ESIC portal
#: materially different from the EPFO one — and is exactly the kind of fact a
#: CA needs BEFORE they click, not in a manual they have not read.
ESIC_IRREVERSIBLE = (
    "Check the figures before you submit. A monthly contribution already "
    "submitted cannot be REDUCED — a supplementary return can only add to it — "
    "so an over-declaration has no ordinary way back."
)

#: The same manual, on what the file must contain: "successful transaction only
#: when all the Employees' (who are currently mapped in the system) details are
#: entered perfectly." One missing person fails the whole upload.
ESIC_ALL_OR_NOTHING = (
    "The upload is all-or-nothing against the portal's own list of mapped "
    "insured persons. If somebody is mapped at ESIC and missing from this file, "
    "the whole file is rejected — not just their row."
)

#: And on a zero: "Once 0 wages given, IP will be removed from the employer's
#: record." A zero-wage row does not report a month, it de-registers somebody.
ESIC_ZERO_REMOVES = (
    "Never enter 0 wages to report an unpaid month. A zero takes the insured "
    "person OFF the establishment's record at ESIC, and they stop being listed "
    "in later months. An unpaid month needs a reason code, which is why members "
    "with no wages come back as problems here rather than as rows."
)


@dataclass(frozen=True)
class IdentityField:
    """One identifier the portal asks for, and where it came from."""
    label: str
    value: Optional[str]
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "note": self.note}


@dataclass(frozen=True)
class Figure:
    """A number the portal will show back and ask the CA to confirm.

    `amount_paise` and `count` are alternatives, not a pair: a headcount is not
    money and formatting it as ₹40.00 because the field was called amount is
    the kind of thing a CA notices and stops trusting the screen over.

    `rupees` is for the two files that carry WHOLE RUPEES on the wire — the ECR
    and the ESIC return both do, because both portals work in rupees — so the
    figure is reported in the unit the portal will show, not converted into
    paise and back.
    """
    label: str
    amount_paise: Optional[int] = None
    rupees: Optional[int] = None
    count: Optional[int] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {"label": self.label, "amount_paise": self.amount_paise,
                "rupees": self.rupees, "count": self.count, "note": self.note}


@dataclass(frozen=True)
class Artefact:
    """The file the CA uploads, or an honest account of why there is none."""
    available: bool
    filename: Optional[str] = None
    endpoint: Optional[str] = None
    why_not: Optional[str] = None

    def to_dict(self) -> dict:
        return {"available": self.available, "filename": self.filename,
                "endpoint": self.endpoint, "why_not": self.why_not}


@dataclass(frozen=True)
class Obligation:
    """One statutory settlement, in the order its portal asks for it."""
    scheme: str
    key: str
    title: str
    authority: str
    portal: str
    portal_host: str
    wage_month: str
    period_label: str
    state: Optional[str] = None
    due_date: Optional[str] = None
    due_note: Optional[str] = None
    statute: Optional[str] = None
    identity: list[IdentityField] = field(default_factory=list)
    confirm: list[Figure] = field(default_factory=list)
    artefact: Artefact = field(default_factory=lambda: Artefact(False))
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record_back: Optional[str] = None
    #: Where the acknowledgement is one of a fixed set, the set — EPFO's return
    #: types, which this product already decides (ecr_sequence.decide_returns)
    #: and which the recording form used to ask about from scratch, defaulting
    #: to Regular whatever the month actually needed.
    record_options: list[str] = field(default_factory=list)
    recorded: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "scheme": self.scheme,
            "key": self.key,
            "title": self.title,
            "authority": self.authority,
            "portal": self.portal,
            "portal_host": self.portal_host,
            "wage_month": self.wage_month,
            "period_label": self.period_label,
            "state": self.state,
            "due_date": self.due_date,
            "due_note": self.due_note,
            "statute": self.statute,
            "identity": [f.to_dict() for f in self.identity],
            "confirm": [f.to_dict() for f in self.confirm],
            "artefact": self.artefact.to_dict(),
            "blocking": list(self.blocking),
            "warnings": list(self.warnings),
            "record_back": self.record_back,
            "record_options": list(self.record_options),
            "recorded": self.recorded,
        }


def contribution_period_label(period: str) -> str:
    """"2026-H1" as a CA would say it out loud.

    ESI Rule 50's periods are April-September and October-March, labelled by the
    year the period STARTED — so the second one spans a calendar year boundary
    and "2026-H2" means October 2026 to March 2027, not anything in H2 of 2026.
    Spelling it out is the whole point: the label is ambiguous to everybody who
    has not read Rule 50, and this screen is read under time pressure.
    """
    year, half = period.split("-")
    y = int(year)
    if half == "H1":
        return f"April – September {y} (contribution period {period})"
    return f"October {y} – March {y + 1} (contribution period {period})"


def month_label(wage_month: str) -> str:
    """"2026-09" as "September 2026"."""
    names = ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December")
    y, m = int(wage_month[:4]), int(wage_month[5:7])
    return f"{names[m - 1]} {y}"


def epf_obligation(
    *,
    wage_month: str,
    due_date: Optional[str],
    establishment_code: Optional[str],
    identity_gaps: list[str],
    file_totals: dict,
    edli_paise: int,
    admin_paise: int,
    problems: list[str],
    filable: bool,
    filename: Optional[str],
    blocking_months: list[str],
    sequence_note: Optional[str],
    required_returns: list[str],
    return_type_reason: Optional[str],
    interest_note: Optional[str],
    recorded: Optional[dict] = None,
) -> Obligation:
    """The EPFO ECR panel.

    The confirm block mixes two sources ON PURPOSE, and says so. The wages and
    contributions are the FILE's own totals — they are what the portal will read
    back off the upload, so a CA comparing the screen to the portal is comparing
    like with like. EDLI (A/c 21) and the administrative charge (A/c 2) are NOT
    in the file: the portal raises them on the challan itself, and the figures
    here are this product's own, carried so the CA can see a disagreement rather
    than discover it as an unexplained difference on the challan.

    A BLOCKED MONTH IS NOT A WRONG FILE. EPFO's revamped ECR will not accept a
    month while an earlier one is unapproved, and that is a fact about the
    upload, not about the return — so it goes in `blocking`, which the screen
    shows beside the download rather than instead of it. Folding it into
    `problems` would withhold a correct return.
    """
    identity = [IdentityField(
        "EPF establishment code", establishment_code,
        "EPFO takes the establishment from your portal login — the ECR file "
        "does not carry it — so this is here to tell you which establishment "
        "this file belongs to.")]

    confirm = [
        Figure("Members in the file", count=int(file_totals.get("members") or 0)),
        Figure("Total EPF wages", rupees=int(file_totals.get("epf_wages") or 0),
               note="what the portal computes A/c 1 and A/c 21 from"),
        Figure("Total EPS wages", rupees=int(file_totals.get("eps_wages") or 0),
               note="capped at the ₹15,000 ceiling per member"),
        Figure("EPF contribution (A/c 1)",
               rupees=int(file_totals.get("epf_contribution") or 0)),
        Figure("EPS contribution (A/c 10)",
               rupees=int(file_totals.get("eps_contribution") or 0)),
        Figure("EDLI (A/c 21)", amount_paise=int(edli_paise or 0),
               note="not in the file — the portal raises it on the challan. "
                    "This is our figure; they should agree."),
        Figure("Administrative charges (A/c 2)", amount_paise=int(admin_paise or 0),
               note="not in the file — the portal raises it on the challan. "
                    "Subject to the ₹500-per-establishment minimum."),
    ]

    blocking: list[str] = []
    if blocking_months:
        blocking.append(sequence_note or (
            f"EPFO is still waiting for {', '.join(blocking_months)}. This "
            f"month's file is correct, but the portal will not accept it until "
            f"those months are filed and approved."))

    # ecr_sequence's own values are lowercase — REGULAR = "regular" — and they
    # go back to the API unchanged. Title case is for the sentence only; a
    # comparison against "Regular" would fire this warning on every ordinary
    # month, which is the way to make a real one invisible.
    beyond_regular = [r for r in required_returns if r.lower() != "regular"]
    warnings: list[str] = []
    if beyond_regular:
        warnings.append(
            "Upload this as a "
            + " and a ".join(r.title() for r in beyond_regular)
            + " return"
            + (f" — {return_type_reason}" if return_type_reason else "."))
    if identity_gaps:
        warnings.extend(identity_gaps)
    if interest_note:
        warnings.append(interest_note)

    return Obligation(
        scheme=EPF,
        key=EPF,
        title="EPF contribution (ECR)",
        authority="EPFO",
        portal=PORTALS[EPF][0],
        portal_host=PORTALS[EPF][1],
        wage_month=wage_month,
        period_label=month_label(wage_month),
        due_date=due_date,
        statute="EPF Scheme 1952, para 38(1)",
        identity=identity,
        confirm=confirm,
        artefact=Artefact(
            available=bool(filable),
            filename=filename,
            endpoint=f"/api/payroll/runs/{{run_id}}/ecr",
            why_not=None if filable else (
                "; ".join(problems) if problems else
                "No member of this run carries a PF contribution, so there is "
                "no ECR to build.")),
        blocking=blocking,
        warnings=warnings,
        record_back="the TRRN the portal gives back, and the date you filed",
        record_options=list(required_returns) or ["regular"],
        recorded=recorded,
    )


def esic_obligation(
    *,
    wage_month: str,
    contribution_period: str,
    due_date: Optional[str],
    employer_code: Optional[str],
    identity_gaps: list[str],
    file_totals: dict,
    employee_share_paise: int,
    employer_share_paise: int,
    problems: list[str],
    filable: bool,
    filename: Optional[str],
    recorded: Optional[dict] = None,
) -> Obligation:
    """The ESIC monthly contribution panel.

    THE CONTRIBUTIONS ARE THE PORTAL'S FIGURES, NOT OURS, and the note says so.
    ESIC's manual is explicit — "IP Contribution and Employer contribution
    calculation will be automatically done by the system" — so the file carries
    days and wages only. Our own figures are shown beside them precisely so a CA
    can spot a disagreement at the confirm screen, which is the last moment it
    can be fixed: see ESIC_IRREVERSIBLE.

    THE PERIOD IS NOT THE MONTH. A CA looking for September 2026 on the portal
    finds it under contribution period 2026-H1, and the label is spelled out
    rather than shown as "2026-H1", which means nothing to anyone who has not
    read Rule 50.
    """
    identity = [IdentityField(
        "ESIC employer code", employer_code,
        "esic.gov.in takes the employer from your portal login — the "
        "contribution file does not carry it.")]

    confirm = [
        Figure("Insured persons in the file",
               count=int(file_totals.get("members") or 0)),
        Figure("Total wages", rupees=int(file_totals.get("wages_rupees") or 0),
               note="the portal computes both contributions from this"),
        Figure("Total days", count=int(file_totals.get("days") or 0)),
        Figure("Employee share (0.75%)", amount_paise=int(employee_share_paise or 0),
               note="our figure — the portal computes its own. Both shares are "
                    "rounded UP to the next whole rupee."),
        Figure("Employer share (3.25%)", amount_paise=int(employer_share_paise or 0),
               note="our figure — the portal computes its own."),
    ]

    return Obligation(
        scheme=ESIC,
        key=ESIC,
        title="ESI contribution",
        authority="ESIC",
        portal=PORTALS[ESIC][0],
        portal_host=PORTALS[ESIC][1],
        wage_month=wage_month,
        period_label=f"{month_label(wage_month)} · "
                     f"{contribution_period_label(contribution_period)}",
        due_date=due_date,
        statute="ESI (General) Regulations 1950, reg. 31",
        identity=identity,
        confirm=confirm,
        artefact=Artefact(
            available=bool(filable),
            filename=filename,
            endpoint=f"/api/payroll/runs/{{run_id}}/esic",
            why_not=None if filable else (
                "; ".join(problems) if problems else
                "No member of this run carries an ESI contribution, so there is "
                "no return to build.")),
        blocking=list(problems) if not filable else [],
        warnings=[ESIC_IRREVERSIBLE, ESIC_ALL_OR_NOTHING, ESIC_ZERO_REMOVES]
                 + list(identity_gaps),
        record_back="the challan number and the amount that left the bank",
        recorded=recorded,
    )


def professional_tax_obligations(
    *,
    wage_month: str,
    by_state: dict[str, int],
    headcount_by_state: dict[str, int],
    registrations: list[dict],
    recorded_by_state: Optional[dict[str, dict]] = None,
) -> list[Obligation]:
    """One panel per STATE this month deducted professional tax in.

    ONE PER STATE, NEVER ONE FOR THE MONTH. A client with staff in Maharashtra
    and Karnataka owes two different authorities, on two different due dates,
    against two different registration certificates, with two challans. A single
    "professional tax: ₹x" row is not a smaller version of that — it is a figure
    that cannot be paid.

    TWO REFUSALS, BOTH DELIBERATE, BOTH NAMED ON THE PANEL:

      * NO DUE DATE. services/compliance_engine.payroll_deposit_due_dates
        excludes professional tax for the reason written there: each state fixes
        its own and there is no rule to derive. A wrong date in a CA's calendar
        is worse than a missing one.
      * NO FILE. Nothing in this product produces a professional-tax challan or
        return for any state (Track F, phase F5). The panel says so rather than
        offering a download that is not there.

    PTRC, NOT PTEC. The Registration Certificate is the employer's authority to
    deduct from employees and deposit; the Enrolment Certificate is the entity's
    own levy on itself. Showing a PTEC where the CA needs a PTRC would send them
    to the portal with the wrong number.
    """
    ptrc = {(r.get("state") or "").strip().upper(): r for r in (registrations or [])}
    recorded_by_state = recorded_by_state or {}

    out: list[Obligation] = []
    for state in sorted(by_state):
        reg = ptrc.get(state.strip().upper(), {})
        number = (reg.get("ptrc_number") or "").strip() or None
        out.append(Obligation(
            scheme=PROFESSIONAL_TAX,
            key=f"{PROFESSIONAL_TAX}:{state}",
            title=f"Professional tax — {state.title()}",
            authority=f"{state.title()} commercial tax department",
            portal=PORTALS[PROFESSIONAL_TAX][0],
            portal_host=PORTALS[PROFESSIONAL_TAX][1],
            wage_month=wage_month,
            period_label=month_label(wage_month),
            state=state,
            due_date=None,
            due_note=(
                "No due date is shown because professional tax is a STATE levy "
                "and each state fixes its own — there is no rule to derive one "
                "from. Read it off the state's own notification; a date guessed "
                "here would go straight into your calendar."),
            statute=f"the {state.title()} professional tax Act",
            identity=[IdentityField(
                "PTRC number", number,
                "the Registration Certificate — the employer's authority to "
                "deduct from employees and deposit. Not the PTEC, which is the "
                "entity's own enrolment."
                + ("" if number else
                   " Nothing is recorded for this state; the employer cannot "
                   "deposit what it has already deducted without one."))],
            confirm=[
                Figure("Employees", count=int(headcount_by_state.get(state, 0))),
                Figure("Professional tax deducted",
                       amount_paise=int(by_state.get(state, 0))),
            ],
            artefact=Artefact(
                available=False,
                why_not=(
                    "This product does not produce a professional-tax challan or "
                    "return for any state yet. The figure above is computed from "
                    "the payslips and is what you enter on the state's portal.")),
            blocking=[] if number else [
                f"No PTRC is recorded for {state.title()}. The employer cannot "
                f"deposit what it has deducted without one — record it under "
                f"Payroll → Setup."],
            warnings=[],
            record_back="the challan number and the amount that left the bank",
            recorded=recorded_by_state.get(state),
        ))
    return out

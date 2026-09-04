"""
Which EPFO returns a wage month still needs, and what is blocking them.

WHY THIS EXISTS

`ecr.py` builds one month's file and knows nothing about any other month. Under
the ECR as revamped on 26 September 2025 (launch circular; FAQ circular of
8 October 2025), that is no longer enough to hand a CA a file they can actually
upload:

  * RETURN AND PAYMENT ARE SEPARATE AND ORDERED. The employer submits and
    APPROVES the return first, and only then generates the challan. So a month
    has two states at the portal, and a return that has been submitted but not
    approved has not cleared that month.
  * SEQUENTIAL MONTH-WISE FILING IS ENFORCED BY BLOCKING. October cannot be
    filed while September is pending. There was a four-month relaxation at
    launch; it expired around January 2026 and enforcement is live. Pending
    pre-September-2025 months go through the revamped system too.
  * THERE ARE THREE RETURN TYPES, and which one a month needs is a fact about
    what has already been filed for it, not a preference:
        Regular        every active member for the wage month;
        Supplementary  members registered AFTER that month's Regular was
                       approved;
        Revised        wages or contributions already submitted, corrected.

Without any of this the product hands a CA a perfectly-formed file for a month
the portal will refuse, and calls it done.

WHAT THIS MODULE DECIDES, AND WHAT IT REFUSES TO

It DERIVES the return type rather than asking. The CA already told us what
happened by recording what they filed; making them then pick "Regular" from a
dropdown invites the one answer that is always wrong — re-filing a Regular for a
month whose Regular is approved, which is what a late joiner looks like if you
are not paying attention.

It NEVER PICKS ONE where two apply. A month whose approved Regular is missing a
new joiner AND has a wrong wage for an existing member needs a Supplementary and
a Revised. `required_returns` is a tuple for exactly that case. Listing both is
the honest answer; picking the first would silently drop the other.

It DOES NOT KNOW THE ORDER the portal wants those two filed in, and does not
pretend to. The circulars seen describe the three types; none of them ranks a
Supplementary against a Revised for the same month. The tuple is in declaration
order, and callers must present it as a list of what is needed, not a sequence.

It DOES NOT DERIVE A RETURN TYPE FROM A MEMBER WHO HAS GONE. A UAN on the
approved Regular that is absent from the current run is reported as
`withdrawn_members` and drives nothing. The ECR format has no way to say "remove
this member" — a member wrongly included is corrected by revising their line,
which shows up as a figure change while they are still in the run. A member who
has simply vanished from the run is a question about the run, and guessing
"Revised" would file a return that says nothing about them.

s.7Q AND s.14B ARE NOT COMPUTED HERE OR ANYWHERE

EPFO computes interest under s.7Q and damages under s.14B itself, and shows them
in the Due Deposit Balance Summary at challan generation. This module carries
the sentence that says so and no arithmetic that would rival it — see
INTEREST_AND_DAMAGES_NOTE, and
tests/test_the_ecr_knows_which_months_are_outstanding.py, which fails if any
payroll module grows a computation for either.

THE LIMIT OF "OUTSTANDING", STATED HONESTLY

Outstanding months are drawn from the months this system holds a FINALISED
payroll run for. A month the client ran on paper, or ran with a previous
provider, or ran before they were onboarded here, is invisible to this module
and will still block them at the portal. `months_known_from` names the earliest
month considered so the CA can see where the window starts rather than reading
an empty list as "nothing owing".

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

#: The launch of the revamped ECR, by wage month. Months before this were filed
#: under the old workflow; pending ones now go through the new system anyway
#: (FAQ 3, circular 08-10-2025), so this is recorded for the note it prints and
#: is deliberately NOT used to exempt an earlier month from blocking.
REVAMP_FROM_WAGE_MONTH = "2025-09"

REGULAR = "regular"
SUPPLEMENTARY = "supplementary"
REVISED = "revised"

#: Recorded on a filing. `submitted` is not `approved`, and only `approved`
#: clears a month: the portal blocks a later month unless the earlier one is
#: filed AND validated.
SUBMITTED = "submitted"
APPROVED = "approved"

INTEREST_AND_DAMAGES_NOTE = (
    "Interest under s.7Q and damages under s.14B on a late remittance are "
    "computed by EPFO and shown in the Due Deposit Balance Summary when the "
    "challan is generated. PracticeSync does not compute either: a second "
    "implementation of a statutory interest calculation would hand you two "
    "numbers with no way to tell which one the portal will accept. s.7Q is "
    "payable with the principal; s.14B may be paid forthwith or later."
)


def is_month(value: object) -> bool:
    return isinstance(value, str) and bool(MONTH_RE.match(value))


def _months(values) -> list[str]:
    """Sort and de-duplicate month labels, dropping anything that is not one.

    YYYY-MM sorts correctly as text, which is the whole reason the column is
    that shape. Anything else is dropped rather than raising: this reads rows
    off a table that predates the format being validated, and one malformed
    month must not make the whole sequence unreadable.
    """
    return sorted({v for v in (values or []) if is_month(v)})


@dataclass(frozen=True)
class FiledMember:
    """One member's figures as they were on a return already filed.

    Frozen at the point of recording, for the same reason the GST services
    freeze a return's payload: "has this member's wage changed since we filed?"
    compares against what was FILED, and a live recomputation from the payslip
    would compare the books against themselves and always agree.

    Three figures, not eleven. These are the ones a Revised return exists to
    correct — "wages or contribution details". Name, NCP days and the refund of
    advances are not carried: a changed name is not a revision, and storing the
    whole line would put a copy of the return in a second place.
    """
    uan: str
    epf_wages: int
    epf_contribution: int
    eps_contribution: int

    def as_dict(self) -> dict:
        return {"uan": self.uan, "epf_wages": self.epf_wages,
                "epf_contribution": self.epf_contribution,
                "eps_contribution": self.eps_contribution}

    @property
    def figures(self) -> tuple[int, int, int]:
        return (self.epf_wages, self.epf_contribution, self.eps_contribution)


@dataclass(frozen=True)
class RecordedFiling:
    """An EPFO return the CA has told us they filed."""
    wage_month: str
    return_type: str
    status: str
    members: tuple[FiledMember, ...] = ()

    @property
    def is_approved(self) -> bool:
        return self.status == APPROVED

    @property
    def uans(self) -> frozenset[str]:
        return frozenset(m.uan for m in self.members)


@dataclass(frozen=True)
class ReturnDecision:
    """What this month still needs, and the evidence for saying so."""
    wage_month: str
    required_returns: tuple[str, ...]
    reason: str
    new_members: tuple[str, ...] = ()
    changed_members: tuple[str, ...] = ()
    withdrawn_members: tuple[str, ...] = ()

    @property
    def nothing_to_file(self) -> bool:
        return not self.required_returns


@dataclass(frozen=True)
class Sequence:
    """Where one wage month sits in the client's EPFO filing order."""
    wage_month: str
    outstanding: tuple[str, ...]
    blocking: tuple[str, ...]
    months_known_from: str | None

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocking)

    @property
    def note(self) -> str:
        if not self.blocking:
            return (
                "No earlier month is outstanding among the months this system "
                "holds a finalised run for"
                + (f", starting {self.months_known_from}. " if self.months_known_from else ". ")
                + "A month run outside PracticeSync is not visible here and "
                  "will still block the upload."
            )
        listed = ", ".join(self.blocking)
        return (
            f"EPFO enforces month-wise sequence: {self.wage_month} cannot be "
            f"filed while {listed} "
            f"{'is' if len(self.blocking) == 1 else 'are'} outstanding. File "
            f"{self.blocking[0]} first. This counts only months this system "
            f"holds a finalised run for; a month run elsewhere will also block "
            f"the upload and is not listed here."
        )


def outstanding_note(outstanding, months_known_from: str | None) -> str:
    """The client-level sentence: what EPFO is still waiting for, in order.

    A sentence rather than a count, and it lives here rather than in the screen
    that renders it, because "what is outstanding, and what did we not look at"
    is a statement about EPFO's rules — the same reason no computation lives in
    the frontend. The screen prints this; it does not compose it.
    """
    months = tuple(outstanding or ())
    if not months:
        return (
            "No wage month is outstanding"
            + (f" among those run here since {months_known_from}. "
               if months_known_from else " — no month has been run here yet. ")
            + "A month run on paper, with a previous provider, or before this "
              "client was onboarded is not counted and will still block an "
              "upload."
        )
    return (
        f"EPFO is waiting for {len(months)} wage month"
        f"{'' if len(months) == 1 else 's'}, and blocks them out of order: "
        + ", ".join(months)
        + f". File {months[0]} first. Only months run here are counted."
    )


def approved_regular_months(filings) -> set[str]:
    """Months whose Regular return is recorded as approved.

    A Supplementary or a Revised does not clear a month — neither of them is
    the month's return, both presuppose it — and a submitted-but-unapproved
    Regular does not either.
    """
    return {f.wage_month for f in (filings or [])
            if f.return_type == REGULAR and f.is_approved and is_month(f.wage_month)}


def outstanding_months(*, finalised_months, filings) -> tuple[str, ...]:
    """Finalised months with no approved Regular return, oldest first."""
    cleared = approved_regular_months(filings)
    return tuple(m for m in _months(finalised_months) if m not in cleared)


def sequence_for(wage_month: str, *, finalised_months, filings) -> Sequence:
    """Where `wage_month` sits, and which earlier months block it.

    EVERY earlier outstanding month is reported, not a window of four. The
    launch relaxation let a month through if the data four months prior was
    complete; it has expired, and encoding a window that has already moved once
    would err in the only direction that matters — telling a CA a month is
    clear to file when the portal will refuse it. Naming every outstanding
    earlier month is never wrong, only sometimes longer than it needs to be.
    """
    known = _months(finalised_months)
    outstanding = outstanding_months(finalised_months=known, filings=filings)
    return Sequence(
        wage_month=wage_month,
        outstanding=outstanding,
        blocking=tuple(m for m in outstanding if is_month(wage_month) and m < wage_month),
        months_known_from=known[0] if known else None,
    )


def decide_returns(wage_month: str, *, members, filings) -> ReturnDecision:
    """Which EPFO returns this month still needs, given what was filed for it.

    `members` are this run's members as FiledMember — built from the ECR the
    run produces now, so the comparison is between the file about to be
    uploaded and the file already accepted.

    Only APPROVED filings count as having covered anything. A Regular that was
    submitted and not approved has not been accepted, and treating it as
    covering its members would recommend a Supplementary for a month whose
    Regular is still in flight.
    """
    live = {m.uan: m for m in (members or [])}
    approved = [f for f in (filings or [])
                if f.wage_month == wage_month and f.is_approved]
    regular = next((f for f in approved if f.return_type == REGULAR), None)

    if regular is None:
        return ReturnDecision(
            wage_month=wage_month,
            required_returns=(REGULAR,),
            reason=("No approved Regular return is recorded for this month, so "
                    "this file is the Regular return."),
        )

    # Everything any approved return for the month has already said, latest
    # figure winning. A Revised supersedes the Regular for the members it
    # carries; comparing against the Regular alone would re-flag a member whose
    # correction has already been filed.
    filed: dict[str, FiledMember] = {}
    for f in approved:
        for m in f.members:
            filed[m.uan] = m

    new = tuple(sorted(u for u in live if u not in filed))
    changed = tuple(sorted(u for u in live
                           if u in filed and live[u].figures != filed[u].figures))
    withdrawn = tuple(sorted(u for u in filed if u not in live))

    required: list[str] = []
    if new:
        required.append(SUPPLEMENTARY)
    if changed:
        required.append(REVISED)

    if not required:
        reason = ("This month's Regular return is approved and every member on "
                  "it still matches the books. There is nothing further to file"
                  + (f", but {len(withdrawn)} member(s) on the filed return are "
                     "no longer in this run — see withdrawn_members."
                     if withdrawn else "."))
    else:
        parts = []
        if new:
            parts.append(f"{len(new)} member(s) are not on any approved return "
                         f"for this month, which is a Supplementary return")
        if changed:
            parts.append(f"{len(changed)} member(s) have figures that differ "
                         f"from what was filed, which is a Revised return")
        reason = "This month's Regular return is approved. " + "; ".join(parts) + "."
        if len(required) > 1:
            reason += (" Both are listed because a month can need both; this "
                       "module does not know which order EPFO wants them in.")

    return ReturnDecision(
        wage_month=wage_month, required_returns=tuple(required), reason=reason,
        new_members=new, changed_members=changed, withdrawn_members=withdrawn,
    )

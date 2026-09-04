"""
Statutory figures the FIRM recorded, and the rules for using one.

WHY THESE COME FROM A TABLE AND NOT FROM CODE

Professional tax is levied by twenty-two states, each setting its own slabs by
its own notification on its own cycle. professional_tax.py models FOUR of them
and reports a named gap for the rest rather than deducting zero, which is right
— Article 276 makes the employer liable to deduct and deposit it, so a silent
nil is a shortfall with interest, not an absence of liability.

Correct, and not a product. Writing the other eighteen states' slabs from
memory would put eighteen confidently wrong deductions into people's pay, and
maintaining them against notification cycles is a research desk this has no
revenue to fund. So the CA records what they READ, once per firm, reused across
every client of that firm.

THE LABOUR WELFARE FUND BELONGS HERE AND IS NOT HERE YET, deliberately. It is
refused for the same reason and by the same shape (lwf.py models no state at
all), but PT already has payroll_slips.pt_paise, a ledger leg and a payslip
line, so a recorded slab becomes a deduction the same day. LWF has none of
those, so its table arrives WITH the slip column and the journal leg that make
a recorded amount actually come out of somebody's pay — a screen that records
figures nothing reads looks like the gap is closed and is not.

PROVENANCE IS THE PRECONDITION, NOT A NICETY

The only reason a hand-entered number may drive a statutory deduction is that a
named person read a named notification on a named date. Migration 327 makes
notification_reference and notification_date NOT NULL, and `provenance()` here
returns them so the register can print the authority beside the figure. A row
without them would be an unsourced number in a payslip, which is the fault the
refusals exist to prevent, with a nicer interface.

A RECORDED SET MUST COVER EVERY WAGE, OR IT IS NOT USED

`bands_cover_every_wage` requires the bands to start at zero and to meet
end-to-start with no hole. Without that, an employee whose gross falls in a gap
gets no matching band, and the natural thing to return is zero — which is the
fall-back-instead-of-fail pattern this codebase keeps closing. A half-recorded
state is reported as still-a-gap rather than quietly deducting nothing from the
people the CA had not got to yet.

THE CODE WINS FOR A STATE IT MODELS

MH, TN, KA and WB are verified against the state Act and pinned by tests, and
two of them have rules no slab table expresses — Maharashtra's February
differential and women's exemption, Tamil Nadu's half-yearly levy. A firm row
recorded against one of those is REPORTED, not applied and not ignored:
applying it would let one typo replace a tested table for every client of the
firm; ignoring it would leave a CA believing they had fixed something.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: PT slabs may be read against the month, or against six months' pay and
#: deducted only in the named months (Tamil Nadu's shape).
BASES = ("monthly", "half_yearly")


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def in_force(rows: list[dict], on: date) -> list[dict]:
    """The one version effective on `on` — every row sharing the latest
    effective_from that is not in the future.

    A revision is recorded as a NEW effective_from rather than by editing the
    old rows, so a run for an earlier month keeps computing at the figures that
    applied to it. Editing in place would silently restate a month already
    posted to the general ledger.
    """
    dated = [(d, r) for r in (rows or [])
             if (d := _as_date(r.get("effective_from"))) is not None and d <= on]
    if not dated:
        return []
    latest = max(d for d, _ in dated)
    return [r for d, r in dated if d == latest]


def bands_cover_every_wage(bands: list[dict]) -> bool:
    """True when the bands start at zero and meet end-to-start with no hole.

    The top band's to_paise is NULL — "and above". Anything else leaves a wage
    with no band, and the only answer available then is a zero that means
    "nobody recorded this", which is indistinguishable from "nothing is due".
    """
    if not bands:
        return False
    ordered = sorted(bands, key=lambda b: int(b.get("from_paise") or 0))
    if int(ordered[0].get("from_paise") or 0) != 0:
        return False
    for lower, upper in zip(ordered, ordered[1:]):
        if lower.get("to_paise") is None:
            return False           # an open band that is not the last one
        if int(lower["to_paise"]) != int(upper.get("from_paise") or 0):
            return False
    return ordered[-1].get("to_paise") is None


def _applies_in(row: dict, month: int | None) -> bool:
    months = row.get("months")
    if not months:
        return True                # NULL/empty means every month
    return month in {int(m) for m in months}


@dataclass(frozen=True)
class RateResult:
    """What a recorded set came to, and whether it may be used.

    `usable` False with amount 0 is a GAP — the same distinction PTResult and
    LWFResult draw, kept here so the caller cannot lose it by reading the
    amount alone.
    """
    employee_paise: int = 0
    employer_paise: int = 0
    usable: bool = False
    note: str = ""
    notification_reference: str = ""
    notification_date: str = ""

    @property
    def is_gap(self) -> bool:
        return not self.usable


def provenance(row: dict) -> tuple[str, str]:
    ref = str(row.get("notification_reference") or "").strip()
    when = _as_date(row.get("notification_date"))
    return ref, (when.isoformat() if when else "")


def professional_tax(slabs: list[dict], *, gross_paise: int, month: int | None,
                     on: date, state: str) -> RateResult:
    """PT from the firm's recorded slabs, or a stated reason why not.

    Returns usable=False rather than 0 whenever the answer would be a guess:
    nothing recorded, nothing effective yet, or bands that do not cover every
    wage. A zero that comes from a matched nil band IS usable — that is a
    state saying nothing is due at this wage, which is a real answer.
    """
    version = in_force(slabs, on)
    if not version:
        return RateResult(note=(
            f"No professional-tax slabs are recorded for {state} effective on or "
            f"before {on.isoformat()}, so nothing has been deducted. Record the "
            f"state notification under Settings -> Statutory values."))

    if not bands_cover_every_wage(version):
        return RateResult(note=(
            f"The professional-tax slabs recorded for {state} do not cover every "
            f"wage — they must start at zero, meet end to start, and finish with "
            f"an open top band. Nothing has been deducted, because a wage that "
            f"falls in a hole would silently come out as nil."))

    basis = str(version[0].get("basis") or "monthly")
    applicable = [b for b in version if _applies_in(b, month)]
    ref, when = provenance(version[0])

    if not applicable:
        # A half-yearly levy in a month it is not deducted in. A real zero.
        return RateResult(usable=True, notification_reference=ref, notification_date=when,
                          note=f"{state} professional tax is not deducted in this month.")

    measure = gross_paise * 6 if basis == "half_yearly" else gross_paise
    for band in sorted(applicable, key=lambda b: int(b.get("from_paise") or 0)):
        upper = band.get("to_paise")
        if measure >= int(band.get("from_paise") or 0) and (upper is None or measure < int(upper)):
            return RateResult(employee_paise=int(band.get("amount_paise") or 0),
                              usable=True, notification_reference=ref,
                              notification_date=when)

    # Unreachable while bands_cover_every_wage holds; kept because "unreachable"
    # is how a silent zero gets in when somebody later relaxes the cover check.
    return RateResult(note=(
        f"No recorded professional-tax band matches a gross of {measure} paise in "
        f"{state}. Nothing has been deducted."))


def slabs_recorded_against_a_modelled_state(slabs: list[dict],
                                            modelled: frozenset[str]) -> list[str]:
    """States where a firm recorded slabs the code will not use.

    Not applied, and not silently dropped. Applying would let one typo replace a
    table verified against the state Act for every client of the firm; dropping
    it would leave a CA believing they had fixed something. Naming the
    disagreement is the only option that cannot mislead — and a notification
    that has genuinely moved is then a code change somebody knows to make.
    """
    states = sorted({str(s.get("state") or "").strip().upper() for s in (slabs or [])}
                    & set(modelled))
    return [
        f"Professional-tax slabs are recorded for {state}, but {state} is modelled "
        f"in the software and verified against the state Act, so the recorded "
        f"slabs were NOT used. If the state has issued a new notification, say so "
        f"— this needs a code change, not a settings change."
        for state in states
    ]

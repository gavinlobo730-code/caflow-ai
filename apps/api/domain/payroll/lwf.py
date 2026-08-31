"""
Labour Welfare Fund: named, and deliberately not guessed.

WHERE THIS STANDS TODAY

Nothing in this payroll module deducts LWF. Not "computes it as zero" — the
concept does not exist here, so an employer in Maharashtra or Karnataka who owes
it has been shown a payslip that silently omits a statutory deduction, and a
statutory summary that does not mention it.

WHAT THIS MODULE DOES, AND WHAT IT DOES NOT

It makes the omission VISIBLE. It carries the list of states that levy LWF under
their own Welfare Fund Act, so a run can say "this employee is in a state that
levies LWF and nothing has been deducted", instead of the current silence.

It does NOT carry the amounts. Each state fixes its own contribution, its own
wage threshold and its own periodicity — some deduct twice a year in June and
December, some annually, some monthly, and the figures move by state
notification. Writing sixteen sets of amounts from memory would put sixteen
confidently wrong deductions into people's pay, and a wrong deduction is worse
than a flagged gap: the employee is short-paid and the employer still owes the
right figure.

This is the same judgement made for professional tax in the module beside this
one, and for the ESIC reason codes: a number that cannot be verified is not
written. Adding a state is a human step — read the current notification, add the
amounts and periodicity, move it out of the unmodelled set.

WHY IT IS WORTH LANDING WITHOUT THE AMOUNTS

Because the failure being fixed is not "the figure is wrong", it is "nobody
knows there is a figure". A CA who sees "Maharashtra levies LWF; not computed"
goes and deducts it. A CA who sees nothing does not.
"""
from __future__ import annotations

from dataclasses import dataclass

# States and union territories with a Labour Welfare Fund Act under which
# employers and employees contribute. Periodicity and amounts vary by state and
# are deliberately not carried here — see the module docstring.
LEVYING_STATES: dict[str, str] = {
    "AP": "Andhra Pradesh", "CG": "Chhattisgarh", "DL": "Delhi",
    "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana",
    "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh",
    "MH": "Maharashtra", "OD": "Odisha", "PB": "Punjab",
    "TG": "Telangana", "TN": "Tamil Nadu", "WB": "West Bengal",
    "CH": "Chandigarh",
}

# None yet. The set exists so that adding a state is a one-line change here plus
# its amounts, and so the tests can assert that nothing claims to be modelled
# while the amounts are absent.
MODELLED_STATES: frozenset = frozenset()


@dataclass(frozen=True)
class LWFResult:
    employee_paise: int
    employer_paise: int
    modelled: bool
    note: str = ""

    @property
    def is_gap(self) -> bool:
        return not self.modelled


def classify_state(state: str | None) -> LWFResult:
    """Say whether LWF is owed in this state, and whether we can compute it."""
    code = (state or "").strip().upper()

    if not code:
        return LWFResult(0, 0, modelled=True,
                         note="No state set; no labour welfare fund contribution.")

    if code not in LEVYING_STATES:
        return LWFResult(0, 0, modelled=True,
                         note=f"{code} has no Labour Welfare Fund Act on this list.")

    return LWFResult(0, 0, modelled=False, note=(
        f"{LEVYING_STATES[code]} levies a Labour Welfare Fund contribution and the "
        f"amounts are not modelled here, so NOTHING has been deducted. The rate, "
        f"the wage threshold and the periodicity are all set by the state — some "
        f"deduct half-yearly in June and December, some annually — so read the "
        f"current notification and deduct it outside this system until it is added."))

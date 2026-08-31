"""
Professional tax: which states levy it, which are modelled, and which are not.

THE BUG THIS EXISTS TO CLOSE

_compute_pt looked its state code up in a dict of slab tables and returned 0 for
anything it did not find. Four states are modelled — Maharashtra, Tamil Nadu,
Karnataka, West Bengal — so an employee whose pt_state is "GJ", "TG", "KL" or a
dozen others was silently deducted NOTHING, on a payroll run the CA had
explicitly marked pt_applicable.

That is the same shape as every other fault found in this codebase this week: a
lookup that falls back instead of failing, producing a confidently wrong number
with nothing to show it was wrong. PT is a state levy under Article 276 with the
employer liable to deduct and deposit it, so the shortfall is the employer's,
with interest and penalty, and it surfaces at assessment.

THREE ANSWERS, NOT TWO

    LEVIES + modelled      -> the amount
    DOES NOT LEVY          -> zero, and zero is CORRECT
    anything else          -> zero, and zero is a GAP that must be visible

The third case is the point. Silently returning zero for Gujarat and for Delhi
is the same number meaning two opposite things — "nothing is due" and "something
is due and we did not compute it". They are separated here so the second can be
reported.

WHY THE UNMODELLED STATES ARE NOT JUST FILLED IN

Each state sets its own slabs by its own notification, and they move
independently. Writing twenty slab tables from memory would put twenty
confidently wrong numbers into people's payslips, which is worse than a gap
somebody can see. The states below are the ones whose tables were verified
against the Act; the rest are named as levying PT so the system SAYS it cannot
compute them.

Adding a state is: verify its current slabs against the state notification, add
the table, move it out of the unmodelled set. That is a human step, like the ITR
schemas — see CLAUDE.md's annual-maintenance section.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Who levies it ────────────────────────────────────────────────────────────
# Article 276(2) caps professional tax at ₹2,500 per person per year, but
# whether it is levied at all is each state's choice.

LEVYING_STATES: dict[str, str] = {
    "AP": "Andhra Pradesh", "AS": "Assam", "BR": "Bihar",
    "CG": "Chhattisgarh", "GJ": "Gujarat", "JH": "Jharkhand",
    "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh",
    "MH": "Maharashtra", "MN": "Manipur", "ML": "Meghalaya",
    "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha",
    "PY": "Puducherry", "PB": "Punjab", "SK": "Sikkim",
    "TN": "Tamil Nadu", "TG": "Telangana", "TR": "Tripura",
    "WB": "West Bengal",
}

NON_LEVYING_STATES: dict[str, str] = {
    "DL": "Delhi", "HR": "Haryana", "UP": "Uttar Pradesh",
    "UK": "Uttarakhand", "RJ": "Rajasthan", "HP": "Himachal Pradesh",
    "JK": "Jammu & Kashmir", "LA": "Ladakh", "CH": "Chandigarh",
    "AN": "Andaman & Nicobar Islands", "LD": "Lakshadweep",
    "AR": "Arunachal Pradesh",
}

# Verified against the state Act and covered by tests. Everything else in
# LEVYING_STATES is a gap, deliberately.
MODELLED_STATES = frozenset({"MH", "TN", "KA", "WB"})


@dataclass(frozen=True)
class PTResult:
    """What PT came to, and whether that number can be trusted."""
    amount_paise: int
    modelled: bool
    note: str = ""

    @property
    def is_gap(self) -> bool:
        """True when the zero means "not computed", not "nothing due"."""
        return not self.modelled and self.amount_paise == 0


def classify_state(state: str | None) -> PTResult:
    """Decide which of the three answers a state code deserves.

    Returns the amount as 0 in every case — the caller computes the real figure
    for a modelled state. This exists to separate a correct zero from a
    dangerous one.
    """
    code = (state or "").strip().upper()

    if not code:
        # No state on the employee. Not a gap: PT is only withheld where the CA
        # has said which state's law applies, and saying nothing is a choice.
        return PTResult(0, modelled=True, note="No state set; no professional tax withheld.")

    if code in NON_LEVYING_STATES:
        return PTResult(0, modelled=True,
                        note=f"{NON_LEVYING_STATES[code]} does not levy professional tax.")

    if code in MODELLED_STATES:
        return PTResult(0, modelled=True, note="")

    if code in LEVYING_STATES:
        return PTResult(0, modelled=False, note=(
            f"{LEVYING_STATES[code]} levies professional tax and its slabs are not "
            f"modelled here, so NOTHING has been deducted. Article 276 makes the "
            f"employer liable to deduct and deposit it, so this is a shortfall to "
            f"settle, not an absence of liability. Verify the current slabs against "
            f"the state notification and add them."))

    return PTResult(0, modelled=False, note=(
        f"State code {code!r} is not recognised, so it cannot be told apart from a "
        f"state that levies professional tax. Nothing has been deducted. Use a "
        f"two-letter code from the list this module carries."))

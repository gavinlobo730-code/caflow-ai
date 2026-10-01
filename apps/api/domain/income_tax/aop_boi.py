"""How an association of persons or a body of individuals is charged — §167B.

WHAT WAS WRONG (TDS-INCOME-TAX-16)
    `clients.entity_type` had no value for an AOP or a BOI, so one was recorded
    as an "Individual" and charged on the individual slabs. The Act does not
    leave it there. §167B charges the total income of an AOP or BOI at the
    MAXIMUM MARGINAL RATE (§2(29C)) — the top slab, from the first rupee, with
    no basic exemption — in two cases, and on the ordinary slab rates only
    otherwise:

      (1) §167B(1): the shares of the members are INDETERMINATE or UNKNOWN;
      (2) §167B(2): the shares are determinate, but the total income of ANY
          member (before his share of the association's income) exceeds the
          maximum amount not chargeable to tax.

    Both limbs turn on a fact about the MEMBERS that no record in this product
    holds — there is no member register, and a member's own income is a figure
    on somebody else's return. So the two facts are INPUTS to the computation,
    tri-state, and an unstated one is REFUSED:

      * assuming "determinate and no member above the limit" charges an
        association on the slabs, with a nil band, when the Act charges every
        rupee at the top rate — the expensive direction of error, on the figure
        the association pays;
      * assuming "indeterminate" charges the top rate on an association the Act
        lets use the slabs, which is the other way.

    Neither guess is safe, so neither is made. The refusal names both questions
    and the section, in the house shape (payroll's `statutory_gaps`, the §195
    chargeability questions, a trust's §12AB/§164 refusal in `assessee.py`).

WHAT IS NOT MODELLED, AND NAMED ON EVERY ANSWER
    §167B's own provisos and the neighbouring cases — a member taxed at a rate
    above the maximum marginal rate, an association every member of which is a
    company, a non-resident member, the §86 exemption of a member's share where
    the association has paid tax on it — are not modelled. `CAVEATS` says so on
    the answer, because a figure that does not name what it leaves out reads as
    complete.

    The MAXIMUM MARGINAL RATE is read off the slab registry's last bracket (30%
    in both regimes in every year held) rather than stated here, so a Finance
    Act that moves the top slab moves it with no edit to this module. §2(29C)
    defines it as the rate "including surcharge" applicable to the highest slab,
    and whether that means the surcharge for the association's own income
    bracket or the highest surcharge rate was not confirmed here (egress is
    refused). The engine applies the surcharge for the association's OWN income
    bracket, which is the LOWER figure for an association below the top bracket
    — so the reading fails generous, and the answer says so.

⚠️ EVERY SECTION'S WORDING HERE IS `[S]`-GRADED. `VERIFIED` is False, and
`tests/test_a_huf_aop_and_boi_have_their_own_tax_basis.py` pins each rule
exactly so a later reader who has the Act in front of them changes a constant
with a test failing rather than a paragraph being edited around.

Nothing here is money. The engine does the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

#: Whether the rules below have been read against the Act. They have not —
#: written from knowledge with egress refused.
VERIFIED = False

def is_aop_or_boi(kind: Optional[str]) -> bool:
    """An association of persons or a body of individuals — the two §167B
    treats as one and the Finance Act's rate schedule names together."""
    return kind in ("aop", "boi")


BASIS_MAXIMUM_MARGINAL_RATE = "maximum_marginal_rate"
BASIS_SLAB = "slab"


@dataclass(frozen=True)
class Basis:
    """Which way §167B charges this association, and the words for it."""
    basis: str
    section: str
    reason: str


#: What is left out, and the one reading that fails generous. Served on every
#: answer — a MAXIMUM MARGINAL RATE answer especially.
CAVEATS: tuple[str, ...] = (
    "§167B's other cases are not modelled: a member taxed at a rate above the "
    "maximum marginal rate, an association all of whose members are companies, "
    "a non-resident member, and the §86 exemption of a member's share. Each can "
    "change the rate.",
    "§2(29C) defines the maximum marginal rate as the rate including surcharge "
    "for the highest slab. The surcharge applied here is the one for this "
    "association's own income bracket, which is the lower figure below the top "
    "bracket; the Act's reading could not be confirmed here, so check it before "
    "filing.",
)

#: The refusal where either fact is unstated. Names both questions.
UNSTATED_REFUSAL = (
    "An association of persons or a body of individuals is charged under §167B "
    "on one of two bases and which one turns on two facts about its members "
    "that are not recorded for this client: whether the members' shares are "
    "determinate and known (§167B(1)), and, if they are, whether any member's "
    "own total income exceeds the maximum amount not chargeable to tax "
    "(§167B(2)). Where the shares are indeterminate, or any member is above "
    "the limit, the whole of its income is charged at the maximum marginal "
    "rate from the first rupee; otherwise the slab rates apply. Nothing is "
    "computed rather than guessing which."
)


def resolve_basis(
    *,
    shares_determinate: Optional[bool],
    any_member_over_exemption: Optional[bool],
) -> tuple[Optional[Basis], Optional[str]]:
    """(basis, refusal). Exactly one of the two is None.

    `shares_determinate` is asked FIRST and short-circuits: where the shares
    are indeterminate, §167B(1) charges the maximum marginal rate whatever any
    member earns, so the second fact is not needed and is not demanded — a
    caller who cannot know a member's income can still compute an association
    whose shares are indeterminate.
    """
    if shares_determinate is None:
        return None, UNSTATED_REFUSAL
    if shares_determinate is False:
        return Basis(
            BASIS_MAXIMUM_MARGINAL_RATE, "§167B(1)",
            "The members' shares are indeterminate or unknown, so §167B(1) "
            "charges the whole of the total income at the maximum marginal "
            "rate, from the first rupee and with no basic exemption."), None
    if any_member_over_exemption is None:
        return None, UNSTATED_REFUSAL
    if any_member_over_exemption:
        return Basis(
            BASIS_MAXIMUM_MARGINAL_RATE, "§167B(2)",
            "The shares are determinate, but a member's own total income "
            "exceeds the maximum amount not chargeable to tax, so §167B(2) "
            "charges the association's whole total income at the maximum "
            "marginal rate, from the first rupee and with no basic exemption."), None
    return Basis(
        BASIS_SLAB, "§167B",
        "The shares are determinate and no member's own total income exceeds "
        "the maximum amount not chargeable to tax, so the association is "
        "charged on the ordinary slab rates, without the §87A rebate, which "
        "reaches only a resident individual."), None


def maximum_marginal_rate_percent(slabs: Sequence) -> int:
    """§2(29C): the rate of the HIGHEST slab, read off the slab table in force.

    Read, not stated: the top bracket is the one with no upper limit, and a
    table that does not end in one is a defect worth a loud failure rather
    than a rate taken from the wrong row."""
    top = slabs[-1]
    if top.upto_paise is not None:
        raise ValueError(
            "the slab table does not end in an open-ended bracket, so there is "
            "no 'highest slab' to read the maximum marginal rate off")
    return int(top.rate_percent)

"""§32(1)(iia) additional depreciation — who it reaches, and what it reaches.

WHAT WAS WRONG (IT-09)

    `domain/income_tax/section_32.py` has implemented the charge since it was
    written: 20% of the actual cost of new plant and machinery, halved by the
    second proviso where the asset was put to use for less than 180 days, with
    the third proviso's carry-forward named as a gap. `Addition` carries
    `additional_depreciation_eligible` and `compute_block` branches on it.

    `services/section_32_service.py` passed `False`. Hardcoded, for every
    addition, for every client. So the §32 screen rendered a headline row
    labelled "Additional u/s 32(1)(iia)" that was structurally ₹0 — a nil
    meaning "we cannot see it" presented as a nil meaning "there was none", on
    a deduction worth a fifth of the cost of every new machine a manufacturer
    buys.

TWO FACTS, AND THEY ARE ABOUT DIFFERENT THINGS

    The section reaches "any new machinery or plant ... acquired and installed
    after the 31st day of March, 2005, BY AN ASSESSEE ENGAGED IN the business of
    manufacture or production of any article or thing or in the business of
    generation, transmission or distribution of power".

      WHO   a fact about the client's business, true of every asset they own or
            of none — `clients.section_32_1_iia_business`.
      WHAT  a fact about one row — new machinery or plant, not excluded by the
            first proviso — `fixed_assets.additional_depreciation_eligible`.

    One column asserting both would give a trading company's new forklift the
    same answer as a factory's, when the section reaches neither the company
    nor the forklift for two different reasons a reader has to tell apart.

    So there are FOUR answers, not two, and this module is the one place that
    decides between them.

NULL IS A THIRD STATE ON EACH, AND THE DIRECTIONS ARE NOT SYMMETRIC

    Assuming NOT eligible reproduces exactly the defect this closes: a silent
    nil on a real deduction, invisible because the row renders ₹0 either way.
    Assuming ELIGIBLE claims a fifth of cost the assessee may not be entitled
    to, which is a disallowance with §270A behind it. Neither is safe, so an
    unrecorded fact is NAMED and the deduction is withheld — the safe direction
    when the CA is looking at the sentence.

THE FIRST PROVISO'S FOUR EXCLUSIONS ARE ASSERTED BY THE TICK, AND SAID

    (A) plant used by any other person before its installation — second-hand;
    (B) plant installed in office premises, residential accommodation or a
        guest house;
    (C) office appliances and road transport vehicles;
    (D) plant whose whole actual cost is allowed as a deduction in one year.

    Four more columns would be four more things to fill in for one answer, so
    the asset-level tick asserts all four and every allowed answer says so —
    the Form 10-IA discipline `domain/income_tax/chapter_vi_a.py` takes with
    §80DD.

WHAT IS REFUSED RATHER THAN GUESSED

  * **Nothing infers the business.** `clients.industry` is free text and
    `business_type` is the legal form; neither answers whether an assessee is
    engaged in manufacture or production, and a keyword match on "Manufacturing"
    would claim a deduction off a label somebody typed.
  * **The THIRD proviso's carry-forward is not computed**, and `section_32`
    already names it: where the asset was put to use for less than 180 days the
    other half is allowed in the FOLLOWING previous year, which needs the prior
    year's additions and is a build of its own.
  * **The 01-04-2005 commencement is not tested**, because an asset acquired
    before it is outside every block this product holds an opening
    written-down value for in any year it could matter, and a date test on a
    `purchase_date` that may be an import artefact would refuse live claims.
    Named on the answer instead.

⚠️ `[S]`-graded: egress is refused at this environment's proxy, so the section
and its provisos are written from knowledge. `VERIFIED` is False, the rate is
pinned exactly by `tests/test_additional_depreciation_needs_two_facts.py`, and
the caveat travels on every answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Not confirmed against a Finance Act from this environment.
VERIFIED = False

#: §32(1)(iia). Twenty per cent of the ACTUAL COST — not of the written-down
#: value, and not of the block. `section_32.compute_block` applies it.
ADDITIONAL_DEPRECIATION_PERCENT = 20

UNVERIFIED_NOTE = (
    "The §32(1)(iia) rate and provisos here are recorded from knowledge, not "
    "read off the Act — this environment refuses outbound requests. Each is "
    "pinned by a test. Check them against the Finance Act before filing."
)

THE_TICK_ASSERTS_THE_PROVISO = (
    "Marking an addition eligible asserts the whole of the first proviso to "
    "§32(1)(iia): the plant was not used by any other person before the "
    "assessee installed it, it is not installed in office premises, "
    "residential accommodation or a guest house, it is not an office appliance "
    "or a road transport vehicle, and its whole actual cost is not allowed as "
    "a deduction in one year."
)

BUSINESS_NOT_RECORDED = (
    "Nobody has recorded whether this client is engaged in the business of "
    "manufacture or production of any article or thing, or in the generation, "
    "transmission or distribution of power. §32(1)(iia) reaches only such an "
    "assessee, so no additional depreciation is claimed — record it on the "
    "client to settle this. It is NOT derived from the industry or the entity "
    "type, neither of which answers the question."
)

BUSINESS_OUTSIDE_THE_SECTION = (
    "This client is recorded as not engaged in manufacture, production or "
    "power, so §32(1)(iia) does not reach any of its assets. The additional "
    "depreciation line is nil because the section does not apply, not because "
    "nothing was bought."
)

NO_ASSET_IS_MARKED = (
    "This client is within §32(1)(iia), and no addition this year is marked as "
    "new plant or machinery the first proviso does not exclude. Mark the "
    "eligible additions on the asset register; until then the additional "
    "depreciation is nil because nobody has said, not because there is none."
)

SOME_ASSETS_UNMARKED = (
    "addition(s) acquired this year have no §32(1)(iia) answer recorded, so "
    "they claim no additional depreciation. An unanswered asset is not a "
    "refused one."
)

COMMENCEMENT_NOT_TESTED = (
    "§32(1)(iia) reaches plant acquired and installed after 31 March 2005. "
    "That date is not tested here — every block this product holds is later, "
    "and a test on a purchase date that may be a migration artefact would "
    "refuse live claims."
)

THIRD_PROVISO_NOT_CARRIED_FORWARD = (
    "Where an eligible asset was put to use for less than 180 days, the third "
    "proviso allows the OTHER half of the additional depreciation in the "
    "FOLLOWING previous year. It is not carried forward here — claim it from "
    "last year's working."
)


@dataclass(frozen=True)
class Eligibility:
    """Whether §32(1)(iia) reaches this client, and what it is silent about."""
    #: True only where the client is within the section AND at least the
    #: possibility of an eligible asset exists. False means no addition claims.
    reaches_the_assessee: bool
    #: One sentence per thing nobody has recorded, in the order a CA acts on
    #: them: the business first, because it settles every asset at once.
    gaps: tuple = ()
    caveats: tuple = ()

    def to_dict(self) -> dict:
        return {
            "reaches_the_assessee": self.reaches_the_assessee,
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "verified": VERIFIED,
        }


def assessee_is_within_the_section(
    section_32_1_iia_business: Optional[bool],
) -> Eligibility:
    """The WHO half, answered from the client's own recorded fact.

    THREE STATES. `None` is not `False`: one means nobody has said and is a
    question for the CA, the other means the section does not reach this
    client and the nil on the screen is an answer. A reader must be able to
    tell them apart, which is exactly what a hardcoded `False` destroyed.
    """
    if section_32_1_iia_business is None:
        return Eligibility(reaches_the_assessee=False,
                           gaps=(BUSINESS_NOT_RECORDED,))
    if not section_32_1_iia_business:
        return Eligibility(reaches_the_assessee=False,
                           gaps=(BUSINESS_OUTSIDE_THE_SECTION,))
    return Eligibility(reaches_the_assessee=True,
                       caveats=(THE_TICK_ASSERTS_THE_PROVISO,
                                COMMENCEMENT_NOT_TESTED, UNVERIFIED_NOTE))


def addition_is_eligible(
    *,
    assessee_within_section: bool,
    asset_flag: Optional[bool],
) -> bool:
    """The WHAT half, ANDed with the WHO half.

    Both must be true. An asset ticked eligible at a client the section does
    not reach claims nothing, and that is not a contradiction to resolve: a CA
    may well mark their machines before recording the business, and the answer
    is simply nil until both are in.
    """
    return bool(assessee_within_section) and asset_flag is True


def report(
    *,
    section_32_1_iia_business: Optional[bool],
    #: One entry per addition acquired in the year: (label, the asset's own
    #: recorded answer). Order is the caller's and is preserved in the gap.
    additions: list,
) -> Eligibility:
    """The whole answer for one client-year, gaps and caveats included.

    The gaps are ORDERED by what settles the most: the business first, because
    recording it answers every asset at once, then the assets. A CA works down
    the list.
    """
    # NO ADDITION, NO QUESTION. §32(1)(iia) is 20% of the ACTUAL COST of an
    # addition, so a year with none claims nothing whatever the business is and
    # naming the unrecorded fact would be a permanent false alarm on every
    # client who bought no plant — which is how a real gap comes to be ignored.
    #
    # The same rule `section_32_service` applies to an unclassified asset
    # ("only worth naming if it would have MATTERED this year"), and the reason
    # this is a gate rather than a shorter sentence.
    if not additions:
        return Eligibility(reaches_the_assessee=False)

    who = assessee_is_within_the_section(section_32_1_iia_business)
    if not who.reaches_the_assessee:
        return who

    gaps: list = []
    unmarked = [label for label, flag in additions if flag is None]
    marked = [label for label, flag in additions if flag is True]
    if additions and not marked:
        gaps.append(NO_ASSET_IS_MARKED)
    elif unmarked:
        gaps.append(f"{len(unmarked)} " + SOME_ASSETS_UNMARKED
                    + " " + ", ".join(sorted(unmarked)[:10])
                    + ("…" if len(unmarked) > 10 else ""))
    return Eligibility(reaches_the_assessee=True, gaps=tuple(gaps),
                       caveats=who.caveats)

"""
Companies Act 2013, Schedule II Part C — the useful LIVES, and the rate derived.

WHY THIS IS A MODULE AND NOT A LITERAL IN A ROUTER

    It was a router-level table, which was fine while one endpoint served it to
    one form. It is now read by three: the categories endpoint the Add Asset
    drawer pre-fills from, the register-integrity report, and — since FA-20 —
    `services/reconciliation_service`'s nightly sweep. A service importing a
    router to reach a statutory table is the wrong direction and one refactor
    away from an import cycle, so the table moved to where both can read it.

WHAT IT IS AND IS NOT

    Schedule II prescribes a useful LIFE per class of asset. It does not
    prescribe a WDV percentage anywhere: the percentage is DERIVED from the
    life. What this replaced was a set of flat literals in which Furniture
    10.00% and Intangibles 25.00% were **Income-tax Act block rates** sitting
    under a form field labelled "Companies Act 2013 Sch II rate" — every one of
    them under-depreciating (FA-02).

    A None life means Schedule II prescribes nothing for that category, and the
    engine REFUSES rather than defaulting to a plausible rate. That refusal is
    the whole point: a plausible rate is how the Income-tax numbers got in.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# Schedule II, Part C, Note 5: "Ordinarily, the residual value of an asset is
# often insignificant but it should generally be not more than 5% of the
# original cost of the asset." Named rather than written inline because it is
# the one term in the derivation that is a statutory cap and not an input.
SCHEDULE_II_RESIDUAL_FRACTION = Decimal("0.05")

# Part C, by the Schedule's own headings. Where a heading prescribes more than
# one life the CA has a real choice, so ALL of them are offered and the first
# is only the default — a server is not a laptop and a lorry on hire is not a
# company car. A life of None means Schedule II prescribes none for that class,
# which is an ANSWER and not a missing number (see _no_statutory_basis).
PART_C: dict[str, tuple[tuple[str, Optional[int]], ...]] = {
    "Building": (
        ("Buildings (other than factory buildings) — RCC frame structure", 60),
        ("Buildings (other than factory buildings) — other than RCC frame structure", 30),
        ("Factory buildings", 30),
    ),
    "Plant & Machinery": (
        ("General rate — plant and machinery other than continuous process plant", 15),
        ("Continuous process plant", 25),
    ),
    "Furniture & Fixtures": (
        ("General furniture and fittings", 10),
        ("Furniture and fittings used in hotels, restaurants, boarding houses and similar", 8),
    ),
    "Office Equipment": (
        ("Office equipment", 5),
    ),
    "Computer & IT Equipment": (
        ("End user devices — desktops, laptops, etc.", 3),
        ("Servers and networks", 6),
    ),
    "Vehicles": (
        ("Motor cars, buses and lorries other than those used in a business of running them on hire", 8),
        ("Motor buses, lorries, cars and taxies used in a business of running them on hire", 6),
        ("Motor cycles, scooters and other mopeds", 10),
    ),
    "Land": (
        ("Land — not a depreciable asset", None),
    ),
    "Intangibles": (
        ("Amortised under AS 26 / Ind AS 38 — Schedule II Part A prescribes no life", None),
    ),
    "Other": (
        ("No Schedule II class — the CA determines the life or rate", None),
    ),
}

# Land has no useful life to spread a cost over, so Schedule II never
# depreciates it. That is a different statement from "we do not have a rate for
# it": the rate is a definite 0.00, and the SL path must honour it too.
NOT_DEPRECIABLE = frozenset({"Land"})


def wdv_rate_for_life(years: Optional[int]) -> Optional[Decimal]:
    """The Schedule II WDV rate for a useful life, to the two decimals
    fixed_assets.wdv_rate_percent (NUMERIC(5,2)) can hold.

        R = 1 − (residual/cost) ^ (1/n),  residual/cost capped at 5%

    Decimal throughout, never float: this number multiplies the WDV in every
    charge the asset will ever produce, and a binary float here is a rounding
    difference in all of them.
    """
    if not years:
        return None
    ratio = SCHEDULE_II_RESIDUAL_FRACTION ** (Decimal(1) / Decimal(years))
    return ((Decimal(1) - ratio) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# category -> the Schedule II classes it offers, each with its derived rate.
CATEGORIES: dict[str, tuple[dict, ...]] = {
    category: tuple(
        {
            "label": label,
            "useful_life_years": years,
            "wdv_rate_percent": (
                Decimal("0.00") if category in NOT_DEPRECIABLE else wdv_rate_for_life(years)
            ),
        }
        for label, years in classes
    )
    for category, classes in PART_C.items()
}


def default_class(category: Optional[str]) -> dict:
    """The class a new asset in this category gets unless the CA picks another.
    An unknown category falls through to "Other", which prescribes nothing —
    so it refuses rather than inventing a rate for a category nobody modelled."""
    classes = CATEGORIES.get(category or "Other") or CATEGORIES["Other"]
    return classes[0]


# The old name and the old shape (category -> rate), now derived from the lives
# so the two can no longer disagree. A None value means Schedule II prescribes
# no life for that category and therefore no rate — the CA supplies one.
DEFAULT_WDV_RATES: dict[str, Optional[Decimal]] = {
    category: classes[0]["wdv_rate_percent"] for category, classes in CATEGORIES.items()
}

"""
Which tax computation a client gets — IT Act 1961.

WHAT WAS MISSING
    `domain/income_tax/entity_rates.py` and `minimum_tax.py` are complete and
    tested, and until now they were imported by nothing outside their own
    package. The one computation endpoint the product has,
    POST /api/income-tax/compute, ran INDIVIDUAL slabs for every client — so a
    Private Limited company's profit was taxed nil to ₹4 lakh, 5% to ₹8 lakh,
    with a ₹60,000 §87A rebate, when a company pays 22%/25%/30% from the first
    rupee and gets no rebate at all. On the live book (4 Private Limited, 1 LLP,
    1 Partnership, 1 Proprietorship, no individuals) that endpoint fitted none
    of the clients.

    This module is the mapping that was absent: from the entity type the client
    master records to the assessee the Act taxes.

THE ONE THAT IS NOT OBVIOUS
    A PROPRIETORSHIP IS AN INDIVIDUAL. It is not a person in tax law at all —
    the proprietor is assessed, on the ordinary slabs, with §87A and the whole
    of Chapter VI-A available. Treating it as a "business entity" and charging
    30% would be as wrong in the other direction as charging a company on slabs.

WHAT IS REFUSED, AND WHY REFUSING IS THE ANSWER
    A TRUST is taxed under §§11-13 where registered under §12AB, and at the
    maximum marginal rate under §164 where it is not; a SOCIETY (a co-operative
    society) has its own rate schedule and §80P. Neither is modelled anywhere in
    this codebase. Running either through the individual slabs or through the
    firm rate would produce a confident number with no statute behind it, which
    is the failure this whole module exists to end — so the answer is a REFUSAL
    naming the sections, in the house shape (payroll's statutory_gaps, the TDS
    register's, §195's chargeability questions).

All monetary values elsewhere are integer paise. Nothing here is money.
"""
from __future__ import annotations

from typing import Literal, Optional

from services.compliance_obligation_service import normalise_entity_type

#: What the tax engines can charge. "individual" is the slab path in
#: itr_engine; the other three go to entity_rates.compute_entity_tax.
AssesseeKind = Literal["individual", "firm", "llp", "domestic_company"]

#: clients.entity_type (migration 001's CHECK, title-case with spaces) → the
#: assessee. Keys are normalise_entity_type's output, so 'Private Limited',
#: 'private_limited' and 'PRIVATE  LIMITED' are one entry — the same fold
#: compliance_obligation_service applies, and for the same reason: an
#: underscored spelling silently missing a title-case constant is a bug this
#: codebase has already had once.
_KIND_BY_ENTITY_TYPE: dict[str, AssesseeKind] = {
    # Incorporated under the Companies Act 2013. The extra spellings are
    # recognised so that adding one to the CHECK cannot silently drop a real
    # company onto the individual slabs — the same defensive set
    # compliance_obligation_service keeps for the §139(1) due date.
    "private limited": "domestic_company",
    "public limited": "domestic_company",
    "one person company": "domestic_company",
    "opc": "domestic_company",
    "section 8": "domestic_company",
    "llp": "llp",
    "partnership": "firm",
    # A proprietorship is the proprietor. See the module docstring.
    "proprietorship": "individual",
    "individual": "individual",
}

#: Entity types the Act taxes on a basis this codebase does not model. The
#: value is the sentence the caller shows — it names the sections, so a CA
#: reading it knows what is missing rather than that something is.
_REFUSED: dict[str, str] = {
    "trust": (
        "A trust is taxed under §§11 to 13 where it is registered under §12AB, "
        "and at the maximum marginal rate under §164 where it is not. Neither "
        "basis is modelled here, and computing it on the individual slabs would "
        "produce a figure with no section behind it."
    ),
    "society": (
        "A co-operative society has its own rate schedule and the §80P "
        "deduction, neither of which is modelled here. Computing it on the "
        "individual slabs or the firm rate would produce a figure with no "
        "section behind it."
    ),
}


def assessee_kind_for_entity_type(
    entity_type: Optional[str],
) -> tuple[Optional[AssesseeKind], Optional[str]]:
    """(kind, refusal). Exactly one of the two is None.

    An UNKNOWN or absent entity type is refused too, rather than defaulting to
    "individual". The default is what produced the defect: every client, whatever
    it was, got the individual slabs, and nothing said so.
    """
    key = normalise_entity_type(entity_type)
    if not key:
        return None, (
            "This client has no entity type recorded, and the tax basis depends "
            "entirely on it — a company pays from the first rupee and an "
            "individual does not. Set the entity type on the client record."
        )
    if key in _KIND_BY_ENTITY_TYPE:
        return _KIND_BY_ENTITY_TYPE[key], None
    if key in _REFUSED:
        return None, _REFUSED[key]
    return None, (
        f"Entity type {entity_type!r} has no tax basis recorded in this "
        f"software. Nothing is computed for it rather than guessing one."
    )


def is_entity(kind: AssesseeKind) -> bool:
    """Whether this assessee is charged at a flat entity rate rather than slabs."""
    return kind in ("firm", "llp", "domestic_company")

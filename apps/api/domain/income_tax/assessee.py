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

A HUF, AN AOP AND A BOI ARE NOT INDIVIDUALS (TDS-INCOME-TAX-16)
    `clients.entity_type` had no value for any of them, so each was recorded as
    "Individual" and computed on the individual slabs WITH the §87A rebate, the
    §16(ia) standard deduction and the senior-citizen slab. None of the three is
    theirs: §87A reaches "an assessee, being an individual resident in India",
    §16(ia) is a deduction from SALARY (a family and an association have no
    employer), and the higher basic exemption at 60 and 80 is for "every
    individual". Migration 453 lets the three be recorded; `domain/income_tax/relief_reach.py`
    says who each relief reaches, by the section's own words, and the engine
    asks it rather than testing a kind by name.

    A HUF otherwise takes the individual's slab path and the §115BAC(1A)
    regimes. An AOP or a BOI takes the slab path ONLY where §167B lets it
    (`domain/income_tax/aop_boi.py`) and is otherwise charged on its whole total
    income at the maximum marginal rate — which depends on two facts about its
    members that no record here holds, so they are inputs to the computation and
    an unstated one is REFUSED rather than assumed.

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

from typing import Literal, Optional, get_args

from services.compliance_obligation_service import normalise_entity_type

#: What the tax engines can charge. "individual", "huf", "aop" and "boi" are
#: the slab path in itr_engine (with the differences `relief_reach.RELIEF_REACH` records, and
#: §167B's for the last two); the other three go to
#: entity_rates.compute_entity_tax. The lower-case spellings are the ones
#: `domain/income_tax/minimum_tax` already uses for the same assessees.
AssesseeKind = Literal["individual", "huf", "aop", "boi",
                       "firm", "llp", "domestic_company"]

#: The kinds that take the slab path. Written once so no caller tests a kind by
#: name and a fifth added later is a decision rather than a fall-through.
SLAB_KINDS: tuple[str, ...] = ("individual", "huf", "aop", "boi")

#: Every kind, DERIVED from the Literal so a request model that must say which
#: it will accept cannot hold a second list — the router's check was a
#: hand-typed tuple of four, which would have refused all three new kinds.
ALL_ASSESSEE_KINDS: tuple[str, ...] = get_args(AssesseeKind)

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
    # Migration 453. The long spellings are recognised so that a client typed
    # or imported as "Hindu Undivided Family" cannot fall to the refusal below
    # and so look like an entity this software has no basis for.
    "huf": "huf",
    "hindu undivided family": "huf",
    "aop": "aop",
    "association of persons": "aop",
    "boi": "boi",
    "body of individuals": "boi",
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


#: The sentence a screen shows BEFORE anything is computed, for the three
#: assessees whose basis is not the individual's. Served with the assessee kind
#: so the screen holds no statute. The AOP/BOI note names §167B's two questions
#: rather than a rate, because which rate applies is the CA's answer to them.
BASIS_NOTE: dict[str, str] = {
    "huf": ("Taxed on the slabs under either regime, like an individual, but "
            "without the §87A rebate, the §16(ia) standard deduction or the "
            "senior-citizen slab, none of which a Hindu undivided family gets."),
    "aop": ("Charged under §167B: at the maximum marginal rate on the whole "
            "income where the members' shares are indeterminate or a member's "
            "own income is above the exemption limit, and on the slabs "
            "otherwise — without the §87A rebate. Answer the two questions "
            "below."),
    "boi": ("Charged under §167B: at the maximum marginal rate on the whole "
            "income where the members' shares are indeterminate or a member's "
            "own income is above the exemption limit, and on the slabs "
            "otherwise — without the §87A rebate. Answer the two questions "
            "below."),
}


#: The ITR form a NEW filing starts on, by assessee — a STARTING POINT the CA
#: can change in the picker, never a computed answer, and SERVED by
#: `GET /api/income-tax/assessee-kind` so the filing screen holds a fallback
#: and not a rule. The individual's is ITR-3 because a proprietorship (which is
#: an individual) most often has business income here. A HUF starts on ITR-2:
#: ITR-1 is for an individual alone, and the commoner HUF holds investments or
#: property and has no business — one that does moves to ITR-3 in the picker.
#: An AOP and a BOI file ITR-5 with the firms and LLPs. Form ELIGIBILITY is not
#: enforced anywhere (any of the seven is accepted for any client); this is
#: where a client's filing starts, not what it may file.
DEFAULT_ITR_FORM: dict[str, str] = {
    "individual": "ITR-3",
    "huf": "ITR-2",
    "aop": "ITR-5",
    "boi": "ITR-5",
    "firm": "ITR-5",
    "llp": "ITR-5",
    "domestic_company": "ITR-6",
}


#: Entity types the Act treats as necessarily carrying business or
#: professional income — the proprietor's whole assessment IS the business,
#: and a firm or an LLP is one by its own constitution. §115BAC(6)'s two
#: clauses turn on exactly this fact (Form 10-IEA where there is business
#: income, the return itself where there is not — see
#: domain/income_tax/regime_election.py's own docstring), so a screen that
#: waits for a CA to type a nonzero business-income figure before treating a
#: Proprietorship, Partnership or LLP client that way is wrong from the
#: moment it opens. `_KIND_BY_ENTITY_TYPE` maps every one of these three to
#: "individual" or "firm"/"llp" already; this set names which of THOSE keys
#: carry business income by construction — an ordinary salaried "individual"
#: does not, so `assessee_kind` alone cannot answer this question and a
#: second table is needed.
_ENTITY_TYPES_IMPLYING_BUSINESS_INCOME: frozenset[str] = frozenset({
    "proprietorship", "partnership", "llp",
})


def implies_business_income(entity_type: Optional[str]) -> bool:
    """Whether this entity type carries business/professional income by
    definition, independent of any figure a CA has or has not typed yet.

    Statutory knowledge, so it lives here rather than being re-derived from
    the raw `clients.entity_type` string in the browser — CLAUDE.md, "zero
    business logic in the frontend" — and `GET /api/income-tax/assessee-kind`
    serves it alongside the assessee kind so the computation screen has both
    answers from the one call it already makes.
    """
    key = normalise_entity_type(entity_type)
    return bool(key) and key in _ENTITY_TYPES_IMPLYING_BUSINESS_INCOME

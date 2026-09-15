"""
HOW LONG A BROUGHT-FORWARD LOSS LIVES — and it is NOT eight years for all of them.

`domain/income_tax/loss_set_off.py` decides WHICH HEAD a carried-forward loss
may reach. This module decides HOW LONG it may be carried, which is a different
question with a different section per head, and it exists because
`brought_forward_losses.expiry_assessment_year` has always been supplied BY THE
CALLER — so the one statutory fact in the row was whatever somebody typed.

THE PERIODS, AND THE ONE THAT IS NOT EIGHT

    business            §72(3)   EIGHT assessment years immediately succeeding
                                 the year the loss was first computed.
    speculation         §73(4)   FOUR. Not eight. A speculation business is a
                                 business, the loss sits in the same table, and
                                 the period is different — which is exactly the
                                 shape that gets copied wrong.
    capital_short_term  §74(2)   EIGHT.
    capital_long_term   §74(2)   EIGHT.
    house_property      §71B     EIGHT.
    other               —        the head is not identified, so no section
                                 applies and no period can be derived. REFUSED
                                 and named, never defaulted to eight.

    `loss_set_off._is_available`'s refusal used to say "§72(3)/§74's eight
    assessment years" for EVERY head, speculation included. Two heads named in
    a sentence about a third is how four becomes eight.

WHAT IS NOT MODELLED, AND SAYS SO RATHER THAN BEING APPROXIMATED
    §32(2) unabsorbed depreciation and §73A's loss of a specified business are
    both carried forward INDEFINITELY, and neither is in the stored vocabulary
    (`loss_set_off.KNOWN_LOSS_TYPES`, pinned to migration 319's CHECK). A CA
    holding one has no row to put it in, and inventing `other` + a made-up
    expiry would be worse than the gap: it would silently expire a loss the Act
    never expires. NAMED in `NOT_MODELLED` so the screen can say so.

⚠️ GRADE
    Every period here is `[S]` — written from knowledge, because direct egress
    is refused at this environment's proxy and incometax.gov.in cannot be
    opened. `VERIFIED` is False for exactly that reason, and every figure is
    pinned by a test so a later correction is a deliberate edit rather than a
    drift. THE ERROR DIRECTION IS NOT SAFE IN EITHER SENSE — a period too
    short expires relief the client is entitled to, and one too long claims
    relief they are not — which is why nothing here is a fallback and the
    derived value is a SUGGESTION the caller may override.

WHY IT DERIVES RATHER THAN REFUSES
    A caller-supplied expiry still wins, the shape `domain/tds/deductor.resolve`
    uses. The derivation exists so the CA is not asked to do eight-year
    arithmetic on a form; it does not exist to overrule them.
"""
from __future__ import annotations

from dataclasses import dataclass

#: False, and it stays False until somebody reads the sections. See ⚠️ above.
VERIFIED = False


@dataclass(frozen=True)
class CarryForwardRule:
    loss_type: str
    section: str
    #: Assessment years the loss may be carried INTO, counted from the year it
    #: was first computed. None where no period can be derived.
    years: int | None
    note: str


_RULES: dict[str, CarryForwardRule] = {
    r.loss_type: r for r in (
        CarryForwardRule("business", "§72(3)", 8,
                         "Eight assessment years immediately succeeding the year "
                         "the loss was first computed, and set off only against "
                         "business income."),
        CarryForwardRule("speculation", "§73(4)", 4,
                         "FOUR assessment years, not eight — a speculation loss "
                         "carries a shorter period than an ordinary business "
                         "loss, and reaches only speculation income."),
        CarryForwardRule("capital_short_term", "§74(2)", 8,
                         "Eight assessment years, against capital gains only."),
        CarryForwardRule("capital_long_term", "§74(2)", 8,
                         "Eight assessment years, against LONG-TERM capital "
                         "gains only."),
        CarryForwardRule("house_property", "§71B", 8,
                         "Eight assessment years, against income from house "
                         "property only."),
        CarryForwardRule("other", "—", None,
                         "The head is not identified, so no section fixes a "
                         "period. Record the last assessment year this loss may "
                         "be set off in."),
    )
}

#: Carried forward INDEFINITELY and absent from the stored vocabulary. Named so
#: a screen can say why there is no row for them, rather than inviting a CA to
#: file one under `other` with an expiry that would end it.
NOT_MODELLED: dict[str, str] = {
    "§32(2) unabsorbed depreciation":
        "carried forward indefinitely, with no expiry at all. There is no loss "
        "type for it here, and recording it as another type would expire it.",
    "§73A loss of a specified business":
        "carried forward indefinitely under §73A(2). Not in the stored "
        "vocabulary either.",
}


def rule_for(loss_type: str) -> CarryForwardRule | None:
    """The rule for a stored loss type, or None if it is not one of them."""
    return _RULES.get(str(loss_type or "").strip().lower())


def known_types() -> list[CarryForwardRule]:
    """Every rule, in the order a form should offer them."""
    return list(_RULES.values())


def _ay_start_year(assessment_year: str | None) -> int | None:
    """The opening year of an 'AAAA-BB' label, or None if it is not one.

    Deliberately the same reading as `loss_set_off._ay_end_year` takes, one
    year earlier: both parse the first four characters and nothing else, so a
    label the FYLabel/AYLabel validators already accepted cannot be read two
    ways by two modules.
    """
    text = str(assessment_year or "").strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4])


def expiry_for(loss_type: str, assessment_year: str) -> tuple[str | None, str]:
    """(last assessment year this loss may be set off in, the reason).

    The LAST year it is still available, matching what
    `loss_set_off._is_available` compares against — a loss whose expiry equals
    the computation's own assessment year is still usable, and one year later
    is not.

    Returns (None, reason) where no period can be derived: an unknown loss
    type, an unparseable year, or `other`, whose head is not identified. None
    is never a quiet zero — the caller must either carry the reason or take
    the CA's own figure.
    """
    rule = rule_for(loss_type)
    if rule is None:
        return None, (f"'{loss_type}' is not a loss type this product stores, so "
                      f"no carry-forward period applies to it.")
    if rule.years is None:
        return None, rule.note
    start = _ay_start_year(assessment_year)
    if start is None:
        return None, (f"'{assessment_year}' is not an assessment year label, so "
                      f"the {rule.section} period cannot be counted from it.")
    last = f"{start + rule.years}-{str(start + rule.years + 1)[-2:]}"
    return last, (f"{rule.section}: {rule.years} assessment years from "
                  f"{assessment_year}, so the last one it may be set off in is "
                  f"{last}.")

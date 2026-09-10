"""Setting off a BROUGHT-FORWARD loss — which head it may reach, and which it may not.

IT-10. brought_forward_losses has existed since migration 156, create_bf_loss
and utilize_bf_loss write it, POST /api/itr/bf-losses records one and the
computation screen DISPLAYS them — and ITRComputeRequest had no field for them
at all, so ITREngine.compute never read one. A CA could record a carried-forward
loss, see it on the screen, and watch it change the computed tax by exactly
nothing.

WHY THIS IS A MODULE AND NOT A LINE IN THE ENGINE

A brought-forward loss is not one rule. Each head carries its own section, and
the sections differ in what they will reach:

    business            §72     against business income ONLY. Not salary — a
                                carried-forward business loss has never been
                                available against salary, and §71(2A) bars even
                                the CURRENT year's.
    speculation         §73     against SPECULATION income only, which is a
                                separate head this engine does not model.
                                REFUSED rather than set off against ordinary
                                business income, which is the mistake §73(1)
                                exists to prevent.
    capital_short_term  §74(1)(a)  against capital gains — short OR long.
    capital_long_term   §74(1)(b)  against LONG-TERM capital gains only.
    house_property      §71B    against income from house property only.
    other               —       the head is not identified, so no section can
                                be applied. REFUSED and named.

THE RULE THAT MATTERS MOST, BECAUSE GETTING IT WRONG IS EXPENSIVE AND QUIET

A capital loss does not relieve other income. §71(3) says it for the current
year and §74 carries it forward on the same terms, and the engine already
floors each capital head at zero for exactly this reason — the comment there
records a ₹5,00,000 short-term loss against a ₹20,00,000 salary cutting the
year's tax from ₹1,92,400 to ₹88,400. A brought-forward capital loss allowed
to touch salary would reopen that hole from the other side, and it would look
entirely reasonable on the screen.

ORDER, AND WHY IT IS NOT ARBITRARY

Long-term losses are set off BEFORE short-term ones. A long-term loss can only
ever reach long-term gains (§74(1)(b)); a short-term loss can reach either
(§74(1)(a)). Taking the short-term one first can consume the long-term gain
that was the long-term loss's only home, and strand it for another year — the
same relief, deferred, for no reason but ordering.

WHAT THIS MODULE WILL NOT DECIDE

§139(3) with §80: a loss may be carried forward only if the return for the year
of the loss was furnished by the §139(1) due date. That is a fact about a PAST
return, and the row's `source_itr_ack` is the only trace of it the product
holds. A loss with no acknowledgement is set off and WARNED about, never
silently disallowed: the CA knows whether they filed on time and the software
does not, and refusing on absence would deny relief that is very often due.
"""
from __future__ import annotations

from dataclasses import dataclass, field


#: The stored vocabulary — brought_forward_losses_loss_type_check (migration
#: 319 records what production enforces). Kept as a constant so a type added to
#: the CHECK without a rule here fails loudly rather than falling through.
KNOWN_LOSS_TYPES = frozenset({
    "business", "speculation", "capital_short_term",
    "capital_long_term", "house_property", "other",
})


@dataclass(frozen=True)
class BroughtForwardLoss:
    """One row of brought_forward_losses, as the engine needs it."""
    loss_type: str
    #: What is left of it — remaining_amount_paise, not the original.
    amount_paise: int
    assessment_year: str | None = None
    #: The LAST assessment year in which the loss may still be set off,
    #: inclusive. §72(3) allows eight assessment years immediately succeeding
    #: the one the loss was first computed for, and the column stores the end
    #: of that run rather than the year after it.
    expiry_assessment_year: str | None = None
    is_expired: bool = False
    #: The acknowledgement of the return that first reported the loss. Its
    #: absence is a warning, never a refusal — see the module docstring.
    source_itr_ack: str | None = None


@dataclass(frozen=True)
class SetOffLine:
    """What happened to one loss, and under which section."""
    loss_type: str
    section: str
    offered_paise: int
    set_off_paise: int
    carried_forward_paise: int
    against: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass
class SetOffResult:
    business_income_paise: int
    house_property_income_paise: int
    stcg_paise: int
    ltcg_paise: int
    ltcg_other_paise: int
    total_set_off_paise: int = 0
    lines: list[SetOffLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ay_end_year(assessment_year: str | None) -> int | None:
    """The closing year of an 'AAAA-BB' label, or None if it is not one."""
    text = str(assessment_year or "").strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4]) + 1


def _is_available(loss: BroughtForwardLoss, assessment_year: str | None) -> tuple[bool, str]:
    if loss.is_expired:
        return False, (f"The loss is marked expired, so §72(3)/§74's eight "
                       f"assessment years have run out and it is no longer "
                       f"available.")
    if loss.amount_paise <= 0:
        return False, "Nothing remains of this loss to set off."
    here = _ay_end_year(assessment_year)
    last = _ay_end_year(loss.expiry_assessment_year)
    if here is not None and last is not None and here > last:
        return False, (f"The loss could be carried forward only to "
                       f"{loss.expiry_assessment_year}, and this computation is "
                       f"for {assessment_year}.")
    return True, ""


def apply_brought_forward_losses(
    *,
    losses: list[BroughtForwardLoss],
    business_income_paise: int,
    house_property_income_paise: int,
    stcg_paise: int,
    ltcg_paise: int,
    ltcg_other_paise: int,
    assessment_year: str | None = None,
) -> SetOffResult:
    """Set each loss off against the head its own section allows, and no other.

    The head figures come in ALREADY floored at zero by the caller: §71(3)
    denies a current-year capital loss any relief against other income, and a
    negative head here would let a brought-forward loss appear to create one.
    """
    result = SetOffResult(
        business_income_paise=business_income_paise,
        house_property_income_paise=house_property_income_paise,
        stcg_paise=stcg_paise,
        ltcg_paise=ltcg_paise,
        ltcg_other_paise=ltcg_other_paise,
    )

    def _record(loss: BroughtForwardLoss, section: str, used: int,
                against: tuple[str, ...], reasons: list[str]) -> None:
        result.total_set_off_paise += used
        result.lines.append(SetOffLine(
            loss_type=loss.loss_type, section=section,
            offered_paise=max(0, loss.amount_paise), set_off_paise=used,
            carried_forward_paise=max(0, loss.amount_paise) - used,
            against=against, reasons=tuple(reasons),
        ))

    # LONG-TERM FIRST. A long-term loss has only one home; a short-term one has
    # two. Taking the short-term loss first can eat the long-term gain and
    # strand the long-term loss for another year.
    order = {"capital_long_term": 0, "capital_short_term": 1}
    for loss in sorted(losses, key=lambda l: order.get(l.loss_type, 2)):
        kind = str(loss.loss_type or "").strip().lower()
        offered = max(0, loss.amount_paise)

        if kind not in KNOWN_LOSS_TYPES:
            _record(loss, "—", 0, (), [
                f"'{loss.loss_type}' is not a loss type this engine has a rule "
                f"for, so no section can be applied to it and nothing is set "
                f"off. Record it under one of: "
                f"{', '.join(sorted(KNOWN_LOSS_TYPES))}."])
            result.warnings.append(
                f"A brought-forward loss of an unknown type ('{loss.loss_type}') "
                f"was not set off.")
            continue

        available, why_not = _is_available(loss, assessment_year)
        if not available:
            _record(loss, _SECTION_FOR.get(kind, "—"), 0, (), [why_not])
            continue

        if loss.source_itr_ack in (None, ""):
            result.warnings.append(
                f"The {kind.replace('_', ' ')} loss carries no acknowledgement of "
                f"the return that first reported it. §139(3) with §80 allows a "
                f"loss to be carried forward only where that return was furnished "
                f"by the §139(1) due date — it has been set off, and that is the "
                f"one fact to confirm before filing.")

        if kind == "business":
            used = min(offered, result.business_income_paise)
            result.business_income_paise -= used
            _record(loss, "§72", used, ("business",), [
                f"§72 allows a carried-forward business loss against the profits "
                f"and gains of business or profession, and nothing else — not "
                f"salary, which §71(2A) bars even for the current year."])

        elif kind == "speculation":
            _record(loss, "§73", 0, (), [
                "§73(1) allows a speculation loss to be set off only against "
                "profits of another SPECULATION business. This engine does not "
                "model speculation as a separate head, so it is carried forward "
                "in full rather than set off against ordinary business income — "
                "which is the very thing the section prevents."])
            result.warnings.append(
                "A brought-forward speculation loss was carried forward rather "
                "than set off: §73 needs a speculation-income head this "
                "computation does not hold.")

        elif kind == "house_property":
            used = min(offered, result.house_property_income_paise)
            result.house_property_income_paise -= used
            _record(loss, "§71B", used, ("house_property",), [
                "§71B carries a house-property loss forward for eight "
                "assessment years, to be set off against income under that "
                "head and no other."])

        elif kind == "capital_long_term":
            remaining = offered
            against: list[str] = []
            for name in ("ltcg", "ltcg_other"):
                if remaining <= 0:
                    break
                have = getattr(result, f"{name}_paise")
                used = min(remaining, have)
                if used:
                    setattr(result, f"{name}_paise", have - used)
                    remaining -= used
                    against.append(name)
            _record(loss, "§74(1)(b)", offered - remaining, tuple(against), [
                "§74(1)(b) allows a long-term capital loss to be set off only "
                "against a LONG-TERM capital gain. Short-term gains are not "
                "available to it, and no other head is."])

        elif kind == "capital_short_term":
            remaining = offered
            against = []
            for name in ("stcg", "ltcg", "ltcg_other"):
                if remaining <= 0:
                    break
                have = getattr(result, f"{name}_paise")
                used = min(remaining, have)
                if used:
                    setattr(result, f"{name}_paise", have - used)
                    remaining -= used
                    against.append(name)
            _record(loss, "§74(1)(a)", offered - remaining, tuple(against), [
                "§74(1)(a) allows a short-term capital loss against capital "
                "gains of either kind — but under no other head. §71(3) denies "
                "a capital loss any relief against salary, business or other "
                "income, and §74 carries it forward on the same terms."])

        else:   # "other"
            _record(loss, "—", 0, (), [
                "The head this loss arose under is not identified, so no "
                "section can be applied to it. Record it as business, "
                "speculation, house property or capital (short or long) and it "
                "will be set off under §72, §73, §71B or §74."])
            result.warnings.append(
                "A brought-forward loss recorded as 'other' was not set off: "
                "its head decides which section reaches it.")

    return result


_SECTION_FOR = {
    "business": "§72",
    "speculation": "§73",
    "house_property": "§71B",
    "capital_short_term": "§74(1)(a)",
    "capital_long_term": "§74(1)(b)",
    "other": "—",
}

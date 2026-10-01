"""Income from house property — IT Act 1961 §§22 to 27 (TDS-INCOME-TAX-14).

WHAT WAS MISSING
    House property was ONE typed figure, with a leading minus for a loss
    (`ITRComputeRequest.house_property_income_paise`). There was no rent
    received, no municipal tax, no net annual value, no 30% deduction under
    §24(a), no §24(b) interest — pre-construction instalments included — no
    co-owner share, no self-occupied cap and no deemed let-out, so the head was
    worked out on paper and typed in pre-netted. Rental income is one of the
    commonest items on an individual's return.

    This module is the working. It reads nothing and writes nothing, takes the
    CA's figures for each property and returns the income or loss PER PROPERTY
    and for the head, with every limit that bit and every fact it could not
    establish. The result FEEDS the computation: the screen puts the head figure
    in the box the engine has always read, after the CA looks at it.

THE RULES, IN THE ORDER THEY ARE APPLIED
    §22/§23(1)  Annual value. A LET-OUT house's gross annual value is the
                higher of the EXPECTED rent (the higher of municipal value and
                fair rent, but not above the STANDARD rent where a rent-control
                law fixes one) and the rent actually RECEIVABLE; the proviso
                (§23(1)(c)) takes the rent actually receivable instead where
                the house stood vacant for part of the year and that was the
                reason it fell short of expected rent. UNREALISED rent comes
                off the rent receivable only where Rule 4's conditions are met.
    §23(1)      Net annual value: gross less municipal taxes the owner PAID
                during the year.
    §23(2)      A SELF-OCCUPIED house's annual value is NIL, and with no annual
                value there is no municipal-tax deduction and no 30%.
                Two houses may be so treated (§23(2) as amended w.e.f. AY
                2020-21); a third is DEEMED LET-OUT under §23(4)(b) and is
                valued at its expected rent.
    §24(a)      30% of the net annual value, on a let-out or deemed let-out
                house.
    §24(b)      Interest on borrowed capital, on the ACCRUAL basis. On a
                let-out house it is allowed in full. On a SELF-OCCUPIED house it
                is capped — ₹2,00,000 where the capital was borrowed on or after
                1-4-1999 to ACQUIRE or CONSTRUCT and the house was completed
                within five years of the end of the year it was borrowed, and
                ₹30,000 otherwise — across BOTH self-occupied houses together,
                and under §115BAC it is not allowed at all.
                Interest for the period BEFORE the year of completion is
                aggregated and allowed in FIVE EQUAL instalments from the year
                of completion (the Explanation to §24(b)), and those instalments
                sit inside the same cap on a self-occupied house.
    §26         Co-owners with definite shares are each assessed on their own
                share, so the property-level figures are scaled by the share.
                `interest_paise` is NOT scaled: it is the interest attributable
                to THIS owner, because a joint loan's interest is split by who
                pays it and not necessarily by title.

WHAT THE HEAD'S TOTAL DOES NOT DO
    A loss is reported as a loss. Whether it may be set off against other heads
    — capped at ₹2,00,000 by §71(3A) under the old regime, not at all under
    §115BAC(2) — is the ENGINE's rule (`itr_engine`, which already applies it
    to the figure it is given and says so in its warnings). Restating it here
    would be a second implementation of a rule that has one.

REFUSALS, NOT GUESSES
    * A third self-occupied house is refused: §23(4)(b) lets the ASSESSEE choose
      which two, the choice changes the tax, and nothing here knows which two
      are most valuable to this client. Mark the third (and any other) as
      deemed let-out.
    * A deemed let-out house with rent entered is refused: rent receivable means
      it is let out.
    * A self-occupied house with no loan dates is capped at ₹30,000 and the
      answer says why — the lower limit cannot under-state income.
    * Unrealised rent is NOT deducted unless Rule 4's conditions are stated as
      met, and the figure is named.

NOT MODELLED, AND NAMED ON EVERY ANSWER (`NOT_MODELLED`)
    Arrears of rent and unrealised rent recovered (§25A, §25B), the property let
    with furniture or services (income from other sources), a house used for
    business or profession (§22 proviso), a house held as stock-in-trade
    (§23(5)), a part-year of self occupation, and the transfer of a house
    between co-owners mid-year.

⚠️ EVERY SECTION'S WORDING IS `[S]`-GRADED. Egress is refused here, so the Act
was not read; `VERIFIED` is False and each constant is pinned exactly by
`tests/test_a_house_property_worksheet_works_the_head_out.py`.

All amounts are integer paise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.ist_clock import normalise_fy_label
from domain.money_text import whole_rupees

VERIFIED = False

USE_LET_OUT = "let_out"
USE_SELF_OCCUPIED = "self_occupied"
USE_DEEMED_LET_OUT = "deemed_let_out"
USES = (USE_LET_OUT, USE_SELF_OCCUPIED, USE_DEEMED_LET_OUT)

PURPOSE_ACQUIRE_OR_CONSTRUCT = "acquire_construct"
PURPOSE_REPAIR_OR_RECONSTRUCT = "repair_renew_reconstruct"
PURPOSES = (PURPOSE_ACQUIRE_OR_CONSTRUCT, PURPOSE_REPAIR_OR_RECONSTRUCT)

#: §24(a).
STANDARD_DEDUCTION_BPS = 3_000
#: §24(b), second proviso and first proviso.
SELF_OCCUPIED_INTEREST_CAP_PAISE = 2_00_000_00
SELF_OCCUPIED_INTEREST_LOWER_CAP_PAISE = 30_000_00
#: The loan must be taken on or after this date for the higher cap.
HIGHER_CAP_LOANS_FROM = date(1999, 4, 1)
#: Completion within this many years of the end of the year of borrowing.
COMPLETION_WINDOW_YEARS = 5
#: The Explanation to §24(b): five equal instalments.
PRE_CONSTRUCTION_INSTALMENTS = 5
#: §23(2)(b) as amended: the number of houses that may be treated as
#: self-occupied with a nil annual value.
MAX_SELF_OCCUPIED_HOUSES = 2

NOT_MODELLED: tuple[str, ...] = (
    "Arrears of rent and unrealised rent later recovered (§25A, §25B) are not "
    "modelled; each is taxed in the year of receipt, with a 30% deduction.",
    "A house let with furniture or services, a house used for the owner's own "
    "business or profession (§22 proviso), a house held as stock-in-trade "
    "(§23(5)) and a part-year of self occupation are not modelled.",
    "Whether a loss may be set off against other income is the computation's "
    "rule (§71(3A) under the old regime, nothing under §115BAC(2)), not this "
    "worksheet's: the head's figure is reported as it is.",
)


class WorksheetRefused(ValueError):
    """The worksheet cannot be worked on what was entered. The message names
    the property and says what to change."""


@dataclass(frozen=True)
class Property:
    key: str
    name: str
    use: str
    #: This owner's share of the property, in basis points (§26).
    share_bps: int = 10_000
    # Annual figures for the WHOLE property; scaled by the share.
    municipal_value_paise: int = 0
    fair_rent_paise: int = 0
    standard_rent_paise: Optional[int] = None
    rent_receivable_paise: int = 0
    unrealised_rent_paise: int = 0
    #: Rule 4's conditions for unrealised rent. None is "nobody said", which is
    #: treated as not met and named.
    unrealised_rent_rule_4_met: Optional[bool] = None
    vacant_part_of_year: bool = False
    municipal_tax_paid_paise: int = 0
    # THIS owner's interest, not scaled.
    interest_paise: int = 0
    pre_construction_interest_paise: int = 0
    #: The financial year the house was acquired or completed — the first of the
    #: five instalments. "2023-24".
    completion_fy: Optional[str] = None
    loan_taken_on: Optional[date] = None
    completed_on: Optional[date] = None
    loan_purpose: Optional[str] = None


@dataclass
class PropertyResult:
    key: str
    name: str
    use: str
    share_bps: int
    gross_annual_value_paise: int = 0
    municipal_tax_paise: int = 0
    net_annual_value_paise: int = 0
    standard_deduction_paise: int = 0
    interest_claimed_paise: int = 0
    interest_allowed_paise: int = 0
    interest_disallowed_paise: int = 0
    pre_construction_instalment_paise: int = 0
    pre_construction_instalment_number: Optional[int] = None
    income_paise: int = 0
    workings: list = field(default_factory=list)
    gaps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "use": self.use,
            "share_bps": self.share_bps,
            "gross_annual_value_paise": self.gross_annual_value_paise,
            "municipal_tax_paise": self.municipal_tax_paise,
            "net_annual_value_paise": self.net_annual_value_paise,
            "standard_deduction_paise": self.standard_deduction_paise,
            "interest_claimed_paise": self.interest_claimed_paise,
            "interest_allowed_paise": self.interest_allowed_paise,
            "interest_disallowed_paise": self.interest_disallowed_paise,
            "pre_construction_instalment_paise": self.pre_construction_instalment_paise,
            "pre_construction_instalment_number": self.pre_construction_instalment_number,
            "income_paise": self.income_paise,
            "workings": list(self.workings), "gaps": list(self.gaps),
        }


@dataclass
class HousePropertyResult:
    fy: str
    use_new_regime: bool
    properties: list = field(default_factory=list)
    head_income_paise: int = 0
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    @property
    def is_loss(self) -> bool:
        return self.head_income_paise < 0

    def to_dict(self) -> dict:
        return {
            "fy": self.fy, "use_new_regime": self.use_new_regime,
            "properties": [p.to_dict() for p in self.properties],
            "head_income_paise": self.head_income_paise,
            "is_loss": self.is_loss,
            "gaps": list(self.gaps), "caveats": list(self.caveats),
            "not_modelled": list(NOT_MODELLED),
            "verified": VERIFIED,
        }


def _scaled(value: int, share_bps: int) -> int:
    """A property-level figure taken at this owner's share. Floors: every
    figure scaled here is either income (so flooring cannot under-declare the
    owner's share of it) or a deduction taken against it in the same
    proportion."""
    return value * share_bps // 10_000


def _fy_start_year(fy: str) -> int:
    return int(normalise_fy_label(fy)[:4])


def _self_occupied_cap(p: Property, result: PropertyResult) -> int:
    """§24(b)'s cap for ONE self-occupied house, and why.

    ₹2,00,000 needs three facts: borrowed to acquire or construct (not to
    repair), borrowed on or after 1-4-1999, and completed within five years of
    the end of the financial year of borrowing. Where any is absent or unknown
    the LOWER cap is taken — which cannot understate income — and the answer
    names which fact was missing.
    """
    if p.loan_purpose == PURPOSE_REPAIR_OR_RECONSTRUCT:
        result.workings.append(
            "Capital borrowed for repair, renewal or reconstruction: the "
            "interest is capped at ₹30,000 (§24(b), first proviso).")
        return SELF_OCCUPIED_INTEREST_LOWER_CAP_PAISE
    missing = []
    if p.loan_purpose != PURPOSE_ACQUIRE_OR_CONSTRUCT:
        missing.append("what the loan was for")
    if p.loan_taken_on is None:
        missing.append("the date the loan was taken")
    if p.completed_on is None:
        missing.append("the date the house was completed")
    if missing:
        result.gaps.append(
            f"{p.name}: {', '.join(missing)} not recorded, so the ₹30,000 cap "
            "was taken. It is the lower of the two caps and cannot understate "
            "income; record the facts and the ₹2,00,000 cap applies where it "
            "should.")
        return SELF_OCCUPIED_INTEREST_LOWER_CAP_PAISE
    if p.loan_taken_on < HIGHER_CAP_LOANS_FROM:
        result.workings.append(
            "Capital borrowed before 1-4-1999: the interest is capped at "
            "₹30,000 (§24(b), first proviso).")
        return SELF_OCCUPIED_INTEREST_LOWER_CAP_PAISE
    # The end of the financial year in which the capital was borrowed.
    loan_fy_end_year = p.loan_taken_on.year + (1 if p.loan_taken_on.month >= 4 else 0)
    deadline = date(loan_fy_end_year + COMPLETION_WINDOW_YEARS, 3, 31)
    if p.completed_on > deadline:
        result.workings.append(
            f"Completed on {p.completed_on.isoformat()}, after {deadline.isoformat()} "
            f"— {COMPLETION_WINDOW_YEARS} years from the end of the year the "
            "capital was borrowed — so the interest is capped at ₹30,000 "
            "(§24(b), first proviso).")
        return SELF_OCCUPIED_INTEREST_LOWER_CAP_PAISE
    result.workings.append(
        "Borrowed to acquire or construct on or after 1-4-1999 and completed "
        f"within {COMPLETION_WINDOW_YEARS} years: the interest is capped at "
        "₹2,00,000 (§24(b), second proviso).")
    return SELF_OCCUPIED_INTEREST_CAP_PAISE


def _pre_construction_instalment(p: Property, fy: str,
                                 result: PropertyResult) -> int:
    """This year's one-fifth of the interest paid BEFORE the house was
    completed, or 0 with the reason.

    Five EQUAL instalments, so the figure is a fifth; the odd paise land in the
    fifth so that the five add up to what was paid and nothing is lost to
    rounding."""
    total = p.pre_construction_interest_paise
    if total <= 0:
        return 0
    if not p.completion_fy:
        result.gaps.append(
            f"{p.name}: interest of this kind is recorded but not the year the "
            "house was acquired or completed, so no instalment is allowed. The "
            "Explanation to §24(b) starts the five instalments in that year.")
        return 0
    index = _fy_start_year(fy) - _fy_start_year(p.completion_fy) + 1
    if index < 1:
        result.gaps.append(
            f"{p.name}: the house is recorded as completed in {p.completion_fy}, "
            f"after FY {fy}, so no pre-construction instalment falls in this year.")
        return 0
    if index > PRE_CONSTRUCTION_INSTALMENTS:
        result.workings.append(
            f"All {PRE_CONSTRUCTION_INSTALMENTS} pre-construction instalments "
            f"were allowed by FY {_fy_label(_fy_start_year(p.completion_fy) + 4)}; "
            "none falls in this year.")
        return 0
    base = total // PRE_CONSTRUCTION_INSTALMENTS
    instalment = (total - base * (PRE_CONSTRUCTION_INSTALMENTS - 1)
                  if index == PRE_CONSTRUCTION_INSTALMENTS else base)
    result.pre_construction_instalment_number = index
    result.workings.append(
        f"Pre-construction interest: instalment {index} of "
        f"{PRE_CONSTRUCTION_INSTALMENTS} (the Explanation to §24(b)).")
    return instalment


def _fy_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _validate(properties: list[Property]) -> None:
    seen = set()
    for p in properties:
        if p.key in seen:
            raise WorksheetRefused(f"Two properties carry the key {p.key!r}.")
        seen.add(p.key)
        if p.use not in USES:
            raise WorksheetRefused(
                f"{p.name}: use must be one of {', '.join(USES)}, not {p.use!r}.")
        if not 1 <= p.share_bps <= 10_000:
            raise WorksheetRefused(
                f"{p.name}: the ownership share must be between 0.01% and 100%.")
        for label, value in (
                ("municipal value", p.municipal_value_paise),
                ("fair rent", p.fair_rent_paise),
                ("rent receivable", p.rent_receivable_paise),
                ("unrealised rent", p.unrealised_rent_paise),
                ("municipal tax paid", p.municipal_tax_paid_paise),
                ("interest", p.interest_paise),
                ("pre-construction interest", p.pre_construction_interest_paise)):
            if value < 0:
                raise WorksheetRefused(f"{p.name}: {label} cannot be negative.")
        if p.standard_rent_paise is not None and p.standard_rent_paise < 0:
            raise WorksheetRefused(f"{p.name}: standard rent cannot be negative.")
        if p.loan_purpose is not None and p.loan_purpose not in PURPOSES:
            raise WorksheetRefused(
                f"{p.name}: the loan purpose must be one of {', '.join(PURPOSES)}.")
        if p.use == USE_DEEMED_LET_OUT and p.rent_receivable_paise:
            raise WorksheetRefused(
                f"{p.name}: rent is entered against a house marked deemed "
                "let-out. Rent receivable means it IS let out — mark it so, or "
                "remove the rent.")
        if p.unrealised_rent_paise > p.rent_receivable_paise:
            raise WorksheetRefused(
                f"{p.name}: unrealised rent exceeds the rent receivable.")
    own_use = [p for p in properties if p.use == USE_SELF_OCCUPIED]
    if len(own_use) > MAX_SELF_OCCUPIED_HOUSES:
        raise WorksheetRefused(
            f"{len(own_use)} houses are marked self-occupied. §23(2) lets "
            f"{MAX_SELF_OCCUPIED_HOUSES} be treated so with a nil annual value "
            "and §23(4)(b) deems the others let out, at the assessee's option "
            "as to which two. That choice changes the tax and is the CA's: mark "
            "the others deemed let-out.")


def compute(properties: list[Property], *, fy: str,
            use_new_regime: bool) -> HousePropertyResult:
    """The head, property by property. Refuses (WorksheetRefused) rather than
    guess; names every fact it could not establish in `gaps`."""
    fy = normalise_fy_label(fy)
    _validate(properties)
    out = HousePropertyResult(fy=fy, use_new_regime=use_new_regime,
                              caveats=list(NOT_MODELLED))

    # The aggregate §24(b) cap across the self-occupied houses, shared in the
    # order the CA listed them.
    self_occupied_pool = SELF_OCCUPIED_INTEREST_CAP_PAISE

    for p in properties:
        r = PropertyResult(key=p.key, name=p.name, use=p.use, share_bps=p.share_bps)
        if p.share_bps != 10_000:
            r.workings.append(
                f"Co-owned: this owner's share is {p.share_bps / 100:g}%. The "
                "property's figures are taken at that share; the interest is "
                "this owner's own (§26).")
        instalment = _pre_construction_instalment(p, fy, r)
        r.pre_construction_instalment_paise = instalment
        claimed = p.interest_paise + instalment
        r.interest_claimed_paise = claimed

        if p.use == USE_SELF_OCCUPIED:
            r.workings.append(
                "Self-occupied: the annual value is nil (§23(2)), so there is no "
                "municipal-tax deduction and no 30% deduction (§24(a)).")
            if use_new_regime:
                allowed = 0
                if claimed:
                    r.workings.append(
                        "Interest on a self-occupied house is not allowed under "
                        "§115BAC(2): nothing is deducted.")
            else:
                cap = min(_self_occupied_cap(p, r), self_occupied_pool)
                allowed = min(claimed, cap)
                self_occupied_pool -= allowed
            r.interest_allowed_paise = allowed
            r.interest_disallowed_paise = claimed - allowed
            r.income_paise = -allowed
            if r.interest_disallowed_paise and not use_new_regime:
                r.workings.append(
                    f"₹{whole_rupees(r.interest_disallowed_paise)} of interest is above "
                    "the cap and is not allowed.")
        else:
            expected = max(_scaled(p.municipal_value_paise, p.share_bps),
                           _scaled(p.fair_rent_paise, p.share_bps))
            if p.standard_rent_paise is not None:
                expected = min(expected, _scaled(p.standard_rent_paise, p.share_bps))
            if not p.municipal_value_paise and not p.fair_rent_paise:
                r.gaps.append(
                    f"{p.name}: neither municipal value nor fair rent is "
                    "recorded, so the expected rent is nil and the annual value "
                    "is the rent actually receivable. §23(1)(a) takes the higher "
                    "of the two.")
            if p.use == USE_DEEMED_LET_OUT:
                gross = expected
                r.workings.append(
                    "Deemed let-out (§23(4)(b)): the annual value is the "
                    "expected rent.")
            else:
                receivable = _scaled(p.rent_receivable_paise, p.share_bps)
                unrealised = _scaled(p.unrealised_rent_paise, p.share_bps)
                if unrealised:
                    if p.unrealised_rent_rule_4_met is True:
                        receivable -= unrealised
                        r.workings.append(
                            "Unrealised rent deducted from the rent receivable "
                            "(Rule 4).")
                    else:
                        r.gaps.append(
                            f"{p.name}: unrealised rent is recorded but Rule 4's "
                            "conditions are not stated as met, so it was NOT "
                            "deducted. Rule 4 needs a bona fide tenancy, a "
                            "defaulting tenant, steps taken to recover the rent "
                            "and the house not occupied by the owner.")
                if p.vacant_part_of_year and receivable < expected:
                    gross = receivable
                    r.workings.append(
                        "Vacant for part of the year, and that is why the rent "
                        "fell short of the expected rent: the annual value is "
                        "the rent actually receivable (§23(1)(c)).")
                else:
                    gross = max(expected, receivable)
                    r.workings.append(
                        "Annual value: the higher of the expected rent and the "
                        "rent receivable (§23(1)).")
            tax_paid = _scaled(p.municipal_tax_paid_paise, p.share_bps)
            net = max(0, gross - tax_paid)
            if tax_paid > gross:
                r.workings.append(
                    "Municipal tax paid exceeds the annual value; the net "
                    "annual value is taken as nil.")
            standard = net * STANDARD_DEDUCTION_BPS // 10_000
            r.gross_annual_value_paise = gross
            r.municipal_tax_paise = min(tax_paid, gross)
            r.net_annual_value_paise = net
            r.standard_deduction_paise = standard
            r.interest_allowed_paise = claimed
            r.income_paise = net - standard - claimed

        out.properties.append(r)
        out.gaps.extend(r.gaps)

    out.head_income_paise = sum(r.income_paise for r in out.properties)
    return out

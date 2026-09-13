"""Sections 54, 54B, 54EC and 54F — what the gain is exempt from when the
money goes back into a new asset (IT-19).

WHAT WAS WRONG
    `capital_gains_engine` computed the gain, the holding period and the rate
    and stopped. On a house sale, the whole of that gain is routinely exempt
    under s.54, and there was nowhere in the product to say so — so the tax
    shown was the tax on a gain the client may not owe tax on at all.

THE FOUR SECTIONS ARE NOT ONE RULE WITH FOUR NAMES, and the differences are
exactly where this goes wrong:

  s.54    a LONG-TERM residential house -> one residential house in India.
          Exemption is the LOWER of the gain and the cost of the new house.

  s.54B   agricultural land used for agriculture in the two years immediately
          preceding -> other agricultural land. **NOT limited to a long-term
          asset** — this is the one section in the family a short-term gain
          can reach, and treating it like its neighbours refuses a claim the
          Act allows.

  s.54EC  a LONG-TERM asset -> notified bonds, within SIX MONTHS. Capped at
          Rs 50 lakh, and **that cap spans two financial years, not one** (the
          second proviso: the investment made in the year of transfer AND in
          the subsequent year, together). Reading it as Rs 50 lakh a year
          doubles the exemption. From 01-04-2018 the section reaches only
          LAND OR BUILDING; before that, any long-term asset.

  s.54F   a LONG-TERM asset that is NOT a residential house -> one residential
          house in India. **The exemption is PROPORTIONATE**, gain x cost /
          NET CONSIDERATION — not the lower of the two. On a Rs 1 crore sale
          with a Rs 40 lakh gain and a Rs 50 lakh house, s.54's rule would
          exempt Rs 40 lakh and s.54F exempts Rs 20 lakh. Applying the wrong
          one here halves the tax.

WHAT THIS MODULE REFUSES RATHER THAN GUESSES
    Three facts decide whether a section is reachable at all and none of them
    is in any ledger: WHAT WAS SOLD (the register's `asset_type` cannot tell a
    residential house from a plot), HOW MANY OTHER HOUSES the assessee owned
    on the date of transfer (s.54F's own condition), and WHETHER THE LAND WAS
    FARMED for the two preceding years (s.54B's). Each is refused and NAMED.
    Guessing is unsafe in both directions — grant an exemption the section
    does not reach and the client is short-paid with s.234B interest running;
    withhold one they were entitled to and they pay tax on an exempt gain.

    The assessee must also be an INDIVIDUAL OR HUF for s.54, s.54B and s.54F
    — s.54EC reaches any assessee. That is asked as its own tri-state
    parameter and NOT read off `capital_gains_engine.ASSESSEE_TYPES`, which
    looks like the right vocabulary and is not: its `other` value means "not a
    RESIDENT individual or HUF", so a NON-RESIDENT individual falls in it —
    and s.54 reaches a non-resident individual perfectly well. Refusing on
    that value would deny the exemption to exactly the assessee whose
    residency the other vocabulary exists to record.

WHAT IT DOES NOT MODEL, AND SAYS SO
    * s.54's TWO-HOUSE option (the proviso inserted by the Finance Act 2019,
      where the gain does not exceed Rs 2 crore) is exercisable ONCE IN THE
      ASSESSEE'S LIFETIME. Nothing here can know whether it has been used.
    * The WITHDRAWAL of an exemption when the new asset is transferred inside
      its lock-in is a fact about a LATER year's return. The date is recorded
      and reported; no earlier year is recomputed, because a posted
      computation is not rewritten in place any more than a posted journal is.
    * NET CONSIDERATION is the full value of consideration LESS expenditure
      wholly and exclusively in connection with the transfer (s.48(i)). The
      register holds no transfer-expenditure column, so the caller passes the
      sale value and the answer says so. The direction is safe: an overstated
      net consideration makes the s.54F fraction SMALLER, so the exemption is
      understated and the tax cannot come out too low.

⚠️ EVERY FIGURE AND WINDOW HERE IS `[S]`-GRADED. Direct egress is refused at
    this environment's proxy — incometax.gov.in included — so none of the
    sections was read against the bare Act. What is written down is what the
    module can be held to; a test pins each constant so a correction is one
    edit and shows up as a deliberate change rather than a drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.income_tax.capital_gains_engine import fy_for_date

# ── the sections ─────────────────────────────────────────────────────────────

SECTION_54 = "54"
SECTION_54B = "54B"
SECTION_54EC = "54EC"
SECTION_54F = "54F"
SECTIONS = (SECTION_54, SECTION_54B, SECTION_54EC, SECTION_54F)

# ── what was sold ────────────────────────────────────────────────────────────

NATURE_RESIDENTIAL_HOUSE = "residential_house"
NATURE_AGRICULTURAL_LAND = "agricultural_land"
NATURE_LAND_OR_BUILDING = "land_or_building"
NATURE_OTHER = "other"
ASSET_NATURES = (NATURE_RESIDENTIAL_HOUSE, NATURE_AGRICULTURAL_LAND,
                 NATURE_LAND_OR_BUILDING, NATURE_OTHER)

KIND_PURCHASE = "purchase"
KIND_CONSTRUCTION = "construction"
KIND_BONDS = "bonds"
ACQUISITION_KINDS = (KIND_PURCHASE, KIND_CONSTRUCTION, KIND_BONDS)

# ── the figures, all [S] ─────────────────────────────────────────────────────

#: s.54EC(1) second proviso — Rs 50 lakh, and it spans the year of transfer
#: AND the subsequent year TOGETHER, which is why it is not a per-year cap.
SECTION_54EC_CAP_PAISE = 50_00_000 * 100

#: The Finance Act 2018 narrowed s.54EC to land or building or both. A transfer
#: before this date reaches the section on any long-term asset, and belated and
#: revised returns for those years are still filed — the same fork shape as the
#: TDS vocabulary and the 23-07-2024 capital-gains fork.
SECTION_54EC_LAND_OR_BUILDING_FROM = date(2018, 4, 1)

#: s.54EC(1) — the investment must be made within six months after the date of
#: transfer.
SECTION_54EC_WINDOW_MONTHS = 6

#: The Finance Act 2018 also took the bond lock-in from three years to five.
SECTION_54EC_LOCK_IN_YEARS = 5

#: The Finance Act 2023 deemed the cost of the new asset under s.54 and s.54F
#: not to exceed Rs 10 crore, with effect from AY 2024-25 — so a transfer in
#: FY 2023-24 onwards.
SECTION_54_54F_COST_CEILING_PAISE = 10_00_00_000 * 100
SECTION_54_54F_COST_CEILING_FIRST_FY = "2023-24"

#: The Finance Act 2019 proviso to s.54(1) lets the assessee take TWO houses
#: where the gain does not exceed this — once in a lifetime. Held so nobody
#: has to look it up, and deliberately NOT applied: see the module docstring.
SECTION_54_TWO_HOUSE_GAIN_LIMIT_PAISE = 2_00_00_000 * 100

_INDIVIDUAL_OR_HUF_ONLY = (SECTION_54, SECTION_54B, SECTION_54F)


@dataclass(frozen=True)
class SectionRule:
    section: str
    heading: str
    #: The natures of transferred asset the section's charging words reach. An
    #: empty tuple would mean "any", which no section here is.
    reaches: tuple[str, ...]
    requires_long_term: bool
    #: Months before / after the transfer in which the new asset may be
    #: acquired. None means the limb does not exist for this section.
    purchase_before_months: Optional[int]
    purchase_after_months: Optional[int]
    construction_after_months: Optional[int]
    #: s.54F alone apportions on net consideration.
    proportionate: bool
    #: An absolute ceiling on the amount invested (s.54EC's Rs 50 lakh).
    invested_cap_paise: Optional[int]
    #: Whether the Capital Gains Accounts Scheme can stand in for the money.
    cgas_available: bool
    lock_in_years: int
    new_asset: str


RULES: dict[str, SectionRule] = {
    SECTION_54: SectionRule(
        section=SECTION_54,
        heading="Profit on sale of property used for residence",
        reaches=(NATURE_RESIDENTIAL_HOUSE,),
        requires_long_term=True,
        purchase_before_months=12,
        purchase_after_months=24,
        construction_after_months=36,
        proportionate=False,
        invested_cap_paise=None,
        cgas_available=True,
        lock_in_years=3,
        new_asset="one residential house in India",
    ),
    SECTION_54B: SectionRule(
        section=SECTION_54B,
        heading="Capital gain on transfer of land used for agricultural purposes",
        reaches=(NATURE_AGRICULTURAL_LAND,),
        # THE ONE SECTION IN THE FAMILY A SHORT-TERM GAIN REACHES. s.54B's
        # charging words describe the USE of the land in the two preceding
        # years, not its holding period.
        requires_long_term=False,
        purchase_before_months=None,
        purchase_after_months=24,
        construction_after_months=None,
        proportionate=False,
        invested_cap_paise=None,
        cgas_available=True,
        lock_in_years=3,
        new_asset="other land for agricultural purposes",
    ),
    SECTION_54EC: SectionRule(
        section=SECTION_54EC,
        heading="Capital gain not to be charged on investment in certain bonds",
        # From 01-04-2018 only land or building; before that, any long-term
        # asset. `_reaches` widens this for an earlier transfer.
        #
        # ALL THREE OF THESE ARE LAND OR BUILDING. A residential house is a
        # building, and agricultural land is land — RURAL agricultural land is
        # not a capital asset at all (s.2(14)(iii)) so no gain arises on it,
        # but urban agricultural land is, and s.54EC's words reach it. Leaving
        # either out would refuse an exemption the section gives, which
        # overstates the tax.
        reaches=(NATURE_LAND_OR_BUILDING, NATURE_RESIDENTIAL_HOUSE,
                 NATURE_AGRICULTURAL_LAND),
        requires_long_term=True,
        purchase_before_months=None,
        purchase_after_months=SECTION_54EC_WINDOW_MONTHS,
        construction_after_months=None,
        proportionate=False,
        invested_cap_paise=SECTION_54EC_CAP_PAISE,
        # No CGAS limb: the section requires the bonds themselves inside six
        # months, and a deposit is not a subscription.
        cgas_available=False,
        lock_in_years=SECTION_54EC_LOCK_IN_YEARS,
        new_asset="bonds redeemable after five years (NHAI / REC / PFC / IRFC or notified)",
    ),
    SECTION_54F: SectionRule(
        section=SECTION_54F,
        heading="Capital gain on transfer of any capital asset other than a residential house",
        reaches=(NATURE_AGRICULTURAL_LAND, NATURE_LAND_OR_BUILDING, NATURE_OTHER),
        requires_long_term=True,
        purchase_before_months=12,
        purchase_after_months=24,
        construction_after_months=36,
        proportionate=True,
        invested_cap_paise=None,
        cgas_available=True,
        lock_in_years=3,
        new_asset="one residential house in India",
    ),
}


# ── inputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reinvestment:
    """One recorded claim — a row of `public.capital_gain_reinvestments`."""
    section: str
    cost_paise: int = 0
    acquisition_kind: Optional[str] = None
    acquisition_date: Optional[date] = None
    cgas_deposit_paise: int = 0
    cgas_deposit_date: Optional[date] = None
    other_residential_houses_owned: Optional[int] = None
    agricultural_use_two_years: Optional[bool] = None
    new_asset_transferred_on: Optional[date] = None
    description: str = ""
    id: str = ""


@dataclass(frozen=True)
class ClaimResult:
    section: str
    heading: str
    allowed: bool
    exemption_paise: int
    #: What the section was allowed to count, after every cap. Reported
    #: separately from the exemption because they differ for a reason the CA
    #: needs to see: s.54EC's Rs 50 lakh, s.54/54F's Rs 10 crore, or a gain
    #: smaller than the investment.
    amount_considered_paise: int
    #: The last date the acquisition may be made, where the section fixes one.
    deadline: Optional[date]
    within_time: Optional[bool]
    working: list[str] = field(default_factory=list)
    #: Facts nobody recorded. A claim with a gap is NOT allowed.
    gaps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExemptionResult:
    gain_paise: int
    total_exemption_paise: int
    taxable_gain_paise: int
    claims: list[ClaimResult] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


# ── the arithmetic ───────────────────────────────────────────────────────────

def _add_months(d: date, months: int) -> date:
    """The same convention as the capital-gains engine: keep the day, clamp to
    the shorter month."""
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    day = d.day
    while day > 1:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1
    return date(y, m, 1)


def _floor(numerator: int, denominator: int) -> int:
    """s.54F's fraction, FLOORED — the exemption is what the tax is NOT charged
    on, so a rounding that grows it grows the shortfall the client pays
    s.234B interest on. This runs the opposite way to the ESI rounding and the
    same way as the GST discount, and for the same reason both do: the
    direction that cannot understate what is owed."""
    if denominator <= 0 or numerator <= 0:
        return 0
    return numerator // denominator


def _reaches(rule: SectionRule, nature: str, transfer_date: date) -> bool:
    if rule.section == SECTION_54EC and transfer_date < SECTION_54EC_LAND_OR_BUILDING_FROM:
        # Before the Finance Act 2018 narrowed it, s.54EC reached any
        # long-term capital asset. A belated or revised return for such a year
        # is still filed at the law of that year.
        return True
    return nature in rule.reaches


def _cost_ceiling_applies(section: str, transfer_date: date) -> bool:
    if section not in (SECTION_54, SECTION_54F):
        return False
    return fy_for_date(transfer_date) >= SECTION_54_54F_COST_CEILING_FIRST_FY


def _deadline(rule: SectionRule, transfer_date: date, kind: Optional[str]) -> Optional[date]:
    if kind == KIND_CONSTRUCTION and rule.construction_after_months:
        return _add_months(transfer_date, rule.construction_after_months)
    if rule.purchase_after_months:
        return _add_months(transfer_date, rule.purchase_after_months)
    return None


def _earliest(rule: SectionRule, transfer_date: date, kind: Optional[str]) -> Optional[date]:
    """The earliest date the new asset may be acquired.

    THE "ONE YEAR BEFORE" LIMB IS A PURCHASE LIMB ONLY. s.54 and s.54F let the
    assessee have PURCHASED a house in the year before the transfer, but a
    CONSTRUCTION must be within three years AFTER it — so applying the earlier
    date to a construction would allow a claim the section does not.
    """
    if kind != KIND_CONSTRUCTION and rule.purchase_before_months:
        return _add_months(transfer_date, -rule.purchase_before_months)
    return transfer_date


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def compute_exemption(
    *,
    gain_paise: int,
    net_consideration_paise: int,
    transfer_date: date,
    is_long_term: bool,
    transferred_asset_nature: Optional[str],
    assessee_is_individual_or_huf: Optional[bool] = None,
    assessee_description: str = "",
    reinvestments: tuple[Reinvestment, ...] = (),
    return_due_date: Optional[date] = None,
    return_due_date_is_decided: bool = False,
    net_consideration_is_gross: bool = True,
) -> ExemptionResult:
    """What is exempt, claim by claim, and what is left to tax.

    Pure. Takes what it needs and reads no database — `capital_gain_service`
    fetches, this decides. Every refusal comes back as a sentence in `gaps`
    rather than an exception, because a screen showing a CA their capital-gains
    register needs to say what to go and record.
    """
    claims: list[ClaimResult] = []
    gaps: list[str] = []
    caveats: list[str] = []

    if net_consideration_is_gross and any(
            RULES[r.section].proportionate for r in reinvestments if r.section in RULES):
        caveats.append(
            "s.54F apportions on NET consideration — the full value of the "
            "consideration less expenditure wholly and exclusively in "
            "connection with the transfer (s.48(i)). The register holds no "
            "transfer-expenditure column, so the full value has been used. "
            "That makes the fraction smaller, so the exemption below is "
            "understated rather than overstated.")

    if transferred_asset_nature is None:
        gaps.append(
            "What was sold has not been recorded against this entry. s.54 "
            "reaches only a residential house, s.54F only an asset that is "
            "not one, s.54B only agricultural land and s.54EC (from "
            "01-04-2018) only land or building — so no claim can be tested "
            "until it is. Record it on the register entry.")
    elif transferred_asset_nature not in ASSET_NATURES:
        gaps.append(f"'{transferred_asset_nature}' is not a nature this module knows.")
        transferred_asset_nature = None

    # THE GAIN IS THE CEILING FOR THE WHOLE SET, not for each claim. Two
    # claims of Rs 40 lakh each against a Rs 50 lakh gain exempt Rs 50 lakh,
    # not Rs 80 lakh — s.54EC and s.54F may both be claimed on one transfer,
    # and nothing in either section exempts more than there was.
    remaining = max(0, gain_paise)

    for rein in reinvestments:
        claim = _one_claim(
            rein=rein,
            gain_paise=gain_paise,
            headroom_paise=remaining,
            net_consideration_paise=net_consideration_paise,
            transfer_date=transfer_date,
            is_long_term=is_long_term,
            nature=transferred_asset_nature,
            individual_or_huf=assessee_is_individual_or_huf,
            assessee_description=assessee_description,
            return_due_date=return_due_date,
            return_due_date_is_decided=return_due_date_is_decided,
        )
        claims.append(claim)
        remaining = max(0, remaining - claim.exemption_paise)

    total = sum(c.exemption_paise for c in claims)
    return ExemptionResult(
        gain_paise=gain_paise,
        total_exemption_paise=total,
        taxable_gain_paise=max(0, gain_paise) - total,
        claims=claims,
        gaps=gaps,
        caveats=caveats,
    )


def _one_claim(
    *,
    rein: Reinvestment,
    gain_paise: int,
    headroom_paise: int,
    net_consideration_paise: int,
    transfer_date: date,
    is_long_term: bool,
    nature: Optional[str],
    individual_or_huf: Optional[bool],
    assessee_description: str,
    return_due_date: Optional[date],
    return_due_date_is_decided: bool,
) -> ClaimResult:
    rule = RULES.get(rein.section)
    if rule is None:
        return ClaimResult(
            section=rein.section, heading="", allowed=False, exemption_paise=0,
            amount_considered_paise=0, deadline=None, within_time=None,
            gaps=[f"'{rein.section}' is not a section this module computes."])

    working: list[str] = []
    gaps: list[str] = []
    caveats: list[str] = []

    # ── who ──────────────────────────────────────────────────────────────────
    if rule.section in _INDIVIDUAL_OR_HUF_ONLY:
        if individual_or_huf is False:
            gaps.append(
                f"s.{rule.section} reaches an individual or a Hindu undivided "
                "family only"
                + (f", and this client is recorded as {assessee_description}."
                   if assessee_description else ".")
                + " s.54EC is the one section in this family that reaches any "
                  "assessee.")
        elif individual_or_huf is None:
            gaps.append(
                f"s.{rule.section} reaches only an individual or a Hindu "
                "undivided family, and whether this assessee is one could not "
                "be established"
                + (f" from an entity type of {assessee_description}."
                   if assessee_description else ".")
                + " Record it rather than assuming — a company, a firm or a "
                  "trust gets none of s.54, s.54B or s.54F.")

    # ── what ─────────────────────────────────────────────────────────────────
    if nature is None:
        gaps.append("What was sold has not been recorded, so this claim cannot be tested.")
    elif not _reaches(rule, nature, transfer_date):
        gaps.append(
            f"s.{rule.section} does not reach a transfer of "
            f"{nature.replace('_', ' ')}. It applies to "
            + (", ".join(n.replace('_', ' ') for n in rule.reaches)) + ".")
    elif (rule.section == SECTION_54EC
          and transfer_date < SECTION_54EC_LAND_OR_BUILDING_FROM):
        caveats.append(
            "This transfer predates 01-04-2018, when the Finance Act 2018 "
            "narrowed s.54EC to land or building. The section is applied at "
            "the law of the year of transfer, which reached any long-term "
            "capital asset.")

    if rule.requires_long_term and not is_long_term:
        gaps.append(
            f"s.{rule.section} reaches a LONG-TERM capital asset and this "
            "transfer is short-term.")
    elif not rule.requires_long_term and not is_long_term:
        caveats.append(
            "s.54B is the one section in this family a SHORT-TERM gain "
            "reaches: its charging words describe the use of the land in the "
            "two preceding years, not a holding period.")

    # ── the section's own conditions ─────────────────────────────────────────
    if rule.section == SECTION_54F:
        owned = rein.other_residential_houses_owned
        if owned is None:
            gaps.append(
                "s.54F requires that the assessee did not own MORE THAN ONE "
                "residential house, other than the new one, on the date of "
                "transfer. How many they owned is not recorded, and it is not "
                "a fact any ledger holds — record it on the claim.")
        elif owned > 1:
            gaps.append(
                f"s.54F is not available: {owned} other residential houses "
                "were owned on the date of transfer, and the section allows "
                "at most one.")
    if rule.section == SECTION_54B:
        used = rein.agricultural_use_two_years
        if used is None:
            gaps.append(
                "s.54B requires the land to have been used for agricultural "
                "purposes in the two years immediately preceding the "
                "transfer, by the assessee or a parent. Whether it was is not "
                "recorded — record it on the claim.")
        elif used is False:
            gaps.append(
                "s.54B is not available: the land was not used for "
                "agricultural purposes in the two preceding years.")

    # ── when ─────────────────────────────────────────────────────────────────
    deadline = _deadline(rule, transfer_date, rein.acquisition_kind)
    earliest = _earliest(rule, transfer_date, rein.acquisition_kind)
    within: Optional[bool] = None
    if rein.acquisition_date is None:
        if deadline is not None:
            caveats.append(
                f"No acquisition date recorded. The last date for this claim "
                f"is {deadline.isoformat()}"
                + (" (construction)." if rein.acquisition_kind == KIND_CONSTRUCTION
                   else "."))
    else:
        within = True
        if deadline is not None and rein.acquisition_date > deadline:
            within = False
            gaps.append(
                f"The new asset was acquired on "
                f"{rein.acquisition_date.isoformat()}, after "
                f"{deadline.isoformat()} — the last date s.{rule.section} "
                "allows for this transfer.")
        if earliest is not None and rein.acquisition_date < earliest:
            within = False
            gaps.append(
                f"The new asset was acquired on "
                f"{rein.acquisition_date.isoformat()}, before "
                f"{earliest.isoformat()} — the earliest date s.{rule.section} "
                "allows for this transfer.")

    # ── how much was put back ────────────────────────────────────────────────
    invested = max(0, rein.cost_paise)
    working.append(f"Cost of the new asset: {_rupees(invested)}.")

    deposit = max(0, rein.cgas_deposit_paise)
    if deposit:
        if not rule.cgas_available:
            gaps.append(
                f"s.{rule.section} has no Capital Gains Accounts Scheme limb "
                "— the section requires the investment itself inside its own "
                f"window, so {_rupees(deposit)} on deposit does not count.")
        elif rein.cgas_deposit_date is None:
            gaps.append(
                f"{_rupees(deposit)} is recorded as deposited under the "
                "Capital Gains Accounts Scheme with no date. The deposit "
                "counts only if it was made before the s.139(1) due date, so "
                "an undated one cannot be counted.")
        elif return_due_date is not None and rein.cgas_deposit_date > return_due_date:
            gaps.append(
                f"The Capital Gains Accounts Scheme deposit was made on "
                f"{rein.cgas_deposit_date.isoformat()}, after the s.139(1) "
                f"due date of {return_due_date.isoformat()}, so it does not "
                "count as utilised.")
        else:
            invested += deposit
            working.append(
                f"Plus {_rupees(deposit)} deposited under the Capital Gains "
                f"Accounts Scheme on {rein.cgas_deposit_date.isoformat()}.")
            if return_due_date is None:
                caveats.append(
                    "Whether the Capital Gains Accounts Scheme deposit was in "
                    "time was not tested: no s.139(1) due date was supplied "
                    "for this client.")
            elif not return_due_date_is_decided:
                caveats.append(
                    f"The s.139(1) due date for this client is not decided "
                    f"from the facts held (see "
                    f"compliance_obligation_service.itr_due_date_for_client), "
                    f"so the deposit was tested against {return_due_date.isoformat()} "
                    "— the EARLIER of the possible dates, which is the "
                    "stricter test.")
            caveats.append(
                "A Capital Gains Accounts Scheme deposit counts only while it "
                "is applied to the new asset inside the section's own window. "
                "An unutilised balance is charged in the year the window "
                "closes; nothing here recomputes that later year.")

    # ── the caps ─────────────────────────────────────────────────────────────
    considered = invested
    if rule.invested_cap_paise is not None and considered > rule.invested_cap_paise:
        considered = rule.invested_cap_paise
        working.append(
            f"Capped at {_rupees(rule.invested_cap_paise)} — s.54EC's own "
            "limit, which the second proviso applies to the investment made "
            "in the year of transfer AND the year after it TOGETHER, not to "
            "each year.")
    if rule.invested_cap_paise is not None:
        caveats.append(
            "s.54EC's Rs 50 lakh spans the financial year of transfer and the "
            "following one together. Where the same assessee has invested "
            "under s.54EC against another transfer in either year, that "
            "amount counts against this limit too and is not visible here.")

    if _cost_ceiling_applies(rule.section, transfer_date) and considered > SECTION_54_54F_COST_CEILING_PAISE:
        considered = SECTION_54_54F_COST_CEILING_PAISE
        working.append(
            f"Capped at {_rupees(SECTION_54_54F_COST_CEILING_PAISE)} — the "
            "Finance Act 2023 deems the cost of the new asset under s.54 and "
            "s.54F not to exceed Rs 10 crore, from AY 2024-25.")

    # ── the exemption ────────────────────────────────────────────────────────
    if gaps:
        return ClaimResult(
            section=rule.section, heading=rule.heading, allowed=False,
            exemption_paise=0, amount_considered_paise=considered,
            deadline=deadline, within_time=within,
            working=working, gaps=gaps, caveats=caveats)

    if rule.proportionate:
        # s.54F(1): the gain bears to the whole of the gain the same
        # proportion as the cost of the new asset bears to the NET
        # CONSIDERATION. Where the cost is not less than the net
        # consideration, the whole gain is exempt.
        if net_consideration_paise <= 0:
            exemption = 0
            working.append(
                "Net consideration is nil, so the s.54F fraction cannot be "
                "formed.")
        elif considered >= net_consideration_paise:
            exemption = max(0, gain_paise)
            working.append(
                f"The cost ({_rupees(considered)}) is not less than the net "
                f"consideration ({_rupees(net_consideration_paise)}), so the "
                "whole gain is exempt.")
        else:
            exemption = _floor(max(0, gain_paise) * considered, net_consideration_paise)
            working.append(
                f"s.54F is PROPORTIONATE: {_rupees(max(0, gain_paise))} x "
                f"{_rupees(considered)} / {_rupees(net_consideration_paise)} "
                f"= {_rupees(exemption)}. It is NOT the lower of the gain and "
                "the cost — that is s.54's rule.")
    else:
        exemption = min(max(0, gain_paise), considered)
        working.append(
            f"s.{rule.section} exempts the LOWER of the gain "
            f"({_rupees(max(0, gain_paise))}) and the amount put back "
            f"({_rupees(considered)}) = {_rupees(exemption)}.")

    if exemption > headroom_paise:
        working.append(
            f"Reduced to {_rupees(headroom_paise)} — an earlier claim against "
            "this same transfer has already exempted part of the gain, and "
            "nothing exempts more gain than there was.")
        exemption = headroom_paise

    if rein.new_asset_transferred_on is not None:
        caveats.append(
            f"The new asset was transferred on "
            f"{rein.new_asset_transferred_on.isoformat()}. s.{rule.section} "
            f"withdraws this exemption where that happens within "
            f"{rule.lock_in_years} years of its acquisition — the charge "
            "falls in the year of THAT transfer, and is not computed here.")

    return ClaimResult(
        section=rule.section, heading=rule.heading, allowed=True,
        exemption_paise=exemption, amount_considered_paise=considered,
        deadline=deadline, within_time=within,
        working=working, gaps=[], caveats=caveats)

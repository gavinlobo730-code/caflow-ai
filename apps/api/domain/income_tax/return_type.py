"""
A RETURN OF INCOME HAS THREE KINDS, and until now this product held one.

IT Act 1961 §139(1) is the ORIGINAL return, §139(5) the REVISED return, and
§139(8A) the UPDATED return (ITR-U). `itr_filings` had no column saying which,
and migration 319's `UNIQUE (firm_id, client_id, financial_year, itr_form)`
could not hold a second return beside the original anyway — so a practice that
revises a return, which is an ordinary week's work, had nowhere to record it
and no way to keep the original's acknowledgement beside the new one. That is
IT-23's fourth limb; migration 381 carries the columns and this module the
rules over them.

WHAT IS CERTAIN AND WHAT IS NOT, stated once here rather than trusted anywhere
downstream. The three KINDS and what each requires of the document are settled
law and are enforced. The two WINDOWS and §140B's additional-tax bands are
graded `[S]` — read from knowledge, not confirmed against the bare Act, because
this environment's egress proxy refuses every `.gov.in` (see
`docs/audits/2026-09-07-market-research/`). Every answer carries the caveat, and
where the reading changes the answer BOTH readings are given rather than one
picked silently — the shape `domain/gst/late_filing.interest_on_rule_37_reversal`
already uses for its two Rule 37 clocks.

THE ONE THING THIS MODULE WILL NOT DO IS GUESS A YEAR IT DOES NOT HOLD.
`rates_for()` in the sibling registries falls back to `LATEST_VERIFIED_FY`, so
a missing year is a confidently wrong number rather than an error (CLAUDE.md,
"the trap that makes this list necessary"). §140B is additional tax a client
PAYS OVER, so `additional_tax` REFUSES an assessment year the band table does
not hold and names it, exactly as `late_filing.SECTION_50_3_NOTIFIED_RATE_BPS`
refuses rather than substituting 24% for 18%.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.ist_clock import ist_today, normalise_fy_label

# ── The three kinds ──────────────────────────────────────────────────────────

#: The stored vocabulary. `original` is the default on the column, so every row
#: that existed before migration 381 reads as what it is.
RETURN_TYPES: tuple[str, ...] = ("original", "revised", "updated")

#: Which section each kind is furnished under. Used in the answers a screen
#: renders, so the CA sees the section rather than an internal word.
SECTION_FOR_TYPE: dict[str, str] = {
    "original": "s. 139(1)",
    "revised": "s. 139(5)",
    "updated": "s. 139(8A)",
}

#: A revised or an updated return RE-DECLARES a year already declared, and the
#: form carries the earlier return's receipt number and date — §139(5) says
#: "if any person, having furnished a return", and the ITR utility will not
#: accept one without them. So both are required on those two kinds and
#: meaningless on an original.
NEEDS_THE_EARLIER_RECEIPT: frozenset[str] = frozenset({"revised", "updated"})


def validated_return_type(value: Optional[str]) -> str:
    """The kind as the product spells it, or a refusal naming the three.

    Tolerant on the way in and CANONICAL on the way out, for the reason
    `itr_workflow.validated_form` is: the value is stored and then filtered on,
    so two spellings of one kind read as two kinds once the table holds both.
    An empty value is an ORIGINAL — that is the column's default and what every
    row written before migration 381 is.
    """
    # `.strip()` FIRST: a whitespace-only value is a caller saying nothing,
    # which is an original, and `value or "original"` alone would not see it.
    canonical = (value or "").strip().lower() or "original"
    if canonical not in RETURN_TYPES:
        raise ValueError(
            f"{value!r} is not a kind of return. Choose one of: "
            f"{', '.join(RETURN_TYPES)} — s. 139(1), s. 139(5) and s. 139(8A).")
    return canonical


# ── The windows ──────────────────────────────────────────────────────────────
#
# ⚠️ BOTH ARE `[S]`. Egress is refused here, so neither could be read off the
# bare Act. What each one gets wrong, and in which direction, is written beside
# it — that is the part that decides whether the answer is safe to show.

#: §139(5) as substituted by the Finance Act 2021 (w.e.f. AY 2021-22): a revised
#: return may be furnished "at any time before three months prior to the end of
#: the relevant assessment year or before the completion of the assessment,
#: whichever is EARLIER". Three months before 31 March is 31 December.
REVISED_RETURN_MONTH, REVISED_RETURN_DAY = 12, 31

#: §139(8A) as amended by the Finance Act 2025: forty-eight months from the end
#: of the relevant assessment year. It was TWENTY-FOUR before that, and which
#: applies to an assessment year whose 24-month window had already closed by
#: 1 April 2025 is NOT settled here — `updated_return_window` says so instead of
#: choosing, and reports both dates.
UPDATED_RETURN_MONTHS_FA2025 = 48
UPDATED_RETURN_MONTHS_BEFORE_FA2025 = 24

#: §139(8A) itself was inserted by the Finance Act 2022 and reaches AY 2020-21
#: onwards. An earlier year has no updated return at all — a different answer
#: from "the window has closed", and said differently.
UPDATED_RETURN_FIRST_AY = "2020-21"


@dataclass(frozen=True)
class ReturnWindow:
    """Whether a kind of return may still be furnished for an assessment year.

    `closes_on` is the date this module believes the window shuts.
    `alternative_closes_on` is the OTHER reading where one exists — never
    None-by-default and never silently reconciled, because a CA who files on
    the strength of the later date and is wrong has filed nothing.
    """
    return_type: str
    assessment_year: str
    is_open: Optional[bool]
    closes_on: Optional[str]
    alternative_closes_on: Optional[str] = None
    caveats: tuple[str, ...] = field(default_factory=tuple)
    gaps: tuple[str, ...] = field(default_factory=tuple)


def _ay_end(assessment_year: str) -> date:
    """31 March of the assessment year's second half. AY '2026-27' ends
    31-03-2027."""
    label = normalise_fy_label(assessment_year, field="assessment year")
    return date(int(label[:4]) + 1, 3, 31)


def _plus_months(d: date, months: int) -> date:
    """The same day-of-month `months` later. Only ever called on 31 March here,
    and every +12n from 31 March is a 31 March, so no clamping arises — but the
    clamp is written rather than assumed, because a caller passing another date
    would otherwise get a ValueError from `date()`."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def revised_return_window(assessment_year: str, *,
                          as_at: Optional[date] = None) -> ReturnWindow:
    """§139(5): 31 December of the assessment year, or the completion of the
    assessment, WHICHEVER IS EARLIER.

    The second limb is a fact this product does not hold — an assessment order
    is served on the client, not recorded in the books — so it is NAMED on
    every answer rather than ignored. That matters because it can only make the
    window shut EARLIER: an answer of "open" here means "open unless the
    assessment is complete", and the caveat says so.
    """
    label = normalise_fy_label(assessment_year, field="assessment year")
    closes = date(int(label[:4]), REVISED_RETURN_MONTH, REVISED_RETURN_DAY)
    today = as_at or ist_today()
    return ReturnWindow(
        return_type="revised",
        assessment_year=label,
        is_open=today <= closes,
        closes_on=closes.isoformat(),
        caveats=(
            "s. 139(5) (Finance Act 2021): three months before the end of the "
            "assessment year, which is 31 December. [S] — read from knowledge, "
            "not confirmed against the bare Act here.",
        ),
        gaps=(
            "s. 139(5) also shuts the window on the COMPLETION OF THE "
            "ASSESSMENT, whichever is earlier. No assessment order is recorded "
            "against a client here, so this date is the outer limit only — "
            "check whether the assessment for this year is complete.",
        ),
    )


def updated_return_window(assessment_year: str, *,
                          as_at: Optional[date] = None) -> ReturnWindow:
    """§139(8A): forty-eight months from the end of the assessment year, and
    the other reading beside it.

    TWO DATES, NOT ONE, and deliberately. The Finance Act 2025 took the window
    from 24 months to 48; what it did to an assessment year whose 24-month
    window had already closed before 1 April 2025 could not be read here.
    Reporting only the 48-month date would tell a CA a window is open that may
    have shut in 2024 — the direction that costs a filing — and reporting only
    the 24-month date would refuse work the Act now allows. So both are given,
    `is_open` is None where they disagree about today, and the caveat names the
    amendment.
    """
    label = normalise_fy_label(assessment_year, field="assessment year")
    if label < UPDATED_RETURN_FIRST_AY:
        return ReturnWindow(
            return_type="updated", assessment_year=label,
            is_open=False, closes_on=None,
            caveats=(
                f"s. 139(8A) was inserted by the Finance Act 2022 and reaches "
                f"AY {UPDATED_RETURN_FIRST_AY} onwards. There is no updated "
                f"return for AY {label} — which is not the same as a window "
                f"that has closed.",
            ),
        )

    end = _ay_end(label)
    long_close = _plus_months(end, UPDATED_RETURN_MONTHS_FA2025)
    short_close = _plus_months(end, UPDATED_RETURN_MONTHS_BEFORE_FA2025)
    today = as_at or ist_today()
    open_long, open_short = today <= long_close, today <= short_close
    return ReturnWindow(
        return_type="updated",
        assessment_year=label,
        is_open=open_long if open_long == open_short else None,
        closes_on=long_close.isoformat(),
        alternative_closes_on=short_close.isoformat(),
        caveats=(
            "s. 139(8A) as amended by the Finance Act 2025: 48 months from the "
            "end of the assessment year. It was 24 months before that, and "
            "whether the longer window revives an assessment year whose "
            "24-month window closed before 01-04-2025 is NOT settled here. "
            "Both dates are shown for that reason. [S].",
        ),
        gaps=() if open_long == open_short else (
            f"The two readings disagree about today: the 24-month window closed "
            f"on {short_close.isoformat()} and the 48-month one closes on "
            f"{long_close.isoformat()}. Confirm the amendment's application to "
            f"AY {label} before filing.",
        ),
    )


def window_for(return_type: str, assessment_year: str, *,
               as_at: Optional[date] = None) -> Optional[ReturnWindow]:
    """The window for a kind, or None for an ORIGINAL.

    An original return has no window of this sort — §139(1)'s own due date is
    `compliance_engine.itr_due_date` and a belated return under §139(4) is a
    different question again — so this answers None rather than inventing one.
    """
    kind = validated_return_type(return_type)
    if kind == "revised":
        return revised_return_window(assessment_year, as_at=as_at)
    if kind == "updated":
        return updated_return_window(assessment_year, as_at=as_at)
    return None


# ── §140B additional income-tax on an updated return ─────────────────────────

@dataclass(frozen=True)
class AdditionalTaxBand:
    """One band of §140B(3): a percentage of the aggregate of tax and interest,
    for a return furnished within `within_months` of the end of the AY."""
    within_months: int
    percent: int


#: ⚠️ EVERY ENTRY IS `verified=False`, and the whole table is `[S]`.
#:
#: §140B(3) charges additional income-tax on an updated return at a percentage
#: of "the aggregate of tax and interest payable". The Finance Act 2022 set 25%
#: within 12 months of the end of the AY and 50% within 24; the Finance Act
#: 2025, extending the window to 48 months, is reported as adding 60% within 36
#: and 70% within 48. The 60/70 pair is the least certain part of this module.
#:
#: Keyed by ASSESSMENT year, not financial year, because §140B is measured from
#: the end of the assessment year — the one place in this codebase where the AY
#: is the natural key, and it is spelled out so nobody "fixes" it to an FY.
ADDITIONAL_TAX_BANDS_BY_AY: dict[str, tuple[AdditionalTaxBand, ...]] = {
    ay: (
        AdditionalTaxBand(12, 25),
        AdditionalTaxBand(24, 50),
        AdditionalTaxBand(36, 60),
        AdditionalTaxBand(48, 70),
    )
    for ay in ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
               "2026-27", "2027-28")
}

#: The Finance Act 2022's own two bands, for an assessment year the later ones
#: cannot reach. Kept separate rather than folded in: an updated return for AY
#: 2020-21 (the first §139(8A) year) could only ever have been furnished under
#: the 24-month window, so 60% and 70% describe a band that did not exist.
ADDITIONAL_TAX_BANDS_BY_AY["2020-21"] = (
    AdditionalTaxBand(12, 25),
    AdditionalTaxBand(24, 50),
)

#: No year has been confirmed against a Finance Act. Deliberately `None` rather
#: than a year, the same statement `tax_audit.LATEST_VERIFIED_FY` makes.
LATEST_VERIFIED_AY: Optional[str] = None


@dataclass(frozen=True)
class AdditionalTaxResult:
    """§140B's charge, or a refusal. `refusal` and `additional_tax_paise` are
    never both set."""
    assessment_year: str
    furnished_on: str
    months_from_ay_end: Optional[int]
    percent: Optional[int]
    base_paise: Optional[int]
    additional_tax_paise: Optional[int]
    refusal: Optional[str] = None
    caveats: tuple[str, ...] = field(default_factory=tuple)


def months_from_ay_end(assessment_year: str, furnished_on: date) -> int:
    """Whole months from 31 March of the assessment year to the filing date.

    §140B's bands read "within twelve months from the end of the relevant
    assessment year", so for AY 2024-25 (which ends 31-03-2025) a return
    furnished on 31-03-2026 is inside the twelve-month band and one furnished
    on 01-04-2026 is not.

    THE PLAIN MONTH DIFFERENCE IS THE ANSWER, and only because the anchor is
    always the LAST DAY OF MARCH. A part-month rule of the kind
    `advance_tax_interest_engine._months_or_part` needs — add one where the
    day of the month has been passed — cannot fire here at all: no date has a
    day greater than 31, so the adjustment would be unreachable code implying
    an arithmetic this function does not do. Written out rather than left as a
    dead branch, because the next reader would trust the branch.

    So 01-04-2026 is 13 (12 + one for April), which is outside the 12-month
    band, and 31-03-2026 is 12, which is inside it. A date on or before the
    end of the assessment year is 0.
    """
    end = _ay_end(assessment_year)
    if furnished_on <= end:
        return 0
    return (furnished_on.year - end.year) * 12 + (furnished_on.month - end.month)

def additional_tax(assessment_year: str, furnished_on: date,
                   tax_paise: int, interest_paise: int) -> AdditionalTaxResult:
    """§140B(3) additional income-tax, or a refusal naming what is missing.

    THE BASE IS TAX PLUS INTEREST, not tax alone — §140B(3) says "aggregate of
    tax and interest payable", and charging the percentage on the tax alone
    understates what the client pays over on every late updated return.

    REFUSES rather than falls back for an assessment year the band table does
    not hold. Every sibling registry in `domain/income_tax` substitutes
    `LATEST_VERIFIED_FY` for a missing year, which turns a gap into a
    confidently wrong figure; this is money a CA pays over on a client's
    behalf, so the answer is a sentence instead.
    """
    label = normalise_fy_label(assessment_year, field="assessment year")
    bands = ADDITIONAL_TAX_BANDS_BY_AY.get(label)
    if not bands:
        return AdditionalTaxResult(
            assessment_year=label, furnished_on=furnished_on.isoformat(),
            months_from_ay_end=None, percent=None, base_paise=None,
            additional_tax_paise=None,
            refusal=(
                f"No s. 140B band is held for AY {label}. Add the year to "
                f"ADDITIONAL_TAX_BANDS_BY_AY from that year's Finance Act "
                f"rather than relying on a neighbouring year's — the "
                f"percentages moved in 2025."),
        )

    months = months_from_ay_end(label, furnished_on)
    band = next((b for b in bands if months <= b.within_months), None)
    if band is None:
        return AdditionalTaxResult(
            assessment_year=label, furnished_on=furnished_on.isoformat(),
            months_from_ay_end=months, percent=None, base_paise=None,
            additional_tax_paise=None,
            refusal=(
                f"{months} months have passed since the end of AY {label}. The "
                f"last s. 140B band ends at {bands[-1].within_months} months, "
                f"so no updated return can be furnished — and therefore no "
                f"additional tax is computed."),
        )

    base = max(int(tax_paise), 0) + max(int(interest_paise), 0)
    # ROUNDED UP. This is a sum the assessee OWES; understating it leaves a
    # residual demand with its own interest running, which is the same
    # direction ESI takes and the opposite of the GST discount.
    charge = -((-base * band.percent) // 100)
    return AdditionalTaxResult(
        assessment_year=label, furnished_on=furnished_on.isoformat(),
        months_from_ay_end=months, percent=band.percent,
        base_paise=base, additional_tax_paise=charge,
        caveats=(
            f"s. 140B(3): {band.percent}% of the aggregate of tax and interest, "
            f"for an updated return furnished within {band.within_months} "
            f"months of the end of AY {label}. [S] — the 25/50 pair is the "
            f"Finance Act 2022's and the 60/70 pair the Finance Act 2025's, "
            f"neither confirmed against the bare Act here. Every band in this "
            f"table is verified=False.",
            "The base excludes any tax already paid — s. 140B(2) gives credit "
            "for advance tax, TDS, TCS and self-assessment tax, and that "
            "credit is the caller's to apply. What is computed here is the "
            "additional tax on the aggregate it is given.",
        ),
    )

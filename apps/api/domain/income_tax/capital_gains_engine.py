"""
Capital gains computation — IT Act 1961 Section 45 (chargeability), Section 48
(mode of computation + indexation proviso), Section 2(42A) (holding-period
classification), Section 111A (STCG, listed equity/equity MF), Section 112A
(LTCG, listed equity/equity MF), Section 112 (LTCG, other assets), Section
115BBH (VDA/cryptocurrency), Section 50AA (debt mutual funds, Finance Act
2023), Section 55(2)(ac) (the Section 112A grandfathered cost).

## TWO FACTS DECIDE MONEY HERE AND NEITHER IS DERIVABLE FROM THE OTHERS

Both are tri-state inputs carried on `public.capital_gains` by migration 402,
nullable with no default and no backfill, and both are REFUSED AND NAMED
rather than guessed — the same shape as `transferred_asset_nature`
(migration 385) and `fixed_assets.rule_43_use`.

  * `is_listed_security` (IT-28). The proviso to Section 2(42A) gives a
    security listed in a recognised stock exchange in India — a bond or a
    debenture as much as a share — a TWELVE-month holding period where an
    unlisted one needs twenty-four. The asset type cannot carry it, because a
    debenture is the same kind of asset either way. Unrecorded takes the
    unlisted period, which over-states the tax, and `listing_gap` says so.

  * `fmv_31_01_2018_paise` (IT-19). Section 55(2)(ac) deems the cost of a
    Section 112A asset acquired before 01-02-2018 to be the higher of the
    actual cost and the lower of the 31-01-2018 fair market value and the
    sale value. That fair market value is a fact about one scrip on one day —
    the highest quoted price, or the net asset value for an unlisted unit —
    which nothing in this product holds and nothing can derive. Unrecorded
    leaves the ACTUAL cost standing, which is limb (i)'s own floor, so the
    gain reported is the LARGEST the section can produce; the gap names the
    over-statement rather than hiding it.

R3.1b: this capability did not exist in the backend at all before this
module — apps/web/app/income-tax/capital-gains/page.tsx computed AND
PERSISTED these figures entirely client-side (a CLAUDE.md "zero business
logic in the frontend" violation with real financial consequences: the
capital_gains register's stored gain_type/tax_rate_percent/indexed_cost_paise
were never validated server-side). This module ports that page's existing
classification/rate logic — treating it as this codebase's existing, cited
baseline (its section references and Budget 2024 dates were already
reasonably specific) — restructured as data + pure functions, plus a Cost
Inflation Index (CII) table that previously existed ONLY in the frontend.

A genuine inconsistency was found and fixed while unifying the frontend's
two independent implementations: the calculator (`computeGains`) computed
the real "lower of 12.5% without indexation OR 20% with indexation" choice
for property LTCG (the actual Budget 2024 grandfather-clause mechanism for
resident individuals/HUFs on immovable property acquired before 23 Jul
2024), but the register (`getRegTaxRate`) just hardcoded a flat 20% for
every non-equity LTCG asset type, never computing or offering the 12.5%
alternative at all. This module follows the calculator's more complete
logic for every caller (both the interactive estimator and the register),
so the register's stored tax_rate_percent will now reflect the real
lower-of comparison for property instead of always defaulting to 20%.

## THE DATE OF TRANSFER DECIDES — the 23-07-2024 fork

The ported logic applied the post-Budget-2024 rates, the post-Budget-2024
₹1,25,000 exemption and a single 24-month holding threshold to EVERY
transfer, whatever its date. That is a wrong number on any transfer made
before the Finance (No. 2) Act 2024's own commencement date, and the
register holds real historical transfers. The Act amended Sections 111A,
112A, 112, 2(42A) and the second proviso to Section 48 for transfers made
**on or after 23 July 2024**; a transfer before that date is governed by
the earlier law indefinitely, the same "fork, not migration" shape
CLAUDE.md records for the TDS vocabulary. Every rate, exemption and
holding threshold below is therefore chosen by `sale_date`, and the
grandfathering conditions additionally by `purchase_date`.

VERIFICATION STATUS: the CII table and the "only immovable property gets an
indexation choice" asymmetry are ported verbatim from the pre-existing
frontend implementation — the only source for these figures anywhere in
this repo — not independently re-derived. The date-dependent rates,
exemptions and holding periods added later ARE stated against the sections
they come from, in the comments beside each. Flagged for the same "pending
statutory verification" treatment as FY2026-27 income-tax figures
(statutory_rates.py) and the non-Karnataka Professional Tax slabs
(routers/payroll.py) — see roadmap R3.1/R3.12. Updating CII_BY_FY for a
newly-notified year, or correcting any of the rates below, is a pure data
change, not a code change.

Integer paise throughout — never float in any stored or returned amount.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from typing import Optional


# ── The statutory fork dates ────────────────────────────────────────────────
# Finance (No. 2) Act 2024. The capital-gains rates (Sections 111A, 112A,
# 112), the Section 112A exemption, the Section 2(42A) holding periods and
# the availability of indexation under the second proviso to Section 48 all
# changed for transfers made ON OR AFTER this date. It is the date of
# TRANSFER that decides, not the financial year — FY 2024-25 straddles it.
FINANCE_NO2_ACT_2024 = date(2024, 7, 23)

# Section 50AA (Finance Act 2023) reaches, in its own words, a unit of a
# Specified Mutual Fund "acquired on or after the 1st day of April, 2023".
# A unit acquired before that date is an ordinary capital asset and keeps
# the Section 2(42A)/112 treatment — see the debt-MF branch below.
SECTION_50AA_FROM = date(2023, 4, 1)

# ── Section 55(2)(ac) — the Section 112A grandfathered cost ─────────────────
# Section 112A charged listed equity to tax for the first time from AY
# 2019-20, and Section 55(2)(ac) protects the appreciation that had already
# happened when it did: for such an asset ACQUIRED BEFORE 1 FEBRUARY 2018 the
# cost of acquisition is deemed to be
#
#     HIGHER of  (i)  the actual cost, and
#                (ii) LOWER of (a) the fair market value on 31 JANUARY 2018
#                              (b) the full value of the consideration.
#
# Both limbs matter and each guards against one failure. Limb (i) is why the
# substitution can never CREATE a loss out of a fall since 2018 — a real loss
# on the actual cost still comes through, because the actual cost wins. Limb
# (ii)(b) is why it can never turn a gain into a loss — capped at the sale
# value, the deemed cost gives a nil gain at worst.
#
# ⚠️ `[S]`. Direct egress is refused at this environment's proxy,
# incometax.gov.in included, so neither date was read against the bare Act.
# Both are pinned exactly by a test so a correction is one edit and shows up
# as a deliberate change.
SECTION_55_2_AC_FMV_DATE = date(2018, 1, 31)
#: "acquired before the 1st day of February, 2018" — so the test is strictly
#: `purchase_date < this`, and an asset bought ON 1 February 2018 is outside.
#: Written as its own constant rather than as `FMV_DATE + 1 day`, because
#: they are two facts of the section that happen to be adjacent.
SECTION_55_2_AC_ACQUIRED_BEFORE = date(2018, 2, 1)


# ── Cost Inflation Index (CII) — IT Act Section 48, 2nd proviso ─────────────
# Base year FY 2001-02 = 100. Ported verbatim from the pre-existing frontend
# table — see module docstring's verification-status note. CBDT typically
# notifies each FY's CII partway through that year, so a not-yet-notified
# FY has no entry here; cii_for() falls back to the latest known year rather
# than guessing.
#
# 2025-26 was carried in this table as 380, a figure with no source anywhere
# — the signature of a number typed in before the notification landed. CBDT
# Notification 70/2025 of 01-07-2025 notifies 376, and six independent
# professional publishers agree on it; a targeted search found nothing
# asserting 380. 2026-27 is 384, Notification 85/2026 of 15-07-2026, issued
# under s. 72(8)(a) of the Income-tax Act 2025 — the same Act fork
# domain/tds/vocabulary.py already models. Every older entry cross-checks.
# See docs/audits/2026-09-07-market-research/income-tax-tds-primary.md §5.3.
CII_BY_FY: dict[str, int] = {
    "2001-02": 100, "2002-03": 105, "2003-04": 109, "2004-05": 113, "2005-06": 117,
    "2006-07": 122, "2007-08": 129, "2008-09": 137, "2009-10": 148, "2010-11": 167,
    "2011-12": 184, "2012-13": 200, "2013-14": 220, "2014-15": 240, "2015-16": 254,
    "2016-17": 264, "2017-18": 272, "2018-19": 280, "2019-20": 289, "2020-21": 301,
    "2021-22": 317, "2022-23": 331, "2023-24": 348, "2024-25": 363, "2025-26": 376,
    "2026-27": 384,
}
# DELIBERATELY still 2025-26, and behind the table's newest entry. This
# marker means "the last year a human checked against the notification
# itself", and both 376 and 384 are SECONDARY-sourced: this environment's
# network policy blocks every government host, so neither notification was
# read directly. Correcting 380 (no source) to 376 (six agreeing sources)
# strictly improves the figure; moving this marker on the same evidence
# would do the thing CLAUDE.md names — silently promote a guess to a
# verified figure. To move it: read Notification 70/2025 and 85/2026 on
# incometax.gov.in, confirm 376 and 384, then set this to "2026-27".
LATEST_CII_FY = "2025-26"

#: The newest year the TABLE holds, which is a different fact from the newest
#: year a human has verified, and is what an unknown year must fall back to.
#:
#: These two were the same variable until 2026-09-08, and holding LATEST_CII_FY
#: back at 2025-26 (deliberately — see above) while 2026-27 went into the table
#: made `cii_for("2027-28")` return **376**, older AND LOWER than the table's
#: own newest value. A lower index on the acquisition year means a smaller
#: indexed cost, a larger gain and more tax — so the verification marker, whose
#: whole purpose is to stop a guess being promoted to a fact, was quietly
#: changing a taxpayer's liability. Derived rather than written down, so the
#: two cannot drift again.
_NEWEST_CII_FY = max(CII_BY_FY)


def cii_for(fy: str) -> int:
    """CII for a given FY string ('2025-26'); falls back to the NEWEST YEAR IN
    THE TABLE for anything not in it (matches statutory_rates.rates_for's same
    unknown-future-year convention).

    The fallback anchor is `_NEWEST_CII_FY`, not `LATEST_CII_FY`. The second is
    a verification marker — the last year somebody read the notification — and
    using it as the anchor made an unknown year read an index older than one
    the table already holds. See the note on _NEWEST_CII_FY.

    KNOWN GAP, flagged rather than guessed: the fallback is written for a
    not-yet-notified FUTURE year. An acquisition FY BEFORE the 2001-02 base
    year also misses the table and gets the latest index, which makes the
    indexed cost equal the actual cost (no indexation at all). The right
    answer there is Section 55(2)(b) — the assessee may substitute the fair
    market value as on 1 April 2001, indexed from the base year — and that
    FMV is a valuation nobody in this system holds. It cannot be derived
    from the cost, so it is not invented here; the direction of the error is
    over-taxation, never under."""
    return CII_BY_FY.get(fy, CII_BY_FY[_NEWEST_CII_FY])


def cii_is_notified(fy: str) -> bool:
    """Whether the index for this FY is a REAL entry or the fallback (IT-29).

    `cii_for` cannot say — it returns an int either way, and that is the whole
    trap this module's own docstring describes in the abstract: a missing year
    is not an error, it is a confidently wrong number. The CII for a year is
    notified PARTWAY THROUGH that year (usually around June), so at 1 April the
    entry legitimately does not exist yet and a sale in the first weeks of a
    year is indexed at the PREVIOUS year's, lower, index — a smaller indexed
    cost, a larger gain, more tax.

    Over-taxation is the safe direction for an ESTIMATE shown on a screen. It
    is not safe for a figure written into the register, which nothing
    recomputes once the notification lands, so the caller uses this to decide
    whether it has a number worth storing."""
    return fy in CII_BY_FY


def fy_for_date(d: date) -> str:
    """Indian FY string ('2025-26') for a given date — Apr 1 to Mar 31."""
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


# ── Asset types ──────────────────────────────────────────────────────────────
# Accepts both the interactive calculator's asset types and the persisted
# register's (coarser) asset types — both map onto the same underlying
# treatment. "bonds"/"other"/"unlisted"/"gold" are all "other assets" under
# Section 112.
#
# WHETHER A SECURITY IS LISTED IS A DIFFERENT FACT FROM WHAT KIND OF ASSET IT
# IS, AND IT DECIDES THE HOLDING PERIOD (IT-28). The asset type says "bonds";
# the proviso to Section 2(42A) turns on whether that bond is a security
# LISTED in a recognised stock exchange in India, and a listed one is
# long-term after twelve months where an unlisted one needs twenty-four. The
# two cannot be collapsed into the asset type — a debenture is the same kind
# of asset listed or not — so `is_listed_security` is its own tri-state
# parameter, carried on the register by migration 402 and REFUSED rather than
# guessed where nobody has recorded it. `listing_gap` below says what
# unrecorded does and why that direction is the safe one.
_EQUITY_LIKE = frozenset({"equity", "equity_shares", "mutual_funds"})
_PROPERTY_LIKE = frozenset({"property"})
_DEBT_MF_LIKE = frozenset({"debt_mf"})
_VDA_LIKE = frozenset({"vda"})
# Everything else (unlisted, gold, bonds, other, ...) falls through to the
# generic "other assets" Section 112 treatment.

#: The asset types for which "is it listed?" is a LIVE, UNANSWERED question.
#:
#: Derived from what the proviso to Section 2(42A) reaches rather than from a
#: list of things that sounded plausible, and every exclusion is its own
#: decision:
#:
#:   * `equity` / `equity_shares` / `mutual_funds` are already on twelve
#:     months — a listed equity share and a unit of an equity-oriented fund
#:     are both named there, so the asset type has already answered it.
#:   * `property` and `gold` are not securities and cannot be listed.
#:   * `vda` is charged under Section 115BBH whatever the holding period.
#:   * `unlisted` ANSWERS THE QUESTION IN ITS OWN NAME. Honouring
#:     `is_listed_security=True` against it would let a caller contradict the
#:     asset type the same row was created with.
#:   * `debt_mf` is a UNIT, and the twelve-month limb reaches a security
#:     "OTHER THAN A UNIT". A listed debt-fund unit is still twenty-four
#:     months, so accepting the flag there would classify a real short-term
#:     gain as long-term — UNDER-taxing, the direction that costs the client
#:     Section 234B interest.
#:
#: KNOWN GAP, named rather than modelled: the same limb of Section 2(42A) also
#: reaches a ZERO COUPON BOND (Section 2(48)) whether or not it is listed.
#: Whether a bond is a notified zero coupon bond is a THIRD fact nobody here
#: holds and it is not derivable from the other two, so an unlisted zero
#: coupon bond gets twenty-four months — over-taxing, never under.
_LISTING_IS_ASKED = frozenset({"bonds", "other"})

ASSET_TYPES = ("equity", "debt_mf", "property", "unlisted", "vda", "gold")
REGISTER_ASSET_TYPES = ("equity_shares", "mutual_funds", "property", "bonds", "other")


# ── Who the assessee is — the Section 112 grandfathering gate ───────────────
# The fifth proviso to Section 112(1) (Finance (No. 2) Act 2024) lets the
# tax on a long-term gain be capped at 20% computed WITH indexation, but
# only where the asset is land or building or both, only where it was
# acquired before 23-07-2024, and only where the assessee is a RESIDENT
# individual or Hindu undivided family. A company, an LLP, a firm and a
# non-resident get the flat 12.5% and nothing else.
#
# "unspecified" is the default because no caller in this repository supplies
# the assessee's status today (routers/income_tax.py's request models have
# no such field), and inventing "resident individual" for every caller would
# hand the option to exactly the assessees the proviso excludes. Unspecified
# therefore charges the flat rate — the direction that cannot under-tax —
# while still returning both candidate figures so a CA can see the option
# and re-run it once the status is stated.
ASSESSEE_RESIDENT_INDIVIDUAL_HUF = "resident_individual_huf"
ASSESSEE_OTHER = "other"
ASSESSEE_UNSPECIFIED = "unspecified"
ASSESSEE_TYPES = (ASSESSEE_RESIDENT_INDIVIDUAL_HUF, ASSESSEE_OTHER, ASSESSEE_UNSPECIFIED)


# ── Holding period — IT Act Section 2(42A) ──────────────────────────────────
_LONG_TERM_MONTHS_LISTED = 12
# From 23-07-2024 Section 2(42A) knows only two holding periods: 12 months
# for a listed security, 24 months for everything else. Before that date an
# asset that was neither a listed security nor immovable property (unlisted
# shares, gold, an ordinary "other" asset) needed THIRTY-SIX months, and
# immovable property needed 24 (Finance Act 2017, for transfers from
# 01-04-2017).
_LONG_TERM_MONTHS_OTHER_FROM_23_JUL_2024 = 24
_LONG_TERM_MONTHS_OTHER_BEFORE_23_JUL_2024 = 36
_LONG_TERM_MONTHS_PROPERTY_BEFORE_23_JUL_2024 = 24

_LTCG_112A_EXEMPTION_PAISE = 125_000_00           # ₹1,25,000, from 23-07-2024
_LTCG_112A_EXEMPTION_PRE_2024_PAISE = 100_000_00  # ₹1,00,000, before that


def long_term_threshold_months(
    asset_type: str,
    sale_date: date,
    is_listed_security: Optional[bool] = None,
) -> int:
    """The Section 2(42A) threshold in force on the date of TRANSFER.

    `is_listed_security` is a TRI-STATE: True (listed on a recognised stock
    exchange in India), False (not listed), None (nobody recorded it). None
    takes the unlisted threshold and the caller reports the gap — see
    `listing_gap`."""
    if asset_type in _EQUITY_LIKE:
        # Proviso to Section 2(42A) — a listed security (and a unit of an
        # equity-oriented fund) has been 12 months throughout the period this
        # module covers.
        return _LONG_TERM_MONTHS_LISTED
    if is_listed_security is True and asset_type in _LISTING_IS_ASKED:
        # The same limb, reached by the same words. A listed debenture or
        # bond is "a security (other than a unit) listed in a recognised
        # stock exchange in India" and has carried 12 months on both sides of
        # the Finance (No. 2) Act 2024 fork, so no date branch is needed.
        return _LONG_TERM_MONTHS_LISTED
    if sale_date >= FINANCE_NO2_ACT_2024:
        return _LONG_TERM_MONTHS_OTHER_FROM_23_JUL_2024
    if asset_type in _PROPERTY_LIKE:
        # Immovable property came down from 36 to 24 months by Finance Act
        # 2017 for transfers on or after 01-04-2017. A transfer older than
        # that is not modelled and cannot arise here: no return covering it
        # is still filable.
        return _LONG_TERM_MONTHS_PROPERTY_BEFORE_23_JUL_2024
    return _LONG_TERM_MONTHS_OTHER_BEFORE_23_JUL_2024


def _add_months(d: date, months: int) -> date:
    """Calendar-month arithmetic, clamping to the last day of a short month
    (31 Jan + 1 month = 28/29 Feb)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def holding_months(purchase_date: date, sale_date: date) -> int:
    """Whole months COMPLETED in the Section 2(42A) period of holding.

    Section 2(42A) counts the period from the date of acquisition to the
    date IMMEDIATELY PRECEDING the date of transfer, so an asset bought on
    1 Jan and sold on 1 Jan the next year was held for 12 months less a day,
    not 12 months. This used to be a bare calendar-month subtraction
    ((sale.year - buy.year) * 12 + (sale.month - buy.month)), which counted
    that holding as a full 12 months and — one line further on — classified
    it long-term. A holding one day short of the threshold was getting the
    long-term rate.

    Display only. is_long_term() below is the classifier, and the two are
    consistent by construction: is_long_term is exactly
    `holding_months(...) >= long_term_threshold_months(...)`."""
    n = (sale_date.year - purchase_date.year) * 12 + (sale_date.month - purchase_date.month)
    while n > 0 and _add_months(purchase_date, n) >= sale_date:
        n -= 1
    return max(0, n)


def is_long_term(
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    is_listed_security: Optional[bool] = None,
) -> bool:
    """Section 2(42A) classification from the two DATES, not from a month
    count. The asset is long-term only where the period of holding EXCEEDS
    the threshold: sold exactly N months after it was bought, the asset has
    been held for N months (the date of transfer itself being excluded) and
    is still short-term."""
    threshold = long_term_threshold_months(asset_type, sale_date, is_listed_security)
    return sale_date > _add_months(purchase_date, threshold)


def listing_gap(
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    is_listed_security: Optional[bool] = None,
) -> Optional[str]:
    """The sentence naming an unrecorded listing, or None where the fact
    changes nothing (IT-28).

    THE GAP IS REPORTED ONLY WHERE THE ANSWER WOULD MOVE THE CLASSIFICATION,
    which is the same discipline `domain/gst/hsn_digits` applies to an
    unrecorded aggregate turnover: a client whose holding is five years long
    is long-term listed or not, and telling them to go and record something
    that decides nothing is how a CA learns to ignore these sentences. The
    test is written as the RULE — ask the classifier both ways — rather than
    as the month band it happens to produce today.

    UNTIL IT IS RECORDED THE UNLISTED THRESHOLD APPLIES, and that is the safe
    direction rather than an accident. A wrongly LONG-TERM classification is
    the expensive one: it charges 12.5% under Section 112 where the slab was
    due, it opens the Section 112A annual exemption, and it lets the Section
    54/54EC/54F family — which `reinvestment_exemption` gates on
    `is_long_term` — exempt a gain those sections do not reach. A wrongly
    SHORT-TERM one over-states the tax on a screen a CA reads before filing,
    which is what this sentence is for."""
    if asset_type not in _LISTING_IS_ASKED or is_listed_security is not None:
        return None
    if (is_long_term(asset_type, purchase_date, sale_date, True)
            == is_long_term(asset_type, purchase_date, sale_date, False)):
        return None
    return (
        "Whether this security is LISTED on a recognised stock exchange in "
        "India is not recorded, and it decides the holding period: the "
        "proviso to s.2(42A) makes a listed security (other than a unit) "
        f"long-term after {_LONG_TERM_MONTHS_LISTED} months, where an "
        "unlisted one needs "
        f"{long_term_threshold_months(asset_type, sale_date, False)}. It has "
        "been treated as UNLISTED, which over-states the tax rather than "
        "under-stating it. Record it on the register entry. A notified zero "
        "coupon bond (s.2(48)) also takes the shorter period whether or not "
        "it is listed, and that is a fact this product does not hold at all.")


@dataclass(frozen=True)
class GrandfatheredCost:
    """What Section 55(2)(ac) makes the cost of acquisition, and why."""
    cost_paise: int
    #: True only where the SUBSTITUTION actually ran — the section reached the
    #: transfer AND a 31-01-2018 fair market value was supplied.
    applied: bool
    #: Facts nobody recorded. Actionable: a CA goes and finds the figure.
    gaps: tuple[str, ...] = ()
    #: Settled reasons. A value the caller supplied that the section does not
    #: reach is named here rather than silently discarded.
    caveats: tuple[str, ...] = ()
    working: tuple[str, ...] = ()


def _rupees(paise: int) -> str:
    """DISPLAY ONLY, for the working sentences — the same helper and the same
    carve-out as `reinvestment_exemption._rupees`. Nothing computed from this
    is stored or returned as an amount; every figure this module answers with
    stays in integer paise."""
    return f"Rs {paise / 100:,.2f}"


def section_55_2_ac_cost(
    *,
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    purchase_cost_paise: int,
    sale_value_paise: int,
    fmv_31_01_2018_paise: Optional[int] = None,
    is_listed_security: Optional[bool] = None,
) -> GrandfatheredCost:
    """The Section 112A grandfathered cost of acquisition (IT-19).

    Section 55(2)(ac) deems the cost of a long-term capital asset being an
    equity share, a unit of an equity-oriented fund or a unit of a business
    trust — the assets Section 112A charges — ACQUIRED BEFORE 01-02-2018 to be
    the HIGHER of the actual cost and the LOWER of the 31-01-2018 fair market
    value and the full value of the consideration.

    NO ROUNDING HAPPENS HERE AND NONE IS NEEDED: every limb is a `max` or a
    `min` of amounts already in integer paise, so there is no division to take
    a direction on. That is worth stating rather than leaving to inference —
    the two roundings this repository argues about (ESI up, the GST discount
    down) both exist because a quotient had to land somewhere, and this one
    has no quotient.

    THE 31-01-2018 FAIR MARKET VALUE IS AN INPUT AND IS REFUSED WHEN ABSENT.
    The Explanation to the clause makes it the highest price quoted on that
    date (or the last preceding trading day) for a listed share, and the net
    asset value for an unlisted unit — a fact per scrip, per date, that no
    ledger in this product holds and that cannot be derived from the cost or
    the sale value. So the section is NOT applied, the ACTUAL cost stands, and
    the gap is NAMED. That is honest rather than conservative: limb (i) makes
    the actual cost a FLOOR on the deemed cost, so the gain reported without
    the substitution is the LARGEST the section can produce — an upper bound
    on the tax, not a guess at it.

    THE FIGURE IS THE WHOLE HOLDING'S, not a per-share price: the register
    holds no quantity, and `purchase_cost_paise` and `sale_value_paise` are
    both totals for what was transferred, so the fair market value must be the
    same shape or the three limbs are not comparable.
    """
    long_term = is_long_term(asset_type, purchase_date, sale_date, is_listed_security)
    reaches = (asset_type in _EQUITY_LIKE
               and long_term
               and purchase_date < SECTION_55_2_AC_ACQUIRED_BEFORE)

    if not reaches:
        caveats: tuple[str, ...] = ()
        if fmv_31_01_2018_paise is not None:
            # A supplied value that is not used is NAMED, never silently
            # dropped — the SALES-31 shape, where a caller filled in a field
            # that was honoured under test and discarded in production.
            if asset_type not in _EQUITY_LIKE:
                why = ("s.55(2)(ac) reaches only an equity share, a unit of an "
                       "equity-oriented fund or a unit of a business trust — the "
                       "assets s.112A charges.")
            elif not long_term:
                why = ("s.55(2)(ac) reaches a LONG-TERM capital asset, and this "
                       "transfer is short-term; s.111A charges it on the actual "
                       "cost.")
            else:
                why = (f"s.55(2)(ac) reaches an asset acquired before "
                       f"{SECTION_55_2_AC_ACQUIRED_BEFORE.strftime('%d-%m-%Y')}, "
                       f"and this one was acquired on "
                       f"{purchase_date.strftime('%d-%m-%Y')}.")
            caveats = (
                "The 31-01-2018 fair market value supplied has NOT been used: "
                + why,)
        return GrandfatheredCost(cost_paise=purchase_cost_paise, applied=False,
                                 caveats=caveats)

    if fmv_31_01_2018_paise is None:
        return GrandfatheredCost(
            cost_paise=purchase_cost_paise,
            applied=False,
            gaps=(
                "This holding was acquired before "
                f"{SECTION_55_2_AC_ACQUIRED_BEFORE.strftime('%d-%m-%Y')}, so "
                "s.55(2)(ac) substitutes a grandfathered cost — the higher of "
                "the actual cost and the lower of the "
                f"{SECTION_55_2_AC_FMV_DATE.strftime('%d-%m-%Y')} fair market "
                "value and the sale value. That fair market value is a fact "
                "about the scrip on one day (the Explanation makes it the "
                "highest quoted price, or the net asset value for an unlisted "
                "unit) and nothing in this product holds it, so the ACTUAL "
                "cost has been used and the gain below is the LARGEST the "
                "section can give — it is over-stated by the whole of the "
                "appreciation up to 31-01-2018. Record the figure for the "
                "WHOLE holding sold, not per share.",),
        )

    # (ii): lower of the 31-01-2018 fair market value and the full value of
    # the consideration. (i) then floors it at the actual cost.
    capped_fmv = min(fmv_31_01_2018_paise, sale_value_paise)
    deemed = max(purchase_cost_paise, capped_fmv)
    return GrandfatheredCost(
        cost_paise=deemed,
        applied=True,
        working=(
            f"s.55(2)(ac)(ii): lower of the 31-01-2018 fair market value "
            f"{_rupees(fmv_31_01_2018_paise)} and the full value of the "
            f"consideration {_rupees(sale_value_paise)} = "
            f"{_rupees(capped_fmv)}.",
            f"s.55(2)(ac)(i): higher of the actual cost "
            f"{_rupees(purchase_cost_paise)} and that = {_rupees(deemed)}, "
            f"which is the deemed cost of acquisition.",
        ),
    )


def _round_paise(numerator: int, denominator: int) -> int:
    """Integer round-half-up division — never a float intermediate."""
    if denominator == 0:
        return 0
    half = denominator // 2
    if numerator >= 0:
        return (numerator + half) // denominator
    return -((-numerator + half) // denominator)


@dataclass(frozen=True)
class CapitalGainsResult:
    holding_months: int
    is_long_term: bool
    gain_paise: int                          # Section 48: sale - cost - improvement (no indexation)
    indexed_cost_paise: int                  # cost adjusted by CII (meaningful only where compared)
    gain_with_indexation_paise: int
    tax_rate_percent: float                  # the rate actually charged (post lower-of, where applicable)
    tax_with_indexation_percent: Optional[float]  # the alternative rate, only when a real choice exists
    # Tax at tax_rate_percent — always populated. The name is the
    # post-23-07-2024 default, where the headline rate is the one WITHOUT
    # indexation. On a Section 112 transfer made BEFORE 23-07-2024 there is
    # no such choice — indexation is mandatory under the second proviso to
    # Section 48 — and this field then holds the 20% tax on the INDEXED
    # gain, which is the tax at tax_rate_percent as documented. The field
    # name is kept because routers/income_tax.py::_cg_response and
    # apps/web/lib/data/income-tax.ts read it by name.
    tax_without_indexation_paise: int
    tax_with_indexation_paise: Optional[int]  # tax at tax_with_indexation_percent — only when a choice exists
    tax_liability_paise: int                 # final tax payable (lower of the two, if both computed) —
                                              # exposed explicitly so callers never re-derive this rounding
                                              # themselves (integer round-half-up, not float Math.round)
    section_ref: str
    note: str
    is_slab_rate_estimate: bool              # True where the real rate depends on the assessee's own
                                              # slab and this is shown at a flat estimate, not a statutory rate
    # THE INDEX ITSELF WAS A FALLBACK (IT-29). A DIFFERENT fact from
    # is_slab_rate_estimate above, which is about the RATE: this one says the
    # CII for the purchase year or the sale year is not in the table and the
    # newest known index was used instead. Defaulted so every positional
    # construction in this module keeps working; set by compute_capital_gains.
    indexation_is_estimated: bool = False
    indexation_note: str = ""
    # THE COST THE GAIN WAS ACTUALLY COMPUTED ON (IT-19) — the actual cost of
    # acquisition, or the Section 55(2)(ac) deemed cost where the substitution
    # ran. Improvement is NOT in it: that is a separate limb of Section 48 and
    # is added on top, exactly as `gain_paise` does.
    cost_of_acquisition_paise: int = 0
    grandfathered_cost_is_applied: bool = False
    # FACTS NOBODY RECORDED, one sentence each, never a guess — and a DIFFERENT
    # thing from `caveats`, which are settled reasons. The panel renders them
    # differently: a gap is actionable (go and record this), a caveat says the
    # section does not reach the transfer. Same split as
    # `domain/gst/rcm_documents.Decision`.
    gaps: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    grandfathering_working: tuple[str, ...] = ()


def compute_capital_gains(
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    purchase_cost_paise: int,
    sale_value_paise: int,
    improvement_cost_paise: int = 0,
    assessee_type: str = ASSESSEE_UNSPECIFIED,
    is_listed_security: Optional[bool] = None,
    fmv_31_01_2018_paise: Optional[int] = None,
) -> CapitalGainsResult:
    """Section 45/48 gain, Section 2(42A) classification, and the applicable
    special tax rate — integer paise throughout, and every rate chosen by the
    date of TRANSFER (see the module docstring's 23-07-2024 fork).

    The indexation flag, the Section 55(2)(ac) cost and the two refusals are
    stamped HERE, once, rather than on each of the eight branches below: each
    is a property of the INPUTS and nothing any branch decides, so threading
    them through every construction would be eight chances to forget it on the
    branch that matters (IT-29)."""
    grandfathered = section_55_2_ac_cost(
        asset_type=asset_type, purchase_date=purchase_date, sale_date=sale_date,
        purchase_cost_paise=purchase_cost_paise, sale_value_paise=sale_value_paise,
        fmv_31_01_2018_paise=fmv_31_01_2018_paise,
        is_listed_security=is_listed_security)
    result = _compute_capital_gains(
        asset_type, purchase_date, sale_date, purchase_cost_paise,
        sale_value_paise, improvement_cost_paise, assessee_type,
        is_listed_security, grandfathered.cost_paise)

    gaps = list(grandfathered.gaps)
    unrecorded_listing = listing_gap(
        asset_type, purchase_date, sale_date, is_listed_security)
    if unrecorded_listing:
        gaps.append(unrecorded_listing)
    result = replace(
        result,
        cost_of_acquisition_paise=grandfathered.cost_paise,
        grandfathered_cost_is_applied=grandfathered.applied,
        gaps=tuple(gaps),
        caveats=grandfathered.caveats,
        grandfathering_working=grandfathered.working,
    )

    purchase_fy = fy_for_date(purchase_date)
    sale_fy = fy_for_date(sale_date)
    missing = [fy for fy in (purchase_fy, sale_fy) if not cii_is_notified(fy)]
    if not missing:
        return result
    return replace(
        result,
        indexation_is_estimated=True,
        indexation_note=(
            f"The Cost Inflation Index for {' and '.join(missing)} is not "
            f"notified in this build, so {CII_BY_FY[_NEWEST_CII_FY]} — the "
            f"index for {_NEWEST_CII_FY} — was used instead. The index for a "
            "year is notified partway through it, usually around June, so "
            "this indexed cost is provisional: it understates the indexed "
            "cost and overstates the gain until the notification is "
            "recorded."),
    )


def _compute_capital_gains(
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    purchase_cost_paise: int,
    sale_value_paise: int,
    improvement_cost_paise: int = 0,
    assessee_type: str = ASSESSEE_UNSPECIFIED,
    is_listed_security: Optional[bool] = None,
    cost_of_acquisition_paise: Optional[int] = None,
) -> CapitalGainsResult:
    months = holding_months(purchase_date, sale_date)
    long_term = is_long_term(asset_type, purchase_date, sale_date, is_listed_security)
    # Transfers on or after 23-07-2024 are governed by the Finance (No. 2)
    # Act 2024 amendments; anything earlier keeps the pre-amendment law.
    pre_2024 = sale_date < FINANCE_NO2_ACT_2024

    # Section 48 is computed on the cost of acquisition, which Section
    # 55(2)(ac) may DEEM to be something other than what was paid. The
    # substitution is resolved by the caller above so it happens once; None
    # means "nobody asked", and the actual cost stands.
    acquisition_paise = (purchase_cost_paise if cost_of_acquisition_paise is None
                         else cost_of_acquisition_paise)
    cost_paise = acquisition_paise + improvement_cost_paise
    gain_paise = sale_value_paise - cost_paise

    purchase_fy = fy_for_date(purchase_date)
    sale_fy = fy_for_date(sale_date)
    cii_purchase = cii_for(purchase_fy)
    cii_sale = cii_for(sale_fy)
    # Indexation runs on the ACTUAL cost, not the Section 55(2)(ac) deemed
    # one: the substitution reaches only assets Section 112A charges, and
    # Section 112A allows no indexation at all — so the two never meet, and
    # taking the deemed cost here would put a figure on the indexed line of a
    # transfer whose indexed line is never read.
    indexed_cost_paise = _round_paise(purchase_cost_paise * cii_sale, cii_purchase) + improvement_cost_paise
    gain_with_indexation_paise = sale_value_paise - indexed_cost_paise


    # Section 111A/112A — listed equity / equity-oriented mutual funds.
    #
    # Both sections require securities transaction tax to have been paid on
    # the transfer (and, for 112A, on the acquisition too, subject to the
    # notified exceptions). That is assumed here from the asset type, as it
    # was in the frontend implementation this module replaces — there is no
    # STT field to read. Likewise Section 112A itself only runs from
    # 01-04-2018; a listed-equity LTCG on a transfer before that date was
    # exempt under the then Section 10(38), which this module does not
    # model. No such transfer can arise in a filable return today.
    if asset_type in _EQUITY_LIKE:
        if not long_term:
            # Section 111A: 15% before 23-07-2024, 20% from that date
            # (Finance (No. 2) Act 2024).
            rate = 15.0 if pre_2024 else 20.0
            rate_bps = 1500 if pre_2024 else 2000
            taxable = max(0, gain_paise)
            tax = _round_paise(taxable * rate_bps, 10000)
            return CapitalGainsResult(
                months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
                rate, None, tax, None, tax, "Section 111A",
                f"STCG on listed equity/equity MF: {rate:g}% "
                + ("(pre-23-07-2024 rate)." if pre_2024
                   else "(Finance (No. 2) Act 2024, transfers from 23-07-2024)."),
                False,
            )
        # Section 112A: 10% over ₹1,00,000 before 23-07-2024, 12.5% over
        # ₹1,25,000 from that date — on the gain computed above, which for a
        # holding acquired before 01-02-2018 is measured against the Section
        # 55(2)(ac) GRANDFATHERED cost where the caller supplied a 31-01-2018
        # fair market value, and against the actual cost (with the gap named)
        # where they did not. See `section_55_2_ac_cost`.
        #
        # Both ceilings are ANNUAL — Section 112A(2) exempts the first slice
        # of the assessee's aggregate 112A gain for the year, not of each
        # transfer. This function computes ONE transfer, so a caller that
        # sums several transfers' tax_liability_paise will have applied the
        # exemption once per transfer. That is why the return-level engine
        # (itr_engine.py) takes the year's aggregate 112A gain as a single
        # figure and applies the exemption to it exactly once.
        exemption = _LTCG_112A_EXEMPTION_PRE_2024_PAISE if pre_2024 else _LTCG_112A_EXEMPTION_PAISE
        rate = 10.0 if pre_2024 else 12.5
        rate_bps = 1000 if pre_2024 else 1250
        taxable = max(0, gain_paise - exemption)
        tax = _round_paise(taxable * rate_bps, 10000)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            rate, None, tax, None, tax, "Section 112A",
            f"LTCG on listed equity/equity MF: {rate:g}% on gains exceeding "
            f"₹{exemption // 100:,} "
            + ("(pre-23-07-2024 rate and exemption)." if pre_2024
               else "(Finance (No. 2) Act 2024, transfers from 23-07-2024)."),
            False,
        )

    # Section 50AA — debt mutual funds (Finance Act 2023): the gain is
    # DEEMED short-term however long the unit was held, so it is always
    # taxed at the assessee's own slab rate. Shown at an ESTIMATED flat rate
    # (not a real statutory rate) since the actual rate depends on the
    # taxpayer's own slab.
    #
    # The section reaches only a unit "acquired on or after the 1st day of
    # April, 2023". A unit bought before that date is an ordinary capital
    # asset — it falls through to the Section 2(42A)/112 treatment below,
    # which for a transfer before 23-07-2024 means a 36-month holding
    # threshold and 20% with indexation if long-term. Applying Section 50AA
    # to every debt-MF row regardless of when it was bought charged slab
    # rate on gains the section does not reach, including on transfers made
    # before the section commenced at all.
    if asset_type in _DEBT_MF_LIKE and purchase_date >= SECTION_50AA_FROM:
        rate = 30.0
        taxable = max(0, gain_paise)
        tax = _round_paise(taxable * 30, 100)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            rate, None, tax, None, tax, "Section 50AA (Finance Act 2023)",
            "Debt MF (acquired after 1 Apr 2023): taxed at the assessee's income slab rate — "
            "shown at an estimated 30% (highest slab); adjust for the actual slab.", True,
        )

    # Section 115BBH — VDA/cryptocurrency: flat 30%, regardless of holding
    # period (STCG/LTCG classification is computed above only for display).
    # The section runs from AY 2023-24 (transfers from 01-04-2022); an
    # earlier transfer is not modelled.
    if asset_type in _VDA_LIKE:
        rate = 30.0
        taxable = max(0, gain_paise)
        tax = _round_paise(taxable * 30, 100)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            rate, None, tax, None, tax, "Section 115BBH",
            "VDA/cryptocurrency: 30% flat regardless of holding period. Section 194S TDS "
            "(1%) also applies on every transaction, separately from this income-tax liability.", False,
        )

    # Section 112 — every other asset (immovable property, unlisted shares,
    # bonds, gold, "other", and a pre-01-04-2023 debt MF unit). STCG is a
    # slab-rate estimate; LTCG depends on the date of transfer.
    outside_50aa = asset_type in _DEBT_MF_LIKE
    debt_mf_note = (
        " This unit was acquired before 1 Apr 2023, so Section 50AA does not reach it."
        if outside_50aa else ""
    )

    if not long_term:
        rate = 30.0
        taxable = max(0, gain_paise)
        tax = _round_paise(taxable * 30, 100)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            rate, None, tax, None, tax, "Section 48",
            "STCG on this asset: taxed at the assessee's income slab rate — shown at an "
            "estimated 30% (highest slab); adjust for the actual slab." + debt_mf_note, True,
        )

    if pre_2024:
        # Section 112(1) read with the second proviso to Section 48: before
        # 23-07-2024 a long-term gain on a non-equity asset was charged at
        # 20% on the INDEXED cost. Indexation was mandatory, not an option,
        # so there is no lower-of comparison to make here.
        #
        # KNOWN GAP, AND ITS REASON CHANGED WITH IT-28 — read this before
        # "finishing the job". The proviso to Section 112(1) let a LISTED
        # security, a unit and a zero coupon bond be charged at 10% WITHOUT
        # indexation where that came to less than 20% with it. Until IT-28 the
        # reason it was not offered was that nothing recorded whether the row
        # was listed; `is_listed_security` records that now, so the reason is
        # no longer true and the option is STILL not offered, deliberately:
        # the proviso's own limbs — which assessees it reaches, and whether
        # the comparison is made before or after the second proviso to Section
        # 48 — could not be read against the Act, because direct egress is
        # refused at this environment's proxy. A rate written from memory that
        # REDUCES what a client pays is the direction this repository refuses
        # (`SECTION_50_3_NOTIFIED_RATE_BPS`, the Section 194I(a)/194J(a)
        # limbs): an under-charge is a shortfall carrying Section 234B
        # interest, an over-charge is a figure a CA checks. So the answer
        # stays 20% with indexation, which errs towards MORE tax, and this
        # note stays until somebody reads the proviso.
        taxable_indexed = max(0, gain_with_indexation_paise)
        tax_indexed = _round_paise(taxable_indexed * 20, 100)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            20.0, None, tax_indexed, None, tax_indexed, "Section 112",
            "LTCG on this asset transferred before 23-07-2024: 20% WITH indexation "
            "(Section 112(1) with the 2nd proviso to Section 48) — indexation is mandatory "
            "here, not a choice." + debt_mf_note, False,
        )

    # From 23-07-2024: 12.5% flat, and the second proviso to Section 48 no
    # longer gives indexation at all — EXCEPT under the fifth proviso to
    # Section 112(1), the grandfather clause for land or building acquired
    # before 23-07-2024 held by a resident individual or HUF, whose tax is
    # capped at 20% computed with indexation.
    taxable_flat = max(0, gain_paise)
    tax_flat = _round_paise(taxable_flat * 125, 1000)  # 12.5%, no indexation

    grandfatherable = asset_type in _PROPERTY_LIKE and purchase_date < FINANCE_NO2_ACT_2024
    if grandfatherable:
        taxable_indexed = max(0, gain_with_indexation_paise)
        tax_indexed = _round_paise(taxable_indexed * 20, 100)  # 20%, with indexation
        if assessee_type == ASSESSEE_RESIDENT_INDIVIDUAL_HUF:
            final_tax = min(tax_flat, tax_indexed)
            note = (
                "LTCG on immovable property acquired before 23-07-2024: 12.5% without "
                "indexation OR 20% with indexation (fifth proviso to Section 112(1), "
                "resident individual/HUF) — whichever is lower."
            )
        else:
            # A company, an LLP, a firm or a non-resident is outside the
            # proviso; so is an assessee whose status nobody has stated.
            # Both figures are still returned so the comparison is visible.
            final_tax = tax_flat
            note = (
                "LTCG on immovable property: 12.5% without indexation. The 20%-with-"
                "indexation option (fifth proviso to Section 112(1)) is NOT applied — it is "
                "available only to a resident individual or HUF, and this computation was "
                + ("run for another class of assessee." if assessee_type == ASSESSEE_OTHER
                   else "run without the assessee's status. State it to claim the option.")
            )
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            12.5, 20.0, tax_flat, tax_indexed, final_tax, "Section 112 (Finance (No. 2) Act 2024)",
            note, False,
        )

    return CapitalGainsResult(
        months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
        12.5, None, tax_flat, None, tax_flat, "Section 112 (Finance (No. 2) Act 2024)",
        "LTCG on this asset: 12.5% without indexation (transfers from 23-07-2024) — no "
        "indexation choice for this asset type." + debt_mf_note, False,
    )

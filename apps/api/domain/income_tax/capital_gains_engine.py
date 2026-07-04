"""
Capital gains computation — IT Act 1961 Section 45 (chargeability), Section 48
(mode of computation + indexation proviso), Section 2(42A) (holding-period
classification), Section 111A (STCG, listed equity/equity MF), Section 112A
(LTCG, listed equity/equity MF), Section 112 (LTCG, other assets), Section
115BBH (VDA/cryptocurrency), Section 50AA (debt mutual funds, Finance Act
2023).

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

VERIFICATION STATUS: the CII table, the two-tier (12/24 month) holding
threshold, and the "only immovable property gets an indexation choice"
asymmetry are ported verbatim from the pre-existing frontend implementation
— the only source for these figures anywhere in this repo — not
independently re-derived or re-confirmed against the Finance Act 2024 text
during this migration. Flagged for the same "pending statutory
verification" treatment as FY2026-27 income-tax figures (statutory_rates.py)
and the non-Karnataka Professional Tax slabs (routers/payroll.py) — see
roadmap R3.1/R3.12. Updating CII_BY_FY for a newly-notified year, or
correcting any of the rates below, is a pure data change, not a code change.

Integer paise throughout — never float in any stored or returned amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


# ── Cost Inflation Index (CII) — IT Act Section 48, 2nd proviso ─────────────
# Base year FY 2001-02 = 100. Ported verbatim from the pre-existing frontend
# table — see module docstring's verification-status note. CBDT typically
# notifies each FY's CII partway through that year, so a not-yet-notified
# FY has no entry here; cii_for() falls back to the latest known year rather
# than guessing.
CII_BY_FY: dict[str, int] = {
    "2001-02": 100, "2002-03": 105, "2003-04": 109, "2004-05": 113, "2005-06": 117,
    "2006-07": 122, "2007-08": 129, "2008-09": 137, "2009-10": 148, "2010-11": 167,
    "2011-12": 184, "2012-13": 200, "2013-14": 220, "2014-15": 240, "2015-16": 254,
    "2016-17": 264, "2017-18": 272, "2018-19": 280, "2019-20": 289, "2020-21": 301,
    "2021-22": 317, "2022-23": 331, "2023-24": 348, "2024-25": 363, "2025-26": 380,
}
LATEST_CII_FY = "2025-26"


def cii_for(fy: str) -> int:
    """CII for a given FY string ('2025-26'); falls back to the latest known
    FY's value for anything not yet in the table (matches
    statutory_rates.rates_for's same unknown-future-year convention)."""
    return CII_BY_FY.get(fy, CII_BY_FY[LATEST_CII_FY])


def fy_for_date(d: date) -> str:
    """Indian FY string ('2025-26') for a given date — Apr 1 to Mar 31."""
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


# ── Asset types ──────────────────────────────────────────────────────────────
# Accepts both the interactive calculator's asset types and the persisted
# register's (coarser) asset types — both map onto the same underlying
# treatment. "bonds"/"other"/"unlisted"/"gold" are all "other assets" under
# Section 112: 24-month threshold, 12.5% flat, NO indexation choice (the
# Budget 2024 grandfather clause is specific to immovable property).
_EQUITY_LIKE = frozenset({"equity", "equity_shares", "mutual_funds"})
_PROPERTY_LIKE = frozenset({"property"})
_DEBT_MF_LIKE = frozenset({"debt_mf"})
_VDA_LIKE = frozenset({"vda"})
# Everything else (unlisted, gold, bonds, other, ...) falls through to the
# generic "other assets" Section 112 treatment.

ASSET_TYPES = ("equity", "debt_mf", "property", "unlisted", "vda", "gold")
REGISTER_ASSET_TYPES = ("equity_shares", "mutual_funds", "property", "bonds", "other")

_LONG_TERM_MONTHS_EQUITY = 12
_LONG_TERM_MONTHS_OTHER = 24

_LTCG_112A_EXEMPTION_PAISE = 125_000_00  # ₹1,25,000, Section 112A


def holding_months(purchase_date: date, sale_date: date) -> int:
    return (sale_date.year - purchase_date.year) * 12 + (sale_date.month - purchase_date.month)


def is_long_term(asset_type: str, months: int) -> bool:
    threshold = _LONG_TERM_MONTHS_EQUITY if asset_type in _EQUITY_LIKE else _LONG_TERM_MONTHS_OTHER
    return months >= threshold


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
    tax_without_indexation_paise: int         # tax at tax_rate_percent — always populated
    tax_with_indexation_paise: Optional[int]  # tax at tax_with_indexation_percent — only when a choice exists
    tax_liability_paise: int                 # final tax payable (lower of the two, if both computed) —
                                              # exposed explicitly so callers never re-derive this rounding
                                              # themselves (integer round-half-up, not float Math.round)
    section_ref: str
    note: str
    is_slab_rate_estimate: bool              # True where the real rate depends on the assessee's own
                                              # slab and this is shown at a flat estimate, not a statutory rate


def compute_capital_gains(
    asset_type: str,
    purchase_date: date,
    sale_date: date,
    purchase_cost_paise: int,
    sale_value_paise: int,
    improvement_cost_paise: int = 0,
) -> CapitalGainsResult:
    """Section 45/48 gain, Section 2(42A) classification, and the applicable
    special tax rate — integer paise throughout."""
    months = holding_months(purchase_date, sale_date)
    long_term = is_long_term(asset_type, months)

    cost_paise = purchase_cost_paise + improvement_cost_paise
    gain_paise = sale_value_paise - cost_paise

    cii_purchase = cii_for(fy_for_date(purchase_date))
    cii_sale = cii_for(fy_for_date(sale_date))
    indexed_cost_paise = _round_paise(purchase_cost_paise * cii_sale, cii_purchase) + improvement_cost_paise
    gain_with_indexation_paise = sale_value_paise - indexed_cost_paise

    # Section 111A/112A — listed equity / equity-oriented mutual funds.
    if asset_type in _EQUITY_LIKE:
        if not long_term:
            rate = 20.0
            taxable = max(0, gain_paise)
            tax = _round_paise(taxable * 20, 100)
            return CapitalGainsResult(
                months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
                rate, None, tax, None, tax, "Section 111A",
                "STCG on listed equity/equity MF: 20% (Budget 2024).", False,
            )
        taxable = max(0, gain_paise - _LTCG_112A_EXEMPTION_PAISE)
        tax = _round_paise(taxable * 125, 1000)  # 12.5%
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            12.5, None, tax, None, tax, "Section 112A",
            f"LTCG on listed equity/equity MF: 12.5% on gains exceeding ₹1,25,000 (Budget 2024).", False,
        )

    # Section 50AA — debt mutual funds (Finance Act 2023): no LTCG at all,
    # always taxed at the assessee's own slab rate. Shown at an ESTIMATED
    # flat rate (not a real statutory rate) since the actual rate depends on
    # the taxpayer's own slab.
    if asset_type in _DEBT_MF_LIKE:
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
    # bonds, gold, "other"). STCG is a slab-rate estimate; LTCG is 12.5%
    # flat, EXCEPT immovable property, which (Budget 2024 grandfather
    # clause, resident individuals/HUF) may instead choose 20% WITH
    # indexation if that yields lower tax — the only asset type in this
    # bucket eligible for that choice.
    if not long_term:
        rate = 30.0
        taxable = max(0, gain_paise)
        tax = _round_paise(taxable * 30, 100)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            rate, None, tax, None, tax, "Section 48",
            "STCG on this asset: taxed at the assessee's income slab rate — shown at an "
            "estimated 30% (highest slab); adjust for the actual slab.", True,
        )

    taxable_flat = max(0, gain_paise)
    tax_flat = _round_paise(taxable_flat * 125, 1000)  # 12.5%, no indexation

    if asset_type in _PROPERTY_LIKE:
        taxable_indexed = max(0, gain_with_indexation_paise)
        tax_indexed = _round_paise(taxable_indexed * 20, 100)  # 20%, with indexation
        final_tax = min(tax_flat, tax_indexed)
        return CapitalGainsResult(
            months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
            12.5, 20.0, tax_flat, tax_indexed, final_tax, "Section 112 (Budget 2024)",
            "LTCG on immovable property: 12.5% without indexation OR 20% with indexation "
            "(resident individual/HUF choice, Budget 2024 grandfather clause) — whichever is lower.",
            False,
        )

    return CapitalGainsResult(
        months, long_term, gain_paise, indexed_cost_paise, gain_with_indexation_paise,
        12.5, None, tax_flat, None, tax_flat, "Section 112 (Budget 2024)",
        "LTCG on this asset: 12.5% without indexation (Budget 2024) — no indexation choice "
        "for this asset type.", False,
    )

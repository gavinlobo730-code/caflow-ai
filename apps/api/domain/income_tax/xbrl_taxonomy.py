"""The MCA XBRL taxonomy versions this product holds, and whether each has been checked (POST-A-118).

THE SEAM
    `domain/income_tax/xbrl_service` used to hold one hand-typed tag table, one namespace string and a `taxonomy_version`
    argument that nothing read: a package could be created under ANY version string, the tag table and the namespace were
    the same whatever it said, and nothing on a screen or in a response said that the tags had never been run through MCA's own
    validation tool. This module is the one place that knows which versions exist, what tags and namespace each carries and
    whether a person has checked it, in the shape every statutory registry here has (a `*_BY_VERSION` dictionary and a
    `LATEST_VERIFIED_*` marker; compare `domain/income_tax/statutory_rates` and `itr_schema`).

WHAT IS VERIFIED, AND WHAT IS NOT
    NOTHING. `MCA_2023` is the one entry and it is `verified=False`: its tags are the hand-typed `in-bse-fin` names the product
    has always emitted, written from the Schedule III line items, and no copy of MCA's published taxonomy or run of MCA's XBRL
    Validation Tool is on record (ledger POST-C-170 is the human step: read the MCA page, download the validator and the C&I and
    Ind AS taxonomies, commit them under `docs/compliance/sources/`). `LATEST_VERIFIED_TAXONOMY` is therefore None, and moving it
    without a downloaded copy would promote a guess to a checked figure, which is the whole reason the marker exists.

    The `http://www.mca.gov.in/...` strings are XML NAMESPACE URIs. They are identifiers and are never dereferenced; do not
    "correct" one to a URL that resolves.

WHAT A VERSION NOW DOES
    It selects the tag table and the namespace the validator and the XML writer use, an unregistered version is refused (a
    `ValueError` the router answers 422) instead of being stored, and every response that names a version carries
    `taxonomy_notice`, the sentence saying whether it has been checked. Adding a version is a human step: download the taxonomy,
    add the entry with `verified=False`, then flip it only after the validator accepts a sample file.

# CA REVIEW REQUIRED — DO NOT AUTO-FILE XBRL to MCA portal
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# (schedule_line, xbrl_tag, label, is_mandatory)
Mapping = tuple[str, str, str, bool]

# Default MCA 2023 XBRL tag mappings (Schedule III → XBRL)
# Companies Act 2013, Schedule III Division I (for companies other than NBFCs)
_MCA_2023_MAPPINGS: tuple = (
    # Balance Sheet — Equity & Liabilities
    ("BalanceSheet.Equity.ShareCapital", "in-bse-fin:ShareCapital", "Share Capital", True),
    ("BalanceSheet.Equity.ReservesAndSurplus", "in-bse-fin:ReservesAndSurplus", "Reserves and Surplus", True),
    ("BalanceSheet.Equity.MoneyReceivedAgainstShareWarrants", "in-bse-fin:MoneyReceivedAgainstShareWarrants", "Money Received Against Share Warrants", False),
    ("BalanceSheet.NonCurrentLiabilities.LongTermBorrowings", "in-bse-fin:LongTermBorrowings", "Long-term Borrowings", True),
    ("BalanceSheet.NonCurrentLiabilities.DeferredTaxLiabilities", "in-bse-fin:DeferredTaxLiabilities", "Deferred Tax Liabilities (Net)", False),
    ("BalanceSheet.NonCurrentLiabilities.OtherLongTermLiabilities", "in-bse-fin:OtherLongTermLiabilities", "Other Long Term Liabilities", False),
    ("BalanceSheet.NonCurrentLiabilities.LongTermProvisions", "in-bse-fin:LongTermProvisions", "Long Term Provisions", False),
    ("BalanceSheet.CurrentLiabilities.ShortTermBorrowings", "in-bse-fin:ShortTermBorrowings", "Short-term Borrowings", True),
    ("BalanceSheet.CurrentLiabilities.TradePayables", "in-bse-fin:TradePayables", "Trade Payables", True),
    ("BalanceSheet.CurrentLiabilities.OtherCurrentLiabilities", "in-bse-fin:OtherCurrentLiabilities", "Other Current Liabilities", True),
    ("BalanceSheet.CurrentLiabilities.ShortTermProvisions", "in-bse-fin:ShortTermProvisions", "Short Term Provisions", False),
    # Balance Sheet — Assets
    ("BalanceSheet.NonCurrentAssets.FixedAssets.TangibleAssets", "in-bse-fin:TangibleAssets", "Tangible Assets", True),
    ("BalanceSheet.NonCurrentAssets.FixedAssets.IntangibleAssets", "in-bse-fin:IntangibleAssets", "Intangible Assets", False),
    ("BalanceSheet.NonCurrentAssets.FixedAssets.CapitalWorkInProgress", "in-bse-fin:CapitalWorkInProgress", "Capital Work in Progress", False),
    ("BalanceSheet.NonCurrentAssets.NonCurrentInvestments", "in-bse-fin:NonCurrentInvestments", "Non-current Investments", False),
    ("BalanceSheet.NonCurrentAssets.DeferredTaxAssets", "in-bse-fin:DeferredTaxAssets", "Deferred Tax Assets (Net)", False),
    ("BalanceSheet.NonCurrentAssets.LongTermLoansAndAdvances", "in-bse-fin:LongTermLoansAndAdvances", "Long Term Loans and Advances", False),
    ("BalanceSheet.NonCurrentAssets.OtherNonCurrentAssets", "in-bse-fin:OtherNonCurrentAssets", "Other Non-current Assets", False),
    ("BalanceSheet.CurrentAssets.CurrentInvestments", "in-bse-fin:CurrentInvestments", "Current Investments", False),
    ("BalanceSheet.CurrentAssets.Inventories", "in-bse-fin:Inventories", "Inventories", True),
    ("BalanceSheet.CurrentAssets.TradeReceivables", "in-bse-fin:TradeReceivables", "Trade Receivables", True),
    ("BalanceSheet.CurrentAssets.CashAndCashEquivalents", "in-bse-fin:CashAndCashEquivalents", "Cash and Cash Equivalents", True),
    ("BalanceSheet.CurrentAssets.ShortTermLoansAndAdvances", "in-bse-fin:ShortTermLoansAndAdvances", "Short Term Loans and Advances", False),
    ("BalanceSheet.CurrentAssets.OtherCurrentAssets", "in-bse-fin:OtherCurrentAssets", "Other Current Assets", False),
    # P&L
    ("ProfitAndLoss.Revenue.RevenueFromOperations", "in-bse-fin:RevenueFromOperations", "Revenue from Operations", True),
    ("ProfitAndLoss.Revenue.OtherIncome", "in-bse-fin:OtherIncome", "Other Income", False),
    ("ProfitAndLoss.Expenses.CostOfMaterialsConsumed", "in-bse-fin:CostOfMaterialsConsumed", "Cost of Materials Consumed", False),
    ("ProfitAndLoss.Expenses.EmployeeBenefitExpense", "in-bse-fin:EmployeeBenefitExpense", "Employee Benefits Expense", True),
    ("ProfitAndLoss.Expenses.FinanceCosts", "in-bse-fin:FinanceCosts", "Finance Costs", True),
    ("ProfitAndLoss.Expenses.DepreciationAndAmortisation", "in-bse-fin:DepreciationAndAmortisation", "Depreciation and Amortisation Expense", True),
    ("ProfitAndLoss.Expenses.OtherExpenses", "in-bse-fin:OtherExpenses", "Other Expenses", True),
    ("ProfitAndLoss.ProfitBeforeTax", "in-bse-fin:ProfitBeforeTax", "Profit Before Tax", True),
    ("ProfitAndLoss.TaxExpense.CurrentTax", "in-bse-fin:CurrentTax", "Current Tax", True),
    ("ProfitAndLoss.TaxExpense.DeferredTax", "in-bse-fin:DeferredTax", "Deferred Tax", False),
    ("ProfitAndLoss.ProfitForThePeriod", "in-bse-fin:ProfitForThePeriod", "Profit for the Period", True),
)


@dataclass(frozen=True)
class Taxonomy:
    version: str
    prefix: str            # the namespace prefix the tags carry, e.g. "in-bse-fin"
    namespace: str         # an XML namespace URI: an identifier, never dereferenced
    mappings: tuple        # of Mapping
    verified: bool = False


DEFAULT_TAXONOMY = "MCA_2023"

TAXONOMY_BY_VERSION: dict[str, Taxonomy] = {
    "MCA_2023": Taxonomy(
        version="MCA_2023",
        prefix="in-bse-fin",
        namespace="http://www.mca.gov.in/taxonomy/2023/in-bse-fin",
        mappings=_MCA_2023_MAPPINGS,
        verified=False,
    ),
}

# The newest version a person has checked against MCA's published taxonomy and validation tool. None: no version has been.
LATEST_VERIFIED_TAXONOMY: Optional[str] = None


class UnknownTaxonomy(ValueError):
    """A taxonomy version this product does not hold. A ValueError so a caller that already maps ValueError to a refusal does."""


def taxonomy_for(version: Optional[str]) -> Taxonomy:
    """The registry entry for `version`; a blank or missing one means the default. An unregistered version is refused, never
    substituted: a package filed under a version whose tags were never loaded would be tagged against the wrong taxonomy."""
    name = (version or "").strip() or DEFAULT_TAXONOMY
    try:
        return TAXONOMY_BY_VERSION[name]
    except KeyError:
        held = ", ".join(sorted(TAXONOMY_BY_VERSION))
        raise UnknownTaxonomy(f"Taxonomy version {name!r} is not one this product holds. It holds: {held}.") from None


def taxonomy_notice(version: Optional[str]) -> Optional[str]:
    """The sentence a screen shows beside a version: None when it has been checked, otherwise what has and has not been done."""
    try:
        entry = taxonomy_for(version)
    except UnknownTaxonomy as exc:
        return str(exc)
    if entry.verified:
        return None
    return (f"The {entry.version} tags were written by hand from the Schedule III line items. They have not been checked against "
            "MCA's published taxonomy and MCA's XBRL Validation Tool has not been run on a file made from them; run that tool "
            "before the file is used.")

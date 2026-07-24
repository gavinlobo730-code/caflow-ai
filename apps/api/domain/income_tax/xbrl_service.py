"""
XBRL Generation Engine — Schedule III → MCA taxonomy mapping.
Companies Act 2013, Schedule III — Balance Sheet and P&L format.
MCA XBRL taxonomy version MCA_2023.

# CA REVIEW REQUIRED — DO NOT AUTO-FILE XBRL to MCA portal
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring
import xml.etree.ElementTree as ET

_logger = logging.getLogger("caflow.xbrl")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_PACKAGES: dict[str, dict] = {}

# Default MCA 2023 XBRL tag mappings (Schedule III → XBRL)
# Companies Act 2013, Schedule III Division I (for companies other than NBFCs)
DEFAULT_MAPPINGS = [
    # Balance Sheet — Equity & Liabilities
    ("BalanceSheet.Equity.ShareCapital", "in-bse-fin:ShareCapital", "Share Capital", True),
    ("BalanceSheet.Equity.ReservesAndSurplus", "in-bse-fin:ReservesAndSurplus", "Reserves and Surplus", True),
    ("BalanceSheet.Equity.MoneyReceivedAgainstShareWarrants", "in-bse-fin:MoneyReceivedAgainstShareWarrants", "Money Received Against Share Warrants", False),
    ("BalanceSheet.NonCurrentLiabilities.LongTermBorrowings", "in-bse-fin:LongTermBorrowings", "Long Term Borrowings", True),
    ("BalanceSheet.NonCurrentLiabilities.DeferredTaxLiabilities", "in-bse-fin:DeferredTaxLiabilities", "Deferred Tax Liabilities (Net)", False),
    ("BalanceSheet.NonCurrentLiabilities.OtherLongTermLiabilities", "in-bse-fin:OtherLongTermLiabilities", "Other Long Term Liabilities", False),
    ("BalanceSheet.NonCurrentLiabilities.LongTermProvisions", "in-bse-fin:LongTermProvisions", "Long Term Provisions", False),
    ("BalanceSheet.CurrentLiabilities.ShortTermBorrowings", "in-bse-fin:ShortTermBorrowings", "Short Term Borrowings", True),
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
    ("ProfitAndLoss.Expenses.EmployeeBenefitExpense", "in-bse-fin:EmployeeBenefitExpense", "Employee Benefit Expense", True),
    ("ProfitAndLoss.Expenses.FinanceCosts", "in-bse-fin:FinanceCosts", "Finance Costs", True),
    ("ProfitAndLoss.Expenses.DepreciationAndAmortisation", "in-bse-fin:DepreciationAndAmortisation", "Depreciation and Amortisation Expense", True),
    ("ProfitAndLoss.Expenses.OtherExpenses", "in-bse-fin:OtherExpenses", "Other Expenses", True),
    ("ProfitAndLoss.ProfitBeforeTax", "in-bse-fin:ProfitBeforeTax", "Profit Before Tax", True),
    ("ProfitAndLoss.TaxExpense.CurrentTax", "in-bse-fin:CurrentTax", "Current Tax", True),
    ("ProfitAndLoss.TaxExpense.DeferredTax", "in-bse-fin:DeferredTax", "Deferred Tax", False),
    ("ProfitAndLoss.ProfitForThePeriod", "in-bse-fin:ProfitForThePeriod", "Profit for the Period", True),
]


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


def create_xbrl_package(
    firm_id: str,
    client_id: str,
    financial_year: str,
    created_by: str,
    year_end_engagement_id: str | None = None,
    taxonomy_version: str = "MCA_2023",
) -> dict:
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "taxonomy_version": taxonomy_version,
            "status": "draft",
            "year_end_engagement_id": year_end_engagement_id,
            "balance_sheet_json": {},
            "pnl_json": {},
            "notes_json": {},
            "xbrl_xml": None,
            "validation_errors": [],
            "missing_tags": [],
            "version": 1,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_PACKAGES[row["id"]] = row
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "taxonomy_version": taxonomy_version,
        "status": "draft",
        "year_end_engagement_id": year_end_engagement_id,
        "created_by": created_by,
    }
    res = sb.table("xbrl_packages").insert(row).execute()
    return res.data[0] if res.data else row


def list_xbrl_packages(firm_id: str, client_id: str) -> list[dict]:
    if _USE_MOCK:
        return [p for p in _MOCK_PACKAGES.values()
                if p["firm_id"] == firm_id and p["client_id"] == client_id]
    sb = _supabase()
    res = sb.table("xbrl_packages").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).order("created_at", desc=True).execute()
    return res.data or []


def update_xbrl_data(
    firm_id: str,
    package_id: str,
    balance_sheet_json: dict | None = None,
    pnl_json: dict | None = None,
    notes_json: dict | None = None,
) -> dict:
    update: dict = {"updated_at": datetime.now(timezone.utc).isoformat(), "status": "draft"}
    if balance_sheet_json is not None:
        update["balance_sheet_json"] = balance_sheet_json
    if pnl_json is not None:
        update["pnl_json"] = pnl_json
    if notes_json is not None:
        update["notes_json"] = notes_json

    if _USE_MOCK:
        if package_id in _MOCK_PACKAGES:
            _MOCK_PACKAGES[package_id].update(update)
        return _MOCK_PACKAGES.get(package_id, {})

    sb = _supabase()
    res = sb.table("xbrl_packages").update(update).eq("id", package_id).eq(
        "firm_id", firm_id
    ).execute()
    return res.data[0] if res.data else {}


def validate_xbrl_package(
    firm_id: str,
    package_id: str,
    taxonomy_version: str = "MCA_2023",
) -> dict:
    """
    Validate XBRL package against MCA taxonomy.
    Checks: mandatory tags present, data types correct, balancing equations.
    Returns validation report with errors and missing tags.
    """
    if _USE_MOCK:
        pkg = _MOCK_PACKAGES.get(package_id, {})
        bs = pkg.get("balance_sheet_json", {})
        pnl = pkg.get("pnl_json", {})
        data = {**bs, **pnl}
        errors, missing = _run_validation(data, taxonomy_version)
        pkg["validation_errors"] = errors
        pkg["missing_tags"] = missing
        pkg["status"] = "validation_failed" if errors or missing else "validated"
        return pkg

    sb = _supabase()
    pkg_res = sb.table("xbrl_packages").select("*").eq("id", package_id).eq(
        "firm_id", firm_id
    ).single().execute()
    if not pkg_res.data:
        raise ValueError("XBRL package not found")

    pkg = pkg_res.data
    data = {**pkg.get("balance_sheet_json", {}), **pkg.get("pnl_json", {})}
    errors, missing = _run_validation(data, taxonomy_version)

    new_status = "validation_failed" if (errors or missing) else "validated"
    update_res = sb.table("xbrl_packages").update({
        "validation_errors": errors,
        "missing_tags": missing,
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", package_id).execute()

    result = update_res.data[0] if update_res.data else pkg
    result["validation_errors"] = errors
    result["missing_tags"] = missing
    return result


def _check_balance_equation(data: dict) -> list[str]:
    """Companies Act 2013, Schedule III, Part I: Total Assets must equal
    Total Equity and Liabilities. DEFAULT_MAPPINGS carries no explicit
    "TotalAssets"/"TotalEquityAndLiabilities" tag, so sum the Balance Sheet
    lines by their section ("...NonCurrentAssets.../...CurrentAssets..." vs
    "...Equity..."/"...Liabilities...") — the same grouping the section
    names themselves encode."""
    total_assets = 0
    total_equity_liab = 0
    for schedule_line, _xbrl_tag, _label, _mandatory in DEFAULT_MAPPINGS:
        val = data.get(schedule_line)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        parts = schedule_line.split(".")
        if len(parts) < 2 or parts[0] != "BalanceSheet":
            continue
        section = parts[1]
        if section == "Equity" or "Liabilities" in section:
            total_equity_liab += val
        elif "Assets" in section:
            total_assets += val

    if total_assets != total_equity_liab:
        return [
            f"Balance Sheet does not balance: Total Assets ({total_assets} paise) != "
            f"Total Equity & Liabilities ({total_equity_liab} paise), "
            f"difference {total_assets - total_equity_liab} paise"
        ]
    return []


def _run_validation(data: dict, taxonomy_version: str) -> tuple[list[str], list[str]]:
    """Check mandatory tags, data type compliance, and the Balance Sheet
    equation (Total Assets == Total Equity and Liabilities)."""
    errors: list[str] = []
    missing: list[str] = []

    for schedule_line, xbrl_tag, label, is_mandatory in DEFAULT_MAPPINGS:
        if is_mandatory and schedule_line not in data:
            missing.append(f"{schedule_line} ({xbrl_tag}) — {label}")
        elif schedule_line in data:
            val = data[schedule_line]
            if not isinstance(val, (int, float)):
                errors.append(f"{schedule_line}: expected numeric value, got {type(val).__name__}")
            if isinstance(val, float):
                errors.append(f"{schedule_line}: use integer paise — never float")

    errors.extend(_check_balance_equation(data))
    return errors, missing


def generate_xbrl_xml(
    firm_id: str,
    package_id: str,
    client_name: str,
    cin: str,
) -> str:
    """
    Generate MCA XBRL XML from validated package data.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA portal
    """
    if _USE_MOCK:
        pkg = _MOCK_PACKAGES.get(package_id, {})
    else:
        sb = _supabase()
        pkg_res = sb.table("xbrl_packages").select("*").eq("id", package_id).eq(
            "firm_id", firm_id
        ).single().execute()
        if not pkg_res.data:
            raise ValueError("XBRL package not found")
        pkg = pkg_res.data

    if pkg.get("status") not in ("validated", "reviewed"):
        raise ValueError("XBRL package must be validated before generating XML")

    # Build XBRL XML structure
    xbrl_ns = "http://www.xbrl.org/2003/instance"
    mca_ns = "http://www.mca.gov.in/taxonomy/2023/in-bse-fin"
    xbrl = Element("xbrl", {
        "xmlns": xbrl_ns,
        "xmlns:in-bse-fin": mca_ns,
        "xmlns:xbrli": xbrl_ns,
    })

    # Context
    ctx = SubElement(xbrl, "context", {"id": "CurrentPeriod"})
    entity = SubElement(ctx, "entity")
    SubElement(entity, "identifier", {"scheme": "http://www.mca.gov.in"}).text = cin
    period = SubElement(ctx, "period")
    fy_start, fy_end_yr = pkg["financial_year"].split("-")
    SubElement(period, "startDate").text = f"{fy_start}-04-01"
    SubElement(period, "endDate").text = f"20{fy_end_yr}-03-31"

    # Unit
    unit = SubElement(xbrl, "unit", {"id": "INR"})
    SubElement(unit, "measure").text = "iso4217:INR"

    # Data items
    all_data = {
        **pkg.get("balance_sheet_json", {}),
        **pkg.get("pnl_json", {}),
    }
    for schedule_line, xbrl_tag, _, _ in DEFAULT_MAPPINGS:
        if schedule_line in all_data:
            # Convert paise to rupees for XBRL (store in rupees per MCA requirement).
            # task #240 fix: floor division truncated every non-zero paise
            # remainder toward zero (e.g. 12,345 paise -> Rs 123, silently
            # dropping 45 paise) instead of rounding to the nearest rupee —
            # never float, per CLAUDE.md, so round via Decimal.
            val_paise = all_data[schedule_line]
            if isinstance(val_paise, int) and not isinstance(val_paise, bool):
                val_rupees = int(
                    (Decimal(val_paise) / 100).to_integral_value(rounding=ROUND_HALF_UP)
                )
            else:
                val_rupees = val_paise
            elem = SubElement(xbrl, xbrl_tag, {
                "contextRef": "CurrentPeriod",
                "unitRef": "INR",
                "decimals": "0",
            })
            elem.text = str(val_rupees)

    xml_str = tostring(xbrl, encoding="unicode", xml_declaration=False)
    xml_output = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

    if not _USE_MOCK:
        sb = _supabase()
        sb.table("xbrl_packages").update({
            "xbrl_xml": xml_output,
            "status": "validated",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", package_id).execute()

    return xml_output


def get_default_tag_mappings(taxonomy_version: str = "MCA_2023") -> list[dict]:
    return [
        {
            "schedule_line": sl,
            "xbrl_tag": tag,
            "xbrl_label": label,
            "is_mandatory": mandatory,
            "data_type": "monetary",
        }
        for sl, tag, label, mandatory in DEFAULT_MAPPINGS
    ]

"""
Firm master Chart-of-Accounts seeding (Batch 3.1 hardening).

Per the Migration-057 architecture (One Firm → One Master COA; clients share the
firm COA, client_id = NULL), this seeds the standard Schedule III CA-practice
chart for a firm. It is invoked during firm onboarding so that posting
(journal_for_sales_invoice / receipt / credit-note / purchase / payroll / assets)
can always resolve its accounts via phase2_journal_service._find_account.

Account NAMES are chosen to match the ILIKE patterns used by the posting engine
(e.g. '%Trade Receivable%', '%Sales%', '%GST Output%', '%Bank%'). Idempotent:
if the firm already has any firm-wide account, seeding is skipped.
"""
import os
import logging
from typing import Optional

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.coa_seed")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


# (account_code, account_name, account_type, account_subtype)
# Names align with phase2_journal_service._find_account patterns.
STANDARD_COA: list[tuple[str, str, str, str]] = [
    # ── Assets ──
    ("1001", "Cash in Hand",                 "Asset", "Cash"),
    ("1101", "Bank Account",                 "Asset", "Bank"),          # %Bank%
    ("1201", "Trade Receivables",            "Asset", "Receivable"),    # %Trade Receivable%
    ("1301", "GST Input Tax Credit",         "Asset", "Tax"),           # %GST Input%
    ("1401", "TDS Receivable",               "Asset", "Tax"),
    ("1402", "Advance Tax Paid",             "Asset", "Tax"),
    ("1501", "Plant & Machinery",            "Asset", "Fixed Asset"),   # %Plant & Machinery%
    ("1502", "Furniture & Fixtures",         "Asset", "Fixed Asset"),   # %Furniture & Fixtures%
    ("1503", "Computers & Software",         "Asset", "Fixed Asset"),   # %Computers & Software%
    ("1504", "Vehicles",                     "Asset", "Fixed Asset"),   # %Vehicles%
    ("1505", "Land & Building",              "Asset", "Fixed Asset"),   # %Land & Building%
    ("1506", "Intangible Assets",            "Asset", "Fixed Asset"),   # %Intangible Assets%
    ("1590", "Accumulated Depreciation",     "Asset", "Fixed Asset"),   # %Accumulated Depreciation%
    # ── Liabilities ──
    ("2001", "Trade Payables",               "Liability", "Current Liability"),  # %Trade Payable%
    ("2002", "GST Output Tax Payable",       "Liability", "Current Liability"),  # %GST Output%
    ("2003", "TDS Payable",                  "Liability", "Current Liability"),  # %TDS Payable%
    ("2004", "TDS Payable - Salary",         "Liability", "Current Liability"),  # %TDS Payable - Salary%
    ("2005", "PF Payable",                   "Liability", "Current Liability"),  # %PF Payable%
    ("2006", "ESI Payable",                  "Liability", "Current Liability"),  # %ESI Payable%
    ("2007", "PT Payable",                   "Liability", "Current Liability"),  # %PT Payable%
    ("2008", "Net Salary Payable",           "Liability", "Current Liability"),  # %Net Salary Payable%
    # ── Equity ──
    ("3001", "Capital Account",              "Equity", "Owner Equity"),
    ("3002", "Retained Earnings",            "Equity", "Owner Equity"),
    # ── Income ──
    ("4001", "Sales Revenue",                "Income", "Revenue"),      # %Sales%
    ("4002", "Professional Fees",            "Income", "Revenue"),
    ("4901", "Profit on Asset Disposal",     "Income", "Other Income"), # %Profit on Asset Disposal%
    # ── Expenses ──
    ("5001", "Purchases",                    "Expense", "Direct Expense"),     # %Purchase%
    ("5002", "Salaries Expense",             "Expense", "Operating Expense"),  # %Salaries Expense%
    ("5003", "Depreciation Expense",         "Expense", "Non-cash Expense"),   # %Depreciation Expense%
    ("5004", "Office Rent",                  "Expense", "Operating Expense"),
    ("5005", "Bank Charges",                 "Expense", "Operating Expense"),
    ("5006", "General Expenses",             "Expense", "Operating Expense"),  # %Expense% fallback
    ("5901", "Loss on Asset Disposal",       "Expense", "Other Expense"),      # %Loss on Asset Disposal%
]


def firm_has_coa(firm_id: str) -> bool:
    if _USE_MOCK:
        return True  # mock posting is a no-op; treat as present
    res = (
        _db().table("chart_of_accounts").select("id", count="exact")
        .eq("firm_id", firm_id).is_("client_id", None).limit(1).execute()
    )
    return bool(res.count and res.count > 0)


def seed_firm_coa(firm_id: str) -> dict:
    """Idempotently seed the firm-wide master CoA. Skips if the firm already has
    firm-wide accounts. Returns {seeded, skipped}."""
    if not firm_id:
        return {"seeded": 0, "skipped": True, "reason": "no firm_id"}
    if _USE_MOCK:
        return {"seeded": 0, "skipped": True, "mock": True}
    if firm_has_coa(firm_id):
        return {"seeded": 0, "skipped": True, "reason": "already seeded"}

    rows = [{
        "firm_id": firm_id, "client_id": None,
        "account_code": code, "account_name": name,
        "account_type": atype, "account_subtype": asub, "is_active": True,
    } for (code, name, atype, asub) in STANDARD_COA]
    # ON CONFLICT-safe: re-running is guarded by firm_has_coa above; insert is a
    # single batch for the firm.
    _db().table("chart_of_accounts").insert(rows).execute()
    _logger.info("Seeded %d firm-wide CoA accounts for firm %s", len(rows), firm_id)
    return {"seeded": len(rows), "skipped": False}

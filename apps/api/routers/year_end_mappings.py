"""
Year End Account Group Mappings router — Phase 6.
Maps Chart of Accounts → Schedule III line codes for financial statement generation.
Reference: Companies Act 2013, Schedule III.

Default mappings are auto-initialized per account_type when none exist for a firm.
All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event
from services.year_end_financial_service import BS_EQUITY_LIABILITY_LINES, BS_ASSET_LINES
from domain.reporting.schedule_iii import bs_bucket, pl_bucket

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-mappings"])

_BS_LINES = set(BS_EQUITY_LIABILITY_LINES) | set(BS_ASSET_LINES)


def _statement_type_for(schedule_line: str) -> str:
    """Balance Sheet vs P&L, per the SAME classification
    services.year_end_financial_service uses to build the statements
    themselves — single source of truth for the Schedule III line taxonomy."""
    return "balance_sheet" if schedule_line in _BS_LINES else "profit_loss"


def _account_name(db, account_id: str) -> Optional[str]:
    """account_group_mappings.account_name is NOT NULL but the mapping request
    body only ever carries account_id -- look the display name up from the
    chart of accounts rather than leaving it unpopulated."""
    row = (
        db.table("accounts").select("account_name")
        .eq("id", account_id).maybe_single().execute().data
    )
    return (row or {}).get("account_name")

# ── Default mapping rules ─────────────────────────────────────────────────────
# account_type → schedule_line
# Companies Act 2013, Schedule III
#
# task #240 fix: this used to be keyed on invented lowercase categories
# ("bank", "receivable", "fixed_asset", "tax_asset", ...) that never matched
# chart_of_accounts.account_type's real CHECK-constrained enum (migration
# 003: 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense' -- see the
# `accounts` view, migration 016, which is a plain passthrough of
# chart_of_accounts). Only "equity"/"expense" happened to coincide after
# lowercasing; every Asset/Liability/Revenue account (i.e. most of a real
# Chart of Accounts) silently fell through get_default_mappings()'s
# `.get(acct_type, "other_current_assets")` fallback -- misclassifying
# receivables, payables, cash, fixed assets and ALL revenue onto a single
# generic Balance Sheet line, corrupting the auto-initialized Schedule III
# mapping that services.year_end_financial_service.generate_financial_statements
# relies on as its single source of truth for account_group_mappings.
#
# Fix: classify by the REAL (account_type, account_subtype) pair using the
# SAME bucket rules as the reporting engine's Schedule III grouping
# (domain.reporting.schedule_iii.bs_bucket/pl_bucket -- already the single
# source of truth for this taxonomy elsewhere in the codebase). This map is
# now only the coarse per-account_type fallback used when a subtype-level
# bucket can't be determined (e.g. no account_subtype set).
_DEFAULT_ACCOUNT_TYPE_MAP = {
    "asset":     "other_current_assets",
    "liability": "other_current_liabilities",
    "equity":    "reserves_and_surplus",
    "revenue":   "revenue_from_operations",
    "expense":   "other_expenses",
}

# Schedule III statutory caption (as returned by domain.reporting.schedule_iii's
# bs_bucket/pl_bucket) → year-end schedule_line code (the snake_case taxonomy
# services.year_end_financial_service.BS_EQUITY_LIABILITY_LINES/BS_ASSET_LINES/
# PL_INCOME_LINES/PL_EXPENSE_LINES actually use).
_CAPTION_TO_SCHEDULE_LINE = {
    "Share Capital":               "share_capital",
    "Reserves & Surplus":          "reserves_and_surplus",
    "Deferred Tax Liability":      "deferred_tax_liabilities",
    "Trade Payables":              "trade_payables",
    "Short Term Borrowings":       "short_term_borrowings",
    "Long Term Borrowings":        "long_term_borrowings",
    "Other Current Liabilities":   "other_current_liabilities",
    "Intangible Fixed Assets":     "intangible_assets",
    "Tangible Fixed Assets":       "tangible_assets",
    "Long Term Investments":       "long_term_investments",
    "Inventories":                 "inventories",
    "Trade Receivables":           "trade_receivables",
    "Cash & Cash Equivalents":     "cash_and_bank",
    "Short Term Loans & Advances": "short_term_loans_and_advances",
    "Other Current Assets":        "other_current_assets",
    "Revenue from Operations":     "revenue_from_operations",
    "Other Income":                "other_income",
    "Cost of Materials":           "cost_of_materials_consumed",
    "Employee Benefit Expense":    "employee_benefit_expense",
    "Finance Costs":               "finance_costs",
    "Depreciation & Amortisation": "depreciation_and_amortisation",
    "Tax Expense":                 "other_expenses",
    "Other Expenses":              "other_expenses",
}


def _schedule_line_for_account(account_type: str, account_subtype: Optional[str]) -> str:
    """Classify an account into a year-end schedule_line using the SAME
    Schedule III bucket rules as the reporting engine (single source of
    truth for the statutory caption taxonomy), keyed on the REAL
    chart_of_accounts.account_type enum, not an invented one."""
    typ = (account_type or "").strip()
    caption = bs_bucket(typ, account_subtype) or pl_bucket(typ, account_subtype)
    if caption:
        return _CAPTION_TO_SCHEDULE_LINE.get(caption, "other_current_assets")
    return _DEFAULT_ACCOUNT_TYPE_MAP.get(typ.lower(), "other_current_assets")

# Normal balance per schedule line (debit or credit)
_LINE_NORMAL_BALANCE = {
    # Assets / Expenses → debit normal
    "tangible_assets":               "debit",
    "intangible_assets":             "debit",
    "capital_wip":                   "debit",
    "long_term_investments":         "debit",
    "deferred_tax_assets":           "debit",
    "long_term_loans_and_advances":  "debit",
    "other_non_current_assets":      "debit",
    "current_investments":           "debit",
    "inventories":                   "debit",
    "trade_receivables":             "debit",
    "cash_and_bank":                 "debit",
    "short_term_loans_and_advances": "debit",
    "other_current_assets":          "debit",
    "cost_of_materials_consumed":    "debit",
    "purchases_of_stock_in_trade":   "debit",
    "changes_in_inventories":        "debit",
    "employee_benefit_expense":      "debit",
    "finance_costs":                 "debit",
    "depreciation_and_amortisation": "debit",
    "other_expenses":                "debit",
    # Liabilities / Income / Equity → credit normal
    "share_capital":                 "credit",
    "reserves_and_surplus":          "credit",
    "long_term_borrowings":          "credit",
    "deferred_tax_liabilities":      "credit",
    "other_long_term_liabilities":   "credit",
    "long_term_provisions":          "credit",
    "short_term_borrowings":         "credit",
    "trade_payables":                "credit",
    "other_current_liabilities":     "credit",
    "short_term_provisions":         "credit",
    "revenue_from_operations":       "credit",
    "other_income":                  "credit",
}

# Mock store: firm_id → list of mapping records
_MOCK_MAPPINGS: dict[str, list[dict]] = {}


# ── Request models ────────────────────────────────────────────────────────────

class MappingIn(BaseModel):
    account_id:   str
    schedule_line: str
    account_type: Optional[str] = None


class BulkMappingIn(BaseModel):
    mappings: List[MappingIn]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/mappings")
def get_mappings(
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """Get all account group mappings for the caller's own firm.

    F1/F4 fix: this previously accepted a client-supplied ?firm_id= query
    param and used it verbatim -- any authenticated user could read another
    firm's Schedule III account mappings by supplying its firm_id. There is
    no legitimate reason for a normal (non-platform-admin) user to view
    another firm's mappings, so the override is removed rather than gated.
    """
    firm_id = current_user["firm_id"]

    if _USE_MOCK:
        existing = _MOCK_MAPPINGS.get(firm_id, [])
        return api_response(True, existing)

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("account_group_mappings")
        .select("*")
        .eq("firm_id", firm_id)
        .order("account_id")
        .execute()
        .data
    )
    return api_response(True, rows)


@router.post("/mappings")
def create_or_update_mapping(
    data: MappingIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Create or update a single account → schedule_line mapping (upsert)."""
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    normal_balance = _LINE_NORMAL_BALANCE.get(data.schedule_line, "debit")
    statement_type = _statement_type_for(data.schedule_line)

    record = {
        "firm_id":        firm_id,
        "account_id":     data.account_id,
        "schedule_line":  data.schedule_line,
        "account_type":   data.account_type,
        "normal_balance": normal_balance,
        "statement_type": statement_type,
        "updated_at":     now,
    }

    if _USE_MOCK:
        existing = _MOCK_MAPPINGS.setdefault(firm_id, [])
        old = next((m for m in existing if m["account_id"] == data.account_id), None)
        if old:
            old.update(record)
            old["updated_at"] = now
            return api_response(True, old)
        new_record = {"id": str(uuid.uuid4()), "created_at": now,
                      "account_name": data.account_id, **record}
        existing.append(new_record)
        return api_response(True, new_record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    record["account_name"] = _account_name(db, data.account_id)

    # Check if mapping already exists for this firm+account_id
    existing = (
        db.table("account_group_mappings")
        .select("id")
        .eq("firm_id", firm_id)
        .eq("account_id", data.account_id)
        .execute()
        .data
    )
    if existing:
        # Update
        updated = (
            db.table("account_group_mappings")
            .update({k: v for k, v in record.items() if k not in ("firm_id",)})
            .eq("firm_id", firm_id)
            .eq("account_id", data.account_id)
            .execute()
            .data[0]
        )
        return api_response(True, updated)

    # Insert
    new_record = {"id": str(uuid.uuid4()), "created_at": now, **record}
    inserted = db.table("account_group_mappings").insert(new_record).execute().data[0]
    log_event(
        firm_id, "account_group_mapping", inserted["id"], "create",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data=inserted,
    )
    return api_response(True, inserted)


@router.put("/mappings/bulk")
def bulk_update_mappings(
    data: BulkMappingIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Bulk create/update an array of account → schedule_line mappings."""
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    if not data.mappings:
        raise HTTPException(status_code=422, detail="mappings array cannot be empty")

    records = []
    for m in data.mappings:
        records.append({
            "id":             str(uuid.uuid4()),
            "firm_id":        firm_id,
            "account_id":     m.account_id,
            "schedule_line":  m.schedule_line,
            "account_type":   m.account_type,
            "normal_balance": _LINE_NORMAL_BALANCE.get(m.schedule_line, "debit"),
            "statement_type": _statement_type_for(m.schedule_line),
            "created_at":     now,
            "updated_at":     now,
        })

    if _USE_MOCK:
        existing = _MOCK_MAPPINGS.setdefault(firm_id, [])
        existing_map = {m["account_id"]: m for m in existing}
        for r in records:
            r.setdefault("account_name", r["account_id"])
            if r["account_id"] in existing_map:
                existing_map[r["account_id"]].update(r)
            else:
                existing.append(r)
                existing_map[r["account_id"]] = r
        return api_response(True, {"updated_count": len(records)})

    from core.supabase_client import get_supabase
    db = get_supabase()
    for record in records:
        record["account_name"] = _account_name(db, record["account_id"])

    # Upsert all mappings
    for record in records:
        existing = (
            db.table("account_group_mappings")
            .select("id")
            .eq("firm_id", firm_id)
            .eq("account_id", record["account_id"])
            .execute()
            .data
        )
        if existing:
            db.table("account_group_mappings").update({
                "schedule_line":  record["schedule_line"],
                "account_type":   record["account_type"],
                "normal_balance": record["normal_balance"],
                "statement_type": record["statement_type"],
                "account_name":   record["account_name"],
                "updated_at":     now,
            }).eq("firm_id", firm_id).eq("account_id", record["account_id"]).execute()
        else:
            db.table("account_group_mappings").insert(record).execute()

    log_event(
        firm_id, "account_group_mapping", firm_id, "bulk_update",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"count": len(records)},
    )
    return api_response(True, {"updated_count": len(records)})


@router.get("/mappings/defaults")
def get_default_mappings(
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """
    Return default mapping suggestions based on account_type.
    If no mappings exist for the firm, auto-initializes from defaults.
    Companies Act 2013, Schedule III mapping recommendations.
    """
    firm_id = current_user["firm_id"]

    defaults = []
    for account_type, schedule_line in _DEFAULT_ACCOUNT_TYPE_MAP.items():
        defaults.append({
            "account_type":   account_type,
            "schedule_line":  schedule_line,
            "normal_balance": _LINE_NORMAL_BALANCE.get(schedule_line, "debit"),
            "description":    f"Default: {account_type} accounts → {schedule_line}",
        })

    if _USE_MOCK:
        existing = _MOCK_MAPPINGS.get(firm_id, [])
        if not existing:
            # Auto-initialize hint (no accounts to map without real DB)
            return api_response(True, {
                "defaults":       defaults,
                "firm_has_mappings": False,
                "note": "No mappings found for this firm. Use POST /api/year-end/mappings to create mappings.",
            })
        return api_response(True, {
            "defaults":          defaults,
            "firm_has_mappings": True,
            "existing_count":    len(existing),
        })

    from core.supabase_client import get_supabase
    db = get_supabase()

    existing_count_res = (
        db.table("account_group_mappings")
        .select("id", count="exact")
        .eq("firm_id", firm_id)
        .execute()
    )
    existing_count = existing_count_res.count or 0

    if existing_count == 0:
        # Auto-initialize mappings from the firm's chart of accounts
        accounts_res = (
            db.table("accounts")
            .select("id, account_type, account_subtype, account_name")
            .eq("firm_id", firm_id)
            .execute()
        )
        accounts = accounts_res.data or []
        now = datetime.now(timezone.utc).isoformat()

        auto_records = []
        for acct in accounts:
            acct_type    = (acct.get("account_type") or "").lower()
            schedule_line = _schedule_line_for_account(acct.get("account_type"), acct.get("account_subtype"))
            auto_records.append({
                "id":             str(uuid.uuid4()),
                "firm_id":        firm_id,
                "account_id":     acct["id"],
                "account_name":   acct.get("account_name"),
                "schedule_line":  schedule_line,
                "account_type":   acct_type,
                "normal_balance": _LINE_NORMAL_BALANCE.get(schedule_line, "debit"),
                "statement_type": _statement_type_for(schedule_line),
                "created_at":     now,
                "updated_at":     now,
            })

        if auto_records:
            db.table("account_group_mappings").insert(auto_records).execute()
            existing_count = len(auto_records)
            log_event(
                firm_id, "account_group_mapping", firm_id, "auto_initialize",
                actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"),
                new_data={"count": len(auto_records)},
            )

    return api_response(True, {
        "defaults":          defaults,
        "firm_has_mappings": existing_count > 0,
        "existing_count":    existing_count,
    })

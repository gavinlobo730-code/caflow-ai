"""
Year End Financial Statements router — Phase 6.
Generates live Schedule III financial statements from the GL and manages
versioned snapshots for audit trail and sign-off.

Reference: Companies Act 2013, Schedule III.
All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-statements"])

_VALID_SCHEDULE_TYPES = {
    "cash_bank", "receivables", "payables",
    "fixed_assets", "gst", "tds", "loans",
}

# ── Mock version store ────────────────────────────────────────────────────────
# engagement_id → list of version snapshots
_MOCK_VERSIONS: dict[str, list[dict]] = {}


def _get_engagement(engagement_id: str, firm_id: str) -> dict:
    """Fetch engagement from DB and enforce firm isolation."""
    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (
        db.table("year_end_engagements")
        .select("*")
        .eq("id", engagement_id)
        .eq("firm_id", firm_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row


def _mock_engagement_meta(engagement_id: str) -> dict:
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        eng = _MOCK_ENGAGEMENTS.get(engagement_id)
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        return eng
    except ImportError:
        raise HTTPException(status_code=503, detail="Engagement service unavailable")


# ── Request models ────────────────────────────────────────────────────────────

class SnapshotCreateIn(BaseModel):
    version_label: Optional[str] = None
    notes: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{engagement_id}/financial-statements")
def get_financial_statements(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """
    Generate live Schedule III financial statements from the GL.
    Companies Act 2013, Schedule III, Parts I and II.
    All values in integer paise. Never float.
    """
    from services.year_end_financial_service import generate_financial_statements

    if _USE_MOCK:
        eng = _mock_engagement_meta(engagement_id)
        supabase = None
    else:
        eng = _get_engagement(engagement_id, current_user["firm_id"])
        from core.supabase_client import get_supabase
        supabase = get_supabase()

    try:
        statements = generate_financial_statements(
            supabase,
            client_id=eng["client_id"],
            firm_id=eng["firm_id"],
            fy_start=eng["fy_start"],
            fy_end=eng["fy_end"],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return api_response(True, statements)


@router.post("/{engagement_id}/financial-statements/snapshot")
def create_snapshot(
    engagement_id: str,
    data: SnapshotCreateIn = SnapshotCreateIn(),
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """
    Create a versioned snapshot of current financial statements.
    Inserts into financial_statement_versions for audit trail.
    """
    from services.year_end_financial_service import generate_financial_statements

    if _USE_MOCK:
        eng = _mock_engagement_meta(engagement_id)
        supabase = None
    else:
        eng = _get_engagement(engagement_id, current_user["firm_id"])
        from core.supabase_client import get_supabase
        supabase = get_supabase()

    try:
        statements = generate_financial_statements(
            supabase,
            client_id=eng["client_id"],
            firm_id=eng["firm_id"],
            fy_start=eng["fy_start"],
            fy_end=eng["fy_end"],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    now = datetime.now(timezone.utc).isoformat()
    version_id = str(uuid.uuid4())

    # Auto-increment version number
    if _USE_MOCK:
        existing_versions = _MOCK_VERSIONS.get(engagement_id, [])
        version_number = len(existing_versions) + 1
    else:
        count_res = (
            supabase
            .table("financial_statement_versions")
            .select("id", count="exact")
            .eq("engagement_id", engagement_id)
            .execute()
        )
        version_number = (count_res.count or 0) + 1

    snapshot = {
        "id":                version_id,
        "engagement_id":     engagement_id,
        "firm_id":           eng["firm_id"],
        "client_id":         eng["client_id"],
        "financial_year":    eng["financial_year"],
        "version_number":    version_number,
        "version_label":     data.version_label or f"v{version_number}",
        "notes":             data.notes,
        "statements_data":   statements,
        "trial_balance_hash":statements.get("trial_balance_hash"),
        "created_by":        current_user.get("auth_user_id"),
        "created_at":        now,
    }

    if _USE_MOCK:
        _MOCK_VERSIONS.setdefault(engagement_id, []).append(snapshot)
        return api_response(True, snapshot)

    result = supabase.table("financial_statement_versions").insert(snapshot).execute()
    created = result.data[0]

    log_event(
        eng["firm_id"], "financial_statement_version", version_id, "create",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"version_number": version_number, "engagement_id": engagement_id},
    )
    return api_response(True, created)


@router.get("/{engagement_id}/financial-statements/versions")
def list_versions(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        return api_response(True, _MOCK_VERSIONS.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("financial_statement_versions")
        .select("id, engagement_id, version_number, version_label, notes, trial_balance_hash, created_by, created_at")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .order("version_number", desc=True)
        .execute()
        .data
    )
    return api_response(True, rows)


@router.get("/{engagement_id}/financial-statements/versions/{version_id}")
def get_version(
    engagement_id: str,
    version_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        versions = _MOCK_VERSIONS.get(engagement_id, [])
        ver = next((v for v in versions if v["id"] == version_id), None)
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")
        return api_response(True, ver)

    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (
        db.table("financial_statement_versions")
        .select("*")
        .eq("id", version_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    return api_response(True, row)


@router.get("/{engagement_id}/schedules/{schedule_type}")
def get_schedule(
    engagement_id: str,
    schedule_type: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """
    Get sub-schedule detail.
    schedule_type: cash_bank | receivables | payables | fixed_assets | gst | tds | loans
    """
    if schedule_type not in _VALID_SCHEDULE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid schedule_type '{schedule_type}'. "
                   f"Must be one of: {sorted(_VALID_SCHEDULE_TYPES)}",
        )

    if _USE_MOCK:
        eng = _mock_engagement_meta(engagement_id)
    else:
        eng = _get_engagement(engagement_id, current_user["firm_id"])

    # Mock schedule data — all values in integer paise
    mock_schedules: dict = {
        "cash_bank": {
            "schedule_type": "cash_bank",
            "line_items": [
                {"description": "Cash in Hand",         "amount_paise": 10_000_00},
                {"description": "Current Account - SBI","amount_paise": 40_000_00},
            ],
            "total_paise": 50_000_00,
        },
        "receivables": {
            "schedule_type": "receivables",
            "line_items": [
                {"description": "Outstanding > 6 months", "amount_paise": 15_000_00},
                {"description": "Outstanding < 6 months", "amount_paise": 45_000_00},
            ],
            "total_paise": 60_000_00,
        },
        "payables": {
            "schedule_type": "payables",
            "line_items": [
                {"description": "MSME Creditors",      "amount_paise": 10_000_00},
                {"description": "Other Creditors",     "amount_paise": 15_000_00},
            ],
            "total_paise": 25_000_00,
        },
        "fixed_assets": {
            "schedule_type": "fixed_assets",
            "line_items": [
                {
                    "description":           "Plant & Machinery",
                    "gross_block_paise":      80_000_00,
                    "accumulated_dep_paise":  0,
                    "net_block_paise":        80_000_00,
                },
            ],
            "total_net_block_paise": 80_000_00,
        },
        "gst": {
            "schedule_type": "gst",
            "line_items": [
                {"description": "IGST Payable",  "amount_paise": 2_000_00},
                {"description": "CGST Payable",  "amount_paise": 1_000_00},
                {"description": "SGST Payable",  "amount_paise": 1_000_00},
                {"description": "GST Input ITC", "amount_paise": 500_00},
            ],
            "net_gst_payable_paise": 3_500_00,
        },
        "tds": {
            "schedule_type": "tds",
            "line_items": [
                {"description": "TDS Payable - 194C", "amount_paise": 500_00},
                {"description": "TDS Receivable",     "amount_paise": 300_00},
            ],
            "net_tds_payable_paise": 200_00,
        },
        "loans": {
            "schedule_type": "loans",
            "line_items": [
                {"description": "Term Loan - HDFC Bank", "amount_paise": 30_000_00, "category": "secured"},
            ],
            "total_paise": 30_000_00,
        },
    }

    if _USE_MOCK:
        return api_response(True, {
            "engagement_id":  engagement_id,
            "financial_year": eng.get("financial_year", ""),
            **mock_schedules.get(schedule_type, {"schedule_type": schedule_type, "line_items": []}),
        })

    from core.supabase_client import get_supabase
    db = get_supabase()

    # Query schedule-specific data from DB based on schedule_type
    # Each schedule maps to a specific set of GL accounts and sub-ledgers
    schedule_data = _fetch_schedule_from_db(db, eng, schedule_type)
    return api_response(True, schedule_data)


def _fetch_schedule_from_db(db, eng: dict, schedule_type: str) -> dict:
    """Fetch detailed sub-schedule data from the GL for a given schedule type."""
    engagement_id = eng["id"]
    firm_id       = eng["firm_id"]
    client_id     = eng["client_id"]
    fy_start      = eng["fy_start"]
    fy_end        = eng["fy_end"]

    # Map schedule_type to schedule_line codes from account_group_mappings
    _schedule_to_lines = {
        "cash_bank":   ["cash_and_bank"],
        "receivables": ["trade_receivables", "short_term_loans_and_advances"],
        "payables":    ["trade_payables", "other_current_liabilities"],
        "fixed_assets":["tangible_assets", "intangible_assets", "capital_wip"],
        "loans":       ["long_term_borrowings", "short_term_borrowings"],
        "gst":         ["other_current_liabilities", "short_term_loans_and_advances"],
        "tds":         ["short_term_loans_and_advances", "other_current_liabilities"],
    }

    target_lines = _schedule_to_lines.get(schedule_type, [])

    mappings_res = (
        db.table("account_group_mappings")
        .select("account_id, schedule_line")
        .eq("firm_id", firm_id)
        .in_("schedule_line", target_lines)
        .execute()
    )
    account_ids = [m["account_id"] for m in (mappings_res.data or [])]

    line_items = []
    total_paise = 0  # integer paise — never float

    if account_ids:
        # Fetch account balances from GL (posted entries in FY)
        accts_res = (
            db.table("accounts")
            .select("id, account_name, account_code, account_type")
            .in_("id", account_ids)
            .execute()
        )
        accts_map = {a["id"]: a for a in (accts_res.data or [])}

        for acct_id in account_ids:
            lines_res = (
                db.table("journal_lines")
                .select(
                    "debit_paise, credit_paise, "
                    "journal_entries!inner(client_id, is_posted, entry_date)"
                )
                .eq("account_id", acct_id)
                .eq("journal_entries.client_id", client_id)
                .eq("journal_entries.is_posted", True)
                .gte("journal_entries.entry_date", fy_start)
                .lte("journal_entries.entry_date", fy_end)
                .execute()
            )
            debit  = sum(int(l["debit_paise"])  for l in (lines_res.data or []))
            credit = sum(int(l["credit_paise"]) for l in (lines_res.data or []))
            # Net balance (integer paise)
            balance = debit - credit

            acct = accts_map.get(acct_id, {})
            line_items.append({
                "account_id":   acct_id,
                "account_code": acct.get("account_code", ""),
                "description":  acct.get("account_name", acct_id),
                "amount_paise": balance,   # integer paise
            })
            total_paise += balance         # integer paise

    return {
        "engagement_id":  engagement_id,
        "financial_year": eng["financial_year"],
        "schedule_type":  schedule_type,
        "line_items":     line_items,
        "total_paise":    total_paise,     # integer paise — never float
    }

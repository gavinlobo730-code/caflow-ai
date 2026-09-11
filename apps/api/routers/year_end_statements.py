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
from domain.reporting.year_end_lines import schedule_line_for_account
# M2 audit finding: every endpoint below resolved its engagement by firm_id
# alone (_get_engagement, live mode) or not at all (_mock_engagement_meta,
# mock mode — checked existence only, not even firm_id); list_versions and
# get_version didn't resolve the engagement at all, applying only an inline
# firm_id filter in live mode and no tenancy check whatsoever in mock mode.
# Delegates to year_end.py's own _assert_engagement_scope rather than a
# fourth copy of the same check (year_end_reviews.py, year_end_checklist.py
# already delegate the same way) — also closes the same
# .single()-raises-on-zero-rows bug _get_engagement had, already fixed
# elsewhere in this sweep.
from routers.year_end import _assert_engagement_scope

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-statements"])

_VALID_SCHEDULE_TYPES = {
    "cash_bank", "receivables", "payables",
    "fixed_assets", "gst", "tds", "loans",
}

# ── Mock version store ────────────────────────────────────────────────────────
# engagement_id → list of version snapshots
_MOCK_VERSIONS: dict[str, list[dict]] = {}


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

    # M2 audit finding: engagement resolved by firm_id alone (live) or not
    # checked at all (mock) — never checked the caller's assignment to its
    # client.
    eng = _assert_engagement_scope(current_user, engagement_id)
    if _USE_MOCK:
        supabase = None
    else:
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

    # M2 audit finding: engagement resolved by firm_id alone (live) or not
    # checked at all (mock) — never checked the caller's assignment to its
    # client.
    eng = _assert_engagement_scope(current_user, engagement_id)
    if _USE_MOCK:
        supabase = None
    else:
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
        "statement_data":    statements,
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
    # M2 audit finding: never resolved the engagement at all — live mode
    # applied only an inline firm_id filter on the versions table, mock
    # mode had no tenancy check whatsoever.
    _assert_engagement_scope(current_user, engagement_id)

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
    # M2 audit finding: never resolved the engagement at all.
    _assert_engagement_scope(current_user, engagement_id)

    if _USE_MOCK:
        versions = _MOCK_VERSIONS.get(engagement_id, [])
        ver = next((v for v in versions if v["id"] == version_id), None)
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")
        return api_response(True, ver)

    from core.supabase_client import get_supabase
    db = get_supabase()
    try:
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
    except Exception:
        # Supabase's real .single() raises (PGRST116) rather than returning
        # None on zero rows — without this a missing version_id crashes to
        # 500 instead of the 404 below. Found while touching this endpoint
        # for the M2 fix above; same shape already fixed elsewhere in this
        # sweep.
        row = None
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

    # M2 audit finding: engagement resolved by firm_id alone (live) or not
    # checked at all (mock) — never checked the caller's assignment to its
    # client.
    eng = _assert_engagement_scope(current_user, engagement_id)

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
        # ONE SHAPE, MOCK AND LIVE (FA-09). The mock branch answered with a
        # per-schedule shape of its own — `net_gst_payable_paise` here,
        # `total_net_block_paise` there, `total_paise` elsewhere, and a
        # `category` key on one line type — while the live branch always
        # answers `line_items` + `total_paise` + `gaps`. A caller written
        # against either was wrong about the other, and the SCREEN could not be
        # written against both. The mock figures are kept; only the envelope is
        # made the live one, and each schedule's own total is summed from its
        # own lines rather than restated.
        mock = mock_schedules.get(schedule_type, {"line_items": []})
        lines = list(mock.get("line_items", []))
        return api_response(True, {
            "engagement_id":  engagement_id,
            "financial_year": eng.get("financial_year", ""),
            "schedule_type":  schedule_type,
            "line_items":     lines,
            "total_paise":    sum(int(l.get("amount_paise") or
                                      l.get("net_block_paise") or 0)
                                  for l in lines),
            "gaps":           [],
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

    # Which schedule_line codes each schedule tab is made of.
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

    # WHICH LEDGERS BELONG ON THIS SCHEDULE IS DERIVED FROM THE ACCOUNT, and a
    # row in account_group_mappings overrides it. This used to read that table
    # and nothing else, and the table holds ZERO rows in production — it is
    # written only by a GET on routers/year_end_mappings that no screen has
    # ever called — so all seven tabs were empty for every client, forever.
    # The CA's own `schedule_iii_mapping`, recorded on 50 accounts, was sitting
    # right there unread.
    #
    # THIS CLIENT'S ACCOUNTS AND THE FIRM'S OWN, and no other client's. The
    # mappings table is firm-scoped with no client column, so the old query
    # could only ever have been firm-wide; deriving from chart_of_accounts
    # makes the client filter both possible and necessary, or one client's
    # schedule would list another's ledger names at nil.
    accounts_res = (
        db.table("chart_of_accounts")
        .select("id, account_name, account_code, account_type, account_subtype, "
                "schedule_iii_mapping")
        .eq("firm_id", firm_id)
        .or_(f"client_id.eq.{client_id},client_id.is.null")
        .execute()
    )
    client_accounts = accounts_res.data or []

    overrides = {
        m["account_id"]: m["schedule_line"]
        for m in (
            db.table("account_group_mappings")
            .select("account_id, schedule_line")
            .eq("firm_id", firm_id)
            .execute()
            .data or []
        )
    }

    accts_map = {}
    account_ids = []
    for acct in client_accounts:
        line = overrides.get(acct["id"]) or schedule_line_for_account(
            acct.get("account_type"), acct.get("account_subtype"),
            acct.get("schedule_iii_mapping"))
        if line in target_lines:
            account_ids.append(acct["id"])
            accts_map[acct["id"]] = acct

    line_items = []
    total_paise = 0  # integer paise — never float

    if account_ids:
        # THE BALANCE AS AT YEAR END, NOT THE YEAR'S MOVEMENT (FA-09).
        #
        # This used to window journal_lines on
        # `entry_date BETWEEN fy_start AND fy_end` and report debit − credit
        # over that window. For a balance-sheet schedule — cash, receivables,
        # payables, fixed assets, loans, and every one this endpoint serves —
        # that is the year's MOVEMENT, not the balance: a client carrying
        # ₹5,00,000 of receivables into the year and billing ₹1,00,000 in it
        # was shown ₹1,00,000. The opening balance was simply absent.
        #
        # Every month up to and including the year end, so the figure is
        # opening plus movement by construction rather than by adding two
        # numbers that can disagree. `routers/year_end_notes.py:180-280` needs
        # the split (it discloses opening, additions, deductions and closing
        # separately) and computes it there; a SCHEDULE is one column, so it
        # takes the closing figure and nothing else.
        #
        # READ FROM account_period_balances, the pre-aggregated monthly table
        # (migrations 227/228) — which is also what CLAUDE.md's reporting rule
        # requires. The loop this replaces made ONE QUERY PER ACCOUNT against
        # journal_lines, each shipping every line of that account's year to
        # Python: N Singapore-to-Mumbai round trips proportional to transaction
        # volume, for a document a few rows long. This is one query whose rows
        # are bounded by accounts × months.
        balances_res = (
            db.table("account_period_balances")
            .select("account_id, debit_paise, credit_paise")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .in_("account_id", account_ids)
            .lte("period_month", fy_end)
            .execute()
        )
        by_account: dict = {}
        for row in (balances_res.data or []):
            by_account[row["account_id"]] = (
                by_account.get(row["account_id"], 0)
                + int(row["debit_paise"] or 0) - int(row["credit_paise"] or 0))

        for acct_id in account_ids:
            balance = by_account.get(acct_id, 0)
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
        # NO LEDGER CLASSIFIES HERE, AND AN EMPTY SCHEDULE MUST NOT READ AS A
        # NIL ONE. An empty `line_items` with no explanation is a claim — "this
        # client has no fixed assets" — and the endpoint cannot tell that apart
        # from a chart of accounts that has no such ledger yet. It says which.
        #
        # The sentence changed with the derivation above. It used to blame
        # account group mappings, which was true while they were the only
        # source and is not now: the classification comes from the account's
        # own type, subtype and Schedule III mapping, so an empty schedule
        # means no ledger in this client's chart of accounts classifies to it.
        "gaps": ([] if account_ids else [
            f"No ledger in this client's chart of accounts classifies to the "
            f"{schedule_type.replace('_', ' ')} schedule, so this is empty "
            f"because nothing belongs to it — not because the balances are "
            f"nil. Check the account's type and its Schedule III mapping."
        ]),
    }

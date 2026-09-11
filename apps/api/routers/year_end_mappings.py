"""
Year End Account Group Mappings router — Phase 6.
Reference: Companies Act 2013, Schedule III.

A ROW HERE IS AN OVERRIDE. An account's Schedule III line is DERIVED from the
account itself — its type, its subtype and the CA's own `schedule_iii_mapping`
— by domain/reporting/year_end_lines.schedule_line_for_account, on every read.
A row in `account_group_mappings` displaces that derived answer for one
account, and exists only where a human has explicitly POSTed one.

It did not work that way until 2026-09-11, and the consequence was severe: the
year-end statements read this table and NOTHING else, sending every account it
did not find to `other_current_assets`. The table holds zero rows in
production, so a whole balanced ledger landed on one line and both sides of the
Balance Sheet came to nil — with the `total_assets == total_equity_and_
liabilities` check passing on 0 == 0. See
tests/test_the_year_end_statements_use_the_chart_of_accounts.py.

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
from domain.reporting.year_end_lines import (
    CAPTION_TO_SCHEDULE_LINE,
    DEFAULT_ACCOUNT_TYPE_MAP,
    LINE_NORMAL_BALANCE,
    schedule_line_for_account,
    statement_type_for,
)

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-mappings"])

# THE TAXONOMY AND THE CLASSIFIER NOW LIVE IN domain/reporting/year_end_lines.
# They were defined here, in a ROUTER, while the two modules that most needed
# them — the financial-statement service and the schedules endpoint — read a
# cache of this function's answer instead and got zeros when it was empty.
# The private aliases below are kept because they are what this module's
# tests address; they are the same objects, not copies.
_statement_type_for       = statement_type_for
_schedule_line_for_account = schedule_line_for_account
_CAPTION_TO_SCHEDULE_LINE = CAPTION_TO_SCHEDULE_LINE
_DEFAULT_ACCOUNT_TYPE_MAP = DEFAULT_ACCOUNT_TYPE_MAP
_LINE_NORMAL_BALANCE      = LINE_NORMAL_BALANCE


def _account_name(db, account_id: str) -> Optional[str]:
    """account_group_mappings.account_name is NOT NULL but the mapping request
    body only ever carries account_id -- look the display name up from the
    chart of accounts rather than leaving it unpopulated."""
    row = (
        db.table("accounts").select("account_name")
        .eq("id", account_id).maybe_single().execute().data
    )
    return (row or {}).get("account_name")

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

    # THE AUTO-INITIALISATION IS GONE, AND ITS REMOVAL IS THE POINT.
    #
    # This GET used to write: finding no rows, it read the firm's whole chart
    # of accounts, classified every account, and INSERTED the answers. Two
    # things were wrong with that, and the second is why removing it matters
    # more now than it did before.
    #
    #   * A GET that writes. This endpoint is guarded `("year_end", "read")`,
    #     so a Reviewer with read-only rights could seed a firm's entire
    #     Schedule III classification by opening a screen.
    #
    #   * IT FROZE A DERIVED ANSWER. `schedule_line_for_account` is a pure
    #     function of the account — its type, subtype and the CA's own
    #     `schedule_iii_mapping` — and these rows are written once and never
    #     re-derived. So the moment they existed, a CA changing an account's
    #     mapping on /accounting/schedule-iii would see the year-end statements
    #     ignore the change forever, because the frozen row outranks it. That
    #     is ACC-10 coming back by a different door, and it would have been
    #     invisible: the new accounts added afterwards WOULD follow the CA's
    #     decision, so half the chart would obey it and half would not.
    #
    # The statements and schedules now classify from the chart of accounts on
    # every read (see domain/reporting/year_end_lines), so there is nothing for
    # a cache to be a cache OF. A row in this table is what a human explicitly
    # POSTed — a deliberate override of the derived line — and only that.
    return api_response(True, {
        "defaults":          defaults,
        "firm_has_mappings": existing_count > 0,
        "existing_count":    existing_count,
    })

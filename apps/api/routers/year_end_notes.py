"""
Year End Notes to Accounts router — Phase 6.
Manages Notes to Financial Statements.
Auto-generates standard notes from GL data; supports manual placeholder notes.
Notes can be locked individually (immutable after locking).

Reference: Companies Act 2013, Schedule III — Notes to Accounts.
All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-notes"])

# Note types — auto-generated (at least partly computed from real data) vs
# manual placeholder. task #240 fix: gst_tds moved out of _AUTO_NOTE_TYPES --
# there is no FY-level GST/TDS payable aggregation function anywhere in the
# codebase (gst_return_service's GL-movement helpers are period-scoped, one
# GSTR-3B return at a time, not a financial year), so unlike fixed_assets/
# share_capital/loans it genuinely cannot be computed here. It now gets the
# same honest CA-input placeholder as related_party/contingent_liabilities
# instead of a plausible-looking fabricated number.
_AUTO_NOTE_TYPES   = {"fixed_assets", "share_capital", "loans"}
_MANUAL_NOTE_TYPES = {"related_party", "contingent_liabilities", "gst_tds"}
_ALL_NOTE_TYPES    = _AUTO_NOTE_TYPES | _MANUAL_NOTE_TYPES

# ── Mock store ────────────────────────────────────────────────────────────────
# engagement_id → list of note dicts
_MOCK_NOTES: dict[str, list[dict]] = {}


def _mock_engagement(engagement_id: str) -> dict:
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        eng = _MOCK_ENGAGEMENTS.get(engagement_id)
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        return eng
    except ImportError:
        return {
            "id": engagement_id,
            "firm_id": "firm-001",
            "client_id": "client-001",
            "financial_year": "2024-25",
        }


def _get_engagement_db(db, engagement_id: str, firm_id: str) -> dict:
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


# ── Request models ────────────────────────────────────────────────────────────

class NoteUpdateIn(BaseModel):
    title:   Optional[str] = None
    content: Optional[str] = None
    note_data: Optional[dict] = None


# ── Real-data computation for auto note types ─────────────────────────────────
# task #240 fix: these figures used to be hardcoded literal constants (e.g.
# gross_block_paise=80_000_00) regardless of the actual client/FY — a
# "Generate Notes" click produced numbers with no connection to the client's
# books at all, which could have ended up in a filed Balance Sheet. Below,
# each figure is either computed from real data or explicitly left blank
# with requires_ca_review=True (the same honest-placeholder pattern already
# used for related_party/contingent_liabilities) — never a plausible-looking
# fabricated number.

def _compute_fixed_assets_note_data(db, firm_id: str, client_id: str, fy_end: Optional[str]) -> dict:
    """Real Fixed Assets figures for the FY, from the fixed assets register.
    Depreciation charge uses the SAME fixed-annual-charge-on-opening-WDV
    logic as routers.fixed_assets (task #232's rounding fix)."""
    if db is None:
        return {
            "gross_block_paise": 0, "accumulated_dep_paise": 0,
            "net_block_paise": 0, "depreciation_charge_paise": 0,
            "note_type": "fixed_assets", "is_auto_generated": True,
            "requires_ca_review": True,
            "review_note": "Fixed assets register unavailable — figures require manual entry.",
        }
    from routers.fixed_assets import _annual_depreciation_for_period
    rows = (
        db.table("fixed_assets").select("*")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("is_disposed", False)
        .execute().data or []
    )
    gross_block     = sum(int(a.get("purchase_cost_paise") or 0) for a in rows)
    accumulated_dep = sum(int(a.get("accumulated_depreciation_paise") or 0) for a in rows)
    period = (fy_end or "")[:7]  # "YYYY-MM" — March of the FY-end year
    dep_charge = 0
    if period:
        for a in rows:
            charge, _fy, _opening = _annual_depreciation_for_period(a, period)
            dep_charge += charge
    return {
        "gross_block_paise":        gross_block,
        "accumulated_dep_paise":    accumulated_dep,
        "net_block_paise":          gross_block - accumulated_dep,
        "depreciation_charge_paise": dep_charge,
        "note_type": "fixed_assets",
        "is_auto_generated": True,
    }


def _compute_gl_schedule_balances(
    db, firm_id: str, client_id: str, fy_start: Optional[str], fy_end: Optional[str],
) -> Optional[dict]:
    """Share Capital / Borrowings balances straight from the General Ledger,
    via the SAME account_group_mappings-driven engine the Balance Sheet
    itself uses (services.year_end_financial_service) — single source of
    truth, never a fabricated placeholder. Returns None if unavailable (e.g.
    the books don't balance yet), so callers fall back to an honest
    CA-review note rather than a wrong number."""
    if db is None or not fy_start or not fy_end:
        return None
    from services.year_end_financial_service import generate_financial_statements
    try:
        result = generate_financial_statements(db, client_id, firm_id, fy_start, fy_end)
    except Exception:
        return None
    return result.get("balance_sheet", {}).get("equity_and_liabilities", {})


# ── Note content generators ───────────────────────────────────────────────────

def _generate_note_content(note_type: str, eng: dict, computed: dict) -> dict:
    """
    Generate note content for auto note types.
    All monetary values in integer paise. Never float.
    """
    fy = eng.get("financial_year", "")
    gl = computed.get("gl_balances")

    _note_templates: dict[str, dict] = {
        "fixed_assets": {
            "title":   "Note 1 — Fixed Assets (Schedule III, Companies Act 2013)",
            "content": (
                f"Fixed assets are stated at cost less accumulated depreciation. "
                f"Depreciation is provided on Written Down Value method as per Companies Act 2013, "
                f"Schedule II useful lives. Financial year: {fy}."
            ),
            "note_data": computed["fixed_assets"],
        },
        "share_capital": {
            "title":   "Note 2 — Share Capital",
            "content": (
                f"Details of authorised, issued, subscribed and paid-up share capital "
                f"as at 31st March of FY {fy}. "
                f"[Reference: Companies Act 2013, §64]"
            ),
            "note_data": {
                "authorised_paise":  None,   # Memorandum/Articles fact — not a GL balance
                "issued_paise":      None,   # Memorandum/Articles fact — not a GL balance
                "subscribed_paise":  None,   # Memorandum/Articles fact — not a GL balance
                "paid_up_paise":     (gl or {}).get("share_capital", 0) if gl is not None else None,
                "note_type":         "share_capital",
                "is_auto_generated": True,
                "requires_ca_review": True,
                "review_note": (
                    "Paid-up capital is computed from the General Ledger (share_capital "
                    "schedule line). Authorised, issued and subscribed capital are "
                    "Memorandum/Articles of Association facts, not GL balances — CA must fill these in."
                    if gl is not None else
                    "General Ledger balance unavailable — all figures require manual entry."
                ),
            },
        },
        "loans": {
            "title":   "Note 3 — Long-term and Short-term Borrowings",
            "content": (
                f"Secured and unsecured loans as at 31st March of FY {fy}. "
                f"Secured loans are against hypothecation of assets."
            ),
            "note_data": {
                "long_term_total_paise":  (gl or {}).get("long_term_borrowings", 0) if gl is not None else None,
                "short_term_total_paise": (gl or {}).get("short_term_borrowings", 0) if gl is not None else None,
                "long_term_secured_paise":    None,
                "long_term_unsecured_paise":  None,
                "short_term_secured_paise":   None,
                "short_term_unsecured_paise": None,
                "note_type": "loans",
                "is_auto_generated": True,
                "requires_ca_review": True,
                "review_note": (
                    "Totals are computed from the General Ledger (long_term_borrowings / "
                    "short_term_borrowings schedule lines). The secured/unsecured split is "
                    "not tracked in the Chart of Accounts — CA must classify each loan."
                    if gl is not None else
                    "General Ledger balance unavailable — figures require manual entry."
                ),
            },
        },
        "gst_tds": {
            "title":   "Note 4 — Statutory Dues (GST & TDS)",
            "content": (
                f"GST and TDS dues as at 31st March of FY {fy}. "
                f"PLACEHOLDER — CA to fill in from GSTR-3B and TDS return records for the FY. "
                f"[CGST Act 2017 §49; IT Act 1961 §194C/194J]"
            ),
            "note_data": {
                "gst_payable_paise": None,
                "tds_payable_paise": None,
                "input_itc_paise":   None,
                "note_type": "gst_tds",
                "is_auto_generated": False,
                "requires_ca_review": True,
                "review_note": (
                    "No financial-year-level GST/TDS payable aggregation exists yet — "
                    "CA must fill this in from GSTR-3B and TDS return records for the FY."
                ),
            },
        },
        "related_party": {
            "title":   "Note 5 — Related Party Transactions",
            "content": (
                "PLACEHOLDER — CA to fill in related party transactions. "
                "[Companies Act 2013, §188; AS-18 / Ind AS 24]"
            ),
            "note_data": {
                "transactions": [],
                "note_type": "related_party",
                "is_auto_generated": False,
                "requires_ca_review": True,
            },
        },
        "contingent_liabilities": {
            "title":   "Note 6 — Contingent Liabilities and Capital Commitments",
            "content": (
                "PLACEHOLDER — CA to disclose contingent liabilities and capital commitments. "
                "[AS-29; Companies Act 2013, Schedule III]"
            ),
            "note_data": {
                "items": [],
                "note_type": "contingent_liabilities",
                "is_auto_generated": False,
                "requires_ca_review": True,
            },
        },
    }

    return _note_templates.get(note_type, {
        "title":     f"Note — {note_type.replace('_', ' ').title()}",
        "content":   f"Auto-generated note for {note_type}.",
        "note_data": {"note_type": note_type, "is_auto_generated": True},
    })


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{engagement_id}/notes")
def list_notes(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        return api_response(True, _MOCK_NOTES.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("year_end_notes")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .order("sequence_no")
        .execute()
        .data
    )
    return api_response(True, rows)


@router.post("/{engagement_id}/notes/generate")
def generate_notes(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """
    Auto-generate standard Notes to Accounts from GL data.
    Creates auto notes for: fixed_assets, share_capital, loans, gst_tds.
    Creates manual placeholders for: related_party, contingent_liabilities.
    """
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        eng = _mock_engagement(engagement_id)
        if eng.get("status") == "locked":
            raise HTTPException(status_code=403, detail="Engagement is locked")
        db = None
    else:
        from core.supabase_client import get_supabase
        db = get_supabase()
        eng = _get_engagement_db(db, engagement_id, current_user["firm_id"])
        if eng["status"] == "locked":
            raise HTTPException(status_code=403, detail="Engagement is locked")

    computed = {
        "fixed_assets": _compute_fixed_assets_note_data(
            db, current_user["firm_id"], eng.get("client_id", ""), eng.get("fy_end"),
        ),
        "gl_balances": _compute_gl_schedule_balances(
            db, current_user["firm_id"], eng.get("client_id", ""),
            eng.get("fy_start"), eng.get("fy_end"),
        ),
    }

    note_types_ordered = [
        "fixed_assets", "share_capital", "loans", "gst_tds",
        "related_party", "contingent_liabilities",
    ]

    generated_notes = []
    for idx, note_type in enumerate(note_types_ordered, start=1):
        content = _generate_note_content(note_type, eng, computed)
        note = {
            "id":            str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "firm_id":       current_user["firm_id"],
            "note_type":     note_type,
            # `note_number` deliberately omitted: it belongs to the never-applied
            # notes_to_accounts schema (migration 067). The table this actually
            # writes to, year_end_notes, orders by sequence_no and has no
            # note_number column — sending it makes PostgREST reject the insert.
            "sequence_no":   idx,
            "title":         content["title"],
            "content":       content["content"],
            "note_data":     content["note_data"],
            "is_locked":     False,
            "is_auto_generated": note_type in _AUTO_NOTE_TYPES,
            "created_by":    current_user.get("auth_user_id"),
            "created_at":    now,
            "updated_at":    now,
        }
        generated_notes.append(note)

    if _USE_MOCK:
        _MOCK_NOTES[engagement_id] = generated_notes
        return api_response(True, generated_notes)

    # Delete existing notes and regenerate
    db.table("year_end_notes").delete().eq("engagement_id", engagement_id).execute()
    result = db.table("year_end_notes").insert(generated_notes).execute()

    log_event(
        current_user["firm_id"], "year_end_notes", engagement_id, "generate",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"count": len(generated_notes)},
    )
    return api_response(True, result.data)


@router.get("/{engagement_id}/notes/{note_id}")
def get_note(
    engagement_id: str,
    note_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    return api_response(True, row)


@router.patch("/{engagement_id}/notes/{note_id}")
def update_note(
    engagement_id: str,
    note_id: str,
    data: NoteUpdateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        eng = _mock_engagement(engagement_id)
        if eng.get("status") == "locked":
            raise HTTPException(status_code=403, detail="Engagement is locked")
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note.get("is_locked"):
            raise HTTPException(status_code=403, detail="Note is locked and cannot be modified")
        updates = data.model_dump(exclude_none=True)
        note.update(updates)
        note["updated_at"] = now
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_engagement_db(db, engagement_id, current_user["firm_id"])
    if eng["status"] == "locked":
        raise HTTPException(status_code=403, detail="Engagement is locked")

    existing = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Note not found")
    if existing.get("is_locked"):
        raise HTTPException(status_code=403, detail="Note is locked and cannot be modified")

    updates = data.model_dump(exclude_none=True)
    updates["updated_at"] = now

    updated = (
        db.table("year_end_notes")
        .update(updates)
        .eq("id", note_id)
        .execute()
        .data[0]
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/notes/{note_id}/lock")
def lock_note(
    engagement_id: str,
    note_id: str,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """Lock a note — immutable after locking. Requires Manager or Partner."""
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        notes = _MOCK_NOTES.get(engagement_id, [])
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note.get("is_locked"):
            raise HTTPException(status_code=409, detail="Note is already locked")
        note["is_locked"]  = True
        note["locked_by"]  = current_user.get("auth_user_id")
        note["locked_at"]  = now
        note["updated_at"] = now
        return api_response(True, note)

    from core.supabase_client import get_supabase
    db = get_supabase()

    existing = (
        db.table("year_end_notes")
        .select("*")
        .eq("id", note_id)
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Note not found")
    if existing.get("is_locked"):
        raise HTTPException(status_code=409, detail="Note is already locked")

    updated = (
        db.table("year_end_notes")
        .update({
            "is_locked":  True,
            "locked_by":  current_user.get("auth_user_id"),
            "locked_at":  now,
            "updated_at": now,
        })
        .eq("id", note_id)
        .execute()
        .data[0]
    )
    log_event(
        current_user["firm_id"], "year_end_note", note_id, "lock",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"is_locked": True},
    )
    return api_response(True, updated)

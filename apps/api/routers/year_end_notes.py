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

# Note types — auto-generated vs manual placeholder
_AUTO_NOTE_TYPES   = {"fixed_assets", "share_capital", "loans", "gst_tds"}
_MANUAL_NOTE_TYPES = {"related_party", "contingent_liabilities"}
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


# ── Note content generators ───────────────────────────────────────────────────

def _generate_note_content(note_type: str, eng: dict) -> dict:
    """
    Generate note content for auto note types.
    All monetary values in integer paise. Never float.
    """
    fy = eng.get("financial_year", "")

    _note_templates: dict[str, dict] = {
        "fixed_assets": {
            "title":   "Note 1 — Fixed Assets (Schedule III, Companies Act 2013)",
            "content": (
                f"Fixed assets are stated at cost less accumulated depreciation. "
                f"Depreciation is provided on Written Down Value method as per Companies Act 2013, "
                f"Schedule II useful lives. Financial year: {fy}."
            ),
            "note_data": {
                "gross_block_paise":          80_000_00,   # integer paise
                "accumulated_dep_paise":       0,
                "net_block_paise":            80_000_00,   # integer paise
                "depreciation_charge_paise":   0,
                "note_type": "fixed_assets",
                "is_auto_generated": True,
            },
        },
        "share_capital": {
            "title":   "Note 2 — Share Capital",
            "content": (
                f"Details of authorised, issued, subscribed and paid-up share capital "
                f"as at 31st March of FY {fy}. "
                f"[Reference: Companies Act 2013, §64]"
            ),
            "note_data": {
                "authorised_paise":   100_000_00,  # integer paise
                "issued_paise":       100_000_00,  # integer paise
                "subscribed_paise":   100_000_00,  # integer paise
                "paid_up_paise":      100_000_00,  # integer paise
                "note_type":          "share_capital",
                "is_auto_generated":  True,
            },
        },
        "loans": {
            "title":   "Note 3 — Long-term and Short-term Borrowings",
            "content": (
                f"Secured and unsecured loans as at 31st March of FY {fy}. "
                f"Secured loans are against hypothecation of assets."
            ),
            "note_data": {
                "long_term_secured_paise":   30_000_00,  # integer paise
                "long_term_unsecured_paise":  0,
                "short_term_secured_paise":   0,
                "short_term_unsecured_paise": 0,
                "note_type": "loans",
                "is_auto_generated": True,
            },
        },
        "gst_tds": {
            "title":   "Note 4 — Statutory Dues (GST & TDS)",
            "content": (
                f"GST and TDS dues as at 31st March of FY {fy}. "
                f"[CGST Act 2017 §49; IT Act 1961 §194C/194J]"
            ),
            "note_data": {
                "gst_payable_paise":  3_500_00,   # integer paise
                "tds_payable_paise":    200_00,   # integer paise
                "input_itc_paise":      500_00,   # integer paise
                "note_type": "gst_tds",
                "is_auto_generated": True,
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
        db.table("notes_to_accounts")
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
    else:
        from core.supabase_client import get_supabase
        db = get_supabase()
        eng = _get_engagement_db(db, engagement_id, current_user["firm_id"])
        if eng["status"] == "locked":
            raise HTTPException(status_code=403, detail="Engagement is locked")

    note_types_ordered = [
        "fixed_assets", "share_capital", "loans", "gst_tds",
        "related_party", "contingent_liabilities",
    ]

    generated_notes = []
    for idx, note_type in enumerate(note_types_ordered, start=1):
        content = _generate_note_content(note_type, eng)
        note = {
            "id":            str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "firm_id":       current_user["firm_id"],
            "note_type":     note_type,
            "note_number":   idx,
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
    db.table("notes_to_accounts").delete().eq("engagement_id", engagement_id).execute()
    result = db.table("notes_to_accounts").insert(generated_notes).execute()

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
        db.table("notes_to_accounts")
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
        db.table("notes_to_accounts")
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
        db.table("notes_to_accounts")
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
        db.table("notes_to_accounts")
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
        db.table("notes_to_accounts")
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

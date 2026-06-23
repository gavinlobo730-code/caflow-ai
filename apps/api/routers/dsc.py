"""
DSC (Digital Signature Certificate) tracker router.

DSCs are required for GST filing (CGST Act), MCA / ROC filings (Companies Act
2013) and Income Tax e-filing; they expire every 1-2 years. This router lets a
firm track, renew and (soft-)delete its certificates. All rows are firm-scoped;
deletes are soft so DSC history is preserved.
"""
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.permissions import rbac
from models.common import api_response
from repositories.dsc_repository import dsc_repo
from services.audit_service import log_event

router = APIRouter(prefix="/api/dsc", tags=["dsc"])

# PAN format AAAAA9999A — 5 uppercase letters + 4 digits + 1 uppercase letter
# (Income Tax Act). Validated for DSC holders just as for clients.
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_DSC_TYPES = {"Class 2", "Class 3"}


# ─── Schemas ──────────────────────────────────────────────────────────────────

class DSCCreate(BaseModel):
    holder_name: str
    pan: Optional[str] = None
    dsc_type: str = "Class 3"
    purpose: str = "Income Tax"
    issued_date: Optional[str] = None
    expiry_date: str
    issued_by: Optional[str] = None
    token_no: Optional[str] = None
    notes: Optional[str] = None


class DSCUpdate(BaseModel):
    holder_name: Optional[str] = None
    pan: Optional[str] = None
    dsc_type: Optional[str] = None
    purpose: Optional[str] = None
    issued_date: Optional[str] = None
    expiry_date: Optional[str] = None
    issued_by: Optional[str] = None
    token_no: Optional[str] = None
    notes: Optional[str] = None


class DSCRenew(BaseModel):
    new_expiry_date: str
    new_issued_date: Optional[str] = None
    token_no: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} must be a valid ISO date (YYYY-MM-DD).")


def _normalize_pan(pan: Optional[str]) -> Optional[str]:
    """Uppercase and validate a PAN if provided; returns the cleaned PAN or None."""
    if pan is None:
        return None
    cleaned = pan.strip().upper()
    if not cleaned:
        return None
    if not _PAN_RE.match(cleaned):
        raise HTTPException(
            status_code=422,
            detail="Invalid PAN — expected PAN format AAAAA9999A (5 letters, 4 digits, 1 letter).",
        )
    return cleaned


def _audit(firm_id, entity_id, action, current_user, *, old_data=None, new_data=None):
    """Wrap audit logging so it can never break the operation (already non-fatal)."""
    try:
        log_event(
            firm_id,
            "dsc",
            entity_id,
            action,
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data=old_data,
            new_data=new_data,
        )
    except Exception:
        pass


def _get_owned_or_404(dsc_id: str, firm_id: str) -> dict:
    """Fetch a DSC record and enforce firm ownership (404 if missing/other firm)."""
    record = dsc_repo.find_by_id(dsc_id, firm_id=firm_id)
    if not record or record.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="DSC record not found")
    return record


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_dsc(current_user: dict = Depends(rbac("dsc", "read"))):
    firm_id = current_user["firm_id"]
    rows = dsc_repo.find_all(firm_id=firm_id)
    return api_response(True, {"dsc_records": rows, "total": len(rows)})


@router.post("")
def create_dsc(body: DSCCreate, current_user: dict = Depends(rbac("dsc", "write"))):
    firm_id = current_user["firm_id"]

    holder_name = body.holder_name.strip()
    if not holder_name:
        raise HTTPException(status_code=422, detail="holder_name is required.")

    if body.dsc_type not in _DSC_TYPES:
        raise HTTPException(status_code=422, detail="dsc_type must be 'Class 2' or 'Class 3'.")

    pan = _normalize_pan(body.pan)

    expiry = _parse_date(body.expiry_date, "expiry_date")
    issued = None
    if body.issued_date:
        issued = _parse_date(body.issued_date, "issued_date")
        if issued > expiry:
            raise HTTPException(status_code=422, detail="issued_date cannot be after expiry_date.")

    # Duplicate prevention: an active (non-deleted) DSC for the same firm with the
    # same PAN (when given) + dsc_type + expiry_date is almost certainly a re-entry.
    for existing in dsc_repo.find_all(firm_id=firm_id):
        if (
            existing.get("dsc_type") == body.dsc_type
            and existing.get("expiry_date") == body.expiry_date
            and (existing.get("pan") or None) == pan
        ):
            raise HTTPException(status_code=409, detail="A matching DSC record already exists.")

    data = {
        "firm_id": firm_id,
        "holder_name": holder_name,
        "pan": pan,
        "dsc_type": body.dsc_type,
        "purpose": body.purpose,
        "issued_date": body.issued_date,
        "expiry_date": body.expiry_date,
        "issued_by": body.issued_by,
        "token_no": body.token_no,
        "notes": (body.notes.strip() if body.notes else None) or None,
    }
    row = dsc_repo.create(data)

    _audit(firm_id, row["id"], "create", current_user, new_data=data)
    return api_response(True, {"dsc_record": row})


@router.patch("/{dsc_id}")
def update_dsc(dsc_id: str, body: DSCUpdate, current_user: dict = Depends(rbac("dsc", "write"))):
    firm_id = current_user["firm_id"]
    existing = _get_owned_or_404(dsc_id, firm_id)

    updates: dict = {}
    fields = body.model_dump(exclude_unset=True)

    if "holder_name" in fields:
        holder_name = (fields["holder_name"] or "").strip()
        if not holder_name:
            raise HTTPException(status_code=422, detail="holder_name cannot be empty.")
        updates["holder_name"] = holder_name

    if "dsc_type" in fields and fields["dsc_type"] is not None:
        if fields["dsc_type"] not in _DSC_TYPES:
            raise HTTPException(status_code=422, detail="dsc_type must be 'Class 2' or 'Class 3'.")
        updates["dsc_type"] = fields["dsc_type"]

    if "pan" in fields:
        updates["pan"] = _normalize_pan(fields["pan"])

    # Resolve the effective issued/expiry dates (incoming override existing) and
    # re-validate the ordering whenever either is supplied.
    new_expiry_str = fields["expiry_date"] if "expiry_date" in fields and fields["expiry_date"] else existing.get("expiry_date")
    new_issued_str = fields["issued_date"] if "issued_date" in fields and fields["issued_date"] else existing.get("issued_date")
    if "expiry_date" in fields and fields["expiry_date"]:
        updates["expiry_date"] = fields["expiry_date"]
    if "issued_date" in fields:
        updates["issued_date"] = fields["issued_date"]
    if ("expiry_date" in fields or "issued_date" in fields) and new_issued_str and new_expiry_str:
        if _parse_date(new_issued_str, "issued_date") > _parse_date(new_expiry_str, "expiry_date"):
            raise HTTPException(status_code=422, detail="issued_date cannot be after expiry_date.")

    for plain in ("purpose", "issued_by", "token_no"):
        if plain in fields:
            updates[plain] = fields[plain]
    if "notes" in fields:
        updates["notes"] = (fields["notes"].strip() if fields["notes"] else None) or None

    if not updates:
        return api_response(True, {"dsc_record": existing})

    row = dsc_repo.update(dsc_id, updates)
    if not row:
        raise HTTPException(status_code=404, detail="DSC record not found")

    _audit(firm_id, dsc_id, "update", current_user, old_data=existing, new_data=updates)
    return api_response(True, {"dsc_record": row})


@router.post("/{dsc_id}/renew")
def renew_dsc(dsc_id: str, body: DSCRenew, current_user: dict = Depends(rbac("dsc", "write"))):
    firm_id = current_user["firm_id"]
    existing = _get_owned_or_404(dsc_id, firm_id)

    new_expiry = _parse_date(body.new_expiry_date, "new_expiry_date")
    updates: dict = {"expiry_date": body.new_expiry_date}

    if body.new_issued_date:
        new_issued = _parse_date(body.new_issued_date, "new_issued_date")
        if new_issued > new_expiry:
            raise HTTPException(status_code=422, detail="new_issued_date cannot be after new_expiry_date.")
        updates["issued_date"] = body.new_issued_date
    if body.token_no is not None:
        updates["token_no"] = body.token_no

    row = dsc_repo.update(dsc_id, updates)
    if not row:
        raise HTTPException(status_code=404, detail="DSC record not found")

    _audit(
        firm_id, dsc_id, "renew", current_user,
        old_data={"expiry_date": existing.get("expiry_date")},
        new_data={"expiry_date": body.new_expiry_date},
    )
    return api_response(True, {"dsc_record": row})


@router.delete("/{dsc_id}")
def delete_dsc(dsc_id: str, current_user: dict = Depends(rbac("dsc", "delete"))):
    firm_id = current_user["firm_id"]
    existing = _get_owned_or_404(dsc_id, firm_id)

    ok = dsc_repo.soft_delete(dsc_id, deleted_by=current_user.get("auth_user_id"))
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete DSC record")

    _audit(firm_id, dsc_id, "delete", current_user, old_data=existing)
    return api_response(True, {"deleted": True})

"""A physical count of a client's fixed assets: the counts, one count's working paper, its findings and its close (POST-A-112). See
`services/fixed_asset_verifications`."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core import db_provider
from core.authz import can_access_client
from core.ist_clock import ist_today
from core.permissions import rbac
from models.accounting import one_line
from models.common import api_response
from models.iso_date import a_real_date
from services import fixed_asset_verifications as counts
from services.audit_service import log_event

router = APIRouter(prefix="/api/fixed-assets/verifications", tags=["fixed_assets"])

#: One sentence for a count that is not there and one the caller may not reach, so the answer is not an oracle for which ids exist.
NOT_FOUND = counts.NOT_FOUND


class CountIn(BaseModel):
    client_id: str
    #: The day the assets were counted, which has happened: not after India's today.
    verified_on: str
    #: Who counted, as the client names them (a person, a team or a firm of valuers), one line.
    counted_by: str = Field(..., min_length=1, max_length=counts.MAX_TEXT)
    note: Optional[str] = Field(None, max_length=counts.MAX_NOTE)

    _line = field_validator("counted_by", mode="before")(lambda cls, v: one_line(v) or "")

    @field_validator("verified_on")
    @classmethod
    def _a_day_that_has_come(cls, v):
        day = a_real_date(v, "verified_on")
        if day > ist_today().isoformat():
            raise ValueError("Counted on: that day has not come yet. A count is recorded once it has been made.")
        return day

    @field_validator("note", mode="before")
    @classmethod
    def _blank_note_is_none(cls, v):
        return v.strip() or None if isinstance(v, str) else v


class FindingIn(BaseModel):
    finding: Literal["found", "found_elsewhere", "not_found", "damaged"]
    #: Where the asset was seen, for an asset found elsewhere (the database refuses one without it, and ignores it otherwise).
    found_in: Optional[str] = Field(None, max_length=counts.MAX_TEXT)
    note: Optional[str] = Field(None, max_length=counts.MAX_NOTE)

    _line = field_validator("found_in", mode="before")(lambda cls, v: one_line(v))


def _db():
    # The register's own door (`routers/fixed_assets._db`): every read here is firm-scoped and asked of the client check first, and
    # the signed-in role holds no write on either table, so the privileged client is the one this reads and writes with.
    db = db_provider.service_db_or_none()
    if db is None:
        raise HTTPException(status_code=503, detail="The database is not configured, so asset counts cannot be read or recorded.")
    return db


def _the_count_row(db, firm_id: str, verification_id: str) -> Optional[dict]:
    rows = (db.table("fixed_asset_verifications").select("id, client_id").eq("id", verification_id).eq("firm_id", firm_id)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


@router.get("")
def list_verifications(client_id: Annotated[str, Query()], current_user: dict = Depends(rbac("accounting", "read"))):
    """The client's physical counts, latest first, each with its tally."""
    if not can_access_client(current_user, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    db = _db()
    return api_response(True, {"counts": counts.list_counts(db, current_user["firm_id"], client_id), "findings": counts.FINDINGS})


@router.post("")
def open_verification(body: CountIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Open a count of the client's assets on a day that has come; a client has one open count at a time."""
    if not can_access_client(current_user, body.client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    db = _db()
    firm_id = current_user["firm_id"]
    client = (db.table("clients").select("id").eq("id", body.client_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    row = counts.create(db, firm_id, body.client_id, verified_on=body.verified_on, counted_by=body.counted_by, note=body.note,
                        created_by=current_user.get("id"))
    log_event(firm_id, "fixed_asset_verification", row.get("id"), "open", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"client_id": body.client_id, "verified_on": body.verified_on, "counted_by": body.counted_by})
    return api_response(True, row)


@router.get("/{verification_id}")
def verification_paper(verification_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """One count's working paper: an open count lists every asset held on the day counted with its finding or none yet; a closed
    count lists its findings, which are its record."""
    db = _db()
    firm_id = current_user["firm_id"]
    found = _the_count_row(db, firm_id, verification_id)
    if not found or not can_access_client(current_user, found.get("client_id")):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    count = counts.one_count(db, firm_id, found["client_id"], verification_id)
    if not count:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return api_response(True, counts.paper(db, firm_id, found["client_id"], count))


@router.put("/{verification_id}/findings/{asset_id}")
def record_finding(verification_id: str, asset_id: str, body: FindingIn,
                   current_user: dict = Depends(rbac("accounting", "write"))):
    """Record (or replace) what an open count found of one asset; the register's place and keeper are read off the asset. A finding
    moves nothing: an asset found elsewhere is moved by recording a movement."""
    db = _db()
    firm_id = current_user["firm_id"]
    found = _the_count_row(db, firm_id, verification_id)
    # The client is the count's own, never the request's: a write, so the client check is asked here before anything is written.
    if not found or not can_access_client(current_user, found.get("client_id")):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    row = counts.record_finding(db, firm_id, found["client_id"], verification_id, asset_id, finding=body.finding,
                                found_in=body.found_in, note=body.note, recorded_by=current_user.get("id"))
    log_event(firm_id, "fixed_asset_verification", verification_id, "finding", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"asset_id": asset_id, "finding": row.get("finding"), "found_in": row.get("found_in"),
                        "register_location": row.get("register_location"), "register_custodian": row.get("register_custodian")})
    return api_response(True, row)


@router.post("/{verification_id}/close")
def close_verification(verification_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Close the count once every asset held on the day counted has a finding; a closed count is the working paper and never
    reopens."""
    db = _db()
    firm_id = current_user["firm_id"]
    found = _the_count_row(db, firm_id, verification_id)
    if not found or not can_access_client(current_user, found.get("client_id")):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    row = counts.close(db, firm_id, found["client_id"], verification_id, closed_by=current_user.get("id"))
    log_event(firm_id, "fixed_asset_verification", verification_id, "close", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data={"status": row.get("status"), "closed_at": row.get("closed_at")})
    return api_response(True, row)

"""Where an asset is and who keeps it, with its dated history (POST-A-112). See `services/fixed_asset_movements`."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import db_provider
from core.authz import can_access_client
from core.ist_clock import ist_today
from core.permissions import rbac
from models.accounting import one_line
from models.common import api_response
from models.iso_date import a_real_date
from services import fixed_asset_movements as movements
from services.audit_service import log_event

router = APIRouter(prefix="/api/fixed-assets", tags=["fixed_assets"])

#: One sentence for an asset that is not there and one the caller may not reach, as the register's own row routes answer, so the
#: answer is not an oracle for which asset ids exist; the database function's refusal of a missing asset is worded the same.
NOT_FOUND = movements.NOT_FOUND


class MovementIn(BaseModel):
    #: The day the asset moved, which has happened: not after India's today (the database asks the same).
    moved_on: str
    #: Where the asset was and who kept it when the form was opened: required keys (null where there was none), because the database
    #: refuses a movement sent from a form opened before the asset last moved, which would otherwise put it back where it was.
    from_location: Optional[str] = Field(..., max_length=movements.MAX_SEEN)
    from_custodian: Optional[str] = Field(..., max_length=movements.MAX_SEEN)
    #: Where the asset is and who keeps it AFTER the movement; a blank one means none.
    to_location: Optional[str] = Field(None, max_length=movements.MAX_TEXT)
    to_custodian: Optional[str] = Field(None, max_length=movements.MAX_TEXT)
    note: Optional[str] = Field(None, max_length=movements.MAX_NOTE)

    #: Tidied before the length is asked, as the database tidies them, so padding does not count against the limit.
    _lines = field_validator("from_location", "from_custodian", "to_location", "to_custodian", mode="before")(
        lambda cls, v: one_line(v))

    @field_validator("moved_on")
    @classmethod
    def _a_day_that_has_come(cls, v):
        day = a_real_date(v, "moved_on")
        if day > ist_today().isoformat():
            raise ValueError("Moved on: that day has not come yet. A movement is recorded once it has happened.")
        return day


def _db():
    # The register's own door (`routers/fixed_assets._db`): the asset table's writes are revoked from the signed-in role (migration 245),
    # and every read here is firm-scoped and asked of the client check first, so the privileged client is the one the register reads with.
    db = db_provider.service_db_or_none()
    if db is None:
        raise HTTPException(status_code=503, detail="The database is not configured, so asset movements cannot be read or recorded.")
    return db


def _live_asset(db, firm_id: str, asset_id: str) -> Optional[dict]:
    """The live asset of the firm, or None. Whether the caller may reach its client is asked by each route, on the row's own client."""
    rows = (db.table("fixed_assets").select("id, client_id, location, custodian").eq("id", asset_id)
            .eq("firm_id", firm_id).is_("deleted_at", "null").limit(1).execute().data) or []
    return rows[0] if rows else None


@router.get("/{asset_id}/movements")
def asset_movements(asset_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """The asset's place and keeper now, and every movement, latest first."""
    db = _db()
    asset = _live_asset(db, current_user["firm_id"], asset_id)
    if not asset or not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return api_response(True, {
        "location": asset.get("location"), "custodian": asset.get("custodian"),
        "movements": movements.history(db, current_user["firm_id"], asset["client_id"], asset_id),
    })


@router.post("/{asset_id}/movements")
def record_asset_movement(asset_id: str, body: MovementIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Record that the asset moved (a new place, a new keeper or both) on a day that has come; the asset moves with it. Refused, with
    nothing recorded, when the asset has moved since the form was opened (409)."""
    db = _db()
    asset = _live_asset(db, current_user["firm_id"], asset_id)
    # The client is the asset row's own, never the request's: a write, so the client check is asked here before anything is written.
    if not asset or not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    firm_id, client_id = current_user["firm_id"], asset["client_id"]
    row = movements.record(db, firm_id, client_id, asset_id, moved_on=body.moved_on, seen_location=body.from_location,
                           seen_custodian=body.from_custodian, to_location=body.to_location, to_custodian=body.to_custodian,
                           note=body.note, recorded_by=current_user.get("id"))
    log_event(firm_id, "fixed_asset", asset_id, "move", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              old_data={"location": row.get("from_location"), "custodian": row.get("from_custodian")},
              new_data={"location": row.get("to_location"), "custodian": row.get("to_custodian"), "moved_on": row.get("moved_on"),
                        "movement_id": row.get("id")})
    return api_response(True, row)

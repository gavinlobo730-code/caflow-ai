"""
Guided tips: one person's switch and the tips they have closed (POST-A-531).

GET  /api/guided-tips           whether the caller is shown tips, whether that is their own choice, and the ids they have closed
PUT  /api/guided-tips           the caller turns tips on or off
POST /api/guided-tips/seen      the caller closes one tip for good
POST /api/guided-tips/show-again  the caller asks to be shown every tip again

Every route acts on the CALLER'S OWN row and takes no person from the request. They are `identity`, the permission every staff role holds
over its own record: a tip is shown to whoever is looking at the screen, whatever their role. The tips themselves (their words, the screen
each belongs to) are the frontend's; the server keeps the two facts that must follow a person to every device.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool

from core.permissions import rbac
from domain.guidance import tips as rule
from models.common import api_response
from services import guided_tips_service as service

router = APIRouter(prefix="/api/guided-tips", tags=["guided-tips"])
_logger = logging.getLogger("caflow.guided_tips")

_NO_ROW = "Only a signed-in team member has guided tips."


class SwitchIn(BaseModel):
    # Strict: "off", 0 and "false" are not a decision about a switch, and a coerced one would be saved as one.
    on: StrictBool


class SeenIn(BaseModel):
    tip_id: str


def _ids(current_user: dict) -> tuple[str, str]:
    return current_user["firm_id"], current_user.get("id")


@router.get("")
def my_guided_tips(current_user: dict = Depends(rbac("identity", "read"))):
    """Whether the caller is shown tips and which they have closed. A row that cannot be read is an error in words, never "tips off"."""
    firm_id, user_id = _ids(current_user)
    state = service.read(firm_id, user_id)
    if state is None:
        raise HTTPException(status_code=403, detail=_NO_ROW)
    return api_response(True, state)


@router.put("")
def set_my_guided_tips(body: SwitchIn, current_user: dict = Depends(rbac("identity", "write"))):
    """The caller turns tips on or off, for themselves, on every device."""
    firm_id, user_id = _ids(current_user)
    try:
        return api_response(True, service.set_on(firm_id, user_id, body.on))
    except service.NotFound:
        raise HTTPException(status_code=403, detail=_NO_ROW) from None


@router.post("/seen")
def close_a_guided_tip(body: SeenIn, current_user: dict = Depends(rbac("identity", "write"))):
    """The caller closes one tip for good. Closing it twice is the same as closing it once."""
    problem = rule.tip_id_problem(body.tip_id)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    firm_id, user_id = _ids(current_user)
    try:
        return api_response(True, service.mark_seen(firm_id, user_id, body.tip_id))
    except service.NotFound:
        raise HTTPException(status_code=403, detail=_NO_ROW) from None


@router.post("/show-again")
def show_my_guided_tips_again(current_user: dict = Depends(rbac("identity", "write"))):
    """The caller asks to be shown every tip again. Whether tips are on is not changed."""
    firm_id, user_id = _ids(current_user)
    try:
        return api_response(True, service.show_all_again(firm_id, user_id))
    except service.NotFound:
        raise HTTPException(status_code=403, detail=_NO_ROW) from None

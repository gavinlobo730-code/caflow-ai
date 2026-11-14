"""A client's narration templates for its manual journals (POST-A-093, migration 590).

The journal editor lists them beside the narration box, fills the box with the one a CA picks, saves the narration it holds as a new
one, and takes one out of the list. The permissions are the manual journal's own: `accounting` read to list, `accounting` write to save
or archive, because the only use of a template is to write a journal. Nothing here touches a journal or a figure.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from core import db_provider
from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response

router = APIRouter(prefix="/api/narration-templates", tags=["narration_templates"])

_NO_DATABASE = "Narration templates are kept in the database, which this server is running without."


def _db():
    """The caller's own client through the one door (`core.db_provider`), or a 503 that says why there is none."""
    db = db_provider.request_db_or_none()
    if db is None:
        raise HTTPException(status_code=503, detail=_NO_DATABASE)
    return db


class TemplateIn(BaseModel):
    client_id: str
    narration: Optional[str] = None


@router.get("")
def list_narration_templates(
    client_id: Annotated[str, Query()],
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The client's live templates, alphabetically."""
    assert_client_access(current_user, client_id)
    from services import narration_template_service as svc
    return api_response(True, svc.list_templates(_db(), current_user.get("firm_id"), client_id))


@router.post("")
def save_narration_template(
    data: TemplateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Save the words as a template, or answer the one that already says them (`created` false)."""
    assert_client_access(current_user, data.client_id)
    from services import narration_template_service as svc
    from services.audit_service import log_event
    db = _db()
    firm_id = current_user.get("firm_id")
    answer = svc.save(db, firm_id, data.client_id, data.narration, actor_id=current_user.get("id"))
    if answer["created"]:
        log_event(firm_id or "", "journal_narration_template", answer["template"].get("id") or "", "create",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data={"client_id": data.client_id, "narration": answer["template"].get("narration")})
    return api_response(True, answer)


@router.delete("/{template_id}")
def archive_narration_template(
    template_id: Annotated[str, Path()],
    client_id: Annotated[str, Query()],
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Take a template out of the list. No journal is touched: an entry keeps its own narration."""
    assert_client_access(current_user, client_id)
    from services import narration_template_service as svc
    from services.audit_service import log_event
    firm_id = current_user.get("firm_id")
    answer = svc.archive(_db(), firm_id, client_id, template_id)
    log_event(firm_id or "", "journal_narration_template", template_id, "archive",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"client_id": client_id})
    return api_response(True, answer)

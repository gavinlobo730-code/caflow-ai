"""Recurring journal templates (ACC-06).

A template says what to post, to which accounts, and how often.
`POST /run` and `POST /{id}/generate` produce DRAFT manual journals through
`manual_journal_service.create` — the one posting kernel — and NEVER post one.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here files, transmits or
# posts. A generated entry sits in the draft queue until a CA issues it.
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access, filter_by_client
from core.permissions import rbac
from models.common import api_response
from services import recurring_journal_service as svc
from services.audit_service import log_event

router = APIRouter(prefix="/api/recurring-journals", tags=["recurring_journals"])


class TemplateLineIn(BaseModel):
    account_id: str
    debit_paise: int = 0
    credit_paise: int = 0
    narration: Optional[str] = None

    @field_validator("debit_paise", "credit_paise")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amounts are integer paise and cannot be negative")
        return v


class TemplateIn(BaseModel):
    client_id: str
    name: str
    frequency: str
    day_of_month: int = Field(default=1, ge=1, le=28)
    narration: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    next_run_date: Optional[str] = None
    status: str = "active"
    lines: list[TemplateLineIn]


class TemplateUpdateIn(BaseModel):
    """Partial. `lines` omitted leaves the stored ones; `lines` supplied
    REPLACES them wholesale — a journal's lines have no identity beyond their
    order, so a diff would have to invent one.

    `client_id` is absent: moving a template to another client would leave its
    generated journals pointing at the first one, and the runs ledger is keyed
    (template, occurrence) with no client in it.
    """
    name: Optional[str] = None
    frequency: Optional[str] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=28)
    narration: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    next_run_date: Optional[str] = None
    status: Optional[str] = None
    lines: Optional[list[TemplateLineIn]] = None


def _scoped(current_user: dict, template_id: str) -> dict:
    t = svc.get_template(current_user["firm_id"], template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Recurring journal template not found.")
    assert_client_access(current_user, t.get("client_id"))
    return t


@router.get("")
def list_templates(client_id: Optional[str] = Query(None),
                   status: Optional[str] = Query(None),
                   current_user: dict = Depends(rbac("accounting", "read"))):
    """Every template the caller may see, with its lines and next due date."""
    if client_id:
        assert_client_access(current_user, client_id)
    rows = svc.list_templates(current_user["firm_id"], client_id=client_id, status=status)
    return api_response(True, filter_by_client(current_user, rows))


@router.post("")
def create_template(body: TemplateIn,
                    current_user: dict = Depends(rbac("accounting", "write"))):
    assert_client_access(current_user, body.client_id)
    out = svc.create_template(current_user["firm_id"], body.model_dump(),
                              created_by=current_user.get("id"))
    log_event(current_user["firm_id"], "client", body.client_id,
              "recurring_journal_template_created",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=out)
    return api_response(True, out)


@router.get("/{template_id}")
def get_template(template_id: str = Path(...),
                 current_user: dict = Depends(rbac("accounting", "read"))):
    return api_response(True, _scoped(current_user, template_id))


@router.patch("/{template_id}")
def update_template(template_id: str = Path(...),
                    body: TemplateUpdateIn = ...,
                    current_user: dict = Depends(rbac("accounting", "write"))):
    t = _scoped(current_user, template_id)
    out = svc.update_template(current_user["firm_id"], template_id,
                              body.model_dump(exclude_unset=True))
    if out is None:
        raise HTTPException(status_code=404, detail="Recurring journal template not found.")
    log_event(current_user["firm_id"], "client", t.get("client_id"),
              "recurring_journal_template_updated",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=out)
    return api_response(True, out)


@router.delete("/{template_id}")
def delete_template(template_id: str = Path(...),
                    current_user: dict = Depends(rbac("accounting", "write"))):
    """Remove a template. The journals it already generated are untouched —
    they are ordinary manual journals, and deleting the template that suggested
    one says nothing about whether the entry was right."""
    t = _scoped(current_user, template_id)
    if not svc.delete_template(current_user["firm_id"], template_id):
        raise HTTPException(status_code=404, detail="Recurring journal template not found.")
    log_event(current_user["firm_id"], "client", t.get("client_id"),
              "recurring_journal_template_deleted",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=t)
    return api_response(True, {"deleted": True, "id": template_id})


@router.get("/{template_id}/history")
def template_history(template_id: str = Path(...),
                     current_user: dict = Depends(rbac("accounting", "read"))):
    """Every occurrence this template has generated — the run ledger, newest
    first, including the failures. A failed occurrence is kept rather than
    retried silently: a template that cannot post needs a CA."""
    _scoped(current_user, template_id)
    return api_response(True, svc.history(current_user["firm_id"], template_id))


@router.get("/{template_id}/preview")
def template_preview(template_id: str = Path(...),
                     count: int = Query(5, ge=1, le=24),
                     current_user: dict = Depends(rbac("accounting", "read"))):
    """The next few dates this template will generate on. Writes nothing."""
    t = _scoped(current_user, template_id)
    return api_response(True, {"template_id": template_id,
                               "occurrences": svc.preview(t, count=count)})


@router.post("/{template_id}/generate")
def generate_one(template_id: str = Path(...),
                 occurrence: Optional[str] = Query(None, description="YYYY-MM-DD"),
                 current_user: dict = Depends(rbac("accounting", "write"))):
    """Generate the DRAFT for one occurrence — the CA's "run it now".

    Idempotent: an occurrence already generated returns `created: false` and
    the existing entry rather than a second journal.
    """
    t = _scoped(current_user, template_id)
    occ = occurrence or (svc.due_occurrences(t) or [t.get("next_run_date")])[0]
    if not occ:
        raise HTTPException(status_code=422, detail="Nothing is due for this template.")
    out = svc.generate_for_occurrence(current_user["firm_id"], t, str(occ)[:10],
                                      actor_id=current_user.get("id"))
    return api_response(True, out)


@router.post("/run")
def run_due(client_id: Optional[str] = Query(None),
            as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today IST"),
            current_user: dict = Depends(rbac("accounting", "write"))):
    """Generate drafts for every due template. Idempotent; never posts."""
    if client_id:
        assert_client_access(current_user, client_id)
    out = svc.run_due(current_user["firm_id"], client_id=client_id, as_of=as_of,
                      actor_id=current_user.get("id"))
    return api_response(True, out)

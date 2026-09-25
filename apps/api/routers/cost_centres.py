"""Cost centres — the master, and income and expenditure by department.

Thin surface over `services/cost_centre_service.py`, which fetches and writes
over `domain/accounting/cost_centre.py`. Nothing here decides that an asset
line is dropped, that the unallocated balance is its own row, or that there is
no balance sheet by cost centre.

WHY IT IS ITS OWN ROUTER RATHER THAN PART OF /api/accounting
    `routers/accounting.py` is the LEDGER — the trial balance, the statements,
    the journal. A cost centre changes none of them, and mounting it there
    would put a management-reporting dimension beside the statutory engines
    and invite the next reader to add it to one. It is also what makes the
    guard below easy to state: a test asserts no return builder mentions the
    column at all.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from domain.accounting import cost_centre as rule
from models.common import api_response
from models.fy import FYLabel
from services import cost_centre_service as svc

router = APIRouter(prefix="/api/cost-centres", tags=["cost-centres"])


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


class CostCentreIn(BaseModel):
    client_id: str
    code: str = Field(..., max_length=rule.CODE_MAX)
    name: str
    description: Optional[str] = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        # The DOOR normalises and refuses, so `factory` and `FACTORY ` cannot
        # become two centres that look identical on every screen and split one
        # department's cost in two. The service normalises again, because a
        # caller reaching it another way must not be able to.
        problem = rule.problem_with_code(v)
        if problem:
            raise ValueError(problem)
        return rule.normalise_code(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        problem = rule.problem_with_name(v)
        if problem:
            raise ValueError(problem)
        return v.strip()


class CostCentreUpdateIn(BaseModel):
    """A PATCH. `None` means unchanged — a validator on the create door only is
    one PATCH from being none, so both carry the same rule."""
    code: Optional[str] = Field(None, max_length=rule.CODE_MAX)
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("code")
    @classmethod
    def _code(cls, v):
        if v is None:
            return v
        problem = rule.problem_with_code(v)
        if problem:
            raise ValueError(problem)
        return rule.normalise_code(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if v is None:
            return v
        problem = rule.problem_with_name(v)
        if problem:
            raise ValueError(problem)
        return v.strip()


@router.get("")
def list_cost_centres(
    client_id: str,
    include_retired: bool = False,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """This client's cost centres. Retired ones are excluded unless asked for.

    RETIRED, NEVER DELETED: posted lines point at them and migration 251 makes
    a posted line immutable, so closing a department does not un-spend last
    year's money. The master row stays and stops being offered — which is also
    why the FK is ON DELETE RESTRICT rather than CASCADE or SET NULL.
    """
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    rows = svc.list_centres(_db(), firm_id, client_id, include_retired=include_retired)
    return api_response(True, {
        "cost_centres": rows,
        "a_dimension_not_a_ledger": rule.A_DIMENSION_NOT_A_LEDGER,
    })


@router.post("")
def create_cost_centre(
    body: CostCentreIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, body.client_id)
    try:
        row = svc.create_centre(_db(), firm_id, body.client_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return api_response(True, row)


@router.patch("/{centre_id}")
def update_cost_centre(
    centre_id: str,
    body: CostCentreUpdateIn,
    client_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        row = svc.update_centre(_db(), firm_id, client_id, centre_id, patch)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return api_response(True, row)


@router.get("/allocation")
def cost_centre_allocation(
    client_id: str,
    financial_year: Annotated[FYLabel, Query()],
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Income and expenditure by cost centre for one financial year.

    ⚠️ INCOME AND EXPENDITURE ONLY. A cost centre divides what a business
    SPENDS and EARNS; splitting a bank balance or a receivable across
    departments needs an allocation basis nothing here records, and a
    departmental balance sheet built on an invented one would balance and mean
    nothing. Asset and liability lines are dropped even where a CA has tagged
    them — the bank leg of a departmental payment legitimately carries one.

    ⚠️ THE UNALLOCATED ROW IS PART OF THE ANSWER, not a gap. Most lines carry
    no cost centre by design — a bank leg, a GST leg and a TDS leg belong to no
    department — so it is expected to be large, and dropping it would stop the
    departments summing to the account.
    """
    firm_id = current_user.get("firm_id")
    assert_client_access(current_user, client_id)
    out = svc.allocation(_db(), firm_id, client_id, financial_year)

    def centre(c) -> dict:
        return {
            "cost_centre_id": c.cost_centre_id,
            "name": c.name,
            "income_paise": c.income_paise,
            "expense_paise": c.expense_paise,
            "result_paise": c.result_paise,
            "accounts": [
                {"account_id": a.account_id, "account_name": a.account_name,
                 "account_kind": a.account_kind, "amount_paise": a.amount_paise}
                for a in c.accounts
            ],
        }

    return api_response(True, {
        "financial_year": financial_year,
        "centres": [centre(c) for c in out.centres],
        "unallocated": centre(out.unallocated) if out.unallocated else None,
        "centres_with_no_activity": list(out.centres_with_no_activity),
        "notes": list(out.notes),
    })

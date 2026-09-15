"""Capital work-in-progress — the register, the two schedules, and the moment
it becomes an asset (FA-11a, migration 397).

Thin surface over `services/cwip_service.py`, which is a fetch-and-post layer
over `domain/fixed_assets/cwip.py`. Nothing here buckets an amount, decides
whether a project is overdue, or knows that capital work-in-progress is not
depreciated.

WHY IT IS ITS OWN ROUTER RATHER THAN PART OF /api/fixed-assets
    Because the whole point is that it is NOT a fixed asset. `routers/
    fixed_assets.py` is the register of assets in use — every one of them
    depreciated, every one of them on the Tangible or Intangible Schedule III
    line. An asset under construction is on a different line, carries no
    depreciation, and has its own two disclosure schedules. Mounting it there
    would make the next reader reach for `_SCHEDULE_II_PART_C`.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from domain.fixed_assets import cwip as cwip_domain
from models.common import api_response
from services import cwip_service as svc

router = APIRouter(prefix="/api/cwip", tags=["cwip"])


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _journal():
    from services.phase2_journal_service import Phase2JournalService
    return Phase2JournalService()


def _a_date(value: str, what: str) -> str:
    try:
        date.fromisoformat(str(value)[:10])
    except Exception:
        raise ValueError(f"{what} must be a date, as YYYY-MM-DD.")
    return str(value)[:10]


class ProjectIn(BaseModel):
    """A project under construction.

    `approved_completion_date` and `approved_cost_paise` are OPTIONAL and are
    not defaulted anywhere. Schedule III's completion schedule measures overdue
    and over-budget against the ORIGINAL approval, and neither can be inferred
    — the start date is not an approved completion date and what has been spent
    is not an approved cost. A project with neither is NAMED as undeterminable
    in the schedule rather than reported as compliant.
    """
    client_id: str
    project_name: str
    started_on: str
    project_code: Optional[str] = None
    asset_category: Optional[str] = None
    approved_completion_date: Optional[str] = None
    approved_cost_paise: Optional[int] = Field(None, gt=0)
    expected_completion_date: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("project_name")
    @classmethod
    def has_a_name(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Name the project. It is what the CA reads on the "
                             "ageing schedule months later.")
        return v.strip()

    @field_validator("started_on", "approved_completion_date",
                     "expected_completion_date")
    @classmethod
    def dates_are_dates(cls, v):
        return _a_date(v, "The date") if v else v


class CostIn(BaseModel):
    """One tranche of construction cost.

    `incurred_on` is the date the Schedule III ageing schedule ages from, and
    it is required with no default: the note ages the MONEY, so a build begun
    three years ago whose last bill arrived last month has amounts in three
    bands at once.
    """
    client_id: str
    incurred_on: str
    description: str
    amount_paise: int = Field(..., gt=0)
    igst_paise: int = Field(0, ge=0)
    cgst_paise: int = Field(0, ge=0)
    sgst_paise: int = Field(0, ge=0)
    itc_eligible: Optional[bool] = None
    itc_blocked_reason: Optional[str] = None
    acquisition_mode: Optional[str] = None
    vendor_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    bank_account_id: Optional[str] = None
    payment_mode: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("description")
    @classmethod
    def says_what_it_is(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Say what the cost is — a contractor's bill, "
                             "materials, a professional fee.")
        return v.strip()

    @field_validator("incurred_on")
    @classmethod
    def incurred_is_a_date(cls, v: str) -> str:
        return _a_date(v, "The date the cost was incurred")

    @field_validator("acquisition_mode")
    @classmethod
    def a_known_mode(cls, v):
        if v is None:
            return v
        if v not in ("paid", "credit", "from_bill"):
            raise ValueError("How it was paid for is 'paid', 'credit' or "
                             "'from_bill'.")
        return v


class StatusIn(BaseModel):
    client_id: str
    status: str
    on_date: str

    @field_validator("on_date")
    @classmethod
    def on_is_a_date(cls, v: str) -> str:
        return _a_date(v, "The date the status changed")


class CapitaliseIn(BaseModel):
    """The project is ready and becomes an asset.

    `put_to_use_date` is the date it became available for use — AS-10
    paragraph 20 — and is what depreciation runs from. Required: a
    capitalisation with no such date would either not depreciate at all or
    depreciate from the project's start, and the second is years of charge on
    an asset nobody could use.
    """
    client_id: str
    put_to_use_date: str
    asset_name: Optional[str] = None
    asset_category: Optional[str] = None
    useful_life_years: Optional[int] = Field(None, gt=0)
    depreciation_method: Optional[str] = None

    @field_validator("put_to_use_date")
    @classmethod
    def ready_is_a_date(cls, v: str) -> str:
        return _a_date(v, "The date the asset became ready for use")


@router.get("")
def list_projects(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Every project, with what has been spent on each."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"projects": [], "additions": [],
                                   "statuses": list(cwip_domain.ROW_LABELS),
                                   "does_not_depreciate":
                                       cwip_domain.CWIP_DOES_NOT_DEPRECIATE})
    return api_response(True, svc.register(
        _db(), firm_id=current_user.get("firm_id") or "", client_id=client_id))


@router.get("/schedules")
def get_schedules(
    client_id: str = Query(...),
    as_of: str = Query(..., description='"YYYY-MM-DD" — the reporting date'),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """The Schedule III CWIP ageing schedule and completion schedule.

    AS AT A DATE, and the date is required with no default. A project
    capitalised in June is capital work-in-progress in a 31 March note and a
    fixed asset in a 30 September one; defaulting to today would silently
    answer a different question from the one a year-end asks.
    """
    assert_client_access(current_user, client_id)
    try:
        when = date.fromisoformat(as_of[:10])
    except Exception:
        raise HTTPException(status_code=422,
                            detail="The reporting date must be YYYY-MM-DD.")
    if _mock_enabled():
        # The DOMAIN's empty answer, not a hand-written stub: the bucket
        # order, the row labels and the caveat are what a screen renders, and
        # a stub omitting one would pass mock-mode tests and render blank.
        return api_response(True, {
            "ageing": cwip_domain.ageing([], [], as_of=when).as_dict(),
            "completion_schedule":
                cwip_domain.completion_schedule([], [], as_of=when).as_dict(),
            "does_not_depreciate": cwip_domain.CWIP_DOES_NOT_DEPRECIATE,
        })
    return api_response(True, svc.schedules(
        _db(), firm_id=current_user.get("firm_id") or "",
        client_id=client_id, as_of=when))


@router.post("")
def create_project(
    data: ProjectIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": "mock-cwip", **data.model_dump()})
    return api_response(True, svc.create_project(
        _db(), firm_id=current_user.get("firm_id") or "",
        client_id=data.client_id, project_name=data.project_name,
        started_on=data.started_on, project_code=data.project_code,
        asset_category=data.asset_category,
        approved_completion_date=data.approved_completion_date,
        approved_cost_paise=data.approved_cost_paise,
        expected_completion_date=data.expected_completion_date,
        notes=data.notes, actor_id=current_user.get("id")))


@router.post("/{cwip_id}/costs")
def add_cost(
    cwip_id: str,
    data: CostIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Record and post one tranche of construction cost.

    THE PERIOD IS ASKED, because this posts to the general ledger — the
    posting kernel asks the closures itself, and asking here means the CA gets
    the sentence rather than a failure inside the kernel.
    """
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"ok": True, "addition": {"id": "mock-cost"}})
    db = _db()
    from services import period_lock_service
    period_lock_service.assert_open(db, current_user.get("firm_id") or "",
                                    data.client_id, data.incurred_on)
    result = svc.add_cost(
        db, firm_id=current_user.get("firm_id") or "", client_id=data.client_id,
        cwip_id=cwip_id, incurred_on=data.incurred_on,
        description=data.description, amount_paise=data.amount_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise,
        sgst_paise=data.sgst_paise, itc_eligible=data.itc_eligible,
        itc_blocked_reason=data.itc_blocked_reason,
        acquisition_mode=data.acquisition_mode, vendor_id=data.vendor_id,
        purchase_bill_id=data.purchase_bill_id,
        bank_account_id=data.bank_account_id, payment_mode=data.payment_mode,
        notes=data.notes, actor_id=current_user.get("id"), journal=_journal())
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    return api_response(True, result)


@router.put("/{cwip_id}/status")
def set_status(
    cwip_id: str,
    data: StatusIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Suspend or resume. The balance stays in capital work-in-progress either
    way — suspension moves it to the other ROW of the ageing schedule."""
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"ok": True, "status": data.status})
    result = svc.set_status(
        _db(), firm_id=current_user.get("firm_id") or "",
        client_id=data.client_id, cwip_id=cwip_id, status=data.status,
        on_date=data.on_date)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    return api_response(True, result)


@router.post("/{cwip_id}/capitalise")
def capitalise(
    cwip_id: str,
    data: CapitaliseIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """The project becomes a fixed asset and depreciation starts."""
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"ok": True, "asset": {"id": "mock-asset"},
                                   "cost_paise": 0})
    db = _db()
    from services import period_lock_service
    period_lock_service.assert_open(db, current_user.get("firm_id") or "",
                                    data.client_id, data.put_to_use_date)
    result = svc.capitalise(
        db, firm_id=current_user.get("firm_id") or "", client_id=data.client_id,
        cwip_id=cwip_id, put_to_use_date=data.put_to_use_date,
        asset_name=data.asset_name, asset_category=data.asset_category,
        useful_life_years=data.useful_life_years,
        depreciation_method=data.depreciation_method,
        actor_id=current_user.get("id"), journal=_journal())
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("refusal"))
    return api_response(True, result)

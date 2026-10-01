"""Annual Information Statement routes — IT Act §285BB.

The reconciliation a CA does against AIS before filing an ITR. It used to
live entirely in a browser page's React state (apps/web/app/income-tax/ais),
so it could be looked at once and never recorded; migration 352 and
services/ais_service give it the shape 26AS has had since migration 156.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
# Nothing here reaches the income-tax portal. AIS is DOWNLOADED from
# incometax.gov.in by hand and uploaded here; feedback on a wrong AIS line is
# submitted on the portal, not from this software.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.fy import AYLabel, FYLabel, OptionalAYLabel
from services import ais_computation_service, ais_service

router = APIRouter(prefix="/api/ais", tags=["ais"])
_logger = logging.getLogger("caflow.ais.router")

# One MB of JSON is a very large AIS. The cap is here rather than in the
# service because it is a property of the request, not of the statement.
_MAX_RAW_CHARS = 4_000_000


class UploadRequest(BaseModel):
    client_id: str
    # The ASSESSMENT year, not the financial year — AIS is published and
    # labelled per AY on the portal. AYLabel is the same label rule as
    # FYLabel: '2026-28' passes a shape regex and then means 2026-27.
    assessment_year: AYLabel
    raw: str
    file_name: Optional[str] = None


class WorkingRequest(BaseModel):
    client_id: str
    # NULL is "nobody has looked", and is not the same statement as 0.
    books_amount_paise: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


class ManualLineRequest(BaseModel):
    client_id: str
    upload_id: str
    transaction_type: str
    payer: str
    amount_paise: int = Field(ge=0)
    tds_deducted_paise: int = Field(default=0, ge=0)
    information_label: Optional[str] = None


def _refusal(exc: ais_service.AISRefused) -> HTTPException:
    """A refusal is a 400 the CA reads, never a 500.

    Every message this module raises names what to do next, so it is shown
    verbatim rather than replaced with a generic one.
    """
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/uploads")
def upload_statement(
    req: UploadRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Upload one AIS JSON downloaded from the portal."""
    assert_client_access(current_user, req.client_id)
    if len(req.raw or "") > _MAX_RAW_CHARS:
        raise HTTPException(
            413, detail="That file is larger than any AIS statement. Check it "
                        "is the AIS JSON and not a full document download.")
    try:
        return api_response(True, ais_service.upload_statement(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            assessment_year=req.assessment_year,
            raw=req.raw,
            file_name=req.file_name,
            uploaded_by=current_user["id"],
        ))
    except ais_service.AISRefused as e:
        raise _refusal(e)
    except Exception:
        _logger.exception("AIS upload failed")
        raise HTTPException(500, detail="Could not read that statement.")


@router.get("/uploads")
def list_uploads(
    client_id: str,
    assessment_year: Annotated[OptionalAYLabel, Query()] = None,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    assert_client_access(current_user, client_id)
    return api_response(True, ais_service.list_uploads(
        current_user["firm_id"], client_id, assessment_year))


@router.get("/statement")
def get_statement(
    client_id: str,
    assessment_year: Annotated[AYLabel, Query()],
    upload_id: Optional[str] = None,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The statement, its lines, each line's working, and the summary."""
    assert_client_access(current_user, client_id)
    return api_response(True, ais_service.get_statement(
        firm_id=current_user["firm_id"],
        client_id=client_id,
        assessment_year=assessment_year,
        upload_id=upload_id,
    ))


@router.put("/records/{record_id}/working")
def save_working(
    record_id: str,
    req: WorkingRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """What the books carry for one AIS line, and what the CA concluded."""
    assert_client_access(current_user, req.client_id)
    try:
        return api_response(True, ais_service.save_working(
            firm_id=current_user["firm_id"],
            record_id=record_id,
            books_amount_paise=req.books_amount_paise,
            status=req.status,
            note=req.note,
            reviewed_by=current_user["id"],
        ))
    except ais_service.AISRefused as e:
        raise _refusal(e)


@router.post("/records")
def add_manual_record(
    req: ManualLineRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """A line the CA knows about that the statement does not carry."""
    assert_client_access(current_user, req.client_id)
    try:
        return api_response(True, ais_service.add_manual_record(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            upload_id=req.upload_id,
            transaction_type=req.transaction_type,
            payer=req.payer,
            amount_paise=req.amount_paise,
            tds_deducted_paise=req.tds_deducted_paise,
            information_label=req.information_label,
        ))
    except ais_service.AISRefused as e:
        raise _refusal(e)


@router.delete("/records/{record_id}")
def delete_record(
    record_id: str,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Only a line the firm added — a published line is refused, with why."""
    try:
        record = ais_service.get_record(current_user["firm_id"], record_id)
        if not record:
            raise HTTPException(404, detail="Record not found")
        # Row-addressed, so the mount guard never fires: scope it here.
        assert_client_access(current_user, record["client_id"])
        return api_response(True, ais_service.delete_record(
            firm_id=current_user["firm_id"], record_id=record_id))
    except ais_service.AISRefused as e:
        raise _refusal(e)


@router.get("/computation-lines")
def computation_lines(
    client_id: str,
    financial_year: Annotated[FYLabel, Query()],
    typed_gross_salary_paise: Optional[int] = Query(None, ge=0),
    typed_other_income_paise: Optional[int] = Query(None, ge=0),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The AIS lines the computation can take — salary, interest, dividend —
    with their sources and the CA's accept or reject, and where a figure
    already typed into a box differs from the statement (TDS-INCOME-TAX-10).

    The two `typed_*` figures are what is ALREADY in the boxes; an absent one is
    "not typed", which is not the same as zero. Nothing is applied here: an AIS
    figure is what others reported, the screen fills only an EMPTY box, and a
    differing typed figure is flagged and kept.
    """
    assert_client_access(current_user, client_id)
    typed = {}
    if typed_gross_salary_paise is not None:
        typed["gross_salary_paise"] = typed_gross_salary_paise
    if typed_other_income_paise is not None:
        typed["other_income_paise"] = typed_other_income_paise
    return api_response(True, ais_computation_service.suggestions(
        firm_id=current_user["firm_id"], client_id=client_id,
        fy=financial_year, typed=typed))


class ComputationDecisionRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    #: accepted | rejected | undecided (takes the decision back)
    decision: str


@router.put("/computation-lines/{line_key}/decision")
def decide_computation_line(
    line_key: str,
    req: ComputationDecisionRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Accept or reject one line, on the figure the CA is looking at."""
    assert_client_access(current_user, req.client_id)
    try:
        return api_response(True, ais_computation_service.decide(
            firm_id=current_user["firm_id"], client_id=req.client_id,
            fy=req.financial_year, line_key=line_key, decision=req.decision,
            user_id=current_user["id"]))
    except ais_computation_service.DecisionRefused as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/meta")
def meta(current_user: dict = Depends(rbac("income_tax", "read"))):
    """The vocabulary the screen renders, from the one place that holds it."""
    return api_response(True, {
        "transaction_types": list(ais_service.TRANSACTION_TYPES),
        "statuses": list(ais_service.STATUSES),
    })

"""Interest on an overdue customer balance (accounting-22).

THIN, BY DESIGN. The rule is `domain/sales/late_interest.py` and the fetching and
the draft are `services/late_interest_service.py`; this module decides only who
may ask and what shape the request has. Read the domain header for the
convention (simple, actual/365, half rounds up), what the balance is, and the
one statutory reading it carries (CGST Act s.15(2)(d), graded `[S]`).

NOTHING HERE POSTS, ISSUES OR EMAILS. `GET /preview` reads. `POST /drafts` makes
an ordinary DRAFT sales invoice through the sales engine, which posts no journal
until somebody issues it — and the CA still has to replace the placeholder
number. `PUT /terms` records a commercial term.

`client_id` IS REQUIRED on every route: interest is a term between ONE client
and ITS customer, and a firm-wide answer would add together the receivables of
unrelated businesses.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator

from core.authz import assert_client_access
from core.permissions import rbac
from domain.sales import late_interest as L
from models.common import api_response
from services import late_interest_service as service

_logger = logging.getLogger("caflow.late_interest")

router = APIRouter(prefix="/api/late-interest", tags=["accounting"])

_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _db():
    """The privileged client, or a 503 with no database. Every route is rbac()-
    gated and checks the client scope first; the reads and writes carry
    `firm_id` and `client_id` filters in the service."""
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(
            status_code=503,
            detail="Interest is computed from the live books and is unavailable "
                   "without the database.")
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


class LateInterestTermsIn(BaseModel):
    """A customer's interest terms. `rate_bps` is an ANNUAL rate in basis points
    (1800 = 18% a year); `null` clears it, which is a different fact from 0
    ("interest is waived")."""

    client_id: str
    customer_id: str
    rate_bps: Optional[int] = None
    grace_days: int = 0
    basis: str = L.FROM_DUE_DATE

    @model_validator(mode="after")
    def _terms_are_terms(self):
        # The same function the service asks: a validator on this door alone is
        # one other writer from being none.
        problem = L.terms_problem(self.rate_bps, self.grace_days, self.basis)
        if problem:
            raise ValueError(problem)
        return self


class LateInterestDraftIn(BaseModel):
    client_id: str
    customer_id: str
    #: Defaults to today (IST). The figures are recomputed from the books on the
    #: server; nothing here carries an amount.
    as_of_date: Optional[str] = None
    #: A subset of the overdue invoices; omitted means every one that has
    #: interest due.
    invoice_ids: Optional[list[str]] = None

    @field_validator("as_of_date")
    @classmethod
    def _a_date(cls, v):
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("as_of_date must be a date (YYYY-MM-DD).")
        return v


def _as_of(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


@router.get("/preview")
def preview(
    client_id: str = Query(...),
    as_of: Annotated[Optional[str], Query(pattern=_DATE)] = None,
    customer_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Interest due per party as at a date, from the open invoices. Writes
    nothing and states the day-count convention on every answer."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, service.preview(
        db, current_user["firm_id"], client_id, _as_of(as_of), customer_id))


@router.get("/terms")
def list_terms(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Every customer of the client with the interest terms on record."""
    assert_client_access(current_user, client_id)
    db = _db()
    return api_response(True, {"customers": service.list_terms(db, current_user["firm_id"], client_id)})


@router.put("/terms")
def put_terms(
    body: LateInterestTermsIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Record, change or clear one customer's interest terms. The one writer of
    those three columns."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.set_terms(
        db, current_user["firm_id"], body.client_id, body.customer_id,
        rate_bps=body.rate_bps, grace_days=body.grace_days, basis=body.basis,
        actor=current_user))


@router.post("/drafts")
def prepare_drafts(
    body: LateInterestDraftIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Prepare DRAFT sales invoice(s) for one customer's interest as at a date.

    Posts nothing, issues nothing and emails nothing. The figures are computed
    here, from the books, never taken from the request."""
    assert_client_access(current_user, body.client_id)
    db = _db()
    return api_response(True, service.prepare_drafts(
        db, current_user["firm_id"], body.client_id, body.customer_id,
        _as_of(body.as_of_date), current_user, body.invoice_ids))

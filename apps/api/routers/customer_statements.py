"""
Customer Statements router (Phase 4.1) — read-only consolidated account
statements per customer. Reuses existing invoices/receipts/credit notes; the
shared invoice PDF stack; and the Resend email service. Firm + client + customer
scoped (assignment isolation via RLS, mirroring invoices). No accounting writes.

Auth mirrors invoice documents: read/PDF = rbac("invoice","read"); email =
rbac("invoice","write").
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.customer_statement_service import customer_statement_service
from services.audit_service import log_event
from services.email_service import GENERIC_SEND_FAILURE_MESSAGE

_logger = logging.getLogger("caflow.customer_statements")

router = APIRouter(prefix="/api/customer-statements", tags=["customer-statements"])


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


class StatementEmailIn(BaseModel):
    client_id: str
    customer_id: str
    start_date: str
    end_date: str
    to_email: Optional[str] = None


@router.get("")
def get_statement(
    client_id: str = Query(...),
    customer_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """Generate the customer statement (JSON). Read-only."""
    db = _db()
    if not db:
        return api_response(True, {"customer": {"id": customer_id}, "transactions": [],
                                   "opening_balance_paise": 0, "closing_balance_paise": 0})
    stmt = customer_statement_service.generate(
        db, current_user["firm_id"], client_id, customer_id, start_date, end_date)
    _audit(current_user, customer_id, "generate", client_id, start_date, end_date)
    return api_response(True, stmt)


@router.get("/pdf")
def get_statement_pdf(
    client_id: str = Query(...),
    customer_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """Download the statement as a PDF (read-only document)."""
    db = _db()
    if not db:
        return Response(content=b"", media_type="application/pdf")
    from services.statement_pdf_service import get_customer_statement_pdf
    pdf_bytes, filename = get_customer_statement_pdf(
        db, current_user["firm_id"], client_id, customer_id, start_date, end_date)
    _audit(current_user, customer_id, "download", client_id, start_date, end_date)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/email")
def email_statement(
    data: StatementEmailIn,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Email the statement PDF to the customer (tracked + audited)."""
    db = _db()
    if not db:
        return api_response(True, {"sent": True, "to": data.to_email})
    firm_id = current_user["firm_id"]
    actor_id = current_user.get("auth_user_id")
    actor_email = current_user.get("email")

    stmt = customer_statement_service.generate(
        db, firm_id, data.client_id, data.customer_id, data.start_date, data.end_date)
    to_email = data.to_email or (stmt["customer"].get("email"))
    if not to_email:
        raise HTTPException(status_code=422,
                            detail="No email address — add one to the customer or provide it in the request.")
    try:
        from email_validator import validate_email as _ve
        _ve(to_email, check_deliverability=False)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid email address: {to_email}")

    delivery_id = customer_statement_service.record_delivery(
        db, firm_id, data.client_id, data.customer_id, data.start_date, data.end_date,
        to_email, actor_id, actor_email)

    from services.statement_pdf_service import build_statement_pdf
    from services.invoice_pdf_service import _load_firm
    from services.email_service import send_statement_to_customer
    firm = _load_firm(firm_id)
    pdf_bytes = build_statement_pdf(stmt, firm, stmt["customer"])
    name = (stmt["customer"].get("name") or "customer").replace(" ", "-").lower()
    success, provider_id = send_statement_to_customer(
        to=to_email, customer_name=stmt["customer"].get("name") or "Customer",
        firm_name=firm.get("name") or "Your Chartered Accountant",
        period_start=data.start_date, period_end=data.end_date,
        closing_balance_paise=stmt["closing_balance_paise"],
        pdf_bytes=pdf_bytes, pdf_filename=f"statement-{name}.pdf")

    customer_statement_service.finish_delivery(
        db, delivery_id, success, provider_id,
        None if success else GENERIC_SEND_FAILURE_MESSAGE)
    _audit(current_user, data.customer_id, "email", data.client_id, data.start_date, data.end_date,
           extra={"sent_to": to_email, "success": success})
    if not success:
        raise HTTPException(status_code=502, detail="Statement email could not be sent.")
    return api_response(True, {"sent": True, "to": to_email, "delivery_id": delivery_id})


@router.get("/deliveries")
def list_deliveries(
    client_id: str = Query(...),
    customer_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    return api_response(True, customer_statement_service.deliveries(
        db, current_user["firm_id"], client_id, customer_id))


def _audit(current_user, customer_id, action, client_id, start, end, extra=None):
    try:
        log_event(current_user["firm_id"], "customer_statement", customer_id, action,
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data={"client_id": client_id, "period_start": start, "period_end": end, **(extra or {})},
                  metadata={"source": "customer_statement"})
    except Exception:  # pragma: no cover - audit must never block
        pass

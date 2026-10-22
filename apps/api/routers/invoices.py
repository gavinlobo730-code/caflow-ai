"""
Invoice management endpoints.

All endpoints require RBAC: billing.read/write. These are the PRACTICE'S OWN fee invoices (`fee_invoices`), the
practice's economics, so they are a Partner's (or a grant on the Team screen). They asked invoice.read/write, an
Executive's, until POST-B-024, while the database was about to refuse an Executive these rows, so the same table
answered an Executive's list with data from one door and nothing from the other.

Endpoints:
  GET    /api/invoices                           - list invoices (with filters)
  GET    /api/invoices/{invoice_id}              - get one invoice
  POST   /api/invoices/from-engagement/{id}      - generate from fixed fee
  POST   /api/invoices/from-time/{id}            - generate from time entries
  PATCH  /api/invoices/{invoice_id}/status       - transition status
  DELETE /api/invoices/{invoice_id}              - delete (Draft only)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.exceptions import unhandled_failure
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, effective_client_ids, filter_by_client
from repositories.invoice_repository import invoice_repo
from services.audit_service import log_event

router = APIRouter(prefix="/api/invoices", tags=["invoices"])
_logger = logging.getLogger("caflow.invoices.router")


def _database_refusal(exc: Exception, *, action: str) -> tuple[int, str]:
    """A status and a sentence for a write the database refused.

    Was a bare `except Exception as e: raise HTTPException(400, str(e))`
    around invoice-number generation (sweep-misc-tools-06), so a
    permission-denied APIError — the RAW Postgres/PostgREST payload — went
    straight to the CA as the reason "Raise Invoice" failed. unhandled_failure
    already turns a recognised SQLSTATE into a 4xx and a sentence; anything
    else is logged by the caller and gets a sentence saying so, never the
    raw text.
    """
    spoken = unhandled_failure(exc)
    if spoken:
        return spoken
    return 500, (f"Could not {action}. The cause has been logged; please try "
                 f"again, and report it if it keeps failing.")


def _assert_invoice_scope(current_user: dict, invoice_id: str) -> dict:
    """Resolve a fee_invoices row and 404 unless the caller may access its
    client. invoice_repo.find_by_id() does not itself filter by firm, so the
    firm check below is load-bearing, not redundant with it.

    404 (not the router's previous 403) and can_access_client (not
    assert_client_access, which raises its own generic message) so a hidden
    invoice and a missing one are byte-identical — existence isn't
    disclosed, matching every other audited router. Previously a missing
    invoice_id got 404 "Invoice not found" while a wrong-firm one got 403
    "Access denied": two different status codes on the same not-yours
    outcome is itself a disclosure oracle, independent of the M2 gap this
    fixes."""
    invoice = invoice_repo.find_by_id(invoice_id)
    if (not invoice or invoice.get("firm_id") != current_user.get("firm_id")
            or not can_access_client(current_user, invoice.get("client_id"))):
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _assert_engagement_scope(current_user: dict, engagement_id: str) -> dict:
    """Resolve a fee_engagements row and 404 unless the caller may access its
    client. fee_engagements.client_id is NOT NULL (migration 014) — every
    engagement belongs to exactly one client. engagement_repo.find_by_id()
    does not itself filter by firm, same shape as invoice_repo above."""
    from repositories.engagement_repository import engagement_repo

    engagement = engagement_repo.find_by_id(engagement_id)
    if (not engagement or engagement.get("firm_id") != current_user.get("firm_id")
            or not can_access_client(current_user, engagement.get("client_id"))):
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


class InvoiceListQuery(BaseModel):
    engagement_id: Optional[str] = None
    client_id: Optional[str] = None
    status: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class GenerateFromTimeQuery(BaseModel):
    invoice_month: Optional[str] = None
    billable_only: bool = True


#: The status moves a person may make by hand. Paid is reached by a receipt (migration 172) and left by nobody, and an invoice
#: that has had money received against it moves only between Issued and Overdue, which is what the nightly check does too.
_MANUAL_STATUS_MOVES: dict[str, tuple[str, ...]] = {
    "Draft": ("Issued",),
    "Issued": ("Overdue",),
    "Overdue": ("Issued",),
}
#: The two statuses an invoice that has had money received may move between by hand (what the nightly check does as well).
_MOVES_THAT_FOLLOW_RECEIPTS_FREELY = frozenset(("Issued", "Overdue"))


class StatusChangeRequest(BaseModel):
    new_status: str = Field(..., description="New status: Issued or Overdue (Paid comes from a receipt; Draft is where an invoice starts)")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices — List invoices with optional filters
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_invoices(
    engagement_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("billing", "read")),
):
    """
    List invoices with optional filters.

    Query parameters:
      - engagement_id: Filter by engagement
      - client_id: Filter by client
      - status: Filter by status (Draft, Issued, Paid, Overdue)
      - date_from: Filter from date (ISO format)
      - date_to: Filter to date (ISO format)
    """
    firm_id = current_user.get("firm_id")

    # M2 audit finding: client_id is caller-supplied and was never checked
    # against the caller's assignment — any member of the firm could list
    # any other client's invoices by id, and without one at all the query
    # returned every invoice in the firm unfiltered.
    if client_id:
        assert_client_access(current_user, client_id)

    invoices = invoice_repo.find_all(
        firm_id=firm_id,
        engagement_id=engagement_id,
        client_id=client_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    if not client_id:
        invoices = filter_by_client(current_user, invoices)

    return api_response(True, {
        "invoices": invoices,
        "total": len(invoices),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices/{invoice_id} — Get single invoice
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("billing", "read")),
):
    """Fetch a single invoice by ID."""
    invoice = _assert_invoice_scope(current_user, invoice_id)
    return api_response(True, {"invoice": invoice})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/from-engagement/{engagement_id} — Generate from fixed fee
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/from-engagement/{engagement_id}")
def generate_from_engagement(
    engagement_id: str,
    invoice_month: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("billing", "write")),
):
    """
    Generate a draft invoice from a fixed-fee engagement.

    The invoice amount is taken from engagement.fee_paise, with 18% GST added.

    Query parameters:
      - invoice_month: Optional invoice date (ISO format, defaults to today)
    """
    from services.invoice_generation_service import generate_invoice_from_engagement

    # Verify the engagement exists and the caller may access its client
    _assert_engagement_scope(current_user, engagement_id)

    from services.invoice_generation_service import PeriodAlreadyBilled
    try:
        invoice_id = generate_invoice_from_engagement(engagement_id, invoice_month)
        invoice = invoice_repo.find_by_id(invoice_id)
        return api_response(True, {"invoice": invoice})
    except HTTPException:
        raise
    except PeriodAlreadyBilled as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _logger.exception("Failed to raise invoice for engagement %s", engagement_id)
        status, sentence = _database_refusal(e, action="raise the invoice")
        raise HTTPException(status_code=status, detail=sentence)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/from-time/{engagement_id} — Generate from time entries
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/from-time/{engagement_id}")
def generate_from_time_entries(
    engagement_id: str,
    invoice_month: Optional[str] = Query(None),
    billable_only: bool = Query(True),
    current_user: dict = Depends(rbac("billing", "write")),
):
    """
    Generate a draft invoice from time entries.

    Queries time_entries for the engagement in the specified month and
    calculates invoice amount based on hourly rates.

    Query parameters:
      - invoice_month: Optional invoice date (ISO format, defaults to today)
      - billable_only: Include only billable time entries (default: true)
    """
    from services.invoice_generation_service import generate_invoice_from_time_entries

    # Verify the engagement exists and the caller may access its client
    _assert_engagement_scope(current_user, engagement_id)

    try:
        invoice_id = generate_invoice_from_time_entries(
            engagement_id,
            invoice_month,
            billable_only,
        )
        invoice = invoice_repo.find_by_id(invoice_id)
        return api_response(True, {"invoice": invoice})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices/{invoice_id}/pdf — Download GST tax invoice PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: str,
    current_user: dict = Depends(rbac("billing", "read")),
):
    """
    Render and download the GST-compliant tax invoice PDF.
    Includes firm details, client details, SAC code and CGST/SGST/IGST breakdown.
    """
    from fastapi.responses import Response
    from services.invoice_pdf_service import get_invoice_pdf

    _assert_invoice_scope(current_user, invoice_id)

    pdf_bytes, filename = get_invoice_pdf(invoice_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/run-overdue-check — Transition Issued past due to Overdue
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run-overdue-check")
def run_overdue_check_endpoint(
    current_user: dict = Depends(rbac("billing", "write")),
):
    """
    Run the invoice lifecycle check for this firm: any Issued invoice past
    its due date (invoice_date + 30 days if no explicit due_date) is marked
    Overdue. Also runs automatically via the daily scheduler.

    M2 audit finding: this is a WRITE across every invoice in the firm, not
    a list — narrowing the output would be the wrong shape, since the status
    transitions would already have happened. Instead the run itself is
    confined to the caller's book, the same "confine-the-run" pattern
    recurring_invoices.py's /run uses: a Partner is firm-wide and runs once
    across the whole firm as before; an Executive or Reviewer runs once per
    client they are actually assigned to.
    """
    from services.invoice_lifecycle_service import run_overdue_check

    firm_id = current_user.get("firm_id")
    eff = effective_client_ids(current_user)
    targets = [None] if eff is None else sorted(eff)

    merged = {"transitioned": 0, "invoice_ids": []}
    for target in targets:
        res = run_overdue_check(firm_id=firm_id, client_id=target)
        merged["transitioned"] += res.get("transitioned", 0)
        merged["invoice_ids"].extend(res.get("invoice_ids", []))
    return api_response(True, merged)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/invoices/{invoice_id}/status — Transition status
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{invoice_id}/status")
def change_invoice_status(
    invoice_id: str,
    body: StatusChangeRequest,
    current_user: dict = Depends(rbac("billing", "write")),
):
    """
    Move an invoice between the statuses a person may set: Draft -> Issued, Issued -> Overdue and Overdue -> Issued.
    Paid is never set here (a receipt that covers the total does it) and nothing moves out of Paid.

    Request body:
      - new_status: One of 'Draft', 'Issued', 'Paid', 'Overdue' (Paid is refused in words)
    """
    firm_id = current_user.get("firm_id")
    invoice = _assert_invoice_scope(current_user, invoice_id)

    # Validate new_status
    valid_statuses = ("Draft", "Issued", "Paid", "Overdue")
    if body.new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    # 'Paid' is not a status anyone sets (ledger POST-A-320): since migration 172 an invoice is Paid because its RECEIPTS cover
    # its total (`record_fee_receipt_atomic` moves `paid_paise` and the status together), and a bare flip would leave a Paid
    # invoice with nothing received, which is the lie that migration closed. The route used to be unreachable in production
    # (the update it ran was refused by the database), so refusing the one transition costs nobody anything.
    if body.new_status == "Paid":
        raise HTTPException(
            status_code=422,
            detail="An invoice becomes Paid when receipts cover its total: record a receipt against it instead.",
        )

    # The other half of the same lie, from the other side: an invoice that is Paid, or has had money received against it,
    # must not be moved back to Draft (where the delete route would then remove it with its receipts orphaned) or on to a
    # state that contradicts what the receipts say. The moves a person may make are the three below.
    current = invoice.get("status")
    if body.new_status not in _MANUAL_STATUS_MOVES.get(current, ()):
        raise HTTPException(
            status_code=422,
            detail=(f"An invoice that is {current} cannot be moved to {body.new_status} by hand."
                    if current in _MANUAL_STATUS_MOVES else
                    f"An invoice that is {current} cannot be moved to another status by hand."),
        )
    if int(invoice.get("paid_paise") or 0) > 0 and {current, body.new_status} != _MOVES_THAT_FOLLOW_RECEIPTS_FREELY:
        raise HTTPException(
            status_code=422,
            detail="Money has been received against this invoice, so its status follows its receipts and is not changed by hand.",
        )

    updated = invoice_repo.change_status(invoice_id, body.new_status, firm_id=firm_id, only_from=current)
    if not updated:
        # the invoice changed under this request (a receipt landed, the overdue check ran): say so rather than "success"
        raise HTTPException(status_code=409, detail="The invoice changed while this was being done. Reload it and try again.")
    log_event(firm_id, "invoice", invoice_id, "status_change",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data={"status": invoice.get("status")}, new_data={"status": body.new_status})
    return api_response(True, {"invoice": updated})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/invoices/{invoice_id} — Delete invoice (Draft only)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("billing", "write")),
):
    """
    Delete an invoice. Only Draft invoices can be deleted.

    Raises 400 if invoice is not in Draft status.
    """
    invoice = _assert_invoice_scope(current_user, invoice_id)

    # Only Draft invoices can be deleted
    if invoice.get("status") != "Draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status '{invoice.get('status')}'. Only Draft invoices can be deleted.",
        )
    # A Draft can carry receipts (the receipt function does not ask the status), and deleting it would orphan them.
    if int(invoice.get("paid_paise") or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an invoice that has receipts recorded against it.",
        )

    firm_id = current_user.get("firm_id")
    if not invoice_repo.delete(invoice_id, firm_id=firm_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    # The privileged client carries no sign-in, so the database's own audit trigger records nothing for this write
    # (migration 111 returns early when there is no auth.uid()): the route records it.
    log_event(firm_id, "invoice", invoice_id, "delete",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data={"status": invoice.get("status"), "invoice_no": invoice.get("invoice_no")},
              new_data={"deleted": True})
    return api_response(True, {"deleted": True})

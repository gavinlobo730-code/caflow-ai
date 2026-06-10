"""
Invoice lifecycle automation.

Issued invoices past their due_date transition automatically to Overdue.
Status transitions are one-way here: only Issued -> Overdue. Paid and Draft
invoices are never touched by the automated check.

All monetary values remain in integer paise — no amounts are recomputed here.
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from repositories.invoice_repository import invoice_repo

logger = logging.getLogger("caflow.services")


def run_overdue_check(firm_id: Optional[str] = None) -> dict:
    """
    Find Issued invoices whose due_date has passed and mark them Overdue.

    Invoices without a due_date fall back to invoice_date + 30 days,
    the standard credit period applied at generation time.

    Returns:
        dict with 'transitioned' count and list of affected invoice ids.
    """
    today = date.today()
    issued = invoice_repo.find_all(firm_id=firm_id, status="Issued")

    transitioned: list[str] = []
    for invoice in issued:
        due = _effective_due_date(invoice)
        if due is None:
            continue
        if due < today:
            updated = invoice_repo.change_status(invoice["id"], "Overdue")
            if updated:
                transitioned.append(invoice["id"])
                logger.info(
                    f"Invoice {invoice.get('invoice_no', invoice['id'])} transitioned Issued -> Overdue "
                    f"(due {due.isoformat()})"
                )
                _notify_overdue(invoice)

    return {"transitioned": len(transitioned), "invoice_ids": transitioned}


def _effective_due_date(invoice: dict) -> Optional[date]:
    raw = invoice.get("due_date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    raw_inv_date = invoice.get("invoice_date")
    if not raw_inv_date:
        return None
    try:
        from datetime import timedelta
        return date.fromisoformat(str(raw_inv_date)[:10]) + timedelta(days=30)
    except ValueError:
        return None


def _notify_overdue(invoice: dict) -> None:
    """Notify firm partners that an invoice has become overdue."""
    try:
        from repositories.user_repository import user_repo
        from repositories.notifications_repository import notifications_repo

        firm_id = invoice.get("firm_id")
        partners = user_repo.find_all(firm_id=firm_id, role="Partner")
        for partner in partners[:1]:
            notifications_repo.create({
                "firm_id": firm_id,
                "user_id": partner["id"],
                "type": "invoice_overdue",
                "title": f"Invoice Overdue: {invoice.get('invoice_no', '')}",
                "message": (
                    f"Invoice {invoice.get('invoice_no', '')} "
                    f"(total ₹{invoice.get('total_paise', 0) // 100:,}) is past its due date."
                ),
                "metadata": {
                    "invoice_id": invoice["id"],
                    "client_id": invoice.get("client_id"),
                    "total_paise": invoice.get("total_paise", 0),
                },
            })
    except Exception as e:
        logger.warning(f"Failed to notify overdue invoice {invoice.get('id')}: {e}")

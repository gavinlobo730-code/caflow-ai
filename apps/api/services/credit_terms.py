"""Shared credit-terms resolution — "Net 30"-style due-date defaulting.

Extracted from the sales-invoice logic in routers/sales_invoices.py
(_resolve_credit_terms/_apply_credit_days_due_date/_apply_due_date_credit_days)
so purchase bills can apply the identical rule against a vendor's credit_days
instead of a customer's, without copy-pasting the date arithmetic a second
time. The two draft-edit rules are this module's alone: sales_invoices.py's private names delegate here (POST-A-021, so the copy
whose unparseable date was swallowed in silence is gone).
"""
from datetime import date, timedelta
from typing import Optional

from core.observability import capture_soft_failure

DEFAULT_CREDIT_DAYS = 30  # fallback when neither the document nor the party sets terms


def resolve_credit_terms(
    doc_date: str,
    due_date: Optional[str],
    credit_days: Optional[int],
    party_credit_days: Optional[int],
) -> tuple[Optional[str], Optional[int]]:
    """
    Resolve the credit terms to SNAPSHOT onto a new document (invoice or bill),
    in priority order:
      1. explicit due_date (kept; credit_days derived from the gap when absent)
      2. explicit credit_days override
      3. the party's (customer/vendor) credit_days default
      4. DEFAULT_CREDIT_DAYS
    Returns (due_date_iso, credit_days). Pure; never raises on malformed input.
    Snapshotting here is what makes a saved document immune to later changes to
    the party's Credit Days.
    """
    try:
        doc_d: Optional[date] = date.fromisoformat(str(doc_date)[:10])
    except (ValueError, TypeError):
        doc_d = None

    if due_date:
        cd = credit_days
        if cd is None and doc_d is not None:
            try:
                cd = (date.fromisoformat(str(due_date)[:10]) - doc_d).days
            except (ValueError, TypeError):
                cd = None
        return str(due_date)[:10], (int(cd) if cd is not None else None)

    cd = credit_days
    if cd is None:
        cd = party_credit_days
    if cd is None:
        cd = DEFAULT_CREDIT_DAYS
    cd = max(0, int(cd))
    due = (doc_d + timedelta(days=cd)).isoformat() if doc_d is not None else None
    return due, cd


def apply_credit_days_due_date(data: dict, base_doc_date: Optional[str]) -> None:
    """On a draft edit: when credit_days is set without an explicit due_date,
    recompute due_date from the (new or stored) document date in place, so an
    edited credit period reflects in the stored due date. No-op otherwise."""
    if data.get("credit_days") is None or data.get("due_date"):
        return
    if not base_doc_date:
        return
    try:
        data["due_date"] = (
            date.fromisoformat(str(base_doc_date)[:10])
            + timedelta(days=max(0, int(data["credit_days"])))
        ).isoformat()
    except (ValueError, TypeError) as unreadable:
        # The stored date is a DATE column and the credit days an integer, so this is damage, not a typing slip: the due date is
        # left as it was, and that is said in the log rather than nowhere.
        capture_soft_failure(unreadable, operation="credit_terms.due_date_from_credit_days", base_date=str(base_doc_date)[:40])


def apply_due_date_credit_days(data: dict, base_doc_date: Optional[str]) -> None:
    """Mirror of apply_credit_days_due_date: when due_date is set directly
    without an explicit credit_days, recompute and re-store credit_days as the
    actual day-gap, so the derived "Terms" label (lib/sales/paymentTerms.ts)
    never goes stale relative to the real due date. No-op otherwise."""
    if not data.get("due_date") or data.get("credit_days") is not None:
        return
    if not base_doc_date:
        return
    try:
        data["credit_days"] = (
            date.fromisoformat(str(data["due_date"])[:10])
            - date.fromisoformat(str(base_doc_date)[:10])
        ).days
    except (ValueError, TypeError) as unreadable:
        # As above: the credit days are left as they were, and the log says why.
        capture_soft_failure(unreadable, operation="credit_terms.credit_days_from_due_date", base_date=str(base_doc_date)[:40])

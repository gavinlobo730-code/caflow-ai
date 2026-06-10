"""
Invoice generation service for CA practice management.

GST on CA services: 18% under SAC 998211
SAC 998211 — Professional, technical, consultancy and like services

All monetary calculations in paise (integer), never floating point.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from dateutil.relativedelta import relativedelta

# Standard credit period applied to all generated invoices
CREDIT_PERIOD_DAYS = 30


def _due_date_for(invoice_date: str) -> str:
    """Payment due date = invoice date + standard credit period."""
    d = datetime.fromisoformat(invoice_date[:10])
    return (d + timedelta(days=CREDIT_PERIOD_DAYS)).date().isoformat()


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def generate_invoice_from_engagement(
    engagement_id: str,
    invoice_month: Optional[str] = None,
) -> str:
    """
    Generate a draft invoice from a fixed-fee engagement.

    Args:
        engagement_id: ID of the fee_engagements record
        invoice_month: ISO date string (YYYY-MM-DD) for invoice date. Defaults to today.

    Returns:
        invoice_id (UUID string)

    Process:
        1. Fetch engagement record
        2. Calculate amount_paise from engagement.fee_paise
        3. Calculate GST: gst_paise = amount_paise * 18 / 100 (integer arithmetic)
        4. Calculate total_paise = amount_paise + gst_paise
        5. Generate invoice_no: "{firm_code}-{fiscal_year}-{sequential}"
        6. Set status: 'Draft'
        7. Insert into fee_invoices
        8. Return invoice_id

    Raises:
        NotFoundError: If engagement not found
    """
    from repositories.engagement_repository import engagement_repo
    from repositories.invoice_repository import invoice_repo

    engagement = engagement_repo.get_or_raise(engagement_id)

    if invoice_month is None:
        invoice_month = datetime.now(timezone.utc).isoformat().split('T')[0]

    amount_paise = engagement["fee_paise"]

    # Calculate GST: 18% of base amount (integer paise arithmetic)
    gst_paise = (amount_paise * 18) // 100

    total_paise = amount_paise + gst_paise

    invoice_no = invoice_repo.generate_next_invoice_number(
        firm_id=engagement["firm_id"],
        current_date=invoice_month,
    )

    invoice_data = {
        "firm_id": engagement["firm_id"],
        "client_id": engagement["client_id"],
        "engagement_id": engagement_id,
        "invoice_no": invoice_no,
        "invoice_date": invoice_month,
        "due_date": _due_date_for(invoice_month),
        "amount_paise": amount_paise,
        "gst_paise": gst_paise,
        "total_paise": total_paise,
        "status": "Draft",
    }

    invoice = invoice_repo.create(invoice_data)
    return invoice["id"]


def generate_invoice_from_time_entries(
    engagement_id: str,
    invoice_month: Optional[str] = None,
    billable_only: bool = True,
) -> str:
    """
    Generate a draft invoice from time entries.

    Args:
        engagement_id: ID of the fee_engagements record
        invoice_month: ISO date string (YYYY-MM-DD) for invoice date. Defaults to today.
        billable_only: Only include time_entries with is_billable=True (default True)

    Returns:
        invoice_id (UUID string)

    Process:
        1. Fetch engagement
        2. Query time_entries for engagement in month
        3. Filter by is_billable if requested
        4. Calculate:
            a. total_minutes = sum(duration_minutes)
            b. amount_paise = (total_minutes * hourly_rate_paise) // 60
            c. gst_paise = (amount_paise * 18) // 100
            d. total_paise = amount_paise + gst_paise
        5. Create draft invoice
        6. Return invoice_id

    Raises:
        NotFoundError: If engagement not found
    """
    from repositories.engagement_repository import engagement_repo
    from repositories.invoice_repository import invoice_repo

    engagement = engagement_repo.get_or_raise(engagement_id)

    if invoice_month is None:
        invoice_month = datetime.now(timezone.utc).isoformat().split('T')[0]

    # Parse invoice_month to get year-month for querying
    month_start = datetime.fromisoformat(invoice_month).replace(day=1, tzinfo=timezone.utc)
    month_end = (month_start + relativedelta(months=1)) - relativedelta(days=1)

    db = _get_db()

    # Query time entries for this engagement in the given month
    query = db.table("time_entries").select("*").eq("engagement_id", engagement_id)
    query = query.gte("started_at", month_start.isoformat())
    query = query.lte("started_at", month_end.isoformat())

    if billable_only:
        query = query.eq("is_billable", True)

    result = query.execute()
    time_entries = result.data or []

    # Aggregate time entries
    total_minutes = 0
    hourly_rate_paise = engagement.get("fee_paise", 0)  # fallback rate from engagement

    for entry in time_entries:
        total_minutes += entry.get("duration_minutes", 0)
        # Use entry's rate if available, fallback to engagement rate
        if "hourly_rate_paise" in entry and entry["hourly_rate_paise"]:
            hourly_rate_paise = entry["hourly_rate_paise"]

    # Calculate amount from time: (minutes * hourly_rate) / 60
    # Integer arithmetic: multiply first, then divide
    amount_paise = (total_minutes * hourly_rate_paise) // 60

    # Calculate GST: 18%
    gst_paise = (amount_paise * 18) // 100

    total_paise = amount_paise + gst_paise

    invoice_no = invoice_repo.generate_next_invoice_number(
        firm_id=engagement["firm_id"],
        current_date=invoice_month,
    )

    invoice_data = {
        "firm_id": engagement["firm_id"],
        "client_id": engagement["client_id"],
        "engagement_id": engagement_id,
        "invoice_no": invoice_no,
        "invoice_date": invoice_month,
        "due_date": _due_date_for(invoice_month),
        "amount_paise": amount_paise,
        "gst_paise": gst_paise,
        "total_paise": total_paise,
        "status": "Draft",
    }

    invoice = invoice_repo.create(invoice_data)
    return invoice["id"]


def generate_recurring_invoice(
    engagement_id: str,
    invoice_month: Optional[str] = None,
) -> Optional[str]:
    """
    Generate invoice for a recurring billing engagement.

    Check if last invoice is older than the billing cycle period.
    Only generate if due.

    Args:
        engagement_id: ID of the fee_engagements record
        invoice_month: ISO date string for invoice date. Defaults to today.

    Returns:
        invoice_id (UUID string) or None if not yet due

    Raises:
        NotFoundError: If engagement not found
    """
    from repositories.engagement_repository import engagement_repo
    from repositories.invoice_repository import invoice_repo

    engagement = engagement_repo.get_or_raise(engagement_id)

    if invoice_month is None:
        invoice_month = datetime.now(timezone.utc).isoformat().split('T')[0]

    invoice_date = datetime.fromisoformat(invoice_month).replace(tzinfo=timezone.utc)

    # Get billing cycle
    billing_cycle = engagement.get("billing_cycle", "Monthly")

    # Get last invoice for this engagement
    invoices = invoice_repo.list_for_engagement(engagement_id)
    if not invoices:
        # No invoices yet, generate one
        return generate_invoice_from_engagement(engagement_id, invoice_month)

    # Find most recent invoice
    invoices_sorted = sorted(invoices, key=lambda x: x.get("invoice_date", ""), reverse=True)
    last_invoice = invoices_sorted[0]
    last_invoice_date = datetime.fromisoformat(last_invoice["invoice_date"].replace('Z', '+00:00'))

    # Calculate when next invoice is due
    if billing_cycle == "Monthly":
        next_due_date = last_invoice_date + relativedelta(months=1)
    elif billing_cycle == "Quarterly":
        next_due_date = last_invoice_date + relativedelta(months=3)
    elif billing_cycle == "Annually" or billing_cycle == "Annual":
        next_due_date = last_invoice_date + relativedelta(years=1)
    else:
        # Default to monthly
        next_due_date = last_invoice_date + relativedelta(months=1)

    # Check if due
    if invoice_date < next_due_date:
        # Not yet due
        return None

    # Generate new invoice
    return generate_invoice_from_engagement(engagement_id, invoice_month)

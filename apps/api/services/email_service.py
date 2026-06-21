"""
Email delivery via Resend API.
All transactional emails for task lifecycle, invoice, compliance, and onboarding events.
"""
import os
import logging
from typing import Optional

_logger = logging.getLogger("caflow.email")
_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_FROM_EMAIL = os.environ.get("EMAIL_FROM", "PracticeSync AI <noreply@caflow.ai>")


def _send(to: str, subject: str, html: str) -> bool:
    """Send email via Resend. Returns True on success, False on failure (non-fatal)."""
    if not _RESEND_API_KEY:
        _logger.info("RESEND_API_KEY not set — skipping email to %s: %s", to, subject)
        return False
    try:
        import httpx
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": _FROM_EMAIL, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True
        _logger.warning("Resend returned %s for email to %s", resp.status_code, to)
        return False
    except Exception as e:
        _logger.error("Email send failed to %s: %s", to, e)
        return False


def send_task_assigned(to: str, assignee_name: str, task_title: str, client_name: str, due_date: Optional[str]) -> bool:
    subject = f"New task assigned: {task_title}"
    html = f"""
    <p>Hi {assignee_name},</p>
    <p>A new task has been assigned to you:</p>
    <table cellpadding="8">
      <tr><td><strong>Task</strong></td><td>{task_title}</td></tr>
      <tr><td><strong>Client</strong></td><td>{client_name}</td></tr>
      <tr><td><strong>Due Date</strong></td><td>{due_date or 'Not set'}</td></tr>
    </table>
    <p>Log in to PracticeSync AI to view and manage this task.</p>
    """
    return _send(to, subject, html)


def send_task_overdue(to: str, assignee_name: str, task_title: str, client_name: str, due_date: str) -> bool:
    subject = f"OVERDUE: {task_title}"
    html = f"""
    <p>Hi {assignee_name},</p>
    <p>The following task is <strong>overdue</strong>:</p>
    <table cellpadding="8">
      <tr><td><strong>Task</strong></td><td>{task_title}</td></tr>
      <tr><td><strong>Client</strong></td><td>{client_name}</td></tr>
      <tr><td><strong>Was Due</strong></td><td>{due_date}</td></tr>
    </table>
    <p>Please action this immediately.</p>
    """
    return _send(to, subject, html)


def send_invoice_overdue(to: str, client_name: str, invoice_number: str, amount_str: str, due_date: str) -> bool:
    subject = f"Invoice overdue: {invoice_number} — {client_name}"
    html = f"""
    <p>This is a reminder that the following invoice is overdue:</p>
    <table cellpadding="8">
      <tr><td><strong>Invoice</strong></td><td>{invoice_number}</td></tr>
      <tr><td><strong>Client</strong></td><td>{client_name}</td></tr>
      <tr><td><strong>Amount</strong></td><td>{amount_str}</td></tr>
      <tr><td><strong>Due Date</strong></td><td>{due_date}</td></tr>
    </table>
    <p>Please follow up with the client at your earliest convenience.</p>
    """
    return _send(to, subject, html)


def send_payment_link_to_customer(to: str, customer_name: str, firm_name: str,
                                  invoice_no: str, amount_paise: int, pay_url: str) -> bool:
    """Email a hosted online-payment link to the customer for an outstanding invoice
    (Phase 4.6). Reuses the Resend transport; has NO accounting side effect.
    Amount formatted with integer paise arithmetic (₹ = paise // 100)."""
    amount_str = f"₹{amount_paise // 100:,}.{amount_paise % 100:02d}"
    subject = f"Payment request: Invoice {invoice_no} from {firm_name}"
    html = f"""
    <p>Hi {customer_name or 'there'},</p>
    <p>{firm_name} has requested payment for the following invoice. You can pay securely online:</p>
    <table cellpadding="8">
      <tr><td><strong>Invoice</strong></td><td>{invoice_no}</td></tr>
      <tr><td><strong>Amount Due</strong></td><td>{amount_str}</td></tr>
    </table>
    <p><a href="{pay_url}" style="background:#4f46e5;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;">Pay Now</a></p>
    <p>Or copy this link into your browser: {pay_url}</p>
    """
    return _send(to, subject, html)


def send_compliance_due_soon(to: str, client_name: str, compliance_type: str, due_date: str) -> bool:
    subject = f"Compliance due soon: {compliance_type} — {client_name}"
    html = f"""
    <p>Upcoming compliance deadline:</p>
    <table cellpadding="8">
      <tr><td><strong>Client</strong></td><td>{client_name}</td></tr>
      <tr><td><strong>Type</strong></td><td>{compliance_type}</td></tr>
      <tr><td><strong>Due Date</strong></td><td>{due_date}</td></tr>
    </table>
    <p>Ensure this is filed on time to avoid penalties.</p>
    """
    return _send(to, subject, html)


def send_escalation_alert(to: str, manager_name: str, task_title: str, assignee_name: str, client_name: str) -> bool:
    subject = f"Escalation: {task_title} is overdue"
    html = f"""
    <p>Hi {manager_name},</p>
    <p>A task assigned to your team member requires attention:</p>
    <table cellpadding="8">
      <tr><td><strong>Task</strong></td><td>{task_title}</td></tr>
      <tr><td><strong>Assigned To</strong></td><td>{assignee_name}</td></tr>
      <tr><td><strong>Client</strong></td><td>{client_name}</td></tr>
    </table>
    """
    return _send(to, subject, html)


def send_firm_invite(to: str, firm_name: str, inviter_name: str, role: str, invite_link: str) -> bool:
    subject = f"You've been invited to {firm_name} on PracticeSync AI"
    html = f"""
    <p>Hi,</p>
    <p><strong>{inviter_name}</strong> has invited you to join <strong>{firm_name}</strong> on PracticeSync AI as <strong>{role}</strong>.</p>
    <p><a href="{invite_link}" style="background:#4f46e5;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;">Accept Invitation</a></p>
    <p>This link expires in 7 days.</p>
    """
    return _send(to, subject, html)


# ---------------------------------------------------------------------------
# Phase 2 — Invoice delivery to customers
# ---------------------------------------------------------------------------

def _fmt_rupees(paise: int) -> str:
    """Format integer paise as a display rupee string, e.g. 123456 → ₹1,234.56."""
    return f"₹{paise // 100:,}.{paise % 100:02d}"


def _send_with_attachment(
    to: str,
    subject: str,
    html: str,
    attachment_bytes: bytes,
    attachment_filename: str,
) -> tuple[bool, Optional[str]]:
    """
    Send an email with a binary attachment via Resend.
    Returns (success, provider_message_id).
    """
    import base64
    if not _RESEND_API_KEY:
        _logger.info("RESEND_API_KEY not set — skipping email+attachment to %s: %s", to, subject)
        return False, None
    try:
        import httpx
        payload = {
            "from": _FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
            "attachments": [
                {
                    "filename": attachment_filename,
                    "content": base64.b64encode(attachment_bytes).decode(),
                }
            ],
        }
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {_RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            message_id = resp.json().get("id")
            return True, message_id
        _logger.warning("Resend returned %s for email+attachment to %s", resp.status_code, to)
        return False, None
    except Exception as e:
        _logger.error("Email+attachment send failed to %s: %s", to, e)
        return False, None


def send_invoice_to_customer(
    to: str,
    customer_name: str,
    firm_name: str,
    invoice_no: str,
    invoice_date: str,
    due_date: Optional[str],
    total_paise: int,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> tuple[bool, Optional[str]]:
    """
    Send a GST tax invoice PDF to a customer by email via Resend.
    Returns (success, provider_message_id).
    """
    subject = f"Invoice {invoice_no} from {firm_name}"
    amount_str = _fmt_rupees(total_paise)
    html = f"""
    <p>Dear {customer_name},</p>
    <p>Please find attached Invoice <strong>{invoice_no}</strong>
    from <strong>{firm_name}</strong>.</p>
    <table cellpadding="8">
      <tr><td><strong>Invoice No</strong></td><td>{invoice_no}</td></tr>
      <tr><td><strong>Invoice Date</strong></td><td>{invoice_date}</td></tr>
      <tr><td><strong>Due Date</strong></td><td>{due_date or 'On receipt'}</td></tr>
      <tr><td><strong>Amount</strong></td><td>{amount_str}</td></tr>
    </table>
    <p>If you have any queries regarding this invoice, please contact us.</p>
    <p>Thank you for your business.</p>
    <p>Regards,<br/><strong>{firm_name}</strong></p>
    """
    return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename)


def send_payment_reminder_to_customer(
    to: str,
    customer_name: str,
    firm_name: str,
    invoice_no: str,
    invoice_date: str,
    due_date: Optional[str],
    outstanding_paise: int,
    reminder_number: int,
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Customer-facing overdue payment reminder (Phase 4.2). Tone escalates with the
    reminder number (1 = gentle, 2 = firm, 3+ = final). The original invoice PDF is
    attached when supplied. Returns (success, provider_message_id).

    This is a COLLECTIONS communication only — it posts no journal and changes no
    accounting figure.
    """
    amount_str = _fmt_rupees(max(outstanding_paise, 0))
    if reminder_number <= 1:
        subject = f"Payment reminder: Invoice {invoice_no} from {firm_name}"
        opener = (f"This is a friendly reminder that Invoice <strong>{invoice_no}</strong> "
                  f"is now past its due date.")
    elif reminder_number == 2:
        subject = f"Second reminder: Invoice {invoice_no} is overdue"
        opener = (f"We notice Invoice <strong>{invoice_no}</strong> remains unpaid. "
                  f"Please arrange payment at the earliest.")
    else:
        subject = f"Final reminder: Invoice {invoice_no} overdue"
        opener = (f"This is a final reminder that Invoice <strong>{invoice_no}</strong> "
                  f"is significantly overdue. Please clear the outstanding amount promptly.")
    html = f"""
    <p>Dear {customer_name},</p>
    <p>{opener}</p>
    <table cellpadding="8">
      <tr><td><strong>Invoice No</strong></td><td>{invoice_no}</td></tr>
      <tr><td><strong>Invoice Date</strong></td><td>{invoice_date}</td></tr>
      <tr><td><strong>Due Date</strong></td><td>{due_date or 'On receipt'}</td></tr>
      <tr><td><strong>Amount Outstanding</strong></td><td>{amount_str}</td></tr>
    </table>
    <p>The original invoice is attached for your reference. If payment has already
    been made, please disregard this reminder.</p>
    <p>Regards,<br/><strong>{firm_name}</strong></p>
    """
    if pdf_bytes and pdf_filename:
        return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename)
    return (_send(to, subject, html), None)


def send_statement_to_customer(
    to: str,
    customer_name: str,
    firm_name: str,
    period_start: str,
    period_end: str,
    closing_balance_paise: int,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> tuple[bool, Optional[str]]:
    """
    Email a customer statement of account PDF via Resend (Phase 4.1).
    Returns (success, provider_message_id). Reuses _send_with_attachment.
    """
    subject = f"Statement of Account from {firm_name}"
    html = f"""
    <p>Dear {customer_name},</p>
    <p>Please find attached your statement of account from <strong>{firm_name}</strong>
    for the period <strong>{period_start}</strong> to <strong>{period_end}</strong>.</p>
    <table cellpadding="8">
      <tr><td><strong>Period</strong></td><td>{period_start} to {period_end}</td></tr>
      <tr><td><strong>Closing Outstanding</strong></td><td>{_fmt_rupees(abs(closing_balance_paise))}</td></tr>
    </table>
    <p>This is a statement of account for your reference — not a tax invoice.
    If you have any queries, please contact us.</p>
    <p>Regards,<br/><strong>{firm_name}</strong></p>
    """
    return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename)

"""
Email delivery via Resend API.
All transactional emails for task lifecycle, invoice, compliance, and onboarding events.
"""
import os
import logging
from typing import Optional

_logger = logging.getLogger("caflow.email")
_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_FROM_EMAIL = os.environ.get("EMAIL_FROM", "CAflow AI <noreply@caflow.ai>")


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
    <p>Log in to CAflow AI to view and manage this task.</p>
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
    subject = f"You've been invited to {firm_name} on CAflow AI"
    html = f"""
    <p>Hi,</p>
    <p><strong>{inviter_name}</strong> has invited you to join <strong>{firm_name}</strong> on CAflow AI as <strong>{role}</strong>.</p>
    <p><a href="{invite_link}" style="background:#4f46e5;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;">Accept Invitation</a></p>
    <p>This link expires in 7 days.</p>
    """
    return _send(to, subject, html)

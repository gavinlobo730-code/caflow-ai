"""
Email delivery via Resend API.
All transactional emails for task lifecycle, invoice, compliance, and onboarding events.
"""
import contextvars
import html as _html
import os
import re
import logging
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Callable, Optional

from core.env import env_or_default
from domain.branding import email_template
from domain.money_text import rupees_paise

_logger = logging.getLogger("caflow.email")
_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_FROM_EMAIL = env_or_default("EMAIL_FROM", "PracticeSync AI <noreply@caflow.ai>")


# ── Who a mail is FROM and where a reply GOES (practice_management-04) ────────
#
# Every send path used one sender, `PracticeSync AI <noreply@caflow.ai>`, and no
# path set a Reply-To — so a client answering an engagement letter wrote to an
# address nobody reads. Two things fix that, and they are separate:
#
#   * the DISPLAY NAME says whose mail this is. The ADDRESS stays the verified
#     sending address: a per-firm sending domain with DKIM needs DNS access on
#     each firm's side and is a later step, not something code can do.
#   * the REPLY-TO says where the answer goes.
#
# WHOSE NAME AND WHOSE ADDRESS IS DECIDED BY WHO THE SENDER IS, not by who
# pressed the button. An engagement letter is the PRACTICE writing to its own
# client, so both are the practice's. An invoice, a statement and a payment
# reminder are the practice sending on a CLIENT's behalf to the CLIENT's
# customer (SALES-13): the supplier is the client, the practice is not a party to
# the debt, and a customer who hits Reply on "Invoice INV/001 from Acme Traders"
# and finds a chartered accountant in the To line has been told who their
# supplier's accountant is. Those three take the CLIENT's name and the CLIENT's
# contact address, and where the client has no address on record they set NO
# Reply-To — the status quo — rather than pointing the answer at the wrong party.
# Callers pass both explicitly; this module never decides whose they are.

# Characters that would break or spoof a header: controls, angle brackets and
# quotes (which end the name), backslash, the list separators — and `@`, because a
# display name containing an address ("victim@bank.test <noreply@...>") is shown
# by many mail clients as the sender, which is display-name spoofing. The name is
# typed by practice staff, so this is a backstop and not an accusation.
_UNSAFE_IN_DISPLAY_NAME = re.compile(r'[\x00-\x1f\x7f<>"\\,;@]')
_MAX_DISPLAY_NAME = 78


def _sender_address() -> str:
    """The bare address of EMAIL_FROM — the one thing a display name never changes."""
    address = parseaddr(_FROM_EMAIL)[1]
    return address or _FROM_EMAIL


def from_header(sender_name: Optional[str] = None) -> str:
    """The `from` field: EMAIL_FROM itself, or its address under `sender_name`.

    No name, or one that is empty once made safe, is the configured sender
    exactly as before — a mail is never sent "from" a blank.
    """
    name = re.sub(r"\s+", " ", _UNSAFE_IN_DISPLAY_NAME.sub(" ", sender_name or "")).strip()
    if not name:
        return _FROM_EMAIL
    return f"{name[:_MAX_DISPLAY_NAME].rstrip()} <{_sender_address()}>"


def reply_to_header(address: Optional[str]) -> Optional[str]:
    """One usable address, or None. An unusable one is DROPPED, never sent:
    a malformed Reply-To can make the provider refuse the whole mail."""
    if not address or not str(address).strip():
        return None
    try:
        from email_validator import validate_email
        checked = validate_email(str(address).strip(), check_deliverability=False)
        return getattr(checked, "normalized", None) or getattr(checked, "email", None)
    except Exception:                                           # noqa: BLE001
        return None


def _envelope(to: str, subject: str, html: str,
              sender_name: Optional[str], reply_to: Optional[str]) -> dict:
    """The Resend JSON shared by both transports, so a header added to one
    cannot be missing from the other."""
    payload: dict = {"from": from_header(sender_name), "to": [to],
                     "subject": subject, "html": html}
    cleaned = reply_to_header(reply_to)
    if cleaned:
        payload["reply_to"] = cleaned
    return payload

# Single, non-technical message shown to end users for ANY email-delivery failure.
# The true cause (missing/invalid API key, unverified sending domain, provider
# rejection, network error) is captured in the SERVER LOG only — never expose the
# env var name, the provider, the response body, or a stack trace to the user.
GENERIC_SEND_FAILURE_MESSAGE = (
    "We couldn't send the email right now. "
    "Please try again later or contact your administrator."
)


def _log_provider_error(resp, to: str, subject: str) -> None:
    """
    Record the FULL provider error — HTTP status, error code/name, and the raw
    response body — plus request context, to the server log. This is what lets an
    administrator distinguish a missing/invalid API key from an unverified sending
    domain or a bad recipient. It must NEVER be returned to the client.
    """
    try:
        body_text = resp.text or ""
    except Exception:
        body_text = ""
    error_code = error_name = None
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            # Resend error shape: {"statusCode": <int>, "name": "...", "message": "..."}
            error_name = payload.get("name")
            error_code = payload.get("statusCode") or payload.get("code")
    except Exception:
        pass
    _logger.error(
        "Resend rejected email: http_status=%s error_code=%s error_name=%s "
        "to=%s subject=%r body=%s",
        getattr(resp, "status_code", "?"), error_code, error_name,
        to, subject, body_text[:1000],
    )


# ── The outbox seam (ops-21) ──────────────────────────────────────────────────
#
# `deliver` (services/practice_mail_service) is the ONE door for the practice's own
# mail, and every mail it sends calls `_send` below from inside a callback. The
# door puts the mail on a QUEUE instead of posting it from the request thread by
# setting this context variable around that callback: `_send` then hands the
# message to the sink and returns True, meaning "accepted for delivery", which is
# what a True from the provider meant to the caller anyway. Nothing else sets
# it, so every other path (an invoice, a statement, an invite - mail whose sender
# reports delivery to the person who pressed the button) posts synchronously exactly
# as it always did. A ContextVar and not a parameter: eleven senders and their
# callers would each have had to learn a flag, and a flag one of them forgot is a
# mail that bypasses the queue - which is the PRACTICE_MAIL_ENABLED bypass the
# queue must not become.
_OUTBOX_SINK: "contextvars.ContextVar[Optional[Callable[..., bool]]]" = contextvars.ContextVar(
    "email_outbox_sink", default=None)


@dataclass(frozen=True)
class SendOutcome:
    """What one POST to the provider came to, in the terms a retry policy needs.

    `retryable` is the whole point of it: a 5xx, a 429, a timeout and a refused
    connection are the provider's or the network's bad moment and the same message
    will go on a later attempt; a 400 or 422 says the MESSAGE is wrong and will
    never go; and 401/403 say the KEY or the sending domain is wrong, which a person
    fixes in a dashboard, so those wait and retry as well."""
    ok: bool
    retryable: bool = False
    status_code: Optional[int] = None
    message_id: Optional[str] = None
    code: Optional[str] = None


#: HTTP statuses a later attempt can fix besides every 5xx: timeouts and rate limits,
#: and the two that mean "our credentials or sending domain are not accepted yet".
_RETRYABLE_STATUSES = frozenset({401, 403, 408, 409, 425, 429})


def _retryable_status(status: int) -> bool:
    return status >= 500 or status in _RETRYABLE_STATUSES


def _short_code(value: object, fallback: str) -> str:
    """A provider's error NAME or an exception's class name, cut to a storable label.
    Never the message: a provider message can quote the recipient's address."""
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:60].strip("_")
    return text or fallback


def _error_code(resp) -> str:
    try:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("name"):
            return _short_code(payload["name"], f"http_{resp.status_code}")
    except Exception:                                           # noqa: BLE001
        # No readable error body: the HTTP status below is the answer. Said at DEBUG, not swallowed.
        _logger.debug("the provider's error body could not be read", exc_info=True)
    return f"http_{getattr(resp, 'status_code', 'unknown')}"


def _message_id(resp) -> Optional[str]:
    try:
        payload = resp.json()
        got = payload.get("id") if isinstance(payload, dict) else None
        return str(got) if got else None
    except Exception:                                           # noqa: BLE001
        return None


def transport(to: str, subject: str, html: str, *,
              sender_name: Optional[str] = None,
              reply_to: Optional[str] = None,
              idempotency_key: Optional[str] = None) -> SendOutcome:
    """POST one message to Resend and say what came of it. Never raises.

    `idempotency_key` is the outbox row's id. A retry after an AMBIGUOUS failure - the
    request timed out after the provider had accepted it - would otherwise send the
    message twice; Resend honours an `Idempotency-Key` header for 24 hours and answers
    the repeat with the first result. `[S]`-graded: recalled from the provider's
    documentation, egress being refused here, and harmless if it is ignored (the
    worst case is the duplicate the header exists to prevent)."""
    if not _RESEND_API_KEY:
        _logger.warning(
            "Email NOT sent — provider not configured (RESEND_API_KEY missing). "
            "to=%s subject=%r", to, subject,
        )
        return SendOutcome(False, retryable=True, code="not_configured")
    headers = {"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        import httpx
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers=headers,
            json=_envelope(to, subject, html, sender_name, reply_to),
            timeout=10,
        )
    except Exception as e:
        _logger.error("Email transport error to %s (subject=%r): %s: %s",
                      to, subject, type(e).__name__, e)
        return SendOutcome(False, retryable=True,
                           code=_short_code(type(e).__name__, "transport_error"))
    if resp.status_code in (200, 201):
        return SendOutcome(True, status_code=resp.status_code, message_id=_message_id(resp))
    _log_provider_error(resp, to, subject)
    return SendOutcome(False, retryable=_retryable_status(resp.status_code),
                       status_code=resp.status_code, code=_error_code(resp))


def _send(to: str, subject: str, html: str, *,
          sender_name: Optional[str] = None,
          reply_to: Optional[str] = None) -> bool:
    """
    Send email via Resend. Returns True on success, False on failure (non-fatal).

    Every failure is logged in full server-side; callers must surface only a
    generic, non-technical message to end users (see GENERIC_SEND_FAILURE_MESSAGE).

    `sender_name` and `reply_to` are optional and default to the configured
    sender with no Reply-To, which is what every internal notification (task
    assigned, escalation, firm invite) still sends.

    INSIDE `practice_mail_service.deliver` the message is QUEUED instead of posted
    (see the note on `_OUTBOX_SINK`): True then means "accepted for delivery", and
    the retry, the final failure and the bounce are the outbox's.
    """
    if not _RESEND_API_KEY:
        _logger.warning(
            "Email NOT sent — provider not configured (RESEND_API_KEY missing). "
            "to=%s subject=%r", to, subject,
        )
        return False
    sink = _OUTBOX_SINK.get()
    if sink is not None:
        return bool(sink(to, subject, html, sender_name, reply_to))
    return transport(to, subject, html, sender_name=sender_name, reply_to=reply_to).ok


# ── The firm's own wording, where it has written one (SALES-13) ──────────────
#
# `public.email_templates` (migration 126) has held one active template per
# kind per firm since the module was built, written by a full Settings screen,
# and THIS FILE MENTIONED NO TEMPLATE AT ALL — every subject and body below is
# a hard-coded f-string. So a CA who rewrote the engagement email in their own
# words saved it and watched the product send the stock one.
#
# `domain/branding/email_template.py` is the authority for the merge fields,
# for which kinds have a live mail at all, and for what a render refuses.

def _firm_wording(kind: str, firm_id: Optional[str],
                  values: dict) -> Optional[tuple[str, str]]:
    """(subject, html) from the firm's own template, or None.

    NONE MEANS SEND THE BUILT-IN, and every path here returns it: no firm_id,
    no template saved, a read that failed, or a placeholder this particular
    mail has no value for. Half-applying a template is the one outcome nobody
    wants — the client would see the CA's sentence with a gap in it, and the
    stock wording is merely impersonal rather than wrong.
    """
    if not firm_id:
        return None
    try:
        from repositories.branding_repository import branding_repo
        row = branding_repo.get_active_email_template(firm_id, kind)
    except Exception:                       # noqa: BLE001 — see the docstring
        _logger.warning("caflow.email: could not read the %s template for "
                        "firm %s; sending the built-in wording", kind, firm_id)
        return None
    if not row:
        return None
    subject = email_template.render(row.get("subject"), values)
    body = email_template.render(row.get("body"), values)
    if not subject or not body:
        _logger.info("caflow.email: the firm's %s template uses a merge field "
                     "this mail has no value for; sending the built-in wording",
                     kind)
        return None
    return subject, email_template.as_html(body)


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
    amount_str = f"₹{rupees_paise(amount_paise)}"
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


# ── The practice's own notices that are not one task or one obligation ───────
#
# Everything below ESCAPES what it interpolates: a client's name, a task's title
# and a portal message's sender are all typed by somebody, and a mail body is
# HTML. The four older notices above interpolate raw and are left as they were —
# `test_internal_notifications_are_unchanged` pins their exact wire shape.

def _esc(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _oneline(value: object) -> str:
    """A value fit for a SUBJECT: one line, no control characters. The subject
    is a JSON field to the provider, so this is hygiene, not an injection fix."""
    return re.sub(r"[\x00-\x1f\x7f\s]+", " ", str(value if value is not None else "")).strip()


def send_attention_digest(to: str, recipient_name: str, subject: str, intro: str,
                          groups: list[tuple[str, list[str]]],
                          link: Optional[str] = None) -> bool:
    """ONE mail listing everything that needs a person's attention after a sweep.

    A practice with sixty clients has sixty GSTR-3Bs due on the 20th, and the
    7-day tier reaches all of them on the 13th — sixty mails to the preparer is
    how a deadline reminder gets a filter rule. So the sweeps send one mail per
    recipient and the single-item functions above are used only where there is
    exactly one thing to say.

    `groups` is `[(heading, [line, ...]), ...]`; nothing here knows what a line
    means. Internal mail: the product's own sender, no Reply-To, like every
    other staff notice.
    """
    body = "".join(
        f"<p><strong>{_esc(heading)}</strong></p><ul>"
        + "".join(f"<li>{_esc(line)}</li>" for line in lines)
        + "</ul>"
        for heading, lines in groups if lines
    )
    open_link = (f'<p><a href="{_esc(link)}">Open PracticeSync AI</a></p>'
                 if link else "<p>Log in to PracticeSync AI to action these.</p>")
    html = f"<p>Hi {_esc(recipient_name or 'there')},</p><p>{_esc(intro)}</p>{body}{open_link}"
    return _send(to, _oneline(subject), html)


def send_client_wrote_to_staff(to: str, recipient_name: str, client_name: str,
                               link: str) -> bool:
    """A client posted a message on the portal. The BODY is not in the mail: a
    message is the client's own business, mail is not a secure channel, and the
    in-app notification inside the authenticated app is where the words are."""
    subject = _oneline(f"New portal message from {client_name}")
    html = (f"<p>Hi {_esc(recipient_name or 'there')},</p>"
            f"<p><strong>{_esc(client_name)}</strong> sent you a message on the client portal.</p>"
            f'<p><a href="{_esc(link)}">Read it in PracticeSync AI</a></p>')
    return _send(to, subject, html)


def send_document_request_notice(
    to: str,
    contact_name: str,
    firm_name: str,
    request_title: str,
    is_urgent: bool,
    due_date: Optional[str],
    login_url: str,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Tell a client's portal contact their accountant has asked for something.

    THE PRACTICE IS THE SENDER (practice_management-04): this is the practice
    writing to its own client, so the From name is the practice's and a reply
    reaches it. It is NOT an invoice-type mail and names no client's customer.

    The wording says where to SEE the request and never offers to upload against
    it: the portal's document upload is deliberately not built
    (routers/portal_data.portal_document_requests), and a mail promising a
    button that is not there is worse than no mail.

    Built-in wording only — the firm's own `document_request` template is NOT
    applied (see domain/branding/email_template.KIND_NOT_LIVE_REASON).
    """
    urgent = "<p><strong>This request is marked urgent.</strong></p>" if is_urgent else ""
    needed = (f"<tr><td><strong>Needed by</strong></td><td>{_esc(due_date)}</td></tr>"
              if due_date else "")
    subject = _oneline(
        f"{'Urgent: ' if is_urgent else ''}{firm_name} has asked you for: {request_title}")
    html = (f"<p>Dear {_esc(contact_name or 'Client')},</p>"
            f"<p><strong>{_esc(firm_name)}</strong> has asked you for a document.</p>"
            f"{urgent}"
            f'<table cellpadding="8"><tr><td><strong>Request</strong></td>'
            f"<td>{_esc(request_title)}</td></tr>{needed}</table>"
            f'<p><a href="{_esc(login_url)}">Sign in to your portal</a> to see the details, '
            f"or reply to this email.</p>")
    return _send(to, subject, html, sender_name=sender_name, reply_to=reply_to)


def send_portal_message_notice(
    to: str,
    contact_name: str,
    firm_name: str,
    login_url: str,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Tell a client's portal contact their accountant has written to them.
    The message itself stays on the portal — see `send_client_wrote_to_staff`."""
    subject = _oneline(f"New message from {firm_name}")
    html = (f"<p>Dear {_esc(contact_name or 'Client')},</p>"
            f"<p><strong>{_esc(firm_name)}</strong> sent you a message on your client portal.</p>"
            f'<p><a href="{_esc(login_url)}">Sign in to read it</a>, or reply to this email.</p>')
    return _send(to, subject, html, sender_name=sender_name, reply_to=reply_to)


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
    return f"₹{rupees_paise(paise)}"


def _send_with_attachment(
    to: str,
    subject: str,
    html: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Send an email with a binary attachment via Resend.
    Returns (success, provider_message_id).
    """
    import base64
    if not _RESEND_API_KEY:
        _logger.warning(
            "Email+attachment NOT sent — provider not configured (RESEND_API_KEY "
            "missing). to=%s subject=%r", to, subject,
        )
        return False, None
    try:
        import httpx
        payload = _envelope(to, subject, html, sender_name, reply_to)
        payload["attachments"] = [
            {
                "filename": attachment_filename,
                "content": base64.b64encode(attachment_bytes).decode(),
            }
        ]
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
        _log_provider_error(resp, to, subject)
        return False, None
    except Exception as e:
        _logger.error("Email+attachment transport error to %s (subject=%r): %s: %s",
                      to, subject, type(e).__name__, e)
        return False, None


def send_invoice_to_customer(
    to: str,
    customer_name: str,
    # WHOSE INVOICE THIS IS — the CA firm's CLIENT, not the practice. The
    # parameter keeps its old name so every caller and test still works; what
    # changed is who the caller passes, and the two callers were passing the
    # PRACTICE (no finding; found building SALES-13).
    #
    # `build_sales_invoice_pdf` has refused the practice's branding on this
    # document since it was written, and `send_statement_to_customer` right
    # below carries the same note in its own words — the EMAIL that carries
    # that PDF was the one place left saying "Invoice INV/001 from Sharma &
    # Co" and "Regards, Sharma & Co" to a stranger who bought goods from Acme
    # Traders. It misstates who supplied and who is owed, and it discloses the
    # client's accountant to their customer.
    firm_name: str,
    invoice_no: str,
    invoice_date: str,
    due_date: Optional[str],
    total_paise: int,
    pdf_bytes: bytes,
    pdf_filename: str,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Send a GST tax invoice PDF to a customer by email via Resend.
    Returns (success, provider_message_id).

    NO FIRM TEMPLATE, DELIBERATELY. `email_templates` is the PRACTICE's, and
    this mail goes from the client to the client's customer — the same boundary
    `build_sales_invoice_pdf` holds for `branding` and `layout`. A client
    wanting their own wording needs their own store, which is a migration.

    `sender_name` and `reply_to` are the CLIENT's (the supplier's) display name
    and contact address, for the same reason: a customer replying to this mail
    is asking the SUPPLIER about the invoice. Pass neither where the client has
    no name or address on record — the mail then goes exactly as it always has,
    and never under the practice's.
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
    return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename,
                                 sender_name=sender_name, reply_to=reply_to)


def send_payment_reminder_to_customer(
    to: str,
    customer_name: str,
    #: WHOSE INVOICE IS OVERDUE — the CA firm's CLIENT. See the note on
    #: send_invoice_to_customer above; this mail had the same defect and it is
    #: worse here, because a reminder demands payment and naming the practice
    #: misstates who is owed.
    firm_name: str,
    invoice_no: str,
    invoice_date: str,
    due_date: Optional[str],
    outstanding_paise: int,
    reminder_number: int,
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Customer-facing overdue payment reminder (Phase 4.2). Tone escalates with the
    reminder number (1 = gentle, 2 = firm, 3+ = final). The original invoice PDF is
    attached when supplied. Returns (success, provider_message_id).

    This is a COLLECTIONS communication only — it posts no journal and changes no
    accounting figure.

    NO FIRM TEMPLATE, for the same reason as the invoice mail above — and
    `sender_name` / `reply_to` are the CLIENT's, for the same reason too.
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
        return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename,
                                     sender_name=sender_name, reply_to=reply_to)
    return (_send(to, subject, html, sender_name=sender_name, reply_to=reply_to), None)


def send_engagement_letter(
    to: str,
    recipient_name: str,
    firm_name: str,
    engagement_number: str,
    title: str,
    letter_html: str,
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
    sign_url: Optional[str] = None,
    firm_id: Optional[str] = None,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Email an engagement letter to the prospective client.

    `sender_name` and `reply_to` are the PRACTICE's display name and contact
    address (practice_management-04): the practice is the sender here, so a
    client who answers the letter writes to the firm and not to a no-reply
    address. Both are optional — without them the mail goes from the configured
    sender with no Reply-To, which is what it always did.

    The rendered letter is shown inline in the email body; when a PDF is supplied
    it is also attached for the client's records (CGST Act Section 31 — written
    engagement record). When sign_url is supplied, a prominent "Review & Sign
    Online" button lets the recipient accept the letter electronically without an
    account. Returns (success, provider_message_id).

    This is a CLIENT communication only — it is NOT a government-portal
    submission and has no accounting side effect.

    THE PRACTICE IS THE SENDER HERE, which is what makes the firm's own
    `email_templates` wording apply (SALES-13). It is the only one of the four
    kinds that has a live mail AND a practice on the sending end — the
    customer-facing invoice and reminder below go from the CLIENT to the
    client's customer, and the firm's wording must never reach those.

    `firm_id` is optional so every existing caller keeps working; without it
    the built-in wording is used, which is what the product has always sent.
    """
    subject = f"Engagement Letter {engagement_number} from {firm_name}"
    accept_instruction = (
        "To accept this engagement, click the button below to review and sign online."
        if sign_url else
        "To accept this engagement, please sign and return a copy to us."
    )
    sign_button = f"""
    <p style="text-align:center;margin:22px 0;">
      <a href="{sign_url}" style="background:#4f46e5;color:#ffffff;padding:12px 28px;
         text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;">
        Review &amp; Sign Online
      </a>
    </p>
    <p style="color:#64748b;font-size:13px;">Or paste this link into your browser:<br/>{sign_url}</p>
    """ if sign_url else ""
    intro = f"""
    <p>Dear {recipient_name or 'Client'},</p>
    <p>Please find below our engagement letter
    (<strong>{engagement_number}</strong>) from <strong>{firm_name}</strong>
    regarding <strong>{title}</strong>.{
        ' A PDF copy is attached for your records.' if pdf_bytes else ''
    }</p>
    <p>{accept_instruction}</p>
    {sign_button}
    <hr/>
    """
    closing = f"""
    <hr/>
    <p style="color:#64748b;font-size:13px;">This engagement letter was sent via
    PracticeSync on behalf of {firm_name}. If you have any questions, simply
    reply to this email.</p>
    """
    html = intro + (letter_html or "") + closing

    # The firm's own wording replaces the SUBJECT and the INTRO. The letter
    # itself and the closing stay: the letter is the document being sent, and
    # the closing is the disclosure that the mail came through this product on
    # the firm's behalf — neither is wording a template is choosing.
    override = _firm_wording("engagement", firm_id, {
        "firm_name": firm_name,
        "client_name": recipient_name or "Client",
        "portal_link": sign_url,
    })
    if override:
        subject, intro_html = override
        html = intro_html + "<hr/>" + (letter_html or "") + closing

    if pdf_bytes and pdf_filename:
        return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename,
                                     sender_name=sender_name, reply_to=reply_to)
    return (_send(to, subject, html, sender_name=sender_name, reply_to=reply_to), None)


def send_statement_to_customer(
    to: str,
    customer_name: str,
    # The name of WHOSE ACCOUNT this is — the CA firm's CLIENT, not the
    # practice. The parameter keeps its name because every caller and test
    # already uses it; what changed is who the caller passes. A statement
    # demanding payment under a chartered accountant's name misstates who is
    # owed, and the practice is not a party to the debt.
    firm_name: str,
    period_start: str,
    period_end: str,
    closing_balance_paise: int,
    pdf_bytes: bytes,
    pdf_filename: str,
    *,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Email a customer statement of account PDF via Resend (Phase 4.1).
    Returns (success, provider_message_id). Reuses _send_with_attachment.

    `sender_name` / `reply_to` are the CLIENT's, as on the invoice mail: the
    customer owes the client, and a question about the statement is the
    client's to answer.
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
    return _send_with_attachment(to, subject, html, pdf_bytes, pdf_filename,
                                 sender_name=sender_name, reply_to=reply_to)

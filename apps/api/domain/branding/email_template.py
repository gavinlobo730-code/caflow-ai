"""The firm's own email templates, and which merge fields each kind can fill
(SALES-13).

WHAT WAS WRONG

    `public.email_templates` (migration 126) has held one active template per
    kind per firm — `invoice`, `engagement`, `document_request`, `reminder`,
    each with a subject and a body carrying `{{merge_field}}` placeholders —
    and a full Settings screen has written it since the module was built.

    `services/email_service.py` contained **no reference to a template at
    all**. Every subject and every body is a hard-coded f-string, so a CA who
    rewrote the invoice email in their own words, in their own language, saved
    it and watched the product send the stock one. `routers/branding.py:361`
    served the rows to the screen that wrote them and to nothing else.

WHY THE VOCABULARY IS PER KIND, WHICH IS THE PART THAT IS EASY TO GET WRONG

    A document-request mail has no invoice number. A blanket list of seven
    fields would let a CA type `{{invoice_amount}}` into it, save it, and send
    a customer a sentence with a hole where an amount should be — or, worse, a
    literal `{{invoice_amount}}`, which is how a template system tells your
    client you are using one.

    So **a merge field the mail cannot fill is REFUSED WHERE IT IS TYPED**, by
    `unfillable_fields`, which the write door asks and the Settings screen
    renders. Nothing is blanked at send time, because by then there is no
    human to tell.

WHAT RENDERING REFUSES

    `render` returns None when a value is missing for a field the template
    uses, and the caller falls back to its own built-in body. A mail with a
    hole in it is worse than a mail in the stock wording: the stock wording is
    correct and merely impersonal, and the hole is visible to the client.

    An UNKNOWN placeholder cannot reach here — the write door refuses it — and
    if one does (a row written before this module, a vocabulary since
    narrowed) it is treated the same way: no render, stock body, logged.

THE BODY IS PLAIN TEXT AND THE MAIL IS HTML

    Every default the Settings screen ships is plain text with blank lines
    between paragraphs, so `as_html` escapes it and turns newlines into
    breaks. Escaping matters in both directions: a CA writing "Fees & taxes"
    must not produce broken markup, and a body is not a place to author HTML
    through a textarea.
"""
from __future__ import annotations

import html as _html
import re
from typing import Optional

#: Migration 126's own CHECK vocabulary.
TEMPLATE_KINDS = ("invoice", "engagement", "document_request", "reminder")

#: Every merge field the product knows, with the label the Settings screen
#: shows. The BROWSER used to hold this list alone; it is served now, the
#: Schedule III caption lesson.
MERGE_FIELDS: dict[str, str] = {
    "firm_name": "Firm Name",
    "client_name": "Client Name",
    "invoice_number": "Invoice #",
    "invoice_amount": "Invoice Amount",
    "due_date": "Due Date",
    "financial_year": "Financial Year",
    "portal_link": "Portal Link",
}

#: WHICH FIELDS A KIND CAN ACTUALLY FILL, **MEASURED AT THE SENDER**.
#:
#: Only the LIVE kinds appear. `engagement` is measured off
#: `routers/engagement_letters._deliver_engagement_email`, which holds the firm
#: name, the recipient's name and the signing URL — and NOT a financial year,
#: because `public.engagements` (migration 115) has no such column. Guessing
#: one from the clock would put a year on a letter nobody stated.
#:
#: A kind's set is the CONTRACT its sender must honour. A sender that stops
#: supplying one of these breaks the template silently, so a test asserts the
#: sender passes every field its kind promises.
#:
#: THE THREE KINDS WITH NO LIVE MAIL ARE ABSENT, DELIBERATELY. Their contract
#: cannot be measured — there is no call site to measure it at — and asserting
#: one would refuse the very defaults the Settings screen ships. For those the
#: write door checks the field is REAL and says the kind is not applied yet;
#: it does not claim to know what a mail nobody sends would hold.
FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    "engagement": frozenset({"firm_name", "client_name", "portal_link"}),
}

#: WHETHER A KIND HAS A MAIL TO APPLY TO, AND WHY NOT WHERE IT HAS NOT.
#:
#: MEASURED against `services/email_service.py` and its callers on 18-09-2026,
#: not assumed from the four names. The Settings screen offers the four as
#: equals; they are not, and a CA rewriting a template that will never be sent
#: is writing into a void. The three reasons are DIFFERENT and a test says so —
#: one kind has no mail at all, one has a mail nothing calls, and one's only
#: mail is sent on the CLIENT's behalf and must never carry the practice's
#: wording.
KIND_IS_LIVE: dict[str, bool] = {
    "engagement": True,
    "invoice": False,
    "reminder": False,
    "document_request": False,
}

KIND_NOT_LIVE_REASON: dict[str, str] = {
    "invoice": (
        "Not applied yet. This wording is for the practice's own fee invoice, "
        "and there is no path that emails one — `/api/invoices/{id}/pdf` "
        "downloads it and nothing sends it. (The 'Send' button on a CLIENT's "
        "sales invoice is a different mail: that one goes from your client to "
        "their customer and carries your client's name, not yours.)"
    ),
    "reminder": (
        "Not applied yet. The compliance reminder this wording is for "
        "(`send_compliance_due_soon`) is written and has no caller, so nothing "
        "sends it. The payment reminders that ARE sent go from your client to "
        "their customer about your client's own sales invoice, and they carry "
        "your client's name rather than the practice's."
    ),
    "document_request": (
        "Not applied yet. Creating a document request records it on the client "
        "portal and sends no mail, so there is nothing for this wording to be "
        "used in."
    ),
}


def kind_status(kind: str) -> dict:
    """Whether a template of this kind will actually be sent, and why not.

    Served beside the templates so the Settings screen can say it where the
    CA is writing. The alternative — four kinds offered as equals, three of
    them inert — is the `BrowserOnlyNotice` shape this repository has already
    had to delete once.
    """
    live = KIND_IS_LIVE.get(kind, False)
    return {
        "kind": kind,
        "is_applied": live,
        "reason": None if live else KIND_NOT_LIVE_REASON.get(
            kind, "Not applied yet."),
    }


_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def placeholders_in(text: Optional[str]) -> list[str]:
    """Every `{{field}}` the text uses, in order, without duplicates."""
    seen: list[str] = []
    for name in _PLACEHOLDER.findall(text or ""):
        if name not in seen:
            seen.append(name)
    return seen


def unknown_fields(subject: Optional[str], body: Optional[str]) -> list[str]:
    """Placeholders naming no merge field this product has."""
    used = placeholders_in(subject) + placeholders_in(body)
    return [f for f in dict.fromkeys(used) if f not in MERGE_FIELDS]


def unfillable_fields(kind: str, subject: Optional[str],
                      body: Optional[str]) -> list[str]:
    """Known merge fields this KIND of mail cannot supply a value for.

    Separate from `unknown_fields` and the two are not interchangeable: an
    unknown field is a typo, and an unfillable one is a real field in the
    wrong template. The sentences a CA needs are different.

    EMPTY for a kind with no live mail — see FIELDS_BY_KIND. There is nothing
    to be unfilled by a mail nobody sends, and refusing on a contract nobody
    has measured is a guess wearing a validator's clothes.
    """
    allowed = FIELDS_BY_KIND.get(kind)
    if allowed is None:
        return []
    used = dict.fromkeys(placeholders_in(subject) + placeholders_in(body))
    return [f for f in used if f in MERGE_FIELDS and f not in allowed]


def problem_with(kind: str, subject: Optional[str],
                 body: Optional[str]) -> Optional[str]:
    """One sentence for the write door, or None.

    Shaped like `gstin.problem_with` deliberately — one shape for "what is
    wrong with this thing somebody typed".
    """
    if kind not in TEMPLATE_KINDS:
        return (f"template_type must be one of {', '.join(TEMPLATE_KINDS)}.")
    if not (subject or "").strip():
        return "The subject is required — a mail with no subject line is spam."
    if not (body or "").strip():
        return "The body is required."
    unknown = unknown_fields(subject, body)
    if unknown:
        return (
            f"{', '.join('{{' + f + '}}' for f in unknown)} is not a merge "
            f"field. The fields available are "
            f"{', '.join('{{' + f + '}}' for f in MERGE_FIELDS)}.")
    unfillable = unfillable_fields(kind, subject, body)
    if unfillable:
        return (
            f"{', '.join('{{' + f + '}}' for f in unfillable)} cannot be "
            f"filled in on a '{kind}' mail — there is no such value to put "
            f"there, so it would reach your client empty. This kind can use "
            f"{', '.join('{{' + f + '}}' for f in sorted(FIELDS_BY_KIND[kind]))}.")
    return None


def render(text: Optional[str], values: dict) -> Optional[str]:
    """Substitute every placeholder, or REFUSE.

    None where the text uses a field `values` has no non-empty answer for, or
    one this product does not know — the caller then sends its own built-in
    wording. Half-applying a template is the one outcome nobody wants: the
    client sees the CA's sentence with a gap in it.
    """
    if not text:
        return None
    for name in placeholders_in(text):
        if name not in MERGE_FIELDS:
            return None
        if not str(values.get(name) or "").strip():
            return None
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def as_html(body: str) -> str:
    """A plain-text body as the mail's HTML.

    Escaped — a CA writing "Fees & taxes" must not produce broken markup, and
    a textarea in Settings is not a place to author HTML.
    """
    return _html.escape(body).replace("\n", "<br/>")


def merge_field_vocabulary() -> dict:
    """What `GET /api/settings/email-templates/merge-fields` serves.

    The browser held this list and the backend did not, which is how it came
    to offer a field for a kind that cannot fill it.
    """
    return {
        "fields": [{"field": f"{{{{{name}}}}}", "name": name, "label": label}
                   for name, label in MERGE_FIELDS.items()],
        # Only the live kinds carry a measured field list; a kind absent from
        # this map is one whose mail does not exist — `status_by_kind` says so
        # and says why, which is the answer a screen needs.
        "by_kind": {kind: sorted(fields)
                    for kind, fields in FIELDS_BY_KIND.items()},
        "kinds": list(TEMPLATE_KINDS),
        "status_by_kind": {kind: kind_status(kind) for kind in TEMPLATE_KINDS},
    }

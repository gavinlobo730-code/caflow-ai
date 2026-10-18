"""The practice's own mail wording: what each live kind can say, and that the screen offers no more
(POST-A-098, POST-A-102; SALES-13).

WHAT WAS WRONG
    * The engagement letter was the only mail whose wording the practice could change, and its wording
      could not name the engagement: `{{engagement_number}}` and `{{engagement_title}}` were not merge
      fields, although the sender holds both, so a CA who wanted "Engagement letter EL-2026-014 (GST
      return filing)" in the subject could not write it.
    * The document request, the other mail a practice sends in its own name to its own client, went out
      in the product's wording only, and its `document_request` template sat saved and unused. The
      reason on record was that the shipped default promised an upload the portal cannot take and named
      a financial year a request does not hold. Both are fixed in the default, the contract is measured
      off the sender, and the template is applied.
    * The Settings screen offered every merge field on every tab and let the server refuse the one a mail
      cannot fill; it now offers the fields the sender can fill, as the server measured them.

The rule that the browser's list of merge fields is the server's, and that a shipped default is one the
server accepts, is asserted from this side: a guard in `apps/web` would assert the screen against a copy
of itself.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from domain.branding import email_template as et
from services import email_service as es

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
PAGE = (WEB / "app" / "settings" / "email-templates" / "page.tsx")


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _merge_fields_on_the_screen() -> list[tuple[str, str]]:
    block = _page()
    block = block[block.index("const MERGE_FIELDS = ["):]
    block = block[:block.index("];")]
    return re.findall(r'\{ field: "\{\{(\w+)\}\}", label: "([^"]+)" \}', block)


def _shipped_default(kind: str) -> tuple[str, str]:
    src = _page()
    start = src.index(f'  {kind}: {{\n    template_type: "{kind}"')
    end = src.index("    is_active: true,", start)
    block = src[start:end]
    subject = re.search(r'subject: "([^"]*)"', block).group(1)
    body = re.search(r"body: `([^`]*)`", block, re.S).group(1)
    return subject, body


# ── the vocabulary ───────────────────────────────────────────────────────────

def test_the_engagement_letter_can_name_the_engagement():
    assert {"engagement_number", "engagement_title"} <= et.FIELDS_BY_KIND["engagement"]
    assert et.problem_with("engagement", "Letter {{engagement_number}}", "For {{engagement_title}}") is None


def test_a_field_belongs_to_the_mail_that_holds_it():
    """`{{request_title}}` is a document request's and `{{engagement_number}}` an engagement's: each
    is a REAL field in the wrong template elsewhere, and the sentence for that is not the typo's."""
    assert et.problem_with("document_request", "Asked for {{request_title}}", "Dear {{client_name}}") is None
    for kind, field in (("engagement", "request_title"), ("document_request", "engagement_number"),
                        ("document_request", "financial_year"), ("document_request", "invoice_amount"),
                        ("document_request", "portal_link")):
        problem = et.problem_with(kind, "x", "{{" + field + "}}")
        assert problem and "cannot be filled in" in problem, (kind, field)


def test_the_screens_merge_fields_are_the_servers():
    """Names, labels and ORDER: the server serves the list and the screen keeps a fallback copy for the
    window where the screen has redeployed ahead of the API."""
    assert _merge_fields_on_the_screen() == list(et.MERGE_FIELDS.items())


def test_two_kinds_are_live_and_the_rest_say_why_not():
    live = [k for k, v in et.KIND_IS_LIVE.items() if v]
    assert live == ["engagement", "document_request"]
    for kind in live:
        assert et.kind_status(kind)["reason"] is None
    assert set(et.FIELDS_BY_KIND) == set(live)
    reasons = {k: et.kind_status(k)["reason"] for k in ("invoice", "reminder")}
    assert all(reasons.values()) and len(set(reasons.values())) == 2


# ── the shipped defaults ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(et.FIELDS_BY_KIND))
def test_a_shipped_default_is_one_the_server_will_accept(kind):
    """A CA pressing Reset to default and then Save must not be refused by the door that guards it."""
    subject, body = _shipped_default(kind)
    assert et.problem_with(kind, subject, body) is None, (kind, et.problem_with(kind, subject, body))


def test_the_document_request_default_promises_nothing_the_portal_cannot_do():
    """The portal's document upload is deliberately not built (a client reads a request there and
    answers by reply), and a request holds no financial year."""
    subject, body = _shipped_default("document_request")
    for text in (subject, body):
        assert "upload" not in text.lower()
        assert "financial_year" not in text and "financial year" not in text.lower()
    assert "{{request_title}}" in subject and "{{request_title}}" in body


def test_the_default_does_not_use_a_field_a_request_may_not_hold():
    """A request has a due date only sometimes, and a template using one the request lacks falls back to
    the built-in wording, so the default a CA can save and forget must not depend on it."""
    subject, body = _shipped_default("document_request")
    assert "{{due_date}}" not in subject + body


def test_the_screen_offers_only_the_fields_the_server_measured():
    src = _page()
    assert "by_kind" in src and "allowedFields" in src
    assert "WORDING_NOTE" in src and "APPLIED_SENTENCE" in src
    # The one sentence for every applied kind said "every engagement letter" under a kind that is not one.
    assert src.count("This wording is used on every engagement letter you send.") == 1
    assert "document request" in src[src.index("APPLIED_SENTENCE"):].lower()


# ── the senders ──────────────────────────────────────────────────────────────

def _fn(func):
    return ast.parse(inspect.getsource(func).strip()).body[0]


def _firm_wording_calls(func) -> list[ast.Call]:
    return [n for n in ast.walk(_fn(func)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_firm_wording"]


@pytest.mark.parametrize("kind,func", [("engagement", es.send_engagement_letter),
                                       ("document_request", es.send_document_request_notice)])
def test_the_sender_supplies_every_field_its_kind_promises(kind, func):
    """FIELDS_BY_KIND is a CONTRACT. A sender that stops supplying one breaks the template silently:
    the render refuses and the stock wording goes out, with nobody told."""
    calls = [c for c in _firm_wording_calls(func)
             if isinstance(c.args[0], ast.Constant) and c.args[0].value == kind]
    assert len(calls) == 1, f"{func.__name__} must ask for the firm's {kind} wording exactly once"
    values = calls[0].args[2]
    assert isinstance(values, ast.Dict)
    supplied = {k.value for k in values.keys if isinstance(k, ast.Constant)}
    assert supplied == set(et.FIELDS_BY_KIND[kind]), (supplied, set(et.FIELDS_BY_KIND[kind]))
    assert "firm_id" in inspect.signature(func).parameters


def test_what_the_firms_wording_returned_reaches_the_document_request_mail():
    """THE RULE, NOT A NAME: the name bound from `_firm_wording` is READ afterwards, so the call cannot
    survive with its value dropped on the floor."""
    fn = _fn(es.send_document_request_notice)
    bound: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "_firm_wording"):
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert bound
    loads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert bound & loads


def test_the_portal_notice_hands_the_sender_the_firm():
    import services.portal_notice_service as pns
    src = inspect.getsource(pns.document_requested)
    assert "firm_id=firm_id" in src


# ── what goes out ────────────────────────────────────────────────────────────

class _Wire:
    def __init__(self):
        self.sent: list[dict] = []

    def __call__(self, to, subject, html, *args, **kwargs):
        self.sent.append({"to": to, "subject": subject, "html": html, **kwargs})
        return True


@pytest.fixture
def wire(monkeypatch):
    w = _Wire()
    monkeypatch.setattr(es, "_send", w)
    return w


def _template(monkeypatch, subject, body):
    from repositories.branding_repository import branding_repo
    monkeypatch.setattr(branding_repo, "get_active_email_template",
                        lambda firm_id, kind: {"subject": subject, "body": body} if subject else None)


def _ask(**overrides):
    args = dict(to="c@example.invalid", contact_name="Ramesh", firm_name="Sharma & Co",
                request_title="Bank statements, April to June", is_urgent=False,
                due_date="30 Oct 2026", login_url="https://app.example.invalid/portal/login",
                firm_id="firm-1")
    args.update(overrides)
    return es.send_document_request_notice(
        args.pop("to"), args.pop("contact_name"), args.pop("firm_name"), args.pop("request_title"),
        args.pop("is_urgent"), args.pop("due_date"), args.pop("login_url"), **args)


def test_a_document_request_goes_out_in_the_firms_words_and_keeps_what_it_is_for(wire, monkeypatch):
    _template(monkeypatch, "{{firm_name}} needs {{request_title}}",
              "Dear {{client_name}},\n\nPlease send {{request_title}} by {{due_date}}.")
    assert _ask(is_urgent=True) is True
    mail = wire.sent[0]
    assert mail["subject"] == "Sharma & Co needs Bank statements, April to June"
    html = mail["html"]
    assert "Please send Bank statements, April to June by 30 Oct 2026." in html.replace("&amp;", "&")
    # The built-in opening is replaced; the particulars, the urgent notice and the sign-in link stay.
    assert "has asked you for a document" not in html
    assert "This request is marked urgent." in html
    assert "<strong>Request</strong>" in html and "Needed by" in html and "30 Oct 2026" in html
    assert 'href="https://app.example.invalid/portal/login"' in html


def test_no_template_sends_exactly_the_built_in_wording(wire, monkeypatch):
    _template(monkeypatch, None, None)
    _ask()
    mail = wire.sent[0]
    assert mail["subject"] == "Sharma & Co has asked you for: Bank statements, April to June"
    assert "has asked you for a document" in mail["html"]
    wire.sent.clear()
    _ask(firm_id=None)
    assert "has asked you for a document" in wire.sent[0]["html"]


def test_a_request_with_no_due_date_is_not_sent_with_a_hole_in_the_firms_sentence(wire, monkeypatch):
    _template(monkeypatch, "Documents for {{firm_name}}", "Send it by {{due_date}}.")
    _ask(due_date=None)
    mail = wire.sent[0]
    assert mail["subject"].startswith("Sharma & Co has asked you for:")
    assert "has asked you for a document" in mail["html"]
    assert "Needed by" not in mail["html"]


def test_a_request_title_with_a_line_break_cannot_split_the_subject(wire, monkeypatch):
    _template(monkeypatch, "Re: {{request_title}}", "Dear {{client_name}}")
    _ask(request_title="Bank statements\nBcc: someone@example.invalid")
    subject = wire.sent[0]["subject"]
    assert "\n" not in subject and "\r" not in subject
    assert subject == "Re: Bank statements Bcc: someone@example.invalid"


def test_the_engagement_letter_can_say_which_engagement_it_is(wire, monkeypatch):
    _template(monkeypatch, "Letter {{engagement_number}} — {{engagement_title}}",
              "Dear {{client_name}},\n\nPlease sign {{engagement_number}}.")
    es.send_engagement_letter("c@example.invalid", "Ramesh", "Sharma & Co", "EL-2026-014",
                              "GST return filing", "<p>The letter.</p>", firm_id="firm-1")
    mail = wire.sent[0]
    assert mail["subject"] == "Letter EL-2026-014 — GST return filing"
    assert "Please sign EL-2026-014." in mail["html"]
    assert "<p>The letter.</p>" in mail["html"]


def test_an_engagement_title_with_a_line_break_cannot_split_the_subject(wire, monkeypatch):
    _template(monkeypatch, "{{engagement_title}}", "Dear {{client_name}}")
    es.send_engagement_letter("c@example.invalid", "Ramesh", "Sharma & Co", "EL-1",
                              "GST\nBcc: x@example.invalid", "<p>L</p>", firm_id="firm-1")
    assert "\n" not in wire.sent[0]["subject"]

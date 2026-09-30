"""A mail says who it is from and where a reply goes (practice_management-04).

WHAT WAS WRONG
    Every send path used ONE sender, `PracticeSync AI <noreply@caflow.ai>`, and no
    path set a Reply-To. An engagement letter therefore arrived from a no-reply
    address and the client's answer to it went nowhere.

WHAT THE FIX DOES, and the one place it differs from the finding's own text
    The finding asked for the FIRM's name and the FIRM's contact address on four
    mails. That is right for ONE of them and would undo SALES-13 on three:

      * the ENGAGEMENT LETTER is the practice writing to its own client — the
        practice's name is the From display name and `firms.email` is the
        Reply-To;
      * the INVOICE, the STATEMENT and the PAYMENT REMINDER are the practice
        sending on a CLIENT's behalf to the CLIENT's customer. The supplier is
        the client; the practice is not a party to the debt; and a customer who
        hits Reply on "Invoice INV/001 from Acme Traders" and finds a chartered
        accountant in the To line has been told who their supplier's accountant
        is. They take the CLIENT's name and the CLIENT's contact address, and a
        client with no address on record sets no Reply-To at all.

    The address part of `from` never changes — a per-firm sending domain with
    DKIM needs DNS on each firm's side and is a later step. There is no
    "fee invoice" mail in this product, so nothing to change there.

WHAT IS ASSERTED — the outbound Resend JSON, through the real senders
    * the engagement letter carries the firm's name in `from` and the firm's
      email in `reply_to`, through the real router path;
    * invoice, statement and reminder carry the CLIENT's, never the firm's — the
      firm is present in the fixtures so a wrong source would show;
    * an absent or malformed address sets no `reply_to`; an absent name keeps the
      default sender; the neutral fallback word is never a display name;
    * a display name cannot inject a header or end the field early;
    * internal notifications still go exactly as before.
"""
from __future__ import annotations

import inspect

import pytest

import routers.customer_statements as cs_router
import routers.engagement_letters as el
import routers.sales_invoices as si
import services.collections_service as coll
import services.email_service as es
from tests.e2e_harness import FakeDB

FIRM_NAME, FIRM_EMAIL = "Gupta & Associates", "partner@gupta-ca.in"
CLIENT_NAME, CLIENT_EMAIL = "Acme Traders Pvt Ltd", "accounts@acme-traders.in"
DEFAULT_FROM = "PracticeSync AI <noreply@caflow.ai>"


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"id": "msg-1"}


@pytest.fixture
def wire(monkeypatch):
    """The JSON bodies POSTed to Resend, through the real transports."""
    sent: list[dict] = []
    monkeypatch.setattr(es, "_RESEND_API_KEY", "test-key")
    monkeypatch.setattr(es, "_FROM_EMAIL", DEFAULT_FROM)

    import httpx

    def post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", post)
    return sent


# ── the header helpers ───────────────────────────────────────────────────────

def test_no_name_is_the_configured_sender_exactly(monkeypatch):
    monkeypatch.setattr(es, "_FROM_EMAIL", DEFAULT_FROM)
    assert es.from_header(None) == DEFAULT_FROM
    assert es.from_header("") == DEFAULT_FROM
    assert es.from_header("   ") == DEFAULT_FROM


def test_a_name_keeps_the_verified_address(monkeypatch):
    monkeypatch.setattr(es, "_FROM_EMAIL", "Other Product <mail@example.test>")
    assert es.from_header("Acme Traders") == "Acme Traders <mail@example.test>"


@pytest.mark.parametrize("hostile", [
    'Acme"\r\nBcc: victim@x.test', "Acme <evil@x.test>", "Acme, Evil <e@x.test>",
    "Acme\\", "Acme;drop", "\x00\x1f\x7f",
])
def test_a_display_name_cannot_inject_a_header_or_end_the_field(hostile):
    header = es.from_header(hostile)
    assert "\r" not in header and "\n" not in header
    # Exactly one address in the field, and it is the verified one.
    assert header.count("<") == 1 and header.count(">") == 1
    assert header.endswith("<noreply@caflow.ai>") or header == DEFAULT_FROM
    assert "evil@x.test" not in header and "victim@x.test" not in header


def test_a_very_long_name_is_cut():
    assert len(es.from_header("A" * 500)) < 120


@pytest.mark.parametrize("good,expected", [
    ("partner@gupta-ca.in", "partner@gupta-ca.in"),
    ("  Partner@Gupta-CA.in  ", "Partner@gupta-ca.in"),
])
def test_a_usable_address_is_the_reply_to(good, expected):
    assert es.reply_to_header(good) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "not-an-address", "a@b", "a b@c.test",
                                 "x@y.test, z@w.test", "x@y.test\r\nBcc: a@b.test"])
def test_an_unusable_address_is_dropped_not_sent(bad):
    assert es.reply_to_header(bad) is None


# ── the transports ───────────────────────────────────────────────────────────

def test_send_carries_the_name_and_the_reply_to(wire):
    assert es._send("c@x.test", "s", "<p>h</p>", sender_name="Acme", reply_to="a@acme-traders.in")
    body = wire[0]
    assert body["from"] == "Acme <noreply@caflow.ai>"
    assert body["reply_to"] == "a@acme-traders.in"


def test_send_with_attachment_carries_them_too(wire):
    ok, _ = es._send_with_attachment("c@x.test", "s", "<p>h</p>", b"%PDF", "f.pdf",
                                     sender_name="Acme", reply_to="a@acme-traders.in")
    assert ok
    body = wire[0]
    assert body["from"] == "Acme <noreply@caflow.ai>" and body["reply_to"] == "a@acme-traders.in"
    assert body["attachments"][0]["filename"] == "f.pdf"


def test_neither_set_is_exactly_the_old_payload(wire):
    es._send("c@x.test", "s", "<p>h</p>")
    es._send_with_attachment("c@x.test", "s", "<p>h</p>", b"%PDF", "f.pdf")
    for body in wire:
        assert body["from"] == DEFAULT_FROM
        assert "reply_to" not in body


def test_a_malformed_reply_to_does_not_reach_the_provider(wire):
    es._send("c@x.test", "s", "<p>h</p>", sender_name="Acme", reply_to="not-an-address")
    assert "reply_to" not in wire[0]
    assert wire[0]["from"] == "Acme <noreply@caflow.ai>"


def test_internal_notifications_are_unchanged(wire):
    es.send_task_assigned("staff@f.test", "Sam", "Do the thing", "Acme", "2026-10-01")
    es.send_escalation_alert("m@f.test", "Mo", "T", "Sam", "Acme")
    es.send_firm_invite("new@f.test", "Gupta", "Gita", "Manager", "https://x.test/i")
    assert len(wire) == 3
    for body in wire:
        assert body["from"] == DEFAULT_FROM and "reply_to" not in body


# ── the engagement letter: the PRACTICE is the sender ────────────────────────

class _Table:
    def __init__(self, rows, db, name):
        self.rows, self.db, self.name = rows, db, name
        self._single, self._op, self._payload = False, "select", None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def single(self): self._single = True; return self
    def maybe_single(self): self._single = True; return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def execute(self):
        class R:  # noqa: N801
            pass
        r = R()
        if self._op == "insert":
            r.data = [{**self._payload, "id": "D1"}]
        elif self._op == "update":
            r.data = [self._payload]
        elif self._single:
            r.data = self.rows[0] if self.rows else None
        else:
            r.data = list(self.rows)
        return r


class _Db:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return _Table(self.tables.get(name, []), self, name)


def _engagement_send(monkeypatch, firm_row):
    monkeypatch.setattr("services.engagement_pdf_service.render_engagement_pdf",
                        lambda content, number: (b"%PDF-1.4", "engagement.pdf"))
    db = _Db(firms=[firm_row] if firm_row is not None else [], clients=[])
    eng = {"id": "E1", "client_id": None, "engagement_number": "EL-2026-0001",
           "title": "GST compliance", "content": "<p>Fee</p>",
           "recipient_name": "Patel Foods", "recipient_email": "owner@patelfoods.in"}
    return el._deliver_engagement_email(db, eng, "F1", None, sign_url=None)


def test_the_engagement_letter_goes_out_under_the_firms_name_and_replies_reach_the_firm(
        monkeypatch, wire):
    res = _engagement_send(monkeypatch, {"name": FIRM_NAME, "email": FIRM_EMAIL})
    assert res["success"] is True
    body = wire[0]
    assert body["from"] == f"{FIRM_NAME} <noreply@caflow.ai>"
    assert FIRM_NAME in body["from"]
    assert body["reply_to"] == FIRM_EMAIL


def test_a_firm_with_no_email_on_record_sets_no_reply_to(monkeypatch, wire):
    _engagement_send(monkeypatch, {"name": FIRM_NAME, "email": None})
    assert wire[0]["from"] == f"{FIRM_NAME} <noreply@caflow.ai>"
    assert "reply_to" not in wire[0]


def test_a_firm_that_cannot_be_read_is_not_named_from_a_placeholder(monkeypatch, wire):
    """"Your Chartered Accountant" is body text for a failed lookup. A mail is
    not sent FROM a placeholder."""
    _engagement_send(monkeypatch, None)
    assert wire[0]["from"] == DEFAULT_FROM
    assert "reply_to" not in wire[0]
    assert "Your Chartered Accountant" in wire[0]["html"]


# ── invoice, statement, reminder: the CLIENT is the sender ───────────────────
#
# The firm's name and email are in every fixture below. A build that read them
# would put the practice on the header — the defect SALES-13 closed — and these
# assertions would see it.

def test_the_invoice_mail_carries_the_clients_name_and_address(wire):
    es.send_invoice_to_customer(
        to="cust@buyer-retail.in", customer_name="Buyer", firm_name=CLIENT_NAME,
        invoice_no="INV/1", invoice_date="2026-06-01", due_date=None, total_paise=118000,
        pdf_bytes=b"%PDF", pdf_filename="inv.pdf",
        sender_name=CLIENT_NAME, reply_to=CLIENT_EMAIL)
    assert wire[0]["from"] == f"{CLIENT_NAME} <noreply@caflow.ai>"
    assert wire[0]["reply_to"] == CLIENT_EMAIL
    assert FIRM_NAME not in wire[0]["from"] and FIRM_EMAIL not in str(wire[0])


def test_the_statement_mail_carries_the_clients_name_and_address(wire):
    es.send_statement_to_customer(
        to="cust@buyer-retail.in", customer_name="Buyer", firm_name=CLIENT_NAME,
        period_start="2026-04-01", period_end="2026-06-30", closing_balance_paise=5000,
        pdf_bytes=b"%PDF", pdf_filename="s.pdf",
        sender_name=CLIENT_NAME, reply_to=CLIENT_EMAIL)
    assert wire[0]["from"] == f"{CLIENT_NAME} <noreply@caflow.ai>"
    assert wire[0]["reply_to"] == CLIENT_EMAIL


@pytest.mark.parametrize("with_pdf", [True, False])
def test_the_reminder_mail_carries_the_clients_name_and_address(wire, with_pdf):
    es.send_payment_reminder_to_customer(
        to="cust@buyer-retail.in", customer_name="Buyer", firm_name=CLIENT_NAME,
        invoice_no="INV/1", invoice_date="2026-06-01", due_date="2026-06-30",
        outstanding_paise=118000, reminder_number=1,
        pdf_bytes=b"%PDF" if with_pdf else None, pdf_filename="i.pdf" if with_pdf else None,
        sender_name=CLIENT_NAME, reply_to=CLIENT_EMAIL)
    assert wire[0]["from"] == f"{CLIENT_NAME} <noreply@caflow.ai>"
    assert wire[0]["reply_to"] == CLIENT_EMAIL


@pytest.mark.parametrize("fn,kwargs", [
    (es.send_invoice_to_customer, dict(invoice_no="I", invoice_date="d", due_date=None,
                                       total_paise=1, pdf_bytes=b"%PDF", pdf_filename="f.pdf")),
    (es.send_statement_to_customer, dict(period_start="a", period_end="b",
                                         closing_balance_paise=1, pdf_bytes=b"%PDF",
                                         pdf_filename="f.pdf")),
    (es.send_payment_reminder_to_customer, dict(invoice_no="I", invoice_date="d", due_date=None,
                                                outstanding_paise=1, reminder_number=1)),
], ids=["invoice", "statement", "reminder"])
def test_a_client_mail_with_no_name_or_address_goes_exactly_as_it_did(wire, fn, kwargs):
    fn(to="c@x.test", customer_name="B", firm_name="Your supplier", **kwargs)
    assert wire[0]["from"] == DEFAULT_FROM and "reply_to" not in wire[0]


@pytest.mark.parametrize("fn", [es.send_invoice_to_customer, es.send_statement_to_customer,
                                es.send_payment_reminder_to_customer])
def test_the_client_mails_take_no_firm_identity(fn):
    """A guard on the PARTY, not on a spelling: these mails have no `firm_id`
    (so no firm wording) and no parameter that could carry the practice's
    address. `firm_name` is the client's name, as its own comments say."""
    params = set(inspect.signature(fn).parameters)
    assert "firm_id" not in params
    assert {"sender_name", "reply_to"} <= params
    assert "_firm_wording" not in inspect.getsource(fn)


# ── the call sites hand over the CLIENT, read from the client's own row ──────

def test_a_reminder_is_sent_under_the_clients_name_with_the_clients_reply_to(monkeypatch):
    captured: dict = {}

    def fake(**kw):
        captured.update(kw)
        return True, "prov-1"

    monkeypatch.setattr(es, "send_payment_reminder_to_customer", fake)
    import services.invoice_pdf_service as pdf
    import services.timeline_service as ts
    monkeypatch.setattr(pdf, "get_sales_invoice_pdf", lambda iid, fid: (b"%PDF", "i.pdf"))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)

    db = FakeDB()
    # The PRACTICE row is seeded with a name and an address too.
    db.seed("firms", {"id": "F1", "name": FIRM_NAME, "email": FIRM_EMAIL})
    db.seed("clients", {"id": "CL-1", "firm_id": "F1", "legal_name": CLIENT_NAME,
                        "client_name": "Acme", "email": CLIENT_EMAIL})
    inv = {"id": "A", "firm_id": "F1", "client_id": "CL-1", "customer_id": "CU-1",
           "invoice_no": "SINV-A", "invoice_date": "2019-12-01", "due_date": "2020-01-01",
           "total_paise": 118000, "paid_paise": 0, "status": "issued",
           "reminder_count": 0, "last_reminded_at": None}
    db.seed("client_sales_invoices", inv)
    assert coll._dispatch_invoice_reminder(
        db, "F1", inv, {"id": "CU-1", "name": "Buyer", "email": "ap@buyer-retail.in"}, 1)
    assert captured["sender_name"] == CLIENT_NAME
    assert captured["reply_to"] == CLIENT_EMAIL
    assert FIRM_NAME not in (captured["sender_name"], captured["firm_name"])
    assert captured["reply_to"] != FIRM_EMAIL


@pytest.mark.parametrize("row,name,reply", [
    ({"legal_name": None, "client_name": "Acme", "email": None}, "Acme", None),
    ({"legal_name": None, "client_name": None, "email": "a@acme-traders.in"}, None, "a@acme-traders.in"),
    ({}, None, None),
], ids=["no-address", "no-name", "no-client-row"])
def test_a_reminder_for_a_thinly_recorded_client_never_falls_back_to_the_practice(
        monkeypatch, row, name, reply):
    captured: dict = {}
    monkeypatch.setattr(es, "send_payment_reminder_to_customer",
                        lambda **kw: (captured.update(kw) or (True, "p")))
    import services.invoice_pdf_service as pdf
    import services.timeline_service as ts
    monkeypatch.setattr(pdf, "get_sales_invoice_pdf", lambda iid, fid: (b"%PDF", "i.pdf"))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    db = FakeDB()
    db.seed("firms", {"id": "F1", "name": FIRM_NAME, "email": FIRM_EMAIL})
    if row:
        db.seed("clients", {"id": "CL-1", "firm_id": "F1", **row})
    inv = {"id": "A", "firm_id": "F1", "client_id": "CL-1", "customer_id": "CU-1",
           "invoice_no": "SINV-A", "invoice_date": "2019-12-01", "due_date": "2020-01-01",
           "total_paise": 100, "paid_paise": 0, "status": "issued",
           "reminder_count": 0, "last_reminded_at": None}
    db.seed("client_sales_invoices", inv)
    coll._dispatch_invoice_reminder(db, "F1", inv, {"name": "B", "email": "ap@b.test"}, 1)
    assert captured["sender_name"] == name
    assert captured["reply_to"] == reply
    # The body keeps its neutral word; the header never gets it.
    assert captured["sender_name"] != "Your supplier"


def test_the_invoice_send_hands_over_the_clients_name_and_address(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(es, "send_invoice_to_customer",
                        lambda **kw: (captured.update(kw) or (True, "p")))
    import services.invoice_pdf_service as pdf
    monkeypatch.setattr(pdf, "get_sales_invoice_pdf", lambda iid, fid: (b"%PDF", "i.pdf"))
    monkeypatch.setattr(si, "log_event", lambda *a, **k: None)
    invoice = {"id": "I1", "firm_id": "F1", "client_id": "CL-1", "status": "issued",
               "invoice_no": "INV/1", "invoice_date": "2026-06-01", "due_date": None,
               "total_paise": 118000, "customers": {"id": "CU-1", "name": "Buyer",
                                                    "email": "ap@buyer-retail.in"}}
    db = _Db(client_sales_invoices=[invoice],
             clients=[{"legal_name": CLIENT_NAME, "client_name": "Acme", "email": CLIENT_EMAIL}],
             firms=[{"name": FIRM_NAME, "email": FIRM_EMAIL}],
             invoice_deliveries=[])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    si._do_send_invoice("I1", si._SendInvoiceBody(),
                        {"firm_id": "F1", "auth_user_id": "a1", "email": "staff@gupta-ca.in"})
    assert captured["sender_name"] == CLIENT_NAME
    assert captured["reply_to"] == CLIENT_EMAIL
    assert captured["firm_name"] == CLIENT_NAME


def test_the_statement_send_hands_over_the_clients_name_and_address(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(es, "send_statement_to_customer",
                        lambda **kw: (captured.update(kw) or (True, "p")))
    import services.statement_pdf_service as sps
    monkeypatch.setattr(cs_router, "_db", lambda: object())
    monkeypatch.setattr(cs_router, "assert_client_access", lambda *a: None)
    monkeypatch.setattr(cs_router, "log_event", lambda *a, **k: None)
    svc = cs_router.customer_statement_service
    monkeypatch.setattr(svc, "generate", lambda *a, **k: {
        "customer": {"name": "Buyer", "email": "ap@buyer-retail.in"},
        "closing_balance_paise": 5000})
    monkeypatch.setattr(svc, "record_delivery", lambda *a, **k: "D1")
    monkeypatch.setattr(svc, "finish_delivery", lambda *a, **k: None)
    monkeypatch.setattr(sps, "build_statement_pdf", lambda *a, **k: b"%PDF")
    monkeypatch.setattr(sps, "load_account_holder", lambda *a, **k: {
        "legal_name": CLIENT_NAME, "client_name": "Acme", "email": CLIENT_EMAIL})
    body = cs_router.StatementEmailIn(client_id="CL-1", customer_id="CU-1",
                                      start_date="2026-04-01", end_date="2026-06-30")
    res = cs_router.email_statement(body, {"firm_id": "F1", "auth_user_id": "a1",
                                           "email": "staff@gupta-ca.in"})
    assert res["success"] is True
    assert captured["sender_name"] == CLIENT_NAME and captured["reply_to"] == CLIENT_EMAIL


def test_the_statement_holder_read_asks_for_the_clients_email():
    """`email` rides the same read as the name; without it `reply_to` would be
    silently None for every statement."""
    from services import statement_pdf_service as sps
    assert '"id,client_name,legal_name,trade_name,gstin,pan,email"' in inspect.getsource(
        sps.load_account_holder)

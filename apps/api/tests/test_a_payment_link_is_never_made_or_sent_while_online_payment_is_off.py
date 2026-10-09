"""While online payment is not switched on, no payment link is made, shown as usable or emailed (PRE-B-002 part 2).

WHAT WAS WRONG

    Pay Now was drawn for every invoice with a balance and opened `https://mock-pay.local/pay/<id>` (the test
    double's address, which does not exist) when `PAYMENT_PROVIDER` was blank or `mock`, and the practice's
    "Payment Link" modal could email that address to a client's customer. A DRAFT or a CANCELLED invoice was
    offered the button too.

WHAT THIS HOLDS, DRIVEN THROUGH THE REAL ROUTERS AND THE REAL SERVICE ON A DATABASE DOUBLE

    * with the provider blank, `mock`, half set up or unrecognised, `POST /api/payments/links`, `POST
      /api/payments/links/{id}/send` and `POST /api/portal/self/invoices/{id}/pay` each answer 409 with the
      SERVER's own sentence (the client's carries no setting name), write no `customer_payment_links` row and send
      no mail; ownership is still asked before availability, so a refusal is no oracle for another client's invoice;
    * the same routes WORK once a real gateway is set up (the gate is not a wall), and the dashboard serves the
      block the portal renders;
    * a payment history shows a stored link the test double made with no address and a note, and says whether a
      link may be made for THIS invoice; a draft, a cancelled or a paid invoice is not payable and a link is not
      created for one;
    * the portal's invoice rows say `can_pay_online` for an issued or part-paid invoice with a balance only;
    * under a real gateway, a link a different provider made is never handed back as this gateway's, and the mail
      refuses a link that is the test double's, expired, paid, half-made or without an address.

NOT HERE: the matrix of provider and key combinations (test_online_payment_is_available_only_for_a_real_provider_
with_every_key.py) and the AST rule that every route reaching the service asks first (test_every_route_that_makes_
or_sends_a_payment_link_asks_whether_online_payment_is_on.py).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import services.payment_service as ps
from domain.payments import availability as rule
from services.payments.base import PaymentLinkResult
from tests.test_online_payments import FakeDB, _seed_invoice

FIRM, CLIENT, CUSTOMER = "F1", "CL-1", "CUST-1"
STAFF = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "ca@f1.test", "auth_user_id": "auth-u1"}
PORTAL = {"portal": True, "client_id": "CL-PORTAL", "firm_id": FIRM, "email": "a@acme.test", "name": "Acme",
          "portal_contact_id": "c-1", "role": "PortalClient", "memberships": []}
RAZORPAY_KEYS = ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET")
GONE = "https://mock-pay.local/pay/L-OLD"


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """The production state unless a test says otherwise: PAYMENT_PROVIDER unset, no gateway key."""
    for name in ("PAYMENT_PROVIDER", *RAZORPAY_KEYS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("services.payment_service.log_event", lambda *a, **k: None)


def _live(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    for k in RAZORPAY_KEYS:
        monkeypatch.setenv(k, "set")


class _Env:
    """A TestClient over the real app with the staff and portal principals overridden and the database a double."""

    def __init__(self, monkeypatch):
        from main import app
        import routers.payments as pr
        import routers.portal_data as pdr
        import services.portal_data_service as pds
        import core.supabase_client as sc
        from core.auth import get_current_user
        from core.portal_auth import get_current_portal_client
        self.app = app
        self.db = FakeDB()
        _seed_invoice(self.db, firm=FIRM, client=CLIENT, customer=CUSTOMER, iid="INV-1")
        monkeypatch.setattr(pr, "_db", lambda: self.db)
        monkeypatch.setattr(pr, "_USE_MOCK", False)
        monkeypatch.setattr(pdr, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: self.db)
        monkeypatch.setattr(pds, "invoice_in_scope", lambda *a, **k: True)
        app.dependency_overrides[get_current_user] = lambda: STAFF
        app.dependency_overrides[get_current_portal_client] = lambda: PORTAL
        self.client = TestClient(app)

    def close(self):
        self.app.dependency_overrides.clear()

    def links(self):
        return self.db.data.get("customer_payment_links", [])


@pytest.fixture
def env(monkeypatch):
    e = _Env(monkeypatch)
    yield e
    e.close()


@pytest.fixture
def mail(monkeypatch):
    """Spy on the one function that mails a payment link. A call is a mail that would have left."""
    calls: list[dict] = []

    def _send(**kw):
        calls.append(kw)
        return True

    monkeypatch.setattr("services.email_service.send_payment_link_to_customer", _send)
    return calls


def _stored_link(db, link_id="L1", **over):
    row = {"id": link_id, "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "invoice_id": "INV-1",
           "amount_paise": 100000, "currency": "INR", "provider": "mock", "status": "active",
           "short_url": GONE, "expires_at": "2099-01-01T00:00:00+00:00"}
    row.update(over)
    return db.seed("customer_payment_links", row)


NOT_LIVE = [
    pytest.param({}, id="provider-unset"),
    pytest.param({"PAYMENT_PROVIDER": ""}, id="provider-blank"),
    pytest.param({"PAYMENT_PROVIDER": "   "}, id="provider-spaces"),
    pytest.param({"PAYMENT_PROVIDER": "mock"}, id="provider-mock"),
    pytest.param({"PAYMENT_PROVIDER": "razorpay"}, id="razorpay-no-keys"),
    pytest.param({"PAYMENT_PROVIDER": "razorpay", "RAZORPAY_KEY_ID": "set", "RAZORPAY_KEY_SECRET": "set"},
                 id="razorpay-no-webhook-secret"),
    pytest.param({"PAYMENT_PROVIDER": "stripe", **{k: "set" for k in RAZORPAY_KEYS}}, id="provider-unrecognised"),
    pytest.param({"PAYMENT_PROVIDER": "mock", **{k: "set" for k in RAZORPAY_KEYS}}, id="mock-with-every-key"),
]


def _set(monkeypatch, values):
    for k, v in values.items():
        monkeypatch.setenv(k, v)


# ── not live: refused with the server's words, nothing written, nothing sent ──────────────────────────────────

@pytest.mark.parametrize("values", NOT_LIVE)
def test_the_practice_cannot_create_a_payment_link_while_online_payment_is_off(env, monkeypatch, values):
    _set(monkeypatch, values)
    r = env.client.post("/api/payments/links", json={"invoice_id": "INV-1"})
    assert r.status_code == 409, r.text
    assert "Online payment is coming soon." in r.text
    assert env.links() == [], "no customer_payment_links row is written"


@pytest.mark.parametrize("values", NOT_LIVE)
def test_the_practice_cannot_email_a_stored_link_while_online_payment_is_off(env, monkeypatch, mail, values):
    _set(monkeypatch, values)
    _stored_link(env.db)
    r = env.client.post("/api/payments/links/L1/send")
    assert r.status_code == 409, r.text
    assert "Online payment is coming soon." in r.text
    assert mail == [], "no mail left"
    assert env.db.data.get("invoice_deliveries", []) == [], "and none was recorded as sent"


@pytest.mark.parametrize("values", NOT_LIVE)
def test_a_portal_client_cannot_start_a_payment_while_online_payment_is_off(env, monkeypatch, values):
    _set(monkeypatch, values)
    spy = []
    monkeypatch.setattr(ps, "create_link", lambda *a, **k: spy.append(a) or {})
    r = env.client.post("/api/portal/self/invoices/INV-1/pay")
    assert r.status_code == 409, r.text
    assert "Online payment is coming soon." in r.text
    assert spy == [] and env.links() == [], "the service was never reached and no link row exists"


def test_what_the_client_is_refused_with_names_no_setting_no_gateway_and_no_test_double(env):
    text = env.client.post("/api/portal/self/invoices/INV-1/pay").json()
    sentence = str(text)
    for word in ("PAYMENT_PROVIDER", "RAZORPAY", "mock", "Razorpay", "webhook", "gateway"):
        assert word not in sentence, f"{word!r} reaches a client: {sentence}"


def test_what_the_practice_is_refused_with_says_why(env):
    sentence = env.client.post("/api/payments/links", json={"invoice_id": "INV-1"}).text
    assert "has not been switched on for this deployment" in sentence


def test_ownership_is_asked_before_availability_so_a_refusal_is_no_oracle(env, monkeypatch):
    import services.portal_data_service as pds
    monkeypatch.setattr(pds, "invoice_in_scope", lambda *a, **k: False)
    assert env.client.post("/api/portal/self/invoices/INV-1/pay").status_code == 404


# ── live: the gate is not a wall ─────────────────────────────────────────────────────────────────────────

def test_with_a_real_gateway_set_up_the_same_routes_reach_the_service(env, monkeypatch):
    _live(monkeypatch)
    made = []

    def create_link(db, firm_id, invoice_id, actor, **kw):
        made.append((firm_id, invoice_id))
        return {"id": "L9", "short_url": "https://pay.example/L9", "amount_paise": 100000, "status": "active"}

    monkeypatch.setattr(ps, "create_link", create_link)
    sent = []
    monkeypatch.setattr(ps, "send_link_email", lambda db, firm, link, actor: sent.append(link) or {"sent": True, "to": "x"})

    r = env.client.post("/api/payments/links", json={"invoice_id": "INV-1"})
    assert r.status_code == 200 and r.json()["data"]["short_url"] == "https://pay.example/L9"
    assert env.client.post("/api/payments/links/L9/send").status_code == 200 and sent == ["L9"]
    pay = env.client.post("/api/portal/self/invoices/INV-1/pay")
    assert pay.status_code == 200 and pay.json()["data"]["short_url"] == "https://pay.example/L9"
    assert made == [(FIRM, "INV-1"), (FIRM, "INV-1")]


# ── what a screen is shown ───────────────────────────────────────────────────────────────────────────────

def test_the_dashboard_serves_the_online_payment_block_the_portal_renders(env, monkeypatch):
    data = env.client.get("/api/portal/dashboard").json()["data"]
    assert data["online_payment"] == rule.portal_block(rule.Availability(rule.NOT_SWITCHED_ON, ("PAYMENT_PROVIDER",)))
    assert data["online_payment"]["available"] is False
    assert "state" not in data["online_payment"] and "settings_to_check" not in data["online_payment"]
    assert {s["key"] for s in data["sections"]} >= {"invoices"}, "the shell is what it was"
    _live(monkeypatch)
    live = env.client.get("/api/portal/dashboard").json()["data"]["online_payment"]
    assert live == {"available": True, "label": "Pay Now", "headline": None, "reason": None}


def test_a_history_shows_a_link_the_test_double_made_with_no_address_and_says_whether_a_link_may_be_made(env):
    _stored_link(env.db, "L-OLD")
    _stored_link(env.db, "L-REAL", provider="razorpay", short_url="https://pay.example/real")
    data = env.client.get("/api/payments", params={"invoice_id": "INV-1"}).json()["data"]
    by_id = {l["id"]: l for l in data["links"]}
    assert by_id["L-OLD"]["short_url"] is None and by_id["L-OLD"]["note"] == rule.MASKED_LINK_NOTE
    assert by_id["L-OLD"]["status"] == "active", "the history is true: it is listed"
    assert by_id["L-REAL"]["short_url"] == "https://pay.example/real" and "note" not in by_id["L-REAL"]
    assert data["online_payment"]["available"] is False and data["online_payment"]["state"] == rule.NOT_SWITCHED_ON
    assert data["online_payment"]["settings_to_check"] == ["PAYMENT_PROVIDER"]
    assert data["can_pay_online"] is True and data["outstanding_paise"] == 100000
    # the other two reads of a link are masked the same way
    listed = env.client.get("/api/payments/links", params={"invoice_id": "INV-1"}).json()["data"]
    assert next(l for l in listed if l["id"] == "L-OLD")["short_url"] is None
    one = env.client.get("/api/payments/links/L-OLD").json()["data"]
    assert one["short_url"] is None and one["note"] == rule.MASKED_LINK_NOTE


@pytest.mark.parametrize("status,payable", [("issued", True), ("partially_paid", True),
                                            ("draft", False), ("cancelled", False), ("paid", False)])
def test_a_history_says_a_link_may_be_made_only_for_an_issued_or_part_paid_invoice(env, status, payable):
    env.db.data["client_sales_invoices"][0]["status"] = status
    data = env.client.get("/api/payments", params={"invoice_id": "INV-1"}).json()["data"]
    assert data["can_pay_online"] is (payable and data["outstanding_paise"] > 0)


def test_the_portal_invoice_rows_say_which_are_payable(env, monkeypatch):
    import services.portal_data_service as pds
    rows = [
        {"id": "a", "status": "issued", "outstanding_paise": 5000},
        {"id": "b", "status": "partially_paid", "outstanding_paise": 100},
        {"id": "c", "status": "draft", "outstanding_paise": 5000},
        {"id": "d", "status": "cancelled", "outstanding_paise": 5000},
        {"id": "e", "status": "paid", "outstanding_paise": 0},
        {"id": "f", "status": "issued", "outstanding_paise": 0},
    ]
    monkeypatch.setattr(pds, "list_invoices", lambda *a, **k: [dict(r) for r in rows])
    got = env.client.get("/api/portal/self/invoices").json()["data"]["invoices"]
    assert {r["id"]: r["can_pay_online"] for r in got} == {
        "a": True, "b": True, "c": False, "d": False, "e": False, "f": False}
    assert [r["id"] for r in got] == [r["id"] for r in rows], "order and rows are as the service gave them"


def test_safe_invoice_is_unchanged_because_the_flag_is_added_outside_it():
    """safe_invoice's key set is pinned (test_portal_data_surfaces) and `dues` shares it: the flag is not in it."""
    import services.portal_data_service as pds
    out = pds.safe_invoice({"id": "A", "total_paise": 1000, "paid_paise": 0, "status": "issued"})
    assert "can_pay_online" not in out
    assert pds.with_pay_flag([out])[0]["can_pay_online"] is True


# ── the service: no link for a draft, none reused from another provider, no mail for a dead link ─────────────

@pytest.mark.parametrize("status", ["draft", "cancelled", "paid", "void"])
def test_no_link_is_created_for_an_invoice_that_is_not_payable(status):
    db = FakeDB()
    _seed_invoice(db, iid="INV-X", total=100000, paid=0, status=status)
    with pytest.raises(HTTPException) as e:
        ps.create_link(db, FIRM, "INV-X", actor={"auth_user_id": "u", "email": "x"})
    assert e.value.status_code == 422
    assert "customer_payment_links" not in db.data or db.data["customer_payment_links"] == []


def test_a_link_another_provider_made_is_not_handed_back_as_this_gateways(monkeypatch):
    """Production holds two active `mock` links. The day a real gateway is set up, the same invoice and amount
    must not return the address that goes nowhere."""
    _live(monkeypatch)
    from services.payments.razorpay import RazorpayProvider
    monkeypatch.setattr(RazorpayProvider, "create_payment_link", lambda self, req: PaymentLinkResult(
        provider="razorpay", provider_link_id="plink_1", provider_order_id="order_1",
        short_url="https://pay.example/real", status="created"))
    db = FakeDB()
    _seed_invoice(db, iid="INV-1", total=100000, paid=0)
    old = _stored_link(db, "L-OLD")
    link = ps.create_link(db, FIRM, "INV-1", actor={"auth_user_id": "u", "email": "x"})
    assert link["id"] != "L-OLD" and link["provider"] == "razorpay"
    assert link["short_url"] == "https://pay.example/real"
    assert db.data["customer_payment_links"][0]["short_url"] == old["short_url"], "the old row is left as it was"
    again = ps.create_link(db, FIRM, "INV-1", actor={"auth_user_id": "u", "email": "x"})
    assert again["id"] == link["id"], "and a link of THIS provider is still reused (idempotent)"


def test_the_mail_refuses_a_link_that_cannot_be_paid_and_sends_a_good_one_once(monkeypatch, mail):
    _live(monkeypatch)
    db = FakeDB()
    _seed_invoice(db, iid="INV-1", total=100000, paid=0)
    actor = {"auth_user_id": "u", "email": "ca@f1.test"}
    good = dict(provider="razorpay", status="active", short_url="https://pay.example/real")
    refused = {
        "the test double's own link": dict(good, provider="mock", short_url=GONE),
        "another gateway's link": dict(good, provider="cashfree"),
        "a half-made link": dict(good, status="created", short_url=None),
        "a paid link": dict(good, status="paid"),
        "an expired link": dict(good, expires_at="2020-01-01T00:00:00+00:00"),
        "a link with no address": dict(good, short_url=""),
    }
    for i, (what, over) in enumerate(refused.items()):
        _stored_link(db, f"L-{i}", **over)
        with pytest.raises(HTTPException) as e:
            ps.send_link_email(db, FIRM, f"L-{i}", actor=actor)
        assert e.value.status_code == 409, what
    assert mail == [] and db.data.get("invoice_deliveries", []) == [], "nothing left and nothing was recorded"

    _stored_link(db, "L-GOOD", **good)
    assert ps.send_link_email(db, FIRM, "L-GOOD", actor=actor) == {"sent": True, "to": "a@acme.test"}
    assert len(mail) == 1 and mail[0]["pay_url"] == "https://pay.example/real"
    assert db.data["invoice_deliveries"][0]["kind"] == "payment_link" and db.data["invoice_deliveries"][0]["status"] == "sent"

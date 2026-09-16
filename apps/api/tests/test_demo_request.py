"""
The marketing site's "Book a demo" endpoint.

This is the only unauthenticated WRITE surface on the API, so what is asserted
here is mostly what it REFUSES. The behaviours below are each load-bearing:

  * a lead is never reported as sent when it was not. The endpoint's whole
    reason to exist is capturing a prospect, and a form that says "thanks" over
    a dropped message loses the lead AND the knowledge that it was lost. Both
    failure modes — transport unconfigured, provider rejected — must be a
    non-2xx with success=false.
  * a spam submission is answered as if it succeeded. Telling a bot it was
    caught teaches whoever wrote it which field to leave alone.
  * the provider's real error never reaches the caller. email_service logs it;
    the response says only that it could not be sent.
  * the free text is HTML-escaped. It is attacker-controlled, it arrives with
    no authentication, and it is interpolated into an email a person on this
    team opens.
"""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _fresh_app(monkeypatch, *, to="sales@example.com"):
    """A client over a freshly-imported router.

    The rate limiter's windows are module-level, so every test needs its own
    module instance or the third test in a file starts getting 429s from the
    second one's submissions.
    """
    monkeypatch.setenv("DEMO_REQUEST_TO", to)
    import routers.demo_request as mod

    mod = importlib.reload(mod)
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app), mod


BODY = {
    "name": "CA Priya Raghavan",
    "firm_name": "Raghavan & Associates",
    "email": "priya@example.com",
    "phone": "+91 98765 43210",
    "firm_size": "6–20 people",
    "message": "We run about 60 clients on Tally and ClearTax today.",
}


def test_a_delivered_request_reports_success(monkeypatch):
    client, mod = _fresh_app(monkeypatch)
    sent = {}

    def fake_send(to, subject, html):
        sent.update(to=to, subject=subject, html=html)
        return True

    monkeypatch.setattr(mod.email_service, "_send", fake_send)

    res = client.post("/api/public/demo-request", json=BODY)
    assert res.status_code == 200
    assert res.json() == {"success": True, "data": {"received": True}, "error": None}
    assert sent["to"] == "sales@example.com"
    assert "Raghavan & Associates" in sent["subject"]
    # Every field the form collects reaches the person who has to act on it.
    for value in ("CA Priya Raghavan", "priya@example.com", "+91 98765 43210", "6–20 people"):
        assert value in sent["html"], value
    assert "Tally and ClearTax" in sent["html"]


def test_a_rejected_send_is_never_reported_as_received(monkeypatch):
    """The failure this endpoint exists to avoid."""
    client, mod = _fresh_app(monkeypatch)
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: False)

    res = client.post("/api/public/demo-request", json=BODY)
    assert res.status_code == 503
    payload = res.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert "couldn't send" in payload["error"].lower()


def test_an_unset_destination_refuses_rather_than_guessing(monkeypatch):
    client, mod = _fresh_app(monkeypatch, to="")
    called = []
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: called.append(1) or True)

    res = client.post("/api/public/demo-request", json=BODY)
    assert res.status_code == 503
    assert res.json()["success"] is False
    # It must not fall back to any address at all.
    assert called == []


def test_the_providers_reason_never_reaches_the_caller(monkeypatch):
    client, mod = _fresh_app(monkeypatch)
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: False)

    error = res_error = client.post("/api/public/demo-request", json=BODY).json()["error"].lower()
    for leak in ("resend", "api_key", "api key", "domain", "401", "403", "traceback"):
        assert leak not in error, leak
    assert res_error  # a real sentence, not an empty string


def test_a_filled_honeypot_looks_like_success_and_sends_nothing(monkeypatch):
    client, mod = _fresh_app(monkeypatch)
    called = []
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: called.append(1) or True)

    res = client.post(
        "/api/public/demo-request",
        json={**BODY, "website": "http://spam.example"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert called == []


def test_free_text_is_html_escaped(monkeypatch):
    """Attacker-controlled, unauthenticated, and rendered in someone's inbox."""
    client, mod = _fresh_app(monkeypatch)
    sent = {}
    monkeypatch.setattr(
        mod.email_service, "_send",
        lambda to, subject, html: sent.update(html=html) or True,
    )

    client.post(
        "/api/public/demo-request",
        json={**BODY, "message": "<script>alert(1)</script>", "name": 'A"B<C'},
    )
    assert "<script>" not in sent["html"]
    assert "&lt;script&gt;" in sent["html"]
    assert 'A"B<C' not in sent["html"]
    assert "A&quot;B&lt;C" in sent["html"]


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "@example.com", "a b@example.com"])
def test_a_value_that_is_not_an_address_is_refused(monkeypatch, bad):
    client, mod = _fresh_app(monkeypatch)
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: True)
    res = client.post("/api/public/demo-request", json={**BODY, "email": bad})
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_the_rate_limit_stops_a_flood(monkeypatch):
    client, mod = _fresh_app(monkeypatch)
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: True)
    headers = {"X-Forwarded-For": "203.0.113.7"}

    codes = [
        client.post("/api/public/demo-request", json=BODY, headers=headers).status_code
        for _ in range(mod._PER_IP_MAX + 2)
    ]
    assert codes[: mod._PER_IP_MAX] == [200] * mod._PER_IP_MAX
    assert codes[mod._PER_IP_MAX] == 429
    # A different caller is unaffected by the first one's limit.
    other = client.post(
        "/api/public/demo-request", json=BODY, headers={"X-Forwarded-For": "198.51.100.4"}
    )
    assert other.status_code == 200


def test_oversized_fields_are_refused_before_the_handler(monkeypatch):
    client, mod = _fresh_app(monkeypatch)
    called = []
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: called.append(1) or True)

    res = client.post("/api/public/demo-request", json={**BODY, "message": "x" * 2001})
    assert res.status_code == 422
    assert called == []


def test_the_form_gets_its_firm_sizes_from_the_server(monkeypatch):
    """One vocabulary. A copy in the browser is a copy that drifts."""
    client, mod = _fresh_app(monkeypatch)
    res = client.get("/api/public/demo-request/options")
    assert res.status_code == 200
    assert res.json()["data"]["firm_sizes"] == mod.FIRM_SIZES
    assert len(mod.FIRM_SIZES) >= 3


def test_the_endpoint_takes_no_tenant_identifier():
    """Structural, not checked at runtime.

    There is no firm_id or client_id to tamper with because the request model
    has no field for one — the same discipline routers/portal_employee.py uses
    to make an employee's self-scoping impossible to subvert rather than merely
    validated.
    """
    import routers.demo_request as mod

    fields = set(mod.DemoRequestIn.model_fields)
    assert not {"firm_id", "client_id", "user_id"} & fields

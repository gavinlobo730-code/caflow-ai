"""
An AI answer comes from the configured model, or the screen is told why not.

WHAT WAS WRONG (sweep-misc-tools-02)
    POST /api/assistant answered 502 "AI service error. Please try again." on
    4 of 4 attempts while the copilot appeared to work. The copilot did not
    work: `ai_copilot_service._call_groq` caught every Groq failure and
    returned a canned `_mock_response`, and every copilot reply stored in
    production (ai_messages, 27-09-2026) has tokens_used = 0 and is that
    mock's text word for word. Both routes sent the same key to the same URL
    for the same HARDCODED model — "llama-3.3-70b-versatile", while
    GROQ_TEXT_MODEL exists precisely so a retired model is a config change —
    and both were failing. One said so uselessly; one hid it.

    The assistant's 502 threw away Groq's status and body, so a revoked key
    and a retired model (the two failures that make EVERY attempt fail) were
    reported as something a retry might fix, and a timeout was not caught at
    all and came back as a bare 500.

WHAT IS ASSERTED — by calling the real endpoint and the real copilot call
against a stand-in Groq (httpx.MockTransport), never a copy of the code:
    * the model sent is GROQ_TEXT_MODEL's, defaulting to the one default;
    * each refusal comes back as a sentence that says what is wrong and
      whether retrying can help, with Groq's own status and body LOGGED;
    * the copilot raises that sentence rather than answering from a script,
      and still answers from the script in mock mode with no key — the one
      case where nobody can mistake it for the model.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import domain.ai_copilot_service as copilot
from core.auth import get_current_user
from domain.ai import groq_text
from routers import assistant as assistant_router

PARTNER = {"id": "u-1", "auth_user_id": "a-1", "firm_id": "firm-1",
           "email": "p@f.test", "role": "Partner"}

_RealAsyncClient = httpx.AsyncClient


@pytest.fixture
def groq(monkeypatch):
    """A stand-in Groq. Set `.respond` to a function of the request; every
    request the code under test makes is recorded in `.sent`."""
    class _Groq:
        sent: list[dict] = []
        respond = staticmethod(lambda req: httpx.Response(200, json={
            "choices": [{"message": {"content":
                "GSTR-1 is due on the 11th.\nSource: CGST Act, Section 37"}}],
            "usage": {"total_tokens": 42}}))

    stub = _Groq()
    stub.sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        stub.sent.append(json.loads(request.content))
        return stub.respond(request)

    transport = httpx.MockTransport(handler)

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    # The module's own reference, so nothing else in the process is touched.
    monkeypatch.setattr(groq_text.httpx, "AsyncClient", _client)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)
    return stub


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(assistant_router.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _ask(client):
    return client.post("/api/assistant", json={"question": "When is GSTR-1 due?"})


def _refuse(status, code=None, message=""):
    body = {"error": {"message": message, "type": "invalid_request_error"}}
    if code:
        body["error"]["code"] = code
    return lambda req: httpx.Response(status, json=body)


# ── The model ────────────────────────────────────────────────────────────────

def test_the_assistant_asks_for_the_model_groq_text_model_names(groq, client, monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "some-current-model")

    r = _ask(client)

    assert r.status_code == 200, r.text
    assert groq.sent[-1]["model"] == "some-current-model", (
        "the assistant hardcoded its model, so GROQ_TEXT_MODEL could not move it")
    data = r.json()["data"]
    assert data == {"answer": "GSTR-1 is due on the 11th.",
                    "source": "Source: CGST Act, Section 37"}


def test_with_nothing_configured_every_groq_text_caller_asks_for_one_default(groq, client):
    _ask(client)
    import routers.document_intelligence_v1 as v1
    assert groq.sent[-1]["model"] == groq_text.DEFAULT_TEXT_MODEL == v1._GROQ_TEXT_MODEL


# ── What a refusal says ──────────────────────────────────────────────────────

def test_a_retired_model_is_named_and_not_called_transient(groq, client):
    # The sentence names the model THIS SERVER asked for (groq_text.text_model(),
    # unset here so it is the shared default) — never a model name parsed out of
    # Groq's own message text, which is why the stub's body below is free to name
    # anything and the assertion is pinned to the configured default instead of a
    # literal that would go stale the next time that default moves.
    model = groq_text.DEFAULT_TEXT_MODEL
    groq.respond = _refuse(400, "model_decommissioned",
                           f"The model `{model}` has been decommissioned.")
    r = _ask(client)

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert f"no longer serves the model '{model}'" in detail, detail
    assert "GROQ_TEXT_MODEL" in detail and "retrying will not help" in detail
    assert "try again" not in detail.lower()


def test_a_refused_key_says_the_key_must_be_replaced(groq, client):
    groq.respond = _refuse(401, "invalid_api_key", "Invalid API Key")
    detail = _ask(client).json()["detail"]
    assert "GROQ_API_KEY" in detail and "retrying will not help" in detail, detail


def test_a_rate_limit_says_to_wait(groq, client):
    groq.respond = _refuse(429, "rate_limit_exceeded", "Rate limit reached")
    r = _ask(client)
    assert r.status_code == 502 and "rate-limiting" in r.json()["detail"]


def test_a_timeout_is_a_504_with_a_sentence_not_a_bare_500(groq, client):
    def _slow(req):
        raise httpx.ReadTimeout("timed out", request=req)
    groq.respond = _slow

    r = _ask(client)

    assert r.status_code == 504, r.text
    assert "did not answer within 30 seconds" in r.json()["detail"]


def test_groqs_own_status_and_body_are_logged_before_answering(groq, client, caplog):
    groq.respond = _refuse(400, "model_decommissioned", "gone")
    with caplog.at_level("ERROR", logger="caflow.ai.groq"):
        _ask(client)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "HTTP 400" in logged and "model_decommissioned" in logged, logged
    assert "gsk_test" not in logged, "the key must never reach a log line"


def test_a_missing_key_names_the_setting(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = _ask(client)
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


# ── The copilot ──────────────────────────────────────────────────────────────

MESSAGES = [{"role": "system", "content": "brief"},
            {"role": "user", "content": "Which workflows have failed recently?"}]


@pytest.fixture
def live_copilot(monkeypatch, groq):
    monkeypatch.setattr(copilot, "_GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(copilot, "_USE_MOCK", False)
    return copilot.AICopilotService.__new__(copilot.AICopilotService)


def test_the_copilot_asks_the_configured_model_and_counts_real_tokens(live_copilot, groq, monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "some-current-model")
    reply, tokens = asyncio.run(live_copilot._call_groq(MESSAGES))

    assert groq.sent[-1]["model"] == "some-current-model"
    assert tokens == 42, "tokens_used = 0 on every production reply was the tell"
    assert reply.startswith("GSTR-1 is due")


def test_a_copilot_that_cannot_reach_the_model_says_so_instead_of_answering_from_a_script(
        live_copilot, groq):
    groq.respond = _refuse(400, "model_decommissioned", "gone")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(live_copilot._call_groq(MESSAGES))

    assert exc.value.status_code == 502
    assert "no longer serves the model" in exc.value.detail
    scripted = live_copilot._mock_response(MESSAGES[-1]["content"])
    assert scripted not in str(exc.value.detail)


def test_outside_mock_mode_a_copilot_with_no_key_says_so(live_copilot, monkeypatch):
    monkeypatch.setattr(copilot, "_GROQ_API_KEY", "")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(live_copilot._call_groq(MESSAGES))
    assert exc.value.status_code == 503 and "GROQ_API_KEY" in exc.value.detail


def test_mock_mode_with_no_key_still_answers_from_the_script(monkeypatch):
    """The one case the canned text is for: local dev and the test suite,
    where there is no model to ask."""
    monkeypatch.setattr(copilot, "_GROQ_API_KEY", "")
    monkeypatch.setattr(copilot, "_USE_MOCK", True)
    svc = copilot.AICopilotService.__new__(copilot.AICopilotService)
    reply, tokens = asyncio.run(svc._call_groq(MESSAGES))
    assert tokens == 0 and reply == svc._mock_response(MESSAGES[-1]["content"])

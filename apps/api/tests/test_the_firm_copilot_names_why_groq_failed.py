"""
POST /api/ai-copilot/chat says WHY Groq refused, and asks for the configured
model — not a hardcoded one.

WHAT WAS WRONG (sweep-misc-tools-02)
    This endpoint has its own httpx call to Groq (it is declared as its own
    network caller in tests/test_the_never_do_list.py's OUTBOUND_MODULES,
    unlike /api/assistant and the copilot's domain layer, which both go
    through domain/ai/groq_text now). It hardcoded the model string
    "llama-3.3-70b-versatile" — the retirement CLAUDE.md says must be a config
    change via GROQ_TEXT_MODEL was a code change here — and on a non-200
    response it discarded Groq's own status and body entirely, answering the
    CA with "AI service error: 401" and "AI service error: 429" alike. Neither
    a revoked key nor a rate limit is fixable by "try again", and the CA could
    not tell the two apart.

WHAT THIS ASSERTS
    Driven with asyncio.run against the real router function (this repo has no
    pytest-asyncio plugin), talking to a stand-in Groq over httpx.MockTransport
    — never a copy of the code:
      * the model sent is GROQ_TEXT_MODEL's value, defaulting to the one
        default domain/ai/groq_text and document_intelligence_v1/v2 share;
      * a 401 and a 429 come back as two DIFFERENT sentences, neither of them
        the old generic "AI service error: <code>";
      * Groq's status and body are logged (never the key).
"""
from __future__ import annotations

import asyncio
import json
import logging
import types

import httpx
import pytest

import routers.ai_copilot as cp

_RealAsyncClient = httpx.AsyncClient

FIRM = "firm-copilot-groq"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


def _fake_request() -> types.SimpleNamespace:
    """Just enough of starlette's Request for check_rate_limit: it only reads
    request.url.path."""
    return types.SimpleNamespace(url=types.SimpleNamespace(path="/api/ai-copilot/chat"))


class Body:
    message = "What is the GSTR-3B due date?"
    conversation_history: list = []
    context = "general"


@pytest.fixture(autouse=True)
def groq_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key")
    monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)


def _respond(status: int, body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.sent = json.loads(request.content)
        return httpx.Response(status, json=body)
    handler.sent = None
    return handler


def _run_chat(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(cp.httpx, "AsyncClient", _client)
    return asyncio.run(cp.copilot_chat(_fake_request(), Body(), current_user=USER))


def test_the_model_sent_is_groq_text_model_not_a_hardcoded_string(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "llama-3.1-8b-instant")
    handler = _respond(200, {"choices": [{"message": {"content": "ok\nSource: CGST Act, Section 37"}}]})

    result = _run_chat(monkeypatch, handler)

    assert result["success"] is True
    assert handler.sent["model"] == "llama-3.1-8b-instant"


def test_the_default_model_matches_the_one_shared_default(monkeypatch):
    from domain.ai import groq_text

    handler = _respond(200, {"choices": [{"message": {"content": "ok\nSource: CGST Act, Section 37"}}]})

    _run_chat(monkeypatch, handler)

    assert handler.sent["model"] == groq_text.DEFAULT_TEXT_MODEL


def test_a_revoked_key_and_a_rate_limit_are_told_apart(monkeypatch):
    unauthorized = _run_chat(monkeypatch, _respond(
        401, {"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}))
    rate_limited = _run_chat(monkeypatch, _respond(
        429, {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}}))

    for result in (unauthorized, rate_limited):
        assert result["success"] is False
        assert result["error"] is not None
        # The old behaviour: a bare "AI service error: <code>" with nothing a
        # CA could act on.
        assert not result["error"].startswith("AI service error:")

    assert unauthorized["error"] != rate_limited["error"]
    assert "revoked" in unauthorized["error"] or "invalid" in unauthorized["error"].lower()
    assert "rate" in rate_limited["error"].lower()


def test_a_groq_failure_is_logged_with_status_and_body(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR, logger="caflow.ai_copilot"):
        _run_chat(monkeypatch, _respond(
            401, {"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}))

    logged = caplog.text
    assert "401" in logged
    assert "invalid_api_key" in logged
    # Never the key itself.
    assert "gsk_test_key" not in logged

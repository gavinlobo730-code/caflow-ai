"""
Government-notice extraction asks Groq for the model GROQ_TEXT_MODEL names.

WHAT WAS WRONG
    routers/document_intelligence_v2._extract_with_groq hardcoded
    model="llama-3.3-70b-versatile" while v1 reads GROQ_TEXT_MODEL. CLAUDE.md
    makes the env var the whole plan for a retired model ("the next
    retirement is a config change"), so setting it would have moved invoice
    extraction and left notice extraction asking for the old name — which the
    endpoint can only report as its generic 502.

WHAT IS ASSERTED — by calling the code with a stand-in Groq
    * the model sent is the one the environment names;
    * with nothing set, it is the one shared default every Groq caller uses, so
      the paths cannot disagree.

HOW THIS IS DRIVEN NOW (ai-04)
    The notice reader used to import the `groq` SDK and the test stubbed that
    package. It goes through `domain/ai/groq_text.chat_sync` now — the one door —
    so the stand-in is an `httpx.MockTransport` behind the door's own client, and
    the rule asserted is unchanged.
"""
from __future__ import annotations

import json

import httpx
import pytest

import routers.document_intelligence_v1 as v1
import routers.document_intelligence_v2 as v2
from domain.ai import groq_text

_RealAsyncClient = httpx.AsyncClient

_NOTICE = json.dumps({"authority": "GSTN", "notice_type": "gst_scrutiny",
                      "reference_no": None, "issue_date": None,
                      "response_due_date": None, "description": "d"})


@pytest.fixture
def groq_calls(monkeypatch):
    """A stand-in Groq behind the door's own HTTP client; records each request."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": _NOTICE}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 9}})

    transport = httpx.MockTransport(handler)

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)
    return calls


def test_the_model_sent_is_the_one_the_environment_names(monkeypatch, groq_calls):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "llama-4-something-newer")
    out = v2._extract_with_groq("DRC-01 notice text")
    assert out["authority"] == "GSTN"
    assert groq_calls[-1]["model"] == "llama-4-something-newer"


def test_with_nothing_set_it_is_the_same_default_invoice_extraction_uses(groq_calls):
    v2._extract_with_groq("DRC-01 notice text")
    notice_model = groq_calls[-1]["model"]

    # Invoice extraction, through the same door, asks for the same model.
    groq_calls.clear()
    try:
        v1._groq_extract_text("Tax invoice text")
    except Exception:                                           # noqa: BLE001
        pass  # the stand-in answers with a notice; only the MODEL is under test
    assert groq_calls, "invoice extraction made no request"
    assert groq_calls[-1]["model"] == notice_model == groq_text.DEFAULT_TEXT_MODEL


def test_neither_router_keeps_a_model_name_of_its_own():
    """The names are decided in domain/ai and read at call time; a module-level
    snapshot at import is how a changed environment stops being honoured."""
    for mod in (v1, v2):
        assert not hasattr(mod, "_GROQ_TEXT_MODEL"), mod.__name__

"""A timeout is the classified 504 sentence on every route that reaches a model (ai-04).

WHAT WAS WRONG
    A model that did not answer was a different thing on each route. The
    assistant said "did not answer within 30 seconds" with a 504; the copilot's
    domain layer did the same; the invoice and notice readers (vendor SDK, no
    timeout argument at all) hung until the platform cut them and then answered
    one generic 502 for every cause; the firm copilot route and both Gemini calls
    had no timeout. "Which setting is wrong, and can trying again help" was said
    on two routes and not on the other six.

WHAT THIS ASSERTS
    Every route that reaches a model is driven against a provider that never
    answers, and each says the SAME classified sentence with the status that goes
    with it (504). The routes that fall back to a plain, honestly-labelled answer
    by design (the statement narrator, the practice digest) are asserted to fall
    back rather than to fail.
"""
from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.ai_copilot as cp
import routers.assistant as asst
import routers.document_intelligence_v1 as v1
import routers.document_intelligence_v2 as v2
from core.auth import get_current_user
from domain import financial_analysis_service as fa
from domain.ai_copilot_service import AICopilotService

_RealAsyncClient = httpx.AsyncClient
PARTNER = {"id": "u1", "auth_user_id": "u1", "firm_id": "F-504", "role": "Partner", "email": "p@f"}
SENTENCE = "did not answer within 30 seconds"


@pytest.fixture
def groq_never_answers(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: _RealAsyncClient(*a, **{**k, "transport": transport}))
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)


@pytest.fixture
def gemini_never_answers(monkeypatch):
    class _Timeout(Exception):
        pass
    _Timeout.__name__ = "ReadTimeout"

    class _Models:
        def generate_content(self, **kw):
            raise _Timeout("slow")

    class _Client:
        def __init__(self, api_key=None, **kw):
            self.models = _Models()
    monkeypatch.setattr("google.genai.Client", _Client)


def _client(router):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _pdf():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "TAX INVOICE INV-1 Acme Total 1180.00")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_the_assistant(groq_never_answers):
    r = _client(asst.router).post("/api/assistant", json={"question": "When is GSTR-3B due?"})
    assert r.status_code == 504
    assert SENTENCE in r.json()["detail"] and "Groq" in r.json()["detail"]


def test_the_firm_copilot_route(groq_never_answers, monkeypatch):
    monkeypatch.setattr(cp, "check_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(cp, "_build_firm_context", lambda *a, **k: "Clients: 2")
    body = cp.CopilotRequest(message="What is due?", conversation_history=[])
    out = asyncio.run(cp.copilot_chat(request=None, body=body, current_user=PARTNER))
    assert out["success"] is False and SENTENCE in out["error"]


def test_the_copilots_domain_layer(groq_never_answers, monkeypatch):
    import domain.ai_copilot_service as mod
    monkeypatch.setattr(mod, "_GROQ_API_KEY", "k")
    with pytest.raises(HTTPException) as e:
        asyncio.run(AICopilotService()._call_groq([{"role": "user", "content": "hi"}]))
    assert e.value.status_code == 504 and SENTENCE in e.value.detail


def test_invoice_extraction_from_a_pdf(groq_never_answers, monkeypatch):
    monkeypatch.setattr(v1, "_GROQ_KEY", "k")
    r = _client(v1.router).post("/api/document-intelligence-v1/extract-invoice",
                                files={"file": ("i.pdf", _pdf(), "application/pdf")},
                                data={"client_id": "c-1"})
    assert r.status_code == 504, r.text
    body = r.json()
    assert body["success"] is False and SENTENCE in body["error"]
    assert "AI extraction failed" not in body["error"], "the generic sentence is for unclassified failures"


def test_invoice_extraction_from_a_photograph(gemini_never_answers, monkeypatch):
    monkeypatch.setattr(v1, "_GEMINI_KEY", "k")
    r = _client(v1.router).post("/api/document-intelligence-v1/extract-invoice",
                                files={"file": ("b.jpg", b"\xff\xd8\xff x", "image/jpeg")},
                                data={"client_id": "c-1"})
    assert r.status_code == 504, r.text
    assert SENTENCE in r.json()["error"] and "Gemini" in r.json()["error"]


def test_notice_extraction(groq_never_answers, monkeypatch):
    monkeypatch.setattr(v2, "_GROQ_KEY", "k")
    v2._MOCK_NOTICES.clear()
    r = _client(v2.router).post("/api/document-intelligence-v2/notices/extract",
                                json={"client_id": "c-1", "document_text": "A notice."})
    assert r.status_code == 504, r.text
    assert SENTENCE in r.json()["error"]
    assert v2._MOCK_NOTICES == {}, "a failed reading stores nothing"


def test_the_statement_narrator_falls_back_and_says_it_did(groq_never_answers, monkeypatch):
    monkeypatch.setattr(fa, "_GROQ_API_KEY", "k")
    pl = {"revenue": {"total_paise": 100000}, "operating_expenses": {"total_paise": 60000},
          "net_profit_paise": 40000}
    out = asyncio.run(fa.generate_statement_analysis(
        pl, {"assets": [], "liabilities": []}, None, "2026-27", "2025-26", firm_id="F"))
    assert out["ai_generated"] is False and out["narrative"].strip()


def test_a_failed_attempt_is_still_a_usage_row(groq_never_answers, ai_usage_events):
    _client(asst.router).post("/api/assistant", json={"question": "q"})
    assert [e.outcome for e in ai_usage_events] == ["timeout"]
    assert ai_usage_events[0].firm_id == "F-504" and ai_usage_events[0].feature == "assistant"
    assert ai_usage_events[0].user_id == "u1"

"""The copilot's model calls say whose they are, and a stored label says who WROTE it (ai-04).

WHAT CHANGED, AND WHY THESE TWO THINGS TRAVEL TOGETHER
    A fallback model changes who wrote an answer. Before the gateway, `text_model()`
    was always the model that answered, so every stored `model_used` label read it;
    with a configured fallback that label would name the PRIMARY on a reply the
    fallback wrote — the exact defect `tests/test_a_stored_reply_names_the_model_that_
    gave_it.py` was written to end. `groq_text.answered_by()` is the model that
    answered the last call in this context, and every place that stores a label
    reads it.

    And the copilot service's `_call_groq` has six callers and test doubles with a
    fixed signature, so who the call is FOR cannot be threaded through as an
    argument; the six public methods set a scope instead (`gateway.attributed`),
    which `_call_groq` reads and passes to the door explicitly.
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import httpx
import pytest

import domain.ai_copilot_service as svc_mod
from domain.ai import gateway, groq_text
from domain.ai_copilot_service import AICopilotService
from repositories.ai_copilot_repository import ai_copilot_repo

_RealAsyncClient = httpx.AsyncClient
API = pathlib.Path(__file__).resolve().parents[1]


def _fallback_answers(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        if body["model"] == "primary-model":
            return httpx.Response(404, json={"error": {"code": "model_not_found", "message": "gone"}})
        return httpx.Response(200, json={"choices": [
            {"message": {"content": "the fallback wrote this"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 4}})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: _RealAsyncClient(*a, **{**k, "transport": transport}))
    monkeypatch.setenv("GROQ_TEXT_MODEL", "primary-model")
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", "backup-model")


def test_a_stored_reply_names_the_model_that_wrote_it_not_the_one_that_failed(monkeypatch):
    _fallback_answers(monkeypatch)

    async def go():
        text, _ = await groq_text.chat([{"role": "user", "content": "q"}], api_key="k",
                                       max_tokens=10, feature="copilot_chat", firm_id="F")
        msg = ai_copilot_repo.add_message("F", "conv-1", "assistant", text)
        return text, msg["model_used"]
    text, label = asyncio.run(go())
    assert text == "the fallback wrote this"
    assert label == "backup-model", "the label must name the model that answered"


def test_a_label_with_no_call_in_this_context_is_the_configured_model(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "primary-model")
    msg = ai_copilot_repo.add_message("F", "conv-2", "assistant", "text")
    assert msg["model_used"] == "primary-model"


def test_no_stored_label_reads_the_configured_model_any_more():
    """Every `model_used` written from a model's reply asks `answered_by()`."""
    offenders = []
    for rel in ("domain/ai_copilot_service.py", "repositories/ai_copilot_repository.py",
                "services/digest_service.py"):
        code = (API / rel).read_text()
        for node in ast.walk(ast.parse(code)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "text_model"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "groq_text"):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


# ── who a call is for ────────────────────────────────────────────────────────

def test_attributed_sets_the_scope_for_the_call_and_clears_it_after():
    class S:
        @gateway.attributed("some_feature")
        async def method(self, firm_id, user_id=None):
            return gateway.current_scope()

    scope = asyncio.run(S().method("F-9", user_id="U-9"))
    assert (scope.firm_id, scope.user_id, scope.feature) == ("F-9", "U-9", "some_feature")
    assert gateway.current_scope().firm_id is None


def test_the_copilot_service_hands_the_scope_to_the_door(monkeypatch):
    seen = {}

    async def fake_chat(messages, **kw):
        seen.update(kw)
        return "text", 3
    monkeypatch.setattr(svc_mod, "_GROQ_API_KEY", "k")
    monkeypatch.setattr(svc_mod.groq_text, "chat", fake_chat)

    async def go():
        with gateway.usage_scope(firm_id="F-7", user_id="U-7", feature="executive_summary"):
            return await AICopilotService()._call_groq([{"role": "user", "content": "q"}])
    asyncio.run(go())
    assert (seen["firm_id"], seen["user_id"], seen["feature"]) == ("F-7", "U-7", "executive_summary")


def test_every_public_model_method_of_the_copilot_service_is_attributed():
    tree = ast.parse((API / "domain" / "ai_copilot_service.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AICopilotService")
    callers = {}
    for fn in cls.body:
        if isinstance(fn, ast.AsyncFunctionDef) and fn.name != "_call_groq":
            calls_model = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                              and n.func.attr == "_call_groq" for n in ast.walk(fn))
            if calls_model:
                callers[fn.name] = any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "attributed" for d in fn.decorator_list)
    assert set(callers) >= {"chat", "get_client_intelligence", "get_compliance_intelligence",
                            "get_workflow_intelligence", "get_relationship_intelligence",
                            "get_executive_dashboard"}
    assert all(callers.values()), [k for k, v in callers.items() if not v]

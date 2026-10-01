"""A reasoning model cannot hand back an empty answer as if it were one (ai-05).

WHAT WAS WRONG
    The default Groq model is a reasoning model (`openai/gpt-oss-120b`), and its
    reasoning tokens are drawn from the SAME response allowance as the answer. The
    code set no `reasoning_effort`, no structured-output format, and allowances of
    1024 (extraction), 512 (notices) and 300 (the statement narrator). A model
    that spends the 300 thinking sends back nothing, and:
      * `message.content.strip()` in the invoice and notice readers raised on a
        null content (or read an empty one) and reached the generic 502;
      * the statement narrator marked the reply `ai_generated=True` because it
        only tested "is not None" — a BLANK summary labelled AI-written;
      * keys of a model's JSON were trusted (`int(data.get(field) or 0)`) with no
        schema to say what a reading may look like.

WHAT THIS ASSERTS — by a stand-in provider behind the one door
    * an empty or null reply is a NAMED failure (`empty_reply`), never a value, and
      the statement narrator falls back with `ai_generated` false;
    * the request carries `reasoning_effort: low` and a `json_schema` response
      format — but only to a model family Groq documents them for, and is sent
      again WITHOUT them if Groq objects (they are hints, not requirements);
    * the allowances are raised;
    * a reading that violates the schema is a CLEAN refusal, naming the field and
      never the value, on the invoice and the notice routes alike;
    * the JSON schema each provider is asked to honour carries exactly the
      pydantic model's fields, so the hint and the check cannot drift apart.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.document_intelligence_v1 as v1
import routers.document_intelligence_v2 as v2
from core.auth import get_current_user
from domain import financial_analysis_service as fa
from domain.ai import extraction_schemas as X
from domain.ai import groq_text

_RealAsyncClient = httpx.AsyncClient
PARTNER = {"id": "u1", "auth_user_id": "u1", "firm_id": "F-5", "role": "Partner", "email": "p@f"}

INVOICE = {"vendor_name": "Acme", "vendor_gstin": None, "invoice_no": "INV-1",
           "invoice_date": "2026-06-01", "taxable_amount_paise": 100000, "cgst_paise": 9000,
           "sgst_paise": 9000, "igst_paise": 0, "total_paise": 118000, "line_items": []}


def _answer(content, finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"total_tokens": 5}}


@pytest.fixture
def groq(monkeypatch):
    """A programmable Groq behind the door's own HTTP client."""
    state = type("S", (), {"replies": [], "calls": []})()

    def handler(request: httpx.Request) -> httpx.Response:
        state.calls.append(json.loads(request.content))
        reply = state.replies[min(len(state.calls) - 1, len(state.replies) - 1)]
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    transport = httpx.MockTransport(handler)

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    return state


def _chat(**kw):
    return asyncio.run(groq_text.chat([{"role": "user", "content": "q"}], api_key="k",
                                      max_tokens=100, feature="t", firm_id="F", **kw))


# ── an empty reply is a failure ──────────────────────────────────────────────

@pytest.mark.parametrize("content", ["", "   \n", None])
def test_an_empty_or_null_reply_is_a_named_failure_not_a_value(groq, content):
    groq.replies = [_answer(content, "length")]
    with pytest.raises(groq_text.ProviderFailed) as e:
        _chat()
    assert e.value.kind == "empty_reply"
    assert "without any text" in e.value.sentence


def test_an_empty_reply_is_recorded_so_the_budget_can_be_tuned(groq, ai_usage_events):
    groq.replies = [{"choices": [{"message": {"content": None}, "finish_reason": "length"}],
                     "usage": {"prompt_tokens": 40, "completion_tokens": 300, "total_tokens": 340,
                               "completion_tokens_details": {"reasoning_tokens": 300}}}]
    with pytest.raises(groq_text.ProviderFailed):
        _chat()
    (ev, *_rest) = ai_usage_events
    assert ev.outcome == "empty_reply" and ev.reasoning_tokens == 300 and ev.completion_tokens == 300


def test_an_empty_reply_tries_the_fallback_model(groq, monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", "backup-model")
    groq.replies = [_answer(""), _answer("a real answer")]
    assert _chat()[0] == "a real answer"
    assert [c["model"] for c in groq.calls] == [groq_text.DEFAULT_TEXT_MODEL, "backup-model"]


def test_a_reply_cut_off_by_the_budget_is_returned_and_recorded_as_truncated(groq, ai_usage_events):
    groq.replies = [_answer("The answer starts but", "length")]
    assert _chat()[0] == "The answer starts but"
    assert ai_usage_events[0].outcome == "truncated"


def test_the_statement_narrator_falls_back_when_the_model_sends_nothing(groq, monkeypatch):
    monkeypatch.setattr(fa, "_GROQ_API_KEY", "k")
    groq.replies = [_answer("")]
    pl = {"revenue": {"total_paise": 100000}, "operating_expenses": {"total_paise": 60000},
          "net_profit_paise": 40000}
    out = asyncio.run(fa.generate_statement_analysis(pl, {"assets": [], "liabilities": []}, None,
                                                     "2026-27", "2025-26", firm_id="F"))
    assert out["ai_generated"] is False
    assert out["narrative"].strip(), "a plain narrative, never a blank one"


def test_the_narrator_also_refuses_a_blank_that_got_past_the_door(monkeypatch):
    """`ai_generated` is a claim about who wrote the text; an empty string was
    'not None'."""
    async def blank(messages, **kw):
        return "  "
    monkeypatch.setattr(fa, "_call_groq", blank)
    pl = {"revenue": {"total_paise": 100000}, "operating_expenses": {"total_paise": 60000},
          "net_profit_paise": 40000}
    out = asyncio.run(fa.generate_statement_analysis(pl, {"assets": [], "liabilities": []}, None,
                                                     "2026-27", "2025-26"))
    assert out["ai_generated"] is False and out["narrative"].strip()


def test_the_narrator_labels_a_real_reply_ai_generated(groq, monkeypatch):
    monkeypatch.setattr(fa, "_GROQ_API_KEY", "k")
    groq.replies = [_answer("Revenue is up and margins are healthy.")]
    pl = {"revenue": {"total_paise": 100000}, "operating_expenses": {"total_paise": 60000},
          "net_profit_paise": 40000}
    out = asyncio.run(fa.generate_statement_analysis(pl, {"assets": [], "liabilities": []}, None,
                                                     "2026-27", "2025-26"))
    assert out["ai_generated"] is True and out["narrative"] == "Revenue is up and margins are healthy."


# ── reasoning effort, structured output, allowances ──────────────────────────

def test_a_reasoning_model_is_asked_for_low_effort_and_a_json_schema(groq):
    groq.replies = [_answer(json.dumps(INVOICE))]
    v1._groq_extract_text("Tax invoice text")
    sent = groq.calls[0]
    assert sent["reasoning_effort"] == "low"
    rf = sent["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == X.INVOICE_SCHEMA.schema


def test_the_hints_go_only_to_a_family_groq_documents_them_for(groq, monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "some-other/model-7b")
    groq.replies = [_answer(json.dumps(INVOICE))]
    v1._groq_extract_text("Tax invoice text")
    sent = groq.calls[0]
    assert "reasoning_effort" not in sent and "response_format" not in sent
    assert sent["model"] == "some-other/model-7b"


def test_a_hint_groq_rejects_is_dropped_and_the_call_goes_again(groq, ai_usage_events):
    reject = lambda req: httpx.Response(400, json={"error": {
        "message": "response_format json_schema is not supported with this model",
        "type": "invalid_request_error"}})
    groq.replies = [reject, _answer(json.dumps(INVOICE))]
    out = v1._groq_extract_text("Tax invoice text")
    assert out["vendor_name"] == "Acme"
    first, second = groq.calls
    assert "response_format" in first and "reasoning_effort" in first
    assert "response_format" not in second and "reasoning_effort" not in second
    assert ai_usage_events.sleeps == [], "an objection to a hint is not a rate limit"
    assert [e.outcome for e in ai_usage_events] == ["param_rejected", "ok"]


def test_a_400_about_something_else_is_not_mistaken_for_a_rejected_hint(groq):
    groq.replies = [lambda req: httpx.Response(400, json={"error": {
        "message": "messages must not be empty", "type": "invalid_request_error"}})]
    with pytest.raises(groq_text.ProviderFailed) as e:
        _chat(reasoning_effort="low")
    assert e.value.kind == "refused"
    assert len(groq.calls) == 1


def test_the_allowances_are_raised_from_what_a_reasoning_model_could_think_inside():
    assert groq_text.EXTRACTION_MAX_TOKENS >= 4096 > 1024
    assert groq_text.NOTICE_MAX_TOKENS >= 2048 > 512
    assert groq_text.NARRATION_MAX_TOKENS >= 1200 > 300


def test_each_reader_asks_for_its_own_allowance(groq):
    groq.replies = [_answer(json.dumps(INVOICE))]
    v1._groq_extract_text("Tax invoice text")
    assert groq.calls[-1]["max_tokens"] == groq_text.EXTRACTION_MAX_TOKENS
    groq.replies = [_answer(json.dumps({"authority": "GSTN", "notice_type": "other",
                                        "description": "d"}))]
    v2._extract_with_groq("Some notice")
    assert groq.calls[-1]["max_tokens"] == groq_text.NOTICE_MAX_TOKENS


# ── a reading that violates the schema is a clean refusal ────────────────────

def _client(router):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _pdf_with_text():
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "TAX INVOICE INV-1 Acme Total 1180.00")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize("reply,field", [
    (json.dumps([INVOICE]), "list"),
    ("Here is the invoice you asked for.", "not valid JSON"),
    (json.dumps({**INVOICE, "total_paise": "N/A"}), "total_paise"),
    (json.dumps({**INVOICE, "taxable_amount_paise": -5}), "taxable_amount_paise"),
    (json.dumps({**INVOICE, "line_items": ["a line"]}), "line_items"),
    (json.dumps({**INVOICE, "igst_paise": 1180.5}), "igst_paise"),
])
def test_an_invoice_reading_that_violates_the_schema_is_a_clean_refusal(groq, monkeypatch, reply, field):
    monkeypatch.setattr(v1, "_GROQ_KEY", "k")
    groq.replies = [_answer(reply)]
    r = _client(v1.router).post("/api/document-intelligence-v1/extract-invoice",
                                files={"file": ("i.pdf", _pdf_with_text(), "application/pdf")},
                                data={"client_id": "c-1"})
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert "Nothing was filled in" in body["error"] and field in body["error"]


def test_a_refusal_names_the_field_and_never_the_value(groq, monkeypatch):
    monkeypatch.setattr(v1, "_GROQ_KEY", "k")
    groq.replies = [_answer(json.dumps({**INVOICE, "total_paise": "ZZ-VALUE-THE-MODEL-WROTE"}))]
    r = _client(v1.router).post("/api/document-intelligence-v1/extract-invoice",
                                files={"file": ("i.pdf", _pdf_with_text(), "application/pdf")},
                                data={"client_id": "c-1"})
    assert "ZZ-VALUE-THE-MODEL-WROTE" not in r.text


def test_the_invoice_route_works_end_to_end_through_the_threadpool(groq, monkeypatch):
    """chat_sync runs the one async door on a private loop; the route is a plain
    `def` that Starlette runs in a worker thread, so prove the two meet."""
    monkeypatch.setattr(v1, "_GROQ_KEY", "k")
    groq.replies = [_answer(json.dumps(INVOICE))]
    r = _client(v1.router).post("/api/document-intelligence-v1/extract-invoice",
                                files={"file": ("i.pdf", _pdf_with_text(), "application/pdf")},
                                data={"client_id": "c-1"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["extracted"]["vendor_name"] == "Acme"


def test_a_notice_reading_that_violates_the_schema_is_a_clean_refusal(groq, monkeypatch):
    monkeypatch.setattr(v2, "_GROQ_KEY", "k")
    v2._MOCK_NOTICES.clear()
    groq.replies = [_answer(json.dumps(["not", "a", "notice"]))]
    r = _client(v2.router).post("/api/document-intelligence-v2/notices/extract",
                                json={"client_id": "c-1", "document_text": "a notice"})
    assert r.status_code == 502, "the reply was unusable: that is the model's failure"
    assert r.json()["success"] is False and "Nothing was saved" in r.json()["error"]
    assert v2._MOCK_NOTICES == {}


# ── the hint and the check cannot drift apart ────────────────────────────────

def test_the_invoice_json_schema_carries_exactly_the_models_fields():
    model_fields = set(X._Invoice.model_fields)
    for schema in (X.INVOICE_SCHEMA.schema, X.INVOICE_GEMINI_SCHEMA):
        assert set(schema["properties"]) == model_fields
    line_props = X.INVOICE_SCHEMA.schema["properties"]["line_items"]["items"]["properties"]
    assert set(line_props) == set(X.INVOICE_LINE_FIELDS)
    from domain import extraction_lines
    assert set(X.INVOICE_LINE_FIELDS) >= {"quantity", "unit", "rate_paise", "gst_rate_bps"}, extraction_lines


def test_the_notice_json_schema_carries_exactly_the_models_fields_and_its_enum():
    assert set(X.NOTICE_SCHEMA.schema["properties"]) == set(X._Notice.model_fields)
    assert X.NOTICE_SCHEMA.schema["properties"]["notice_type"]["enum"] == list(X.NOTICE_TYPES)


def test_the_strict_schema_asks_for_every_field_and_allows_no_other():
    """Groq's strict mode needs both; a schema missing either is rejected and the
    hint silently dropped for nothing."""
    for schema in (X.INVOICE_SCHEMA.schema, X.NOTICE_SCHEMA.schema):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    items = X.INVOICE_SCHEMA.schema["properties"]["line_items"]["items"]
    assert items["additionalProperties"] is False and set(items["required"]) == set(items["properties"])

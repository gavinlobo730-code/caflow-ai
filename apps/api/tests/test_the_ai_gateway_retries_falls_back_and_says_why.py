"""One gateway for every model call: timeout, bounded retry, fallback, usage (ai-04).

WHAT WAS WRONG
    Eight places called a model and each had its own idea of a failure. Only the
    assistant and the copilot's domain layer classified a refusal into a sentence;
    the invoice and notice readers used the vendor SDK with no timeout argument
    and answered one generic 502; both Gemini calls had neither a timeout nor a
    retry; the firm copilot route and the statement narrator built their own
    httpx requests and swallowed everything. There was one model and no second
    route, so a model Groq retired (it did, on 29-09-2026) took a whole feature
    out, and nobody could say afterwards how often, how slowly or at what cost.

WHAT THIS ASSERTS — against a stand-in provider, never a copy of the code
    * a 5xx is retried after a pause and, still failing, falls to the SECOND model
      named by GROQ_TEXT_MODEL_FALLBACK; a rate limit honours a short Retry-After
      and does not wait out a long one; a retired model moves on without a retry;
      a revoked key STOPS (a second model behind the same key fails the same way);
    * a timeout is the classified 504 sentence on every route that reaches a model;
    * with no fallback configured nothing is invented: one model, as before;
    * when every model fails the sentence is the PRIMARY model's;
    * one usage row per ATTEMPT, sharing a call id, with counts, a model name, a
      latency and an outcome — and no field that could hold what was said;
    * the same policy governs Gemini, behind its own door;
    * NO module outside `domain/ai` imports a provider SDK or names a provider
      host, so a ninth call site cannot appear beside the gateway.
"""
from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import pathlib

import httpx
import pytest

from domain.ai import gateway, gemini_vision, groq_text

API = pathlib.Path(__file__).resolve().parents[1]
OK_BODY = {"choices": [{"message": {"content": "an answer"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                     "completion_tokens_details": {"reasoning_tokens": 3}}}
MSG = [{"role": "user", "content": "When is GSTR-3B due?"}]
FIRM = "firm-gw"


def script(*steps):
    """A stand-in Groq. Each step is an Exception to raise or (status, body[, headers]);
    the last repeats. Returns (transport, the request bodies it saw)."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        step = steps[min(len(calls) - 1, len(steps) - 1)]
        if isinstance(step, type) and issubclass(step, httpx.TimeoutException):
            raise step("timed out", request=request)
        status, body, *rest = step
        return httpx.Response(status, json=body, headers=rest[0] if rest else None)

    return httpx.MockTransport(handler), calls


TIMEOUT = httpx.ReadTimeout


def _ask(transport, **kw):
    return asyncio.run(groq_text.chat(
        MSG, api_key="k", max_tokens=100, transport=transport,
        feature="test_feature", firm_id=FIRM, **kw))


def _err(status, code=None, message="x"):
    return (status, {"error": {"code": code, "message": message}})


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "primary-model")
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)


@pytest.fixture
def with_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", "backup-model")


# ── the policy, as a table ───────────────────────────────────────────────────

@pytest.mark.parametrize("outcome,attempt,expected", [
    (gateway.RATE_LIMITED, 1, gateway.RETRY), (gateway.RATE_LIMITED, 2, gateway.NEXT_MODEL),
    (gateway.SERVER_ERROR, 1, gateway.RETRY), (gateway.SERVER_ERROR, 2, gateway.NEXT_MODEL),
    (gateway.NETWORK, 1, gateway.RETRY),
    (gateway.TIMEOUT, 1, gateway.NEXT_MODEL),
    (gateway.MODEL_GONE, 1, gateway.NEXT_MODEL),
    (gateway.EMPTY, 1, gateway.NEXT_MODEL),
    (gateway.BAD_SHAPE, 1, gateway.NEXT_MODEL),
    (gateway.AUTH, 1, gateway.STOP),
    (gateway.TOO_LONG, 1, gateway.STOP),
    (gateway.REFUSED, 1, gateway.STOP),
])
def test_what_to_do_after_each_kind_of_failure(outcome, attempt, expected):
    assert gateway.decide(outcome, attempt) == expected


def test_every_outcome_the_gateway_can_name_has_a_decision():
    for outcome in gateway.OUTCOMES - {gateway.OK, gateway.TRUNCATED, gateway.PARAM_REJECTED}:
        assert gateway.decide(outcome, 1) in (gateway.RETRY, gateway.NEXT_MODEL, gateway.STOP)


def test_backoff_doubles_to_a_cap_and_honours_a_short_retry_after_only():
    assert [gateway.backoff_delay(n) for n in (1, 2, 3, 4, 5)] == [0.5, 1.0, 2.0, 4.0, 4.0]
    assert gateway.backoff_delay(1, retry_after=2.0) == 2.0
    assert gateway.backoff_delay(1, retry_after=0.1) == 0.5          # never shorter than ours
    assert gateway.backoff_delay(1, retry_after=gateway.RETRY_AFTER_CAP_S + 1) is None


def test_the_model_chain_is_the_primary_then_the_configured_fallbacks_once_each(monkeypatch):
    assert groq_text.model_chain() == ["primary-model"]
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", " backup-a , primary-model,backup-b,backup-a ,")
    assert groq_text.model_chain() == ["primary-model", "backup-a", "backup-b"]


def test_no_fallback_model_is_built_in():
    """A default nobody has called is the 29-09-2026 mistake again."""
    src = (API / "domain" / "ai" / "groq_text.py").read_text()
    assert "FALLBACK_MODEL =" not in src and "DEFAULT_FALLBACK" not in src
    assert groq_text.fallback_models() == []


# ── retry and fallback ───────────────────────────────────────────────────────

def test_a_503_is_retried_then_falls_back_to_the_second_model(with_fallback, ai_usage_events):
    transport, calls = script(_err(503), _err(503), (200, OK_BODY))
    text, tokens = _ask(transport)

    assert (text, tokens) == ("an answer", 18)
    assert [c["model"] for c in calls] == ["primary-model", "primary-model", "backup-model"]
    assert ai_usage_events.sleeps == [0.5], "one pause, before the one retry"
    assert [e.outcome for e in ai_usage_events] == ["provider_error", "provider_error", "ok"]
    assert [e.fallback_used for e in ai_usage_events] == [False, False, True]
    assert [e.attempt for e in ai_usage_events] == [1, 2, 3]
    assert len({e.call_id for e in ai_usage_events}) == 1


def test_a_transient_503_that_clears_does_not_touch_the_fallback(with_fallback):
    transport, calls = script(_err(503), (200, OK_BODY))
    assert _ask(transport)[0] == "an answer"
    assert [c["model"] for c in calls] == ["primary-model", "primary-model"]


def test_a_retired_model_moves_on_without_a_retry_or_a_pause(with_fallback, ai_usage_events):
    transport, calls = script(_err(404, "model_not_found", "gone"), (200, OK_BODY))
    assert _ask(transport)[0] == "an answer"
    assert [c["model"] for c in calls] == ["primary-model", "backup-model"]
    assert ai_usage_events.sleeps == []
    assert ai_usage_events[0].outcome == "model_gone"
    assert ai_usage_events[0].provider_code == "model_not_found"


def test_a_revoked_key_stops_it_even_with_a_fallback(with_fallback):
    """A second model behind the same key fails the same way."""
    transport, calls = script(_err(401, "invalid_api_key", "bad key"), (200, OK_BODY))
    with pytest.raises(groq_text.ProviderFailed) as e:
        _ask(transport)
    assert len(calls) == 1
    assert e.value.provider_status == 401 and "GROQ_API_KEY" in e.value.sentence


def test_a_prompt_that_is_too_long_stops_it_too(with_fallback):
    transport, calls = script(_err(413, "request_too_large", "big"), (200, OK_BODY))
    with pytest.raises(groq_text.ProviderFailed):
        _ask(transport)
    assert len(calls) == 1


def test_a_rate_limit_waits_out_a_short_retry_after(ai_usage_events):
    transport, calls = script((429, {"error": {"code": "rate_limit_exceeded"}}, {"retry-after": "2"}),
                              (200, OK_BODY))
    assert _ask(transport)[0] == "an answer"
    assert ai_usage_events.sleeps == [2.0]
    assert len(calls) == 2


def test_a_rate_limit_with_a_long_retry_after_is_not_waited_out_in_a_request(
        with_fallback, ai_usage_events):
    transport, calls = script((429, {"error": {"code": "rate_limit_exceeded"}}, {"retry-after": "60"}),
                              (200, OK_BODY))
    assert _ask(transport)[0] == "an answer"
    assert ai_usage_events.sleeps == []
    assert [c["model"] for c in calls] == ["primary-model", "backup-model"]


def test_with_no_fallback_configured_a_failing_model_is_the_end(ai_usage_events):
    transport, calls = script(_err(503))
    with pytest.raises(groq_text.ProviderFailed) as e:
        _ask(transport)
    assert len(calls) == gateway.MAX_ATTEMPTS_PER_MODEL
    assert "unavailable" in e.value.sentence


def test_when_every_model_fails_the_sentence_is_the_primary_models(with_fallback):
    """The primary is the one the operator configured, and a retired primary is a
    standing fault whose remedy matters more than a fallback's transient one."""
    transport, calls = script(_err(404, "model_not_found", "gone"), _err(503))
    with pytest.raises(groq_text.ProviderFailed) as e:
        _ask(transport)
    assert "no longer serves the model 'primary-model'" in e.value.sentence
    assert "GROQ_TEXT_MODEL" in e.value.sentence


def test_the_total_budget_stops_a_call_that_has_run_out_of_time(with_fallback, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(gateway, "clock", lambda: now[0])

    def handler(request):
        now[0] += 25.0                       # every attempt takes 25 seconds
        return httpx.Response(503, json={"error": {}})

    calls = []
    transport = httpx.MockTransport(lambda r: (calls.append(1), handler(r))[1])
    with pytest.raises(groq_text.ProviderFailed):
        _ask(transport)
    assert len(calls) == 2, "the fallback was not tried: there was no time left"


# ── a timeout is a classified 504 ────────────────────────────────────────────

def test_a_timeout_is_the_classified_504_sentence(ai_usage_events):
    transport, calls = script(TIMEOUT)
    with pytest.raises(groq_text.ProviderFailed) as e:
        _ask(transport)
    assert e.value.http_status == 504
    assert "did not answer within 30 seconds" in e.value.sentence
    assert len(calls) == 1, "a second wait of the same length is the budget gone"
    assert ai_usage_events[0].outcome == "timeout"


def test_a_timeout_falls_to_the_fallback_when_there_is_one(with_fallback):
    transport, calls = script(TIMEOUT, (200, OK_BODY))
    assert _ask(transport)[0] == "an answer"
    assert [c["model"] for c in calls] == ["primary-model", "backup-model"]


def test_the_model_that_answered_is_the_one_a_stored_label_names(with_fallback):
    transport, _ = script(_err(404, "model_not_found", "gone"), (200, OK_BODY))

    async def go():
        await groq_text.chat(MSG, api_key="k", max_tokens=10, transport=transport,
                             feature="t", firm_id=FIRM)
        return groq_text.answered_by()
    assert asyncio.run(go()) == "backup-model"


def test_with_nothing_answered_the_label_is_the_configured_model():
    assert groq_text.answered_by() == "primary-model"


# ── the usage record ─────────────────────────────────────────────────────────

def test_a_usage_row_carries_counts_a_model_a_latency_and_an_outcome(ai_usage_events):
    transport, _ = script((200, OK_BODY))
    _ask(transport, user_id="u-1")
    (ev,) = ai_usage_events
    assert (ev.firm_id, ev.user_id, ev.feature, ev.provider) == (FIRM, "u-1", "test_feature", "groq")
    assert (ev.model, ev.attempt, ev.outcome, ev.http_status) == ("primary-model", 1, "ok", 200)
    assert (ev.prompt_tokens, ev.completion_tokens, ev.reasoning_tokens, ev.total_tokens) == (11, 7, 3, 18)
    assert ev.latency_ms >= 0 and ev.fallback_used is False


def test_a_usage_row_has_no_field_that_could_hold_what_was_said(ai_usage_events):
    names = {f.name for f in dataclasses.fields(gateway.UsageEvent)}
    for forbidden in ("prompt", "messages", "content", "reply", "text", "completion",
                      "message", "client", "client_id", "gstin", "pan", "error"):
        assert forbidden not in names, forbidden
    assert names == {
        "firm_id", "user_id", "feature", "provider", "model", "call_id", "attempt", "outcome",
        "latency_ms", "fallback_used", "http_status", "provider_code", "prompt_tokens",
        "completion_tokens", "reasoning_tokens", "total_tokens", "input_units"}


def test_a_usage_row_never_contains_the_prompt_or_the_answer(ai_usage_events):
    secret = "ZZ-SECRET-QUESTION-27AAAAA0000A1Z5"
    transport, _ = script(_err(503), (200, {**OK_BODY, "choices": [
        {"message": {"content": "ZZ-SECRET-ANSWER"}, "finish_reason": "stop"}]}))
    asyncio.run(groq_text.chat([{"role": "user", "content": secret}], api_key="k",
                               max_tokens=10, transport=transport, feature="t", firm_id=FIRM))
    blob = " ".join(repr(e) for e in ai_usage_events)
    assert "ZZ-SECRET" not in blob and "27AAAAA0000A1Z5" not in blob


def test_a_failing_usage_sink_never_costs_anybody_an_answer():
    def boom(_ev):
        raise RuntimeError("the usage table is down")
    gateway.set_sink(boom)
    transport, _ = script((200, OK_BODY))
    assert _ask(transport)[0] == "an answer"


def test_the_default_sink_writes_a_row_only_with_a_firm_and_a_database(monkeypatch):
    written = []
    monkeypatch.setattr(gateway, "_writer", type("W", (), {
        "submit": staticmethod(lambda fn, ev: written.append(ev))})())
    gateway.set_sink(None)
    ev = gateway.UsageEvent(firm_id=FIRM, user_id=None, feature="f", provider="groq", model="m",
                            call_id="c", attempt=1, outcome="ok", latency_ms=1)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    gateway.record(ev)
    assert written == [], "no database, no row"
    monkeypatch.setenv("SUPABASE_URL", "http://db")
    gateway.record(dataclasses.replace(ev, firm_id=None))
    assert written == [], "no firm, no row"
    gateway.record(ev)
    assert written == [ev]


# ── Gemini, behind its own door, under the same policy ───────────────────────

class _GemResp:
    def __init__(self, text, usage=(5, 3, 2, 10)):
        self.text = text
        self.usage_metadata = type("U", (), dict(
            prompt_token_count=usage[0], candidates_token_count=usage[1],
            thoughts_token_count=usage[2], total_token_count=usage[3]))()


class _APIError(Exception):
    def __init__(self, code, status="X", message="m"):
        super().__init__(f"{code} {status}")
        self.code, self.status, self.message = code, status, message


class _ReadTimeout(Exception):
    pass


@pytest.fixture
def gemini(monkeypatch):
    """A programmable stand-in for google.genai.Client."""
    steps: list = []
    seen: list[dict] = []

    class _Models:
        def generate_content(self, **kwargs):
            seen.append(kwargs)
            step = steps[min(len(seen) - 1, len(steps) - 1)]
            if isinstance(step, Exception):
                raise step
            return step

    class _Client:
        def __init__(self, api_key=None, **kw):
            seen_clients.append({"api_key": api_key, **kw})
            self.models = _Models()

    seen_clients: list[dict] = []
    monkeypatch.setattr("google.genai.Client", _Client)
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gem-primary")
    monkeypatch.delenv("GEMINI_VISION_MODEL_FALLBACK", raising=False)
    return type("G", (), {"steps": steps, "seen": seen, "clients": seen_clients})


def _see(**kw):
    return gemini_vision.generate(api_key="k", images=[b"p1", b"p2"], mime="image/png",
                                  prompt="read it", feature="invoice_extraction",
                                  firm_id=FIRM, **kw)


def test_gemini_has_a_timeout_of_its_own(gemini):
    gemini.steps.append(_GemResp("{}"))
    _see()
    assert gemini.clients[0]["http_options"].timeout == 30_000


def test_a_gemini_503_is_retried_then_falls_back(gemini, monkeypatch, ai_usage_events):
    monkeypatch.setenv("GEMINI_VISION_MODEL_FALLBACK", "gem-backup")
    gemini.steps += [_APIError(503, "UNAVAILABLE"), _APIError(503, "UNAVAILABLE"), _GemResp("read ok")]
    assert _see() == "read ok"
    assert [c["model"] for c in gemini.seen] == ["gem-primary", "gem-primary", "gem-backup"]
    assert ai_usage_events.sleeps == [0.5]
    assert [e.outcome for e in ai_usage_events] == ["provider_error", "provider_error", "ok"]
    assert ai_usage_events[-1].input_units == 2 and ai_usage_events[-1].provider == "gemini"
    assert ai_usage_events[-1].reasoning_tokens == 2


def test_a_gemini_timeout_is_the_classified_504(gemini):
    gemini.steps.append(_ReadTimeout("slow"))
    with pytest.raises(gateway.ProviderFailed) as e:
        _see()
    assert e.value.http_status == 504
    assert "AI provider (Gemini) did not answer within 30 seconds" in e.value.sentence
    assert len(gemini.seen) == 1


def test_a_retired_gemini_model_is_named_with_its_own_setting(gemini):
    gemini.steps.append(_APIError(404, "NOT_FOUND", "no longer available to new users"))
    with pytest.raises(gateway.ProviderFailed) as e:
        _see()
    assert "no longer serves the model 'gem-primary'" in e.value.sentence
    assert "GEMINI_VISION_MODEL" in e.value.sentence and "GROQ" not in e.value.sentence


def test_an_empty_gemini_reply_is_a_failure_not_an_empty_page(gemini):
    gemini.steps.append(_GemResp(""))
    with pytest.raises(gateway.ProviderFailed) as e:
        _see()
    assert e.value.kind == "empty_reply"


def test_a_gemini_reply_with_no_text_part_is_an_empty_reply_not_a_crash(gemini):
    class _Blocked:
        usage_metadata = None

        @property
        def text(self):
            raise ValueError("no text part")
    gemini.steps.append(_Blocked())
    with pytest.raises(gateway.ProviderFailed) as e:
        _see()
    assert e.value.kind == "empty_reply"


def test_a_schema_gemini_rejects_is_dropped_and_the_call_goes_again(gemini):
    gemini.steps += [_APIError(400, "INVALID_ARGUMENT", "response_schema is not supported"),
                     _GemResp("read ok")]
    assert _see(response_schema={"type": "OBJECT"}) == "read ok"
    first, second = gemini.seen
    assert first["config"].response_schema is not None
    assert getattr(second.get("config"), "response_schema", None) is None


def test_a_schema_the_sdk_refuses_to_build_is_dropped_and_the_call_goes_again(gemini, monkeypatch):
    """A response schema the SDK cannot turn into a request (a version that spells
    it differently) must cost the structured-output HINT, not the reading."""
    from google.genai import types
    real = types.GenerateContentConfig

    def picky(**kw):
        if "response_schema" in kw:
            raise ValueError("unsupported schema shape for this SDK version")
        return real(**kw)
    monkeypatch.setattr(types, "GenerateContentConfig", picky)
    gemini.steps.append(_GemResp("read ok"))
    assert _see(response_schema={"type": "OBJECT"}) == "read ok"
    assert len(gemini.seen) == 1, "the request that failed to BUILD was never sent"


def test_an_unclassified_gemini_failure_stops_and_says_so_without_leaking_the_exception(gemini):
    gemini.steps.append(RuntimeError("internal: project 42 quota detail"))
    with pytest.raises(gateway.ProviderFailed) as e:
        _see()
    assert "project 42" not in e.value.sentence and e.value.kind == "refused"
    assert len(gemini.seen) == 1


# ── the one-door rule ────────────────────────────────────────────────────────

#: The only modules that may import a provider SDK or name a provider host.
GATEWAY_FILES = {"domain/ai/groq_text.py", "domain/ai/gemini_vision.py"}
PROVIDER_IMPORTS = ("groq", "google.genai", "google.generativeai", "openai", "anthropic")
PROVIDER_HOSTS = ("api.groq.com", "generativelanguage.googleapis.com")


def _production_files():
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/", ".venv", "venv")):
            continue
        yield rel, path.read_text()


def _imports(src: str) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            out.add(base)
            out |= {f"{base}.{a.name}" for a in node.names}
    return out


def test_no_module_outside_the_gateway_imports_a_provider_sdk():
    scanned, offenders = 0, []
    for rel, src in _production_files():
        scanned += 1
        for name in _imports(src):
            if any(name == p or name.startswith(p + ".") for p in PROVIDER_IMPORTS) \
                    and rel not in GATEWAY_FILES:
                offenders.append(f"{rel} imports {name}")
    assert scanned > 200, "the scan found almost nothing — it would pass vacuously"
    assert not offenders, offenders


def test_no_module_outside_the_gateway_names_a_provider_host():
    offenders = [f"{rel} names {h}" for rel, src in _production_files() for h in PROVIDER_HOSTS
                 if h in src and rel not in GATEWAY_FILES]
    assert not offenders, offenders


def test_the_scan_would_catch_a_module_that_did():
    """Negative control for the two scans above: they fire on a planted import."""
    planted = "def f():\n    from groq import Groq\n    import google.genai\n"
    assert any(n == "groq" or n.startswith("groq.") for n in _imports(planted))
    assert any(n.startswith("google.genai") for n in _imports(planted))


DOOR_CALLS = {"chat", "chat_detailed", "chat_sync", "generate"}


def test_every_call_to_a_door_says_which_firm_and_which_feature():
    """The usage row is only as good as its attribution. A call that does not pass
    `firm_id=` and `feature=` writes a row nobody can bill or a row nobody writes."""
    found, missing = 0, []
    for rel, src in _production_files():
        if rel in GATEWAY_FILES or "groq_text" not in src and "gemini_vision" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id in ("groq_text", "gemini_vision")):
                continue
            if node.func.attr not in DOOR_CALLS:
                continue
            found += 1
            kws = {k.arg for k in node.keywords}
            if not {"firm_id", "feature"} <= kws:
                missing.append(f"{rel}:{node.lineno} {owner.id}.{node.func.attr}")
    assert found >= 8, f"only {found} door calls found — the scan has probably stopped working"
    assert not missing, missing

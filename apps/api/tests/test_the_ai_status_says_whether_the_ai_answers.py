"""The AI path is proven live, or it says it is unverified (ai-06).

WHAT WAS WRONG
    The Groq default changed on 29-09-2026 after a live `model_not_found` on the
    old one, to a name nobody had called, and no successful live call was recorded
    anywhere. Production on 01-10-2026 held no `ai_usage_events` row and two
    stored assistant replies — both from 27-09-2026, both `tokens_used = 0`, the
    canned mock text. Nothing in the product could say whether the AI answers.

WHAT THIS ASSERTS
    * the gateway remembers, per provider, the last attempt and the last answer,
      and reads `unverified` (never `ok`) until something has been asked;
    * a probe makes ONE small real call through the one door, leaves the usage
      row, sends nothing about any client, and reports a failure as a RESULT in
      the gateway's own sentence — a retired model, a revoked key and an empty
      reply are three different answers;
    * a missing key is `skipped`, not a failure, and nothing is sent;
    * the Partner's status reads this firm's history only;
    * `/health` carries one word per provider, makes no network call and never
      turns into a 503 because a provider is failing;
    * the probe route is Partner-only, behind `mfa_guard`, and rate limited AFTER
      the permission check so a refusal spends nothing.
"""
from __future__ import annotations

import inspect
import json
import struct
import zlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, mfa_guard
from domain.ai import gateway, gemini_vision, groq_text, probe
from domain.ai.redaction import contains_identifier
from middleware import rate_limit
from services import ai_status_service
from tests.e2e_harness import FakeDB

FIRM = "firm-status"
OTHER = "firm-other"

OK_BODY = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 14, "completion_tokens": 2, "total_tokens": 16,
                     "completion_tokens_details": {"reasoning_tokens": 1}}}


def _event(provider="groq", outcome=gateway.OK, model="m", tokens=16, latency=120):
    return gateway.UsageEvent(
        firm_id=FIRM, user_id=None, feature="probe", provider=provider, model=model,
        call_id="c", attempt=1, outcome=outcome, latency_ms=latency, total_tokens=tokens)


def _groq(*steps):
    """A stand-in Groq returning each step in turn (the last repeats)."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        step = steps[min(len(seen) - 1, len(steps) - 1)]
        status, body = step
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), seen


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k-groq")
    monkeypatch.setenv("GEMINI_API_KEY", "k-gem")
    monkeypatch.setenv("GROQ_TEXT_MODEL", "groq-primary")
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gem-primary")
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)
    monkeypatch.delenv("GEMINI_VISION_MODEL_FALLBACK", raising=False)


# ── what the gateway has seen ────────────────────────────────────────────────

def test_a_provider_nobody_has_asked_is_unverified_not_ok():
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_UNVERIFIED
    assert gateway.last_success("groq") is None and gateway.last_attempt("groq") is None


def test_an_unset_key_is_its_own_state_and_outranks_everything():
    gateway.record(_event())
    assert gateway.provider_status("groq", configured=False) == gateway.STATUS_NOT_CONFIGURED


def test_an_answered_attempt_makes_the_provider_ok():
    gateway.record(_event(model="groq-primary"))
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_OK
    seen = gateway.last_success("groq")
    assert (seen.model, seen.total_tokens, seen.outcome) == ("groq-primary", 16, "ok")


def test_a_reply_cut_off_by_the_budget_is_still_an_answer():
    gateway.record(_event(outcome=gateway.TRUNCATED))
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_OK


def test_a_later_failure_is_not_hidden_by_an_earlier_success():
    gateway.record(_event())
    gateway.record(_event(outcome=gateway.MODEL_GONE))
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_FAILING
    # ...and the earlier answer is still remembered, because it is a real fact.
    assert gateway.last_success("groq").outcome == "ok"
    gateway.record(_event())
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_OK


def test_the_hint_the_gateway_drops_says_nothing_about_the_provider():
    """A 400 that names `response_format` is the gateway's own housekeeping — the
    call goes again without it — and must not turn a healthy provider to failing,
    or a working one to ok."""
    gateway.record(_event(outcome=gateway.PARAM_REJECTED))
    assert gateway.last_attempt("groq") is None
    gateway.record(_event())
    gateway.record(_event(outcome=gateway.PARAM_REJECTED))
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_OK


def test_the_two_providers_are_remembered_apart():
    gateway.record(_event(provider="groq"))
    gateway.record(_event(provider="gemini", outcome=gateway.AUTH))
    assert gateway.provider_status("groq", True) == gateway.STATUS_OK
    assert gateway.provider_status("gemini", True) == gateway.STATUS_FAILING


def test_a_sink_that_fails_does_not_stop_the_attempt_being_noted():
    def boom(_ev):
        raise RuntimeError("database down")
    gateway.set_sink(boom)
    gateway.record(_event())
    assert gateway.last_success("groq") is not None


def test_what_is_remembered_has_no_field_that_could_hold_what_was_said():
    import dataclasses
    assert {f.name for f in dataclasses.fields(gateway.Seen)} == {
        "provider", "model", "outcome", "at", "latency_ms", "total_tokens", "http_status"}


def test_a_restart_forgets_and_the_honest_answer_is_unverified():
    gateway.record(_event())
    gateway.reset_health()
    assert gateway.provider_status("groq", True) == gateway.STATUS_UNVERIFIED


# ── the probe: Groq ──────────────────────────────────────────────────────────

def test_a_groq_probe_makes_one_small_real_call_and_leaves_its_row(ai_usage_events):
    transport, seen = _groq((200, OK_BODY))
    result = probe.probe_groq(firm_id=FIRM, user_id="u-1", transport=transport)
    assert result.ok and result.state == "ok"
    assert result.model == "groq-primary" and result.answered_by == "groq-primary"
    assert result.total_tokens == 16 and result.latency_ms is not None
    assert len(seen) == 1, "one request, not a loop"
    row = ai_usage_events[-1]
    assert (row.feature, row.firm_id, row.provider, row.outcome) == ("probe", FIRM, "groq", "ok")
    assert gateway.provider_status("groq", True) == gateway.STATUS_OK


def test_what_a_probe_sends_is_a_fixed_sentence_with_no_identifier_in_it():
    transport, seen = _groq((200, OK_BODY))
    probe.probe_groq(firm_id=FIRM, transport=transport)
    messages = seen[0]["messages"]
    assert messages == [{"role": "user", "content": probe.PROMPT}]
    assert not contains_identifier(json.dumps(seen[0]))
    assert seen[0]["max_tokens"] == probe.GROQ_MAX_TOKENS >= 256, (
        "the default model spends reasoning out of the answer's allowance; a handful "
        "of tokens would come back EMPTY and report a healthy provider as broken")


def test_a_retired_model_is_reported_as_a_result_in_the_gateways_own_words(ai_usage_events):
    transport, _ = _groq((404, {"error": {"code": "model_not_found", "message": "gone"}}))
    result = probe.probe_groq(firm_id=FIRM, transport=transport)
    assert (result.state, result.kind) == ("failed", gateway.MODEL_GONE)
    assert "groq-primary" in result.sentence and "GROQ_TEXT_MODEL" in result.sentence
    assert ai_usage_events[-1].outcome == gateway.MODEL_GONE
    assert gateway.provider_status("groq", True) == gateway.STATUS_FAILING


def test_a_revoked_key_is_a_different_answer_from_a_retired_model():
    transport, _ = _groq((401, {"error": {"code": "invalid_api_key", "message": "bad"}}))
    revoked = probe.probe_groq(firm_id=FIRM, transport=transport)
    transport, _ = _groq((404, {"error": {"code": "model_not_found", "message": "gone"}}))
    retired = probe.probe_groq(firm_id=FIRM, transport=transport)
    assert revoked.kind == gateway.AUTH and retired.kind == gateway.MODEL_GONE
    assert revoked.sentence != retired.sentence
    assert "GROQ_API_KEY" in revoked.sentence


def test_an_empty_reply_is_a_failure_not_a_healthy_provider():
    empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
             "usage": {"total_tokens": 512}}
    transport, _ = _groq((200, empty))
    result = probe.probe_groq(firm_id=FIRM, transport=transport)
    assert (result.state, result.kind) == ("failed", gateway.EMPTY)


def test_a_missing_key_is_skipped_and_nothing_is_sent(monkeypatch, ai_usage_events):
    monkeypatch.delenv("GROQ_API_KEY")

    def refuse(request):
        raise AssertionError("a request was sent with no key")
    result = probe.probe_groq(firm_id=FIRM, transport=httpx.MockTransport(refuse))
    assert result.state == "skipped" and not result.ok
    assert "GROQ_API_KEY" in result.sentence
    assert list(ai_usage_events) == [], "nothing was asked, so nothing is recorded"
    assert gateway.provider_status("groq", probe.configured("groq")) == gateway.STATUS_NOT_CONFIGURED


# ── the probe: Gemini ────────────────────────────────────────────────────────

class _GemResp:
    def __init__(self, text, total=12):
        self.text = text
        self.usage_metadata = type("U", (), dict(
            prompt_token_count=8, candidates_token_count=2,
            thoughts_token_count=2, total_token_count=total))()


class _APIError(Exception):
    def __init__(self, code, status="X", message="m"):
        super().__init__(f"{code} {status}")
        self.code, self.status, self.message = code, status, message


@pytest.fixture
def gemini(monkeypatch):
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
            self.models = _Models()

    monkeypatch.setattr("google.genai.Client", _Client)
    return type("G", (), {"steps": steps, "seen": seen})


def test_a_gemini_probe_reads_a_plain_picture_and_leaves_its_row(gemini, ai_usage_events):
    gemini.steps.append(_GemResp("OK"))
    result = probe.probe_gemini(firm_id=FIRM, user_id="u-1")
    assert result.ok and result.answered_by == "gem-primary" and result.total_tokens == 12
    assert len(gemini.seen) == 1
    row = ai_usage_events[-1]
    assert (row.feature, row.provider, row.outcome, row.input_units) == ("probe", "gemini", "ok", 1)
    assert gateway.provider_status("gemini", True) == gateway.STATUS_OK


def test_the_picture_a_probe_sends_is_a_valid_plain_white_square():
    png = probe._white_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos:pos + 4])
        kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + data) & 0xFFFFFFFF, f"bad CRC on {kind!r}"
        chunks[kind] = data
        pos += 12 + length
    assert list(chunks) == [b"IHDR", b"IDAT", b"IEND"]
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    pixels = zlib.decompress(chunks[b"IDAT"])
    assert (width, height) == (64, 64) and len(pixels) == 64 * 65
    assert set(pixels[1:65]) == {255}, "the first row is white"


def test_a_gemini_probe_that_fails_is_a_result_with_the_providers_own_setting_named(gemini):
    gemini.steps.append(_APIError(404, "NOT_FOUND", "no longer available to new users"))
    result = probe.probe_gemini(firm_id=FIRM)
    assert (result.state, result.kind) == ("failed", gateway.MODEL_GONE)
    assert "GEMINI_VISION_MODEL" in result.sentence and "GROQ" not in result.sentence


def test_gemini_without_a_key_is_skipped_and_says_what_it_would_have_read(monkeypatch, gemini):
    monkeypatch.delenv("GEMINI_API_KEY")
    result = probe.probe_gemini(firm_id=FIRM)
    assert result.state == "skipped" and "GEMINI_API_KEY" in result.sentence
    assert gemini.seen == []


def test_an_unknown_provider_is_a_programming_error():
    with pytest.raises(KeyError):
        probe.probe("openai", firm_id=FIRM)
    with pytest.raises(KeyError):
        probe.configured("openai")


def test_the_probe_module_builds_no_request_and_imports_no_sdk():
    src = inspect.getsource(probe)
    for forbidden in ("api.groq.com", "generativelanguage", "import httpx", "from google",
                      "import google", "import groq"):
        assert forbidden not in src, f"the probe must go through the gateway doors ({forbidden})"


# ── the Partner's status ─────────────────────────────────────────────────────

def _row(firm, provider, outcome, at, model="m", feature="assistant"):
    return {"firm_id": firm, "provider": provider, "outcome": outcome, "created_at": at,
            "model": model, "feature": feature, "latency_ms": 100, "total_tokens": 10}


def _provider(answer, name):
    return next(p for p in answer["providers"] if p["provider"] == name)


def test_with_no_database_the_stored_history_is_unread_and_says_so():
    answer = ai_status_service.status(None, FIRM)
    groq = _provider(answer, "groq")
    assert groq["this_firm"] is None and "no database" in groq["this_firm_unread"]
    assert groq["status"] == gateway.STATUS_UNVERIFIED


def test_the_history_is_this_firms_own_and_the_latest_answered_call():
    db = FakeDB()
    db.seed("ai_usage_events", _row(FIRM, "groq", "ok", "2026-10-01T10:00:00+00:00", "old"))
    db.seed("ai_usage_events", _row(FIRM, "groq", "ok", "2026-10-01T12:00:00+00:00", "new"))
    db.seed("ai_usage_events", _row(FIRM, "groq", "model_gone", "2026-10-01T13:00:00+00:00", "dead"))
    db.seed("ai_usage_events", _row(OTHER, "groq", "ok", "2026-10-02T09:00:00+00:00", "theirs"))
    db.seed("ai_usage_events", _row(FIRM, "gemini", "ok", "2026-10-01T09:00:00+00:00", "gem"))
    groq = _provider(ai_status_service.status(db, FIRM), "groq")
    assert groq["this_firm"]["last_answered"]["model"] == "new"
    assert groq["this_firm"]["last_attempt"]["model"] == "dead", (
        "a later failure is shown beside the earlier answer, not hidden by it")
    assert "theirs" not in json.dumps(ai_status_service.status(db, FIRM)), (
        "another firm's call is never shown")
    assert _provider(ai_status_service.status(db, FIRM), "gemini")["this_firm"][
        "last_answered"]["model"] == "gem"


def test_a_firm_with_no_calls_has_none_and_that_is_not_a_clean_bill():
    answer = ai_status_service.status(FakeDB(), FIRM)
    groq = _provider(answer, "groq")
    assert groq["this_firm"] == {"last_answered": None, "last_attempt": None}
    assert groq["this_firm_unread"] is None
    assert any("not that every feature works" in s for s in answer["not_covered"])


def test_the_gateways_own_housekeeping_row_is_not_the_last_attempt():
    db = FakeDB()
    db.seed("ai_usage_events", _row(FIRM, "groq", "ok", "2026-10-01T10:00:00+00:00", "answered"))
    db.seed("ai_usage_events", _row(FIRM, "groq", "param_rejected", "2026-10-01T11:00:00+00:00", "hint"))
    groq = _provider(ai_status_service.status(db, FIRM), "groq")
    assert groq["this_firm"]["last_attempt"]["model"] == "answered"


def test_a_history_that_cannot_be_read_is_said_so_and_does_not_raise():
    class _Broken:
        def table(self, *_a):
            raise RuntimeError("postgrest down")
    groq = _provider(ai_status_service.status(_Broken(), FIRM), "groq")
    assert groq["this_firm"] is None and "could not be read" in groq["this_firm_unread"]


def test_every_status_word_is_labelled_and_toned_by_the_server():
    assert set(ai_status_service.PRESENTATION) == {
        gateway.STATUS_OK, gateway.STATUS_FAILING, gateway.STATUS_UNVERIFIED,
        gateway.STATUS_NOT_CONFIGURED}
    for label, tone in ai_status_service.PRESENTATION.values():
        assert label and tone in {"ready", "problem", "attention", "neutral"}
    groq = _provider(ai_status_service.status(None, FIRM), "groq")
    assert (groq["status"], groq["status_tone"]) == ("unverified", "attention"), (
        "an unasked provider is flagged for attention, never shown as ready")
    gateway.record(_event())
    groq = _provider(ai_status_service.status(None, FIRM), "groq")
    assert (groq["status"], groq["status_label"], groq["status_tone"]) == (
        "ok", "Answering", "ready")


def test_a_probe_result_carries_the_tone_it_is_drawn_in():
    base = dict(provider="groq", model="m")
    assert probe.ProbeResult(state="ok", **base).as_dict()["tone"] == "note"
    assert probe.ProbeResult(state="failed", **base).as_dict()["tone"] == "problem"
    assert probe.ProbeResult(state="skipped", **base).as_dict()["tone"] == "attention"


def test_the_status_carries_the_configured_models_and_the_fallback_that_is_not_built_in(monkeypatch):
    answer = ai_status_service.status(None, FIRM)
    groq = _provider(answer, "groq")
    assert groq["model"] == "groq-primary" and groq["fallback_models"] == []
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", "backup-a, backup-b")
    assert _provider(ai_status_service.status(None, FIRM), "groq")["fallback_models"] == [
        "backup-a", "backup-b"]


# ── /health ──────────────────────────────────────────────────────────────────

def test_health_words_are_one_word_per_provider_and_nothing_else():
    words = ai_status_service.health_words()
    assert set(words) == {"groq", "gemini"}
    assert set(words.values()) <= {"ok", "failing", "unverified", "not_configured"}
    assert words == {"groq": "unverified", "gemini": "unverified"}


def test_health_reports_not_configured_when_there_is_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    assert ai_status_service.health_words()["gemini"] == "not_configured"


def test_health_words_make_no_database_or_network_call():
    src = inspect.getsource(ai_status_service.health_words)
    assert ".table(" not in src and "httpx" not in src and "get_service_supabase" not in src


def test_the_health_route_carries_the_ai_words_and_stays_200_when_a_provider_is_failing():
    from main import app
    gateway.record(_event(outcome=gateway.AUTH))
    res = TestClient(app, raise_server_exceptions=False).get("/health")
    assert res.status_code == 200, "a failing provider must never take the health check down"
    ai = res.json()["data"]["ai"]
    assert ai["groq"] == "failing"
    assert "model" not in json.dumps(ai) and "groq-primary" not in json.dumps(ai), (
        "/health is unauthenticated: words only, the model names are behind a login")


# ── the routes ───────────────────────────────────────────────────────────────

def _user(role, uid):
    return {"id": uid, "firm_id": FIRM, "role": role, "email": f"{uid}@f.test",
            "auth_user_id": f"auth-{uid}"}


def _client(user):
    from routers import ai_status
    app = FastAPI()
    app.include_router(ai_status.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_probe(monkeypatch):
    import routers.ai_status as mod
    calls: list[tuple] = []

    def _probe(provider, *, firm_id, user_id=None):
        calls.append((provider, firm_id, user_id))
        return probe.ProbeResult(provider=provider, state="ok", model="m", answered_by="m",
                                 latency_ms=5, total_tokens=3)
    monkeypatch.setattr(mod.ai_probe, "probe", _probe)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: calls.append(("audit", a, k)))
    return calls


def test_a_partner_reads_the_status():
    res = _client(_user("Partner", "p1")).get("/api/ai-status")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert [p["provider"] for p in body["data"]["providers"]] == ["groq", "gemini"]


@pytest.mark.parametrize("role", ["Manager", "Executive", "Reviewer"])
def test_nobody_below_a_partner_reads_the_status_or_runs_the_probe(role, fake_probe):
    c = _client(_user(role, "u"))
    assert c.get("/api/ai-status").status_code == 403
    assert c.post("/api/ai-status/probe?provider=groq").status_code == 403
    assert fake_probe == [], "no model call was made for a refused caller"


def test_a_refused_caller_spends_none_of_the_firms_probe_allowance(fake_probe):
    """The limiter is declared AFTER rbac(), so a permission refusal costs nothing."""
    exec_client = _client(_user("Executive", "ex"))
    for _ in range(6):
        assert exec_client.post("/api/ai-status/probe?provider=groq").status_code == 403
    partner = _client(_user("Partner", "p1"))
    assert partner.post("/api/ai-status/probe?provider=groq").status_code == 200


def test_the_probe_is_rate_limited_per_user(fake_probe):
    c = _client(_user("Partner", "p1"))
    cap = rate_limit.user_limit(rate_limit.BUCKETS["probe"][0])
    codes = [c.post("/api/ai-status/probe?provider=gemini").status_code for _ in range(cap + 1)]
    assert codes[:cap] == [200] * cap and codes[cap] == 429


def test_the_probe_asks_for_one_provider_and_only_a_known_one(fake_probe):
    c = _client(_user("Partner", "p1"))
    assert c.post("/api/ai-status/probe").status_code == 422
    assert c.post("/api/ai-status/probe?provider=openai").status_code == 422
    assert fake_probe == []


def test_a_probe_answers_with_the_result_and_audits_without_any_text(fake_probe):
    c = _client(_user("Partner", "p1"))
    res = c.post("/api/ai-status/probe?provider=groq")
    data = res.json()["data"]
    assert data["result"]["state"] == "ok" and data["result"]["provider"] == "groq"
    assert "status" in data
    assert ("groq", FIRM, "p1") in fake_probe
    audit = next(c for c in fake_probe if c[0] == "audit")
    assert audit[1][:4] == (FIRM, "ai_probe", "", "create")
    assert audit[2]["actor_id"] == "auth-p1", "the audit log takes the AUTH id"
    assert set(audit[2]["new_data"]) == {"provider", "state", "kind", "model", "answered_by"}


def test_a_failing_probe_is_a_200_with_a_sentence_not_an_error(monkeypatch):
    import routers.ai_status as mod

    def _failed(provider, *, firm_id, user_id=None):
        return probe.ProbeResult(provider=provider, state="failed", model="m",
                                 sentence="The model has been retired.", kind="model_gone",
                                 http_status=502)
    monkeypatch.setattr(mod.ai_probe, "probe", _failed)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    res = _client(_user("Partner", "p1")).post("/api/ai-status/probe?provider=groq")
    assert res.status_code == 200
    assert res.json()["data"]["result"]["sentence"] == "The model has been retired."


def test_both_routes_sit_behind_the_mfa_guard():
    import routers.ai_status as mod
    for route in mod.router.routes:
        assert any(d.dependency is mfa_guard for d in route.dependencies), (
            f"{route.path} reports configuration and spends quota: it needs mfa_guard")


def test_an_aal1_partner_is_refused_when_mfa_is_required(monkeypatch, fake_probe):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    c = _client({**_user("Partner", "p1"), "aal": "aal1"})
    assert c.get("/api/ai-status").status_code == 403
    assert c.post("/api/ai-status/probe?provider=groq").status_code == 403
    assert fake_probe == []


def test_the_probe_bucket_exists_and_is_the_smallest():
    limits = {name: cap for name, (cap, _window) in rate_limit.BUCKETS.items()}
    assert limits["probe"] == min(limits.values())


def test_the_probe_route_is_one_the_model_route_scan_finds():
    """The coverage guard derives 'reaches a model' from a route's own source; if the
    probe route stopped matching it, a later change could drop its limiter unseen."""
    import routers.ai_status as mod
    from tests.test_every_route_that_reaches_a_model_is_rate_limited import MODEL_MARKERS
    code = inspect.getsource(mod.run_probe)
    assert any(m in code for m in MODEL_MARKERS)

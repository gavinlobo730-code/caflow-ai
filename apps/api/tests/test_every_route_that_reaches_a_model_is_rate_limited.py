"""
Every route that reaches an AI model is rate limited (ai-17, security_privacy-22).

WHAT WAS WRONG
    `check_rate_limit` had one caller, `/api/ai-copilot/chat`, which no screen
    calls. `/api/assistant` was in the limiter's table and never checked;
    `/api/copilot/*`, `extract-invoice`, `notices/extract`, the scanned-statement
    read and the statement analysis had no limiter at all. One busy or
    misbehaving firm could run up the provider bill — or use up the quota for
    everybody — and the vision path sends up to twenty page images a call.

WHAT THIS ASSERTS
    * the limiter itself: per-firm and per-user, a 429 with Retry-After, windows
      that expire, and no state shared between firms;
    * a route guard that derives "reaches a model" from the route's own source and
      requires a limiter, so a model route added next year cannot be unlimited;
    * the routes the finding names answer 429 at their limit, end to end.
"""
from __future__ import annotations

import inspect
import re

import pytest
from fastapi import HTTPException

from middleware import rate_limit
from middleware.rate_limit import BUCKETS, enforce, user_limit

# ── the limiter ──────────────────────────────────────────────────────────────


def _spend(bucket, firm, n, user=None):
    for i in range(n):
        enforce(bucket, firm, user if user is not None else f"{firm}-u{i}")


def test_the_firm_limit_refuses_the_request_after_the_last_allowed_one():
    limit, window = BUCKETS["chat"]
    _spend("chat", "F1", limit)                       # a different user each time
    with pytest.raises(HTTPException) as e:
        enforce("chat", "F1", "someone-new")
    assert e.value.status_code == 429
    assert "your firm" in e.value.detail


def test_the_refusal_says_how_long_to_wait_and_carries_retry_after():
    limit, window = BUCKETS["chat"]
    _spend("chat", "F1", limit)
    with pytest.raises(HTTPException) as e:
        enforce("chat", "F1", "someone-new")
    retry = int(e.value.headers["Retry-After"])
    assert 1 <= retry <= window
    assert f"{retry} second" in e.value.detail


def test_one_user_cannot_spend_the_whole_firms_allowance():
    limit, _ = BUCKETS["chat"]
    cap = user_limit(limit)
    assert cap < limit, "the premise: a user's share is smaller than the firm's"
    _spend("chat", "F1", cap, user="u-busy")
    with pytest.raises(HTTPException) as e:
        enforce("chat", "F1", "u-busy")
    assert e.value.status_code == 429 and "you" in e.value.detail
    enforce("chat", "F1", "u-colleague")              # the rest of the firm still works


def test_one_firm_does_not_starve_another():
    limit, _ = BUCKETS["chat"]
    _spend("chat", "F1", limit)
    enforce("chat", "F2", "u1")                       # does not raise


def test_buckets_are_independent():
    limit, _ = BUCKETS["extract"]
    _spend("extract", "F1", limit)
    enforce("chat", "F1", "u1")                       # extraction spent, chat untouched


def test_the_window_expires(monkeypatch):
    limit, window = BUCKETS["vision"]
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    _spend("vision", "F1", limit)
    with pytest.raises(HTTPException):
        enforce("vision", "F1", "x")
    now[0] += window + 1
    enforce("vision", "F1", "x")                      # allowed again


def test_a_user_limit_is_never_below_three():
    assert user_limit(5) == 3 and user_limit(1) == 3 and user_limit(20) == 10


def test_an_unknown_bucket_is_a_programming_error_not_a_free_pass():
    with pytest.raises(KeyError):
        enforce("nonsense", "F1", "u1")
    with pytest.raises(KeyError):
        rate_limit.ai_limit("nonsense")


def test_the_legacy_entry_point_still_limits_the_copilot_chat_path():
    from types import SimpleNamespace
    req = SimpleNamespace(url=SimpleNamespace(path="/api/ai-copilot/chat"))
    limit, _ = BUCKETS["chat"]
    for _ in range(limit):
        rate_limit.check_rate_limit(req, "F1")
    with pytest.raises(HTTPException):
        rate_limit.check_rate_limit(req, "F1")
    other = SimpleNamespace(url=SimpleNamespace(path="/api/clients"))
    rate_limit.check_rate_limit(other, "F1")          # an unrelated path is never limited


# ── the guard: which routes reach a model, and do they have a limiter ────────

#: What a route's own source contains when it reaches a model. A route is an AI
#: route if ANY of these appears in it; it then needs the limiter. The markers
#: are the entry points, not the providers, so a route that hands work to a new
#: service method is caught by the method, and one that calls Groq directly by the
#: call.
MODEL_MARKERS = (
    "groq_text.chat(", "_run_extraction(", "_run_notice_extraction(",
    "generate_statement_analysis(", "_service().chat(",
    ".get_client_intelligence(", ".get_compliance_intelligence(",
    ".get_workflow_intelligence(", ".get_relationship_intelligence(",
    ".get_executive_dashboard(", "GROQ_API_URL", "_read_statement_file(",
)

#: Routes limited INSIDE the handler rather than by a dependency, with where.
LIMITED_INLINE = {
    "copilot_chat": "check_rate_limit(",
    "upload_statement": "rate_key=",
}


def _has_dependency(route) -> bool:
    def walk(dep):
        if getattr(dep.call, "_ai_limit_bucket", None):
            return True
        return any(walk(d) for d in dep.dependencies)
    return walk(route.dependant)


def _ai_routes():
    from fastapi.routing import APIRoute
    from main import app
    out = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        try:
            src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            continue
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("#"))
        if any(m in code for m in MODEL_MARKERS):
            out.append((r, code))
    return out


def test_the_scan_finds_the_model_routes_and_is_not_vacuous():
    names = {r.endpoint.__name__ for r, _ in _ai_routes()}
    for expected in ("assistant", "extract_invoice", "extract_notice", "quick_chat",
                     "send_message", "executive_dashboard", "get_statement_analysis",
                     "copilot_chat", "upload_statement"):
        assert expected in names, f"the scan did not find {expected}"
    assert len(names) >= 12


def test_every_route_that_reaches_a_model_has_a_limiter():
    missing = []
    for route, code in _ai_routes():
        name = route.endpoint.__name__
        if _has_dependency(route):
            continue
        marker = LIMITED_INLINE.get(name)
        if marker and marker in code:
            continue
        missing.append(f"{sorted(route.methods)[0]} {route.path} ({name})")
    assert not missing, (
        "these routes reach an AI model and are not rate limited — add "
        f"`_limit: None = Depends(ai_limit(<bucket>))` after rbac(): {missing}")


def test_the_inline_exemptions_are_real():
    """An inline limit is only a limit if the call is really there."""
    import routers.banking as banking
    import routers.ai_copilot as cp
    assert 'rate_limit.enforce("vision"' in inspect.getsource(banking._read_statement_file)
    assert "check_rate_limit(" in inspect.getsource(cp.copilot_chat)


# ── end to end on the routes the finding names ───────────────────────────────

PARTNER = {"id": "u-partner", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "a1"}


def _client(router):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_assistant_answers_429_at_its_limit(monkeypatch):
    import routers.assistant as mod

    async def fake_chat(messages, **kw):
        return "An answer.\nSource: CGST Act, Section 39", 5
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(mod.groq_text, "chat", fake_chat)
    c = _client(mod.router)
    cap = user_limit(BUCKETS["chat"][0])
    body = {"question": "When is GSTR-3B due?", "conversation_history": []}
    codes = [c.post("/api/assistant", json=body).status_code for _ in range(cap + 1)]
    assert codes[:cap] == [200] * cap
    assert codes[cap] == 429


def test_the_v2_copilot_chat_answers_429_at_its_limit(monkeypatch):
    import routers.ai_copilot_v2 as mod

    class _Svc:
        async def chat(self, **kw):
            return {"answer": "ok"}

    class _Repo:
        def create_conversation(self, *a, **k):
            return {"id": "conv1"}
    monkeypatch.setattr(mod, "_service", lambda: _Svc())
    monkeypatch.setattr(mod, "_repo", lambda: _Repo())
    c = _client(mod.router)
    cap = user_limit(BUCKETS["chat"][0])
    body = {"content": "hello"}
    codes = [c.post("/api/copilot/chat", json=body).status_code for _ in range(cap + 1)]
    assert codes[:cap] == [200] * cap and codes[cap] == 429


def test_an_intelligence_report_answers_429_at_its_limit(monkeypatch):
    import routers.ai_copilot_v2 as mod

    class _Svc:
        async def get_executive_dashboard(self, *a, **k):
            return {"ok": True}
    monkeypatch.setattr(mod, "_service", lambda: _Svc())
    c = _client(mod.router)
    cap = user_limit(BUCKETS["intelligence"][0])
    codes = [c.get("/api/copilot/executive-dashboard").status_code for _ in range(cap + 1)]
    assert codes[:cap] == [200] * cap and codes[cap] == 429


def test_invoice_extraction_answers_429_at_its_limit(monkeypatch):
    import routers.document_intelligence_v1 as mod
    monkeypatch.setattr(mod, "_GEMINI_KEY", "k")
    monkeypatch.setattr(mod, "_gemini_extract_image", lambda *a, **k: {
        "vendor_name": "V", "vendor_gstin": None, "invoice_no": "1", "invoice_date": None,
        "taxable_amount_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
        "total_paise": 0, "line_items": []})
    c = _client(mod.router)
    cap = user_limit(BUCKETS["extract"][0])

    def one():
        return c.post("/api/document-intelligence-v1/extract-invoice",
                      files={"file": ("b.jpg", b"\xff\xd8\xff x", "image/jpeg")},
                      data={"client_id": "c-001"}).status_code
    codes = [one() for _ in range(cap + 1)]
    assert codes[:cap] == [200] * cap and codes[cap] == 429


def test_a_permission_refusal_does_not_spend_the_firms_allowance(monkeypatch):
    """The limiter is declared AFTER rbac(), so a caller who is refused for
    permission has not used the budget."""
    import routers.assistant as mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(mod.router)
    reviewer_client = {"id": "u-x", "firm_id": "F1", "role": "Client", "email": "c@x.test"}
    app.dependency_overrides[get_current_user] = lambda: reviewer_client
    c = TestClient(app, raise_server_exceptions=False)
    for _ in range(30):
        assert c.post("/api/assistant", json={"question": "q"}).status_code in (401, 403)
    # Nothing was spent: a permitted caller in the same firm is not limited.
    enforce("chat", "F1", "u-partner")

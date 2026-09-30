"""
Module 9.0 / M2 — AI copilot authorization.

The copilot must only inject context for clients the caller is authorized to see.
Tests target the synchronous context builder (no Groq call) and the router gate.
"""
import pytest
from fastapi import HTTPException

from domain.ai_copilot_service import AICopilotService

# C2's STATUS is distinctive because the client block no longer carries a NAME
# (ai-15): these tests used the name as the thing that proves a client was or was
# not injected, and with the name withheld from every prompt that assertion would
# have passed vacuously — "Secret Co" cannot appear whether or not C2 leaked. The
# status line is what the block still carries and what tells the two apart.
CLIENTS = [
    {"id": "C1", "client_name": "Allowed Co", "status": "active", "gstin": "G1", "pan": "P1"},
    {"id": "C2", "client_name": "Secret Co", "status": "dormant_secret", "gstin": "G2", "pan": "P2"},
]


@pytest.fixture
def svc(monkeypatch):
    s = AICopilotService.__new__(AICopilotService)  # no repo needed for _build_context
    import domain.ai_copilot_service as mod

    class _Repo:
        def find_all(self, firm_id=None, **kw):
            return list(CLIENTS)
        def find_by_id(self, cid, *a, **k):
            return next((c for c in CLIENTS if c["id"] == cid), None)
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Repo())
    return s


def test_global_context_scoped_to_allowed_clients(svc):
    ctx = svc._build_context("F1", "global", None, allowed_client_ids={"C1"})
    assert "TOTAL CLIENTS: 1" in ctx          # only the allowed client counted


def test_global_context_firmwide_when_none(svc):
    ctx = svc._build_context("F1", "global", None, allowed_client_ids=None)
    assert "TOTAL CLIENTS: 2" in ctx          # Partner/Manager see all


def test_client_context_blocked_for_unauthorized(svc):
    # Asking for C2's context while only authorized for C1 must not leak C2.
    ctx = svc._build_context("F1", "client", "C2", allowed_client_ids={"C1"})
    assert "Secret Co" not in ctx
    # The assertion that can actually fail: no client block at all, so none of C2's
    # figures — its status being the distinctive one — reached the prompt.
    assert "dormant_secret" not in ctx
    assert "CLIENT STATUS" not in ctx


def test_client_context_allowed_for_authorized(svc):
    ctx = svc._build_context("F1", "client", "C1", allowed_client_ids={"C1"})
    # The authorised client's FIGURES are in; its name and tax IDs are not — they
    # are withheld from every prompt (ai-15, security_privacy-12).
    assert "CLIENT STATUS: active" in ctx
    assert "Allowed Co" not in ctx
    assert "G1" not in ctx.replace("FIRM: F1", "") and "P1" not in ctx


def test_the_unauthorized_assertion_is_not_vacuous(svc):
    """The premise the test above relies on: with access, the block IS there."""
    ctx = svc._build_context("F1", "client", "C2", allowed_client_ids={"C1", "C2"})
    assert "CLIENT STATUS: dormant_secret" in ctx


def test_router_gates_context_id(monkeypatch):
    """quick_chat must 404 a context_id the caller cannot access (no Groq call)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.ai_copilot_v2 as mod
    from routers.ai_copilot_v2 import router
    from core.auth import get_current_user

    # Force enforced assignment: executive assigned to nothing → C2 denied.
    monkeypatch.setattr(mod, "effective_client_ids", lambda u: set())

    def deny(user, client_id):
        if client_id and client_id not in set():
            raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(mod, "assert_client_access", deny)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "e", "firm_id": "F1", "role": "Executive"}
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/copilot/chat", json={"content": "hi", "context_type": "client", "context_id": "C2"})
    assert r.status_code == 404

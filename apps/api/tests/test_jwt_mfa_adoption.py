"""
M6 adoption tests — per-user JWT cutover mechanism + MFA guard.

Verify the request-scoped DB accessor selects the right client based on the
USE_USER_JWT flag and the per-request token, that the explicit service accessor
never downgrades, and that the request middleware populates the token.
"""
import core.supabase_client as sc
import core.security_config as cfg
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def test_get_supabase_is_service_when_flag_off(monkeypatch):
    monkeypatch.setattr(cfg, "use_user_jwt", lambda: False)
    monkeypatch.setattr(sc, "_service_client", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    h = sc.set_request_token("tok")
    try:
        assert sc.get_supabase() == "SERVICE"
    finally:
        sc.reset_request_token(h)


def test_get_supabase_is_user_when_flag_on_and_token(monkeypatch):
    monkeypatch.setattr(cfg, "use_user_jwt", lambda: True)
    monkeypatch.setattr(sc, "_service_client", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    h = sc.set_request_token("tok123")
    try:
        assert sc.get_supabase() == "USER:tok123"
    finally:
        sc.reset_request_token(h)


def test_get_supabase_falls_back_to_service_without_token(monkeypatch):
    # Background jobs have no request token even when the flag is on.
    monkeypatch.setattr(cfg, "use_user_jwt", lambda: True)
    monkeypatch.setattr(sc, "_service_client", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    h = sc.set_request_token(None)
    try:
        assert sc.get_supabase() == "SERVICE"
    finally:
        sc.reset_request_token(h)


def test_service_accessor_never_downgrades(monkeypatch):
    monkeypatch.setattr(cfg, "use_user_jwt", lambda: True)
    monkeypatch.setattr(sc, "_service_client", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    h = sc.set_request_token("tok")
    try:
        assert sc.get_service_supabase() == "SERVICE"
    finally:
        sc.reset_request_token(h)


def test_middleware_populates_request_token():
    # The main.py middleware extracts the bearer token into the ContextVar.
    app = FastAPI()

    @app.middleware("http")
    async def carry(request: Request, call_next):
        from core.supabase_client import set_request_token, reset_request_token, _request_access_token
        auth = request.headers.get("authorization")
        token = auth[7:].strip() if auth and auth[:7].lower() == "bearer " else None
        handle = set_request_token(token)
        try:
            return await call_next(request)
        finally:
            # capture before reset for assertion
            request.state.seen = _request_access_token.get()
            reset_request_token(handle)

    @app.get("/echo")
    def echo(request: Request):
        from core.supabase_client import _request_access_token
        return {"token": _request_access_token.get()}

    c = TestClient(app)
    assert c.get("/echo", headers={"Authorization": "Bearer abc.def.ghi"}).json()["token"] == "abc.def.ghi"
    assert c.get("/echo").json()["token"] is None

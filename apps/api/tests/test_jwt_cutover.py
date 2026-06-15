"""M6 — per-user-JWT cutover seam (flag-gated routing). Default OFF → service role."""
import core.supabase_client as sc


def test_service_role_when_flag_off(monkeypatch):
    monkeypatch.delenv("USE_USER_JWT", raising=False)
    monkeypatch.setattr(sc, "get_supabase", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    assert sc.get_request_supabase("tok") == "SERVICE"


def test_user_jwt_when_flag_on(monkeypatch):
    monkeypatch.setenv("USE_USER_JWT", "true")
    monkeypatch.setattr(sc, "get_supabase", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    assert sc.get_request_supabase("tok") == "USER:tok"


def test_falls_back_to_service_without_token(monkeypatch):
    monkeypatch.setenv("USE_USER_JWT", "true")
    monkeypatch.setattr(sc, "get_supabase", lambda: "SERVICE")
    monkeypatch.setattr(sc, "get_user_supabase", lambda t: "USER:" + t)
    assert sc.get_request_supabase(None) == "SERVICE"

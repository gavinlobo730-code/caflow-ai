"""Under USE_USER_JWT, Supabase Storage sees the signed-in user, not `anon`.

`get_user_supabase` gave the caller's JWT to PostgREST only. supabase-py builds
its storage client lazily from `options.headers`, which `create_client` had
filled with the ANON key, so every `get_supabase().storage` call ran as `anon`
— for which `get_my_firm_id()` is NULL — and migration 005's Documents policies
(`(storage.foldername(name))[1] = get_my_firm_id()::text`) refused all of them.
Storage logs on 27-09-2026 showed role=anon on the year-end PDF exports.
"""
from __future__ import annotations

import pytest

import core.supabase_client as sc

_ANON = "anon.key.value"
_USER = "user.jwt.value"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", _ANON)


def _auth(session) -> str:
    return dict(session.headers).get("authorization", "")


def test_storage_carries_the_users_own_token(env):
    client = sc.get_user_supabase(_USER)
    assert _auth(client.storage.session) == f"Bearer {_USER}"
    assert _auth(client.storage.from_("Documents")._client) == f"Bearer {_USER}"


def test_postgrest_still_carries_it_too(env):
    client = sc.get_user_supabase(_USER)
    assert _auth(client.postgrest.session) == f"Bearer {_USER}"


def test_premise_the_library_alone_gives_storage_the_anon_key(env):
    # What get_user_supabase did before: create the client and authenticate
    # PostgREST only. Storage is then the anon key — the defect.
    from supabase import create_client
    client = create_client("https://example.supabase.co", _ANON)
    client.postgrest.auth(_USER)
    assert _auth(client.storage.session) == f"Bearer {_ANON}"


def test_the_portal_download_is_signed_with_the_service_role():
    # A portal principal has no `users` row, so the firm-folder policy refuses
    # it whatever token it carries; the endpoint checks ownership first and
    # then signs with the service role, which its own docstring always said.
    import inspect
    from routers import portal_data
    src = inspect.getsource(portal_data.portal_document_download)
    assert "get_service_supabase().storage" in src
    assert "get_supabase().storage" not in src.replace("get_service_supabase().storage", "")

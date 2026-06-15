"""
Supabase client for the FastAPI backend.
Uses SERVICE_ROLE key — full DB access, bypasses RLS for internal operations.
All tenant isolation enforced at repository level via firm_id filter.
"""
import os
import logging
from supabase import create_client, Client

_client: Client | None = None
_logger = logging.getLogger("caflow.supabase")


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set."
            )
        # Service role keys always start with "eyJ" (JWT) and are much longer
        # than anon keys. Log a warning if the key looks wrong.
        if not key.startswith("eyJ"):
            _logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY does not look like a JWT "
                "(expected 'eyJ...'). Check Render env var value."
            )
        _logger.info(
            "Initialising Supabase client — URL: %s, key prefix: %s...",
            url,
            key[:12],
        )
        _client = create_client(url, key)
    return _client


def get_user_supabase(access_token: str) -> Client:
    """
    M6 (staged) — a per-request Supabase client authenticated as the END USER
    (anon key + the caller's access token), so Postgres RLS is enforced on the
    backend's DB access too. This is the seam for the per-user-JWT cutover.

    A fresh client is created per call (cheap; carries the user's Authorization
    header) — do NOT cache it, as it is user-scoped.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon = os.environ.get("SUPABASE_ANON_KEY", "").strip() or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_ANON_KEY", ""
    ).strip()
    if not url or not anon:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set for user-scoped access.")
    client = create_client(url, anon)
    # Attach the user's JWT so PostgREST runs as the `authenticated` role and RLS
    # (auth.uid(), get_my_role(), can_access_client(), ...) applies.
    client.postgrest.auth(access_token)
    return client


def get_request_supabase(access_token: str | None) -> Client:
    """
    Return the DB client for a user request. When the USE_USER_JWT flag is ON and
    a token is present, returns the user-scoped client (RLS enforced); otherwise
    the service-role client (current behaviour). Lets the cutover roll out behind
    a flag without touching every call site at once.
    """
    from core.security_config import use_user_jwt
    if use_user_jwt() and access_token:
        return get_user_supabase(access_token)
    return get_supabase()

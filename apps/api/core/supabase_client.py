"""
Supabase client for the FastAPI backend.

Two access modes:
  * SERVICE_ROLE  — full DB access, bypasses RLS. Used for privileged/bootstrap
    paths (auth resolution, audit/login writes, approval writes, background jobs,
    provisioning, authz decision lookups) via get_service_supabase().
  * PER-USER JWT  — anon key + caller's bearer token, so Postgres RLS applies.
    Used for all user-initiated client-scoped data access via get_supabase()
    once USE_USER_JWT is enabled (M6 cutover). A per-request ContextVar carries
    the caller's token so existing get_supabase() call sites adopt the user
    client automatically when the flag is on; with the flag off (or no token,
    e.g. background jobs) get_supabase() returns the service-role client — so the
    cutover ships dark and is reverted by the flag alone.
"""
import os
import logging
from contextvars import ContextVar
from supabase import create_client, Client

_client: Client | None = None
_logger = logging.getLogger("caflow.supabase")


def _force_http1(client: Client) -> Client:
    """Rebuild PostgREST's httpx session without HTTP/2.

    WHY
        postgrest 0.18's create_session hardcodes http2=True, and h2 is
        installed, so every Supabase call multiplexes over ONE HTTP/2
        connection. _service_client() below caches a single client in a module
        global, and FastAPI runs our sync `def` endpoints in a threadpool — so
        that one connection is driven by many threads at once. The h2 state
        machine does not survive that: frames from different streams interleave
        and it ends up parsing a REQUEST's pseudo-headers as a response
        trailer. In production that surfaced as

            LocalProtocolError: Received pseudo-header in trailer
            {b':scheme', b':method', b':path', b':authority'}

        on GET /api/accounting/profit-loss, raised out of core.auth's firm
        lookup. It is load-dependent, which is why no test ever saw it.

        HTTP/1.1 sidesteps the whole class: httpx's pool gives each request its
        own connection for its duration, so there is no shared state machine to
        corrupt. We lose multiplexing, which costs nothing at our request rate
        against PostgREST.

        Rebuilding the session is the available seam — supabase 2.10's
        ClientOptions exposes timeouts and headers but not the httpx client, and
        http2 cannot be changed after construction. Every argument below mirrors
        postgrest's own create_session except http2.
    """
    session = getattr(getattr(client, "postgrest", None), "session", None)
    if session is None:  # pragma: no cover — shape changed under us
        _logger.warning("Supabase client exposes no postgrest session; leaving HTTP/2 as-is.")
        return client
    try:
        from postgrest._sync.client import SyncClient
        client.postgrest.session = SyncClient(
            base_url=session.base_url,
            headers=session.headers,
            timeout=session.timeout,
            follow_redirects=True,
            http2=False,
        )
        session.close()
    except Exception:
        # A client on HTTP/2 still works; it just carries the concurrency bug.
        # Failing to start because of this would be the worse outcome.
        _logger.exception("Could not disable HTTP/2 on the Supabase session; continuing.")
    return client

# Per-request access token (set by middleware from the Authorization header).
# None for background jobs / unauthenticated paths.
_request_access_token: ContextVar[str | None] = ContextVar("request_access_token", default=None)


def set_request_token(token: str | None):
    """Store the caller's bearer token for the current request; returns a reset
    handle. Called by the request middleware (and cleared after the response)."""
    return _request_access_token.set(token)


def reset_request_token(handle) -> None:
    try:
        _request_access_token.reset(handle)
    except Exception:
        pass


def _service_client() -> Client:
    """The shared SERVICE_ROLE client (bypasses RLS)."""
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
        _client = _force_http1(create_client(url, key))
    return _client


def get_service_supabase() -> Client:
    """Explicit SERVICE_ROLE accessor for privileged/bootstrap paths that must
    bypass RLS regardless of the USE_USER_JWT flag (auth resolution, audit/login
    writes, approvals, background jobs, provisioning, authz decision lookups)."""
    return _service_client()


def get_supabase() -> Client:
    """Request-scoped DB client.

    When USE_USER_JWT is enabled AND a caller token is present for this request,
    returns a per-user client (RLS enforced). Otherwise returns the service-role
    client (current behaviour). Privileged paths must use get_service_supabase()
    instead so they are never downgraded by the cutover.
    """
    from core.security_config import use_user_jwt
    if use_user_jwt():
        token = _request_access_token.get()
        if token:
            return get_user_supabase(token)
    return _service_client()


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
    client = _force_http1(create_client(url, anon))
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

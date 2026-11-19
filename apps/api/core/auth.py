"""
FastAPI JWT authentication dependency.
Validates Supabase-issued JWTs via JWKS (supports ES256 / RS256 / HS256).
Extracts user identity and resolves firm_id from the users table.
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from fastapi import Header, HTTPException, status, Depends
import jwt

_logger = logging.getLogger("caflow.auth")
from jwt import PyJWKClient
from core import auth_time
from core.env import env_or_default
from core.supabase_client import get_service_supabase
from core.request_actor import bind as bind_actor
from core.request_context import bind_firm

_jwks_client: Optional[PyJWKClient] = None

# R3.5e — get_current_user() ran 2 serialized, uncached DB round trips (users,
# firms) on ~88/93 routers, every single request. Short-TTL in-process cache,
# keyed by auth_user_id: bounds a disabled account / session revocation /
# suspended firm to at most this many seconds of staleness after the DB write,
# in exchange for skipping both lookups on every other request in that window.
# Only successful lookups are cached — a miss (user row not yet visible, e.g.
# mid-onboarding) is never cached, so a legitimate new user is never stuck
# behind a stale 403. Per-process only (no cross-worker sharing); that's an
# acceptable trade-off for a bounded staleness window, not a correctness gap.
_USER_LOOKUP_CACHE_TTL_SECONDS = 30
_user_lookup_cache: dict[str, tuple[float, dict, Optional[dict]]] = {}


def _permission_overrides(supabase, user_id, firm_id) -> dict:
    """This person's per-person access overrides (migration 403), keyed
    ``"resource:action"`` -> bool.

    Read HERE, inside the 30-second cached lookup, rather than in `rbac()`:
    `apps/api` runs in Singapore and Postgres in Mumbai, so a read per request
    would put a cross-region round trip in front of all 1037 guarded endpoints.
    Here it costs one read per user per 30 seconds.

    That TTL means a permission change takes up to 30 seconds to bite, which is
    exactly how a ROLE change already behaves on this same cache — the same
    delay, on the same row, for the same reason.

    A FAILED read returns {} — no overrides — which falls back to the role. That
    is the safe direction and the only defensible one: failing closed would
    lock every user out of everything on a transient PostgREST error, while
    failing to the role is precisely the behaviour this firm had before anybody
    ticked a box. It is logged, not swallowed.
    """
    if not user_id or not firm_id:
        # No firm to read the member's rows in means no override, which is the role: never the rows of every firm.
        return {}
    try:
        # Only a row WRITTEN IN THE MEMBER'S OWN FIRM counts (migration 530): the read bypasses row security and `users.id`
        # is a global key, so a row a Partner of another firm wrote for this member is not their answer.
        rows = (
            supabase.table("user_permissions")
            .select("resource, action, granted")
            .eq("user_id", user_id)
            .eq("firm_id", firm_id)
            .execute()
        ).data or []
    except Exception:
        _logger.exception("permission-override lookup failed for user_id=%s", user_id)
        return {}
    if not isinstance(rows, list):
        # A row set, always — this is a plain filtered select with no
        # `.single()`. Anything else is a caller or a stub handing back a shape
        # this function does not read, and iterating a dict here would walk its
        # KEYS and then fail on `str.get` inside the auth path, turning a
        # malformed read into a 500 on every request rather than into the
        # role-default fallback the failure above deliberately chooses.
        _logger.warning("permission-override lookup returned %s, not a list, for user_id=%s",
                        type(rows).__name__, user_id)
        return {}
    out: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource, action = row.get("resource"), row.get("action")
        granted = row.get("granted")
        if resource and action and isinstance(granted, bool):
            out[f"{resource}:{action}"] = granted
    return out


#: PostgreSQL's "undefined_column", which PostgREST passes through as the error's code.
_UNDEFINED_COLUMN = "42703"


def _read_user_row(supabase, auth_user_id: str):
    """The caller's `users` row, asking for the two columns migration 765 added (`other_sessions_revoked_at`,
    `other_sessions_kept_session_id`).

    The API can go live a few minutes before the migration job has applied a migration (they are separate jobs on the same push), and
    a select naming a column that does not exist yet is refused for EVERY request, which would lock everybody out of everything.
    So THAT one answer, and only that one (undefined column), reads the row again without the two columns: until the migration has
    run nobody can have signed out their other sessions, so there is no mark to miss. Any other failure still raises, and the caller
    answers 503 as it always has: a check that fails open on an error it cannot name is not a check. Both selects are written out
    whole, not built from a variable, so the column check (`tests/test_backend_columns_exist_pg.py`) can read them.
    """
    try:
        return (
            supabase.table("users")
            .select("id, firm_id, role, full_name, is_active, sessions_revoked_at, other_sessions_revoked_at, other_sessions_kept_session_id")
            .eq("auth_user_id", auth_user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:                                  # noqa: BLE001
        if getattr(exc, "code", None) != _UNDEFINED_COLUMN:
            raise
        _logger.warning("users.other_sessions_* columns are not there yet (migration 765 not applied); reading without them")
        return (
            supabase.table("users")
            .select("id, firm_id, role, full_name, is_active, sessions_revoked_at")
            .eq("auth_user_id", auth_user_id)
            .maybe_single()
            .execute()
        )


def _get_user_and_firm(supabase, auth_user_id: str) -> tuple[Optional[dict], Optional[dict]]:
    cached = _user_lookup_cache.get(auth_user_id)
    if cached is not None and (time.monotonic() - cached[0]) < _USER_LOOKUP_CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    try:
        # maybe_single() — NOT single(): single() raises for both zero-row AND
        # multi-row results, so a bare except around it can't tell "genuinely no
        # such user" apart from "the query itself failed" (network blip, rate
        # limit, transient PostgREST error) — both looked identical and both
        # produced the same misleading 403 "User not found in firm", even when
        # the row was actually there. maybe_single() returns data=None for the
        # zero-row case without raising, so an exception here now means the
        # query itself broke — worth logging, not silently treating as a
        # missing account.
        result = _read_user_row(supabase, auth_user_id)
        user_data = result.data
    except Exception as exc:
        # The lookup itself broke — Supabase unreachable, rate-limited, a
        # transient PostgREST error. That is NOT "this user has no account".
        #
        # It used to be reported as one: the except set user_data = None, the
        # caller saw a falsy row and raised 403 "User not found in firm". A 403
        # is a statement that the caller is permanently not allowed, so the
        # frontend fails closed and its retries are pointless — which is exactly
        # what was seen in production, five consecutive 403s on
        # /api/identity/permissions while /health was returning 503. The firm's
        # only user was active, in an active firm, with a valid auth_user_id
        # link; nothing about authorization was wrong.
        #
        # Raise it as what it is. 503 tells the caller to try again, and the
        # switch to maybe_single() above means reaching here really does mean
        # the query failed rather than returned nothing.
        _logger.exception("user lookup failed for auth_user_id=%s", auth_user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify your account just now. Please try again.",
        ) from exc

    if not user_data:
        return None, None

    firm_row = None
    firm_id_for_status = user_data.get("firm_id")
    if firm_id_for_status:
        try:
            firm_row = (
                supabase.table("firms")
                .select("is_active, deleted_at")
                .eq("id", firm_id_for_status)
                .maybe_single()
                .execute()
            ).data
        except Exception as exc:
            # Fail CLOSED, for the same reason the user lookup above does.
            #
            # This used to swallow the error and set firm_row = None — and the
            # caller reads it as `if firm_row:`, so None SKIPS the suspended-firm
            # and deleted-firm checks entirely and admits the request. A
            # transient PostgREST error therefore did not deny access, it
            # granted it; and because the result was written to the cache below,
            # one glitch kept that check bypassed for the whole TTL.
            #
            # It was not hypothetical. A shared-client HTTP/2 concurrency bug
            # (see core.supabase_client._force_http1) raised LocalProtocolError
            # here in production, logged "firm lookup failed", and let the
            # request through.
            #
            # 503 says "ask again", which is true and is what the user lookup
            # already returns for the identical situation.
            _logger.exception("firm lookup failed for firm_id=%s", firm_id_for_status)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not verify your account just now. Please try again.",
            ) from exc
        if firm_row is None:
            # Not an error — maybe_single() found no row. The user names a firm
            # that does not exist, which is a data problem worth seeing rather
            # than a reason to deny a working login, so behaviour is unchanged
            # and this is only made visible.
            _logger.warning(
                "user %s names firm_id=%s, which has no row", auth_user_id, firm_id_for_status)

    # Carried ON the user row rather than as a fourth return value: every caller
    # of this function reads `user_data`, and a separate channel is one caller
    # away from being dropped — which would read as "this person has no
    # overrides", i.e. silently back to role-only access with nothing to see.
    user_data = {
        **user_data,
        "permission_overrides": _permission_overrides(supabase, user_data.get("id"), user_data.get("firm_id")),
    }
    _user_lookup_cache[auth_user_id] = (time.monotonic(), user_data, firm_row)
    return user_data, firm_row


def _get_jwks_client() -> PyJWKClient:
    # Lazy singleton — fetches JWKS from Supabase on first call, cached thereafter.
    global _jwks_client
    if _jwks_client is None:
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        if not supabase_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server configuration error: SUPABASE_URL not set",
            )
        # JWKS endpoint documented at: https://supabase.com/docs/guides/auth/jwks
        _jwks_client = PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")
    return _jwks_client


#: SECURITY-PRIVACY-21. What a token must prove BEYOND "the project's key signed
#: it". Supabase signs several kinds of token with the same keys — a signed-in
#: user's access token (aud "authenticated"), the anon and service_role API keys
#: (no aud, no sub, iss "supabase") and any future audience the project mints —
#: and `verify_aud=False` with no issuer check accepted every one that carried a
#: `sub`. The impact was bounded only by portal and employee tokens having no
#: users row; it was never a designed control.
_JWT_AUDIENCE = "authenticated"
#: `sub` is what everything downstream keys on; `exp` is what makes a stolen token
#: stop working; `iat` is what the session-revocation comparison below reads, and
#: a token without one used to skip that comparison altogether.
_JWT_REQUIRED_CLAIMS = ["exp", "sub", "iat"]
_JWT_ALGORITHMS = ["ES256", "RS256", "HS256"]


def expected_jwt_issuer() -> str:
    """The `iss` a token must carry: this project's own auth endpoint.

    GoTrue signs `{API_EXTERNAL_URL}/auth/v1`, which for a hosted project is
    `{SUPABASE_URL}/auth/v1` — the same URL `_get_jwks_client` fetches the keys
    from, so the two cannot disagree about which project is being trusted.

    SUPABASE_JWT_ISSUER overrides it, for a project served from a custom domain
    where the two differ. It is an escape hatch and not a way to loosen the
    check: one exact string is still required. Unset is the normal case.
    """
    override = os.environ.get("SUPABASE_JWT_ISSUER", "").strip().rstrip("/")
    if override:
        return override
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server configuration error: SUPABASE_URL not set",
        )
    return f"{supabase_url}/auth/v1"


def decode_supabase_jwt(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    THE ONE PLACE A TOKEN IS DECODED. `get_current_user` and `get_jwt_user` each
    carried their own `jwt.decode(..., options={"verify_aud": False})`, so a
    check added to one would have left the other — the door reached by a caller
    with no users row yet, which is also where every portal principal comes
    through — exactly as open as before.

    Verifies, beyond the signature and `exp`: the audience is "authenticated",
    the issuer is this project's, and `exp`, `sub` and `iat` are present. Every
    failure is a `jwt.InvalidTokenError` (an absent claim is
    `MissingRequiredClaimError`, a subclass), so callers keep one `except`.
    """
    # PyJWKClient fetches the public key matching the token's kid header, then
    # verifies the signature using the algorithm declared in the token. This
    # handles ES256 (ECC P-256), RS256, and HS256 without hardcoding.
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_JWT_ALGORITHMS,
        audience=_JWT_AUDIENCE,
        issuer=expected_jwt_issuer(),
        options={"require": _JWT_REQUIRED_CLAIMS},
    )


def _token_predates_revocation(payload: dict, revoked_epoch: float) -> bool:
    return auth_time.issued_before_revocation(payload, revoked_epoch)


def _instant_epoch(value) -> float:
    """A stored timestamp as POSIX seconds. Raises on anything it cannot read.

    A naive value is read as UTC rather than as the host's local time, which
    `datetime.timestamp()` would otherwise assume. PostgREST always sends an
    offset for a timestamptz, so this only matters for a value that arrived some
    other way — and there it is the reading that cannot move a session's
    revocation by the host's UTC offset.
    """
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _refuse_a_session_signed_out_from_elsewhere(user_data: dict, payload: dict, auth_user_id: str) -> None:
    """POST-A-486 — "sign out my other sessions": the person ended every session but one. A token of a session that began before that
    instant and is not the kept one is refused, the kept session and any later sign-in are not. Fails closed like the revocation in
    `get_current_user`: a mark nobody can read is not evidence it was withdrawn."""
    other_at = user_data.get("other_sessions_revoked_at")
    if not other_at:
        return
    try:
        ended = auth_time.ended_by_other_sessions_sign_out(
            payload, _instant_epoch(other_at), user_data.get("other_sessions_kept_session_id"))
    except Exception as exc:                                 # noqa: BLE001
        _logger.error(
            "other_sessions_revoked_at for user %s could not be compared with the token; refusing the request",
            auth_user_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session could not be verified. Please sign in again.",
        ) from exc
    if ended:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session was signed out from another device. Please sign in again.",
        )


def _refuse_a_closed_firms_person(supabase, auth_user_id: str, payload: dict) -> None:
    """A signed-in account with no member row, from a firm that was permanently deleted (POST-A-499).

    The purge deletes the member rows and leaves the sign-in accounts, so a session that was open at the time reached "User not found in
    firm" and the browser opened the new-practice wizard. `closed_account_markers` (migration 772) remembers who they were and when it
    happened; a session that BEGAN before then is answered 403 "Firm unavailable", the words the browser already reads as "the firm is
    closed" (it signs the person out and says so). A session that began after it is a new sign-in by a person who may start a practice,
    and is left to the ordinary refusal. A marker that cannot be read leaves the ordinary refusal too: that is what this path did before,
    and a read that fails must not turn a person mid-sign-up into someone who is signed out."""
    try:
        row = (supabase.table("closed_account_markers").select("closed_at")
               .eq("auth_user_id", auth_user_id).maybe_single().execute()).data
    except Exception:                                    # noqa: BLE001 — the ordinary refusal follows
        _logger.warning("closed-account marker lookup failed for auth_user_id=%s", auth_user_id, exc_info=True)
        return
    if not row or not row.get("closed_at"):
        return
    try:
        began_before = auth_time.issued_before_revocation(payload, _instant_epoch(row["closed_at"]))
    except Exception:                                    # noqa: BLE001 — an unreadable instant is judged as the ordinary refusal
        _logger.warning("closed_at for auth_user_id=%s could not be compared with the token", auth_user_id, exc_info=True)
        return
    if began_before:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Firm unavailable")


def _refuse_an_ended_session(user_data: dict, firm_row: Optional[dict], payload: Mapping[str, Any], auth_user_id: str) -> None:
    """The four refusals a member's token meets before any route runs, as ONE function (POST-A-498): a disabled account, a firm that was deleted
    or suspended, a revocation of every session (a suspension, a force sign-out), and a session signed out from elsewhere. `get_current_user` asks
    it for every route behind it, and `refuse_a_member_whose_session_has_ended` asks it for the one route that answers from a member's row without
    that dependency, so what a route behind the dependency refuses and what the invitation's repeat-accept refuses are the same set, in the same
    words, from one place. The order is the order they were always made in."""
    # M1 — Active-user enforcement: a disabled account must not continue to
    # operate through a still-valid (unexpired) JWT. is_active defaults True so
    # rows predating the column are unaffected; only an explicit False blocks.
    if user_data.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled. Contact your firm administrator.",
        )

    # Platform Admin enforcement: a suspended or soft-deleted firm blocks ALL of
    # its users. Enforced centrally here so every firm endpoint is gated at once.
    if firm_row:
        if firm_row.get("deleted_at"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Firm unavailable")
        if firm_row.get("is_active") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Firm suspended")

    # M6 — Session revocation / forced logout: reject any token issued before the
    # account's sessions_revoked_at instant (set by suspend / force-logout / global
    # logout). Compares the JWT 'iat' (issued-at) against the stored timestamp.
    #
    # FAILS CLOSED (SECURITY-PRIVACY-21). This used to `except Exception: pass`
    # around the comparison, on the reasoning that "an unparseable timestamp must
    # never hard-fail auth" — so a sessions_revoked_at nobody could read let a
    # token through that the account's own owner had revoked, and silently: the
    # one request that should have been refused answered 200. A revocation is a
    # security decision somebody made; a value the code cannot read is not
    # evidence it was withdrawn. The comparison is also no longer skipped for a
    # token with no `iat` (now a required claim, but `iat: 0` is falsy and a test
    # double can omit it): if a revocation exists and the token cannot show when
    # it was issued, it cannot show it was issued after.
    revoked_at = user_data.get("sessions_revoked_at")
    if revoked_at:
        try:
            revoked_epoch = _instant_epoch(revoked_at)
            # By `iat` AND by when the session began (core/auth_time.py): a renewed token has a
            # new `iat` and would otherwise walk straight back past a revocation.
            issued_before_revocation = _token_predates_revocation(payload, revoked_epoch)
        except Exception:                                    # noqa: BLE001
            _logger.error(
                "sessions_revoked_at for user %s could not be compared with the "
                "token's iat; refusing the request", auth_user_id, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session could not be verified. Please sign in again.",
            )
        if issued_before_revocation:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked. Please sign in again.",
            )

    _refuse_a_session_signed_out_from_elsewhere(user_data, payload, auth_user_id)


def refuse_a_member_whose_session_has_ended(auth_user_id: str, claims: Mapping[str, Any]) -> None:
    """For a route that answers from a member's own row WITHOUT `get_current_user` (the invitation's repeat-accept, which authenticates with the
    token alone because the caller may have no row yet): read the member and their firm as `get_current_user` reads them and refuse as it does
    (POST-A-498). Nothing happens for a sign-in that has no member row, so a stranger's answer is unchanged. `claims` are the token's session
    claims (`get_jwt_user` returns them as `session_claims`); absent claims are read as a token showing nothing, which fails closed wherever a
    revocation exists. In the development fallback (no SUPABASE_URL) there is no member table to ask, which is what `get_current_user` does too."""
    if not os.environ.get("SUPABASE_URL"):
        return
    user_data, firm_row = _get_user_and_firm(get_service_supabase(), auth_user_id)
    if not user_data:
        return
    _refuse_an_ended_session(user_data, firm_row, claims or {}, auth_user_id)


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
    x_firm_id: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
) -> dict:
    """
    Dependency: validates Bearer JWT from Supabase Auth.
    Returns dict with: auth_user_id, firm_id, email, role
    Supports ES256 (ECC P-256), RS256, and HS256 signing keys automatically
    via JWKS — no algorithm hardcoding required.
    In dev/test mode (no SUPABASE_URL), reads X-User-Role / X-Firm-Id headers.
    """
    # Dev fallback — only allowed when APP_ENV=development AND no SUPABASE_URL.
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        app_env = env_or_default("APP_ENV", "production")
        if app_env != "development":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server configuration error: SUPABASE_URL not set",
            )
        role = (x_user_role or "partner").strip().capitalize()
        bind_firm(x_firm_id or "firm-001")
        return {
            "auth_user_id": x_user_id or "dev-user",
            "id": x_user_id or "dev-user",
            "firm_id": x_firm_id or "firm-001",
            "email": "dev@caflow.ai",
            "role": role,
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    auth_user_id: str = payload.get("sub", "")
    if not auth_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim")

    # Resolve firm_id from users table (+ the firm's active/deleted status),
    # short-TTL cached — see _get_user_and_firm / _USER_LOOKUP_CACHE_TTL_SECONDS.
    # supabase-py 2.x raises postgrest.exceptions.APIError (406) when
    # .single() finds no matching row instead of returning result.data=None,
    # so we catch that and convert it to a clean 403.
    supabase = get_service_supabase()
    user_data, firm_row = _get_user_and_firm(supabase, auth_user_id)

    if not user_data:
        _refuse_a_closed_firms_person(supabase, auth_user_id, payload)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found in firm. Contact your firm administrator.",
        )

    # The four refusals every route behind this dependency makes (a disabled account, a closed or suspended firm, a revocation of every session,
    # a session signed out from elsewhere), in one function that the invitation's repeat-accept asks as well (POST-A-498).
    _refuse_an_ended_session(user_data, firm_row, payload, auth_user_id)

    # M1 — default to least-privileged staff role (not silently Executive) when a
    # row somehow has no role; never silently grant elevated access.
    role = user_data.get("role") or "Reviewer"

    # ops-11: say which firm this request is for, so the log line, the Sentry event and a 5xx can be found
    # by firm. The firm's UUID only; core/request_context.py says what may never be bound.
    bind_firm(user_data["firm_id"])
    # POST-A-317: the verified person, for the ledger door to hand the database (core/request_actor.py says why it is not read off the token again).
    bind_actor(auth_user_id)

    return {
        "auth_user_id": auth_user_id,
        # Internal users.id — required for client-assignment lookups (core.authz)
        # and per-user notification scoping. Distinct from auth_user_id.
        "id": user_data.get("id"),
        "firm_id": user_data["firm_id"],
        "email": payload.get("email", ""),
        "role": role,
        "full_name": user_data.get("full_name", ""),
        # M6 — MFA assurance level from the Supabase JWT (aal1 = password only,
        # aal2 = MFA satisfied). Used by require_mfa() when REQUIRE_MFA is enabled.
        "aal": payload.get("aal", "aal1"),
        # POST-A-486 — the sign-in service's id for THIS session (None for a token that carries none), so a sign-in can be told
        # from the person's other devices and "sign out my other sessions" can keep this one.
        "session_id": auth_time.session_id_of(payload),
        "access_token": token,
        # Per-person access overrides (migration 403). `core.permissions.can_user`
        # reads this key, so it must be present on EVERY principal rbac() can
        # see. An absent key and an empty map resolve identically — to the role —
        # which is what keeps the dev/mock path below working unchanged.
        "permission_overrides": user_data.get("permission_overrides") or {},
    }


def get_jwt_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    Lightweight JWT-only dependency — validates the Supabase JWT but does NOT
    require a row in the users table. Used for firm onboarding where the caller
    has just completed Supabase Auth sign-up and has no users record yet.
    Returns: { auth_user_id, email, aal }
    """
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        app_env = env_or_default("APP_ENV", "production")
        if app_env != "development":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="Server configuration error: SUPABASE_URL not set")
        return {"auth_user_id": "dev-user", "email": "dev@caflow.ai", "aal": "aal1"}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    auth_user_id = payload.get("sub", "")
    if not auth_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim")

    return {
        "auth_user_id": auth_user_id, "email": payload.get("email", ""), "aal": payload.get("aal", "aal1"),
        # When an authenticator code was last entered in this session (POST-A-484): the platform admin's destructive
        # actions ask for one entered in the last five minutes.
        "last_authenticator_code_at": auth_time.last_authenticator_code_epoch(payload),
        # The claims the session rules read and nothing else of the token (POST-A-498): the one route that answers from a member's row
        # with this dependency asks `refuse_a_member_whose_session_has_ended` with them.
        "session_claims": {k: payload[k] for k in ("iat", "amr", "session_id") if k in payload},
    }


def require_mfa(current_user: dict = Header(default=None)) -> dict:  # pragma: no cover - thin wrapper
    """Placeholder kept for import stability; real dependency is mfa_guard()."""
    return current_user


def mfa_guard(current_user: dict = Depends(get_current_user)) -> dict:
    """
    M6 — MFA enforcement (staged behind REQUIRE_MFA, default OFF).

    When enabled, users whose role is in MFA_REQUIRED_ROLES must present an aal2
    (MFA-satisfied) token; otherwise a 403 instructs them to complete MFA. When the
    flag is off this is a no-op pass-through, so it is safe to attach to sensitive
    routes now and switch on after MFA is validated in staging.
    """
    from core.security_config import mfa_required_for
    if mfa_required_for(current_user.get("role")):
        if current_user.get("aal") != "aal2":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Multi-factor authentication required for this action.",
            )
    return current_user

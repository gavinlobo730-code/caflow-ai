"""
FastAPI JWT authentication dependency.
Validates Supabase-issued JWTs via JWKS (supports ES256 / RS256 / HS256).
Extracts user identity and resolves firm_id from the users table.
"""
import os
import time
from typing import Optional
from fastapi import Header, HTTPException, status, Depends
import jwt
from jwt import PyJWKClient
from core.supabase_client import get_service_supabase

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


def _get_user_and_firm(supabase, auth_user_id: str) -> tuple[Optional[dict], Optional[dict]]:
    cached = _user_lookup_cache.get(auth_user_id)
    if cached is not None and (time.monotonic() - cached[0]) < _USER_LOOKUP_CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    try:
        result = (
            supabase.table("users")
            .select("id, firm_id, role, full_name, is_active, sessions_revoked_at")
            .eq("auth_user_id", auth_user_id)
            .single()
            .execute()
        )
        user_data = result.data
    except Exception:
        user_data = None

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
                .single()
                .execute()
            ).data
        except Exception:
            firm_row = None

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
        app_env = os.environ.get("APP_ENV", "production")
        if app_env != "development":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server configuration error: SUPABASE_URL not set",
            )
        role = (x_user_role or "partner").strip().capitalize()
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
        # PyJWKClient fetches the public key matching the token's kid header,
        # then verifies the signature using the algorithm declared in the token.
        # This handles ES256 (ECC P-256), RS256, and HS256 without hardcoding.
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "HS256"],
            options={"verify_aud": False},
        )
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found in firm. Contact your firm administrator.",
        )

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
    revoked_at = user_data.get("sessions_revoked_at")
    token_iat = payload.get("iat")
    if revoked_at and token_iat:
        try:
            from datetime import datetime, timezone
            revoked_epoch = datetime.fromisoformat(
                str(revoked_at).replace("Z", "+00:00")
            ).timestamp()
            if float(token_iat) < revoked_epoch:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session revoked. Please sign in again.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # unparseable timestamp must never hard-fail auth

    # M1 — default to least-privileged staff role (not silently Executive) when a
    # row somehow has no role; never silently grant elevated access.
    role = user_data.get("role") or "Reviewer"

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
        "access_token": token,
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
        app_env = os.environ.get("APP_ENV", "production")
        if app_env != "development":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="Server configuration error: SUPABASE_URL not set")
        return {"auth_user_id": "dev-user", "email": "dev@caflow.ai", "aal": "aal1"}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key,
                             algorithms=["ES256", "RS256", "HS256"],
                             options={"verify_aud": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    auth_user_id = payload.get("sub", "")
    if not auth_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim")

    return {"auth_user_id": auth_user_id, "email": payload.get("email", ""), "aal": payload.get("aal", "aal1")}


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
    from core.security_config import require_mfa as _flag, mfa_required_roles
    if _flag() and current_user.get("role") in mfa_required_roles():
        if current_user.get("aal") != "aal2":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Multi-factor authentication required for this action.",
            )
    return current_user

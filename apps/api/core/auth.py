"""
FastAPI JWT authentication dependency.
Validates Supabase-issued JWTs using the project's JWT secret.
Extracts user identity and resolves firm_id from the users table.
"""
import os
from typing import Optional
from fastapi import Header, HTTPException, status
import jwt
from core.supabase_client import get_supabase

_JWT_SECRET: Optional[str] = None


def _get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
    return _JWT_SECRET


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    Dependency: validates Bearer JWT from Supabase Auth.
    Returns dict with: auth_user_id, firm_id, email, role
    If SUPABASE_JWT_SECRET is not set, returns a dev fallback (firm-001).
    """
    secret = _get_jwt_secret()

    # Dev fallback — only allowed when APP_ENV=development AND secret is unset.
    # In production this path is unreachable: SUPABASE_JWT_SECRET is always set.
    if not secret:
        app_env = os.environ.get("APP_ENV", "production")
        if app_env != "development":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server configuration error: SUPABASE_JWT_SECRET not set",
            )
        return {
            "auth_user_id": "dev-user",
            "firm_id": "firm-001",
            "email": "dev@caflow.ai",
            "role": "Partner",
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    auth_user_id: str = payload.get("sub", "")
    if not auth_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim")

    # Resolve firm_id from users table
    supabase = get_supabase()
    result = (
        supabase.table("users")
        .select("firm_id, role, full_name")
        .eq("auth_user_id", auth_user_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found in firm. Contact your firm administrator.",
        )

    return {
        "auth_user_id": auth_user_id,
        "firm_id": result.data["firm_id"],
        "email": payload.get("email", ""),
        "role": result.data.get("role", "Executive"),
        "full_name": result.data.get("full_name", ""),
    }

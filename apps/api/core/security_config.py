"""
M6 — security feature flags (env-driven, default OFF).

Two pieces of this milestone cannot be validated without a live multi-user
Supabase environment, so they ship behind flags and are turned on only after
validation in staging:

  USE_USER_JWT   — route the backend's DB access through a per-user JWT client
                   (anon key + caller's bearer token) so Postgres RLS applies to
                   the API path, instead of the service-role key that bypasses RLS.
  REQUIRE_MFA    — enforce MFA (aal2) for sensitive roles/actions.
  MFA_REQUIRED_ROLES — comma-separated roles that must present aal2 when REQUIRE_MFA
                   is on (default: Partner).

Everything else in M6 is enforced unconditionally.
"""
import os


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def use_user_jwt() -> bool:
    """Per-user JWT DB cutover (staged). OFF ⇒ backend keeps using service_role."""
    return _flag("USE_USER_JWT")


def require_mfa() -> bool:
    """MFA enforcement (staged). OFF ⇒ no aal2 requirement."""
    return _flag("REQUIRE_MFA")


def mfa_required_roles() -> set[str]:
    """Roles that must present aal2 when REQUIRE_MFA is on.

    PARTNER AND MANAGER, not Partner alone. The guard filters by role, so the
    role list and the guarded routers have to be chosen together: payroll RBAC
    is Manager+ (core/permissions.py), so putting payroll behind the guard while
    this held only "Partner" would leave every Manager who runs payroll
    unchallenged. The router would look guarded and would not be.

    Executive and Reviewer are deliberately out: neither can reach payroll, and
    neither can reach the four firm-administration routers that carry the guard,
    so including them would add a login step that protects nothing. If a surface
    they CAN reach is ever put behind the guard — documents, clients — this list
    has to be revisited in the same change.
    """
    raw = os.environ.get("MFA_REQUIRED_ROLES", "Partner,Manager")
    return {r.strip() for r in raw.split(",") if r.strip()}

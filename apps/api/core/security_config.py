"""
M6 — security feature flags.

Two switches decide whether the two strongest controls this product has are
actually in force:

  USE_USER_JWT   — route the backend's DB access through a per-user JWT client
                   (anon key + caller's bearer token) so Postgres RLS applies to
                   the API path, instead of the service-role key that bypasses RLS.
  REQUIRE_MFA    — enforce MFA (aal2) for sensitive roles/actions.
  MFA_REQUIRED_ROLES — comma-separated roles that must present aal2 when REQUIRE_MFA
                   is on (default: Partner, Manager).

THE DEFAULT DEPENDS ON WHERE THE PROCESS IS RUNNING (SECURITY-PRIVACY-16)
    Both used to default to false everywhere, and `render.yaml` declares them
    `sync: false`, so nothing in the repository could see production's values —
    the only record that the answer is "true" was a comment. An unset pair
    already cost an outage on 2026-08-15, and the QUIET half of that failure is
    the dangerous one: USE_USER_JWT unset means `service_role`, which BYPASSES
    row-level security on every request, while the API keeps answering normally.

    So with `APP_ENV=production` an UNSET (or blank, or unrecognisable) value now
    means ON. An explicit "false" is still honoured — it is the operator's own
    emergency switch (the user-JWT path needs grants and an anon key, and a way
    to roll back without a deploy is worth having) — but it is no longer silent:
    `core/security_posture.py` logs it at ERROR at boot and reports it on the
    Partner-only posture endpoint.

    **`production` means APP_ENV is literally "production"**, not "APP_ENV is not
    development". `core/auth.py` reads an unset APP_ENV as production for its
    header-auth gate, and that is right THERE (it can only refuse more). It would
    be wrong here: the whole unit-test suite and every local run leave APP_ENV
    unset, and turning MFA and the per-user client on for them would change what
    they exercise. The gap that leaves — a real deployment that forgot APP_ENV —
    is reported by the posture check as its own ERROR rather than papered over.
"""
import os

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

def app_env() -> str:
    """APP_ENV, trimmed and lower-cased; "" when unset."""
    return os.environ.get("APP_ENV", "").strip().lower()


def is_production() -> bool:
    """True only when APP_ENV is explicitly "production". See the module header."""
    return app_env() == "production"


def flag_setting(name: str) -> bool | None:
    """What the environment EXPLICITLY says about a flag, or None.

    None covers unset, blank and unrecognisable ("ture", "disabled"), because
    all three are the same fact to a safety switch: nobody made a decision the
    code can read. Kept separate from `_flag` so the posture report can say
    "defaulted" as distinct from "set".
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def flag_value_unrecognised(name: str) -> bool:
    """A non-blank value that is neither a true word nor a false one."""
    raw = (os.environ.get(name) or "").strip()
    return bool(raw) and flag_setting(name) is None


def _flag(name: str, *, production_default: bool = False) -> bool:
    explicit = flag_setting(name)
    if explicit is not None:
        return explicit
    return production_default and is_production()


def use_user_jwt() -> bool:
    """Per-user JWT DB cutover. OFF ⇒ backend uses service_role (RLS bypassed).

    In production an unset value is ON — see the module header.
    """
    return _flag("USE_USER_JWT", production_default=True)


def require_mfa() -> bool:
    """MFA enforcement. OFF ⇒ no aal2 requirement.

    In production an unset value is ON — see the module header.
    """
    return _flag("REQUIRE_MFA", production_default=True)


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


def mfa_required_for(role: str | None) -> bool:
    """Whether a caller holding `role` must present aal2.

    The one comparison `core.auth.mfa_guard` makes, named so that
    `GET /api/security/mfa-policy` tells the browser the SAME answer rather
    than the browser re-deriving it from a role list. The raw stored role is
    compared, exactly as the guard compares it, so a legacy spelling cannot
    make the two disagree.
    """
    return require_mfa() and role in mfa_required_roles()

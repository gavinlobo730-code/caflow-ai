"""
Platform Admin authorization — COMPLETELY separate from the firm RBAC model.

A platform admin is identified ONLY by membership in the platform_admins
allowlist (an auth_user_id), never by a firm role (Partner/Manager/...). These
dependencies do not touch core.permissions / core.authz at all, so a firm user
can never reach platform powers through any role or assignment change.

Platform endpoints are cross-tenant BY DESIGN and use the service-role client;
access is gated to the vetted allowlist and every mutating action is audited.

THE LOCKS ON A PLATFORM PAGE (POST-B-351, the owner's decision of 25-11-2026), in the order they are asked:
  1. the account is on the platform list, or the answer is a plain 404 (a firm user cannot tell the pages exist);
  2. the session passed the authenticator code (`aal2`) — every platform read, not only the destructive actions,
     which additionally need a code from the last five minutes (`require_platform_admin_mfa`, POST-A-484);
  3. the account belongs to no firm, client portal or employee portal — ONCE the list has held at least one account
     that belongs to none (recorded once in `platform_audit` and never undone, so the rule cannot switch itself off). Until then a list made only of firm members is let through, every mail says so, and nothing
     has to be switched: adding the dedicated account is what turns the rule on, so the owner is never locked out
     by a deploy and an old account cannot quietly stay in use beside the new one;
  4. the first request of each sign-in session, and every action, is mailed to everybody on the list
     (`services/platform_notice`).
A read that cannot answer lock 3 refuses (503): a check that fails open is not a check.
"""
import logging
import time
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, status
from core import auth_time
from core.auth import get_jwt_user

_logger = logging.getLogger("caflow.platform")


def _is_platform_admin(auth_user_id: str) -> bool:
    if not auth_user_id:
        return False
    try:
        from core.supabase_client import get_service_supabase
        res = (
            get_service_supabase()
            .table("platform_admins")
            .select("auth_user_id")
            .eq("auth_user_id", auth_user_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:  # pragma: no cover - defensive
        _logger.error("platform_admin lookup failed: %s", e)
        return False


def is_platform_admin(jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Non-failing — returns the caller plus an is_platform_admin flag and whether the session still needs the second
    factor. Used by GET /api/platform/me for UI gating (does NOT deny non-admins, and is not a platform visit: nothing is
    mailed for it)."""
    listed = _is_platform_admin(jwt_user.get("auth_user_id", ""))
    return {**jwt_user, "is_platform_admin": listed,
            "second_factor_needed": listed and jwt_user.get("aal") != "aal2"}


SECOND_FACTOR_SENTENCE = (
    "The platform pages need your authenticator code: sign out, sign in again and enter the code when it is asked for."
)
STANDING_UNREADABLE_SENTENCE = (
    "The platform pages could not check whether this account belongs to a firm just now, so they stay closed. "
    "Please try again in a moment."
)

# The tables whose rows make a sign-in account somebody inside a firm: a member of staff, a client's portal contact,
# an employee with portal access. A platform account is none of them.
PRINCIPAL_TABLES = ("users", "client_portal_users", "payroll_employees", "clients")
#: The `platform_audit` row that says the firm-less rule has turned on. Once written it is never undone by this code, so
#: the rule cannot switch itself off if the dedicated account later gains a firm row (by running the new-practice wizard
#: or accepting an invitation, found by the independent review of 27-11-2026): that account is then refused too, which
#: is loud, instead of the old firm-member accounts quietly being let back in.
FIRMLESS_RULE_ON = "platform_firmless_rule_on"


@dataclass(frozen=True)
class Standing:
    belongs_to: tuple[str, ...]          # which PRINCIPAL_TABLES hold a row for this account (empty: it belongs to no firm)
    firmless_admin_on_list: bool         # whether any account on the platform list belongs to no firm


def _tables_holding(db, auth_user_id: str) -> tuple[str, ...]:
    """Which PRINCIPAL_TABLES hold a row for this account. Each table is named outright, not looped over, so the
    firm-scope guard reads each query (a table named by a variable is one of its blind spots)."""
    staff = db.table("users").select("auth_user_id").eq("auth_user_id", auth_user_id).limit(1).execute().data
    portal = (db.table("client_portal_users").select("auth_user_id")
              .eq("auth_user_id", auth_user_id).limit(1).execute().data)
    employee = (db.table("payroll_employees").select("auth_user_id")
                .eq("auth_user_id", auth_user_id).limit(1).execute().data)
    # The legacy one-contact portal link on the client's own row (`portal_access_service._legacy_client`).
    legacy = db.table("clients").select("id").eq("portal_user_id", auth_user_id).limit(1).execute().data
    found = {"users": staff, "client_portal_users": portal, "payroll_employees": employee, "clients": legacy}
    return tuple(t for t in PRINCIPAL_TABLES if found[t])


def _firm_standing(auth_user_id: str) -> Standing:
    """Lock 3's two facts. Raises on a failed read; the gate turns that into a refusal."""
    from core.supabase_client import get_service_supabase
    db = get_service_supabase()
    mine = _tables_holding(db, auth_user_id)
    turned_on = bool(db.table("platform_audit").select("id").eq("action", FIRMLESS_RULE_ON).limit(1).execute().data)
    if turned_on:
        return Standing(belongs_to=mine, firmless_admin_on_list=True)
    listed = [r.get("auth_user_id") for r in (db.table("platform_admins").select("auth_user_id").execute().data or [])]
    firmless = [str(uid) for uid in listed if uid and not _tables_holding(db, str(uid))]
    if firmless:
        db.table("platform_audit").insert({"action": FIRMLESS_RULE_ON, "actor_auth_user_id": firmless[0],
                                           "metadata": {"firmless_accounts": len(firmless)}}).execute()
    return Standing(belongs_to=mine, firmless_admin_on_list=bool(firmless))


def require_platform_admin(request: Request, jwt_user: dict = Depends(get_jwt_user)) -> dict:
    """Deny-by-default gate for platform endpoints, the locks in the module's docstring in order. A caller who is not on
    the list, or whose account belongs to a firm once a firm-less account is listed, gets 404 (not 403) so a firm user
    cannot even confirm the platform surface exists."""
    uid = jwt_user.get("auth_user_id", "")
    if not _is_platform_admin(uid):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if jwt_user.get("aal") != "aal2":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SECOND_FACTOR_SENTENCE)
    try:
        standing = _firm_standing(uid)
    except Exception as exc:                             # noqa: BLE001 — refused in words, logged here
        _logger.error("could not read whether a platform administrator belongs to a firm", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STANDING_UNREADABLE_SENTENCE) from exc
    if standing.belongs_to and standing.firmless_admin_on_list:
        _logger.warning("a platform administrator who belongs to a firm (%s) was refused: the list holds a firm-less account",
                        ",".join(standing.belongs_to))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    admin = {**jwt_user, "platform_transitional": bool(standing.belongs_to)}
    from core.client_ip import client_ip
    from services import platform_notice
    platform_notice.later(platform_notice.note_visit, admin, client_ip(request))
    return admin


def require_platform_admin_mfa(admin: dict = Depends(require_platform_admin)) -> dict:
    """Destructive actions (suspend, soft delete, permanent delete) need a session that passed the second factor
    AND an authenticator code entered in the last five minutes (POST-A-484).

    `aal2` alone is true for the whole life of a session that passed the second factor once, so a left-open platform
    page could suspend, delete or purge a firm hours later. The token carries when the code was entered
    (`core/auth_time`); the page asks for a fresh one when it is refused with FRESH_CODE_SENTENCE."""
    if admin.get("aal") != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication is required for this action. Enrol at Settings → Security.",
        )
    if not auth_time.authenticator_code_is_fresh(admin.get("last_authenticator_code_at"), time.time()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=auth_time.FRESH_CODE_SENTENCE)
    return admin

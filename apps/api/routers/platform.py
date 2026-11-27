"""
Platform Admin API — /api/platform.

Cross-tenant visibility + control for the PracticeSync owner. Every endpoint is
gated by the platform_admins allowlist (require_platform_admin), uses the
service-role DB client (intentionally bypassing firm RLS), and audits every
mutation. This router is intentionally NOT part of firm RBAC.

Scope: list firms + stats, view a firm + its users, suspend / unsuspend, SOFT delete,
and a PERMANENT delete (`DELETE /firms/{id}/permanent`, irreversible, behind a typed
firm name and a fresh authenticator code). No billing, impersonation, or cross-firm
data editing. (This docstring said "no hard delete" for as long as the purge existed.)

CLOSING A FIRM SIGNS ITS PEOPLE OUT (POST-A-482, POST-A-499). Suspend and soft delete change
`firms.is_active` / `deleted_at`, which the API reads (`core/auth`: "Firm suspended",
"Firm unavailable") a few seconds later, and ALSO stamp `users.sessions_revoked_at` for
every member of the firm, so a token the person already holds is refused 401 even after
the firm is reopened (`core/auth_time` says why `iat` alone would not hold). Unsuspending
does not undo it: people sign in again. A PERMANENT delete stamps nothing, because it deletes
the members' `users` rows, which is where that stamp lives: it writes a row in
`closed_account_markers` (migration 772) for each member BEFORE the purge, and `core/auth`
answers a session older than the marker from that row.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from models.common import api_response
from core.platform_auth import require_platform_admin, require_platform_admin_mfa, is_platform_admin
from core.supabase_client import get_service_supabase
from services.audit_service import log_event
from services import platform_notice

router = APIRouter(prefix="/api/platform", tags=["platform"])
_logger = logging.getLogger("caflow.platform")


class SuspendBody(BaseModel):
    reason: str


def _end_sessions(db, firm_id: str) -> int:
    """Stamp `sessions_revoked_at` on every member of the firm, through the service client and naming the firm, and
    return how many were stamped. Raises on a failed write: a closure that leaves the people signed in has not done
    what it says."""
    now = datetime.now(timezone.utc).isoformat()
    res = db.table("users").update({"sessions_revoked_at": now}).eq("firm_id", firm_id).execute()
    # The list of who is signed in where (POST-A-486) is told too, so a closed firm's people are not listed as signed in for forty
    # minutes. Best-effort: the stamp above is what ends the sessions, and before migration 765 is applied there is no such table.
    try:
        db.table("login_sessions").update({"ended_at": now, "ended_how": "forced"}).eq("firm_id", firm_id).is_("ended_at", "null").execute()
    except Exception:                                    # noqa: BLE001
        logging.getLogger("caflow.platform").warning("could not close the session rows of firm %s", firm_id, exc_info=True)
    return len(res.data or [])


def _mark_closed_accounts(db, firm_id: str) -> list[str]:
    """Write a marker for every member of the firm BEFORE it is purged, and return whose (POST-A-499).

    The purge deletes the members' `users` rows, which is where `sessions_revoked_at` lives, and leaves the sign-in accounts: a person
    who held a session then reached "User not found in firm" and the new-practice wizard, signed out of nothing and told nothing. The
    marker survives the row: `core/auth.get_current_user` reads it on that path and answers a session that began before it 403 "Firm
    unavailable", which the browser turns into a sign-out and a sentence. A platform administrator is left out, because their access to
    the platform page survives the purge of their own firm by design (`purge_firm`'s docstring). Raises when the markers cannot be
    written: a purge that leaves its people sent to the wizard has not done what the screen says, so the firm is left whole instead."""
    members = db.table("users").select("auth_user_id").eq("firm_id", firm_id).execute().data or []
    people = {str(m["auth_user_id"]): m for m in members if m.get("auth_user_id")}          # one per sign-in account
    if not people:
        return []
    admins = db.table("platform_admins").select("auth_user_id").in_("auth_user_id", sorted(people)).execute().data or []
    admin_ids = {str(a["auth_user_id"]) for a in admins}
    to_mark = [m for i, m in people.items() if i not in admin_ids]
    if not to_mark:
        return []
    now = datetime.now(timezone.utc).isoformat()
    # The payload is written out at the call, naming the SIGN-IN id each member row carries: the backend's schema guard reads a payload
    # only when it is a literal at the call, and the person-column guard reads which kind of id the column is given from this value.
    db.table("closed_account_markers").upsert(
        [{"auth_user_id": m["auth_user_id"], "closed_at": now, "closed_how": "firm_purged"} for m in to_mark],
        on_conflict="auth_user_id").execute()
    return [str(m["auth_user_id"]) for m in to_mark]


def _unmark_closed_accounts(db, auth_user_ids: list[str]) -> None:
    """Take back the markers of a purge that did not happen, best effort (POST-A-499).

    A marker says "this account's firm was permanently deleted at this instant", and a purge that failed after the markers were
    written has made that false. It is read only for an account with no member row, so a leftover would mislabel a person removed from
    their firm later as someone whose firm was deleted; this removes it, and logs rather than raises when it cannot, because the
    failure that matters is the purge's, which is re-raised by the caller."""
    if not auth_user_ids:
        return
    try:
        db.table("closed_account_markers").delete().in_("auth_user_id", auth_user_ids).execute()
    except Exception:                                    # noqa: BLE001 — logged; the purge's own failure is what the caller raises
        _logger.exception("could not take back the closed-account markers of a purge that failed (%d accounts)", len(auth_user_ids))


def _count(db, table: str, **eq) -> int:
    q = db.table(table).select("id", count="exact").limit(1)
    for k, v in eq.items():
        q = q.eq(k, v)
    return q.execute().count or 0


def _firm_status(firm: dict) -> str:
    if firm.get("deleted_at"):
        return "deleted"
    return "active" if firm.get("is_active", True) else "suspended"


# ─── Identity / gating ───────────────────────────────────────────────────────
@router.get("/me")
def me(ctx: dict = Depends(is_platform_admin)):
    """UI gating — non-failing; returns whether the caller is a platform admin."""
    return api_response(True, {"is_platform_admin": ctx.get("is_platform_admin", False),
                               "second_factor_needed": ctx.get("second_factor_needed", False)})


# ─── Stats ───────────────────────────────────────────────────────────────────
@router.get("/stats")
def stats(_admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firms = db.table("firms").select("id, is_active, deleted_at").execute().data or []
    active = sum(1 for f in firms if not f.get("deleted_at") and f.get("is_active", True))
    suspended = sum(1 for f in firms if not f.get("deleted_at") and not f.get("is_active", True))
    return api_response(True, {
        "total_firms": len(firms),
        "active_firms": active,
        "suspended_firms": suspended,
        "total_users": _count(db, "users"),
        "total_clients": _count(db, "clients", is_internal=False),
    })


# ─── Firms ───────────────────────────────────────────────────────────────────
@router.get("/firms")
def list_firms(_admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firms = (db.table("firms").select("id, name, created_at, is_active, deleted_at")
             .order("created_at", desc=True).execute().data or [])
    out = []
    for f in firms:
        out.append({
            "id": f["id"],
            "name": f.get("name"),
            "created_at": f.get("created_at"),
            "users": _count(db, "users", firm_id=f["id"]),
            "clients": _count(db, "clients", firm_id=f["id"], is_internal=False),
            "status": _firm_status(f),
        })
    return api_response(True, out)


@router.get("/firms/{firm_id}")
def firm_detail(firm_id: str, _admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firm = db.table("firms").select("*").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    return api_response(True, {
        "id": firm["id"],
        "name": firm.get("name"),
        "email": firm.get("email"),
        "created_at": firm.get("created_at"),
        "status": _firm_status(firm),
        "users": _count(db, "users", firm_id=firm_id),
        "clients": _count(db, "clients", firm_id=firm_id, is_internal=False),
    })


@router.get("/firms/{firm_id}/users")
def firm_users(firm_id: str, _admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    rows = (db.table("users").select("full_name, email, role, is_active")
            .eq("firm_id", firm_id).order("role").execute().data or [])
    return api_response(True, [{
        "name": r.get("full_name"),
        "email": r.get("email"),
        "role": r.get("role"),
        "status": "active" if r.get("is_active", True) else "inactive",
    } for r in rows])


# ─── What has been done on the platform pages (POST-B-351) ────────────────────
@router.get("/activity")
def activity(_admin: dict = Depends(require_platform_admin)):
    """The last fifty platform sign-ins and actions, newest first, from `platform_audit`: what the mails said, kept
    where the platform pages can show it, so a sign-in nobody remembers is seen on the page as well as in the inbox."""
    db = get_service_supabase()
    rows = (db.table("platform_audit").select("action, firm_name, actor_email, metadata, created_at")
            .order("created_at", desc=True).order("id", desc=True).limit(50).execute().data or [])
    return api_response(True, [{
        "action": r.get("action"),
        "firm_name": r.get("firm_name"),
        "by": r.get("actor_email"),
        "address": (r.get("metadata") or {}).get("address"),
        "mailed": (r.get("metadata") or {}).get("mailed"),
        "at": r.get("created_at"),
    } for r in rows])


# ─── Suspend / unsuspend / soft-delete ──────────────────────────────────────
@router.post("/firms/{firm_id}/suspend")
def suspend_firm(firm_id: str, body: SuspendBody,
                 admin: dict = Depends(require_platform_admin_mfa)):
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to suspend a firm.")
    db = get_service_supabase()
    firm = db.table("firms").select("id, name, is_active").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    # The sessions are ended FIRST: a stamp that fails then leaves the firm open and the request refused, to be tried again,
    # and not a closed firm with people still signed in and no audit row (found by the independent review of this change).
    signed_out = _end_sessions(db, firm_id)
    db.table("firms").update({"is_active": False}).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_suspend",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"),
              metadata={"reason": body.reason.strip(), "sessions_ended": signed_out})
    platform_notice.later(platform_notice.note_action, admin, "platform_suspend", firm_id, firm.get("name"),
                              f"Reason given: {body.reason.strip()}. {signed_out} people were signed out.")
    return api_response(True, {"firm_id": firm_id, "status": "suspended", "sessions_ended": signed_out})


@router.post("/firms/{firm_id}/unsuspend")
def unsuspend_firm(firm_id: str, admin: dict = Depends(require_platform_admin)):
    db = get_service_supabase()
    firm = db.table("firms").select("id, name, deleted_at").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    if firm.get("deleted_at"):
        raise HTTPException(status_code=409, detail="Cannot unsuspend a deleted firm.")
    db.table("firms").update({"is_active": True}).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_unsuspend",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"))
    platform_notice.later(platform_notice.note_action, admin, "platform_unsuspend", firm_id, firm.get("name"))
    return api_response(True, {"firm_id": firm_id, "status": "active"})


@router.delete("/firms/{firm_id}")
def soft_delete_firm(firm_id: str, admin: dict = Depends(require_platform_admin_mfa)):
    db = get_service_supabase()
    firm = db.table("firms").select("id, name").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    # SOFT delete only — records are preserved. Sessions first, for the reason in suspend_firm.
    signed_out = _end_sessions(db, firm_id)
    db.table("firms").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "is_active": False,
    }).eq("id", firm_id).execute()
    log_event(firm_id, "firm", firm_id, "platform_delete",
              actor_id=admin.get("auth_user_id"), actor_email=admin.get("email"),
              metadata={"sessions_ended": signed_out})
    platform_notice.later(platform_notice.note_action, admin, "platform_delete", firm_id, firm.get("name"),
                              f"{signed_out} people were signed out.")
    return api_response(True, {"firm_id": firm_id, "status": "deleted", "sessions_ended": signed_out})


@router.delete("/firms/{firm_id}/permanent")
def purge_firm(firm_id: str, admin: dict = Depends(require_platform_admin_mfa)):
    """PERMANENT (hard) delete — irreversible. Removes the firm and ALL of its
    data (users rows, clients, every firm-scoped table) via platform_purge_firm,
    which disables FK enforcement for its own transaction to handle the mixed
    CASCADE / NO ACTION constraints. Auth login accounts are intentionally left
    intact (so the platform admin's own access survives purging their firm).
    Gated by aal2 (require_platform_admin_mfa).

    A PURGE ENDS ITS PEOPLE'S SESSIONS BY A MARKER, NOT A STAMP (POST-A-499). The sessions of a closed firm end by a stamp on the
    member's `users` row, and this deletes those rows, so before the purge each member gets a row in `closed_account_markers`
    (migration 772), which survives it. A session that began before the purge is then answered 403 "Firm unavailable" and the
    browser signs the person out and says the firm is closed; a sign-in made after it is not refused, so the person may start a new
    practice with the same login. Platform administrators are not marked. If the markers cannot be written the purge does not run."""
    db = get_service_supabase()
    firm = db.table("firms").select("id, name").eq("id", firm_id).maybe_single().execute().data
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    try:
        marked = _mark_closed_accounts(db, firm_id)
    except Exception as exc:                             # noqa: BLE001 — logged here; the firm is left whole and the person told
        _logger.exception("could not mark the members of firm %s as closed; the purge was not run", firm_id)
        raise HTTPException(status_code=503, detail=(
            "The firm's people could not be marked as closed just now, so nothing was deleted. Please try again in a moment.")) from exc
    try:
        removed = db.rpc("platform_purge_firm", {"p_firm_id": firm_id}).execute().data
    except Exception:
        _unmark_closed_accounts(db, marked)              # the firm is still whole, so nobody of it is "closed"
        raise
    # Told BEFORE the audit row is written, so a purge whose row then fails is still mailed (the review of 27-11-2026).
    platform_notice.later(platform_notice.note_action, admin, "platform_purge", firm_id, firm.get("name"),
                          f"{len(marked)} people were told their firm is closed.", record=False)
    # Durable platform-level audit — written AFTER the purge so it is not swept
    # away with the firm's own (firm-scoped) audit_logs.
    db.table("platform_audit").insert({
        "action": "platform_purge",
        "target_firm_id": firm_id,
        "firm_name": firm.get("name"),
        "actor_auth_user_id": admin.get("auth_user_id"),
        "actor_email": admin.get("email"),
        "metadata": {**(removed or {}), "people_marked_closed": len(marked)},
    }).execute()
    return api_response(True, {"firm_id": firm_id, "status": "purged", "removed": removed, "people_marked_closed": len(marked)})

"""
M6 — Identity Administration backend (audited, server-side).

Replaces the client-side identity mutations in team/page.tsx with authorized,
audited backend APIs. Partner-only writes (rbac team:write); Manager+ reads.

Capabilities: create user, activate, suspend (kills sessions), reactivate, change
role, force-logout (single + firm-wide), login history. Every mutation is written
to audit_log; session-affecting actions also record a login_events row and bump
users.sessions_revoked_at so existing JWTs are rejected immediately.
"""
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from middleware.public_rate_limit import public_limit
from models.common import api_response
from core.auth import get_current_user, get_jwt_user
from core.list_window import probe, split
from core.permissions import rbac, Role, canonical_role, get_accessible_resources
from domain.firm.invite_token import is_stored_form, opens_a_sign_in
from domain.firm.member_state import member_state
from repositories.user_repository import user_repo
from repositories.login_events_repository import login_events_repo
from services import staff_invite_service
from services.audit_service import log_event

router = APIRouter(prefix="/api/identity", tags=["identity"])

# Mounted in main.py WITHOUT _MFA_GUARD: the invitee has no users row yet, and
# mfa_guard's get_current_user refuses exactly that caller, so on the guarded
# router no invite could ever be accepted. Two routes belong on it and nothing
# else: accept-invite, and the sign-in the join page opens from the invitation's
# own link before it accepts (POST-A-445).
invite_router = APIRouter(prefix="/api/identity", tags=["identity"])

_CANONICAL = {r.value for r in Role}

_INVALID_INVITE = "Invalid or expired invite."

#: Why a sign-in that already belongs to a practice cannot accept another invitation (POST-A-445).
ALREADY_A_MEMBER = ("This sign-in already belongs to a member of a practice on PracticeSync, and one sign-in can "
                    "belong to one practice. Ask the practice that invited you to send the invitation to another "
                    "email address.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateUserBody(BaseModel):
    full_name: str
    email: str
    role: str


class RoleBody(BaseModel):
    role: str


def _get_member(user_id: str, firm_id: str) -> dict:
    # Scoped in the query (the repository reads as the service role) AND
    # re-checked here, so a fake or a future repository change cannot widen it.
    member = user_repo.find_by_id(user_id, firm_id=firm_id)
    if not member or member.get("firm_id") != firm_id:
        raise HTTPException(404, "User not found in firm")
    return member


@router.get("/users")
def list_users(current_user: dict = Depends(rbac("team", "read"))):
    # The list carries every member of the firm (the repository reads as the service role). No row carries an
    # invitation's token: the repository returns none but through `find_by_invite_token` (POST-A-445), and the
    # strip below is the second lock. Each row carries `member_state` (PRE-A-020), so the Team screen shows
    # Invited or Invite expired for someone who has not accepted, never Active.
    now = datetime.now(timezone.utc)
    users = [{**{k: v for k, v in u.items() if k != "invite_token"}, "member_state": member_state(u, now)}
             for u in user_repo.find_all(firm_id=current_user["firm_id"])]
    return api_response(True, {"users": users})


def _invite_answer(row: dict, mail: "staff_invite_service.MailResult", now: datetime) -> dict:
    """A member row as the Team screen is sent it after an invitation: its state, what became of the mail, and
    never the token (POST-A-445). The token reaches the invitee's mailbox and nobody else."""
    return {**{k: v for k, v in row.items() if k != "invite_token"},
            "member_state": member_state(row, now), "invite_mail": mail.as_dict()}


@router.post("/users")
def create_user(body: CreateUserBody, current_user: dict = Depends(rbac("team", "write"))):
    if body.role not in _CANONICAL:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(sorted(_CANONICAL))}")
    firm_id = current_user["firm_id"]
    # F21 fix: the invite link carries a single-use, expiring, server-issued token (never the firm_id or role
    # themselves); /join exchanges it through POST /api/identity/accept-invite. POST-A-445: the server mails it,
    # naming the practice and the Partner, and the answer no longer carries it.
    now = datetime.now(timezone.utc)
    invitation = staff_invite_service.fresh_invitation(now)
    created = user_repo.create({
        "firm_id": firm_id, "full_name": body.full_name, "email": body.email,
        "role": body.role, "is_active": True, "status": "invited", **invitation.columns,
    })
    log_event(firm_id, "user", str(created.get("id", "")), "create",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"email": body.email, "role": body.role})
    mail = staff_invite_service.send({**created, "firm_id": firm_id}, invitation, current_user)
    return api_response(True, _invite_answer({**created, **invitation.columns}, mail, now))


@router.post("/users/{user_id}/resend-invite")
def resend_invite(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    """Send a member's invitation again, with a fresh token and expiry (POST-A-445).

    The fresh token REPLACES the old one, so the link in an earlier mail stops working: a mail sent to a wrong or
    lost address is withdrawn by sending the right one. If the new mail does not go, the old token and expiry are
    put back, so a link that still worked keeps working, and the answer says so (`invite_mail.kept_previous`). Only
    somebody still waiting to join is sent one: a member who has joined has nothing to accept, and a withdrawn
    invitation is switched back on first (Activate), because a Partner who withdrew it decided once already and a
    resend is not the place to undo that silently."""
    firm_id = current_user["firm_id"]
    member = _get_member(user_id, firm_id)
    name = member.get("full_name") or member.get("email") or "This member"
    now = datetime.now(timezone.utc)
    state = member_state(member, now)
    if member.get("auth_user_id"):
        raise HTTPException(409, f"{name} has already joined, so there is no invitation to send.")
    if state == "inactive":
        raise HTTPException(409, f"The invitation to {name} was withdrawn. Activate them first, "
                                 "then send the invitation again.")
    if state not in ("invited", "invite_expired"):
        raise HTTPException(409, f"{name} is not waiting on an invitation, so there is none to send.")
    previous = user_repo.invite_columns(user_id, firm_id=firm_id)
    # Only an earlier invitation whose link still WORKS is worth putting back if the new mail fails: one that is
    # live (`invited`) and kept hashed, i.e. one the server mailed and whose link can still sign its owner in.
    previous_works = bool(previous) and state == "invited" and is_stored_form(previous.get("invite_token"))
    invitation = staff_invite_service.fresh_invitation(now)
    updated = user_repo.update(user_id, invitation.columns, firm_id=firm_id)
    if not updated:
        raise HTTPException(404, "User not found in firm")
    mail = staff_invite_service.send({**member, **updated, "firm_id": firm_id}, invitation, current_user)
    restored = None
    if not mail.sent and previous_works:
        # The new mail did not go: put the earlier invitation back, so its link keeps working, but only while the row
        # still holds the invitation this request wrote (a withdraw, an acceptance or another resend that landed
        # while the mail was being sent is never undone).
        restored = user_repo.restore_invitation(user_id, previous, replacing=invitation.columns["invite_token"],
                                                firm_id=firm_id)
    if not mail.sent:
        mail = staff_invite_service.MailResult(False, mail.problem, kept_previous=bool(restored))
    answer = _invite_answer({**member, **(restored or updated)}, mail, now)
    log_event(firm_id, "user", user_id, "invite_resent" if mail.sent else "invite_resend_not_sent",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"email": member.get("email"), "invite_expires_at": answer.get("invite_expires_at")})
    return api_response(True, answer)


class AcceptInviteBody(BaseModel):
    token: str


class InviteSessionBody(BaseModel):
    token: str
    #: False asks only whose invitation this is (its address), opening no sign-in: the join page asks that when the
    #: browser is signed in as somebody else, so merely looking creates nothing at Supabase (POST-A-445).
    open_sign_in: bool = True


def _live_invitation(token: str) -> dict:
    """The member row `token` invites, while the invitation can still be accepted, or the one 404 every refusal
    shares (no such token, already used, withdrawn, past its expiry): telling them apart would let somebody probe
    which tokens exist."""
    invite = user_repo.find_by_invite_token(token)
    if not invite or member_state(invite) != "invited":
        raise HTTPException(status_code=404, detail=_INVALID_INVITE)
    return invite


@invite_router.post("/accept-invite/session", dependencies=[Depends(public_limit("invite"))])
def invite_session(body: InviteSessionBody):
    """Open a sign-in from the invitation's own link (POST-A-445). No login: before this there is no session to
    require one from, and the invitation's token is what authorises the call, exactly as it authorises
    accept-invite. The join page redeems the answer with `supabase.auth.verifyOtp({token_hash, type})` and then
    calls accept-invite with the session it produces. Nothing is consumed here; accept-invite is what uses the
    token. The sign-in is for the invitation's OWN address, never one the request names, only for an invitation the
    server mailed (kept hashed; one issued before POST-A-445 is accepted from the sign-in its own mail carried), and
    never for an address that already has a sign-in (409 in words: that person signs in as usual and opens the link
    again)."""
    invite = _live_invitation(body.token)
    if not opens_a_sign_in(invite):
        raise HTTPException(status_code=404, detail=_INVALID_INVITE)
    if not body.open_sign_in:
        return api_response(True, {"email": str(invite.get("email") or "").strip()})
    return api_response(True, staff_invite_service.sign_in_for(invite, body.token))


def _already_joined(jwt_user: dict) -> Optional[dict]:
    """The caller's own membership when the caller IS an active member whose address is the one the sign-in carries,
    else None (POST-A-481).

    A repeat of accept-invite (a second click, a reload, the link opened in another tab or on a phone after the
    first one joined) found the token spent and answered the one refusal every spent token shares, so a person who
    had just joined was told their invitation "could not be used". It reveals nothing about the token: the answer is
    the caller's OWN membership, read from their own verified sign-in, and a caller with no membership still gets the
    404."""
    linked = user_repo.find_linked_member(jwt_user.get("auth_user_id") or "")
    if not linked or not linked.get("id") or not linked.get("firm_id"):
        return None
    row = user_repo.find_by_id(str(linked["id"]), firm_id=str(linked["firm_id"]))
    if not row or member_state(row) != "active":
        return None
    if (row.get("email") or "").strip().lower() != (jwt_user.get("email") or "").strip().lower():
        return None
    return {"firm_id": row.get("firm_id"), "role": row.get("role"), "full_name": row.get("full_name"),
            "already_joined": True}


@invite_router.post("/accept-invite", dependencies=[Depends(public_limit("invite"))])
def accept_invite(body: AcceptInviteBody, jwt_user: dict = Depends(get_jwt_user)):
    """Complete a staff invite (F21 fix). JWT-only auth — the caller has no
    `users` row yet (that is exactly what this endpoint creates by linking).

    Identity is established ENTIRELY from the verified Supabase JWT (auth_user_id
    + email) and the pre-created invite row (firm_id + role) — never from a
    client-supplied field. This is the only way a `users` row's auth_user_id can
    ever be set; there is no client-side insert/update path left (see migration
    153, which also removed the RLS/grant paths that made the old raw insert
    possible)."""
    # The invitation must be live: found, switched on (a Partner who deactivated a pending invitee has withdrawn
    # it, and accepting must not reactivate them; that is POST /users/{id}/reactivate, a Partner's act), and not
    # past its expiry. One rule, `member_state`, which the Team screen and the sign-in below also read.
    try:
        invite = _live_invitation(body.token)
    except HTTPException as refused:
        # A repeat by the person who already joined is answered with their membership, not a refusal (POST-A-481).
        joined = _already_joined(jwt_user) if refused.status_code == 404 else None
        if joined is not None:
            return api_response(True, joined)
        raise
    if (invite.get("email") or "").strip().lower() != (jwt_user.get("email") or "").strip().lower():
        # Defense in depth: the token alone (a 256-bit random secret only ever
        # transmitted to the invited email) is already unforgeable, but a mismatch
        # here means the wrong mailbox somehow held the link — refuse rather than
        # silently link the wrong identity.
        raise HTTPException(status_code=404, detail=_INVALID_INVITE)
    if user_repo.find_linked_member(jwt_user["auth_user_id"]):
        # One sign-in, one practice: `core/auth` reads a sign-in's member row with `maybe_single`, so a second row
        # linked to the same sign-in would lock its owner out of both practices (POST-A-445).
        raise HTTPException(status_code=409, detail=ALREADY_A_MEMBER)

    updated = user_repo.update(invite["id"], {
        "auth_user_id": jwt_user["auth_user_id"],
        "status": "active",
        "invite_token": None,
        "invite_expires_at": None,
    }, firm_id=invite["firm_id"])
    log_event(invite["firm_id"], "user", str(invite["id"]), "invite_accepted",
              actor_id=jwt_user.get("auth_user_id"), actor_email=jwt_user.get("email"))
    return api_response(True, {
        "firm_id": invite["firm_id"], "role": invite["role"], "full_name": invite.get("full_name"),
    } if updated else None)


@router.patch("/users/{user_id}/role")
def change_role(user_id: str, body: RoleBody, current_user: dict = Depends(rbac("team", "write"))):
    if body.role not in _CANONICAL:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(sorted(_CANONICAL))}")
    member = _get_member(user_id, current_user["firm_id"])
    old = member.get("role")
    updated = user_repo.update(user_id, {"role": body.role}, firm_id=current_user["firm_id"])
    log_event(current_user["firm_id"], "user_role", user_id, "update",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data={"role": old}, new_data={"role": body.role})
    return api_response(True, updated)


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    member = _get_member(user_id, current_user["firm_id"])
    # Disable AND revoke sessions so any existing JWT is rejected immediately.
    change = {"is_active": False, "sessions_revoked_at": _now()}
    if member.get("auth_user_id") is None:
        # A pending invitee has no session to revoke, only the emailed link:
        # withdraw it, so a later reactivate does not revive it either.
        change.update({"invite_token": None, "invite_expires_at": None})
    updated = user_repo.update(user_id, change, firm_id=current_user["firm_id"])
    log_event(current_user["firm_id"], "user", user_id, "suspend",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"))
    login_events_repo.record(current_user["firm_id"], user_id, member.get("email"), "suspended")
    return api_response(True, updated)


@router.post("/users/{user_id}/reactivate")
def reactivate_user(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    _get_member(user_id, current_user["firm_id"])
    updated = user_repo.update(user_id, {"is_active": True}, firm_id=current_user["firm_id"])
    log_event(current_user["firm_id"], "user", user_id, "reactivate",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"))
    return api_response(True, updated)


@router.post("/users/{user_id}/force-logout")
def force_logout(user_id: str, current_user: dict = Depends(rbac("team", "write"))):
    member = _get_member(user_id, current_user["firm_id"])
    updated = user_repo.update(user_id, {"sessions_revoked_at": _now()}, firm_id=current_user["firm_id"])
    log_event(current_user["firm_id"], "user", user_id, "force_logout",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"))
    login_events_repo.record(current_user["firm_id"], user_id, member.get("email"), "forced_logout")
    return api_response(True, updated)


@router.post("/force-logout-all")
def force_logout_all(current_user: dict = Depends(rbac("team", "write"))):
    """Global logout — revoke every user's sessions in the firm."""
    firm_id = current_user["firm_id"]
    now = _now()
    count = 0
    for m in user_repo.find_all(firm_id=firm_id):
        user_repo.update(m["id"], {"sessions_revoked_at": now}, firm_id=firm_id)
        count += 1
    log_event(firm_id, "firm", firm_id, "force_logout_all",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              metadata={"users_affected": count})
    return api_response(True, {"users_affected": count})


@router.get("/users/{user_id}/login-history")
def user_login_history(user_id: str, current_user: dict = Depends(rbac("team", "read"))):
    _get_member(user_id, current_user["firm_id"])
    return api_response(True, {"events": login_events_repo.list_for_user(current_user["firm_id"], user_id)})


#: The most login events one read of the firm's history may ask for. Served to the screen as `max_limit`.
LOGIN_HISTORY_MAX = 1000


@router.get("/login-history")
def firm_login_history(
    limit: Annotated[int, Query(ge=1, le=LOGIN_HISTORY_MAX)] = 200,
    current_user: dict = Depends(rbac("team", "read")),
):
    """The firm's latest `limit` login events and whether older ones exist (core/list_window). The screen used to decide
    it had been cut short by comparing the row count to the number it expected the server to default to (POST-A-262)."""
    events, has_more = split(login_events_repo.list_for_firm(current_user["firm_id"], limit=probe(limit)), limit)
    return api_response(True, {
        "events": events, "returned": len(events), "has_more": has_more,
        "limit": limit, "max_limit": LOGIN_HISTORY_MAX,
    })


# ─── Self-service: what may the caller do? ───────────────────────────────────
# Deliberately guarded by get_current_user, NOT by rbac(). Gating "which actions
# am I allowed?" behind a permission is circular — every role would need it, so
# the guard would assert nothing while implying it asserts something.
#
# This exists so the FRONTEND stops re-deriving the matrix. Before this, the UI
# hardcoded role lists (hasRole(role, ["Partner","Manager"])) beside each button,
# which drifts the moment core/permissions.py changes: an Executive was still
# shown accounting write actions the backend answers with 403. Serving the
# matrix means there is exactly one copy of it, here.
#
# Not a security boundary. rbac() on each endpoint is still the only thing that
# decides anything; this only decides what is worth rendering.
@router.get("/permissions")
def my_permissions(current_user: dict = Depends(get_current_user)):
    """The caller's own resource→actions map, plus their canonical role.

    Answers for the PERSON since migration 403 — the caller's own overrides are
    passed through, so this agrees with what `rbac()` will actually do. Serving
    the role's template here instead would offer an Executive granted payroll a
    screen with no button on it, and hide nothing from an Executive whose
    payroll was taken away: the drift this endpoint exists to prevent, one layer
    down.
    """
    role = canonical_role(current_user.get("role"))
    if role is None:
        # Unknown role string: an empty map rather than a 500. The frontend
        # helpers fail closed on an empty map, which is the right outcome for a
        # row carrying a role nobody recognises.
        return api_response(True, {"role": None, "permissions": {}})
    overrides = current_user.get("permission_overrides") or {}
    return api_response(True, {
        "role": role,
        "permissions": get_accessible_resources(role, overrides),
        # The role's own template, so a screen can show what a person has that
        # their role does not give them (or has had taken away) without asking
        # a second endpoint. Distinct from `permissions`, which is what they may
        # actually do.
        "role_defaults": get_accessible_resources(role),
        "has_overrides": bool(overrides),
    })


# ─── Per-person access (migration 403) ───────────────────────────────────────
#
# The Team screen's grid, made real. Its header used to read "Toggle access per
# member per module. Changes are saved instantly. Overrides the role default for
# that individual" while the toggles went into localStorage, reaching no other
# user, device or server — and nothing in core/permissions.py could have
# honoured them. It was left read-only rather than deleted because the need was
# real; these three endpoints are the need, built.
#
# Guarded by team:read / team:write, the same tiers that govern every other
# member administration act in this router and the same tiers migration 403's
# RLS policies carry — the app-layer check is the primary control and RLS is
# defence in depth, so the two disagreeing would mean one of them is decorative.


@router.get("/permission-vocabulary")
def permission_vocabulary(current_user: dict = Depends(rbac("team", "read"))):
    """Every (resource, action) pair that exists, with two flags a grid needs.

    Served rather than spelled in the browser for the reason /role-matrix
    already exists: the last hardcoded copy of an engine vocabulary in this
    codebase drifted in BOTH directions at once — offering five captions the
    engine had never heard of and spelling five others differently — and nine
    of fifty mapped accounts were silently discarded as a result.

    `notice` is the one sentence the grid's drawer shows about what a block
    reaches and what it does not (POST-A-005). It is served for the same
    reason the pairs are: it is a claim about `pg_policies`, the guard that
    keeps it true is a Python test, and a copy typed into the browser would
    outlive the policies it describes.
    """
    from services.user_permission_service import DENIAL_REACH_NOTICE, vocabulary
    return api_response(True, {"permissions": vocabulary(), "notice": DENIAL_REACH_NOTICE})


@router.get("/users/{user_id}/permissions")
def member_permissions(user_id: str, current_user: dict = Depends(rbac("team", "read"))):
    """One member's grid: the role template, the stored overrides, the effective answer."""
    from core.supabase_client import get_service_supabase
    from services.user_permission_service import grid_for
    member = _get_member(user_id, current_user["firm_id"])
    return api_response(True, grid_for(get_service_supabase(), current_user["firm_id"], member))


class PermissionChangesBody(BaseModel):
    # {"payroll:write": true, "billing:read": false, "gst:approve": null}
    #
    # Optional[bool] rather than bool: **null means DELETE the row**, which is a
    # third state and not a spelling of false. Absence means "whatever the role
    # says"; false means "refused however senior". A screen that could only send
    # the second could never hand a permission back to the role, and would
    # freeze today's role map into the person's row.
    changes: dict[str, Optional[bool]]


@router.put("/users/{user_id}/permissions")
def set_member_permissions(user_id: str, body: PermissionChangesBody,
                           current_user: dict = Depends(rbac("team", "write"))):
    """Change one member's access. Partner-only, audited, validated before any write."""
    from core.supabase_client import get_service_supabase
    from services.user_permission_service import PermissionWriteRefused, set_permissions
    member = _get_member(user_id, current_user["firm_id"])
    db = get_service_supabase()
    try:
        grid = set_permissions(db, current_user["firm_id"], member,
                               dict(body.changes), current_user.get("id"))
    except PermissionWriteRefused as e:
        # 422 rather than 400: the request is well-formed and the firm is not
        # allowed to make this change, which is what the screen has to explain.
        raise HTTPException(422, str(e))
    # Audited like every other mutation in this router, and for a stronger
    # reason: who may do what is the record an ICAI peer review asks for.
    log_event(current_user["firm_id"], "user_permissions", user_id, "update",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"changes": {k: v for k, v in body.changes.items()}})
    return api_response(True, grid)


@router.get("/role-matrix")
def role_matrix(current_user: dict = Depends(rbac("team", "read"))):
    """What EVERY role can reach, for the Team screen's access matrix.

    /permissions above answers for the caller alone, which is what a screen
    needs to decide whether to render a control. This answers for all five
    roles, which is what the Team screen needs to show a Partner what each
    member's role actually grants.

    WHY IT EXISTS (a defect with no finding)
        `app/team/page.tsx` carried its own ROLE_DEFAULTS map — eleven modules
        by five roles, "mirrors permissions.ts logic" said the comment — AND a
        per-member override grid whose header read "Toggle access per member
        per module. Changes are saved instantly. Overrides the role default for
        that individual."

        Every clause of that was false. The overrides went into
        `localStorage["practicesync_permissions_<firm>"]`, so they reached no
        other user, no other device and no server; there is no per-member
        override concept in `core/permissions.py` at all, so nothing could have
        honoured them; and `rbac()` decides every request from the ROLE alone.
        A Partner who unticked Payroll for an Executive believed they had
        removed access. They had not, anywhere.

        A control that does nothing is the dead-control fault this codebase
        keeps removing. A control that does nothing while LOOKING like access
        control is worse, so the grid is read-only now and reads from here.

    NOT A SECURITY BOUNDARY, exactly as /permissions says of itself: `rbac()`
    on each endpoint is the only thing that decides anything. This decides what
    is worth rendering, and it exists so there is one copy of the matrix
    instead of a browser copy that drifts the moment PERMISSIONS changes.
    """
    from core.permissions import Role as _Role
    return api_response(True, {
        # Ordered least- to most-privileged, so a screen rendering columns in
        # this order does not have to know the hierarchy itself.
        "roles": [r.value for r in _Role],
        "matrix": {r.value: get_accessible_resources(r.value) for r in _Role},
    })


class MyProfileBody(BaseModel):
    full_name: str


# Self-service profile edit. Previously the Settings page did this itself, with
# `supabase.from("users").update({ full_name })` straight from the browser —
# which has silently failed for everyone since migration 153 revoked UPDATE on
# `users` from `authenticated`. The revoke was right; the missing half was an
# endpoint to do the write instead.
#
# identity:write (_ALL_STAFF) is the correct guard for the same reason
# login-event uses it: this is a caller acting on the caller. It is NOT
# team:write — that is Partner-only and governs editing OTHER people's accounts,
# which this endpoint deliberately cannot do.
@router.patch("/me")
def update_my_profile(body: MyProfileBody,
                      current_user: dict = Depends(rbac("identity", "write"))):
    """Update the CALLER's own display name. No user_id parameter exists, by
    design — the row is addressed from the verified token, so there is no id for
    a caller to substitute and no scope check that could be forgotten."""
    name = (body.full_name or "").strip()
    if not name:
        raise HTTPException(400, "full_name cannot be empty")
    if len(name) > 120:
        raise HTTPException(400, "full_name must be 120 characters or fewer")

    updated = user_repo.update(current_user["id"], {"full_name": name}, firm_id=current_user["firm_id"])
    # Audited like every other mutation in this router: a display name is how a
    # person is identified in approvals and audit trails, so a change to it is
    # worth a record.
    log_event(current_user.get("firm_id"), "user", str(current_user["id"]), "profile_update",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"full_name": name})
    return api_response(True, updated)


class LoginEventBody(BaseModel):
    event: str  # 'login' | 'logout'


# NOTE: was rbac("ai", "read") — wrong resource entirely (this records who
# signed in, not anything AI), and a read-level action guarding a WRITE:
# it persists a row via login_events_repo.record below.
@router.post("/login-event")
def record_login_event(body: LoginEventBody,
                       current_user: dict = Depends(rbac("identity", "write"))):
    """Recorded by the frontend on sign-in / sign-out for the current user."""
    if body.event not in ("login", "logout"):
        raise HTTPException(400, "event must be 'login' or 'logout'")
    ev = login_events_repo.record(current_user.get("firm_id"), current_user.get("id"),
                                  current_user.get("email"), body.event)
    return api_response(True, ev)

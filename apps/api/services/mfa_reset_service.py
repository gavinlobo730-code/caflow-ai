"""A lost authenticator is reset by a Partner who is not the person who asked (POST-A-006).

THE GAP
    MFA is a TOTP app, enrolled and removed by the person in the browser. There was no backup code and no way for anybody
    else to take a lost authenticator away, so a Partner or Manager who lost a phone was locked out until somebody with
    the sign-in service's own dashboard removed the factor by hand. That is also the reason MFA could not be widened to
    more roles or more tables: a rule that can lock people out for good has to have a way back first.

WHAT THIS IS
    A request type of the maker-checker engine (`services/approval_service`), not a second mechanism:

      * ANYONE who is signed in at the password level may ask for THEIR OWN authenticator to be reset, which is the
        locked-out person's only way to ask, and a Partner may ask for anyone's in the firm. Nobody else may ask for
        another person's, so an Executive cannot ask for a Partner's;
      * the request names a person of THIS firm and the server resolves who: the browser's name and e-mail are never
        stored, and the summary a Partner reads is written from the member's own row;
      * a DIFFERENT Partner decides it (approving is already Partner-only and behind the second factor). The one
        exception is the firm's only Partner resetting somebody who is not a Partner, because there is nobody else, and
        the audit entry says so. The only Partner's OWN authenticator cannot be reset here: nobody could approve it, and
        it stays a step for whoever administers the sign-in service, which the refusal says in words;
      * approving removes every factor the person holds and revokes their sessions, so the next sign-in is a password and
        then the existing prompt to set up a new authenticator (`mustEnrolMfa`);
      * a request older than seven days is refused on approval: whether a phone is still lost is a question for today;
      * WHO IS ASKED OF AT EACH END (an independent review of this change, 18-10-2026): asking for ANOTHER person's reset
        needs the asker's own second factor (a stolen Partner password must not be able to put a colleague's name in front
        of the deciding Partner), the decider must be a Partner at the second factor whatever the role is spelt, the person
        who asked must still be an active member (and still a Partner, for a request about somebody else) when it is
        decided, a suspended person is not reset, and when a reset is approved every other request still waiting for the
        same person is closed so a leftover cannot remove the NEW authenticator days later.

WHAT IT DELIBERATELY DOES NOT DO
    It does not send the person an e-mail (the firm's own mail is off unless somebody says on); the signal they get is the
    sign-out and the prompt. It adds no recovery codes: a code is a second secret to lose and to phish, and a reset a
    Partner decides leaves a record of who decided it. And it cannot be proven against the live sign-in service from the
    build: see `core/auth_admin`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from core import auth_admin
from core.permissions import canonical_role
from core.security_config import require_mfa
from repositories.approval_repository import approval_repo
from repositories.user_repository import user_repo
from services.audit_service import log_event

REQUEST_TYPE = "mfa_reset"

#: How long a request may wait before it is refused on approval.
VALID_FOR = timedelta(days=7)

#: The reason is what the deciding Partner reads, so it is required, and bounded so it stays a sentence.
REASON_MIN = 5
REASON_MAX = 300


def _is_partner(user: dict) -> bool:
    return canonical_role(user.get("role")) == "Partner"


def _name(member: dict) -> str:
    return (member.get("full_name") or member.get("email") or "this person").strip() or "this person"


def _member(firm_id: str, user_id) -> Optional[dict]:
    """The member of THIS firm with that id, or None. An id that names nobody (empty, or not text: a stored request is
    only as good as what wrote it) is never put to the database, whose uuid column would answer with an error."""
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    return user_repo.find_by_id(user_id, firm_id=firm_id)


def _other_partners(firm_id: str, asker_id: Optional[str], target_id: Optional[str] = None) -> list[dict]:
    """The firm's active Partners who could decide a request the asker made: signed up, not suspended, not the asker and
    not the person whose authenticator it is (nobody decides a reset of their own)."""
    return [
        m for m in user_repo.find_all(firm_id=firm_id)
        if canonical_role(m.get("role")) == "Partner" and m.get("is_active") is not False
        and m.get("auth_user_id") and m.get("id") not in (asker_id, target_id)
    ]


def _lone_partner_may_decide_own_request(firm_id: str, asker: dict, target: dict) -> bool:
    """The firm's only Partner resetting somebody who is not a Partner: nobody else can decide it, and the target is
    not the person asking or a person of the same standing."""
    return (
        _is_partner(asker) and target.get("id") != asker.get("id") and canonical_role(target.get("role")) != "Partner"
        and not _other_partners(firm_id, asker.get("id"), target.get("id"))
    )


def _waiting_for(firm_id: str, user_id: str) -> list[dict]:
    """The requests for this person that are still pending AND still decidable (a request more than `VALID_FOR` old is
    refused on approval, so it must not block a new one). Asked of the database by person, not read out of the firm's
    latest hundred requests, where an old one would be missed once the inbox is long."""
    now = datetime.now(timezone.utc)
    out = []
    for r in approval_repo.pending_with_payload(firm_id, REQUEST_TYPE, "user_id", user_id):
        made = _parse(r.get("created_at"))
        if made is None or now - made <= VALID_FOR:
            out.append(r)
    return out


def _reason(raw) -> str:
    text = " ".join(str(raw or "").split())
    if len(text) < REASON_MIN:
        raise HTTPException(422, "Say why the authenticator needs resetting (a few words), so the Partner who decides it knows.")
    if len(text) > REASON_MAX:
        raise HTTPException(422, f"Keep the reason under {REASON_MAX} characters.")
    return text


def prepare(firm_id: str, payload: dict, asker: dict) -> dict:
    """Validate a request when it is made and return the payload that is STORED (resolved by the server)."""
    reason = _reason(payload.get("reason"))
    wants_own = payload.get("self") is True
    target_id = asker.get("id") if wants_own else payload.get("user_id")
    if not isinstance(target_id, str) or not target_id.strip():
        raise HTTPException(422, "Say whose authenticator is to be reset.")
    target = _member(firm_id, target_id)
    if target is None:
        raise HTTPException(404, "That person is not a member of this firm.")
    own = target.get("id") == asker.get("id")
    if not own and not _is_partner(asker):
        raise HTTPException(403, "Only a Partner can ask for another person's authenticator to be reset. "
                                 "If it is your own that is lost, ask for your own.")
    if not own and require_mfa() and asker.get("aal") != "aal2":
        # The one place the create route is NOT left at the password level: a locked-out person asks for THEIR OWN reset
        # with a password, but naming somebody else to the deciding Partner is a Partner's act and needs their second
        # factor, or a stolen Partner password could put a colleague's name in front of the one person who can approve.
        raise HTTPException(403, "To ask for another person's authenticator to be reset, sign in with your own second "
                                 "factor first. If it is your own that is lost, ask for your own.")
    if not target.get("auth_user_id"):
        raise HTTPException(409, f"{_name(target)} has not signed in yet, so there is no authenticator to reset.")
    if target.get("is_active") is False:
        raise HTTPException(409, f"{_name(target)} is suspended, so there is nothing to reset. Reactivate them first.")
    if _waiting_for(firm_id, target["id"]):
        raise HTTPException(409, f"A reset for {_name(target)} is already waiting for a Partner to decide it.")
    if not _other_partners(firm_id, asker.get("id"), target.get("id")) \
            and not _lone_partner_may_decide_own_request(firm_id, asker, target):
        if own and _is_partner(asker):
            raise HTTPException(409, "You are the firm's only active Partner, so there is nobody to approve this. "
                                     "A lost authenticator for the only Partner is removed by whoever administers the "
                                     "firm's sign-in service, not from here.")
        raise HTTPException(409, "There is no other active Partner to decide this request. "
                                 "Add or reactivate a Partner first.")
    return {
        "user_id": target["id"], "target_name": _name(target), "target_email": target.get("email"),
        "reason": reason, "self_requested": own,
        # How the asker proved who they were, shown to the Partner who decides: a self-request made with a password
        # alone is the weakest thing this screen is ever asked to act on.
        "asker_aal": asker.get("aal") if asker.get("aal") in ("aal1", "aal2") else None,
    }


def summary(payload: dict) -> str:
    who = f"{payload.get('target_name')} ({payload.get('target_email')})" if payload.get("target_email") else payload.get("target_name")
    return f"Reset the authenticator app of {who}" + (", asked for by them" if payload.get("self_requested") else "")


def _parse(stamp) -> Optional[datetime]:
    if isinstance(stamp, datetime):
        value = stamp
    else:
        try:
            value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def check_decider(firm_id: str, request: dict, decider: dict) -> None:
    """Refuse, before anything is claimed, a decision that would defeat the point of asking a second person."""
    made = _parse(request.get("created_at"))
    if made is not None and datetime.now(timezone.utc) - made > VALID_FOR:
        raise HTTPException(409, "This request is more than seven days old. Reject it and ask again if the "
                                 "authenticator is still lost: whether it is, is a question for today.")
    if not _is_partner(decider):
        # `approval:approve` can be granted to a person one at a time, so the route alone does not make a decider a Partner.
        raise HTTPException(403, "Only a Partner can decide a reset of somebody's authenticator.")
    if require_mfa() and decider.get("aal") != "aal2":
        # The route's own second-factor guard compares the stored role string; this one does not, so a role spelt another
        # way (or a guard that was widened wrongly) cannot let a password alone remove somebody's authenticator.
        raise HTTPException(403, "Deciding a reset needs your own second factor. Sign in with it and try again.")
    payload = request.get("payload") or {}
    target = _member(firm_id, payload.get("user_id"))
    if target is None:
        return  # the handler refuses in words; nothing is claimed twice
    if target.get("id") == decider.get("id"):
        # Whoever asked: P1 asking for P2's reset must not let P2 decide it either.
        raise HTTPException(403, "You cannot approve the reset of your own authenticator. Another Partner has to.")
    asker = _member(firm_id, request.get("requested_by"))
    if asker is None or asker.get("is_active") is False:
        raise HTTPException(409, "The person who asked is no longer an active member of this firm, so this request "
                                 "cannot be trusted. Reject it and ask again.")
    if not payload.get("self_requested") and not _is_partner(asker):
        raise HTTPException(409, "The person who asked for this reset is no longer a Partner. Reject it and ask again.")
    if decider.get("id") == request.get("requested_by") and not _lone_partner_may_decide_own_request(firm_id, decider, target):
        raise HTTPException(403, "A different Partner has to approve this request, because you made it.")


def execute(firm_id: str, payload: dict) -> dict:
    """The approved act: remove every factor, then end the person's access tokens."""
    target = _member(firm_id, payload.get("user_id"))
    if target is None or not target.get("auth_user_id"):
        raise HTTPException(409, "That person is no longer a member of this firm with a sign-in, so nothing was reset. "
                                 "Reject this request.")
    if target.get("is_active") is False:
        raise HTTPException(409, f"{_name(target)} has been suspended since this was asked, so nothing was reset. "
                                 "Reject this request.")
    try:
        removed = auth_admin.remove_all_authenticators(target["auth_user_id"])
    except auth_admin.AuthAdminError as exc:
        # Some factors may already be gone: the trail says how many, because the request goes back to pending and the
        # next attempt will report only what was left.
        log_event(firm_id, "user", str(target["id"]), "mfa_reset_failed",
                  metadata={"factors_removed_before_the_failure": getattr(exc, "removed", 0)})
        raise HTTPException(503, "The sign-in service could not be reached, so nothing is certain to have changed. "
                                 "The request is still waiting: approve it again in a moment.") from exc
    # After the factors, so a failure above leaves the person signed in with what they had. Idempotent on a retry.
    stamped = user_repo.update(target["id"], {"sessions_revoked_at": datetime.now(timezone.utc).isoformat()}, firm_id=firm_id)
    if not stamped:
        raise HTTPException(409, "The authenticators were removed, but the person's record could not be marked, so their "
                                 "current sign-ins were not ended. Approve again, or reject if they have left the firm.")
    # The sign-in check reads the member through a short cache; without this the stamp is not seen for thirty seconds.
    from core.auth import _user_lookup_cache
    _user_lookup_cache.pop(target["auth_user_id"], None)
    return {"user_id": target["id"], "factors_removed": removed, "sessions_revoked": True}


def audit_extra(request: dict, result: dict, decider: dict) -> dict:
    payload = request.get("payload") or {}
    return {
        "target_user_id": payload.get("user_id"), "target_email": payload.get("target_email"),
        "factors_removed": result.get("factors_removed"), "asked_by_the_target": bool(payload.get("self_requested")),
        "decided_by_the_asker": decider.get("id") == request.get("requested_by"),
    }


def after_approval(firm_id: str, request: dict, result: dict, decider: dict) -> None:
    """The reset is also written against the PERSON, so their own history shows it (audit_log.actor_id takes the auth id)."""
    log_event(firm_id, "user", str(result.get("user_id")), "mfa_reset",
              actor_id=decider.get("auth_user_id"), actor_email=decider.get("email"),
              metadata=audit_extra(request, result, decider))
    _close_the_others(firm_id, request, result, decider)


def _close_the_others(firm_id: str, request: dict, result: dict, decider: dict) -> None:
    """Every OTHER request still waiting to reset this person is now answered by this one: left pending, one approved days
    later would remove the authenticator the person set up in the meantime and sign them out again."""
    for other in approval_repo.pending_with_payload(firm_id, REQUEST_TYPE, "user_id", result.get("user_id")):
        if other.get("id") == request.get("id"):
            continue
        approval_repo.decide_if_pending(firm_id, other["id"], {
            "status": "rejected", "decided_by": decider.get("id"), "decided_by_email": decider.get("email"),
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "reason": "Closed: another reset of this person's authenticator was approved first.",
        })

"""
Public engagement-letter signing (client-facing, NO login).

A prospect receives a tokenized link in their engagement-letter email and can
review and electronically accept (or decline) the letter without any account.
The unguessable sign_token IS the bearer credential; every endpoint is scoped
strictly to the single letter that token resolves to.

Because there is no user JWT, these endpoints use the SERVICE-ROLE DB client
(RLS is bypassed) — so every query/update is constrained to the token's row and
the response exposes only a client-safe projection of the letter (never firm
internals, ids, or the audit trail).

Electronic acceptance (typed name + explicit consent + timestamp + IP) is a
valid contract under the Information Technology Act, 2000, Section 10A.
Engagement letters require no Digital Signature Certificate. This is CLIENT
acceptance only — it is never a government-portal submission, so it is exempt
from the "DO NOT AUTO-SUBMIT to a government portal" rule.

Registered in main.py WITHOUT the staff _CLIENT_GUARD (it is intentionally
public, like the hosted invoice payment link).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.common import api_response
# Reuse the canonical helpers so the public path shares the same audit-event and
# forward-only lead-advance behaviour as the staff path.
from routers.engagement_letters import _log_engagement_event, _advance_lead

router = APIRouter(prefix="/api/public/engagement-letters", tags=["engagement_sign_public"])
_logger = logging.getLogger("caflow.engagement_sign_public")

# Statuses from which a recipient may still act on the letter.
_ACTIONABLE = {"Sent", "Viewed"}


class SignBody(BaseModel):
    signer_name: str
    consent: bool = False


class RejectBody(BaseModel):
    reason: Optional[str] = None


def _db():
    # Token is the credential; there is no user JWT, so use the service-role
    # client and constrain every access to the token's row.
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _public_view(eng: dict, firm_name: str) -> dict:
    """Client-safe projection — only the letter the recipient was sent. Excludes
    firm/lead/client ids, the sign token, IP, and the audit trail."""
    return {
        "engagement_number": eng.get("engagement_number"),
        "title": eng.get("title"),
        "content": eng.get("content"),
        "status": eng.get("status"),
        "recipient_name": eng.get("recipient_name"),
        "firm_name": firm_name,
        "signed_at": eng.get("signed_at"),
        "signed_by_name": eng.get("signed_by_name"),
        "rejected_at": eng.get("rejected_at"),
    }


def _load_by_token(db, token: str) -> Optional[dict]:
    # Cheap guard against trivially short/garbage tokens before hitting the DB.
    if not token or len(token) < 20:
        return None
    try:
        res = (
            db.table("engagements")
            .select("*")
            .eq("sign_token", token)
            .maybe_single()
            .execute()
        )
        return res.data
    except Exception:
        return None


def _firm_name(db, firm_id) -> str:
    if not firm_id:
        return "Your Chartered Accountant"
    try:
        r = db.table("firms").select("name").eq("id", firm_id).maybe_single().execute()
        return (r.data or {}).get("name") or "Your Chartered Accountant"
    except Exception:
        return "Your Chartered Accountant"


def _client_ip(request: Request) -> Optional[str]:
    # Render/Cloudflare sit in front of the API, so prefer the forwarded client IP.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _actor(eng: dict) -> dict:
    """Synthetic actor for the reused staff helpers — the signer has no user id."""
    return {"auth_user_id": None, "email": eng.get("recipient_email")}


@router.get("/{token}")
def view_letter(token: str, request: Request):
    """Public: fetch the letter for review. First open advances Sent → Viewed."""
    db = _db()
    eng = _load_by_token(db, token)
    if not eng:
        raise HTTPException(status_code=404,
                            detail="This engagement letter link is invalid or has expired.")

    if eng.get("status") == "Sent":
        now = datetime.now(timezone.utc).isoformat()
        try:
            db.table("engagements").update(
                {"status": "Viewed", "viewed_at": now, "updated_at": now}
            ).eq("id", eng["id"]).eq("sign_token", token).execute()
            eng["status"] = "Viewed"
            eng["viewed_at"] = now
            _log_engagement_event(db, eng["id"], eng["firm_id"], "viewed", None,
                                  {"channel": "public_link", "ip": _client_ip(request)})
        except Exception as e:
            _logger.warning("view_letter could not mark Viewed: %s", e)

    return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))


@router.post("/{token}/sign")
def sign_letter(token: str, body: SignBody, request: Request):
    """Public: record the recipient's electronic acceptance (typed name + consent)."""
    if not body.consent:
        return api_response(False, None, "Please tick the consent box to accept the engagement.")
    if not body.signer_name or not body.signer_name.strip():
        return api_response(False, None, "Please type your full name to sign.")

    db = _db()
    eng = _load_by_token(db, token)
    if not eng:
        raise HTTPException(status_code=404,
                            detail="This engagement letter link is invalid or has expired.")

    status = eng.get("status")
    if status == "Signed":
        # Idempotent — already accepted; return the confirmed state.
        return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))
    if status not in _ACTIONABLE:
        return api_response(False, None,
                            f"This letter can no longer be signed (current status: {status}).")

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "status": "Signed",
        "signed_at": now,
        "updated_at": now,
        "signed_by_name": body.signer_name.strip()[:200],
        "signed_ip": _client_ip(request),
        "signed_user_agent": (request.headers.get("user-agent") or "")[:500],
    }
    try:
        db.table("engagements").update(update).eq("id", eng["id"]).eq("sign_token", token).execute()
    except Exception as e:
        _logger.error("sign_letter update failed: %s", e)
        return api_response(False, None, "Could not record your signature. Please try again.")
    eng.update(update)

    _log_engagement_event(db, eng["id"], eng["firm_id"], "signed", None,
                          {"signed_by_name": update["signed_by_name"],
                           "ip": update["signed_ip"], "channel": "public_link"})
    # Forward-only lead advance (never raises). The signer is the linked lead.
    _advance_lead(eng.get("lead_id"), eng["firm_id"], "Engagement Signed", _actor(eng))
    try:
        from services.audit_service import log_event
        log_event(eng["firm_id"], "engagement", eng["id"], "status_change",
                  actor_id=None, actor_email=eng.get("recipient_email"),
                  old_data={"status": status},
                  new_data={"status": "Signed", "signed_by_name": update["signed_by_name"]},
                  metadata={"channel": "public_link", "ip": update["signed_ip"]})
    except Exception:
        pass

    return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))


@router.post("/{token}/reject")
def reject_letter(token: str, body: RejectBody, request: Request):
    """Public: let the recipient decline the engagement."""
    db = _db()
    eng = _load_by_token(db, token)
    if not eng:
        raise HTTPException(status_code=404,
                            detail="This engagement letter link is invalid or has expired.")

    status = eng.get("status")
    if status == "Rejected":
        return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))
    if status not in _ACTIONABLE:
        return api_response(False, None,
                            f"This letter can no longer be declined (current status: {status}).")

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": "Rejected", "rejected_at": now, "updated_at": now}
    if body.reason:
        update["rejection_notes"] = body.reason.strip()[:1000]
    try:
        db.table("engagements").update(update).eq("id", eng["id"]).eq("sign_token", token).execute()
    except Exception as e:
        _logger.error("reject_letter update failed: %s", e)
        return api_response(False, None, "Could not record your response. Please try again.")
    eng.update(update)

    _log_engagement_event(db, eng["id"], eng["firm_id"], "rejected", None,
                          {"reason": update.get("rejection_notes"),
                           "channel": "public_link", "ip": _client_ip(request)})
    return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))

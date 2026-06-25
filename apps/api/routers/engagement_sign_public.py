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
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.common import api_response
# Reuse the canonical helpers so the public path shares the same audit-event and
# forward-only lead-advance behaviour as the staff path.
from routers.engagement_letters import _log_engagement_event, _advance_lead, _revert_lead

router = APIRouter(prefix="/api/public/engagement-letters", tags=["engagement_sign_public"])
_logger = logging.getLogger("caflow.engagement_sign_public")

# Statuses from which a recipient may still act on the letter.
_ACTIONABLE = {"Sent", "Viewed"}

# Business timezone for date-only expiry comparisons. expiry_date is a DATE, and
# the financial year / due dates are all reckoned in IST — comparing against UTC
# would expire a letter up to 5.5h early (just after IST midnight). A letter
# "expiring 30 Jun" therefore stays signable through all of 30 Jun IST.
_IST = timezone(timedelta(hours=5, minutes=30))


class _LookupError(Exception):
    """A real backend failure while resolving a sign token (NOT a missing token).

    Kept distinct from "token not found" so an infrastructure problem — e.g. the
    service_role missing a table grant, or a transport/DB error — is surfaced
    honestly as a 503 with the true cause logged, instead of being masked as a
    404 "invalid/expired" link. That masking is precisely what hid the original
    missing-grant root cause of this bug.
    """


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
        "expired": _is_expired(eng),
    }


def _load_by_token(db, token: str) -> Optional[dict]:
    """Resolve a live (non-deleted) engagement by its public sign token.

    Returns None when the token simply matches no live letter (caller → 404).
    Raises _LookupError on an ACTUAL backend failure (permission/transport/DB)
    so the caller can return a distinct 503 instead of a misleading
    "invalid or has expired" — the previous bare `except: return None` is what
    disguised the missing service_role grant as an invalid link.
    """
    # Cheap guard against trivially short/garbage tokens before hitting the DB.
    if not token or len(token) < 20:
        return None
    try:
        res = (
            db.table("engagements")
            .select("*")
            .eq("sign_token", token)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _logger.error("sign-token lookup failed (token_len=%s): %s", len(token or ""), exc)
        raise _LookupError(str(exc)) from exc
    rows = res.data or []
    eng = rows[0] if rows else None
    # A soft-deleted letter's link must not resolve.
    if eng and eng.get("is_deleted"):
        return None
    return eng


def _get_letter_or_http(db, token: str) -> dict:
    """Load the letter for a token or raise the correct HTTPException:
      * backend failure (_LookupError) → 503 (true cause already logged)
      * genuinely no match              → 404 (invalid/expired link)
    """
    try:
        eng = _load_by_token(db, token)
    except _LookupError as exc:
        raise HTTPException(
            status_code=503,
            detail="The signing service is temporarily unavailable. Please try again in a moment.",
        ) from exc
    if not eng:
        raise HTTPException(
            status_code=404,
            detail="This engagement letter link is invalid or has expired.",
        )
    return eng


def _is_expired(eng: dict) -> bool:
    """True when the letter is past its expiry_date (date-only, reckoned in IST).
    Letters with no expiry_date never expire."""
    exp = eng.get("expiry_date")
    if not exp:
        return False
    try:
        exp_date = date.fromisoformat(str(exp)[:10])
    except Exception:
        return False
    return datetime.now(_IST).date() > exp_date


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
    eng = _get_letter_or_http(db, token)

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
    eng = _get_letter_or_http(db, token)

    status = eng.get("status")
    if status == "Signed":
        # Idempotent — already accepted; return the confirmed state.
        return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))
    if status not in _ACTIONABLE:
        return api_response(False, None,
                            f"This letter can no longer be signed (current status: {status}).")
    # An expired letter must not be signable, even though it is still "Sent".
    if _is_expired(eng):
        return api_response(False, None,
                            "This engagement letter has expired. Please contact the firm to request a new copy.")

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
    eng = _get_letter_or_http(db, token)

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
    # A declined letter must not orphan the lead — revert it to an active stage.
    _revert_lead(eng.get("lead_id"), eng["firm_id"], _actor(eng))
    return api_response(True, _public_view(eng, _firm_name(db, eng.get("firm_id"))))

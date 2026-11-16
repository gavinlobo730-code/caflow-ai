"""A staff invitation: its token, the mail that carries it, and the sign-in it opens (POST-A-445).

WHAT WAS WRONG. Invite Member created the member's row with a single-use token and an expiry and handed the token
BACK to the Partner's browser, which then asked Supabase to mail the person an ordinary sign-in link that came back
to `/join?token=...`. So the mail said neither which practice had invited them nor who had, the link lasted only as
long as Supabase keeps a one-time code (far shorter than the seven days the invitation was good for), the Partner's
browser held the invitee's secret, and nothing could send it again: a lost or expired invitation left a member who
could not get in and a Partner who could not tell why (the owner, inviting himself on the live site, 15-11-2026).

WHAT IT DOES NOW. The server issues the token, stores only its hash (`domain/firm/invite_token`), and sends the mail
itself, naming the practice and the Partner, with a link to `/join?token=...` that works for as long as the
invitation does. The token itself exists only in that mail; the repository returns no row with even the hash but
through `find_by_invite_token`. A Partner can send it again: a fresh token and expiry replace the old ones, so the
earlier link stops working, unless the new mail did not go, in which case the old ones are put back. The join page
turns the token into a sign-in through `POST /api/identity/accept-invite/session`, which asks Supabase for a sign-in
for the invitation's own address only after the invitation is found live (`member_state` says `invited`, the one
rule the Team screen also reads) and was mailed by the server, and never for an address that already has a sign-in:
that person signs in as they always do and opens the link, and accept-invite links that session.

What the screen is told about the mail is what the mail service answered: sent, or not sent with one sentence.
The cause of a failure is in the server log (`services/email_service`), never on the screen.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from urllib.parse import quote

from core import db_provider
from core.ist_clock import IST
from core.urls import frontend_base
from domain.firm.invite_token import stored_form
from services import email_service, practice_mail_service, sign_in_link

_logger = logging.getLogger("caflow.staff_invite")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

#: How long an invitation can be accepted. The mail states the instant it ends.
INVITE_TTL = timedelta(days=7)

#: Why the Team screen says the email did not go, as the reason inside its own sentence ("The invite for X was
#: created, but the email to Y could not be sent. <this>"). The member and the invitation exist either way.
MAIL_NOT_SENT = ("The mail service did not accept it. Use Resend invite on their row to try again; if it fails "
                 "again, this deployment's mail is not reaching the mail service.")

#: What the join page is told when Supabase could not open a sign-in for a live invitation.
SIGN_IN_REFUSAL = ("Could not sign you in from this invitation just now. Please try the link again in a moment, "
                   "or ask the practice to send the invitation again.")

#: What the join page is told when the invitation's address already has a PracticeSync sign-in. The link does not
#: sign anybody in as an existing account; that person signs in the usual way and then opens it.
EXISTING_ACCOUNT = ("This email address already has a PracticeSync sign-in. Sign in with it first (if you never set a "
                    "password, use Forgot password on the sign-in page), then open this invitation's link again to "
                    "join.")


def _new_token() -> str:
    """A 256-bit URL-safe secret. Its own function so a test can know the token a mail would carry."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Invitation:
    """A fresh invitation: the token for the mail's link, and the columns that keep it (its hash and its expiry)."""
    token: str
    columns: dict


def fresh_invitation(now: datetime) -> Invitation:
    """A new single-use token and the instant it stops working. Writing the columns over a member's row replaces any
    earlier invitation, so the earlier link no longer finds a row. Only the token's hash is kept."""
    token = _new_token()
    return Invitation(token, {"invite_token": stored_form(token),
                              "invite_expires_at": (now + INVITE_TTL).isoformat()})


def join_url(token: str) -> str:
    """Where the invitation's link points: the join page, with the token and nothing else."""
    return f"{frontend_base()}/join?token={quote(token, safe='')}"


def valid_until_words(expires_at: str) -> str:
    """The expiry as a person reads it, in India's time: `23 November 2026, 6:18 am IST`."""
    moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).astimezone(IST)
    hour = moment.hour % 12 or 12
    return f"{moment.day} {moment:%B} {moment.year}, {hour}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'} IST"


@dataclass(frozen=True)
class MailResult:
    """What became of the invitation's email: `sent` is the mail service's answer, `problem` the screen's sentence."""
    sent: bool
    problem: Optional[str] = None
    #: On a resend whose mail did not go: whether the earlier invitation was put back, so its link still works.
    kept_previous: Optional[bool] = None

    def as_dict(self) -> dict:
        out = {"sent": self.sent, "problem": self.problem}
        if self.kept_previous is not None:
            out["kept_previous"] = self.kept_previous
        return out


def send(member: Mapping[str, Any], invitation: Invitation, inviter: Mapping[str, Any]) -> MailResult:
    """Mail `invitation` to `member`, naming the practice and `inviter`, the Partner who pressed the button. Never
    raises: the member and the invitation are saved whether or not the mail goes."""
    practice_name, _ = practice_mail_service.practice_sender(str(member.get("firm_id") or ""))
    try:
        ok = email_service.send_firm_invite(
            str(member.get("email") or ""),
            practice_name=practice_name,
            inviter_name=(str(inviter.get("full_name") or "").strip() or None),
            role=str(member.get("role") or "a member of staff"),
            invite_link=join_url(invitation.token),
            valid_until=valid_until_words(invitation.columns["invite_expires_at"]),
            reply_to=inviter.get("email"),
        )
    except Exception:                                   # noqa: BLE001 — logged here, and the screen is told it did not go
        _logger.exception("caflow.staff_invite: the invitation email for member %s could not be built or sent",
                          member.get("id"))
        ok = False
    return MailResult(True) if ok else MailResult(False, MAIL_NOT_SENT)


def sign_in_for(member: Mapping[str, Any], token: str) -> dict:
    """A sign-in for the invitation's own address, for a member row the caller has already found live. The answer
    carries the address so the join page can tell a person signed in as somebody else which address this is for."""
    email = str(member.get("email") or "").strip()
    if _USE_MOCK:
        # No Supabase Auth to ask in mock mode; a recognisable stand-in, as the employee portal's mint gives.
        digest = hashlib.sha256(token.encode()).hexdigest()[:16]
        return {"token_hash": f"mock-staff-invite-{digest}", "verification_type": "magiclink", "email": email}
    minted = sign_in_link.mint(db_provider.service_db().auth.admin, email, refusal=SIGN_IN_REFUSAL,
                               existing_account_refusal=EXISTING_ACCOUNT)
    return {**minted, "email": email}

"""A sign-in for an invited address, minted by the server once it has checked the invitation (POST-A-445).

Two invitations open a session from their own link, and this is the one place that asks Supabase for it:

  * an employee's portal invitation (`services/employee_portal_service.mint_activation_session`), and
  * a staff invitation (`routers/identity.invite_session`).

Each caller FIRST proves the invitation is live (its single-use token found, pending, not past its expiry, not
withdrawn) and only then asks for a sign-in for the invitation's OWN address, never one a request names. The
answer is the raw ingredients the browser redeems with `supabase.auth.verifyOtp({token_hash, type})`, the same
operation Supabase's client performs when a real magic-link URL is opened. So the link the invitee holds lasts as
long as the invitation does (seven days for staff, fourteen for an employee), not as long as Supabase keeps an
emailed one-time code.

`type="invite"` is tried first because it creates the Supabase sign-in on demand, which is the common case of
somebody who has never signed in. What happens when the address ALREADY has a sign-in is the caller's choice, and the
two callers choose differently on purpose:

  * the employee portal retries as `type="magiclink"` (an employee re-invited after a revoke keeps the Supabase user
    `revoke_employee_portal` left behind). Its token is kept hashed and returned to nobody, so only the mailbox that
    received it can present it. THAT SENTENCE WAS FALSE UNTIL 22-11-2026 (POST-A-552): the invite's route handed the
    token and the link back to the member of staff who sent it, and the dialog showed it for copying, so whoever could
    invite an employee could be signed in as any existing account by typing its address. The route returns neither
    now, and the service opens a sign-in only for an invitation issued since (`employee_portal_service.opens_a_sign_in`);
  * a staff invitation passes `existing_account_refusal` and is REFUSED in those words (409): the person signs in the
    way they always do and opens the link again, and accept-invite links that session. A link that could sign its
    holder in as an address with an existing account would make whoever held the link that person, in whatever
    practice or portal the account already belongs to (the independent review of 16-11-2026 found exactly that, with
    the token leaking from the team list). Nothing here sends a mail: `generate_link` only mints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException


def _already_registered(exc: Exception) -> bool:
    """Whether Supabase refused because the address already has a sign-in. Read off the error's code where the SDK
    gives one and its words otherwise; anything else is a failure to mint, not an answer about the address."""
    code = str(getattr(exc, "code", "") or "").lower()
    if code in ("email_exists", "user_already_exists"):
        return True
    words = str(exc).lower()
    return "already been registered" in words or "already registered" in words or "email_exists" in words


def mint(admin, email: str, *, refusal: str, existing_account_refusal: Optional[str] = None) -> dict:
    """`{"token_hash", "verification_type"}` for `email`, or a 503 in `refusal`'s words when Supabase could not
    mint. With `existing_account_refusal`, an address that already has a sign-in is refused with a 409 in those words
    and never given a magic link; without it, it is given one. `admin` is the service client's `auth.admin`."""
    try:
        resp = admin.generate_link({"type": "invite", "email": email})
    except Exception as exc:                            # noqa: BLE001 — read below and answered in words
        if existing_account_refusal is not None:
            if _already_registered(exc):
                raise HTTPException(status_code=409, detail=existing_account_refusal) from exc
            raise HTTPException(status_code=503, detail=refusal) from exc
        try:
            resp = admin.generate_link({"type": "magiclink", "email": email})
        except Exception as exc2:                       # noqa: BLE001 — said to the caller, not swallowed
            raise HTTPException(status_code=503, detail=refusal) from exc2
    props = resp.properties
    return {"token_hash": props.hashed_token, "verification_type": props.verification_type}

"""A sign-up link: asked for on the sign-up form, mailed by the server, and turned into a sign-in at a press (POST-A-485, 497).

WHAT WAS WRONG. A sign-up link was the sign-in library's own emailed one-time link. The first opener won, so a mail scanner that opens links
before the person does, a second click, or the link opened on a phone after the laptop left the person on a page that said it had
expired (POST-A-479 only softened the words). And what the link MEANT ("a new practice, not the one this address already belongs to")
lived in a note in the browser that sent the form, so the link opened in another browser entered an existing practice silently
(POST-A-497).

WHAT IT DOES NOW, the way a staff invitation does (`services/staff_invite_service`):

  * the form asks the SERVER (`request_link`), which keeps one row per address (the hash of the secret, the firm name and the person's name
    typed on the form, the expiry) and mails the link itself, to the address typed. The page the link opens is ours, so the secret is
    read by a page that signs nobody in until a button is pressed: a scanner that opens the page spends nothing;
  * `look` answers what the link is for without signing anybody in, so the page can say "start <firm> for <address>" and a person who is
    signed in as somebody else can be told so first;
  * `open_sign_in` mints a sign-in for the link's OWN address (never one a request names) when the button is pressed. It consumes
    nothing, so a second click, a reload or the link opened on another device all work, until the link expires or the practice has been
    created (`forget`, called by the create-firm route);
  * the firm name and the person's name come back with the sign-in, so the page writes them where the wizard reads them in whichever
    browser it is open in: the intent travels with the link and not in the browser that sent the form (POST-A-497).

THE ADDRESS ALREADY HAS A SIGN-IN. The sign-up link signs in an existing account as the library's emailed link did, because it goes only
to the mailbox of the address it opens (holding the mail IS that proof, exactly as before); the staff invitation refuses an existing
account because its holder could be somebody the Partner forwarded it to. The wizard then says the address already has a practice
(POST-A-480) and does not start another: one sign-in belongs to one practice.

WHAT IS NOT KNOWN TO A STRANGER. Asking for a link answers the same whether or not the address has an account, and nothing about an
existing account is read: the form is public.

WHAT IT CANNOT DO. The per-address cooldown and hourly cap are the row's own counters (`domain/firm/signup_link`), so they survive a
restart; the per-network limit on the route is in this process (`middleware/public_rate_limit`) and does not stop a flood from many
addresses (docs/operations/edge-protection.md, not applied). A stranger can still cause a handful of mails an hour to an address they
type; each says it is safe to ignore.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import HTTPException

from core import db_provider
from core.urls import frontend_base
from domain.firm import signup_link as rules
from domain.firm.invite_token import stored_form
from repositories.signup_link_repository import signup_link_repo
from services import email_service, sign_in_link
from services.staff_invite_service import valid_until_words

_logger = logging.getLogger("caflow.signup_link")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

#: Why the sign-up page says the mail did not go. The link was not kept either: asking again is the way.
MAIL_NOT_SENT = ("The email could not be sent just now, so no link was created. Please try again in a moment; if it keeps "
                 "failing, this deployment's mail is not reaching the mail service.")

#: What the page is told when Supabase could not open a sign-in for a live link.
SIGN_IN_REFUSAL = ("Could not sign you in from this link just now. Please press the button again in a moment, or ask for a "
                   "new link.")

#: The one answer for every link that cannot be used (no such link, expired, replaced by a newer one, or the practice has been
#: created): telling them apart would only let a stranger probe which links exist.
NOT_ACTIVE = ("This sign-up link is no longer active. It may have expired, been replaced by a newer one, or already been used to "
              "create the practice.")


#: How many times a request reads the address's row again after losing the race to write it (it is refused after the last).
CLAIM_ATTEMPTS = 3


def _new_token() -> str:
    """A 256-bit URL-safe secret. Its own function so a test can know the token a mail would carry."""
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def continue_url(token: str) -> str:
    """Where the link in the mail points: our own page, with the secret and nothing else, in the FRAGMENT of the address.

    A browser never sends a fragment to a server, so the static host's request log, a mail scanner's log and a `Referer` header cannot hold
    it. That matters more here than for the sign-in library's own link, which was single use: this one keeps working until it expires or the
    practice is created, and it can sign in an address that already has an account. The trailing slash is the static export's own address
    for the page, so the host does not redirect (and a redirect would not lose the fragment, but there is nothing to gain by one)."""
    return f"{frontend_base()}/signup/continue/#token={quote(token, safe='')}"


class LinkRefused(HTTPException):
    """A 429 for this ADDRESS (not this network) that says how long to wait, in the sentence the page shows."""

    def __init__(self, sentence: str, wait_seconds: int) -> None:
        super().__init__(status_code=429, detail=sentence, headers={"Retry-After": str(wait_seconds)})
        self.wait_seconds = wait_seconds


@dataclass(frozen=True)
class Requested:
    """What asking for a link came to: always sent (a failure to send raises). The page's wait is the server's own cooldown."""
    valid_until: str
    wait_seconds: int = rules.COOLDOWN_SECONDS


def request_link(email: str, firm_name: str, full_name: str, *, now: Optional[datetime] = None) -> Requested:
    """Keep a link for `email` and mail it. Raises ValueError (a sentence for the form) when a name is unusable, `LinkRefused` when the
    address was mailed too recently or too often, and a 503 in `MAIL_NOT_SENT`'s words when the mail did not go, in which case the
    earlier link, if there was one, is put back and keeps working."""
    now = now or _now()
    address = rules.normalise_email(email)
    firm = rules.clean_name(firm_name, "your firm's name")
    person = rules.clean_name(full_name, "your name")

    sweep_expired(now)                                  # housekeeping never stops a person asking

    # READ, JUDGE, WRITE IF NOBODY WROTE IN BETWEEN. Two requests that overlap read the same row and would both be judged against it; the
    # write is a compare-and-set (`claim`), so only one wins, and the other reads again, now sees a link sent a moment ago and is refused.
    expires = rules.expires_at(now)
    for _ in range(CLAIM_ATTEMPTS):
        previous = signup_link_repo.find_by_email(address)
        verdict = rules.allowance(previous, now)
        if not verdict.ok:
            raise LinkRefused(rules.refusal_sentence(verdict), verdict.wait_seconds)
        token = _new_token()
        saved = signup_link_repo.claim(address, previous, {
            "email": address, "firm_name": firm, "full_name": person, "token_hash": stored_form(token),
            "expires_at": expires, "sent_at": now, "send_count": verdict.send_count,
            "window_started_at": verdict.window_started_at, "created_at": now,
        })
        if saved is not None:
            break
    else:
        # The row changed under every read: somebody is asking for this address at this very moment, and their mail is the one that goes.
        just_sent = rules.Allowance(False, rules.COOLDOWN_SECONDS, "cooldown")
        raise LinkRefused(rules.refusal_sentence(just_sent), just_sent.wait_seconds)
    valid_until = valid_until_words(str(saved.get("expires_at") or expires.isoformat()))
    try:
        sent = email_service.send_signup_link(address, firm_name=firm, link=continue_url(token), valid_until=valid_until)
    except Exception:                                   # noqa: BLE001 — logged here, and the page is told it did not go
        _logger.exception("caflow.signup_link: the sign-up mail could not be built or sent")
        sent = False
    if not sent:
        try:
            signup_link_repo.put_back(address, previous, replacing=stored_form(token))
        except Exception:                               # noqa: BLE001 — logged; the 503 below is the answer that matters
            _logger.exception("caflow.signup_link: the link of a mail that did not go could not be put back")
        raise HTTPException(status_code=503, detail=MAIL_NOT_SENT)
    return Requested(valid_until)


def sweep_expired(now: Optional[datetime] = None) -> None:
    """Remove the links that have expired. A row holds an address and two names a stranger typed, so one must not outlive its use because
    nobody asked again: this runs when a link is asked for and at the close of the daily sweep (`jobs/scheduler._close_sweep`). An expired
    row answers nothing the unknown ones do not (the page says the same sentence for both), and its counters are an hour's, so there is no
    reason to keep it. Never raises: housekeeping is not a reason to refuse a request or to end a sweep."""
    try:
        signup_link_repo.delete_expired_before(now or _now())
    except Exception:                                   # noqa: BLE001 — logged; the caller goes on
        _logger.warning("caflow.signup_link: expired links could not be swept", exc_info=True)


def _live(token: Any) -> Optional[dict]:
    """The row `token` names while the link can be used, or None. The secret is looked up by its hash, so a stored hash read from
    anywhere names nothing when presented as the secret (it would be hashed a second time)."""
    if not isinstance(token, str) or not token:
        return None
    row = signup_link_repo.find_by_token_hash(stored_form(token))
    return row if rules.is_live(row, _now()) else None


def look(token: Any) -> dict:
    """What a live link is for, signing nobody in: the address, the firm name and the person's name it was asked for with, and when it
    ends. 404 in `NOT_ACTIVE`'s words for every link that cannot be used."""
    row = _live(token)
    if not row:
        raise HTTPException(status_code=404, detail=NOT_ACTIVE)
    return {"email": row["email"], "firm_name": row["firm_name"], "full_name": row["full_name"],
            "expires_at": row["expires_at"], "valid_until": valid_until_words(str(row["expires_at"]))}


def open_sign_in(token: Any) -> dict:
    """A sign-in for the link's own address, opened at the press, plus the names the link was asked for with. Nothing is used up: a
    second press signs in again, until the link expires or the practice has been created. 404 for a link that cannot be used, and a
    503 in `SIGN_IN_REFUSAL`'s words when the sign-in service could not mint one."""
    row = _live(token)
    if not row:
        raise HTTPException(status_code=404, detail=NOT_ACTIVE)
    email = str(row["email"]).strip()
    names = {"email": email, "firm_name": row["firm_name"], "full_name": row["full_name"]}
    if _USE_MOCK:
        # No sign-in service to ask in mock mode; a recognisable stand-in, as the staff invitation's mint gives.
        digest = hashlib.sha256(str(token).encode()).hexdigest()[:16]
        return {"token_hash": f"mock-signup-link-{digest}", "verification_type": "magiclink", **names}
    minted = sign_in_link.mint(db_provider.service_db().auth.admin, email, refusal=SIGN_IN_REFUSAL)
    return {**minted, **names}


def forget(email: Optional[str]) -> None:
    """The practice has been created: its address's link has done its job and is removed, so the mail can no longer sign anybody in.
    Never raises: the firm exists whether or not this housekeeping worked, and the link lapses by itself."""
    address = rules.normalise_email(email)
    if not address:
        return
    try:
        signup_link_repo.delete_by_email(address)
    except Exception:                                   # noqa: BLE001 — logged; the link expires on its own
        _logger.warning("caflow.signup_link: the link of a created practice could not be removed", exc_info=True)

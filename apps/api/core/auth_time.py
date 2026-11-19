"""When a session's person last PROVED who they are, read from the token (POST-A-482, POST-A-484).

Two facts about a Supabase access token are easy to mistake for one another.

  `iat`        when THIS TOKEN was issued. A refresh token exchanged for a new access token (the browser does it
               hourly, and again whenever an API call answers 401) is issued afresh, so `iat` is newer every time.
  `amr`        the authentication methods behind the session, each with the moment it was used: `[{"method":
               "password", "timestamp": 1700000000}, {"method": "totp", "timestamp": 1700000040}]`. The list is
               carried unchanged from one token of the session to the next, so its OLDEST stamp is when the session
               began (the person's sign-in), however many times the token was renewed, and its newest TOTP stamp is when
               an authenticator code was last entered.

Revoking a person's sessions by comparing `iat` alone therefore revokes nothing that is still in use: the signed-in
browser renews its token, the new `iat` is after the revocation, and the person is back in (seen by reading the code on
19-11-2026: a Partner's "force sign-out" and a platform suspension both stamp `users.sessions_revoked_at`, and both
were undone by the next token renewal). A revocation has to ask the second fact as well.

WHY THE OLDEST STAMP AND NOT THE NEWEST. A person whose sessions were revoked and who still holds the old session can
enter an authenticator code against it (it needs the session and the authenticator, not the password); that adds a stamp
AFTER the revocation, and judging by the newest would read the old session as a fresh sign-in. A genuinely new sign-in has
every stamp after the revocation, so the oldest is the right one to ask (found by the independent review of this change).

A token that carries no `amr` (an older one, a test double) is judged by `iat` alone, which is what it always was.

Dependency-free so a test can load it without the application.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

TOTP_METHOD = "totp"

#: How recent an authenticator code must be for a destructive platform action (POST-A-484).
FRESH_CODE_WINDOW_SECONDS = 300
#: A stamp this far in the future is clock skew, not a code entered tomorrow.
_FUTURE_TOLERANCE_SECONDS = 60

#: The sentence a refused destructive platform action carries. The browser recognises it to ask for a code
#: (`apps/web/lib/auth/freshCode.ts` holds the same words; `tests/test_the_fresh_code_sentence_is_one_sentence_in_two_languages.py`
#: pins the pair).
FRESH_CODE_SENTENCE = (
    "Enter a fresh authenticator code to continue: this action needs a code entered within the last 5 minutes."
)


def _stamps(payload: Mapping[str, Any], method: Optional[str] = None) -> list[float]:
    amr = payload.get("amr")
    if not isinstance(amr, list):
        return []
    out: list[float] = []
    for entry in amr:
        if not isinstance(entry, Mapping):
            continue
        if method is not None and entry.get("method") != method:
            continue
        stamp = entry.get("timestamp")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            continue
        out.append(float(stamp))
    return out


def session_began_epoch(payload: Mapping[str, Any]) -> Optional[float]:
    """The OLDEST moment any method in the token's `amr` was used, which is when this session began, or None when the token
    carries none."""
    stamps = _stamps(payload)
    return min(stamps) if stamps else None


def last_authenticator_code_epoch(payload: Mapping[str, Any]) -> Optional[float]:
    """The newest moment an authenticator code was entered in this session, or None."""
    stamps = _stamps(payload, TOTP_METHOD)
    return max(stamps) if stamps else None


def issued_before_revocation(payload: Mapping[str, Any], revoked_epoch: float) -> bool:
    """True when the token must be refused because the person's sessions were revoked at `revoked_epoch`:
    the token was issued before it, OR the session it belongs to began before it (a renewed token is issued after the
    revocation but carries the stamps of the session it renews, and a code entered later does not make it a new one)."""
    if float(payload["iat"]) < revoked_epoch:
        return True
    began = session_began_epoch(payload)
    return began is not None and began < revoked_epoch


def authenticator_code_is_fresh(code_epoch: Optional[float], now_epoch: float) -> bool:
    """Whether an authenticator code entered at `code_epoch` is recent enough (within the window, never far ahead)."""
    if code_epoch is None:
        return False
    age = now_epoch - float(code_epoch)
    return -_FUTURE_TOLERANCE_SECONDS <= age <= FRESH_CODE_WINDOW_SECONDS

"""Who the request in flight is, as the authentication dependency established it, for the ledger door to hand the database (POST-A-317).

WHY THIS EXISTS
    The ledger functions are called with the API's privileged client, which has no `auth.uid()`, and the audit triggers record a write
    only when there is one. Most of the helpers that post a document's entry do not know who is signed in (they take no `created_by`),
    so the person has to come from the request, not from the helper's arguments. The authentication dependency
    (`core.auth.get_current_user`) has verified the token and resolved the person to a member of a firm; it records their AUTH id
    here, and `services/ledger_door` reads it back. The token is never decoded a second time: `tests/test_a_token_must_be_issued_for_
    this_product.py` holds that there is exactly one decode, and an unverified read of a claim would have been a second door.

THE HOLDER IS MUTABLE ON PURPOSE (the reason `core/request_context` gives)
    The middleware that begins the request runs before authentication, and a sync dependency runs on a worker thread whose contextvar
    context is a COPY, so a plain variable set there would never be seen again. The ContextVar holds a small mutable object and the
    copy shares it. A job has no request and so no holder: `bind` does nothing and `current_auth_user_id` is None, which is what a job's
    audit has always been.

WHAT IS HELD, AND WHAT IS NOT
    One AUTH id (a uuid in production), only for the length of the request and never logged: `core/request_context` is where a log line
    gets its context and it deliberately carries no person. Nothing here is a credential; the database checks the person is a member of
    the entry's own firm before it believes the label.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional


class _Holder:
    __slots__ = ("auth_user_id",)

    def __init__(self) -> None:
        self.auth_user_id: Optional[str] = None


_current: ContextVar[Optional[_Holder]] = ContextVar("caflow_request_actor", default=None)


def begin() -> Token:
    """Called by the request middleware before anything else runs."""
    return _current.set(_Holder())


def end(token: Token) -> None:
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):
        _current.set(None)


def bind(auth_user_id: Optional[str]) -> None:
    """Record the person the authentication dependency verified. A blank or non-text value, or no request in flight, records nothing."""
    holder = _current.get()
    if holder is not None and isinstance(auth_user_id, str) and auth_user_id.strip():
        holder.auth_user_id = auth_user_id.strip()


def current_auth_user_id() -> Optional[str]:
    holder = _current.get()
    return holder.auth_user_id if holder is not None else None

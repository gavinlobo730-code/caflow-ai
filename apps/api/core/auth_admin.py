"""The one door to the sign-in service's admin API for taking a person's authenticator away (POST-A-006).

WHY A MODULE OF ITS OWN
    Removing a second factor is the one act in this product that LOWERS somebody's sign-in protection on purpose, and it
    is done by the service-role key, which can do far more than that. Keeping the call in one small module means the
    approval engine has exactly one thing to name, a test can stand a fake in for the whole of it, and the library traps
    below are guarded in one place.

THE LIBRARY TRAPS (gotrue 2.11.4, pinned in the lock)
    1. Its delete call declares the parameters as `{"user_id", "id"}` and then BUILDS THE URL from `params.get("factor_id")`,
       so a call written exactly as the type says deletes `admin/users/<user>/factors/None` and the sign-in service
       answers 404 for a factor that is still enrolled.
    2. Its listing call validates the reply as `{"factors": [...]}`, while the service answers the listing as a BARE ARRAY
       (supabase-js wraps it in `{factors}` itself, in its own transform). Parsed by the library, the first real approval
       would fail inside the listing and answer 503 for a reason nobody could see from the sentence.
    So this module builds BOTH paths itself, through the admin class's own authenticated request method with its own
    parsing: the listing is read as either shape, and a delete is judged by the HTTP status alone (the reply body is never
    parsed, so a body the library did not expect cannot turn a removed factor into a failure). The method it relies on is
    private to the library, so `tests/test_a_lost_authenticator_is_reset_by_a_partner_other_than_the_asker.py` drives the
    REAL admin class over a stand-in HTTP transport (the URL, the method, a bare-array reply, a wrapped reply, an empty
    delete reply) and fails if a library release moves it.

WHAT IS NOT PROVEN
    Nothing here has been run against the live sign-in service (the container has no way to reach it with a real user).
    The paths are the service's documented ones, the parsing is tolerant of both reply shapes, and the first real reset is
    a step for a person (the ledger line that closed this one says so).
"""
from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger("caflow.auth_admin")


class AuthAdminError(Exception):
    """The sign-in service could not be asked, or refused. Carries no secret; the cause is chained.

    `removed` is how many factors were already gone when it failed, so the caller can say so in the audit trail."""

    def __init__(self, message: str, *, removed: int = 0):
        super().__init__(message)
        self.removed = removed


def factor_ids(body: Any) -> list[str]:
    """The factor ids in the sign-in service's listing, whichever of the two shapes it came in.

    A bare array of factors is what the service sends; `{"factors": [...]}` is what the library's own parser expects.
    Anything else, or a factor with no usable id, is an error and not an empty list: reading an unrecognised reply as
    "this person has no factors" would report a reset that removed nothing."""
    rows = body.get("factors") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        raise ValueError("the sign-in service's factor listing is neither a list nor an object with a factors list")
    ids: list[str] = []
    for row in rows:
        fid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(fid, str) or not fid.strip():
            raise ValueError("a factor in the sign-in service's listing has no id")
        ids.append(fid)
    return ids


def remove_all_authenticators(auth_user_id: str) -> int:
    """Delete every second factor (verified or not) the sign-in service holds for this account; return how many.

    Idempotent by construction: it lists first, so a second run after a partial failure removes what is left and
    returns that count. Raises `AuthAdminError` on any failure (carrying how many were removed before it), after which
    an unknown number of factors may already be gone, which is why the caller treats a failure as "try again" and not as
    "nothing happened".
    """
    if not auth_user_id or not isinstance(auth_user_id, str):
        raise AuthAdminError("no account id to reset")
    removed = 0
    try:
        from core.supabase_client import get_service_supabase
        admin = get_service_supabase().auth.admin
        ids = admin._request("GET", f"admin/users/{auth_user_id}/factors", xform=factor_ids)
        for fid in ids:
            admin._request("DELETE", f"admin/users/{auth_user_id}/factors/{fid}", no_resolve_json=True,
                           xform=lambda _response: None)
            removed += 1
    except Exception as exc:  # noqa: BLE001 - every failure here is "the sign-in service could not do it"
        _logger.error("caflow.auth_admin: removing the authenticators of %s failed after %d", auth_user_id, removed,
                      exc_info=True)
        raise AuthAdminError("the sign-in service could not remove the authenticator", removed=removed) from exc
    return removed

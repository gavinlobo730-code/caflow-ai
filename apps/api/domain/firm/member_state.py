"""What a member of the firm's team is, in one word the Team screen shows (PRE-A-020).

A staff invitation creates the member's row before they ever sign in: `POST /api/identity/users` writes
`is_active` true and `status` 'invited', with a single-use token and an expiry. So `is_active` alone cannot
tell a colleague who works here from an address an invitation was sent to, and the Team screen, which read it
alone, showed a member who had never accepted as Active (found by the owner on 15-11-2026). This is the one
rule, and `GET /api/identity/users` serves its answer on each row so the screen derives nothing.

    inactive        the row is switched off (`is_active` false): a Partner deactivated them or withdrew an invite
    active          the row is linked to a sign-in (`auth_user_id` set): the invitation was accepted
    invited         an invitation is outstanding: no sign-in yet, a token, and an expiry still ahead
    invite_expired  no sign-in, and the invitation can no longer be used: past its expiry, or its token is gone

A row with no sign-in that was never an invitation (a `status` other than 'invited', which rows written
before invitations existed and the mock fixtures carry) reads as active, as it always has: nothing on the row
tells it apart, and saying otherwise would be a guess.

The expiry is an instant, compared as one: it is stored as an ISO timestamp with its offset, and the
comparison is against the current instant, never against a calendar day.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

MEMBER_STATES = ("active", "invited", "invite_expired", "inactive")


def _instant(value: Any) -> Optional[datetime]:
    """An aware datetime from a stored timestamp, or None when there is none or it cannot be read. A naive
    value is read as UTC, which is what the column holds."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            # Not a timestamp. A timestamptz column always reads back as ISO text, so a stored instant never lands here: this is an absent value or a
            # hand-built one, and None says there is no instant.
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def member_state(row: Mapping[str, Any], now: Optional[datetime] = None) -> str:
    """The member's state, one of `MEMBER_STATES`. `row` is a `users` row as stored, its invite token
    included (the caller strips the token from what it sends after asking this)."""
    if row.get("is_active") is False:
        return "inactive"
    if row.get("auth_user_id"):
        return "active"
    if row.get("status") != "invited":
        return "active"
    moment = now or datetime.now(timezone.utc)
    expires = _instant(row.get("invite_expires_at"))
    # The token itself on a row read by `find_by_invite_token`; whether one is set (`invite_outstanding`) on every
    # other row, because the repository returns no other row with its token (POST-A-445).
    has_token = bool(row.get("invite_token") or row.get("invite_outstanding"))
    if has_token and expires is not None and expires > moment:
        return "invited"
    return "invite_expired"

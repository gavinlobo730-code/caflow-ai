"""How a staff invitation's token is kept: as a hash, never as the secret itself (POST-A-445).

WHY. The token in an invitation's link is a bearer secret, and since POST-A-445 it is more than that: the join page
turns it into a sign-in for the invitation's address (`POST /api/identity/accept-invite/session`). It used to be
stored as it was sent and returned on rows the API served (the team list, a role change, an activation), so a Manager
could read a pending Partner's invitation and a Partner of one practice could read the token of an invitation they
had sent to somebody else's address. A hash cannot be presented as the token, so a stored value that leaks opens
nothing. The employee portal's invitation has been kept this way since migration 264.

THE COLUMN IS THE SAME ONE. `users.invite_token` (migration 153, TEXT, unique while set) holds `sha256:<hex>` for an
invitation the server mailed, and the secret itself for one issued before POST-A-445. The prefix tells them apart:
the secret is URL-safe base64 and never contains a colon. A presented value that is already in the stored form is
refused outright, or a stored hash read from anywhere could be handed back as though it were the token.

WHAT THE OLDER FORM STILL DOES. An invitation stored before POST-A-445 can still be ACCEPTED by somebody already
signed in as its address (the link Supabase mailed carried that sign-in), and nothing else: the server opens a
sign-in only for an invitation in the stored form (`opens_a_sign_in`). A Partner who resends one replaces it with a
hashed one.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional

STORED_PREFIX = "sha256:"


def stored_form(token: str) -> str:
    """What the column holds for `token`."""
    return STORED_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_stored_form(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(STORED_PREFIX)


def lookup_values(token: Optional[str]) -> list[str]:
    """The column values a presented token matches: its stored form, and the token itself for an invitation stored
    before POST-A-445. Nothing for an empty value or one already in the stored form."""
    if not token or not isinstance(token, str) or is_stored_form(token):
        return []
    return [stored_form(token), token]


def opens_a_sign_in(row: Mapping[str, Any]) -> bool:
    """Whether the server may open a sign-in from this invitation: only one it mailed itself, kept hashed."""
    return is_stored_form(row.get("invite_token"))

"""Reads and writes one person's guided-tips preference on their own `users` row (POST-A-531). It decides nothing: `domain/guidance/tips`
holds the rule.

THE SERVER'S CLIENT, NAMING THE PERSON AND THEIR FIRM ON EVERY QUERY. The signed-in role cannot write these columns (it may write only its
own name on its own row), so the write is the server's, made for the person (`privileged_for`, so the row-level edit log names them). The
service role bypasses row security, so `.eq("id", user_id).eq("firm_id", firm_id)` on each query is the isolation: an id from another firm
matches nothing.

A ROW THAT CANNOT BE READ IS NOT "TIPS OFF" AND NOT "NOTHING CLOSED". `read` answers None, and every write that cannot find the row raises
`NotFound`, so a screen is never told a preference was saved when it was not.

CLOSING A TIP IS READ-THEN-WRITE. Two tabs of one person closing two different tips in the same instant can lose one of them, and that tip
is shown once more. That is the whole cost, and a database function to make it atomic would be a function a signed-in session must be
kept from calling for the sake of it.
"""
from __future__ import annotations

from typing import Optional

from core import db_provider
from core.db_provider import privileged_for
from domain.guidance import tips as rule

_db = db_provider.service_db
_COLUMNS = "id, guided_tips_on, guided_tips_seen"


class NotFound(Exception):
    """The caller has no `users` row in this firm, so there is nothing to read or write."""


def _row(db, firm_id: str, user_id: str) -> Optional[dict]:
    rows = (db.table("users").select(_COLUMNS)
            .eq("id", user_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def read(firm_id: str, user_id: Optional[str]) -> Optional[dict]:
    """The person's tips state, or None when they have no row here."""
    if not user_id:
        return None
    row = _row(_db(), firm_id, user_id)
    return rule.state(row) if row else None


def _own_row(firm_id: str, user_id: Optional[str]):
    """The server's client and the person's own row, or `NotFound`. Every write below starts here."""
    if not user_id:
        raise NotFound()
    db = privileged_for(_db())
    row = _row(db, firm_id, user_id)
    if row is None:
        raise NotFound()
    return db, row


def _stored(db, firm_id: str, user_id: str) -> dict:
    row = _row(db, firm_id, user_id)
    if row is None:
        raise NotFound()
    return rule.state(row)


# EACH WRITE IS A LITERAL. `tests/test_the_member_check_rests_on_two_premises_that_a_test_holds_pg.py` reads every update of `users`
# to show that none of them sets `firm_id`, and it can read a payload only where it is written out. So the three writes are three
# statements and not one helper that takes a dict.

def set_on(firm_id: str, user_id: Optional[str], on: bool) -> dict:
    """The person turns tips on or off. Returns the state as stored."""
    db, _ = _own_row(firm_id, user_id)
    db.table("users").update({"guided_tips_on": bool(on)}).eq("id", user_id).eq("firm_id", firm_id).execute()
    return _stored(db, firm_id, user_id)


def mark_seen(firm_id: str, user_id: Optional[str], tip_id: str) -> dict:
    """The person closes one tip for good. Returns the state as stored."""
    db, row = _own_row(firm_id, user_id)
    seen = rule.clean_seen(row.get("guided_tips_seen"))
    if tip_id in seen:
        return rule.state(row)
    db.table("users").update({"guided_tips_seen": rule.with_seen(seen, tip_id)}).eq("id", user_id).eq("firm_id", firm_id).execute()
    return _stored(db, firm_id, user_id)


def show_all_again(firm_id: str, user_id: Optional[str]) -> dict:
    """The person asks to be shown every tip again. Their on/off choice is not touched."""
    db, _ = _own_row(firm_id, user_id)
    db.table("users").update({"guided_tips_seen": []}).eq("id", user_id).eq("firm_id", firm_id).execute()
    return _stored(db, firm_id, user_id)

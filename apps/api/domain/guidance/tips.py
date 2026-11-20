"""Guided tips: what the server keeps for one person, and nothing about what a tip says (POST-A-531).

THE SPLIT. A tip is a sentence on a screen about a thing on that screen, so the tips themselves are written beside the screens
(`apps/web/lib/tips/registry.ts`, held to the code by its own guard). The SERVER keeps the two facts that must follow a person to every
device: whether they want tips at all, and which they have already closed. So this module knows the shape of a tip's id and not a list of
tips: a list here would be a second registry that drifts from the screens'.

THE DEFAULT IS ON, FOR EVERY STAFF ROLE. `guided_tips_on` is NULL until a person turns the switch either way; NULL answers on. The owner
asked for a new CA to be shown round, and a colleague an hour into the product needs it as much as the Partner who signed the firm up. A
person who has chosen keeps their choice whatever the default becomes, which is why "never chosen" is kept apart from "chose on".

A TIP ID IS A SLUG. Lower-case letters, digits and single hyphens, at most `MAX_TIP_ID` characters: it is stored in a row, logged and sent
back to a screen that uses it to look a tip up, so it is never free text.

THE LIST OF CLOSED TIPS IS BOUNDED. `MAX_SEEN` ids, the oldest dropped first. A person cannot grow their own row without limit by posting
ids, and a dropped id costs one tip shown once more.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

MAX_TIP_ID = 64
MAX_SEEN = 300
DEFAULT_ON = True

_TIP_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def tip_id_problem(tip_id: object) -> Optional[str]:
    """None when `tip_id` is a tip's id; otherwise one sentence saying what is wrong with it."""
    if not isinstance(tip_id, str) or not tip_id:
        return "A tip is named by its id."
    if len(tip_id) > MAX_TIP_ID:
        return f"A tip's id is at most {MAX_TIP_ID} characters."
    if not _TIP_ID.match(tip_id):
        return "A tip's id is lower-case letters, digits and single hyphens."
    return None


def resolved_on(stored: Optional[bool]) -> bool:
    """Whether the person is shown tips: their own choice, or the default where they never chose."""
    return DEFAULT_ON if stored is None else stored is True


def clean_seen(stored: object) -> list[str]:
    """The stored list as ids, in the order they were closed, each once. Anything that is not a tip's id is dropped: a row written by
    something else must not reach a screen as a tip the person has closed."""
    out: list[str] = []
    if not isinstance(stored, (list, tuple)):
        return out
    for item in stored:
        if tip_id_problem(item) is None and item not in out:
            out.append(item)
    return out


def with_seen(seen: Iterable[str], tip_id: str) -> list[str]:
    """`seen` with `tip_id` closed. Closing a tip twice changes nothing; a full list drops its oldest ids."""
    out = clean_seen(list(seen))
    if tip_id not in out:
        out.append(tip_id)
    return out[-MAX_SEEN:]


def state(row: dict) -> dict:
    """What a screen is told about one person's tips, from their own `users` row."""
    stored = row.get("guided_tips_on")
    return {
        "on": resolved_on(stored),
        # False = the person never turned the switch, so `on` is the product's default and not their decision.
        "chosen": stored is not None,
        "seen": clean_seen(row.get("guided_tips_seen")),
    }

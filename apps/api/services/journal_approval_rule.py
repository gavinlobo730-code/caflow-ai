"""Who may put a manual journal on the books, asked the same way at every door (POST-A-456).

THE RULE. A firm says, in `firms.manual_journals_need_approval` (migration 681), whether a Partner approves every manual journal.

* OFF (the default, and every firm's state when the column arrived): anyone who may write the books (`accounting` `write`, a Manager and
  above, or whoever the Team grid gives it) may put a manual journal on them, as a NEW entry sent as posted or by posting a SAVED DRAFT.
  The two doors used to disagree: the first asked `write` and the second `approve`, so the Approvals queue was a step a Manager went
  around by typing the entry again as new.
* ON: only someone who may APPROVE (`accounting` `approve`, a Partner, or whoever the grid gives it) may post a new entry, post a draft,
  or correct or delete an entry already on the books. Everyone else who may write saves a DRAFT, which waits in Approvals. Correcting and
  deleting a posted entry are held to it too, because otherwise a member could change the figures of an entry a Partner approved.

WHY THIS SHAPE, BY THE THREE TESTS. Lawful: no statute asks a practice to have a second person approve its client's journals, and the
edit log (Companies (Accounts) Rules 2014, Rule 3(1) proviso) records who did what either way, so both answers are lawful. Safe for the
client's data: an approval step is a second pair of eyes on judgement entries, so a firm that wants one must be able to have it, and the
API, not the screen, is what holds it. Best for the product: practices differ (in many, a Manager passes journals and the Partner reviews at
the year end), and forcing approval on every firm would turn the queue into the rubber stamp `services/bank_posting_service.post` records
removing for bank lines, so the firm chooses, and the default is the behaviour a Manager already had at the create door.

What it does NOT govern: reversing a posted journal, which stays `accounting` `approve` at its own route whatever the setting says, and
postings made by the documents themselves (invoices, bills, receipts, bank lines), which are not manual journals.

A DATABASE WITHOUT THE COLUMN (migration 681 not applied yet, the minutes the API is live first) reads as OFF: no firm can have chosen ON
before the column existed. Any other failure to read the setting is a 503 for someone who is not an approver, never a guess.
"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException

from core.permissions import can_user

_logger = logging.getLogger("caflow.journal_approval_rule")

_COLUMN = "manual_journals_need_approval"

#: Mock mode (no SUPABASE_URL): the firm's answer, held in the process.
_MOCK_SETTING: dict[str, bool] = {}

#: The refusal, said once, so the five doors cannot word it differently.
REFUSAL_TO_POST = ("This firm has every manual journal approved before it posts, and you may not approve. Save the entry as a draft: it waits in "
                   "Approvals for someone who may approve it.")
REFUSAL_TO_CHANGE_POSTED = ("This firm has every manual journal approved before it posts, and you may not approve, so you cannot change or delete "
                            "an entry that is on the books. Ask someone who may approve, or reverse it through them.")
UNREADABLE = ("Could not read whether this firm has manual journals approved before they post, so the entry was not posted. Try again in a "
              "moment, or save it as a draft.")


def _use_mock() -> bool:
    return not os.environ.get("SUPABASE_URL")


def reset_mock_store() -> None:  # test helper
    _MOCK_SETTING.clear()


def _names_the_missing_column(error: Exception) -> bool:
    text = str(error).lower()
    return _COLUMN in text and (getattr(error, "code", None) in ("42703", "PGRST204") or "42703" in text
                                or "pgrst204" in text or "does not exist" in text)


def approval_required(firm_id: str) -> bool:
    """Whether the firm has a Partner approve every manual journal. Raises 503 when the answer cannot be read (see the module docstring)."""
    if _use_mock():
        return bool(_MOCK_SETTING.get(firm_id, False))
    from core import db_provider

    db = db_provider.service_db_or_none()
    if db is None:
        return bool(_MOCK_SETTING.get(firm_id, False))
    try:
        rows = db.table("firms").select("id, manual_journals_need_approval").eq("id", firm_id).limit(1).execute().data or []
    except Exception as exc:  # noqa: BLE001 — only the missing column is answered; anything else is a refusal, never a guess
        if _names_the_missing_column(exc):
            _logger.error("approval_required: migration 681 is not applied to this database; every firm reads as not requiring approval")
            return False
        _logger.exception("approval_required: the firm's setting could not be read")
        raise HTTPException(status_code=503, detail=UNREADABLE) from exc
    if not rows:
        raise HTTPException(status_code=503, detail=UNREADABLE)
    return bool(rows[0].get(_COLUMN))


def may_approve(user: dict) -> bool:
    return can_user(user, "accounting", "approve")


def may_post(user: dict) -> bool:
    """Whether THIS person may put a manual journal on the books now: an approver always; a writer while the firm does not require approval."""
    if may_approve(user):
        return True
    if not can_user(user, "accounting", "write"):
        return False
    return not approval_required(str(user.get("firm_id") or ""))


def assert_may_post(user: dict) -> None:
    """The check at the three doors that put a manual journal on the books: a new entry sent as posted, posting a saved draft, and a
    voucher import sent as posted (asked on its preview too)."""
    if not may_post(user):
        raise HTTPException(status_code=403, detail=REFUSAL_TO_POST)


def assert_may_change_posted(user: dict) -> None:
    """The check at the two doors that change an entry already on the books: a correction and a delete."""
    if not may_post(user):
        raise HTTPException(status_code=403, detail=REFUSAL_TO_CHANGE_POSTED)


def describe(user: dict) -> dict:
    """What the screens are served: the firm's setting, what THIS person may do under it, and whether they may change it."""
    required = approval_required(str(user.get("firm_id") or ""))
    approver = may_approve(user)
    writer = can_user(user, "accounting", "write")
    return {
        "approval_required": required,
        "may_post": approver or (writer and not required),
        "may_approve": approver,
        "may_change_setting": can_user(user, "settings", "write"),
    }


def set_required(firm_id: str, required: bool) -> bool:
    """Record the firm's answer. Scoped to the caller's own firm by the caller; returns what was stored."""
    if _use_mock():
        _MOCK_SETTING[firm_id] = bool(required)
        return bool(required)
    from core import db_provider

    db = db_provider.service_db_or_none()
    if db is None:
        _MOCK_SETTING[firm_id] = bool(required)
        return bool(required)
    try:
        res = db.table("firms").update({"manual_journals_need_approval": bool(required)}).eq("id", firm_id).execute()
    except Exception as exc:  # noqa: BLE001 — a database without the column cannot hold the answer; said so rather than raised raw
        if _names_the_missing_column(exc):
            raise HTTPException(status_code=503, detail="This setting is not available yet: the database is being updated. Try again "
                                                        "in a few minutes.") from exc
        raise
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Firm not found.")
    return bool(required)


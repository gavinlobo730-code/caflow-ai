"""A client's narration templates: list, save, archive (POST-A-093, migration 590).

`domain/accounting/narration_templates` is the rule for the words; this reads and writes the rows. A template is the words and nothing
else: the journal editor fills its narration box from one, and the entry stores the words, so nothing here touches a journal.

READS go through the caller's own client (the signed-in role may read the table, scoped by row security to the clients the member is
assigned), and every read names the firm and the client. WRITES go through `privileged_for(db)`, because the signed-in role holds no
write on the table (migration 590), and that client carries the acting person (migration 547). `created_by` is the member's internal
`users.id`, the id the column's key holds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.db_provider import privileged_for
from core.exceptions import _sqlstate
from domain.accounting import narration_templates as rule

#: Said when the database refuses the words as a duplicate and the template that holds them cannot be read back.
ALREADY_SAVED = "These words are already saved for this client."


def list_templates(db, firm_id: str, client_id: str) -> list[dict]:
    """The client's live templates, alphabetically by their words (ignoring case), as a picker shows them."""
    rows = fetch_all(
        lambda: db.table("journal_narration_templates").select("id, narration, created_at")
        .eq("firm_id", firm_id).eq("client_id", client_id).is_("archived_at", "null"),
        label="narration_templates.list")
    shaped = [{"id": r.get("id"), "narration": r.get("narration"), "created_at": r.get("created_at")} for r in rows]
    return sorted(shaped, key=lambda r: (rule.normalise(r["narration"]).casefold(), str(r["id"])))


def _live_with_the_same_words(db, firm_id: str, client_id: str, words: str) -> Optional[dict]:
    return next((r for r in list_templates(db, firm_id, client_id) if rule.same_words(r.get("narration"), words)), None)


def save(db, firm_id: str, client_id: str, narration: Optional[str], *, actor_id: Optional[str]) -> dict:
    """Save these words as a template of the client, or answer the one that already says them.

    Returns `{"template": row, "created": bool}`. Words already saved (ignoring case and spacing) are not saved twice: the answer is
    the template that holds them, so a second press of "Save as template" is harmless. Words the rule refuses are a 422 in its words.
    """
    problem = rule.problem(narration)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    words = rule.normalise(narration)
    existing = _live_with_the_same_words(db, firm_id, client_id, words)
    if existing:
        return {"template": existing, "created": False}
    try:
        res = privileged_for(db).table("journal_narration_templates").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "narration": words,
            "narration_key": rule.key(words),
            "created_by": actor_id,
        }).execute()
    except Exception as exc:
        # Two saves of the same words at one moment: the database's unique index (on the same key the service compares by) takes one,
        # and the other is answered with it. A refusal whose winner cannot be read back is said in words, never a bare error.
        if _sqlstate(exc) != "23505":
            raise
        existing = _live_with_the_same_words(db, firm_id, client_id, words)
        if not existing:
            raise HTTPException(status_code=409, detail=ALREADY_SAVED) from exc
        return {"template": existing, "created": False}
    row = (res.data or [{}])[0]
    return {"template": {"id": row.get("id"), "narration": row.get("narration", words), "created_at": row.get("created_at")},
            "created": True}


def archive(db, firm_id: str, client_id: str, template_id: str) -> dict:
    """Take a template out of the picker. The row is kept (an entry never pointed at it, so nothing else changes); a template that is
    not one of this client's live ones is a 404, worded the same either way."""
    found = (db.table("journal_narration_templates").select("id")
             .eq("firm_id", firm_id).eq("client_id", client_id).eq("id", template_id).is_("archived_at", "null")
             .limit(1).execute().data or [])
    if not found:
        raise HTTPException(status_code=404, detail="That narration template was not found.")
    done = (privileged_for(db).table("journal_narration_templates").update({"archived_at": datetime.now(timezone.utc).isoformat()})
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("id", template_id).is_("archived_at", "null").execute().data or [])
    if not done:
        # Another request archived it between the read and the write: this one archived nothing, and says so the same way.
        raise HTTPException(status_code=404, detail="That narration template was not found.")
    return {"id": template_id, "archived": True}

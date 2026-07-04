"""
Year-end engagement workflow — shared logic between routers/year_end.py's
generic status-transition endpoint and routers/year_end_reviews.py's
specific review-step endpoints.

R3.8: the two routers implement genuinely different, both-legitimate
things (year_end.py: a simple, generic transition; year_end_reviews.py: a
richer 4-step review workflow with per-step actor/timestamp columns, a
revision-request loop, and its own audit trail) — not accidental
duplication to merge away. But ONE piece of behavior matters identically
in both: completing an engagement (→ locked) must also lock its financial
year for posting. That one behavior is extracted here so it cannot
independently drift between the two routers the way it had — year_end.py
had it, year_end_reviews.py's final_approve (the only actually-reachable
locking transition, since the frontend never called year_end.py's
endpoint at all) did not.
"""
from typing import Optional


def lock_year_if_completing(
    db,
    firm_id: str,
    financial_year: Optional[str],
    new_status: str,
    actor_id: Optional[str],
    actor_email: Optional[str],
) -> None:
    """When an engagement transitions to 'locked', lock its financial year
    for posting too. This transition is already Partner-gated, so the
    system lock bypasses the interactive PIN. Idempotent and audited."""
    if new_status != "locked" or not financial_year:
        return
    from services.year_lock_service import set_lock
    set_lock(
        db, firm_id, financial_year, lock=True, bypass_pin=True,
        actor_id=actor_id, actor_email=actor_email,
    )

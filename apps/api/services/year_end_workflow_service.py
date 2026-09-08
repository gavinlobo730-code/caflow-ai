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
import logging
from typing import Optional

_logger = logging.getLogger("caflow.year_end_workflow")


def lock_year_if_completing(
    db,
    firm_id: str,
    financial_year: Optional[str],
    new_status: str,
    actor_id: Optional[str],
    actor_email: Optional[str],
    client_id: Optional[str] = None,
    actor_auth_id: Optional[str] = None,
) -> None:
    """When an engagement transitions to 'locked', close THAT CLIENT's
    financial year for posting. Idempotent and audited.

    This used to call set_lock(db, firm_id, financial_year, ...) — a
    FIRM-level lock with no client dimension — so finalising one client's
    year-end stopped posting in that year for every other client in the
    practice, and clearing it needed the firm lock PIN. In March or September
    that is a practice-wide outage caused by a routine Partner click.

    An engagement belongs to one accounting entity, so the lock it produces
    belongs to one entity too (migration 289). The firm-level lock is
    untouched and still available as a deliberate practice-wide decision
    through the Partner-gated, PIN-guarded endpoint.

    client_id is optional only so that an older caller cannot crash; without
    it there is nothing to lock, and locking the whole firm instead is exactly
    the bug being removed — so it refuses rather than falling back.
    """
    if new_status != "locked" or not financial_year:
        return
    if not client_id:
        _logger.warning(
            "lock_year_if_completing called without client_id for firm %s "
            "FY %s — not locking. A year-end engagement closes one client's "
            "year; there is no correct firm-wide fallback.",
            firm_id, financial_year,
        )
        return
    from services.year_lock_service import set_client_lock
    set_client_lock(
        db, firm_id, client_id, financial_year, lock=True,
        actor_id=actor_id, actor_email=actor_email,
        actor_auth_id=actor_auth_id,
        reason="Year-end engagement finalised",
    )


def unlock_year_on_reopen(
    db,
    firm_id: str,
    financial_year: Optional[str],
    reason: str,
    actor_id: Optional[str],
    actor_email: Optional[str],
    client_id: Optional[str] = None,
    actor_auth_id: Optional[str] = None,
) -> None:
    """Reopen THAT CLIENT's financial year when a locked engagement is reopened.

    THE OTHER HALF, WHICH DID NOT EXIST (ACC-05). set_client_lock has taken
    lock=False since migration 289, and nothing had ever passed it: the only
    caller in the repository was lock_year_if_completing with lock=True, and
    routers/year_end.py made "locked" a terminal status. So the kernel's refusal
    — "FY {fy} is closed for this client — its year-end has been finalised.
    Reopen the year before posting to it." — named an action the product did not
    have. The only remedies left were a DELETE straight on client_year_locks or
    posting the correction into the wrong year.

    Every Indian practice reopens a closed year: a revised interest certificate
    in October, a §143(1) intimation, an audit adjustment found while filing the
    ITR. Tally's period lock is set and cleared at will; Zoho Books lets an
    admin unlock a closed period with a reason. The reason is the point — this
    is a Partner reversing a Partner's own finalisation, and the audit row
    set_client_lock already writes is what makes that answerable later.

    Deliberately NOT idempotent-silent about a missing reason: the caller is
    responsible for demanding one, and passing an empty string here would write
    an audit row that records nothing about why a closed year was opened.
    """
    if not financial_year:
        return
    if not client_id:
        _logger.warning(
            "unlock_year_on_reopen called without client_id for firm %s FY %s "
            "— not unlocking. A year-end reopens one client's year; there is "
            "no correct firm-wide fallback.",
            firm_id, financial_year,
        )
        return
    from services.year_lock_service import set_client_lock
    set_client_lock(
        db, firm_id, client_id, financial_year, lock=False,
        actor_id=actor_id, actor_email=actor_email,
        actor_auth_id=actor_auth_id,
        reason=reason,
    )

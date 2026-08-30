"""A client's closed year is enforced by the posting kernel, for that client only.

WHAT WAS WRONG
    Finalising a year-end engagement called
    year_lock_service.set_lock(db, firm_id, financial_year, ...) — a FIRM-level
    lock written into firms.locked_financial_years, with no client dimension
    anywhere in the path. A Partner finalising ONE client's FY 2024-25 stopped
    posting in that year for EVERY OTHER CLIENT in the practice, and clearing it
    needed the firm lock PIN. In March or September that is a practice-wide
    outage caused by a routine click.

    It is also the wrong shape. The tenancy model is firm = tenant, client =
    accounting entity, and a year-end engagement belongs to one entity.

WHERE IT IS ENFORCED, AND WHY THERE
    In services/phase2_journal_service._create_journal. CLAUDE.md guarantees
    that every accounting event touching the GL is written by that one method,
    so a single check covers sales, purchases, banking, payroll, fixed assets,
    opening balances, manual journals and reversals alike. The alternative was
    threading a client_id through validate_posting_date's 67 call sites — far
    more churn for weaker coverage.

    The FIRM-level lock is untouched and still checked by those call sites. A
    posting is refused if EITHER applies.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import FakeDB

FIRM = "F1"
LOCKED_CLIENT = "C-locked"
OPEN_CLIENT = "C-open"

# 2024-25 (April 2024 – March 2025), so a date inside it and one outside are
# both easy to name.
IN_LOCKED_FY = "2024-06-01"
IN_LATER_FY = "2025-06-01"


def _lines():
    return [
        {"account_id": "a1", "debit_paise": 10_000_00, "credit_paise": 0},
        {"account_id": "a2", "debit_paise": 0, "credit_paise": 10_000_00},
    ]


def _post(db, client_id: str, entry_date: str, ref: str) -> str:
    from services.phase2_journal_service import Phase2JournalService
    return Phase2JournalService()._create_journal(
        db, FIRM, client_id, entry_date, ref, "n", "Journal", _lines(),
    )


@pytest.fixture()
def db():
    d = FakeDB()
    d.seed("client_year_locks", {
        "id": "L1", "firm_id": FIRM, "client_id": LOCKED_CLIENT,
        "financial_year": "2024-25", "reason": "Year-end engagement finalised",
    })
    return d


def test_posting_into_a_clients_closed_year_is_refused(db):
    with pytest.raises(ValueError, match="closed for this client"):
        _post(db, LOCKED_CLIENT, IN_LOCKED_FY, "REF-1")


def test_another_client_in_the_same_year_is_unaffected(db):
    """The whole point. One client's year-end must not stop the practice."""
    entry_id = _post(db, OPEN_CLIENT, IN_LOCKED_FY, "REF-2")
    assert entry_id, (
        "a second client's posting was blocked by the first client's year-end — "
        "the practice-wide outage this change removes"
    )


def test_the_same_client_in_a_later_year_is_unaffected(db):
    """Closing FY 2024-25 must not close FY 2025-26."""
    assert _post(db, LOCKED_CLIENT, IN_LATER_FY, "REF-3")


def test_the_january_to_march_quarter_belongs_to_the_year_that_began_in_april(db):
    """The Indian FY runs 1 April – 31 March, so 15 February 2025 is inside
    FY 2024-25 and must be refused. Getting this backwards would leave the
    last quarter of every closed year open."""
    with pytest.raises(ValueError, match="closed for this client"):
        _post(db, LOCKED_CLIENT, "2025-02-15", "REF-4")


def test_the_first_of_april_starts_the_new_year(db):
    """1 April 2025 is FY 2025-26 — the boundary, from the open side."""
    assert _post(db, LOCKED_CLIENT, "2025-04-01", "REF-5")


def test_the_thirty_first_of_march_is_still_the_closed_year(db):
    with pytest.raises(ValueError, match="closed for this client"):
        _post(db, LOCKED_CLIENT, "2025-03-31", "REF-6")


def test_another_firms_lock_does_not_reach_this_firm(db):
    db.seed("client_year_locks", {
        "id": "L2", "firm_id": "OTHER-FIRM", "client_id": OPEN_CLIENT,
        "financial_year": "2024-25",
    })
    assert _post(db, OPEN_CLIENT, IN_LOCKED_FY, "REF-7")

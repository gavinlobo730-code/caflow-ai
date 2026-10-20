"""Whether a compliance obligation is OVERDUE: one rule, for every reader of `compliance_records` that counts them.

THE WORD IS NOT WRITTEN. `compliance_records.status` is the stored workflow state, and "Overdue" in it is a transition somebody makes by hand
(`compliance_record_service.VALID_TRANSITIONS`): nothing in `apps/api` sets it when a due date passes. The browser knew this and derives it
(`apps/web/lib/compliance/overdue.ts`: "nothing in apps/api sets it when a due date passes"), so the Deadlines screen counted 220 overdue
obligations on the seeded demo firm. Readers in seven backend modules still asked the stored word, so on the same firm the executive
dashboard said `compliance_failures` 0, the client health score deducted nothing for any of them, the risk engine and the insight generator
raised nothing, and the AI assistant was told "OVERDUE COMPLIANCE FILINGS: 0". The same firm, two answers. (The dashboard's firm health ring
reads another column, `clients.health_score`, which nothing writes: that is a separate item on the ledger, POST-A-279.)

THE RULE, the browser's with this table's own settled words. Not settled, and either somebody moved it to "Overdue" by hand or its due date is
strictly BEFORE today: an obligation due today is not late until the day is out. Settled is "Filed" and "Completed" (the terminal step after
Filed; the browser's pair is "filed" and "na", its own vocabulary), which owe nothing whatever the date; the older readers compared only to
"Filed", so a Completed obligation with a past date counted as late. A missing due date cannot be late (`"" < today` would say it is).
"Today" is the CA's day, a date and not an instant: callers pass `ist_today()` once, so every row of one answer is judged against one day.
`tests/test_one_rule_says_a_compliance_obligation_is_overdue.py` pins this module and scans the backend for any reader that asks the stored
word again.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

#: Workflow states that owe nothing, however far past the due date.
SETTLED = ("Filed", "Completed")
#: The only stored state that is itself a claim of lateness (set by hand).
STORED_OVERDUE = "Overdue"


def is_settled(status: Optional[str]) -> bool:
    return status in SETTLED


def is_overdue(record: dict, today: date) -> bool:
    status = record.get("status")
    if is_settled(status):
        return False
    if status == STORED_OVERDUE:
        return True
    due = str(record.get("due_date") or "")
    # `[:10]` on the day so a datetime handed in by mistake (a subclass of date) is still read as its day: "2026-10-20" sorts BEFORE
    # "2026-10-20T10:00:00", which would call an obligation due today late.
    return due != "" and due < today.isoformat()[:10]


def overdue_records(records: Iterable[dict], today: date) -> list[dict]:
    """The records that are overdue on `today`, in the order given."""
    return [r for r in records if is_overdue(r, today)]

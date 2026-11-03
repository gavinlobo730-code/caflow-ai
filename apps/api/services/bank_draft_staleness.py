"""Mark a client's open bank lines for re-proposal (POST-A-272).

WHY THIS IS NOT A METHOD OF THE BANK ENTRY SERVICE ALONE. What the queue proposes for an open debit depends on facts that live outside the
bank module: a rule, and, since migration 578, a recorded TDS challan. The router that records, retracts, ties or untied a challan has to say
"the proposals for this client may have changed" without importing the service that PASSES lines (a router that reaches a posting module is
a router the database's posting lock has to be reviewed for: `tests/test_the_two_ledger_functions_ask_the_closure_and_the_pairs_the_posting_routes_ask.py`).
So the one UPDATE lives here, reads no ledger and posts nothing, and `BankEntryService.mark_stale` and the TDS register both call it.

It writes `drafted_at = NULL` and nothing else: the redraft happens in chunks, with progress, when the queue is next asked for.
"""
from __future__ import annotations

from domain.banking import entry as E
from core.db_provider import privileged_for


def mark_stale(db, firm_id: str, client_id: str) -> int:
    """Every open line of the client is re-proposed on the next redraft. One UPDATE; returns how many lines it marked."""
    rows = (privileged_for(db).table("bank_transactions").update({"drafted_at": None})
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("entry_state", list(E.OPEN_STATES)).execute().data or [])
    return len(rows)

"""Which tables are the payroll, bank and document tables, and which database functions read them (POST-A-010, POST-A-339).

One definition, read by the two guards that hold the same set from two sides: the browser reaches none of them
(`test_a_sensitive_table_is_not_read_from_the_browser.py`) and the API queries every one of them with the privileged client
(`test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client.py`). Two copies of this list would drift the way
every pair of copies in this repository has, so it lives here once.
"""
from __future__ import annotations

#: Whole-name prefixes: a table created next month under one of them is covered with no edit.
SENSITIVE_PREFIXES = ("payroll_", "bank_")

#: Exact names the prefixes do not cover.
SENSITIVE_TABLES = frozenset({
    # payroll: hangs from an employee (`salary_slips` is a view over the payroll tables, so it is held with them)
    "leave_balances", "attendance", "salary_structures", "salary_slips",
    # documents
    "client_documents", "documents", "document_requests",
    "document_extractions", "document_risks", "entity_documents",
})

#: Database functions that read or write a bank table and are called with the privileged client: the two that are not
#: `SECURITY DEFINER` and read a bank table as whoever calls them (called with a signed-in session's client they fail the day that
#: session loses its grant), and `replace_bank_transaction_splits`, a definer executable by the SERVICE ROLE ALONE (migration 256;
#: production's ACL read on 26-10-2026) that was being called on the caller's own sign-in and so refused by the database.
SENSITIVE_RPCS = frozenset({"bank_register", "bank_reconciling_items", "replace_bank_transaction_splits"})


def is_sensitive(table: str) -> bool:
    return table in SENSITIVE_TABLES or table.startswith(SENSITIVE_PREFIXES)

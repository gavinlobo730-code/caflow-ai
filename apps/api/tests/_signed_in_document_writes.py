"""Give the signed-in roles back the write privileges migration 563 revokes on the six document headers and their lines, in a throwaway database.

Migration 563 is the FIRST lock on twelve tables (`client_sales_invoices`, `purchase_bills`, `credit_notes`, `debit_notes`,
`purchase_credit_notes`, `sales_debit_notes` and the six lines tables): a signed-in session (`authenticated`, `anon`) holds no INSERT,
UPDATE, DELETE or TRUNCATE on them. The row policies and the triggers of 539, 541 and 544 stay as the SECOND lock, and several test
modules exist to measure that second lock by writing as a signed-in role. With the first lock in place every such write is refused by
the privilege before a policy or a trigger is asked, so the module would measure nothing. Those modules call
`give_the_signed_in_writes_back` once their rows are seeded; the privilege itself is measured by
`test_563_a_signed_in_session_writes_none_of_the_six_document_headers_or_their_lines_pg.py`, and the access matrix keeps a control that
puts it back.

The rollback file is the source, so this cannot drift from what the migration took away.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROLLBACK = (Path(__file__).resolve().parents[1] / "migrations" /
             "563_a_signed_in_session_writes_none_of_the_six_document_headers_or_their_lines_rollback.sql")


def rollback_sql() -> str:
    return _ROLLBACK.read_text(encoding="utf-8")


def give_the_signed_in_writes_back(dsn: str) -> None:
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=rollback_sql(), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

"""Give the signed-in roles back what migration 551 takes away from them, in a throwaway database.

Migration 551 takes every signed-in privilege on the five document tables (`documents`, `client_documents`, `document_requests`,
`document_extractions`, `document_risks`) and DROPS the object policies of 005, 426 and 469 on `storage.objects`. For the tables the
row policies stay as the SECOND lock, and several test modules exist to measure that second lock by acting as a signed-in role: with
the first lock in place every such statement is refused by the privilege before a policy is asked, so the module would measure
nothing. For Storage the policies were the only lock, so a module that measures them measures what 551's ROLLBACK restores, which is
worth holding for its own sake: the rollback has to leave a database whose files open for the people the policies name.

Those modules call `give_the_signed_in_document_access_back` once their rows are seeded; the live state is measured by
`test_551_*_pg.py`, and the access matrix keeps controls that put it back. The rollback file is the source, so this cannot drift from
what the migration took away.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROLLBACK = (Path(__file__).resolve().parents[1] / "migrations" /
             "551_a_signed_in_session_reads_and_writes_none_of_the_document_tables_and_opens_no_stored_file_rollback.sql")


def give_the_signed_in_document_access_back(dsn: str) -> None:
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=_ROLLBACK.read_text(encoding="utf-8"), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

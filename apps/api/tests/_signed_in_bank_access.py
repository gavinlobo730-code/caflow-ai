"""Give the signed-in roles back the privileges migration 550 revokes on the bank tables, in a throwaway database.

Migration 550 is the FIRST lock on the eight bank tables (a signed-in session holds no privilege on them at all) and on the two
bank reports (`bank_register`, `bank_reconciling_items`: not executable by it). The row-security policies of 093, 261, 370, 487,
524, 527 and 530 stay as the SECOND lock, and several test modules exist to measure that second lock by acting as a signed-in
role. With the first lock in place every such statement is refused by the privilege before a policy is asked, so the module would
measure nothing. Those modules call `give_the_signed_in_bank_access_back` once their rows are seeded; the privilege itself is
measured by `test_550_*_pg.py`, and the access matrix keeps a control that puts it back.

The rollback file is the source, so this cannot drift from what the migration took away.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROLLBACK = (Path(__file__).resolve().parents[1] / "migrations" /
             "550_a_signed_in_session_reads_and_writes_none_of_the_bank_tables_and_runs_neither_bank_report_rollback.sql")


def give_the_signed_in_bank_access_back(dsn: str) -> None:
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=_ROLLBACK.read_text(encoding="utf-8"), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

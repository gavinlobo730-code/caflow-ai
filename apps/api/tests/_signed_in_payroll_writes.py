"""Give the signed-in roles back the payroll write privileges migration 499 revokes, in a throwaway database.

Migration 499 is the FIRST lock on seventeen payroll tables: a signed-in session (`authenticated`, `anon`) holds no
INSERT, UPDATE, DELETE or TRUNCATE on them. The row-security policies of 261/485/490 and the triggers of 498 stay as the
SECOND lock, and several test modules exist to measure that second lock by writing as a signed-in role. With the first
lock in place every such write is refused by the privilege before a policy or a trigger is asked, so the module would
measure nothing. Those modules call `give_the_signed_in_writes_back` once their rows are seeded; the privilege itself is
measured by `test_499_*_pg.py`, and the access matrix keeps a control that puts it back.

The rollback file is the source, so this cannot drift from what the migration took away.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROLLBACK = (Path(__file__).resolve().parents[1] / "migrations" /
             "499_a_signed_in_session_writes_none_of_the_payroll_tables_the_browser_never_writes_rollback.sql")


def rollback_sql() -> str:
    return _ROLLBACK.read_text(encoding="utf-8")


def give_the_signed_in_writes_back(dsn: str) -> None:
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=rollback_sql(), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

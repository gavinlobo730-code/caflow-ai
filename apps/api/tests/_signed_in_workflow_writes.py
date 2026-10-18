"""Give the signed-in roles back the workflow write privileges migration 509 revokes, in a throwaway database.

Migration 509 is the FIRST lock on the eleven `workflow_*` tables: a signed-in session (`authenticated`, `anon`) holds no
INSERT, UPDATE or DELETE on them. The row-security policies (migration 503's among them) stay as the SECOND lock, and a test
module exists to measure that second lock by writing as a signed-in role. With the first lock in place every such write is
refused by the privilege ("permission denied for table") before a policy is asked, so the module would measure nothing and
report the refusal as if it were the policy's. Such a module calls `give_the_signed_in_writes_back` once its rows are seeded;
the privilege itself is measured by `test_509_*_pg.py`.

The rollback file is the source, so this cannot drift from what the migration took away. It is the same device as
`_signed_in_payroll_writes`, for the same reason.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROLLBACK = (Path(__file__).resolve().parents[1] / "migrations" /
             "509_a_signed_in_session_writes_none_of_the_workflow_tables_rollback.sql")


def rollback_sql() -> str:
    return _ROLLBACK.read_text(encoding="utf-8")


def give_the_signed_in_writes_back(dsn: str) -> None:
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=rollback_sql(), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

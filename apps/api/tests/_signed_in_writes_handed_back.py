"""Hand a signed-in session back the writes the closed list says it no longer holds, on the tables a test names, in a throwaway database.

POST-A-008's tranche migrations (595 onward) take INSERT, UPDATE and DELETE away from `authenticated` on the tables the API now writes
with its privileged client, and each table joins `tests/fixtures/tables_the_signed_in_role_cannot_write.txt` in the change whose migration
takes the write away. That privilege is the FIRST lock. The row policies and the triggers on those tables stay as the SECOND lock, and
several older test modules measure that second lock by writing as a signed-in role (a Manager assigned to the client, a portal client, a
member of another firm). With the first lock in place every such write is refused by the privilege before a policy or a trigger is asked,
so the module would measure nothing, or would read the privilege's refusal as the policy's.

Such a module calls `hand_back(dsn, tables)` on its throwaway copy, naming the tables it writes signed in. The helper grants back what each
tranche migration's rollback grants back (INSERT, UPDATE and DELETE to `authenticated`, or INSERT alone on a table 501 made append-only), on those of the named tables the closed list names,
and on nothing else: a table no migration has closed yet is left as it is, so the same call is right before and after the change that
closes it, and a module never needs a second edit when a later tranche closes another of its tables. It returns the tables it handed
back, so a module can assert it measured what it meant to. The first lock itself is measured by each migration's own file
(`test_595_...` onward) and by the general writer rule.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_CLOSED_LIST = Path(__file__).resolve().parent / "fixtures" / "tables_the_signed_in_role_cannot_write.txt"

# What a table's tranche rollback gives back when it is not INSERT, UPDATE and DELETE: migration 501 made a knowledge article's
# versions append-only (a signed-in session inserted and never rewrote or deleted one), so 606's rollback gives INSERT alone back.
_GIVEN_BACK = {"knowledge_article_versions": "INSERT"}


def closed_tables() -> frozenset[str]:
    """The tables the closed list names (comment lines and blanks skipped)."""
    return frozenset(ln.strip() for ln in _CLOSED_LIST.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))


def hand_back(dsn: str, tables) -> list[str]:
    """Grant `authenticated` what the tranche took (INSERT, UPDATE and DELETE, or `_GIVEN_BACK`'s narrower set) on each of `tables`
    the closed list names; return those, sorted."""
    given = sorted(set(tables) & closed_tables())
    if given:
        sql = "".join(f"GRANT {_GIVEN_BACK.get(t, 'INSERT, UPDATE, DELETE')} ON public.{t} TO authenticated; " for t in given)
        done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    return given

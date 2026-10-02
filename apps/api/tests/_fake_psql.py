"""A stand-in for `psql`, just faithful enough to watch the migration runner behave.

WHY IT EXISTS
    The runner (scripts/db/apply_migrations.py) shells out to psql, and what it is
    meant to guarantee -- a file that fails on its third statement leaves nothing
    behind, a failure it remembers keeps the run red -- is a property of how it
    CALLS psql and what it does with the answer. The real-Postgres tests prove the
    database half (tests/test_a_migration_is_atomic_pg.py) but are skipped without
    a server, which is the case for the ordinary mock-mode CI job and for a
    developer's machine. This is the half that needs no server: it records every
    invocation and models just two things a real psql does.

WHAT IT MODELS, AND ONLY THIS
    * the tracking tables (`schema_migrations`, `schema_migration_failures`) as a
      JSON file, so a second run sees what the first run recorded;
    * a migration's EFFECT as the statements before a line reading `FAIL_HERE;`
      that were COMMITTED: all of them when the call carried no transaction, none
      when it carried `--single-transaction` or the file opened its own BEGIN
      (psql exits on the first error with ON_ERROR_STOP, the connection closes and
      the server rolls the open transaction back).

    It does not parse SQL. A migration for these tests is a few lines, each ending
    in `;`, one of which may be `FAIL_HERE;`.

THE STATE FILE is named by FAKE_PSQL_STATE. `calls` records each invocation's
argument vector and standard input, so a test can assert on HOW psql was called.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

_SCRIPT = r'''#!{python}
import json, os, re, sys

state_path = os.environ["FAKE_PSQL_STATE"]
state = json.load(open(state_path))
argv = sys.argv[1:]
stdin = ""
if "-f" in argv and argv[argv.index("-f") + 1] == "-":
    stdin = sys.stdin.read()

def save():
    json.dump(state, open(state_path, "w"))

state["calls"].append({{"argv": argv, "stdin": stdin}})

if "-c" in argv:
    sql = argv[argv.index("-c") + 1]
    if sql.lstrip().startswith("SELECT filename, checksum FROM schema_migration_failures"):
        for fn, cs in state["failed"].items():
            print(fn + "|" + cs["checksum"])
    elif sql.lstrip().startswith("SELECT filename, checksum FROM schema_migrations"):
        for fn, cs in state["applied"].items():
            print(fn + "|" + cs)
    elif "INSERT INTO schema_migration_failures" in sql:
        m = re.search(r"VALUES \('([^']*)', '([^']*)'", sql)
        prev = state["failed"].get(m.group(1), {{"attempts": 0}})
        state["failed"][m.group(1)] = {{"checksum": m.group(2), "attempts": prev["attempts"] + 1}}
    elif "DELETE FROM schema_migration_failures" in sql:
        m = re.search(r"filename = '([^']*)'", sql)
        state["failed"].pop(m.group(1), None)
    save()
    sys.exit(0)

if stdin:
    wrapped = "--single-transaction" in argv
    statements = [s.strip() for s in stdin.split(";") if s.strip()]
    own_txn = any(s.upper().startswith(("BEGIN", "START TRANSACTION")) for s in statements)
    effects = []
    for s in statements:
        if s.startswith("INSERT INTO schema_migrations"):
            m = re.search(r"VALUES \('([^']*)', '([^']*)'", s)
            effects.append(("tracked", m.group(1), m.group(2)))
        elif s == "FAIL_HERE":
            if not (wrapped or own_txn):
                for e in effects:
                    if e[0] == "stmt":
                        state["committed"].append(e[1])
            sys.stderr.write("psql:<stdin>:3: ERROR:  boom at FAIL_HERE\n")
            save()
            sys.exit(3)
        else:
            effects.append(("stmt", s))
    for e in effects:
        if e[0] == "stmt":
            state["committed"].append(e[1])
        else:
            state["applied"][e[1]] = e[2]
    save()
    sys.exit(0)

save()
'''


def install(directory: Path) -> dict:
    """Write the fake into `directory` as `psql`, return the env a test needs."""
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / "psql"
    exe.write_text(_SCRIPT.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    state = directory / "state.json"
    state.write_text(json.dumps({"applied": {}, "failed": {}, "committed": [], "calls": []}))
    return {"PATH": f"{directory}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_PSQL_STATE": str(state)}


def read(env: dict) -> dict:
    return json.loads(Path(env["FAKE_PSQL_STATE"]).read_text())

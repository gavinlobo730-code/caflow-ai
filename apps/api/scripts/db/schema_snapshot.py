#!/usr/bin/env python3
"""
Introspect a database's public schema into a comparable snapshot.

WHY

Nothing in this repository compared the schema the MIGRATIONS declare with the
schema the LIVE DATABASE actually has, and the two have drifted. That gap is not
theoretical:

  * Migration 291 passed every local check and then failed against production
    with `column "status" does not exist`, because form_26as_uploads has a
    different shape there than migration 052 declares.

  * Before that, an audit read migration 052, concluded `uploaded_by` did not
    exist, and deleted the code that wrote it. That column DOES exist in
    production and is NOT NULL, so every 26AS upload has failed there since.
    The audit was careful; it just read the wrong source.

Both failures share one cause: the CI template is built FROM the migrations with
--continue-on-error, so every local run and both column checkers only ever see
what the migrations say. A migration can be green here and broken there, and the
only signal is a production failure after merge.

This script produces one side of the comparison. schema_drift.py compares two.

WHAT IT CAPTURES

Columns, their types, nullability and defaults, per table. Deliberately not
indexes, policies, functions or triggers: the failures above were all column
shape, and a diff that reports everything reports nothing.

USAGE

    python scripts/db/schema_snapshot.py --dsn "postgresql://..." > live.json

    # or against a template built from the migrations:
    python scripts/db/apply_migrations.py --dsn "$SCRATCH" --with-compat \
        --only-schema --continue-on-error
    python scripts/db/schema_snapshot.py --dsn "$SCRATCH" > declared.json

The SQL is exported as INTROSPECT_SQL so a caller that reaches its database
another way (the Supabase MCP tools, say) can run the identical query and get a
snapshot that compares cleanly.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

# One query, used for BOTH sides. If the two sides were introspected
# differently, the diff would report the difference in the questions rather than
# in the schemas.
INTROSPECT_SQL = """
SELECT json_agg(t ORDER BY t.table_name, t.column_name)
FROM (
  SELECT table_name, column_name, data_type, is_nullable,
         COALESCE(column_default, '') AS column_default
  FROM information_schema.columns
  WHERE table_schema = 'public'
) t;
"""


def snapshot_via_psql(dsn: str | None) -> list[dict]:
    cmd = ["psql"]
    if dsn:
        cmd.append(dsn)
    cmd += ["-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", INTROSPECT_SQL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"introspection failed: {res.stderr.strip()}")
    return json.loads(res.stdout.strip() or "[]")


def normalise(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """table -> column -> {type, nullable, default}, so the diff is by name.

    Ordinal position is deliberately dropped. Two databases that hold the same
    columns in a different order are not drifted in any way that can break a
    query, and reporting it would bury the differences that can.
    """
    out: dict[str, dict[str, dict]] = {}
    for r in rows or []:
        out.setdefault(r["table_name"], {})[r["column_name"]] = {
            "type": r["data_type"],
            "nullable": r["is_nullable"],
            "default": r.get("column_default") or "",
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", help="libpq DSN; omit to use PG* environment vars")
    args = ap.parse_args()
    print(json.dumps(normalise(snapshot_via_psql(args.dsn)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

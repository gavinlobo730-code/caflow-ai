#!/usr/bin/env python3
"""
Introspect the guards — RLS policies and table constraints — into a comparable
snapshot.

WHY THIS EXISTS SEPARATELY FROM schema_snapshot.py

That script compares COLUMNS, and says so: "deliberately not indexes, policies,
functions or triggers: the failures above were all column shape, and a diff that
reports everything reports nothing." That was the right call for the failures it
was written for. It is also a blind spot, and migration 293 walked into it.

Two things surfaced there, neither of which the column diff can see:

  * production has no client_timeline_events_client_id_fkey, a foreign key the
    migrations declare;
  * both RESTRICTIVE policies on that table had drifted from their declared
    form — production's were the pre-cast versions, because migrations 074/084
    are already recorded and never re-ran.

The second is the one that matters. A policy that is missing in production, or
that is PERMISSIVE there and RESTRICTIVE here, is a tenancy-isolation defect: a
restrictive policy is a check every row must pass, a permissive one is a grant
that widens access. Nothing in this repository would have reported either.

WHAT IT CAPTURES, AND WHY IT HASHES THE EXPRESSIONS

Identity and the security-relevant flags in full — table, policy name,
permissive vs restrictive, command, roles — and the USING / WITH CHECK
expressions as an md5 rather than as text.

That is not to hide them. It is because the expressions are the bulk of the
data: 539 policies and 1,034 constraints carry roughly 150 KB of SQL, and a
fixture nobody can read in a diff is a fixture nobody checks. The hash still
detects that an expression changed, which is all the assertion needs — the
question "is production's policy the one we declared?" is answered by equality,
and the moment the answer is no, a human has to read both anyway.

RLS-enabled is captured per table because a policy on a table with RLS switched
off is decoration.

USAGE

    python scripts/db/guard_snapshot.py --dsn "postgresql://..." > live_guards.json

GUARD_SQL is exported so a caller that reaches its database another way (the
Supabase MCP console, say) runs the identical query and gets a snapshot that
compares cleanly. Introspecting the two sides differently would diff the
questions rather than the schemas.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

GUARD_SQL = """
SELECT json_agg(g ORDER BY g.kind, g.tbl, g.name)
FROM (
  -- RLS switch, per table. A policy on a table with RLS off does nothing.
  SELECT 'rls'::text AS kind, c.relname::text AS tbl, ''::text AS name,
         CASE WHEN c.relrowsecurity THEN 'on' ELSE 'OFF' END AS detail,
         ''::text AS expr_md5
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind = 'r'

  UNION ALL

  -- Policies. `detail` carries what decides access: permissive vs restrictive,
  -- the command, and the roles. Roles are sorted so two databases that granted
  -- them in a different order do not read as drifted.
  --
  -- The expressions are hashed after folding `( SELECT auth.uid() AS uid)`
  -- back to `auth.uid()`. The two are the same predicate: the subselect form
  -- is Supabase's linter rewrite (it lets the planner evaluate the call once
  -- per statement rather than once per row), and migration 008 applied it to
  -- some policies while production has it on others. The first run of this
  -- snapshot reported five policies as drifted whose only difference was that
  -- rewrite. A real change to WHO a policy admits still changes the hash.
  SELECT 'policy', c.relname::text, p.polname::text,
         CASE WHEN p.polpermissive THEN 'permissive' ELSE 'RESTRICTIVE' END
           || ' cmd=' || p.polcmd::text
           || ' roles=' || COALESCE((
                SELECT string_agg(r.rolname::text, ',' ORDER BY r.rolname)
                FROM pg_roles r WHERE r.oid = ANY(p.polroles)), 'PUBLIC'),
         md5(regexp_replace(
               COALESCE(pg_get_expr(p.polqual, p.polrelid), '')
               || '|' || COALESCE(pg_get_expr(p.polwithcheck, p.polrelid), ''),
               '\\( SELECT (auth\\.[a-z_]+\\(\\)) AS [a-z_]+\\)', '\\1', 'g'))
  FROM pg_policy p
  JOIN pg_class c ON c.oid = p.polrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'

  UNION ALL

  -- Constraints. contype is the letter postgres uses: p primary key, u unique,
  -- f foreign key, c check, x exclusion. NOT NULL is not here — it is a column
  -- property and schema_snapshot.py already carries it.
  SELECT 'constraint', t.relname::text, con.conname::text,
         con.contype::text,
         md5(pg_get_constraintdef(con.oid))
  FROM pg_constraint con
  JOIN pg_class t ON t.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'public'
) g;
"""


def snapshot_via_psql(dsn: str | None) -> list[dict]:
    cmd = ["psql"]
    if dsn:
        cmd.append(dsn)
    cmd += ["-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", GUARD_SQL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"guard introspection failed: {res.stderr.strip()}")
    return json.loads(res.stdout.strip() or "[]")


def normalise(rows: list[dict]) -> dict[str, dict]:
    """kind -> "table.name" -> {detail, expr_md5}.

    One flat key per object so the diff is by identity. RLS rows have no name,
    so their key is the bare table.
    """
    out: dict[str, dict] = {"rls": {}, "policy": {}, "constraint": {}}
    for r in rows or []:
        key = r["tbl"] if r["kind"] == "rls" else f"{r['tbl']}.{r['name']}"
        out.setdefault(r["kind"], {})[key] = {
            "detail": r["detail"],
            "expr_md5": r["expr_md5"],
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

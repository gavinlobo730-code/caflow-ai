#!/usr/bin/env python3
"""
Compare the GUARDS the migrations declare against the guards a database has.

schema_drift.py compares columns and says so. This is its twin for the other
half of a schema — row-level security, policies and constraints — and it
exists because migration 293 found two things the column diff could not see:
production had no client_timeline_events_client_id_fkey, and two RESTRICTIVE
policies there had drifted from their declared form. Neither is a column.

Reads two snapshots from guard_snapshot.py and reports, most dangerous first:

  * a table with RLS switched OFF in the live database — every policy on it
    is decoration and the direct PostgREST path sees every firm's rows
  * a RESTRICTIVE policy the migrations declare that the live database lacks —
    a restrictive policy is a check every row must pass, so its absence widens
    what a caller can reach
  * a table the migrations give policies and the live database gives none —
    with RLS on that is fail-closed, so the frontend's direct reads of it
    return nothing, silently
  * a CHECK constraint whose expression differs — production accepting a
    value the migrations refuse is harmless; production REFUSING a value the
    migrations accept means code that passes every test here is rejected
    there. clients_status_check was exactly this: migration 042 added
    'archived', production never got it, and archiving a client failed in
    production while the suite stayed green
  * a UNIQUE constraint the migrations declare that the live database lacks —
    an upsert written against it fails there with "no unique or exclusion
    constraint matching the ON CONFLICT specification"

and then, informationally, every policy or constraint present on one side
only or differing in kind, roles or expression.

WHAT IT DOES NOT COMPARE

Grants, functions, triggers, indexes that are not constraints. A policy's
roles and expression are compared; its expression is a hash, so "differs" is
all this can say about one, and a human reads both.

USAGE

    python scripts/db/guard_drift.py declared.json live.json
    python scripts/db/guard_drift.py declared.json live.json --json

Exit code is 1 when any difference is found, so it can gate a job.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Tables that live in the database but are not (and should not be) declared by
# any migration in this repository — the migration runner's own bookkeeping.
NOT_OURS = {"schema_migrations", "schema_migration_failures"}


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _table_of(key: str) -> str:
    return key.split(".", 1)[0]


def diff_guards(declared: dict, live: dict) -> dict:
    """Both arguments are guard_snapshot.normalise() output:
    {"rls": {table: {...}}, "policy": {"table.name": {...}},
     "constraint": {"table.name": {...}}}.
    """
    out: dict[str, list] = {
        "rls_off_in_live": [],
        "restrictive_policies_missing_from_live": [],
        "tables_left_without_a_policy_in_live": [],
        "check_constraints_differ": [],
        "unique_constraints_missing_from_live": [],
        "tables_missing_from_live": [],
        "tables_only_in_live": [],
        "policies_missing_from_live": [],
        "policies_only_in_live": [],
        "policies_differ": [],
        "constraints_missing_from_live": [],
        "constraints_only_in_live": [],
        "constraints_differ": [],
    }
    d_rls, l_rls = declared.get("rls", {}), live.get("rls", {})
    d_pol, l_pol = declared.get("policy", {}), live.get("policy", {})
    d_con, l_con = declared.get("constraint", {}), live.get("constraint", {})

    # ── Tables. A policy or constraint on a table the other side lacks is not
    #    separately reported: the missing table is the finding.
    both: set[str] = set()
    for table in sorted((set(d_rls) | set(l_rls)) - NOT_OURS):
        if table in d_rls and table not in l_rls:
            out["tables_missing_from_live"].append(table)
        elif table in l_rls and table not in d_rls:
            out["tables_only_in_live"].append(table)
        else:
            both.add(table)
            if l_rls[table]["detail"] != "on":
                out["rls_off_in_live"].append(table)

    # ── Policies.
    d_by_table: dict[str, int] = {}
    l_by_table: dict[str, int] = {}
    for k in d_pol:
        d_by_table[_table_of(k)] = d_by_table.get(_table_of(k), 0) + 1
    for k in l_pol:
        l_by_table[_table_of(k)] = l_by_table.get(_table_of(k), 0) + 1
    for table in sorted(both):
        if d_by_table.get(table, 0) and not l_by_table.get(table, 0):
            out["tables_left_without_a_policy_in_live"].append(table)

    for key in sorted(set(d_pol) | set(l_pol)):
        if _table_of(key) not in both:
            continue
        d, l = d_pol.get(key), l_pol.get(key)
        if d and not l:
            out["policies_missing_from_live"].append(f"{key}  [{d['detail']}]")
            if d["detail"].startswith("RESTRICTIVE"):
                out["restrictive_policies_missing_from_live"].append(key)
        elif l and not d:
            out["policies_only_in_live"].append(f"{key}  [{l['detail']}]")
        elif d["detail"] != l["detail"]:
            out["policies_differ"].append(
                f"{key}: migrations say {d['detail']}, live says {l['detail']}")
        elif d["expr_md5"] != l["expr_md5"]:
            out["policies_differ"].append(f"{key}: USING / WITH CHECK expression differs")

    # ── Constraints. `detail` is the contype letter: p, u, f, c, x.
    for key in sorted(set(d_con) | set(l_con)):
        if _table_of(key) not in both:
            continue
        d, l = d_con.get(key), l_con.get(key)
        if d and not l:
            out["constraints_missing_from_live"].append(f"{key}  [{d['detail']}]")
            if d["detail"] == "u":
                out["unique_constraints_missing_from_live"].append(key)
        elif l and not d:
            out["constraints_only_in_live"].append(f"{key}  [{l['detail']}]")
        elif d["detail"] != l["detail"]:
            out["constraints_differ"].append(
                f"{key}: migrations say type {d['detail']}, live says {l['detail']}")
        elif d["expr_md5"] != l["expr_md5"]:
            if d["detail"] == "c":
                out["check_constraints_differ"].append(key)
            else:
                out["constraints_differ"].append(f"{key}: definition differs")
    return out


# Every key diff_guards() produces must appear here, or it is silently dropped
# from the report. tests/test_guard_drift.py asserts the two stay in step.
HEADINGS = {
    "rls_off_in_live":
        "Row-level security is OFF in the live database — every policy on the "
        "table is decoration and the direct PostgREST path sees every firm",
    "restrictive_policies_missing_from_live":
        "RESTRICTIVE policies the migrations declare that the live database lacks "
        "— a check every row must pass is not being applied",
    "tables_left_without_a_policy_in_live":
        "Tables the migrations give policies and the live database gives NONE — "
        "RLS is on, so the frontend's direct reads return nothing",
    "check_constraints_differ":
        "CHECK constraints whose expression differs — a value the migrations accept "
        "may be REJECTED in production while every test here passes",
    "unique_constraints_missing_from_live":
        "UNIQUE constraints the migrations declare that the live database lacks — "
        "an upsert written against one fails there",
    "tables_missing_from_live": "Tables the migrations declare that the live database does not have",
    "tables_only_in_live": "Tables in the live database that no migration declares",
    "policies_missing_from_live": "Policies the migrations declare that the live database does not have",
    "policies_only_in_live": "Policies in the live database that no migration declares",
    "policies_differ": "Policies whose kind, command, roles or expression differ",
    "constraints_missing_from_live": "Constraints the migrations declare that the live database does not have",
    "constraints_only_in_live": "Constraints in the live database that no migration declares",
    "constraints_differ": "Constraints whose type or definition differs",
}


def render(report: dict) -> str:
    lines: list[str] = []
    for key, heading in HEADINGS.items():
        items = report[key]
        if not items:
            continue
        lines.append(f"\n{heading}  ({len(items)})")
        lines.append("-" * min(len(heading), 78))
        lines.extend(f"  {i}" for i in items)
    if not lines:
        return ("No drift. The migrations and the live database agree on every "
                "RLS switch, policy and constraint.")
    total = sum(len(v) for v in report.values())
    lines.append(f"\n{total} difference(s).")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("declared", help="guard snapshot of a database built from the migrations")
    ap.add_argument("live", help="guard snapshot of the real database")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    report = diff_guards(load(args.declared), load(args.live))
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

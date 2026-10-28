#!/usr/bin/env python3
"""
Compare what the migrations declare against what a database actually has.

Reads two snapshots from schema_snapshot.py and reports the differences that
can break code:

  * a table the migrations declare that the database does not have
  * a table the database has that no migration declares
  * a column missing on one side
  * a column whose NULLABILITY differs — the one that bit hardest, because a
    NOT NULL column absent from the migrations is invisible to every check here
    and rejects every insert there
  * a column whose TYPE differs
  * a column whose DEFAULT differs, in the two ways that matter: the migrations give a NOT NULL column a default production does
    not have (an insert written from the migrations is rejected there), and both give one and the VALUES differ

Ordering, indexes, policies and functions are not compared. The failures this
exists for were all column shape, and a diff that reports everything reports
nothing.

WHY IT MATTERS, CONCRETELY

form_26as_uploads holds `uploaded_by NOT NULL` in production and does not have
it in migration 052. An audit read the migration, concluded the column did not
exist, and removed the code that wrote it — so every 26AS upload has failed in
production ever since, silently, while every test passed. This diff is what
would have shown that in one line.

USAGE

    python scripts/db/schema_drift.py declared.json live.json
    python scripts/db/schema_drift.py declared.json live.json --json
    python scripts/db/schema_drift.py declared.json live.json --table customers

Exit code is 1 when any difference is found, so it can gate a job.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Tables that live in the database but are not (and should not be) declared by
# any migration in this repository. Listing them keeps "extra in live" as a
# meaningful signal rather than permanent noise.
NOT_OURS = {
    "schema_migrations",   # written by scripts/db/apply_migrations.py itself
}


# Two spellings of one default are not drift. A default is compared after its casts are dropped (`'info'::text` and
# `'info'::event_severity` are one default) and with the two UUID functions read as one, because the snapshot stores the
# expression text and that text is the only thing that differs.
_CAST = re.compile(r"::[a-z_][a-z0-9_ ]*(\[\])?")
_UUID_FUNCTIONS = {"uuid_generate_v4()": "gen_random_uuid()"}


def normalised_default(expression: str) -> str:
    text = _CAST.sub("", (expression or "").strip()).strip()
    return _UUID_FUNCTIONS.get(text, text)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff(declared: dict, live: dict) -> dict:
    out: dict[str, list] = {
        # THE ONE THAT BITES. A column production demands with no default, that
        # the migrations do not mark required — code written from the
        # migrations omits it and every insert is rejected there while every
        # check here passes. form_26as_uploads.uploaded_by was exactly this,
        # and no 26AS upload had ever succeeded in production because of it.
        "live_requires_but_migrations_do_not": [],
        "tables_missing_from_live": [],
        "tables_only_in_live": [],
        "columns_missing_from_live": [],
        "columns_only_in_live": [],
        "nullability_differs": [],
        "type_differs": [],
        # THE MIRROR OF THE FIRST KEY. The migrations give a column a default and production, where it is NOT NULL, has none: code
        # written from the migrations omits the column and the insert is rejected there while every check here passes.
        "live_lacks_a_default_the_migrations_give": [],
        # Both give a default and the values differ (casts and the two UUID functions are not a difference): a row that omits the
        # column stores one thing here and another there.
        "default_value_differs": [],
    }

    for table in sorted(set(declared) | set(live)):
        if table in NOT_OURS:
            continue
        d_cols, l_cols = declared.get(table), live.get(table)
        if d_cols is not None and l_cols is None:
            out["tables_missing_from_live"].append(table)
            continue
        if l_cols is not None and d_cols is None:
            out["tables_only_in_live"].append(table)
            continue

        for col in sorted(set(d_cols) | set(l_cols)):
            d, l = d_cols.get(col), l_cols.get(col)
            if d and not l:
                out["columns_missing_from_live"].append(f"{table}.{col}")
            elif l and not d:
                if l["nullable"] == "NO" and not l["default"]:
                    out["live_requires_but_migrations_do_not"].append(f"{table}.{col}")
                # The dangerous direction. A NOT NULL column no migration
                # declares rejects every insert that does not name it, while
                # every check in this repo says the column does not exist.
                out["columns_only_in_live"].append(
                    f"{table}.{col}" + ("  [NOT NULL]" if l["nullable"] == "NO" else ""))
            else:
                if (d["nullable"] == "YES" and l["nullable"] == "NO"
                        and not l["default"]):
                    out["live_requires_but_migrations_do_not"].append(f"{table}.{col}")
                elif d["nullable"] != l["nullable"]:
                    out["nullability_differs"].append(
                        f"{table}.{col}: migrations say nullable={d['nullable']}, "
                        f"live says {l['nullable']}")
                if d["type"] != l["type"]:
                    out["type_differs"].append(
                        f"{table}.{col}: migrations say {d['type']}, live says {l['type']}")
                if d["default"] and not l["default"] and l["nullable"] == "NO":
                    out["live_lacks_a_default_the_migrations_give"].append(f"{table}.{col}")
                elif (d["default"] and l["default"]
                      and normalised_default(d["default"]) != normalised_default(l["default"])):
                    out["default_value_differs"].append(
                        f"{table}.{col}: migrations say {d['default']}, live says {l['default']}")
    return out


# Every key diff() produces must appear here, or it is silently dropped from
# the report. tests/test_schema_drift.py asserts the two stay in step.
HEADINGS = {
    "live_requires_but_migrations_do_not":
        "REQUIRED in the live database, not required by the migrations — "
        "an insert written from the migrations is REJECTED in production",
    "tables_missing_from_live": "Tables the migrations declare that the live database does not have",
    "tables_only_in_live": "Tables in the live database that no migration declares",
    "columns_missing_from_live": "Columns the migrations declare that the live database does not have",
    "columns_only_in_live": "Columns in the live database that no migration declares",
    "nullability_differs": "Columns whose NULLABILITY differs",
    "type_differs": "Columns whose TYPE differs",
    "live_lacks_a_default_the_migrations_give":
        "NOT NULL in the live database with NO default, where the migrations give one — "
        "an insert written from the migrations is REJECTED in production",
    "default_value_differs": "Columns whose DEFAULT VALUE differs",
}


def render(report: dict) -> str:
    lines: list[str] = []
    for key, heading in HEADINGS.items():
        items = report[key]
        if not items:
            continue
        lines.append(f"\n{heading}  ({len(items)})")
        lines.append("-" * len(heading))
        lines.extend(f"  {i}" for i in items)
    if not lines:
        return "No drift. The migrations and the live database agree on every table and column."
    total = sum(len(v) for v in report.values())
    lines.append(f"\n{total} difference(s).")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("declared", help="snapshot of a database built from the migrations")
    ap.add_argument("live", help="snapshot of the real database")
    ap.add_argument("--table", help="limit the comparison to one table")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    declared, live = load(args.declared), load(args.live)
    if args.table:
        declared = {k: v for k, v in declared.items() if k == args.table}
        live = {k: v for k, v in live.items() if k == args.table}

    report = diff(declared, live)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

# production_schema_2026-08-31.json

A point-in-time capture of the live database's `public` schema — every column,
its type, nullability and default — taken on 31 August 2026 with the query
`scripts/db/schema_snapshot.py` exports as `INTROSPECT_SQL`.

`test_schema_matches_production_pg.py` compares a database built from the
migrations against it, and fails if any column is REQUIRED in production while
the migrations call it optional. That is the direction that has caused real
damage: code written from the migrations omits the column, passes every check
here, and has every insert rejected there.

## It is a snapshot, and it goes stale

Deliberately. It records what production looked like on one day, so the check
runs in CI without production credentials. A column added to production
out-of-band after that date is invisible to it.

Refresh it by re-running the introspection against the live database and
replacing this file in a commit of its own, so the diff shows what moved in
production rather than burying it inside a feature change. `docs/schema-drift.md`
has the commands.

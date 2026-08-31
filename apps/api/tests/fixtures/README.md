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

## Refreshed 31 August 2026, after migration 293

293 converged the seventeen columns whose TYPE differed between the migrations
and production. Ten of them changed on production's side, so this file went
stale the moment it applied.

It was refreshed WITHOUT a full re-capture, because this session had no direct
libpq route to production — only a SQL console. Editing a snapshot by hand is
normally the wrong thing to do, so the edit was made and then PROVED equivalent
to a re-capture rather than trusted:

    -- in production
    SELECT md5(string_agg(
             table_name||'|'||column_name||'|'||data_type||'|'||is_nullable
             ||'|'||COALESCE(column_default,''),
             E'\n' ORDER BY table_name, column_name))
    FROM information_schema.columns WHERE table_schema = 'public';

The same string was built from this file and hashed the same way. Both sides:
f8a3570e1c53c5f6772673509536cd39, over 3,606 columns in 249 tables. That covers
every column, not only the ten touched, so an unrelated change made in
production out-of-band would have shown up as a mismatch.

Prefer a real re-capture when a libpq DSN is available. Use this route only
where one is not, and only with the checksum shown — an unverified hand edit to
this file would silently weaken every assertion that reads it.

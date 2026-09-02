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

## Refreshed again, 31 August 2026, after migration 294

294 added the 31 columns the migrations declared and production did not have —
the drift category this file's own check had, wrongly, treated as harmless. Four
features were failing in production because of them; see
test_schema_matches_production_pg.py's docstring.

Same route as the 293 refresh and the same proof: the 31 entries were copied
from the migration-built template (294 made production match it), then the whole
file was hashed against production the same way. Both sides
28b0a6f294089a9c269c198cb053eedd, over 3,637 columns in 249 tables — 3,606 + 31.

columns_missing_from_live is now asserted, and went 32 -> 1. The survivor is
clients_external.is_test: clients_external is a VIEW on both sides whose two
definitions select different columns. The assertion excludes views by asking the
database which relations are views, never by naming them, so a table cannot fall
through it.

# production_guards_2026-09-03.json

The same idea for the OTHER half of a schema: every table's RLS switch, every
policy (kind, command, roles, and an md5 of its USING / WITH CHECK), and every
constraint (type and an md5 of its definition), captured from production at
02:15 IST on 3 September 2026 with `scripts/db/guard_snapshot.py`'s
`GUARD_SQL`. 257 tables, 597 policies, 1,116 constraints.

`test_guards_match_production_pg.py` compares a database built from the
migrations against it and fails on the four directions that break something:
RLS off in production, a RESTRICTIVE policy missing there, a table with declared
policies and none there, and a CHECK constraint admitting different values
there. The first run's findings, and what migration 316 did about them, are in
`docs/audits/2026-09-03-guard-drift-first-run.md`.

## It was assembled from six SQL-console slices, and proved equal to one capture

This session had no libpq route to production, so the rows were pulled through
the Supabase SQL console in six pieces (RLS; policies split at `m`; constraints
split at `f` and `p`) and normalised with the same `normalise()` the script
uses. That is a hand assembly, so it was proved rather than trusted: production
was asked for

    md5(string_agg(kind||'|'||tbl||'|'||name||'|'||detail||'|'||expr_md5,
                   E'\n' ORDER BY kind, tbl, name))

over `GUARD_SQL`'s rows, and the same string was built from this file. Both
sides: `4815504f83ec550027c05bfd2b41cd2e` over 1,970 rows. The hash is recorded
in the `.meta.json` as `guards_md5` so the next refresh can be checked the same
way.

## The hash folds one rewrite out

Production carries `( SELECT auth.uid() AS uid)` in some policy expressions
where the migrations carry `auth.uid()` — the Supabase linter's initplan
rewrite, same predicate. `GUARD_SQL` folds it back before hashing, on both
sides, so a refresh taken with an older `GUARD_SQL` would NOT compare cleanly.
Always capture with the query the script exports today.

## Refreshing

Same rules as the schema fixture: re-run `GUARD_SQL` against production
(`python3 scripts/db/guard_snapshot.py --dsn "$PRODUCTION_DSN"`, or the console
route above with its checksum), replace both files in a commit of their own,
and set `applied_through_migration` to production's `max(filename)` in
`schema_migrations` at that moment. The PG test excuses guards named by
migrations above that mark — and refuses to run if the repository is more than
ten migrations ahead of it, so a stale fixture cannot quietly excuse a
regression.

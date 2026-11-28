# Production migration auto-apply (task #244)

## What this is

`.github/workflows/backend-ci.yml`'s `deploy-migrations` job runs
`apps/api/scripts/db/apply_migrations.py` against the real production
Supabase database on every push to `main`, once tests and the migration-apply
ratchet both pass. It applies any migration in `apps/api/migrations/` that
isn't already recorded in production's `schema_migrations` tracking table —
idempotent, ordered, fails fast on the first error.

This closes the gap that let migrations 233–241 sit committed (and
CI-validated against a *throwaway* Postgres) but unapplied to the *real*
database for up to 6 days, while the application code that depended on them
was already live on Render and silently failing behind broad `try/except`
handlers. See `apps/api/core/schema_guard.py` for the runtime backstop this
pairs with.

## One-time setup required

The job needs a `SUPABASE_DB_URL` repository secret — a direct Postgres
connection string with permission to run DDL (`ALTER TABLE`, `CREATE
FUNCTION`, etc). Until this secret is added, the job fails loudly with a
clear message instead of silently skipping.

**To add it:**

1. In the Supabase dashboard, open the `caflow-ai` project → **Project
   Settings → Database → Connection string**.
2. Choose the **URI** format, **Session pooler** (not Transaction pooler —
   DDL statements need a session-scoped connection). It looks like:
   `postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-0-xxxx.pooler.supabase.com:5432/postgres`
3. Replace `[YOUR-PASSWORD]` with the actual database password (Project
   Settings → Database → reset if you don't have it saved).
4. In GitHub: repo → **Settings → Secrets and variables → Actions → New
   repository secret**. Name: `SUPABASE_DB_URL`. Value: the full connection
   string from step 3.

That's it — the next push to `main` will pick it up automatically.

## What this means going forward

Once the secret is set, **every migration merged to `main` applies to
production automatically, with no manual review step in between.** This
trades the old "someone remembers to run it by hand" process (which failed
silently for days) for full automation. If a migration is ever wrong, the
job fails the push immediately and loudly (visible in the Actions tab) rather
than corrupting data quietly — but it does mean a bad migration reaches
production the moment it's merged, same as application code already does.

## How one migration is applied, and what a failure leaves behind

Written for ops-16. `apps/api/scripts/db/apply_migrations.py` is the runner; its module
docstring is the authority and this is the version for a person reading a red run.

**Each file runs in ONE transaction**, with its `schema_migrations` row inside it
(`psql --single-transaction`). A migration that fails on its third statement therefore
leaves nothing behind: not the first two statements, and not a tracking row. Before this
the first two were already committed, on the live database, for good — and because a
failure is remembered and not retried, they stayed.

**A file is NOT wrapped, and is reported as such (`not_atomic` in `--json`), when:**

| reason | why a wrapper would be wrong |
|---|---|
| it carries its own `BEGIN`/`COMMIT` (109 existing files do) | a second `BEGIN` is a warning, and the file's `COMMIT` would end the runner's transaction early |
| it uses `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER TYPE ... ADD VALUE`, … | PostgreSQL refuses it inside a transaction block (or, for `ADD VALUE`, forbids using the new value before the block ends) |
| it contains a line `-- migration: no-transaction` followed by the reason | for what the scanner cannot see, such as a `DO` block that `COMMIT`s. **Only in a NEW file** — an applied migration is never edited (see below) |
| it is one of the ten files in `BASELINE_FAILURES` | they fail on a fresh database and commit what precedes the failure; the rest of the schema build was written against that, so they keep the legacy behaviour until each is fixed |

The scanner reads the file the way the server does — comments, string literals and
`$$ … $$` bodies are blanked first — so the `BEGIN … END;` of a plpgsql function is not
mistaken for transaction control. `python scripts/db/apply_migrations.py --dry-run --json`
shows how each pending file would run before you merge.

**A migration can say something to whoever reads the run.** psql runs with
`client_min_messages=warning` and a clean run's output is discarded, so a `RAISE NOTICE` in
a migration is never seen. A migration that has a fact to report (migration 530 counts the
access rows that name a member or a client of another firm than their own, and deletes
none) writes `RAISE WARNING 'migration NNN: ...'`. The runner keeps those lines and only
those (Postgres's own warnings are not), and shows them as `messages` in `--json`, as a
`NOTE` line in the text report, and as a notice annotation on the run's summary page under
Actions.

**An applied migration is never edited, not even a comment, and two locks hold it.** The runner compares each file's checksum
with the one the database recorded. For a file that FAILED, a new checksum is the retry. For a file that APPLIED, the runner used to
do the same thing, and a second run of old SQL over a database every later migration has changed puts back what the file defined
and undoes each later change to the same object. On 27 November 2026 a rename sweep rewrote test names in the comments of eight
applied migrations, six ran again in production, and the ledger posting function went back to its September body until migration
786 restored it (the record is in `docs/design-record/engineering-and-ci.md`).

1. **The edit does not merge.** `tests/test_an_applied_migration_is_never_edited.py` holds every migration to the checksum listed
   in `tests/fixtures/migration_checksums.txt`. **A new migration adds its line with
   `python3 scripts/db/freeze_migration_checksums.py`** (from `apps/api`); the script never rewrites an existing line by itself. If
   the test names a file you did not mean to change, put the file back.
2. **The runner does not run it.** A file recorded in `schema_migrations` at another checksum is left alone, named
   (`changed_after_apply` in `--json`, an error annotation under Actions), and the run **exits non-zero** until the file is put
   back. It still applies whatever else is pending. To run one such file again on purpose, name it:
   `--reapply-changed NNN_name.sql`, one file at a time; a success records the new checksum. There is deliberately no switch that
   lets every changed file through.

**A failure is remembered, and a remembered failure keeps the run red.** A file that fails
is recorded in `schema_migration_failures` at its checksum and is not attempted again. The
next run skips it, still applies what else is pending, and **exits non-zero** with an error
annotation naming the file — it no longer goes green with the change unapplied. The ten
baseline files are the one exception: a remembered failure of one of those does not turn the
run red (in production they are recorded as applied and never reach the check at all).

To clear a remembered failure:

1. **Fix the file in a new commit.** Its checksum changes, so it runs again, and a success
   removes the row. This is the normal path. (Never edit a migration production has already
   applied; that is a different file and a different problem.)
2. **Or `--retry-failed`**, to attempt every remembered failure once more without a code change
   — for a failure that was the environment's (a lock timeout, a dropped connection).
3. **Or the migration was applied by hand** (the Supabase SQL editor): record that fact where
   the runner looks, in one transaction, so the next run sees it as applied:

   ```sql
   BEGIN;
   INSERT INTO schema_migrations(filename, checksum) VALUES ('NNN_name.sql', '<sha256 of the file>')
     ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum, applied_at = now();
   DELETE FROM schema_migration_failures WHERE filename = 'NNN_name.sql';
   COMMIT;
   ```

   The checksum is `sha256sum apps/api/migrations/NNN_name.sql`. Do this only after checking the
   change really is in the database; the row is a claim that it is.

**What the wrapper costs, stated plainly.** A transaction holds every lock it takes until it
ends. A migration that alters several busy tables used to release each table's lock as soon as
its statement finished; now they are held together, so a migration touching `journal_lines` and
three other hot tables waits for all four and blocks writers to the first while it waits for the
last. Keep a migration that touches hot tables short and few in statements, or split it.

**Not run where this was written.** The environment that built this change had no Postgres, so the
real-database proof (`tests/test_a_migration_is_atomic_pg.py`) is first executed by the
`migration apply — real Postgres 16` job, which also builds the whole schema through the wrapper.

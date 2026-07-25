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

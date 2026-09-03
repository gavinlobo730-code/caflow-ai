# Three writes production refuses

*3 September 2026. All three found by the guard comparison migration 316 added —
the first check in this repository able to see a constraint that exists in
production and in no migration. None was visible to any test.*

Each has the same shape: **the shipped code writes a value the live database
rejects, and the rejection is swallowed rather than surfaced.** They are not
schema tidiness. Each one breaks a feature for a real user, silently.

## 1. Every client-portal document upload fails

`apps/web/app/client-portal/page.tsx` set, on every `client_documents` insert:

```js
uploaded_by: userSession?.session?.user?.id ?? null,
```

`client_documents.uploaded_by` is a foreign key to `public.users(id)` — the
**internal** id of a firm user. The value to hand is the Supabase **auth** id.
The two are never equal: in production, 0 of 2 users have `id = auth_user_id`.
So the insert violates the foreign key and the upload fails.

There was no correct value to write, which is the more interesting half. A
portal uploader is the **client**, and a client has no `public.users` row at
all — the link is `clients.portal_user_id`, which holds an auth id (verified:
of the one client with a portal user, its `portal_user_id` matches a
`users.auth_user_id` and no `users.id`). The column can only name a firm user.

The fix is to stop writing it. `client_id` already carries the attribution, and
the CA-side upload page (`app/clients/[id]/documents/page.tsx`) omits the column
for the same reason.

This is the **third** instance of one pattern — an auth id written into a column
that keys the internal user table. The first two were backend (the year-end
review trail, fixed by migration 315). This one is in the frontend, which is a
static export talking to PostgREST directly, so the backend scan added with the
first fix could never have seen it.
`tests/test_frontend_never_writes_an_auth_id_into_a_users_fk_pg.py` now asserts
the same rule over `apps/web`, reading the foreign-key list from the schema so a
new one is covered without editing the test.

## 2. A partially-failed GST portal sync 500s with a raw database error

`domain/gst/portal_service.py:179` sets `status = 'partial_failure'` when some
snapshots of a sync succeeded and others failed. It was added deliberately —
its own comment ("A per-snap_type fetch failure must not be silently swallowed
into a blanket completed"), its own display branch in
`routers/gst_portal.py:103`, three tests pinning it.

Production's CHECK on `gst_sync_jobs.status` was created with the table in
Supabase Studio **before** that status existed and admits only
`pending | running | completed | error`. Every such UPDATE has been rejected
there since.

The consequence is worse than a lost status. The raise lands in the `except` at
`:191`, which overwrites the status with `'error'`, stores the Postgres
constraint text as `error_message` and re-raises; the router turns that into
HTTP 500. So the CA sees a total failure and a raw database error,
`completed_at` is never set and `snapshots_created` stays 0 — **even though the
snapshots were written**.

Here the constraint is what is wrong, so migration 318 widens it. That makes 318
the one real DDL change in this series rather than a no-op.

No test caught it because `tests/test_r239_gst_computation_gaps.py` runs the
path against an in-memory `FakeDB`, which has no constraints.

## 3. A crashed Tally import sits at `importing` for ever

`domain/tally/migration_service.py`'s detached-import failure handler wrote
`status = 'failed'`. Production's CHECK admits ten values and `'failed'` is not
one of them; the codebase's own frontend
(`apps/web/app/migration/page.tsx:27-36`) has no `failed` branch either.
Production and the UI both speak `'error'`.

So the UPDATE was refused, and the refusal was caught by the inner
`except Exception` that only logs "Could not even mark job %s failed". The
result is exactly what the handler's docstring says it exists to prevent: a
crashed import stays at `'importing'` with nobody told why. The router's
docstring documented the wrong vocabulary too.

Fixed in the code, not the constraint — the constraint agrees with the frontend.

### A default that drifted, found alongside it

`migrations/156_missing_tables_f5.sql:435` declares
`tally_migration_jobs.status NOT NULL DEFAULT 'pending'`; production's default
is `'uploaded'`. `create_migration_job` omits `status` and lets the default
decide, so the two databases disagreed about a new job's status — and
`'pending'` is not among the ten production admits, so declaring production's
CHECK would have broken every job creation locally until the default agreed.

**No check in this repository compares defaults.**
`test_schema_matches_production_pg.py` asserts presence, nullability and type
only, which is why this was invisible from both sides. Migration 318 converges
it; extending the column diff to defaults is worth doing and is not done here.

## The guard that generalises them

`tests/test_status_vocabularies_pg.py` reads every enum-shaped CHECK out of the
migration-built schema and asserts that each literal the backend writes to those
columns is admitted. The vocabulary comes from the database, so it cannot drift
from what is enforced; the literals come from source, so a new status added in
code fails here rather than in production.

Getting it to a usable state took three passes, and the failures are worth
recording because each was a false positive, which is the failure mode that
makes a check like this get deleted:

1. **A window after each `.table(…)` call.** One write got attributed to every
   table whose call appeared within 1,200 characters, inventing offenders like
   `clients.status = 'completed'`.
2. **Nearest preceding call only.** Better, but it still read
   `return {"status": "not_filed", …}` in `gst_exception_service.py` — a
   function's response contract, not a column value.
3. **Only `.insert({…})` / `.update({…})` payloads, delimited by balanced
   braces, with the lookahead stopped at the next `.table(` call.** Without
   that last bound, `.insert(rows)` taking a variable fell through to the
   following statement's payload.

What it still cannot see: a value held in a variable, and a payload built in one
file while the table is named in another — the repository pattern. It is a
floor, not a ceiling, and it says so.

## What is still open

* **The column diff does not compare defaults.** One instance found here; there
  may be others.
* **`documents` and `client_documents` are parallel tables.** The frontend
  writes `client_documents`; `routers/documents.py` writes `documents` through
  `document_repo`. `documents.uploaded_by` foreign-keys `team_members(id)`, a
  table with **zero rows in production**, and the router writes an auth id into
  it — so those writes cannot succeed either. Which of the two tables is meant
  to survive is a design question, not a bug fix, and is left alone here.
* **The backend FK scan is blind to the repository pattern.** It requires the
  payload and the literal `.table("…")` in one file within 1,500 characters, so
  a router that builds a payload and hands it to a repository is invisible.
  That is how the `documents` case above escaped it.

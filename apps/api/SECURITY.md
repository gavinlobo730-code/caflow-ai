# PracticeSync AI — Tenant Isolation & Security Model

## Current model (production today)

The FastAPI backend connects to Supabase with the **service_role** key
(`apps/api/core/supabase_client.py`). The service_role key **bypasses
Row-Level Security (RLS)** at the database level.

Tenant (firm) isolation is therefore enforced **at the application layer**:

1. Every request resolves `firm_id` from the authenticated user
   (`current_user["firm_id"]`, derived from the verified JWT).
2. Every list query passes `firm_id` into the repository
   (`.eq("firm_id", firm_id)`).
3. Every by-id lookup either:
   - passes `firm_id` into the repository so the query itself is scoped
     (e.g. `client_repo.find_by_id(client_id, firm_id)`), **and/or**
   - is followed by `_assert_firm(row, firm_id)` in the router.

Defense-in-depth: `find_by_id` now accepts an optional `firm_id`. When
supplied, a row belonging to another firm is returned as `None` — so a single
forgotten `_assert_firm` can no longer leak a cross-firm record on the
client lookup path.

## Defense-in-depth layer (ready, not yet enforced)

`apps/api/migrations/071_rls_policies.sql` defines RLS policies for the
Phase 10–13 tables of the form:

```sql
USING (firm_id::text = (auth.jwt() ->> 'firm_id'))
```

These policies are **inert while the backend uses service_role** (service_role
bypasses RLS). They become the real DB-level safety net only once
client-facing requests use the **anon key + the end-user JWT**.

## Migration path to anon key + JWT (deferred — high risk, requires a live DB to test)

Switching client-facing requests from service_role to anon+JWT is the correct
long-term hardening, but it is a cross-cutting change that touches every
router and repository and **cannot be validated without a live Supabase
instance**. It is intentionally deferred to a focused, testable effort.

When undertaken, the work is roughly:

1. Add a per-request Supabase client built from the **anon key** + the
   caller's `Authorization: Bearer <jwt>` so `auth.jwt()` resolves inside
   Postgres and RLS applies.
2. Thread that per-request client through the repository layer (replace the
   `get_supabase()` singleton for client-facing paths).
3. Keep the **service_role** singleton only for internal/batch jobs
   (schedulers in `apps/api/jobs/`, system seeding) that legitimately run
   without a user context.
4. Verify each RLS policy in `071_rls_policies.sql` actually blocks
   cross-firm reads/writes under the anon role, against a live DB.

Until then, **the app-layer `firm_id` filter is the only enforced isolation
boundary** — a forgotten filter on a new endpoint is a cross-firm leak with no
DB backstop. New repositories and routers MUST scope every query by `firm_id`.

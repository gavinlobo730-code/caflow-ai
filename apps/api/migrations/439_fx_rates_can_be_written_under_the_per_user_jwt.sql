-- Migration 439 — fx_rates can now be WRITTEN under the per-user JWT, not
-- only read
--
-- WHAT WAS WRONG
--
--   `PUT /api/currencies/rates` (routers/currencies.py::record_fx_rate) is the
--   one write action Settings > Multi-Currency > Exchange Rates exists for,
--   and it has 500ed on every call with SQLSTATE 42501 since the screen was
--   built. `core/exceptions.py`'s `_NOT_TRANSIENT` table is what turns that
--   SQLSTATE into the sentence the CA actually saw: "The server is not
--   permitted to write this table."
--
--   render.yaml has `USE_USER_JWT=true` in production (see its own comment:
--   "BOTH OF THESE ARE true IN PRODUCTION"), so `core/supabase_client.
--   get_supabase()` — what `record_fx_rate` calls — runs every request as the
--   Postgres role `authenticated` with RLS enforced, not as `service_role`.
--
--   Migration 146 enabled RLS on `public.fx_rates` and created exactly one
--   policy, `read_fx_rates`, FOR SELECT. It never created an INSERT or UPDATE
--   policy for any role. With RLS on and no permissive policy for a command,
--   every row is denied for that command regardless of any GRANT — and
--   migration 194's systematic sweep, by its own stated rule ("closes gaps
--   against policies that already exist and already name `authenticated`"),
--   correctly granted `fx_rates` only SELECT, because SELECT was the only
--   `authenticated`-scoped policy on the table for it to find. INSERT and
--   UPDATE were never granted to `authenticated` at all, on top of having no
--   policy to grant them for.
--
--   `service_role` is unaffected by this and was never the problem: migration
--   269's blanket sweep (`GRANT SELECT, INSERT, UPDATE, DELETE ... TO
--   service_role` over every table in `public` except its five named
--   read-only exceptions, which `fx_rates` is not one of) already covers it,
--   since 269 postdates 146. The gap is specific to the `authenticated` path
--   USE_USER_JWT switched production onto.
--
-- WHAT THIS DOES
--
--   Adds the missing INSERT and UPDATE policies for `authenticated`, and the
--   GRANTs to go with them — the exact repair migrations 192/193/194 made for
--   the same authoring mistake on other tables, and the one migration 194's
--   own header predicted would eventually recur ("an RLS policy is written
--   scoped to authenticated for some command, but the base table-level GRANT
--   for that command is never issued alongside it").
--
--   `USING (true)` / `WITH CHECK (true)`, matching `read_fx_rates`'s own
--   shape, because `fx_rates` carries no `firm_id` at all (migration 146's own
--   comment: "USD->INR on a date is a fact about the world", the same reason
--   `currencies` is unscoped) — there is no tenant boundary for a row-level
--   policy to express here. The real access control is already in the
--   application layer: `record_fx_rate` sits behind `rbac("settings",
--   "write")`, which is Partner-only, and that authorization is unchanged by
--   this migration — it decides who may REACH the endpoint, and this decides
--   only that the endpoint's own writes are not blocked by RLS/GRANT once
--   they get there. No DELETE policy or grant: there is no delete endpoint for
--   a recorded rate, and adding write surface nothing calls is not this fix's
--   job.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, GRANT is additive and
-- re-running it changes nothing. No data moves and no existing row is
-- affected — this only widens who may write a NEW or CORRECTED rate.

DROP POLICY IF EXISTS insert_fx_rates ON public.fx_rates;
CREATE POLICY insert_fx_rates ON public.fx_rates
  FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS update_fx_rates ON public.fx_rates;
CREATE POLICY update_fx_rates ON public.fx_rates
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

GRANT INSERT, UPDATE ON public.fx_rates TO authenticated;

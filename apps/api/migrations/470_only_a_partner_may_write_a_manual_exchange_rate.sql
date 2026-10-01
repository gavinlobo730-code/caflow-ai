-- Migration 470 — only a Partner may write a MANUAL exchange rate, and nobody
-- but the backend may write any other kind (security_privacy-19).
--
-- THE HOLE
--   Migration 439 made `public.fx_rates` writable under the per-user JWT, which
--   it had to be — the API runs as `authenticated` in production — and wrote
--   the policies as
--
--       INSERT  TO authenticated  WITH CHECK (true)
--       UPDATE  TO authenticated  USING (true) WITH CHECK (true)
--
--   on the reasoning, recorded in its header, that the table has no `firm_id`
--   and "the real access control is already in the application layer:
--   `record_fx_rate` sits behind `rbac("settings", "write")`, which is
--   Partner-only". That is true of the ROUTE and not of the table. The browser
--   holds the anon key and the member's own JWT and speaks PostgREST directly,
--   so the Partner-only rule was a property of one URL while the table was open
--   to every signed-in principal there is: an Executive, a Reviewer, a client
--   on the portal, an employee on the payroll portal, another firm's Partner —
--   any of them could overwrite the closing rate a firm's AS 11 year-end
--   revaluation reads, and a rate is a number that moves a profit and loss
--   account.
--
-- WHAT THIS DECIDES, AND WHAT IT LEAVES TO THE OWNER
--   The table STAYS GLOBAL. That is the owner's decision (recorded beside
--   `routers/currencies.py`'s rate endpoints and in
--   docs/audits/questions-for-the-owner.md): USD→INR on a date is a fact about
--   the world, so a firm-scoped table would have every firm re-type the same
--   number and the rate a document is booked at would depend on who typed it.
--   This migration does not reopen that. It makes the DATABASE enforce the half
--   of the decision that was only ever enforced by a URL:
--
--     * WHO — the same question the route asks, asked by the same function:
--       `my_permission('settings', 'write', 'Partner')`, so a per-person grant
--       or denial in the access grid (migration 403) applies here exactly as it
--       does at `rbac()`. A portal client, an employee and any member who is
--       not a Partner have no such permission; a suspended Partner has none
--       either (468).
--     * WHAT — a row whose `source` is `'manual'`, which is the only thing
--       `record_fx_rate` writes ("`source` is ALWAYS 'manual' and is not
--       settable"). A row from a provider — `rbi`, `ecb`, whatever a feed job
--       writes under the service key — is not a thing any member may change,
--       Partner or not. The unique key is (base, quote, rate_date, rate_type,
--       source), so a second source is a second rate for the day and not a
--       correction; a member editing a provider's row would be rewriting
--       somebody else's data.
--
--   What it does NOT do, and says so: one firm's Partner can still record a
--   manual rate that another firm's documents resolve through, because the
--   table is shared. That is the cost of the owner's decision and the reason the
--   finding proposed a firm column; it is a product choice with two defensible
--   answers and it is the owner's to revisit, not a defect to fix in passing.
--   `read_fx_rates` is untouched — a rate is public, and a portal client's own
--   foreign invoice needs to resolve one.
--
-- ONE EXISTING TEST CHANGED ITS PREMISE, AND THAT IS THE POINT
--   `tests/test_fx_rates_can_be_written_under_authenticated_pg.py` proved 439's
--   repair by writing as `authenticated` with NO identity at all — it modelled
--   the privilege gap and, in doing so, modelled exactly the caller this closes.
--   It now writes as a seeded Partner, which is the call the API actually makes.
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE). The table-level GRANT
-- of INSERT and UPDATE to `authenticated` from 439 stays: a grant says the role
-- MAY be allowed a row, the policy says which. Reversible:
-- 470_only_a_partner_may_write_a_manual_exchange_rate_rollback.sql.

DROP POLICY IF EXISTS insert_fx_rates ON public.fx_rates;
CREATE POLICY insert_fx_rates ON public.fx_rates
  FOR INSERT TO authenticated
  WITH CHECK (
    source = 'manual'
    AND public.my_permission('settings', 'write', 'Partner')
  );

DROP POLICY IF EXISTS update_fx_rates ON public.fx_rates;
CREATE POLICY update_fx_rates ON public.fx_rates
  FOR UPDATE TO authenticated
  USING (
    source = 'manual'
    AND public.my_permission('settings', 'write', 'Partner')
  )
  WITH CHECK (
    source = 'manual'
    AND public.my_permission('settings', 'write', 'Partner')
  );

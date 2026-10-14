-- Migration 495 — the practice's fee tables are read only by someone who holds billing access
-- (security_privacy-34, the last of the role-by-table matrix's deviation classes; ledger POST-B-024, stage two).
--
-- THE HOLE
--   core/permissions reserves the practice's own fee economics to `billing` ("exposes fee economics": Partner by
--   default, or a grant on the Team screen). fee_engagements and fee_invoices carry a firm rule, an assignment scope
--   and a Partner-only write tier, and NOTHING that asks the read tier, so an assigned Manager, Executive or Reviewer
--   could select the fees of every client they are assigned to with their own sign-in. fee_receipts has no client_id and
--   only a firm-wide select rule, so EVERY member of the firm could read every client's fee receipts.
--
-- WHY IT COULD NOT SIMPLY BE ADDED, AND WHAT CHANGED FIRST (read-only audit of every reader, 14-10-2026)
--   Five places asked these tables a different question as the caller and would have been answered with an empty
--   list and no error: the Compliance tab, the obligation generator, the ITR due-date question, the generate-
--   obligations route and the relationship-health score. The first four read an engagement's SCOPE (service and
--   status, no fee) and now do so through the privileged client (engagement_repo.find_scope); the score reads every
--   invoice of the client the same way and gives a role without billing:read the score and no figures. The
--   remaining readers either already ask `billing:read` (the engagements and billing routers, the billing screen) or
--   were moved onto it with this change (the /api/invoices routes, the analytics profitability, concentration and
--   revenue-vs-effort endpoints, the firm totals), and the two staff screens that read the tables from the browser
--   (/billing and /accounting/receivables, with /practice/profitability) sit behind FeeAccessGate, which says in
--   words that the screen is withheld. The privileged readers (time_rates_service, the definer functions, the
--   scheduler) are unaffected by row security.
--
-- WHAT THIS DOES (all RESTRICTIVE, so they AND with the existing firm, assignment and role rules and can only narrow)
--   Role is asked through `my_permission(resource, action, floor)`, the function the route's `rbac()` resolves through,
--   so a per-person grant or denial in the access grid counts here as it does at the route: a Manager the Partner has
--   given billing access reads, and is still confined to their assigned clients by the assignment scope that already
--   exists on fee_engagements and fee_invoices.
--
--     fee_engagements   fee_engagements_read_tier   SELECT   my_permission('billing','read','Partner')
--     fee_invoices      fee_invoices_read_tier      SELECT   my_permission('billing','read','Partner')
--     fee_receipts      fee_receipts_read_tier      SELECT   my_permission('billing','read','Partner')
--                                                            AND invoice_id IN (SELECT id FROM fee_invoices)
--
--   fee_receipts has no client_id, so it is scoped through its invoice: the subquery runs under the caller's own row
--   security, so it means "an invoice this person is allowed to see" (the firm, the assignment scope AND the read tier
--   above), and a receipt follows its invoice exactly. Writes already ask the Partner tier (the *_role_insert/update/
--   delete policies, migration 260, and the revoked grants on fee_invoices and fee_receipts), and UPDATE or DELETE with
--   a WHERE also consults the SELECT policy, so a person granted billing:write without billing:read is refused,
--   which is the same answer the API gives.
--
-- NOT DONE, ON PURPOSE
--   * The internal practice client's own fee rows get no extra condition: the practice does not bill itself
--     (guardrails G1 to G4), so there is nothing to protect that billing:read does not already.
--   * `client_firm_customer_links` and the portal's own invoice reads are a different table family
--     (client_sales_invoices) and are untouched: no portal principal reads these three tables.
--   * Production's catalogue was not read for the fee tables' current policies beyond the repository's snapshot; the
--     migration is DROP-IF-EXISTS then CREATE, so it is correct whatever is there.

DROP POLICY IF EXISTS "fee_engagements_read_tier" ON public.fee_engagements;
CREATE POLICY "fee_engagements_read_tier" ON public.fee_engagements
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('billing', 'read', 'Partner'));

DROP POLICY IF EXISTS "fee_invoices_read_tier" ON public.fee_invoices;
CREATE POLICY "fee_invoices_read_tier" ON public.fee_invoices
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('billing', 'read', 'Partner'));

DROP POLICY IF EXISTS "fee_receipts_read_tier" ON public.fee_receipts;
CREATE POLICY "fee_receipts_read_tier" ON public.fee_receipts
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('billing', 'read', 'Partner') AND invoice_id IN (SELECT id FROM public.fee_invoices));

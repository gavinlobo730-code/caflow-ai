-- Migration 166: harden RLS on sales_invoices/fixed_assets -- R3.3
-- orphaned-page discovery.
--
-- apps/web/app/accounting/invoices/page.tsx (never linked from navigation,
-- reachable only by typing the URL) wrote directly to sales_invoices from
-- the browser -- a table the real, linked invoicing flow
-- (apps/web/app/clients/[id]/sales/page.tsx -> apps/api/routers/
-- sales_invoices.py) never reads; it writes client_sales_invoices instead.
-- Any invoice header entered through the orphaned page was invisible to
-- every report, GST return, and dashboard in the app (the page's line-item
-- insert into "invoice_lines" already fails outright today -- migration 139
-- dropped that table years ago as dead/empty schema, unrelated to this
-- discovery, so only the orphaned header row survives). sales_invoices is
-- retired alongside the page (see the accompanying frontend change) -- this
-- migration closes the underlying write path so no future direct
-- REST/Supabase call can add more stranded rows, without deleting any
-- existing data a real user may have entered (that requires a human with
-- production access; see the audit doc's Implementation Log for the exact
-- follow-up check).
--
-- apps/web/app/accounting/fixed-assets/page.tsx (same orphaned-route class)
-- wrote directly to the SAME fixed_assets table the real, linked page
-- (apps/web/app/clients/[id]/fixed-assets/page.tsx -> apps/api/routers/
-- fixed_assets.py) uses -- but without going through the backend's
-- depreciation/disposal logic, so rows inserted via the orphan page never
-- got a journal_entry_id, silently breaking depreciation/GL tie-out. Same
-- fix pattern as R2.10/R3.0/R3.1b/R3.13a: revoke direct mutation, force all
-- writes through the backend service-role path.

REVOKE INSERT, UPDATE, DELETE ON public.sales_invoices FROM authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.fixed_assets FROM authenticated;

DROP POLICY IF EXISTS "sales_invoices_own_firm" ON public.sales_invoices;
CREATE POLICY "sales_invoices_own_firm" ON public.sales_invoices
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_client_isolation" ON public.fixed_assets;
CREATE POLICY "firm_client_isolation" ON public.fixed_assets
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

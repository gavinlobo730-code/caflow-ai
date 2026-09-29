-- Migration 443: a portal client may read the documents behind their own fee
-- scope — the eight tables migration 442's own header named as the reason
-- fixing `client_firm_customer_links` alone would not be enough.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE BUG THAT SURVIVES 440/441/442
-- ═══════════════════════════════════════════════════════════════════════════
-- `services/portal_data_service.resolve_fee_scope` (fixed by migration 442) is
-- only the FIRST of two RLS-gated steps in every one of its six callers —
-- `list_invoices`, `dues`, `invoice_in_scope`, `reminder_history`, `statement`
-- and `statement_pdf`. Each of them then queries one or more of eight further
-- tables, under `USE_USER_JWT=true` (on in production per render.yaml), on the
-- portal client's own per-user-JWT session:
--
--   client_sales_invoices     — list_invoices, invoice_in_scope, statement,
--                                statement_pdf, and payment_service.create_link
--                                (the portal Pay Now path migration 441 fixed
--                                the SECOND half of)
--   invoice_deliveries        — reminder_history
--   customers                 — statement, statement_pdf, and
--                                payment_service.create_link (the customer's
--                                name/email/phone handed to the payment
--                                provider)
--   receipts                  — statement, statement_pdf
--   receipt_allocations       — statement, statement_pdf (the true AR-relief
--                                figure per receipt, task #102)
--   credit_notes              — statement, statement_pdf
--   sales_debit_notes         — statement, statement_pdf
--   customer_statement_deliveries — see the "ONE TABLE ON THIS LIST IS NOT
--                                ACTUALLY ON THE PATH" section below
--
-- So migration 442 succeeding does not, by itself, do anything: the very next
-- query in every one of these callers is still RLS-denied, and a SELECT an
-- RLS RESTRICTIVE policy blocks returns ZERO ROWS, not an error — the exact
-- silence `resolve_fee_scope` itself was blocked with before 442. A portal
-- client's Invoices, Dues, Statement and Payment-Reminder tabs still come
-- back empty in production until this migration lands.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- EVERY TABLE'S REAL POLICY STACK WAS READ FROM A BUILT DATABASE, NOT FROM ITS
-- OWN CREATING MIGRATION — because that has already been wrong twice on this
-- exact bug shape (migration 442's own header, about client_firm_customer_links)
-- ═══════════════════════════════════════════════════════════════════════════
-- A throwaway database built from every migration in this tree (441/442
-- included) was queried directly against `pg_policies` for all eight tables.
-- Three things a plain read of each table's OWN creating migration would have
-- gotten wrong, in three different ways:
--
-- (1) `client_sales_invoices`'s permissive firm-scope policy is no longer
--     named `firm_client_sales_invoices` (as migration 050 declares it) —
--     migration 053 renamed it to `firm_client_isolation` and tightened its
--     qual with a join to `clients`, and a SEPARATE migration (075) added
--     `client_sales_invoices_internal_partner_only`, because 074's own static
--     table array said `sales_invoices` — a name this table has never had —
--     and 075's own header calls that out explicitly ("074 listed the Doc-5
--     name 'sales_invoices' which does not exist here"). `receipts` and
--     `credit_notes` show the identical `firm_client_isolation` rename from
--     053. Reading only 050/074 would have missed all of this.
-- (2) `sales_debit_notes` (migration 210) declared NO RLS and NO GRANT at
--     all — migration 212's own header records this as a defect found by "an
--     independent adversarial review", closed nine migrations later — and its
--     `_assignment_scope` policy came later still, from migration 370's
--     explicit six-table list (370's own header: 084's one-shot loop "has
--     never run again", and this table is one of the six read straight from
--     the browser with none). So `sales_debit_notes` carries no
--     `_internal_partner_only` policy at all — 074's array predates 210, and
--     nothing has ever added the G1 policy for this table.
-- (3) `receipt_allocations` has no `client_id` column at all (it is scoped
--     through `receipt_id`), so neither 074's static array nor 084's dynamic
--     `client_id`-column sweep ever touched it: it carries exactly ONE policy,
--     a PERMISSIVE `firm_client_isolation` (053) joining through `receipts`.
--     There is no RESTRICTIVE layer to widen on this table at all — the fix
--     here is purely additive.
--
-- The full, VERIFIED (not assumed) shape, per table, before this migration:
--
--   client_sales_invoices          2 PERMISSIVE (own_firm/075, firm_client_
--                                  isolation/053) + 2 RESTRICTIVE FOR ALL
--                                  (assignment_scope/084, internal_partner_
--                                  only/075)
--   invoice_deliveries             1 PERMISSIVE (097) + 2 RESTRICTIVE FOR ALL,
--                                  both declared directly by 097 itself
--   customers                      1 PERMISSIVE (049) + 2 RESTRICTIVE FOR ALL
--                                  (assignment_scope/084, internal_partner_
--                                  only/074) + 3 RESTRICTIVE role policies
--                                  (customers_role_insert/update/delete,
--                                  migrations 260/261's my_permission() gate —
--                                  untouched here, see below)
--   receipts                       1 PERMISSIVE (firm_client_isolation/053) +
--                                  2 RESTRICTIVE FOR ALL (assignment_scope/084,
--                                  internal_partner_only/074)
--   receipt_allocations            1 PERMISSIVE ONLY (firm_client_isolation/
--                                  053) — no RESTRICTIVE layer exists
--   credit_notes                   1 PERMISSIVE (firm_client_isolation/053) +
--                                  2 RESTRICTIVE FOR ALL (assignment_scope/084,
--                                  internal_partner_only/074)
--   sales_debit_notes               1 PERMISSIVE (firm_sales_debit_notes/212) +
--                                  1 RESTRICTIVE FOR ALL (assignment_scope/370)
--                                  — no internal_partner_only
--   customer_statement_deliveries  1 PERMISSIVE (105) + 2 RESTRICTIVE FOR ALL,
--                                  both declared directly by 105 itself
--
-- Every RESTRICTIVE `_assignment_scope` reads `can_access_client(client_id)`,
-- unconditionally FALSE-or-NULL for a portal principal (no `public.users` row
-- → `get_my_role()` NULL → the assignment EXISTS clause FALSE → `NULL OR FALSE
-- OR FALSE` = NULL = deny) — the identical mechanism 440/441/442 close on
-- their own tables. Every PERMISSIVE policy on these eight tables requires
-- `firm_id = get_my_firm_id()` (directly, or one hop through `receipts`/
-- `clients`), and `get_my_firm_id()` is ALSO NULL for a portal principal — so,
-- exactly like `customer_payment_links` and `client_firm_customer_links`
-- before 441/442, NONE of these eight tables has a PERMISSIVE lane a portal
-- principal can ever satisfy, whatever the RESTRICTIVE layer allows.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE IDENTITY COLUMN WAS TRACED PER TABLE, NOT ASSUMED FROM THE OTHERS
-- ═══════════════════════════════════════════════════════════════════════════
-- `client_sales_invoices.client_id` — like `customer_payment_links.client_id`
-- before it — is the FIRM's own internal client id (`firms.internal_client_id`,
-- the G3 pattern), NEVER the portal client's own external id: a fee invoice is
-- booked on the firm's internal books with the real client recorded only as
-- the CUSTOMER (`portal_data_service.list_invoices`:
-- `.eq("client_id", scope["internal_client_id"]).eq("customer_id",
-- scope["internal_customer_id"])`). So the portal-client branch on every one
-- of these tables is keyed on `customer_id` (via
-- `public.my_portal_customer_ids()`, migrations 441/442's own helper,
-- unchanged here), never `client_id` — copying migration 440's `client_id`
-- shape onto any of these eight would match no row any of these services ever
-- reads, exactly the mistake migration 441's header warns an early draft of
-- its OWN fix made before it was caught.
--
-- Six of the eight carry `customer_id` directly (confirmed against each
-- table's own creating migration): `client_sales_invoices`, `receipts`,
-- `credit_notes`, `sales_debit_notes`, `customer_statement_deliveries`, and
-- `customers` itself — where the portal client's own row IS the customer row
-- (`customers.id = internal_customer_id`), so its branch is `id IN (SELECT
-- my_portal_customer_ids())`, not `customer_id IN (...)`.
--
-- TWO OF THE EIGHT HAVE NO `customer_id` COLUMN AT ALL, AND EACH NEEDS ITS OWN
-- ONE-HOP HELPER — copying `my_portal_customer_ids()`'s OWN reasoning (it is
-- SECURITY DEFINER specifically so a policy using it never has to depend on
-- the RLS of the table it reads) rather than writing the join inline against
-- a sibling table this same migration is also rewriting:
--
--   * `invoice_deliveries` carries only `invoice_id` (no `customer_id`), and
--     `collections_service._dispatch_invoice_reminder` confirms
--     `invoice_deliveries.client_id` is always copied straight off the
--     invoice's own `client_id` — the identical "client_id is the FIRM's, the
--     real identity is one hop further in" shape migration 441 found on
--     `customer_payment_links`. `public.my_portal_invoice_ids()` is declared
--     here: SECURITY DEFINER, reading `client_sales_invoices` directly
--     (bypassing that table's own RLS, the same reason
--     `my_portal_customer_ids()` bypasses `client_firm_customer_links`'s), so
--     that this policy's correctness never depends on `client_sales_invoices`'
--     RLS being in any particular state — even though this same migration
--     also widens it, a policy built on a SECURITY DEFINER read is not
--     accidentally coupled to that fact.
--   * `receipt_allocations` carries only `receipt_id` and `sales_invoice_id`
--     (no `customer_id`), and `receipts.customer_id` is the more direct of the
--     two available hops (`customer_statement_service.generate` already reads
--     allocations by `receipt_id`, never `sales_invoice_id`, for exactly this
--     data). `public.my_portal_receipt_ids()` is declared here for the same
--     reason as `my_portal_invoice_ids()` above — SECURITY DEFINER, reading
--     `receipts` directly.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- READS ONLY, EVERY ONE OF THE EIGHT — CONFIRMED BY GREPPING EVERY CALLER, NOT
-- ASSUMED FROM THE SERVICE'S OWN "READ-ONLY" DOCSTRING
-- ═══════════════════════════════════════════════════════════════════════════
-- `portal_data_service.py`'s own module docstring says "read-only, client-safe
-- views" — checked rather than trusted, because `payment_service.create_link`
-- (reached from `POST /invoices/{id}/pay`, a WRITE endpoint) also reads
-- `client_sales_invoices` and `customers` on the SAME portal-client session,
-- and a read-only claim about the SERVICE says nothing about every ROUTE that
-- reaches these tables. Grepping every one of
-- `routers/portal_data.py`'s nine endpoints plus `payment_service.create_link`
-- confirms: NONE of the eight tables in this migration is ever INSERTed,
-- UPDATEd or DELETEd from a portal-authenticated code path. So — matching
-- migration 442's own reasoning for `client_firm_customer_links`, and 441's
-- own reasoning for leaving `customer_payment_links`'s DELETE narrow — every
-- new PERMISSIVE lane here is `FOR SELECT` only, and every RESTRICTIVE
-- INSERT/UPDATE/DELETE policy (where one exists to split) keeps
-- `can_access_client(client_id)` UNCHANGED. Widening a write no portal caller
-- can even reach would be exactly the migration-380-documented mistake of
-- opening a write ahead of the feature that needs it.
--
-- `customers_role_insert` / `_role_update` / `_role_delete` (migrations
-- 260/261's `my_permission()`-gated RESTRICTIVE policies) are UNTOUCHED for
-- the identical reason: they are independent RESTRICTIVE policies on the same
-- three commands, and nothing here needs to widen a write path.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- `_internal_partner_only` NEEDS NO WIDENING ON ANY OF THE SIX TABLES THAT
-- CARRY IT — CONFIRMED ON A BUILT DATABASE, NOT JUST REASONED FROM THE SQL
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 441's header works out, for the identical policy shape on
-- `customer_payment_links_internal_partner_only`, that its OR-branch
-- (`client_id::text IS DISTINCT FROM my_internal_client_id()::text`) is TRUE
-- for EVERY row on that table for ANY portal principal, because
-- `my_internal_client_id()` reads `firms WHERE id = get_my_firm_id()` —
-- `get_my_firm_id()` is NULL for a portal principal, so that lookup returns no
-- row and the function itself returns NULL, and `<anything non-null> IS
-- DISTINCT FROM NULL` is TRUE by the operator's own definition. The identical
-- argument applies verbatim to `client_sales_invoices_internal_partner_only`,
-- `invoice_deliveries_internal_partner_only`, `customers_internal_partner_
-- only`, `receipts_internal_partner_only`, `credit_notes_internal_partner_
-- only` and `cust_stmt_deliveries_internal_partner_only` — all six declare the
-- SAME expression against the SAME helper. Reasoned here and then CONFIRMED
-- on the built database below (this migration's own test), not left as an
-- inference: a portal client's SELECT against their own row succeeds with
-- these policies present and unmodified, which could only be true if this
-- reasoning is right.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ONE TABLE ON THIS LIST IS NOT ACTUALLY ON THE PORTAL PATH TODAY, AND IT IS
-- FIXED ANYWAY — REPORTED RATHER THAN QUIETLY DROPPED FROM THE LIST
-- ═══════════════════════════════════════════════════════════════════════════
-- `customer_statement_deliveries` is written and read by exactly
-- `services/customer_statement_service.record_delivery` /
-- `.finish_delivery` / `.deliveries`, and their only caller is
-- `routers/customer_statements.py` — the STAFF-side "email this statement"
-- feature. Neither `portal_data_service.statement` nor `.statement_pdf` reads
-- or writes it: `get_customer_statement_pdf` calls `generate()` +
-- `load_account_holder()` and returns the bytes; nothing records a delivery.
-- So fixing this table's RLS does not, by itself, change what a portal client
-- sees today — it is fixed anyway because it carries the identical bug shape
-- and the task that produced this migration named it explicitly, and leaving
-- a known-vulnerable table's RLS alone because its only current reader
-- happens to be staff-side would be exactly the kind of "nothing reaches it
-- from the browser" reasoning CLAUDE.md records as the WRONG call once
-- `USE_USER_JWT` is live and a future portal feature (a client requesting
-- their own statement be emailed) reaches it without anyone re-auditing RLS
-- first.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- FOUND, NAMED, AND DELIBERATELY NOT FIXED HERE: `clients` BLOCKS
-- `statement_pdf` TOO, AND TOUCHING IT IS OUT OF SCOPE
-- ═══════════════════════════════════════════════════════════════════════════
-- `statement_pdf` -> `statement_pdf_service.get_customer_statement_pdf` ->
-- `load_account_holder(db, firm_id, client_id)` reads `public.clients` for
-- `id = scope["internal_client_id"]` — the firm's OWN internal-client row, so
-- the PDF's letterhead can print the FIRM's name rather than the practice's
-- (see that function's own docstring). `clients` carries the same shape as
-- every table above (`clients_own_firm` PERMISSIVE requiring
-- `firm_id = get_my_firm_id()`; `clients_assignment_scope` RESTRICTIVE
-- requiring `can_access_client(id::text)` — both NULL for a portal principal
-- reading the internal-client row) — confirmed on the built database, not
-- assumed. So `/statement/pdf` will still fail for a portal client even after
-- this migration, on a table this migration deliberately does not touch: it
-- is exactly the "real, separate, out-of-scope defect" migration 440's own
-- header already named for `clients` (there, about a legacy portal-linked
-- client's OWN row) — `clients` is the single most heavily-loaded table in
-- this schema (074's G1 sweep, 084's G5 sweep, 260/261's role policies all
-- converge on it), and widening its RLS is a change with a blast radius far
-- past one portal endpoint. Flagged, not fixed.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ALL EIGHT TAKE THE 262 SHAPE (CLEAN DROP), NONE TAKES THE portal_messages
-- SHAPE — CHECKED PER TABLE AGAINST 294's OWN EXACT LIST, NOT ASSUMED FROM THE
-- TWO SIBLING FIXES THAT ALREADY MADE THIS CALL
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 294's idempotent restore loop names exactly eight (table, kind)
-- pairs by EXACT string equality (`policyname = tablename || '_' || kind`):
-- `client_health_overrides`/`assignment_scope`, `client_health_scores`/
-- `assignment_scope`, `government_notices`/`assignment_scope`,
-- `government_notices`/`internal_partner_only`, `gstr2b_uploads`/
-- `assignment_scope`, `gstr2b_uploads`/`internal_partner_only`,
-- `portal_messages`/`assignment_scope`, `year_end_adjustments`/
-- `assignment_scope` — read directly from 294's own file, not from memory.
-- None of `client_sales_invoices`, `invoice_deliveries`, `customers`,
-- `receipts`, `credit_notes`, `sales_debit_notes` or
-- `customer_statement_deliveries` appears (`receipt_allocations` has no
-- `_assignment_scope` policy to begin with). So every `_assignment_scope`
-- FOR-ALL policy this migration touches is DROPPED outright and replaced with
-- four per-command ones — migration 262's shape, not migration 440's — for
-- the identical reason migrations 441 and 442 give: no out-of-band re-run of
-- 294 goes looking for any of these names, so nothing recreates the FOR-ALL
-- policy this migration retires. (Migration 370's own idempotent loop, which
-- DOES touch `sales_debit_notes`, guards on `policyname LIKE '%assignment%'`
-- — a substring test, not exact equality — so it will see the four
-- `sales_debit_notes_assignment_scope_{select,insert,update,delete}` names
-- this migration creates and continue to skip that table on any future
-- out-of-band re-run; confirmed by reading 370's own `DO` block.)
--
-- ═══════════════════════════════════════════════════════════════════════════
-- BELT AND SUSPENDERS, ATOMIC — FOR THE SAME REASONS AS 440/441/442
-- ═══════════════════════════════════════════════════════════════════════════
-- Grants are re-asserted idempotently to match what this environment's own
-- `information_schema.role_table_grants` shows today (SELECT/INSERT/UPDATE/
-- DELETE on all eight — `invoice_deliveries` and `customer_statement_
-- deliveries` were each declared without DELETE by their own creating
-- migrations, 097 and 105, and both since gained it from migration 194's
-- systematic grant sweep; re-asserting anything narrower here would not
-- change RLS but would misdescribe the table's own privilege history). This
-- environment cannot inspect production's actual ACL independently of the
-- schema this repo declares (migration 194's whole premise).
--
-- `apply_migrations.py` invokes `psql -f` WITHOUT --single-transaction, so a
-- failure partway through any one of these eight DROP-then-CREATE sequences
-- must not leave a RESTRICTIVE policy dropped with nothing yet in its place.
-- BEGIN/COMMIT makes that impossible: the file fully applies or does nothing.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- VERIFIED END TO END ON A REAL DATABASE BUILT FROM THE FULL MIGRATION SET
-- ═══════════════════════════════════════════════════════════════════════════
-- See tests/test_r443_portal_client_reads_own_fee_documents_pg.py: raw-SQL
-- proofs for all eight tables (own row visible, sibling portal client's row
-- invisible, unassigned staff sees nothing, an assigned/Partner staff member
-- unaffected, no write widened) PLUS the real, unmodified
-- `services.portal_data_service` functions — `list_invoices`, `dues`,
-- `invoice_in_scope`, `reminder_history`, `statement`, `statement_pdf` — called
-- directly against a `db` double whose `.table(...)` calls execute real SQL
-- over the portal client's own RLS-constrained session for every one of the
-- eight tables this migration touches (migration 442's own test routed
-- `client_sales_invoices` through the admin/no-RLS session specifically
-- because it was NOT YET FIXED; this file's test routes it through the real
-- portal session, because it now is). A negative-control build (every
-- migration in this tree EXCEPT this one) reproduces the identical empty
-- result every one of the six callers gave before this fix — the concrete
-- shape of "a portal client's tabs return empty" the task set out to close.

BEGIN;

-- ── Helpers ───────────────────────────────────────────────────────────────
--
-- my_portal_client_ids() / my_portal_customer_ids() are declared VERBATIM as
-- migrations 440/441/442 already declare them, so that whichever migration in
-- this family lands first in any given merge order, CREATE OR REPLACE leaves
-- every later re-declaration a harmless no-op — all name the same global
-- function with the same body.

CREATE OR REPLACE FUNCTION public.my_portal_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT client_id FROM public.client_portal_users
   WHERE auth_user_id = auth.uid() AND status = 'active'
  UNION
  SELECT id FROM public.clients
   WHERE portal_user_id = auth.uid()
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_client_ids() TO authenticated;

CREATE OR REPLACE FUNCTION public.my_portal_customer_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT internal_customer_id FROM public.client_firm_customer_links
   WHERE client_id IN (SELECT public.my_portal_client_ids())
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_customer_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_customer_ids() TO authenticated;

-- NEW: one hop further in, for the two tables that carry no `customer_id` of
-- their own. Each is SECURITY DEFINER for the identical reason
-- my_portal_customer_ids() is — a policy built on it never depends on the RLS
-- state of the table it reads, including this migration's own widening of
-- that table two sections below.

CREATE OR REPLACE FUNCTION public.my_portal_invoice_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT id FROM public.client_sales_invoices
   WHERE customer_id IN (SELECT public.my_portal_customer_ids())
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_invoice_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_invoice_ids() TO authenticated;

CREATE OR REPLACE FUNCTION public.my_portal_receipt_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT id FROM public.receipts
   WHERE customer_id IN (SELECT public.my_portal_customer_ids())
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_receipt_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_receipt_ids() TO authenticated;

-- ── client_sales_invoices ────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_sales_invoices TO authenticated;
GRANT ALL ON public.client_sales_invoices TO service_role;

DROP POLICY IF EXISTS "client_sales_invoices_assignment_scope" ON public.client_sales_invoices;

CREATE POLICY "client_sales_invoices_assignment_scope_select" ON public.client_sales_invoices
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "client_sales_invoices_assignment_scope_insert" ON public.client_sales_invoices
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "client_sales_invoices_assignment_scope_update" ON public.client_sales_invoices
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "client_sales_invoices_assignment_scope_delete" ON public.client_sales_invoices
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "client_sales_invoices_portal_client_select" ON public.client_sales_invoices;
CREATE POLICY "client_sales_invoices_portal_client_select" ON public.client_sales_invoices
  FOR SELECT TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

-- ── invoice_deliveries ───────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON public.invoice_deliveries TO authenticated;
GRANT ALL ON public.invoice_deliveries TO service_role;

DROP POLICY IF EXISTS "invoice_deliveries_assignment_scope" ON public.invoice_deliveries;

CREATE POLICY "invoice_deliveries_assignment_scope_select" ON public.invoice_deliveries
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR invoice_id IN (SELECT public.my_portal_invoice_ids())
  );

CREATE POLICY "invoice_deliveries_assignment_scope_insert" ON public.invoice_deliveries
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "invoice_deliveries_assignment_scope_update" ON public.invoice_deliveries
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "invoice_deliveries_assignment_scope_delete" ON public.invoice_deliveries
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "invoice_deliveries_portal_client_select" ON public.invoice_deliveries;
CREATE POLICY "invoice_deliveries_portal_client_select" ON public.invoice_deliveries
  FOR SELECT TO authenticated
  USING (invoice_id IN (SELECT public.my_portal_invoice_ids()));

-- ── customers ────────────────────────────────────────────────────────────────
-- Its own `id` IS the internal_customer_id here (this is the customer master
-- itself, not a table that merely references one) — the branch is `id IN
-- (...)`, not `customer_id IN (...)`. customers_role_insert/_update/_delete
-- (migrations 260/261) are separate, independent RESTRICTIVE policies on the
-- same three commands and are left exactly as they are.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.customers TO authenticated;
GRANT ALL ON public.customers TO service_role;

DROP POLICY IF EXISTS "customers_assignment_scope" ON public.customers;

CREATE POLICY "customers_assignment_scope_select" ON public.customers
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "customers_assignment_scope_insert" ON public.customers
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "customers_assignment_scope_update" ON public.customers
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "customers_assignment_scope_delete" ON public.customers
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "customers_portal_client_select" ON public.customers;
CREATE POLICY "customers_portal_client_select" ON public.customers
  FOR SELECT TO authenticated
  USING (id IN (SELECT public.my_portal_customer_ids()));

-- ── receipts ─────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON public.receipts TO authenticated;
GRANT ALL ON public.receipts TO service_role;

DROP POLICY IF EXISTS "receipts_assignment_scope" ON public.receipts;

CREATE POLICY "receipts_assignment_scope_select" ON public.receipts
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "receipts_assignment_scope_insert" ON public.receipts
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "receipts_assignment_scope_update" ON public.receipts
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "receipts_assignment_scope_delete" ON public.receipts
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "receipts_portal_client_select" ON public.receipts;
CREATE POLICY "receipts_portal_client_select" ON public.receipts
  FOR SELECT TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

-- ── receipt_allocations ──────────────────────────────────────────────────────
-- No client_id column and no RESTRICTIVE policy exists on this table at all —
-- purely additive. FOR SELECT only, to match the "reads only" finding above
-- exactly; the table's single existing PERMISSIVE policy (firm_client_
-- isolation, migration 053) is untouched, and PERMISSIVE policies only ever
-- widen what a role may do, never narrow it, so adding this one cannot affect
-- any existing reader.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.receipt_allocations TO authenticated;
GRANT ALL ON public.receipt_allocations TO service_role;

DROP POLICY IF EXISTS "receipt_allocations_portal_client_select" ON public.receipt_allocations;
CREATE POLICY "receipt_allocations_portal_client_select" ON public.receipt_allocations
  FOR SELECT TO authenticated
  USING (receipt_id IN (SELECT public.my_portal_receipt_ids()));

-- ── credit_notes ─────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON public.credit_notes TO authenticated;
GRANT ALL ON public.credit_notes TO service_role;

DROP POLICY IF EXISTS "credit_notes_assignment_scope" ON public.credit_notes;

CREATE POLICY "credit_notes_assignment_scope_select" ON public.credit_notes
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "credit_notes_assignment_scope_insert" ON public.credit_notes
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "credit_notes_assignment_scope_update" ON public.credit_notes
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "credit_notes_assignment_scope_delete" ON public.credit_notes
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "credit_notes_portal_client_select" ON public.credit_notes;
CREATE POLICY "credit_notes_portal_client_select" ON public.credit_notes
  FOR SELECT TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

-- ── sales_debit_notes ────────────────────────────────────────────────────────
-- No internal_partner_only policy exists here (see the header) — nothing is
-- added: this migration only ever widens SELECT for the portal branch, never
-- reaches for a G1 policy that isn't already this table's own business.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sales_debit_notes TO authenticated;
GRANT ALL ON public.sales_debit_notes TO service_role;

DROP POLICY IF EXISTS "sales_debit_notes_assignment_scope" ON public.sales_debit_notes;

CREATE POLICY "sales_debit_notes_assignment_scope_select" ON public.sales_debit_notes
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "sales_debit_notes_assignment_scope_insert" ON public.sales_debit_notes
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "sales_debit_notes_assignment_scope_update" ON public.sales_debit_notes
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "sales_debit_notes_assignment_scope_delete" ON public.sales_debit_notes
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "sales_debit_notes_portal_client_select" ON public.sales_debit_notes;
CREATE POLICY "sales_debit_notes_portal_client_select" ON public.sales_debit_notes
  FOR SELECT TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

-- ── customer_statement_deliveries ────────────────────────────────────────────
-- Not on the portal's read path today (see the header) — fixed anyway, same
-- shape, same reasoning.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.customer_statement_deliveries TO authenticated;
GRANT ALL ON public.customer_statement_deliveries TO service_role;

DROP POLICY IF EXISTS "cust_stmt_deliveries_assignment_scope" ON public.customer_statement_deliveries;

CREATE POLICY "cust_stmt_deliveries_assignment_scope_select" ON public.customer_statement_deliveries
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "cust_stmt_deliveries_assignment_scope_insert" ON public.customer_statement_deliveries
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "cust_stmt_deliveries_assignment_scope_update" ON public.customer_statement_deliveries
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "cust_stmt_deliveries_assignment_scope_delete" ON public.customer_statement_deliveries
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "cust_stmt_deliveries_portal_client_select" ON public.customer_statement_deliveries;
CREATE POLICY "cust_stmt_deliveries_portal_client_select" ON public.customer_statement_deliveries
  FOR SELECT TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

COMMIT;

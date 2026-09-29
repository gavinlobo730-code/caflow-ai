-- Migration 441: a portal client may pay their own invoice.
--
-- SAME BUG SHAPE AS THE SIBLING PORTAL_MESSAGES FIX, FOUND WHILE
-- PATTERN-SEARCHING FOR IT
-- A sibling fix (written as migration 438, since renumbered to 440 on `main`
-- because 438/439 were claimed by other in-flight work by the time it merged
-- — see the numbering note at the foot of this header) closed the identical
-- defect on `portal_messages`: a RESTRICTIVE `<table>_assignment_scope`
-- policy ANDs `public.can_access_client(client_id)` on top of every
-- PERMISSIVE policy, and `can_access_client` is unconditionally FALSE-or-NULL
-- for a portal-CLIENT principal — `core/portal_auth.get_current_portal_client`
-- issues a real Supabase JWT with NO `public.users` row, so `get_my_role()`
-- reads NULL, the assignment EXISTS clause is FALSE, and
-- `NULL OR FALSE OR FALSE` is NULL, which RLS treats as deny. Grepping every
-- RESTRICTIVE `*_assignment_scope` policy that a portal WRITE path reaches
-- found the identical shape on `customer_payment_links`, reachable from
-- `POST /api/portal/self/invoices/{id}/pay`
-- (`routers/portal_data.py:portal_pay_invoice` ->
-- `services/payment_service.create_link`), called with
-- `core.supabase_client.get_supabase()` — the PER-USER-JWT client, not
-- `get_service_supabase()` — so under `USE_USER_JWT=true` (on in production
-- per render.yaml) this genuinely runs as the portal client's own
-- row-level-security-constrained session, exactly like the portal_messages
-- INSERT did.
--
-- CONFIRMED BY READING THE CALLER, NOT ASSUMED FROM THE SIBLING
-- `create_link` (services/payment_service.py) does THREE things against
-- `customer_payment_links` for that one client, on the SAME `db` handle
-- `portal_pay_invoice` passed in, in this order: a SELECT for idempotent
-- reuse of an existing open link (lines 89-92), an INSERT of the new row
-- (99-104), and — after calling the payment provider — an UPDATE of THE SAME
-- ROW to `status='active'` with the provider's `short_url` (118-121). A fix
-- that widens only the INSERT (the literal shape of the sibling fix, which
-- only ever needed an INSERT/SELECT widened for portal_messages) leaves that
-- immediately-following UPDATE to fail with the identical 42501 one line
-- later — a shorter-lived but equally real version of the same bug, and the
-- reason the per-command split below adds an UPDATE branch the sibling fix
-- did not need.
--
-- THE ROW'S OWN `client_id` IS NOT THE PORTAL CLIENT'S ID, AND THIS IS THE
-- PART A "COPY THE SIBLING'S OR-BRANCH" FIX WOULD HAVE GOT WRONG
-- The obvious mirror of the sibling fix is a policy OR-ing in
-- `client_id IN (SELECT public.my_portal_client_ids())`, the same branch
-- `portal_messages` needed, because on that table `client_id` IS the portal
-- client's own external client id. `customer_payment_links.client_id` is NOT
-- that value here — tracing `create_link` end to end shows it: the router
-- passes `portal["client_id"]` (the portal member's own EXTERNAL client id)
-- only to `portal_data_service.invoice_in_scope`, which calls
-- `resolve_fee_scope` — the "Firm-as-Internal-Client" (G3) lookup — and that
-- resolves the EXTERNAL client to `firms.internal_client_id` (the FIRM's OWN
-- practice-client row) plus an `internal_customer_id`, via
-- `client_firm_customer_links(firm_id, client_id [external], internal_customer_id)`.
-- `create_link` then reads the invoice with `_get_invoice`, and the row it
-- finds carries `client_sales_invoices.client_id = firms.internal_client_id`
-- — a fee invoice is booked on the FIRM'S OWN internal books, with the real
-- client recorded only as the CUSTOMER on that invoice
-- (`client_sales_invoices.customer_id = internal_customer_id`). Every field
-- `create_link` inserts into `customer_payment_links` is copied straight off
-- that invoice row (`"client_id": inv["client_id"], "customer_id":
-- inv["customer_id"]`), so the payment link this portal client is trying to
-- pay ALSO carries `client_id = firms.internal_client_id` — a value that is
-- never a member of ANY portal client's own `my_portal_client_ids()`, by
-- construction. A policy OR-ing that branch in on `client_id` would apply to
-- no row `create_link` ever inserts and would look fixed under a test that
-- (like an early draft of this migration's own test file) inserted a probe
-- row with `client_id` set to the portal member's own id directly, which is
-- not the shape the real code produces.
-- The column that DOES carry the portal client's own identity, one hop
-- removed, is `customer_id` — it is exactly `internal_customer_id`, the
-- value `client_firm_customer_links` maps FROM the caller's own external
-- `client_id`. So the correct branch is
-- `customer_id IN (SELECT public.my_portal_customer_ids())`, where
-- `my_portal_customer_ids()` composes `my_portal_client_ids()` with that same
-- join — mirroring, in SQL, exactly the authorization
-- `portal_data_service.resolve_fee_scope` already performs in Python (over
-- the service-role connection) before the router ever reaches `create_link`.
--
-- TWO THINGS BLOCK THIS TABLE, NOT ONE, AND ONLY ONE OF THEM IS THE
-- PORTAL_MESSAGES SHAPE
-- `customer_payment_links` carries three policies, all declared directly by
-- migration 110 (NOT by migration 084's one-shot loop — 110 postdates 084, so
-- it wrote the RESTRICTIVE policy inline, in 084's own wording, its own
-- header says so: "Mirrors the invoice_deliveries / receipts 3-policy stack
-- for the client-scoped tables"):
--
--   firm_customer_payment_links                   PERMISSIVE FOR ALL
--                                                  firm_id = get_my_firm_id()
--   customer_payment_links_assignment_scope       RESTRICTIVE FOR ALL
--                                                  can_access_client(client_id)
--   customer_payment_links_internal_partner_only  RESTRICTIVE FOR ALL
--                                                  get_my_role()='Partner' OR
--                                                  client_id IS DISTINCT FROM
--                                                  my_internal_client_id()
--
-- `get_my_firm_id()` (last defined by migration 019) is `SELECT firm_id FROM
-- public.users WHERE auth_user_id = auth.uid()` — the SAME "no users row"
-- hole as `get_my_role()` — so it ALSO reads NULL for a portal client. That
-- is the second, INDEPENDENT thing wrong here: this table has exactly ONE
-- PERMISSIVE policy, and it is staff-only. Unlike `portal_messages`, which
-- already carried a portal-friendly PERMISSIVE policy
-- (`portal_client_messages`, migrations 048/094, and `portal_contact_messages`,
-- 109) so only the RESTRICTIVE layer needed widening there,
-- `customer_payment_links` has NO portal-friendly PERMISSIVE policy at all.
-- Fixing only the RESTRICTIVE policy — the literal shape of the sibling fix —
-- would still 42501 the INSERT, because a PERMISSIVE OR-group with zero
-- passing members denies regardless of what any RESTRICTIVE policy allows.
-- Confirmed both ways round: `customer_payment_links_internal_partner_only`
-- does NOT need touching — its OR-branch
-- (`client_id IS DISTINCT FROM my_internal_client_id()`) is TRUE for any
-- portal client and ANY row here, because `my_internal_client_id()` (last
-- defined by migration 074) reads `firms WHERE id = get_my_firm_id()`, which
-- is `firms WHERE id = NULL` for a portal principal and therefore evaluates
-- to NULL, and `client_id IS DISTINCT FROM NULL` is TRUE for every row on
-- this table (every row's `client_id` is a firm's real internal client, never
-- itself null) by definition of that operator. Only `assignment_scope`
-- (RESTRICTIVE) and the missing PERMISSIVE lane are the actual problem.
--
-- WHY THIS TAKES THE "262 SHAPE" (CLEAN DROP), NOT THE
-- "PORTAL_MESSAGES SHAPE" (KEEP THE BARE NAME ALIVE)
-- The sibling fix kept `portal_messages_assignment_scope`'s bare NAME alive
-- (narrowed to UPDATE only, its one command that needed no widening) because
-- migration 294's idempotent restore loop checks existence by
-- `policyname = tablename || '_assignment_scope'` for a NAMED set of EIGHT
-- tables that includes `portal_messages`, and dropping the name would let a
-- future out-of-band re-run of 294 silently recreate the exact FOR ALL policy
-- that fix retires. `customer_payment_links` is not one of those eight tables
-- and no migration anywhere else in this tree goes looking for
-- `customer_payment_links_assignment_scope` by that exact name — checked:
-- `grep -rl customer_payment_links apps/api/migrations/*.sql` finds only 110
-- (which declares it), 110's own rollback, and 194 (an unrelated DELETE
-- grant). That is exactly 294's own stated exception for why migration 262
-- could DROP `payroll_employees_assignment_scope` outright — "no earlier
-- migration's own logic still goes looking for it by that exact name" — so
-- this migration takes 262's shape: the FOR ALL restrictive policy is DROPPED
-- outright and replaced with clean per-command ones, rather than preserving a
-- name nothing else depends on.
--
-- THE SHAPE OF THE FIX
-- `public.my_portal_client_ids()` is declared here VERBATIM as the sibling
-- fix declares it (SECURITY DEFINER, reading BOTH the multi-contact link —
-- `client_portal_users`, migration 109 — and the legacy single-user link —
-- `clients.portal_user_id`, migration 048) so that whichever of the two
-- migrations lands first in the merged history, `CREATE OR REPLACE FUNCTION`
-- leaves the other's re-declaration a harmless no-op rather than a conflict
-- — both name the same global function with the same body. A second helper,
-- `public.my_portal_customer_ids()`, composes it through
-- `client_firm_customer_links` for the reason explained above.
--
--   * ONE new PERMISSIVE policy, `customer_payment_links_portal_client`,
--     mirroring migration 048's `portal_client_messages` shape (FOR ALL,
--     USING only — Postgres uses the USING expression as the WITH CHECK too
--     when a FOR ALL policy declares no WITH CHECK of its own), but on
--     `customer_id` rather than `client_id`. The portal side genuinely needs
--     SELECT (idempotent reuse), INSERT (create) and UPDATE (activate the
--     row it just created) — confirmed by reading `create_link` above — and
--     DELETE is not even GRANTed to `authenticated` on this table at all, so
--     FOR ALL costs nothing beyond what those three already need.
--   * The RESTRICTIVE `customer_payment_links_assignment_scope` is DROPPED
--     and replaced by FOUR per-command policies. SELECT, INSERT and UPDATE
--     each gain the portal-client OR-branch
--     (`customer_id IN (SELECT public.my_portal_customer_ids())`); DELETE
--     keeps `can_access_client((client_id)::text)` UNCHANGED, because nothing
--     anywhere — staff or portal — ever deletes a `customer_payment_links`
--     row (grep for it is empty) and the table's own GRANT (migration 110)
--     never included DELETE in the first place, so widening a write nobody
--     can even reach would be exactly the mistake this codebase's own
--     conventions warn against at migration 380: what a trusted rule may
--     propose stays unchanged even as matching widens, because widening a
--     write nobody uses only widens what happens with nobody watching.
--
-- BELT AND SUSPENDERS
-- Grants re-asserted idempotently — this environment cannot inspect
-- production's actual ACL, and grants have drifted from their own migrations
-- independently of any RLS question before (migration 194's whole premise).
--
-- ATOMIC, FOR THE SAME REASON AS THE SIBLING FIX
-- `apply_migrations.py` invokes `psql -f` WITHOUT --single-transaction, so a
-- failure partway through a DROP-then-CREATE sequence must not leave the
-- RESTRICTIVE policy dropped with nothing yet in its place. BEGIN/COMMIT
-- makes that impossible: the file fully applies or does nothing.
--
-- ⚠️ MIGRATION-NUMBER COLLISION RISK, FLAGGED FOR WHOEVER INTEGRATES THIS
-- This worktree's next free number was 438 when this fix was written, and 438
-- is already claimed by the sibling portal_messages fix on an unmerged
-- branch — do not reuse it. Checking every worktree and the main checkout
-- visible from here at the time of writing: 438 is the sibling's own
-- (unmerged) number; `main` has SINCE renumbered that same sibling fix to
-- 440, and `main` also already carries an unrelated 439
-- (fx_rates_can_be_written_under_the_per_user_jwt). 441 was the lowest number
-- confirmed free across every branch and worktree this session could see, but
-- it could not see every remote branch, so re-check `ls apps/api/migrations`
-- on the actual merge target before this lands and renumber if 441 has since
-- been claimed by other in-flight work.

BEGIN;

GRANT SELECT, INSERT, UPDATE ON public.customer_payment_links TO authenticated;
GRANT ALL ON public.customer_payment_links TO service_role;

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

-- One hop further than my_portal_client_ids(): the internal-customer id that
-- REPRESENTS this portal principal's own external client in the firm's
-- "Firm-as-Internal-Client" (G3) books — exactly what
-- `client_sales_invoices.customer_id` / `customer_payment_links.customer_id`
-- actually carry for a fee invoice, per the header above.
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

-- The portal-client lane: a PERMISSIVE policy of its own, since this table
-- (unlike portal_messages) never had one. FOR ALL / USING-only mirrors
-- migration 048's "portal_client_messages" shape, keyed on `customer_id`
-- rather than `client_id` for the reason explained in the header.
DROP POLICY IF EXISTS "customer_payment_links_portal_client" ON public.customer_payment_links;
CREATE POLICY "customer_payment_links_portal_client" ON public.customer_payment_links
  FOR ALL TO authenticated
  USING (customer_id IN (SELECT public.my_portal_customer_ids()));

-- The FOR ALL restrictive policy is DROPPED outright (the 262 shape — see the
-- header) and replaced by four per-command ones. UPDATE is widened alongside
-- SELECT and INSERT because create_link's own second write — activating the
-- link with the provider's short_url — runs on the row the portal client
-- just inserted, in the same session.
DROP POLICY IF EXISTS "customer_payment_links_assignment_scope" ON public.customer_payment_links;

CREATE POLICY "customer_payment_links_assignment_scope_select" ON public.customer_payment_links
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client((client_id)::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "customer_payment_links_assignment_scope_insert" ON public.customer_payment_links
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (
    public.can_access_client((client_id)::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

CREATE POLICY "customer_payment_links_assignment_scope_update" ON public.customer_payment_links
  AS RESTRICTIVE FOR UPDATE
  USING (
    public.can_access_client((client_id)::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  )
  WITH CHECK (
    public.can_access_client((client_id)::text)
    OR customer_id IN (SELECT public.my_portal_customer_ids())
  );

-- DELETE stays exactly as migration 110 declared it inside the old FOR ALL
-- policy: nothing anywhere deletes a customer_payment_links row, and the
-- table's own GRANT never included DELETE, so there is nothing to widen here.
CREATE POLICY "customer_payment_links_assignment_scope_delete" ON public.customer_payment_links
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client((client_id)::text));

COMMIT;

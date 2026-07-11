-- Migration 194 — systematic sweep for the same grant gap as 192/193
--
-- Both prior fixes (service_catalogue/firm_hsn_library/credit_note_
-- allocations/debit_note_allocations in 192, debit_notes/debit_note_lines in
-- 193) turned out to be instances of the same recurring authoring mistake:
-- an RLS policy is written scoped to `authenticated` for some command, but
-- the base table-level GRANT for that command is never issued alongside it.
-- Postgres checks the GRANT before RLS is even evaluated, so the policy's
-- intent is silently unreachable — every such table has been quietly broken
-- for the per-user-JWT path (USE_USER_JWT) since whenever it was added,
-- surfacing only when a user happens to hit that specific operation.
--
-- Found by comparing every RLS policy naming `authenticated` against actual
-- information_schema.role_table_grants — this is every table where that
-- comparison shows a gap (18 tables), not a guess. Two (fx_adjustments,
-- fx_revaluations) were missing ALL FOUR base privileges — entirely
-- unreachable via the per-user-JWT path, not just for one operation.
--
-- Deliberately NOT touched: any table where the authenticated-scoped policy
-- doesn't exist at all — those were reviewed separately (see migration 192's
-- note) and many look like intentional backend/service-role-only write
-- boundaries (the ledger, audit trail, auth tables). This migration only
-- closes gaps against policies that already exist and already name
-- `authenticated` — i.e. access the platform's own RLS already says should
-- be allowed.

GRANT DELETE, UPDATE                  ON public.activity_logs                TO authenticated;
GRANT DELETE, UPDATE                  ON public.automation_executions        TO authenticated;
GRANT SELECT                          ON public.currencies                   TO authenticated;
GRANT DELETE                          ON public.customer_payment_events      TO authenticated;
GRANT DELETE                          ON public.customer_payment_links       TO authenticated;
GRANT DELETE                          ON public.customer_payments            TO authenticated;
GRANT DELETE                          ON public.customer_statement_deliveries TO authenticated;
GRANT UPDATE                          ON public.fee_invoices                 TO authenticated;
GRANT DELETE, INSERT, UPDATE          ON public.fixed_assets                 TO authenticated;
GRANT DELETE, INSERT, SELECT, UPDATE  ON public.fx_adjustments               TO authenticated;
GRANT SELECT                          ON public.fx_rates                    TO authenticated;
GRANT DELETE, INSERT, SELECT, UPDATE  ON public.fx_revaluations              TO authenticated;
GRANT DELETE                          ON public.hsn_sac_preferences          TO authenticated;
GRANT DELETE                          ON public.invoice_deliveries           TO authenticated;
GRANT DELETE                          ON public.ledger_balances              TO authenticated;
GRANT DELETE                          ON public.portal_messages              TO authenticated;
GRANT DELETE                          ON public.reminder_settings            TO authenticated;
GRANT UPDATE                          ON public.users                        TO authenticated;

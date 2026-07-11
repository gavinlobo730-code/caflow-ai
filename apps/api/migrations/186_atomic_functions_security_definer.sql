-- Migration 186: mark the atomic multi-table posting RPCs SECURITY DEFINER.
--
-- post_journal_atomic (152), settle_receipt_atomic (160/162),
-- numbered_document_atomic (167), and record_fee_receipt_atomic (172) were
-- all created SECURITY INVOKER (the Postgres default) — every OTHER RPC this
-- backend calls (next_invoice_number, get_cash_payments_above_threshold,
-- increment_message_count, platform_purge_firm) is correctly SECURITY
-- DEFINER, so this looks like a one-off omission on these four rather than
-- a deliberate choice.
--
-- The backend's Supabase client authenticates PostgREST calls as the
-- `authenticated` role (a plain user JWT), which has direct table grants on
-- e.g. client_sales_invoices/client_sales_invoice_lines/receipts (so plain
-- .table() inserts work fine) but NOT on journal_entries, journal_lines,
-- client_credit_notes, client_debit_notes, or fee_receipts — those are
-- intentionally writable only via these controlled RPCs. Invoked
-- SECURITY INVOKER, the function's own INSERT executes as the CALLING
-- role, so it hits "permission denied for table journal_entries" (etc.)
-- the moment a real (non-service_role) user calls it — confirmed live via
-- the project's postgres logs, which show exactly this error at every
-- Issue-invoice attempt. This breaks: issuing a Sales Invoice (posts a
-- journal), creating a Credit/Debit Note (manual numbering), recording a
-- Fee Receipt, and settling a customer Receipt or vendor Payment (also
-- posts a journal) — i.e. most of the platform's actual money-movement
-- endpoints.
--
-- All four already SET search_path (public, pg_catalog) — the standard
-- SECURITY DEFINER search_path-hijack mitigation — so adding SECURITY
-- DEFINER here is safe; RBAC authorization is still enforced at the FastAPI
-- route layer before any of these RPCs is ever invoked.

ALTER FUNCTION public.post_journal_atomic(jsonb, jsonb) SECURITY DEFINER;
ALTER FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) SECURITY DEFINER;
ALTER FUNCTION public.numbered_document_atomic(text, jsonb, text, jsonb, text) SECURITY DEFINER;
ALTER FUNCTION public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text) SECURITY DEFINER;

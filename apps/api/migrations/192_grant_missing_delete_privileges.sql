-- Migration 192 — grant missing table-level privileges to `authenticated`
--
-- Discovered live: Product/Service hard-delete failed with a generic error
-- ("Unable to delete the service. Please try again.") for every attempt,
-- regardless of usage. Root cause confirmed via postgres logs:
-- "permission denied for table service_catalogue" — a plain GRANT gap, not
-- an RLS policy problem. service_catalogue and firm_hsn_library both already
-- have RLS policies covering ALL commands (including DELETE) for
-- `authenticated`, but the table-level GRANT for DELETE was never issued —
-- so every hard-delete attempt through the per-user-JWT path (USE_USER_JWT)
-- was rejected by Postgres before RLS was even evaluated. Both are affected:
-- service_catalogue (routers/service_catalogue.py delete_service, pre-
-- existing) and firm_hsn_library (routers/firm_hsn_library.py purge_code,
-- added this session — same gap, caught before it shipped further).
--
-- credit_note_allocations / debit_note_allocations are a related but
-- distinct gap: both already have an RLS policy scoped to `authenticated`
-- for ALL commands, but were missing EVERY base grant (SELECT/INSERT/
-- UPDATE/DELETE) — not just DELETE. That mismatch (a policy written for
-- access that was never actually granted) indicates an oversight, not an
-- intentional restriction, so it's fixed alongside the other two here.
--
-- Deliberately NOT touched: several other tables (journal_entries,
-- journal_lines, audit_log, login_events, users, capital_gains, and more)
-- also show incomplete `authenticated` grants, but many of those look like
-- intentional backend/service-role-only write boundaries (the ledger,
-- audit trail, and auth tables should not be directly writable by ordinary
-- user requests). Those need individual review, not a blanket grant, and
-- are out of scope for this fix.

GRANT DELETE ON public.service_catalogue TO authenticated;
GRANT DELETE ON public.firm_hsn_library TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.credit_note_allocations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.debit_note_allocations TO authenticated;

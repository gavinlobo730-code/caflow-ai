-- Migration 193 — grant missing table-level privileges: debit_notes,
-- debit_note_lines
--
-- Found live while verifying migration 192's fix: the very next attempt to
-- delete a Product/Service that's used on a debit note failed with
-- "permission denied for table debit_note_lines". Same root cause as 192 —
-- both tables already have an RLS policy scoped to `authenticated` for ALL
-- commands (firm_debit_notes, firm_debit_note_lines), but the base GRANT was
-- never issued, so every access via the per-user-JWT path (USE_USER_JWT) was
-- rejected by Postgres before RLS was even evaluated. credit_notes /
-- credit_note_lines already had full grants — debit_notes was apparently
-- added or migrated separately and the grant step was missed.

GRANT SELECT, INSERT, UPDATE, DELETE ON public.debit_notes TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.debit_note_lines TO authenticated;

-- Migration 238: scope advance_tax_payments' uniqueness by firm_id too.
--
-- Task #230 audit finding: routers/income_tax.py::save_advance_tax accepted a
-- caller-supplied client_id with no ownership check (fixed in the same task
-- via assert_client_access), but the table's own UNIQUE(client_id,
-- financial_year, installment_number) constraint (migration 035) never
-- included firm_id — the exact same on_conflict key the upsert used. Even
-- with the app-level check now in place, this is the correct schema shape
-- for a firm-scoped table (every sibling table in this codebase — invoices,
-- bills, journal entries — keys its per-client uniqueness by (firm_id,
-- client_id, ...), never client_id alone), and closes the gap for any other
-- future write path into this table.
--
-- RLS on this table is not the enforcement layer for backend writes (the API
-- always uses the SERVICE_ROLE client, which bypasses RLS — see
-- core/supabase_client.py) — the UNIQUE index is the real backstop, same
-- role migration 151 (sales invoice numbers) and 224 (bank import hashes)
-- play for their respective tables.

-- Postgres auto-generates the UNIQUE constraint's name (truncated to fit the
-- 63-byte identifier limit), so locate it by column signature (set equality,
-- independent of declaration order) rather than guessing the literal name.
DO $$
DECLARE
  con_name text;
BEGIN
  SELECT con.conname INTO con_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  WHERE rel.relname = 'advance_tax_payments'
    AND con.contype = 'u'
    AND (SELECT array_agg(k ORDER BY k) FROM unnest(con.conkey) k)
      = (
        SELECT array_agg(attnum ORDER BY attnum)
        FROM pg_attribute
        WHERE attrelid = rel.oid
          AND attname IN ('client_id', 'financial_year', 'installment_number')
      );
  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.advance_tax_payments DROP CONSTRAINT %I', con_name);
  END IF;
END $$;

ALTER TABLE public.advance_tax_payments
  ADD CONSTRAINT advance_tax_payments_firm_client_fy_installment_key
  UNIQUE (firm_id, client_id, financial_year, installment_number);

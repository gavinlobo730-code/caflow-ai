-- Rollback for Migration 111: remove the generic database-level audit triggers.
-- Drops trg_audit_capture from every table that has it, then the function.
-- Existing audit_log rows are preserved (the table is append-only).

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.relname AS table_name
    FROM pg_trigger tg
    JOIN pg_class c ON c.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE tg.tgname = 'trg_audit_capture' AND n.nspname = 'public'
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_audit_capture ON public.%I', r.table_name);
  END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.audit_capture();
DROP FUNCTION IF EXISTS public.audit_capture_firm();

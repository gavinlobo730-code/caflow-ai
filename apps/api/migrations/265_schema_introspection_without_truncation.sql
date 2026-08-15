-- Migration 265: schema introspection that cannot be silently truncated.
--
-- THE BUG THIS FIXES
--     get_public_columns() (migration 242) RETURNS TABLE — one row per column.
--     This database has 3531 columns in the public schema, and PostgREST caps a
--     response at db-max-rows, which is 1000 here. So core/schema_guard.py asked
--     for the schema, received the first 1000 rows, and treated that slice as
--     the COMPLETE schema. Every column past the cut looked absent.
--
--     Measured on the live database, in the row order the function returns:
--
--         bank_reconciliations.reopen_count      row  218   -> seen
--         form_26as_uploads.parse_errors         row  922   -> seen
--         clients.firm_id                        row 1277   -> "missing"
--         bank_reconciliations.reopen_reason     row 2791   -> "missing"
--         form_26as_uploads.parse_status         row 3073   -> "missing"
--
--     The cut lands mid-table — parse_errors is "present" while parse_status on
--     the same table is "missing" — which is the signature of a row limit rather
--     than of real drift.
--
--     Consequence: /health returned 503 on every boot since the guard shipped,
--     naming 401 columns that all exist. clients.firm_id is among them, and the
--     entire tenant-isolation RLS policy set is built on it. A check that is
--     always red cannot be acted on, so Render's health gate — had it been wired
--     up — could never have let a deploy through, and real drift would have been
--     indistinguishable from the noise.
--
-- WHY A NEW FUNCTION RATHER THAN AN ORDER BY + PAGING
--     Paging needs a stable total order, and information_schema.columns has no
--     guaranteed one; a row that shifts between pages is silently dropped, which
--     reproduces the same false-drift report with extra steps. A single row
--     cannot be truncated by a row limit at all, so the failure mode is removed
--     rather than made less likely.
--
-- WHY THE PAYLOAD COUNTS ITSELF
--     `total_columns` is computed independently of `tables`, so the caller can
--     verify it received everything by counting what it parsed and comparing.
--     That turns any FUTURE truncation — a different cap, a proxy, a partial
--     read — into a detected error instead of a confident wrong answer. The
--     original bug was not that the read was capped; it was that a capped read
--     was indistinguishable from a complete one.
--
-- get_public_columns() from migration 242 is left in place: dropping it would
-- break any deploy still running the previous image mid-rollout, and it costs
-- nothing to keep. core/schema_guard.py no longer calls it.

BEGIN;

CREATE OR REPLACE FUNCTION public.get_public_schema_columns()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_catalog
STABLE
AS $$
  SELECT jsonb_build_object(
    -- Counted independently of the map below so the two can be cross-checked.
    'total_columns', (
      SELECT count(*)
      FROM information_schema.columns
      WHERE table_schema = 'public'
    ),
    'tables', COALESCE((
      SELECT jsonb_object_agg(t, cols)
      FROM (
        SELECT c.table_name::text AS t,
               jsonb_agg(c.column_name::text ORDER BY c.column_name) AS cols
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        GROUP BY c.table_name
      ) grouped
    ), '{}'::jsonb)
  );
$$;

COMMENT ON FUNCTION public.get_public_schema_columns() IS
    'Read-only schema introspection for the boot-time schema-drift guard '
    '(core/schema_guard.py). Returns ONE jsonb row: {"total_columns": int, '
    '"tables": {table: [column, ...]}}. Single-row on purpose — the previous '
    'row-per-column function (get_public_columns, migration 242) was silently '
    'truncated to PostgREST''s 1000-row cap against this schema''s 3531 columns, '
    'so the guard reported 401 existing columns as missing and failed /health on '
    'every boot. total_columns lets the caller prove it received the whole map.';

GRANT EXECUTE ON FUNCTION public.get_public_schema_columns() TO authenticated, service_role;

COMMIT;

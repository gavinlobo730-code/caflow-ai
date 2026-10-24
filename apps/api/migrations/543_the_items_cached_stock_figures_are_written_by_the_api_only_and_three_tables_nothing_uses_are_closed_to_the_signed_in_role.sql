-- Migration 543 — the cached stock figures of an item are written by the API only, and three tables nothing uses are closed to the
-- signed-in role (POST-A-327, POST-A-333).
--
-- WHAT WAS WRONG
--   * service_catalogue.stock_qty_units, avg_cost_paise and stock_version are a copy of the stock ledger's last row, rewritten by every
--     movement. The signed-in role holds UPDATE on the table (migrations 176 and 194; production read on 23-10-2026: authenticated
--     arwdDxtm, every grant made by postgres) with only the assignment scope between a member and the row, so a member assigned to the
--     client could set the copy to any figure over PostgREST. Closing stock is summed from the ledger's deltas and ties to the
--     Inventory control account, and the stock register, the reorder level check and the next movement's cost read the LEDGER, so the
--     books were not affected; what reads the copy is the catalogue's Stock column, the product form's "stock already started" gate,
--     the item block of the item ledger and the stock reconciliation, until a movement rewrites it. The writers had to be on the
--     privileged client first: the compare-and-set of a movement, its restore after a refused ledger insert and the opening-stock
--     batch's upsert are, since the change that shipped before this migration (the privileged client names the firm and the client in
--     each of them).
--   * A signed-in member assigned to a client can DELETE an item (service_catalogue) outright, and the foreign key from the stock
--     ledger is ON DELETE CASCADE, so the item's stock ledger rows go with it, with no reversal of the Inventory control journal that
--     posted them (found by the independent review of this change and reproduced). The API refuses to delete an item that has a stock
--     movement or a real document line (routers/service_catalogue.py delete_service); the database did not.
--   * activity_logs, ai_evidence and ai_signals have no reader and no writer anywhere in the API or the browser (the table-use scanner
--     finds a retention-position tuple for the first and nothing for the other two; production holds no row in any of them), yet the
--     signed-in role holds every write verb on all three (production ACL, 23-10-2026: authenticated arwdDxtm, anon Dxtm, every grant
--     made by postgres). Migration 540 guarded their client_id with a trigger because a trigger leaves the grants as they are; the
--     cleaner end state is the one migrations 505 and 538 gave other unused tables.
--
-- WHAT THIS DOES (one transaction)
--   * public.refuse_a_signed_in_edit_of_the_items_cached_stock(): a trigger function on service_catalogue, BEFORE INSERT OR UPDATE OF stock_qty_units, avg_cost_paise,
--     stock_version, judging only a signed-in session (current_setting('role') authenticated or anon; the privileged client, the
--     database owner and the firm purge are not judged):
--       - UPDATE: refuses a change of any of the three columns (a statement that names one and sends the value the row already holds
--         is not a change, and a statement that names none never runs the trigger);
--       - INSERT: refuses an item created with a figure other than the column default (0, 0, 0), because an item born with a forged copy
--         is the same forgery. The API creates an item with the defaults and seeds its opening stock through the privileged client.
--     A catalogue edit of anything else (the name, the rate, the HSN, the reorder level) is untouched. EXECUTE is revoked from the
--     signed-in roles.
--   * public.refuse_a_signed_in_delete_of_an_item_with_stock_history(): BEFORE DELETE on service_catalogue, refusing a signed-in session's
--     delete of an item that has a row in the stock ledger (the API's own rule, which the cascade made optional). A delete of an item
--     with no stock history is untouched, and so is a delete made by a foreign-key action (the firm purge runs with triggers off).
--   * Both triggers are created with CREATE OR REPLACE TRIGGER inside one DO block that first takes the table lock without queueing
--     (NOWAIT, retried for up to 15 seconds), the shape of migration 541. CREATE OR REPLACE TRIGGER takes SHARE ROW EXCLUSIVE whether
--     or not the trigger exists (measured on 16); a DROP TRIGGER of an existing trigger would take ACCESS EXCLUSIVE, which on a
--     re-apply queues behind every reader and can deadlock a transaction that reads and then writes.
--   * activity_logs, ai_evidence and ai_signals: REVOKE ALL from authenticated, anon and PUBLIC, and the service role's four privileges
--     granted explicitly. Migration 540's triggers on them stay as a second lock.
--   * A closing DO block checks it: the trigger (table, event, function, enabled, tgtype 23 and exactly the three columns), the function
--     not executable by a signed-in role, and the effective privileges (table, column, through PUBLIC) of authenticated and anon on the
--     three tables, with the service role's writes kept.
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--   * The cache is still a copy that a bug can leave wrong: the reconciliation names a disagreement and a movement rewrites it.
--   * A privileged writer that sets the three columns for an item that is not its client's is not stopped by the database; the three
--     writers name the firm and the client (a guard test holds that).
--   * An item with NO stock history can still be deleted by a signed-in member although a document line may name it (the foreign
--     keys from the lines are ON DELETE SET NULL, so the lines keep their text and lose only the link); the API refuses that too, and
--     it is the smaller harm.
--   * No row is changed and no table is dropped.
--
-- DEPLOY ORDER
--   The writers of the three columns moved to the privileged client in the change that precedes this one. An API instance that still
--   writes them under the caller's sign-in fails soft and wrong against this migration: a movement's compare-and-set is refused with
--   42501, which is not a version conflict, so it propagates before any ledger row or stock journal is written and the callers swallow
--   stock failures by design, so the movement is LOST silently; the opening-stock batch inserts its ledger rows and caches nothing.
--   So that change was merged and running on Render for at least an hour before this one.
--
-- Idempotent (CREATE OR REPLACE for the functions and the triggers, REVOKE/GRANT). Reversible: 543_the_items_cached_stock_figures_are_written_by_the_api_only_and_three_tables_nothing_uses_are_closed_to_the_signed_in_role_rollback.sql.

SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_edit_of_the_items_cached_stock()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
  v_role text := COALESCE(current_setting('role', true), 'none');
BEGIN
  IF v_role NOT IN ('authenticated', 'anon') THEN
    RETURN NEW;
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.stock_qty_units IS DISTINCT FROM 0 OR NEW.avg_cost_paise IS DISTINCT FROM 0 OR NEW.stock_version IS DISTINCT FROM 0 THEN
      RAISE EXCEPTION 'The cached stock of an item (quantity, average cost, version) is written by the stock ledger and cannot be set from a signed-in session: create the item without it and record an opening balance. Nothing was saved.'
        USING ERRCODE = '42501';
    END IF;
  ELSIF NEW.stock_qty_units IS DISTINCT FROM OLD.stock_qty_units
     OR NEW.avg_cost_paise IS DISTINCT FROM OLD.avg_cost_paise
     OR NEW.stock_version IS DISTINCT FROM OLD.stock_version THEN
    RAISE EXCEPTION 'The cached stock of an item (quantity, average cost, version) is written by the stock ledger and cannot be changed from a signed-in session: record a stock movement or an adjustment instead. Nothing was changed.'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_edit_of_the_items_cached_stock() IS
  'POST-A-327. A signed-in session may not set or change service_catalogue.stock_qty_units, avg_cost_paise or stock_version: they '
  'are a copy of the stock ledger''s last row, written by the API''s privileged client. Migration 543.';

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_edit_of_the_items_cached_stock() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_delete_of_an_item_with_stock_history()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  -- a foreign-key action (a cascade from a parent) runs one trigger level deeper than a statement and is not judged
  IF COALESCE(current_setting('role', true), 'none') IN ('authenticated', 'anon')
     AND pg_trigger_depth() <= 1
     AND EXISTS (SELECT 1 FROM public.inventory_stock_ledger l WHERE l.service_catalogue_id = OLD.id) THEN
    RAISE EXCEPTION 'An item that has stock movements cannot be deleted from a signed-in session: its stock ledger would go with it. Archive the item instead. Nothing was deleted.'
      USING ERRCODE = '42501';
  END IF;
  RETURN OLD;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_delete_of_an_item_with_stock_history() IS
  'POST-A-327 (found in its review). A signed-in session may not delete a service_catalogue row that has stock ledger rows: the '
  'foreign key is ON DELETE CASCADE, so the stock history would go with it. Migration 543.';

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_delete_of_an_item_with_stock_history() FROM PUBLIC, anon, authenticated;

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  -- the lock is asked for without queueing and retried (see the header), so a write in flight is waited for and nothing queues behind us;
  -- SHARE ROW EXCLUSIVE is what CREATE OR REPLACE TRIGGER takes, so nothing below asks for a stronger lock than the one held
  LOOP
    BEGIN
      LOCK TABLE public.service_catalogue IN SHARE ROW EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'migration 543: could not lock public.service_catalogue in 15 seconds (a transaction is writing it); run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  CREATE OR REPLACE TRIGGER an_items_cached_stock_is_not_edited_from_a_signed_in_session
    BEFORE INSERT OR UPDATE OF stock_qty_units, avg_cost_paise, stock_version ON public.service_catalogue
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_the_items_cached_stock();

  CREATE OR REPLACE TRIGGER an_item_with_stock_history_is_not_deleted_from_a_signed_in_session
    BEFORE DELETE ON public.service_catalogue
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_delete_of_an_item_with_stock_history();
END $apply$;

-- ── the three tables nothing uses ───────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['activity_logs', 'ai_evidence', 'ai_signals'] LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE EXCEPTION 'migration 543: public.% should exist', t;
    END IF;
    EXECUTE format('REVOKE ALL ON public.%I FROM authenticated, anon, PUBLIC', t);
    -- the service role's own privileges are explicit, so that nothing above can have removed them through PUBLIC
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);
  END LOOP;
END $$;

-- ── check it ─────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  t text;
  v_priv text;
BEGIN
  IF NOT EXISTS (
       SELECT 1 FROM pg_trigger g
        WHERE g.tgname = 'an_items_cached_stock_is_not_edited_from_a_signed_in_session'
          AND g.tgrelid = 'public.service_catalogue'::regclass
          AND g.tgfoid = 'public.refuse_a_signed_in_edit_of_the_items_cached_stock()'::regprocedure
          AND NOT g.tgisinternal AND g.tgenabled = 'O'
          AND g.tgtype = 23                                  -- ROW, BEFORE, INSERT, UPDATE
          AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                 FROM unnest(g.tgattr) AS k(num) JOIN pg_attribute a ON a.attrelid = g.tgrelid AND a.attnum = k.num)
              = ARRAY['avg_cost_paise', 'stock_qty_units', 'stock_version']) THEN
    RAISE EXCEPTION 'migration 543: the cached-stock trigger on public.service_catalogue is missing, disabled or is not the one written';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM pg_trigger g
        WHERE g.tgname = 'an_item_with_stock_history_is_not_deleted_from_a_signed_in_session'
          AND g.tgrelid = 'public.service_catalogue'::regclass
          AND g.tgfoid = 'public.refuse_a_signed_in_delete_of_an_item_with_stock_history()'::regprocedure
          AND NOT g.tgisinternal AND g.tgenabled = 'O'
          AND g.tgtype = 11) THEN                            -- ROW, BEFORE, DELETE
    RAISE EXCEPTION 'migration 543: the stock-history delete trigger on public.service_catalogue is missing, disabled or is not the one written';
  END IF;
  IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_edit_of_the_items_cached_stock()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_edit_of_the_items_cached_stock()', 'EXECUTE')
     OR has_function_privilege('authenticated', 'public.refuse_a_signed_in_delete_of_an_item_with_stock_history()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_delete_of_an_item_with_stock_history()', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 543: a signed-in role can execute a trigger function of this migration';
  END IF;

  FOREACH t IN ARRAY ARRAY['activity_logs', 'ai_evidence', 'ai_signals'] LOOP
    FOR v_priv IN SELECT unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) LOOP
      IF has_table_privilege('authenticated', 'public.' || t, v_priv) OR has_table_privilege('anon', 'public.' || t, v_priv) THEN
        RAISE EXCEPTION 'migration 543: the signed-in or anonymous role can still % public.%', v_priv, t;
      END IF;
    END LOOP;
    IF has_any_column_privilege('authenticated', 'public.' || t, 'SELECT, INSERT, UPDATE, REFERENCES')
       OR has_any_column_privilege('anon', 'public.' || t, 'SELECT, INSERT, UPDATE, REFERENCES') THEN
      RAISE EXCEPTION 'migration 543: a column privilege on public.% is still held by the signed-in or anonymous role', t;
    END IF;
    FOREACH v_priv IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
      IF NOT has_table_privilege('service_role', 'public.' || t, v_priv) THEN
        RAISE EXCEPTION 'migration 543: the service role lost % on public.%', v_priv, t;
      END IF;
    END LOOP;
  END LOOP;
END $$;

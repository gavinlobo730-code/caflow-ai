-- Rollback of migration 580: give back the ledger entries exactly what they carried before it stamped them (POST-A-372).
--
-- It undoes the entries migration 580's own audit rows name, and nothing else: an entry stamped by any other means (the posting kernel,
-- a later migration) has no such row and is never touched. For each named entry it puts back the source the row recorded as the old
-- one, and only while the entry still carries exactly what migration 580 gave it (so a second run, or an entry that has changed since,
-- is left alone). For the vendor-payment entry the old source_type is the one it always had, so in effect only source_id goes back.
-- Like the migration it writes one audit row per entry it changes (metadata source 'migration 580 rollback', which the migration's
-- own rows do not match, so this cannot undo itself), and it runs under the same transaction-local allowance, set and cleared here.
-- Run it only if the stamp has to come off: the customer-wise and vendor-wise breakdowns of the control accounts go back to showing
-- these entries as unattributed.
BEGIN;

DO $$
DECLARE
    v_undone int;
BEGIN
    PERFORM set_config('app.journal_edit', 'on', true);

    WITH named AS (
        SELECT a.entity_id::uuid AS entry_id, a.firm_id,
               NULLIF(a.old_data->>'source_type', '') AS old_type,
               NULLIF(a.old_data->>'source_id', '')::uuid AS old_id,
               NULLIF(a.new_data->>'source_type', '') AS new_type,
               NULLIF(a.new_data->>'source_id', '')::uuid AS new_id
          FROM public.audit_log a
         WHERE a.entity_type = 'journal_entry' AND a.action = 'update' AND a.metadata->>'source' = 'migration 580'
    ), undo AS (
        UPDATE public.journal_entries j
           SET source_type = n.old_type, source_id = n.old_id
          FROM named n
         WHERE j.id = n.entry_id AND j.firm_id = n.firm_id
           AND j.source_type IS NOT DISTINCT FROM n.new_type
           AND j.source_id IS NOT DISTINCT FROM n.new_id
        RETURNING j.id AS entry_id, j.firm_id, n.old_type, n.old_id, n.new_type, n.new_id
    ), logged AS (
        INSERT INTO public.audit_log (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
        SELECT u.firm_id, NULL, NULL, 'journal_entry', u.entry_id::text, 'update',
               jsonb_build_object('source_type', u.new_type, 'source_id', u.new_id),
               jsonb_build_object('source_type', u.old_type, 'source_id', u.old_id),
               jsonb_build_object('source', 'migration 580 rollback',
                                  'reason', 'the stamp migration 580 gave this entry was taken off again')
          FROM undo u
        RETURNING 1
    )
    SELECT count(*) INTO v_undone FROM undo;

    PERFORM set_config('app.journal_edit', '', true);

    RAISE WARNING 'migration 580 rollback: % ledger entr(ies) are back to carrying the source they had before the stamp', v_undone;
END $$;

COMMIT;

-- Migration 775: the two columns the guided tips used are dropped (ledger POST-A-541).
--
-- Migration 774 added `users.guided_tips_on` and `users.guided_tips_seen` on 21-11-2026 for the guided tips (POST-A-531). The owner tried the
-- tips on the live Test Firm the same morning and asked for a guide a person can ask instead; the "Where is…?" guide replaced them (POST-A-538)
-- and that change removed everything that read or wrote these columns: the route `/api/guided-tips`, its service, and the screens' own calls.
-- Since then the two columns hold nothing anybody reads. The owner's instruction of 21-11-2026 was to remove them now.
--
-- WHAT IS LOST: whether a person had turned the tips off, and which tips they had closed. Neither means anything without the tips. No firm's
-- data, no client's data and no figure is in either column.
--
-- ORDER MATTERS, AND IT IS HELD BY THE MERGE ORDER: this migration applies to production when it is merged, so it is merged only after the
-- change that removed the readers (POST-A-538) is merged and deployed. An API still serving `/api/guided-tips` against a database without
-- these columns would answer that route with an error.
--
-- IF EXISTS, so a database that never had them (one built before 774, or rolled back) takes this as a no-op.

ALTER TABLE public.users DROP COLUMN IF EXISTS guided_tips_seen;
ALTER TABLE public.users DROP COLUMN IF EXISTS guided_tips_on;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                  AND column_name IN ('guided_tips_on', 'guided_tips_seen')) THEN
        RAISE EXCEPTION 'migration 775: a guided-tips column is still on public.users';
    END IF;
END $$;

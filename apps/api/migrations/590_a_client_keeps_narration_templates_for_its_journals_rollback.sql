-- Rollback of migration 590: drop the narration templates. They are words a practice saved for reuse; no entry, figure or return reads
-- them (an entry stores its own narration), so dropping the table loses the saved words and nothing else. The firm checks installed on
-- it by `guard_client_firm` and `guard_member_firm` are triggers on this table and go with it. Safe to run twice.

DROP TABLE IF EXISTS public.journal_narration_templates;

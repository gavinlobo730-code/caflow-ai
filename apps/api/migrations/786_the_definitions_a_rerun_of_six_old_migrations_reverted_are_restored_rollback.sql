-- Rollback of migration 786: nothing, on purpose.
--
-- Migration 786 restates definitions that migrations 546 (post_journal_atomic), 768 (my_portal_client_ids) and 526 (the
-- assignment-scope policies) had already made, after a second run of six old migrations undid them on production. On a database
-- built from the migrations it changes nothing, so there is nothing of its own to take away, and "undoing" it on production would
-- mean putting the fault back: a ledger function that asks nobody who is calling. To go back further than 786, use the rollback
-- of the migration whose definition is in question (546, 768 or 526).
SELECT 1;

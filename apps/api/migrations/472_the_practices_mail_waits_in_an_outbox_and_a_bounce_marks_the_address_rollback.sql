-- Rollback for 472. DISCARDS every queued message and the suppression list.
--
-- Messages still waiting in the outbox are lost (they are the practice's own
-- notices, and the sweeps that raised them can raise them again once their log
-- rows are not blocking: practice_email_log rows recorded as `sent` for a message
-- that was still queued would keep a sweep from re-sending it, so DELETE the
-- `detail = 'queued for delivery'` rows with `status = 'sent'` too if you roll
-- back while anything is queued).
--
-- The suppression list is the product's only memory of an address that bounced.
-- Rolling back forgets it, and the next sweep mails those addresses again.
--
-- The API treats a MISSING outbox as "mail goes out synchronously, as before 472",
-- so rolling the database back first is safe; roll the code back with this file if
-- you want the queueing to stop being attempted.

BEGIN;

DROP FUNCTION IF EXISTS public.claim_email_outbox(integer, integer);
DROP TABLE IF EXISTS public.email_suppressions;
DROP TABLE IF EXISTS public.email_outbox;

COMMIT;

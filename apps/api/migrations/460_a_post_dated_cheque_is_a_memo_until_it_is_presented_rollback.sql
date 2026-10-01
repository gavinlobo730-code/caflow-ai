-- Rollback for 460.
--
-- ⚠️ EVERY ROW IS A CHEQUE A CLIENT HOLDS OR HAS ISSUED, and nothing can
-- re-derive one — the cheque number, date and drawee bank are on a piece of
-- paper. A CONVERTED row also records which receipt or payment it became, which
-- is the only link back from that document to the cheque. Export before running
-- this:
--
--   SELECT * FROM public.post_dated_cheques;
--
-- Dropping the table posts nothing and reverses nothing: a converted cheque's
-- receipt or payment is an ordinary document and stays exactly as it is.

DROP TABLE IF EXISTS public.post_dated_cheques;

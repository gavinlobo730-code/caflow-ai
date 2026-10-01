-- Rollback for 462 — job work comes back in lots (GST-30).
--
-- Dropping this table LOSES every recorded return of goods sent for job work:
-- how much came back, when, under which of the job worker's challans, and what
-- was lost or wasted. Nothing else holds it. And it changes what is OWED: a
-- challan whose goods were brought back in lots through this table has had its
-- `received_back_on` stamped when the last lot came in, but a challan that is
-- still PART returned would, once the rows are gone, read as having NOTHING
-- returned — and CGST s.143(3) then deems the whole of it supplied on the day it
-- left, with interest, when only part of it is outstanding.
--
-- So this REFUSES while any job-work challan has a recorded return and is not
-- yet marked wholly received back. To roll back deliberately: record the
-- remaining lots, or mark each such challan received back through the challan
-- screen (which holds the one date), then run this. Export first:
--   SELECT * FROM public.delivery_challan_returns;

BEGIN;

DO $$
DECLARE n BIGINT;
BEGIN
  SELECT count(DISTINCT r.challan_id) INTO n
    FROM public.delivery_challan_returns r
    JOIN public.delivery_challans c ON c.id = r.challan_id
   WHERE c.received_back_on IS NULL
     AND c.status IN ('draft', 'issued');
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 462: % job-work challan(s) are part returned and not '
      'marked received back. Dropping the returns would make each read as having '
      'nothing returned, and CGST s.143(3) would then deem all of it supplied on '
      'the day it left. Record the rest or mark each received back first.', n;
  END IF;
END $$;

DROP TABLE IF EXISTS public.delivery_challan_returns;

COMMIT;

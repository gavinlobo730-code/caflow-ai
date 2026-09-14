-- Rollback for 388.
--
-- REFUSES while any document exists. These are STATUTORY records the recipient
-- issued under CGST Act s.31(3), and on an inward supply from an unregistered
-- person the self-invoice is the document the input credit rests on (Rule
-- 36(1)(b) with s.16(2)(a)). Dropping the table would destroy the evidence for
-- a credit already claimed on a filed return, which is not something a rollback
-- may do quietly. Same shape as 386's.
DO $$
DECLARE n bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'rcm_documents') THEN
    SELECT count(*) INTO n FROM public.rcm_documents WHERE deleted_at IS NULL;
    IF n > 0 THEN
      RAISE EXCEPTION
        'Refusing to roll back 388: % reverse-charge document(s) exist. The '
        's.31(3)(f) self-invoice is the document Rule 36(1)(b) makes the input '
        'credit rest on. Export them before dropping the table.', n;
    END IF;
  END IF;
END $$;

DROP TABLE IF EXISTS public.rcm_documents;

-- The recorded registration status goes too. It is a fact somebody entered, so
-- dropping it loses work — but it exists only for s.31(3)(f) and nothing else
-- reads it.
ALTER TABLE public.vendors DROP CONSTRAINT IF EXISTS vendors_gst_registration_status_check;
ALTER TABLE public.vendors DROP COLUMN IF EXISTS gst_registration_status;

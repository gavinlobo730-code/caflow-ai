-- Rollback for 395.
--
-- REFUSES while any determination exists. These rows are the employer's own
-- §10/§11 computation and their §9 dismissals — facts nothing else in the
-- product holds and nobody can re-derive, so dropping the tables destroys
-- them. Clear them deliberately first if that is really what is meant.
DO $$
DECLARE n INTEGER;
BEGIN
  SELECT (SELECT count(*) FROM public.bonus_declarations)
       + (SELECT count(*) FROM public.bonus_disqualifications) INTO n;
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 395: % bonus determination/disqualification rows '
      'exist. They are the employer''s own §10/§11 computation and their §9 '
      'dismissals, which nothing else holds and nobody can re-derive.', n;
  END IF;
END $$;

DROP TABLE IF EXISTS public.bonus_disqualifications;
DROP TABLE IF EXISTS public.bonus_declarations;

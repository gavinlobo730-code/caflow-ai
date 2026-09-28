-- 433: two entities with no PAN recorded are not duplicates of each other.
--
-- WHY
--   Migration 059 declared `entities_pan_unique UNIQUE NULLS NOT DISTINCT
--   (firm_id, pan)`. NULLS NOT DISTINCT makes every NULL equal to every other,
--   so a firm could hold exactly ONE entity with no PAN on file — the second
--   director, guarantor or trustee whose PAN nobody has yet was refused as a
--   duplicate of the first. A PAN is often not known when a person is first
--   recorded (it is collected later, at onboarding), and the Add Entity form
--   leaves it optional.
--
--   Measured on 28-09-2026: 3 entities in production, 1 with a NULL PAN, none
--   with a blank one, no two sharing a PAN — so re-adding the constraint with
--   ordinary NULL semantics cannot fail.
--
-- WHAT THIS DOES
--   Re-adds the constraint under the SAME NAME with the default NULLS DISTINCT:
--   one PAN is still one entity per firm, and an absent PAN is not a value.
--   routers/relationships stores a blank PAN as NULL (never ''), so a blank
--   cannot become a shared value either.

BEGIN;

ALTER TABLE public.entities DROP CONSTRAINT IF EXISTS entities_pan_unique;
ALTER TABLE public.entities ADD CONSTRAINT entities_pan_unique UNIQUE (firm_id, pan);

COMMIT;

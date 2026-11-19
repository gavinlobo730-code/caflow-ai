-- Rollback of migration 771 (POST-A-485, 497). Drops the table of sign-up links; nothing else refers to it. A link mailed while the
-- table existed stops working, and the person asks for another.
BEGIN;
DROP TABLE IF EXISTS public.signup_links;
COMMIT;

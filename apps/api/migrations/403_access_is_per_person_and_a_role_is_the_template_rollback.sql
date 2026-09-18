-- Rollback for migration 403.
--
-- Dropping the table restores the pure role model exactly: `can_user` falls
-- back to the role for every pair when there are no rows, and an absent table
-- reads the same way as an empty one. Nothing else in the schema references it.
DROP TABLE IF EXISTS public.user_permissions;

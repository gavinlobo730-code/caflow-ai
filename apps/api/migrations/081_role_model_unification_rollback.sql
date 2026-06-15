-- Rollback for 081_role_model_unification.sql
-- Restores the permissive (pre-M1) CHECK constraint from migration 022.
-- NOTE: role *values* normalized by 081 are NOT reverted (the legacy strings are
-- lossy and there is no reliable inverse); only the constraint is widened back.

ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE public.users ADD CONSTRAINT users_role_check
  CHECK (role IN ('Partner', 'Admin', 'Manager', 'Article', 'Staff', 'Viewer',
                  'owner', 'manager', 'staff', 'viewer',
                  'Executive', 'Reviewer', 'Client'));

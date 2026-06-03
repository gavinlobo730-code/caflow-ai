-- Migration 021: Fix users table role constraint to match application roles
-- The UI uses Partner/Manager/Article/Staff but DB had owner/manager/staff/viewer

ALTER TABLE public.users
  DROP CONSTRAINT IF EXISTS users_role_check;

ALTER TABLE public.users
  ADD CONSTRAINT users_role_check
  CHECK (role IN ('Partner', 'Manager', 'Article', 'Staff', 'owner', 'manager', 'staff', 'viewer'));

-- Also add lock_pin column to firms for Lock Year PIN protection
ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS lock_pin TEXT;

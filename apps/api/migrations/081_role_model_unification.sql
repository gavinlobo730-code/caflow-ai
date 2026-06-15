-- PracticeSync AI — Migration 081: Role Model Unification (Module 9.0 / M1)
--
-- Problem: three divergent role vocabularies existed —
--   backend enum (core/permissions.py): Partner, Manager, Executive, Reviewer, Client
--   frontend type (lib/auth/permissions.ts): Partner, Manager, Article, Staff
--   DB CHECK (migrations 001/021/022): Partner, Admin, Manager, Article, Staff,
--                                       Viewer + lowercase owner/manager/staff/viewer
-- The live CHECK (022) REJECTED Executive/Reviewer/Client — three of the five roles
-- the backend RBAC is built on — and ALLOWED Article/Staff/Admin/Viewer, which the
-- backend cannot evaluate (→ 403 on every guarded endpoint for those users).
--
-- This migration establishes the backend enum as the single source of truth:
--   1. Normalize every existing users.role to a canonical value.
--   2. Replace the CHECK constraint with the canonical 5-value set.
--
-- Mapping (kept in sync with LEGACY_ROLE_MAP in core/permissions.py):
--   owner            -> Partner      admin   -> Manager
--   article / staff  -> Executive    viewer  -> Reviewer
-- Idempotent and safe to re-run. Rollback: 081_role_model_unification_rollback.sql.

-- 1. Drop the old CHECK constraint FIRST. The normalization below sets canonical
--    values (Executive/Reviewer/...) that the legacy constraint forbids, so the
--    constraint must be removed before the UPDATEs run.
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_role_check;

-- 2. Normalize legacy / lowercase role strings to canonical values.
UPDATE public.users SET role = 'Partner'   WHERE lower(role) = 'owner';
UPDATE public.users SET role = 'Manager'   WHERE lower(role) IN ('admin', 'manager');
UPDATE public.users SET role = 'Executive' WHERE lower(role) IN ('article', 'staff');
UPDATE public.users SET role = 'Reviewer'  WHERE lower(role) = 'viewer';
-- Any remaining non-canonical value (defensive) → least-privileged staff role.
UPDATE public.users
   SET role = 'Reviewer'
 WHERE role NOT IN ('Partner', 'Manager', 'Executive', 'Reviewer', 'Client');

-- 3. Add the canonical CHECK constraint (single source of truth).
ALTER TABLE public.users ADD CONSTRAINT users_role_check
  CHECK (role IN ('Partner', 'Manager', 'Executive', 'Reviewer', 'Client'));

COMMENT ON COLUMN public.users.role IS
  'Module 9.0 canonical role (single source of truth = core/permissions.py Role enum): Partner, Manager, Executive, Reviewer, Client.';

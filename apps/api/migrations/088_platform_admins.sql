-- PracticeSync AI — Migration 088: Platform Admin (Super Admin) identity.
--
-- Platform Admin sits ABOVE firms and is COMPLETELY separate from the firm
-- authorization model: it is NOT a value in users.role, NOT firm-scoped, and a
-- firm user can never grant it to themselves. Authority comes solely from
-- membership in this allowlist, which is readable/writable ONLY via the
-- service-role key (RLS-enabled with no policy => denied to authenticated/anon).
--
-- Suspension/deletion reuse the existing firms.is_active and firms.deleted_at
-- columns (no new status columns). Additive, idempotent, reversible.

CREATE TABLE IF NOT EXISTS public.platform_admins (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  auth_user_id  UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  email         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by    UUID
);

-- Lock it down: RLS on with NO policy => firm users (authenticated/anon) are
-- denied entirely; only the service-role key (used by the platform router)
-- can read/write it. REVOKE is belt-and-suspenders against any blanket grant.
ALTER TABLE public.platform_admins ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_admins FROM anon, authenticated;
GRANT ALL ON public.platform_admins TO service_role;

COMMENT ON TABLE public.platform_admins IS
  'Platform/Super Admin allowlist — authority ABOVE firms, separate from users.role. Service-role only; firm users can never read, write, or self-grant it.';

-- Seed the initial Platform Admin (the PracticeSync owner) by email. No-op if the
-- email is not yet a Supabase Auth user. Add more operators with:
--   INSERT INTO public.platform_admins(auth_user_id,email)
--   SELECT id,email FROM auth.users WHERE email='<operator>' ON CONFLICT DO NOTHING;
INSERT INTO public.platform_admins (auth_user_id, email)
SELECT id, email FROM auth.users WHERE email = 'gavin.lobo.730@gmail.com'
ON CONFLICT (auth_user_id) DO NOTHING;

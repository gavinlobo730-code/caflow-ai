-- Add job_title to users
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS job_title TEXT;

-- Widen role constraint to include Admin/Viewer as access levels
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE public.users ADD CONSTRAINT users_role_check
  CHECK (role IN ('Partner', 'Admin', 'Manager', 'Article', 'Staff', 'Viewer', 'owner', 'manager', 'staff', 'viewer'));

-- Client assignments for Staff/Viewer scoped access
CREATE TABLE IF NOT EXISTS public.user_client_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, client_id)
);

ALTER TABLE public.user_client_assignments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_members_see_assignments" ON public.user_client_assignments
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

CREATE POLICY "partners_manage_assignments" ON public.user_client_assignments
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Client portal support
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS portal_enabled BOOLEAN DEFAULT false;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS portal_user_id UUID;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS portal_invited_at TIMESTAMPTZ;

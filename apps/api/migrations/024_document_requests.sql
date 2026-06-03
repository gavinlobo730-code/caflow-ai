CREATE TABLE IF NOT EXISTS public.document_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  requested_by UUID REFERENCES public.users(id),
  title TEXT NOT NULL,
  description TEXT,
  is_urgent BOOLEAN DEFAULT false,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fulfilled')),
  fulfilled_at TIMESTAMPTZ,
  storage_path TEXT,
  file_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.document_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_staff_manage_requests" ON public.document_requests
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

CREATE POLICY "portal_client_sees_own_requests" ON public.document_requests
  FOR SELECT TO authenticated
  USING (
    client_id IN (
      SELECT id FROM public.clients WHERE portal_user_id = auth.uid()
    )
  );

CREATE POLICY "portal_client_fulfills_own_requests" ON public.document_requests
  FOR UPDATE TO authenticated
  USING (
    client_id IN (
      SELECT id FROM public.clients WHERE portal_user_id = auth.uid()
    )
  );

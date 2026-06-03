CREATE TABLE IF NOT EXISTS public.client_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  uploaded_by UUID REFERENCES public.users(id),
  file_name TEXT NOT NULL,
  label TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  file_size_bytes BIGINT,
  mime_type TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.client_documents ENABLE ROW LEVEL SECURITY;

-- Firm staff can see all documents for their firm
CREATE POLICY "firm_staff_see_documents" ON public.client_documents
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

-- Firm staff can insert documents
CREATE POLICY "firm_staff_insert_documents" ON public.client_documents
  FOR INSERT TO authenticated
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Firm staff can delete their own uploads
CREATE POLICY "firm_staff_delete_documents" ON public.client_documents
  FOR DELETE TO authenticated
  USING (firm_id = public.get_my_firm_id());

-- Portal clients can see their own documents
-- (portal_user_id on clients matches auth.uid())
CREATE POLICY "portal_client_sees_own_documents" ON public.client_documents
  FOR SELECT TO authenticated
  USING (
    client_id IN (
      SELECT id FROM public.clients WHERE portal_user_id = auth.uid()
    )
  );

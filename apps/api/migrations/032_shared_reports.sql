-- Migration 032: Shared Reports for Client Portal
-- CA can share P&L / Balance Sheet / GST Summary with specific clients
-- Clients can view and download the shared report

CREATE TABLE IF NOT EXISTS public.shared_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  report_type TEXT NOT NULL CHECK (report_type IN ('pl', 'balance_sheet', 'gst_summary', 'tds_summary')),
  report_label TEXT NOT NULL, -- e.g. "P&L FY 2024-25"
  financial_year TEXT NOT NULL, -- e.g. "2024-25"
  storage_path TEXT NOT NULL, -- path in Supabase Storage
  file_name TEXT NOT NULL,
  file_size_bytes BIGINT,
  shared_by UUID REFERENCES public.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.shared_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_manage_shared_reports" ON public.shared_reports;
DROP POLICY IF EXISTS "portal_client_sees_own_shared_reports" ON public.shared_reports;

CREATE POLICY "firm_staff_manage_shared_reports" ON public.shared_reports
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

CREATE POLICY "portal_client_sees_own_shared_reports" ON public.shared_reports
  FOR SELECT TO authenticated
  USING (
    client_id IN (
      SELECT id FROM public.clients WHERE portal_user_id = auth.uid()
    )
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.shared_reports TO authenticated;

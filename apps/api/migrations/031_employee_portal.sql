-- Migration 031: Employee portal, scheduled reports, document versioning

-- Feature 1: Employee Self-Service Portal
ALTER TABLE public.payroll_employees ADD COLUMN IF NOT EXISTS auth_user_id UUID;
ALTER TABLE public.payroll_employees ADD COLUMN IF NOT EXISTS portal_enabled BOOLEAN DEFAULT false;

CREATE POLICY "employee_sees_own_record" ON public.payroll_employees
  FOR SELECT TO authenticated
  USING (auth_user_id = auth.uid());

-- Feature 2: Scheduled Report Delivery
CREATE TABLE IF NOT EXISTS public.scheduled_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID REFERENCES public.clients(id) ON DELETE CASCADE,
  report_type TEXT NOT NULL CHECK (report_type IN ('pl', 'balance_sheet', 'gst_summary', 'tds_summary', 'payroll_summary')),
  frequency TEXT NOT NULL CHECK (frequency IN ('monthly', 'quarterly', 'yearly')),
  recipients TEXT[] NOT NULL DEFAULT '{}', -- email addresses
  day_of_month INTEGER DEFAULT 5, -- send on 5th of month/quarter
  is_active BOOLEAN DEFAULT true,
  last_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.scheduled_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_scheduled_reports" ON public.scheduled_reports
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Feature 5: Document Version Control
ALTER TABLE public.client_documents ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE public.client_documents ADD COLUMN IF NOT EXISTS parent_document_id UUID REFERENCES public.client_documents(id);

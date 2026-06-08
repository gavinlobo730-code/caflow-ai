-- Payroll Enhancements: Attendance, Leave Balances
-- Migration 027

-- Attendance records
CREATE TABLE IF NOT EXISTS public.attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  employee_id UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  year INTEGER NOT NULL,
  working_days INTEGER NOT NULL DEFAULT 26,
  days_present INTEGER NOT NULL DEFAULT 26,
  casual_leaves INTEGER NOT NULL DEFAULT 0,
  sick_leaves INTEGER NOT NULL DEFAULT 0,
  earned_leaves INTEGER NOT NULL DEFAULT 0,
  lop_days INTEGER NOT NULL DEFAULT 0, -- Loss of Pay
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(employee_id, month, year)
);

ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_attendance" ON public.attendance
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Leave balances
CREATE TABLE IF NOT EXISTS public.leave_balances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  employee_id UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  year INTEGER NOT NULL,
  casual_leave_balance INTEGER NOT NULL DEFAULT 12,
  sick_leave_balance INTEGER NOT NULL DEFAULT 12,
  earned_leave_balance INTEGER NOT NULL DEFAULT 15,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(employee_id, year)
);

ALTER TABLE public.leave_balances ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_leave_balances" ON public.leave_balances
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

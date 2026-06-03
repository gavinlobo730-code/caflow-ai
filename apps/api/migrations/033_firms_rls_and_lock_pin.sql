-- Migration 033: Ensure firms table has all required columns and RLS allows reads
-- Fixes "Firm not found" on Lock Year page

-- Ensure columns exist (safe if already added by 020/021)
ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS locked_financial_years TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS lock_pin TEXT;

-- Ensure authenticated users can read and update their own firm
DROP POLICY IF EXISTS "firms_own" ON public.firms;
CREATE POLICY "firms_own" ON public.firms
  FOR ALL TO authenticated
  USING (id = public.get_my_firm_id())
  WITH CHECK (id = public.get_my_firm_id());

GRANT SELECT, UPDATE ON public.firms TO authenticated;

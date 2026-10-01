-- Rollback for migration 470: the two write policies on fx_rates go back to
-- migration 439's `true`.
--
-- Rolling back RE-OPENS the hole 470 closes: any signed-in principal can write
-- any exchange rate, including the closing rate another firm's revaluation reads.

DROP POLICY IF EXISTS insert_fx_rates ON public.fx_rates;
CREATE POLICY insert_fx_rates ON public.fx_rates
  FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS update_fx_rates ON public.fx_rates;
CREATE POLICY update_fx_rates ON public.fx_rates
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

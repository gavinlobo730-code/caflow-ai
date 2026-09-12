-- Rollback for 371. Comments only, so the rollback removes them.
COMMENT ON TABLE  public.tds_section_limits IS NULL;
COMMENT ON COLUMN public.tds_section_limits.threshold_paise IS NULL;
COMMENT ON COLUMN public.tds_section_limits.rate_individual IS NULL;
COMMENT ON COLUMN public.tds_section_limits.rate_company IS NULL;
COMMENT ON COLUMN public.tds_challans.minor_head IS NULL;
COMMENT ON COLUMN public.tds_challans.interest_paise IS NULL;
COMMENT ON COLUMN public.tds_challans.penalty_paise IS NULL;
COMMENT ON COLUMN public.tds_challans.tds_paise IS NULL;

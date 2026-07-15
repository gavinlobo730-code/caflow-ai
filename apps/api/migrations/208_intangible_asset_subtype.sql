-- Migration 208 — Intangible Assets: distinguishable Schedule III subtype
--
-- Account 1506 "Intangible Assets" was seeded with account_subtype
-- 'Fixed Asset' — indistinguishable from tangible fixed assets to the
-- Schedule III bucketing (schedule_iii.bs_bucket / the frontend's bsBucket),
-- both of which scan the SUBTYPE, so software/goodwill presented under
-- "Fixed Assets — Tangible" and "Fixed Assets — Intangible" was always ₹0.
-- Purely presentational (the money was always in the right ACCOUNT); the
-- seed list (coa_seed_service.STANDARD_COA) is updated in the same commit
-- so newly-onboarded firms get the correct subtype directly.

UPDATE public.chart_of_accounts
   SET account_subtype = 'Intangible Asset'
 WHERE account_code = '1506'
   AND account_name = 'Intangible Assets'
   AND account_subtype = 'Fixed Asset';

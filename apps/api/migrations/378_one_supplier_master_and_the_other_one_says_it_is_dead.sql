-- 378 — there is one supplier master, and it is public.vendors (PUR-16)
--
-- WHAT WAS WRONG
--
--   `/accounting/suppliers` read and wrote `public.suppliers` (migration 030)
--   straight over PostgREST. Every purchase path in the product — bill
--   creation, TDS withholding, the AP ageing, the Schedule III payables note,
--   GSTR-2B matching, s.43B(h) — reads `public.vendors`. Two masters, and no
--   join between them.
--
--   The credit limit is the harmless half: nothing anywhere reads
--   `credit_limit_paise`, on suppliers or on clients. The TDS SECTION is not.
--   A CA who opened Supplier Master, picked 194J against a professional firm
--   and saved it wrote `suppliers.tds_section`; the bill path then read
--   `vendors.tds_section`, found NULL, and withheld nothing. Under-deduction
--   disallows the WHOLE expenditure under IT Act s.40(a)(ia), and s.201(1)
--   makes the deductor liable for the tax with s.201(1A) interest on top.
--
-- WHAT THIS MIGRATION DOES, AND WHAT IT DELIBERATELY DOES NOT
--
--   1. Gives `vendors` the one column it was missing, so repointing the screen
--      loses nothing the CA had typed. Every other field on that form already
--      has a home: supplier_name -> name, payment_terms_days -> credit_days,
--      tds_rate_percent -> tds_rate_bps (x100).
--
--   2. Says in the database that `public.suppliers` is dead.
--
--   NO DATA IS MIGRATED, and that is a measurement rather than a decision:
--   `public.suppliers` held ZERO rows in production on 13-09-2026, and the
--   only writer it has ever had is the one screen this change repoints. There
--   is nothing to copy, and a matching heuristic (by name? by GSTIN? against
--   which client?) written for an empty table would be untested guesswork
--   sitting in the migration history for ever.
--
--   NO DROP. Same reasoning as migration 371, which retired the dead TDS rate
--   master: `tests/fixtures/` carries point-in-time production snapshots that
--   test_schema_matches_production_pg.py and test_guards_match_production_pg.py
--   compare a migration-built database against, and `suppliers` is in both of
--   them (its table, its three constraints, its five policies and its RLS
--   switch). Dropping it moves both sides of that comparison at once.
--   docs/schema-drift.md says how to refresh them; that is a separate change
--   somebody can review as a deletion rather than as a fixture churn.
--
-- WHY credit_limit_paise IS NULLABLE WITH NO DEFAULT
--
--   The same reason migration 202 took the NOT NULL DEFAULT 30 off
--   `credit_days`: "no limit recorded" and "the limit is zero" are different
--   facts, and a DEFAULT 0 cannot represent the first. A zero limit would mean
--   this vendor may not be given credit at all, which is a real thing a CA
--   might record and is not what an untouched row means.
--
--   Nothing enforces it — no code path in apps/api or apps/web reads a credit
--   limit, on a vendor or on a client. It is a recorded fact, and the column
--   comment says so rather than implying a control that does not exist.

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS credit_limit_paise BIGINT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'vendors_credit_limit_paise_check') THEN
    ALTER TABLE public.vendors
      ADD CONSTRAINT vendors_credit_limit_paise_check
      CHECK (credit_limit_paise IS NULL OR credit_limit_paise >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.vendors.credit_limit_paise IS
  'Credit limit agreed with this supplier, in integer paise. NULL = no limit '
  'recorded, which is NOT the same as a recorded limit of zero (that means no '
  'credit at all). RECORDED, NOT ENFORCED: nothing in apps/api or apps/web '
  'blocks or warns on a bill that would exceed it, and clients.credit_limit_paise '
  'has no reader either. Moved here from the retired public.suppliers by '
  'migration 378 so the Supplier Master screen could be repointed at the '
  'master every purchase path actually reads. PUR-16.';

COMMENT ON TABLE public.suppliers IS
  'RETIRED — NOT THE SUPPLIER MASTER. public.vendors is, and every purchase '
  'path reads it: bill creation, TDS withholding (routers/vendors.py, '
  'domain/tds), AP ageing, the Schedule III payables note, GSTR-2B matching '
  'and s.43B(h). This table was written only by /accounting/suppliers, which '
  'migration 378 repointed; it held ZERO rows in production on 13-09-2026 and '
  'nothing reads it now. A tds_section recorded here reached no bill, so no '
  'tax was withheld — s.40(a)(ia) disallows the whole expenditure for that. '
  'Do not write to it and do not read it; add the field to public.vendors '
  'instead. A DROP is the right end state and needs the production-fixture '
  'refresh in docs/schema-drift.md. PUR-16.';

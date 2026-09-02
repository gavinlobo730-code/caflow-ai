-- 310: treaty rates as a table keyed by COUNTRY and NATURE, not a number on a
-- vendor.
--
-- WHY THE VENDOR COLUMN WAS THE WRONG SHAPE
--   Migration 309 put treaty_rate_bps on the vendor, which reads naturally and
--   is wrong in a way that shows up on the second vendor. A DTAA rate is a fact
--   about a COUNTRY and an ARTICLE, not about a supplier: royalty to
--   Switzerland is the same rate whichever Swiss company is being paid, and the
--   same treaty commonly gives royalty, fees for technical services, interest
--   and dividends four DIFFERENT rates.
--
--   So a firm with five Swiss vendors was entering one rate five times, could
--   not express that royalty and interest differ under the same agreement, and
--   would have to find all five rows again when a protocol changed. One row per
--   (country, nature) fixes all three.
--
-- THIS SHIPS EMPTY, AND THAT IS THE POINT
--   No rates are seeded. India has agreements with over ninety countries, their
--   royalty/FTS/interest articles differ, MFN clauses need their own s.90(1)
--   notification (AO v. Nestle SA, 2023), and a wrong rate too low disallows the
--   WHOLE expenditure under s.40(a)(i) while too high takes money off a supplier
--   who can only recover it by filing an Indian return. A CA reads the
--   agreement and records what they read, once per country and nature they
--   actually deal with.
--
-- WHY FIRM-SCOPED RATHER THAN ONE GLOBAL TABLE
--   The entry is a professional judgement the firm signs off and stands behind
--   — most visibly on MFN positions, where firms legitimately differ. A shared
--   table would make one firm's reading silently become another's.
--
-- "NO ARTICLE" IS A VALUE, NOT A MISSING ROW
--   Several agreements — the UAE and Singapore among them — have NO fees for
--   technical services article at all. That is not an unknown rate: it means the
--   income is business profits under Article 7 and is not taxable in India
--   without a permanent establishment. Recording it as no_article is therefore
--   a real answer, and the engine treats it as one (still requiring the payee's
--   no-PE declaration, because that is the fact it turns on).
--
--   A row must say one thing or the other, which is what the CHECK enforces: a
--   row with neither a rate nor no_article is a half-finished thought, and the
--   engine would have to guess which.
--
-- Re-runnable: IF NOT EXISTS throughout, policies dropped before creation,
-- whole file in one transaction.

BEGIN;

CREATE TABLE IF NOT EXISTS public.dtaa_treaty_rates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  -- ISO 3166-1 alpha-2, matching vendors.country_of_residence so the lookup is
  -- an equality join and not a name match.
  country_code  text NOT NULL,
  nature        text NOT NULL,
  -- Exactly one of these two carries the answer. NULL rate with no_article
  -- false is not "unknown" — it is a row that should not have been saved.
  rate_bps      integer,
  no_article    boolean NOT NULL DEFAULT false,
  -- Which article the reader relied on, e.g. 'Article 12(2)'. Not validated:
  -- article numbering differs between agreements, and a wrong-looking string a
  -- human typed is better evidence than a blank one.
  article_ref   text,
  notes         text,
  -- Who stood behind this reading, and when. A treaty rate is a professional
  -- judgement; an unattributed one cannot be defended to an assessing officer.
  verified_by   uuid REFERENCES public.users(id),
  verified_on   date NOT NULL DEFAULT ((now() AT TIME ZONE 'Asia/Kolkata')::date),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (firm_id, country_code, nature)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'dtaa_treaty_rates_country_check'
                      AND conrelid = 'public.dtaa_treaty_rates'::regclass) THEN
        ALTER TABLE public.dtaa_treaty_rates
          ADD CONSTRAINT dtaa_treaty_rates_country_check
          CHECK (country_code ~ '^[A-Z]{2}$');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'dtaa_treaty_rates_nature_check'
                      AND conrelid = 'public.dtaa_treaty_rates'::regclass) THEN
        ALTER TABLE public.dtaa_treaty_rates
          ADD CONSTRAINT dtaa_treaty_rates_nature_check
          CHECK (nature IN ('royalty', 'fees_for_technical_services', 'interest', 'interest_194lc', 'dividend', 'ltcg_112', 'ltcg_112a', 'stcg_111a', 'business_profits_no_pe', 'other_sums'));
    END IF;

    -- Say one thing or the other. A rate AND no_article is a contradiction; a
    -- row with neither is a half-finished thought the engine would have to
    -- guess at.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'dtaa_treaty_rates_answer_check'
                      AND conrelid = 'public.dtaa_treaty_rates'::regclass) THEN
        ALTER TABLE public.dtaa_treaty_rates
          ADD CONSTRAINT dtaa_treaty_rates_answer_check
          CHECK ((no_article AND rate_bps IS NULL)
                 OR (NOT no_article AND rate_bps IS NOT NULL
                     AND rate_bps >= 0 AND rate_bps <= 10000));
    END IF;
END $$;

COMMENT ON TABLE public.dtaa_treaty_rates IS
    'A firm''s reading of the DTAA rates it withholds under, one row per '
    '(country, nature of income). Ships EMPTY and is never seeded: India has '
    'agreements with over ninety countries and a wrong rate too low disallows '
    'the whole expenditure under IT Act s.40(a)(i). s.90(2) then gives the '
    'assessee whichever of this and the Act rate is lower. Migration 310.';

COMMENT ON COLUMN public.dtaa_treaty_rates.no_article IS
    'TRUE where the agreement has no article for this nature at all — several, '
    'including the UAE and Singapore, have no fees-for-technical-services '
    'article. That makes the income business profits under Article 7, not '
    'taxable in India without a permanent establishment, so it is an ANSWER '
    'rather than a missing rate. Migration 310.';

CREATE INDEX IF NOT EXISTS idx_dtaa_treaty_rates_lookup
  ON public.dtaa_treaty_rates (firm_id, country_code, nature);

ALTER TABLE public.dtaa_treaty_rates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_dtaa_treaty_rates" ON public.dtaa_treaty_rates;
CREATE POLICY "firm_dtaa_treaty_rates" ON public.dtaa_treaty_rates
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- Role-aware write guards, the shape migrations 260/261/304/305 established.
-- RESTRICTIVE so they narrow rather than widen. MANAGER tier, matching
-- schedule_iii_unbilled_reviews: recording a treaty rate is a professional
-- position the firm withholds tax on and defends, not a preference.
DO $$
DECLARE t text := 'dtaa_treaty_rates';
BEGIN
  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
    'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
    'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
    t || '_role_update', t, 'Manager', 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
    'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Manager');
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.dtaa_treaty_rates TO authenticated;

-- The vendor column stays, and changes meaning: it is now an OVERRIDE for the
-- rare vendor whose position genuinely differs from the firm's country reading
-- — an advance ruling, or a payee that fails a beneficial-ownership condition
-- the country row assumes. Left in place rather than dropped because dropping
-- it would silently discard whatever migration 309's users have already
-- recorded.
COMMENT ON COLUMN public.vendors.treaty_rate_bps IS
    'PER-VENDOR OVERRIDE of the firm''s dtaa_treaty_rates row for this '
    'vendor''s country and nature of income (migration 310). Leave NULL to use '
    'the country table, which is where a treaty rate normally belongs — the '
    'rate is a fact about a country and an article, not about a supplier. Set '
    'it only where this payee''s position genuinely differs, e.g. an advance '
    'ruling or a failed beneficial-ownership condition. Migration 309, '
    'redefined by 310.';

COMMIT;

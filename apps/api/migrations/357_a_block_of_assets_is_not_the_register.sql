-- Migration 357: the IT Act §32 block register, beside the Companies Act one.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SECOND REGISTER
-- ═══════════════════════════════════════════════════════════════════════════
-- Depreciation is charged twice in every Indian business's books, on two
-- systems that are not two rates for one calculation:
--
--     Companies Act 2013, Schedule II — per ASSET, over its useful LIFE. That
--     is `public.fixed_assets`, and it is what the accounts carry.
--
--     IT Act 1961, §32 — per BLOCK, at the block's RATE, on the block's
--     written-down value. Assets lose their identity inside the block; there
--     is no per-asset written-down value and no per-asset life at all.
--
-- The difference between them is usually the largest single line in the
-- book-to-tax bridge, and until `domain/income_tax/section_32.py` there was no
-- implementation of the second system anywhere in this codebase.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS STORED HERE AND WHAT IS DERIVED
-- ═══════════════════════════════════════════════════════════════════════════
-- Additions and deletions are DERIVED from the fixed-asset register — a
-- purchase in the year is an addition, a disposal is a reduction by the moneys
-- payable. What cannot be derived, and is stored:
--
--   * WHICH BLOCK an asset falls in (`fixed_assets.it_block_key`). §2(11) makes
--     a block a group of assets of the same NATURE carrying the same RATE, and
--     the Schedule II categories on the register do not map onto it — "Plant &
--     Machinery" is one Schedule II category and several §32 blocks. It is a
--     CA's determination. NULL means unclassified, and the service refuses to
--     put such an asset in any block rather than guessing one.
--
--   * THE BLOCK'S RATE. Appendix I to the Income-tax Rules is a long statutory
--     table, and this repository's rule is that such data is entered by a human
--     rather than written from memory (CLAUDE.md, "The other statutory data a
--     human has to supply"). A block IS a rate under §2(11), so the person who
--     decides the block has decided the rate. The engine holds no table.
--
--   * THE OPENING WRITTEN-DOWN VALUE. It comes off last year's return. In the
--     first year this software covers a client there is nothing here to derive
--     it from, and a zero would allow no depreciation at all on a block that
--     has been running for a decade.
--
--   * WHETHER ANY ASSET OF THE BLOCK REMAINS at the year end. §50 turns an
--     emptied block into a short-term capital loss and allows no depreciation
--     on it, and a positive written-down value does not settle the question —
--     a block can hold money and no assets, if everything in it was sold at a
--     loss. NULL means nobody has said, and the computation reports that as a
--     gap rather than assuming either way.
--
--   * WHEN AN ASSET WAS PUT TO USE (`fixed_assets.put_to_use_date`). The second
--     proviso to §32(1) halves the rate on an asset "acquired ... AND put to
--     use ... for a period of less than one hundred and eighty days", and an
--     asset bought in February and put to use in June belongs to the NEXT
--     previous year entirely. The purchase date does not answer it and must not
--     be substituted for it; NULL is a gap.

ALTER TABLE public.fixed_assets
    ADD COLUMN IF NOT EXISTS it_block_key     text,
    ADD COLUMN IF NOT EXISTS put_to_use_date  date;

COMMENT ON COLUMN public.fixed_assets.it_block_key IS
    'Which IT Act §32 block of assets this asset falls in — a CA determination, '
    'not derivable from asset_category. NULL = unclassified, and the §32 '
    'computation names it rather than placing it.';
COMMENT ON COLUMN public.fixed_assets.put_to_use_date IS
    'When the asset was PUT TO USE, which is what the second proviso to §32(1) '
    'turns on. Not the purchase date, and never defaulted to it.';

CREATE TABLE IF NOT EXISTS public.income_tax_asset_blocks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id           UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    -- 'YYYY-YY', the previous year this opening balance opens.
    financial_year    TEXT NOT NULL,
    -- The CA's own name for the block, e.g. 'Plant & Machinery 15%'. It is what
    -- fixed_assets.it_block_key points at.
    block_key         TEXT NOT NULL,
    -- Appendix I's rate for the block, as a whole per cent. A block IS a rate
    -- (§2(11)), so this is not a property of the block, it is half its identity.
    rate_percent      SMALLINT NOT NULL CHECK (rate_percent >= 0 AND rate_percent <= 100),
    -- Off last year's return. NOT NULL with no default: a zero is a claim.
    opening_wdv_paise BIGINT NOT NULL,
    -- §50's second limb. NULL = nobody has said.
    assets_remain     BOOLEAN,
    notes             TEXT,
    created_by        UUID REFERENCES public.users(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One opening balance per block per year. The §32 computation reads exactly
    -- one row per block and a second would silently double the opening WDV.
    UNIQUE (firm_id, client_id, financial_year, block_key)
);

COMMENT ON TABLE public.income_tax_asset_blocks IS
    'IT Act §32 blocks of assets: the opening written-down value and rate for one '
    'client and one previous year. Additions and deletions are derived from '
    'public.fixed_assets; everything here is a fact only a CA holds. See '
    'domain/income_tax/section_32.py.';

CREATE INDEX IF NOT EXISTS idx_it_asset_blocks_client_fy
    ON public.income_tax_asset_blocks (firm_id, client_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_fixed_assets_it_block
    ON public.fixed_assets (firm_id, client_id, it_block_key);

ALTER TABLE public.income_tax_asset_blocks ENABLE ROW LEVEL SECURITY;

-- Firm isolation plus role-guarded writes, in the shape migrations 260/261
-- established and 352 last used: the frontend reaches ~83 tables over PostgREST
-- where rbac() never runs, so a table's write policy is the only check on that
-- path. An opening written-down value decides a client's whole depreciation
-- allowance for the year, so it is Executive+ to write and Manager+ to delete.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_income_tax_asset_blocks ON public.income_tax_asset_blocks';
  EXECUTE 'CREATE POLICY firm_income_tax_asset_blocks ON public.income_tax_asset_blocks '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  EXECUTE 'DROP POLICY IF EXISTS income_tax_asset_blocks_role_insert ON public.income_tax_asset_blocks';
  EXECUTE 'CREATE POLICY income_tax_asset_blocks_role_insert ON public.income_tax_asset_blocks '
          'AS RESTRICTIVE FOR INSERT WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS income_tax_asset_blocks_role_update ON public.income_tax_asset_blocks';
  EXECUTE 'CREATE POLICY income_tax_asset_blocks_role_update ON public.income_tax_asset_blocks '
          'AS RESTRICTIVE FOR UPDATE USING (public.my_role_at_least(''Executive'')) '
          'WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS income_tax_asset_blocks_role_delete ON public.income_tax_asset_blocks';
  EXECUTE 'CREATE POLICY income_tax_asset_blocks_role_delete ON public.income_tax_asset_blocks '
          'AS RESTRICTIVE FOR DELETE USING (public.my_role_at_least(''Manager''))';

  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.income_tax_asset_blocks TO authenticated';
END $$;

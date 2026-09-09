-- 351 — a fixed asset can be corrected: the columns a correction path needs.
--
-- Problem (FA-10)
-- ---------------
-- routers/fixed_assets.py exposes list / create / depreciate / dispose /
-- schedule / categories / register-integrity, and nothing else. A CA who types
-- ₹15,00,000 for ₹1,50,000, or picks Plant & Machinery for an Office Equipment
-- asset, has no way back: the cost is frozen as the depreciable base for the
-- asset's whole life, an acquisition journal is on the ledger at that amount,
-- and migration 245 revokes UPDATE and DELETE on public.fixed_assets from
-- `authenticated`, so the direct PostgREST path cannot help either. The three
-- workarounds are all wrong — dispose at nil proceeds books a fabricated loss
-- (and first demands every unposted month be depreciated); reversing the
-- journal through the generic accounting endpoint leaves the register claiming
-- a cost the ledger no longer carries; the third is a database console.
--
-- What this migration adds
-- ------------------------
--   deleted_at / deleted_by   migration 275's soft-delete shape, which this
--                             table could not express at all. A correction that
--                             removes an asset must leave the row present: see
--                             the unique index below.
--   updated_at                so a corrected row says it was corrected.
--   UNIQUE (firm_id, client_id, asset_code), NOT partial.
--
-- Why that index is deliberately NOT partial on deleted_at:
--   asset_code is the identity every FA journal reference is built from —
--   FA-ACQ-{code}, FA-CAP-{code}, FA-DEPN-{code}-{period}, FA-DISP-{code} — and
--   the posting kernel dedupes on (client_id, reference_no, entry_date). Let a
--   deleted asset's code be handed to the NEXT asset and its acquisition
--   journal dedupes onto the deleted one's entry at the same purchase date:
--   two assets share one entry and the second one's cost never reaches the
--   balance sheet. A soft-deleted row keeps its code for ever.
--
-- The code itself was also generated from a COUNT of the client's assets
-- (routers/fixed_assets.py) — the same defect as SALES-04, and the reason this
-- index could not have been added before: delete an asset and the next one
-- takes a code that is already in use. It now reads the highest code through
-- services/numbering.py::next_sequence, which is what makes this index
-- satisfiable.
--
-- No grant changes. `authenticated` keeps SELECT only (migrations 166/245); the
-- service-role backend stays the only writer, and every rule lives in apps/api.

ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS corrections_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.fixed_assets.corrections_count IS
  'How many times the acquisition has been corrected. It is the REVISION SUFFIX '
  'on the re-posted acquisition journal''s reference (FA-ACQ-{code}-R{n}), which '
  'is why it is a stored counter and not a derived one: re-posting at the '
  'unchanged reference and date can return the REVERSED entry''s id from '
  'post_journal_atomic''s unique-violation handler (migration 274), which selects '
  'the winner without filtering is_reversed.';

COMMENT ON COLUMN public.fixed_assets.deleted_at IS
  'Soft delete (migration 275''s shape). A deleted asset is excluded from every '
  'read but KEEPS its asset_code, because the FA-* journal references are built '
  'from it and the posting kernel dedupes on (client_id, reference_no, entry_date).';

-- Backfill: rows created before this migration were never updated after
-- creation, so created_at is the truthful value.
UPDATE public.fixed_assets SET updated_at = created_at WHERE updated_at IS NULL;

-- Duplicate asset_codes cannot exist under the count-based generator unless a
-- row was removed by hand; create the index only when the data allows it, and
-- say so loudly rather than failing the whole migration run.
DO $$
DECLARE dupes int;
BEGIN
  SELECT count(*) INTO dupes FROM (
    SELECT firm_id, client_id, asset_code
    FROM public.fixed_assets
    WHERE asset_code IS NOT NULL
    GROUP BY firm_id, client_id, asset_code
    HAVING count(*) > 1
  ) d;

  IF dupes > 0 THEN
    RAISE WARNING 'fixed_assets: % duplicate (firm_id, client_id, asset_code) groups — '
                  'uq_fixed_assets_client_asset_code NOT created. Resolve the duplicates '
                  'and re-run; until then two assets can share one journal reference.', dupes;
  ELSE
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_assets_client_asset_code
      ON public.fixed_assets (firm_id, client_id, asset_code)
      WHERE asset_code IS NOT NULL;
  END IF;
END $$;

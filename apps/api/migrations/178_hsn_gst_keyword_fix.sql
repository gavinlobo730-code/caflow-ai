-- Migration 178 — HSN/SAC keyword fix: "GST" is unsearchable (Batch: Invoice
-- Autocomplete Performance & Data Quality Refinement)
--
-- Audit finding (manual verification against a real hsn_master load, mirroring
-- migration 175's seed): searching the literal term "GST" — something a CA
-- billing "GST Return Filing" / "GST Registration" work would very plausibly
-- type — returns ZERO relevant rows. It doesn't even fail cleanly: the only
-- hit is chapter 81 ("Other base metals; cermets...") because its keyword
-- "tungsten" happens to contain the substring "gst" (tun-GST-en) — a
-- misleading false positive with no relevant result anywhere near it.
--
-- None of migration 175's tax/accounting keyword lists include the literal
-- token "gst" (they use "tax", "accounting", "audit" etc.), even though GST
-- return/registration work is exactly the kind of line item this feature
-- exists to make findable in one search. This migration only appends "gst" to
-- the `keywords` column of the SAC codes a CA would actually bill that work
-- under — additive, no schema change, no effect on description/rate/type, so
-- it cannot alter any existing invoice, GSTR-1 return or PDF (hsn_master feeds
-- only the lookup search, per migration 175's own backward-compatibility note).
UPDATE public.hsn_master SET keywords = keywords || ' gst'
 WHERE hsn_code = '9982'    AND keywords NOT LIKE '%gst%';   -- Legal and accounting services (parent group)
UPDATE public.hsn_master SET keywords = keywords || ' gst return filing'
 WHERE hsn_code = '998231'  AND keywords NOT LIKE '%gst%';   -- Corporate tax consulting and preparation services
UPDATE public.hsn_master SET keywords = keywords || ' gst return filing'
 WHERE hsn_code = '998232'  AND keywords NOT LIKE '%gst%';   -- Individual tax preparation and planning services

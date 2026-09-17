-- Rollback for 399.
--
-- The back-fill cannot be undone safely and this does not try. Setting gstin
-- back to NULL where it equals gst_number would blank the column for any firm
-- that legitimately holds the same value in both — including every firm
-- created through POST /api/onboarding/firm, which has always written `gstin`
-- and which a later profile save now also writes. There is no marker
-- distinguishing "copied by 399" from "written by the product", and inventing
-- one afterwards would be a guess about the firm's own legal identity.
--
-- Only the comments are reverted, which is the whole of what this migration
-- changed about the SCHEMA. The data it moved is left where it is: it is the
-- GSTIN the CA recorded, now in the column the product reads.
BEGIN;

COMMENT ON COLUMN public.firms.gstin IS NULL;
COMMENT ON COLUMN public.firms.gst_number IS NULL;

COMMIT;

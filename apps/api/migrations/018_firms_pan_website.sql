-- Migration 018: Add pan and website columns to firms table
-- PAN format per IT Act Section 139A: AAAAA9999A

ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS pan     TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS website TEXT;

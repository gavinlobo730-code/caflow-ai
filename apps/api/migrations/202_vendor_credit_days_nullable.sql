-- Make vendors.credit_days genuinely OPTIONAL instead of forcing every
-- vendor to carry a specific number. Migration 201 gave it DEFAULT 30,
-- but a firm-wide default silently overwrites reality for any vendor whose
-- real payment terms the CA hasn't actually confirmed — "Due on Receipt"
-- (0) and "unknown" are different facts, and NOT NULL DEFAULT 30 can't
-- represent the second one.
--
-- Correct the 41 vendors that got credit_days=0 from the model-default bug
-- fixed alongside this migration (models/parties.py: VendorIn.credit_days
-- defaulted to 0 while the DB defaulted to 30 — model_dump() always sends
-- every field, so every vendor create before today silently wrote 0). No
-- vendor could have deliberately chosen "Due on Receipt" before today: the
-- Payment Terms UI didn't exist until this same batch of work, so every
-- credit_days=0 row is unambiguously bug fallout, not a real CA choice.
ALTER TABLE public.vendors
  ALTER COLUMN credit_days DROP NOT NULL,
  ALTER COLUMN credit_days DROP DEFAULT;

UPDATE public.vendors SET credit_days = NULL WHERE credit_days = 0;

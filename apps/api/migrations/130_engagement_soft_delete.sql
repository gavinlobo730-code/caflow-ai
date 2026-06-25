-- Migration 130: soft-delete for engagement letters
--
-- Adds an is_deleted flag so a CA can discard/cancel an engagement letter
-- without destroying the record (audit history is preserved — the row and its
-- engagement_events stay). Deleting (or rejecting) an engagement reverts the
-- linked lead to an active pipeline stage so it is never orphaned mid-engagement
-- (see routers/lifecycle.revert_lead_after_engagement_closed).
--
-- No CHECK-constraint change: deletion is tracked by this boolean, not a new
-- status value.

ALTER TABLE public.engagements
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;

-- Active (non-deleted) engagements for a lead is the hot path for both listing
-- and the lead-stage recompute, so index it.
CREATE INDEX IF NOT EXISTS idx_engagements_lead_active
    ON public.engagements (lead_id, status)
    WHERE is_deleted = false AND lead_id IS NOT NULL;

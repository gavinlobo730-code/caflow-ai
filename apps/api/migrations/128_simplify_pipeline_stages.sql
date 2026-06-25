-- Migration 128: Simplify sales pipeline — remove Qualified and Proposal Sent stages
--
-- Background: "Qualified" and "Proposal Sent" are legacy stages that have no
-- backing functionality in the application. The pipeline now flows directly:
--   Lead → Engagement Drafted → Engagement Sent → Engagement Signed → Onboarding → Active
--
-- This migration:
--   1. Migrates any existing leads in the removed stages to "Engagement Drafted"
--      so no leads are lost or become inaccessible.
--   2. Drops and recreates the leads_stage_check constraint without the removed stages.
--
-- Mapping:
--   Qualified     → Engagement Drafted
--   Proposal Sent → Engagement Drafted

-- Step 1: migrate existing leads in removed stages
UPDATE public.leads
    SET stage = 'Engagement Drafted', updated_at = now()
    WHERE stage IN ('Qualified', 'Proposal Sent');

-- Step 2: update CHECK constraint
ALTER TABLE public.leads
    DROP CONSTRAINT IF EXISTS leads_stage_check;

ALTER TABLE public.leads
    ADD CONSTRAINT leads_stage_check CHECK (stage IN (
        'Lead',
        'Engagement Drafted',
        'Engagement Sent',
        'Engagement Signed',
        'Proposal Accepted',
        'Onboarding',
        'Active',
        'Dormant',
        'Renewal Due',
        'Exiting',
        'Exited',
        '_deleted'
    ));

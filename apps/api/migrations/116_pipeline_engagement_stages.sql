-- Migration 116: Pipeline — Engagement Stages for leads.stage CHECK constraint
--
-- The leads table was created in migration 059 with a CHECK constraint on the
-- stage column. We now add three new engagement letter stages to the pipeline
-- and a _deleted sentinel used by the pipeline kanban UI for soft-removal:
--
--   'Engagement Drafted' — CA has created the engagement letter (Draft status)
--   'Engagement Sent'    — engagement letter has been sent to the prospect
--   'Engagement Signed'  — prospect has signed the engagement letter
--   '_deleted'           — soft-delete sentinel (lead hidden from kanban board)
--
-- The full set after this migration:
--   Lead | Qualified | Proposal Sent | Engagement Drafted | Engagement Sent |
--   Engagement Signed | Proposal Accepted | Onboarding | Active | Dormant |
--   Renewal Due | Exiting | Exited | _deleted

ALTER TABLE public.leads
    DROP CONSTRAINT IF EXISTS leads_stage_check;

ALTER TABLE public.leads
    ADD CONSTRAINT leads_stage_check CHECK (stage IN (
        'Lead',
        'Qualified',
        'Proposal Sent',
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

-- Migration 132: engagement resend / send-history tracking.
--
-- Supports the DocuSign-style resend workflow (resend email, change recipient &
-- resend, regenerate link) without ever creating a new engagement:
--   * sent_at        (existing) = First Sent  — set once, on the first send
--   * last_sent_at   (new)      = Last Sent   — updated on the first send and
--                                               on every resend
--   * resend_count   (new)      = number of RESENDS (0 after the first send);
--                                 total sends shown to the CA = resend_count + 1
--
-- service_role already holds GRANT ALL on public.engagements (migration 131);
-- table-level privileges cover new columns, so no re-grant is needed.

ALTER TABLE public.engagements
    ADD COLUMN IF NOT EXISTS last_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resend_count INTEGER NOT NULL DEFAULT 0;

-- Backfill: a letter that was already sent has been sent exactly once, so its
-- existing sent_at is also its last_sent_at; resend_count stays 0.
UPDATE public.engagements
   SET last_sent_at = sent_at
 WHERE sent_at IS NOT NULL AND last_sent_at IS NULL;

-- Migration 129: client-facing engagement-letter e-signature
--
-- Adds a public, unguessable sign token plus the captured e-signature evidence
-- (typed name, IP, user agent) so a prospect can review and electronically
-- accept an engagement letter via a tokenized public link — no login required.
--
-- The recipient at the "Sent" stage is typically still a LEAD (not yet an
-- onboarded portal client), so signing uses a tokenized public link (like the
-- hosted invoice payment link) rather than the authenticated client portal.
--
-- Electronic acceptance (typed name + explicit consent + timestamp + IP) is a
-- valid contract under the Information Technology Act, 2000, Section 10A.
-- Engagement letters do NOT require a Digital Signature Certificate. This is
-- CLIENT acceptance only — it is never a government-portal submission.
--
-- The engagements.status CHECK already permits 'Viewed'/'Signed'/'Rejected'
-- (migration 115), so no constraint change is needed here.

ALTER TABLE public.engagements
    ADD COLUMN IF NOT EXISTS sign_token        TEXT,
    ADD COLUMN IF NOT EXISTS signed_by_name    TEXT,
    ADD COLUMN IF NOT EXISTS signed_ip         TEXT,
    ADD COLUMN IF NOT EXISTS signed_user_agent TEXT;

-- One token per letter; many letters legitimately have no token (not yet sent),
-- so uniqueness is enforced only over non-null tokens (partial unique index).
-- This index is also the lookup path for the public signing endpoints.
CREATE UNIQUE INDEX IF NOT EXISTS idx_engagements_sign_token
    ON public.engagements (sign_token)
    WHERE sign_token IS NOT NULL;

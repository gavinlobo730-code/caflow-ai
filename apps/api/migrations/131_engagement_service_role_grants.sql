-- Migration 131: grant service_role DML on the engagement tables.
--
-- ROOT CAUSE of the "This engagement letter link is invalid or has expired."
-- bug on the PUBLIC signing link (clicking "Review & Sign Online"):
--
--   The public signing endpoints (routers/engagement_sign_public.py) have no
--   user JWT — the unguessable sign_token is the credential — so they query via
--   get_service_supabase(), i.e. PostgREST running as the `service_role`.
--
--   Migration 115 created the engagement tables but never granted table
--   privileges to service_role, and the blanket grant migrations (039/041)
--   pre-date 115 — so service_role held only REFERENCES/TRIGGER/TRUNCATE and had
--   NO SELECT/INSERT/UPDATE/DELETE on these tables. Every public read/update
--   therefore failed with "permission denied for table engagements", which the
--   router swallowed and surfaced as a 404 "invalid or has expired" link.
--
--   The STAFF path was unaffected: it runs as `authenticated` (full DML) via the
--   logged-in user's JWT, so the letter was created, sent, and its token stored
--   correctly — but the public service_role role could not read that token back.
--
-- NOTE: BYPASSRLS (which service_role has) only skips RLS *policies*; it does NOT
-- confer table privileges. service_role still needs an explicit GRANT. This
-- matches the convention used across the codebase (GRANT ALL ... TO service_role).
--
-- Idempotent: GRANT is a no-op if the privilege is already held.

GRANT ALL ON public.engagements          TO service_role;
GRANT ALL ON public.engagement_events    TO service_role;
GRANT ALL ON public.engagement_templates TO service_role;

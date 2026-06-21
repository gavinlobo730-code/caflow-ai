-- 109 — Phase 4.5.1 Customer Portal Foundation: multi-contact portal access (ADDITIVE).
--
-- Decision 1: many portal contacts per client, backward compatible. The legacy
-- single-user link (clients.portal_user_id) is UNTOUCHED — its RLS policies keep
-- working. This adds a SECOND, additive linkage (client_portal_users) plus SIBLING
-- RLS policies that are OR-combined (permissive) with the legacy ones. No data
-- rewrite, no backfill, no breaking change.

CREATE TABLE IF NOT EXISTS public.client_portal_users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
    client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    email          TEXT NOT NULL,
    name           TEXT,
    auth_user_id   UUID,                        -- Supabase auth.uid(); NULL until first login binds it (activation)
    status         TEXT NOT NULL DEFAULT 'invited' CHECK (status IN ('invited','active','deactivated')),
    invited_by     UUID,
    invited_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at   TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_client_portal_users_client_email
    ON public.client_portal_users (client_id, lower(email));
CREATE INDEX IF NOT EXISTS idx_client_portal_users_auth
    ON public.client_portal_users (auth_user_id) WHERE auth_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_client_portal_users_firm_client
    ON public.client_portal_users (firm_id, client_id);

ALTER TABLE public.client_portal_users ENABLE ROW LEVEL SECURITY;

-- Firm staff manage their firm's portal contacts.
CREATE POLICY client_portal_users_own_firm ON public.client_portal_users
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());

-- A portal contact may read their OWN row (used by the sibling RLS subqueries below).
CREATE POLICY client_portal_users_self ON public.client_portal_users
    FOR SELECT TO authenticated
    USING (auth_user_id = ( SELECT auth.uid() ));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_portal_users TO authenticated;
GRANT ALL ON public.client_portal_users TO service_role;

-- ── Additive multi-contact RLS on the existing RLS-direct surfaces (Decision 3) ──
-- Siblings of the legacy portal_user_id policies (permissive → OR), so the legacy
-- single-user access is unchanged. No SECURITY DEFINER function is introduced; the
-- subquery runs under client_portal_users_self (a contact reads only their own rows).

CREATE POLICY portal_contact_sees_own_documents ON public.client_documents
    FOR SELECT TO authenticated
    USING (client_id IN (SELECT client_id FROM public.client_portal_users
                         WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'));

CREATE POLICY portal_contact_sees_own_requests ON public.document_requests
    FOR SELECT TO authenticated
    USING (client_id IN (SELECT client_id FROM public.client_portal_users
                         WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'));

CREATE POLICY portal_contact_fulfills_own_requests ON public.document_requests
    FOR UPDATE TO authenticated
    USING (client_id IN (SELECT client_id FROM public.client_portal_users
                         WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'));

CREATE POLICY portal_contact_messages ON public.portal_messages
    FOR ALL TO authenticated
    USING (client_id IN (SELECT client_id FROM public.client_portal_users
                         WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'))
    WITH CHECK (client_id IN (SELECT client_id FROM public.client_portal_users
                              WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'));

CREATE POLICY portal_contact_sees_own_shared_reports ON public.shared_reports
    FOR SELECT TO authenticated
    USING (client_id IN (SELECT client_id FROM public.client_portal_users
                         WHERE auth_user_id = ( SELECT auth.uid() ) AND status = 'active'));

COMMENT ON TABLE public.client_portal_users IS
    'Phase 4.5.1: multiple portal contacts per client. Additive to the legacy clients.portal_user_id single-user link; both resolve in get_current_portal_client and in RLS.';

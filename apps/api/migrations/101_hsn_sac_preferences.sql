-- PracticeSync AI — Migration 101: hsn_sac_preferences (smart HSN/SAC suggestions)
--
-- Learns the HSN/SAC code a firm habitually uses for a given line description so
-- the invoice form can auto-suggest it ("Used in 47 previous GST Filing
-- invoices") and reduce manual HSN entry. CGST Rule 46(g): HSN/SAC is a
-- mandatory tax-invoice field, so getting it right and consistent matters.
--
-- One row per (firm, client, normalised description, hsn_sac). use_count and
-- last_used_at drive ranking: a code the user picks most recently/most often
-- surfaces first, so an override is prioritised next time. Pure metadata — this
-- table feeds the UI only and is NEVER read by any GST/journal/report code.
--
-- Backfilled from existing invoice lines so suggestions work from day one.

CREATE TABLE IF NOT EXISTS public.hsn_sac_preferences (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            UUID        NOT NULL,
    client_id          UUID        NOT NULL,
    -- Normalised lookup key: lower-cased, whitespace-collapsed line description.
    description_key    TEXT        NOT NULL,
    -- A representative original-cased description, for display in the dropdown.
    sample_description TEXT        NOT NULL,
    hsn_sac            TEXT        NOT NULL,
    -- Last GST rate used with this description+code (bps; 1800 = 18%). Lets the
    -- form pre-fill the rate too. Never used for any tax computation.
    gst_rate_bps       INTEGER,
    use_count          INTEGER     NOT NULL DEFAULT 1,
    last_used_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (firm_id, client_id, description_key, hsn_sac)
);

CREATE INDEX IF NOT EXISTS idx_hsn_pref_lookup
    ON public.hsn_sac_preferences (firm_id, client_id, description_key);
CREATE INDEX IF NOT EXISTS idx_hsn_pref_rank
    ON public.hsn_sac_preferences (firm_id, client_id, last_used_at DESC, use_count DESC);

ALTER TABLE public.hsn_sac_preferences ENABLE ROW LEVEL SECURITY;

-- RLS: identical three-policy stack used by invoice_deliveries / receipts
-- (migration 084 assignment-scoped pattern). Backend may use a per-user JWT
-- client (USE_USER_JWT), so the table must be safe under RLS.
CREATE POLICY firm_hsn_preferences
    ON public.hsn_sac_preferences
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

CREATE POLICY hsn_preferences_assignment_scope
    ON public.hsn_sac_preferences
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (can_access_client((client_id)::text));

CREATE POLICY hsn_preferences_internal_partner_only
    ON public.hsn_sac_preferences
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (
        (get_my_role() = 'Partner'::text)
        OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text)
    );

GRANT SELECT, INSERT, UPDATE ON public.hsn_sac_preferences TO authenticated;
GRANT ALL                     ON public.hsn_sac_preferences TO service_role;

-- ---------------------------------------------------------------------------
-- Backfill from historical invoice lines. Full Postgres aggregation (PostgREST
-- can't GROUP BY at runtime), so the suggestion endpoint only does simple reads.
-- ---------------------------------------------------------------------------
INSERT INTO public.hsn_sac_preferences
    (firm_id, client_id, description_key, sample_description, hsn_sac, gst_rate_bps, use_count, last_used_at)
SELECT
    i.firm_id,
    i.client_id,
    lower(btrim(regexp_replace(l.description, '\s+', ' ', 'g')))            AS description_key,
    (array_agg(l.description    ORDER BY i.created_at DESC))[1]             AS sample_description,
    l.hsn_sac,
    (array_agg(l.gst_rate_bps   ORDER BY i.created_at DESC))[1]             AS gst_rate_bps,
    count(*)                                                               AS use_count,
    max(i.created_at)                                                      AS last_used_at
FROM public.client_sales_invoice_lines l
JOIN public.client_sales_invoices i ON i.id = l.sales_invoice_id
WHERE l.hsn_sac     IS NOT NULL AND btrim(l.hsn_sac)     <> ''
  AND l.description IS NOT NULL AND btrim(l.description) <> ''
GROUP BY i.firm_id, i.client_id, description_key, l.hsn_sac
ON CONFLICT (firm_id, client_id, description_key, hsn_sac) DO NOTHING;

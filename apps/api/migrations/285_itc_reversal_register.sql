-- PracticeSync — Migration 285: itc_reversal_register
--
-- WHY
--   GSTR-3B Table 4(B)(2) declares credit reversed that MAY come back — Rule
--   37 / 37A (supplier unpaid 180 days), CGST Act §16(2)(b) and (c). Table
--   4(D)(1) declares the reclaim when it does. Neither could ever be filled:
--   nothing in this system recorded that a reclaimable reversal had happened,
--   so there was never anything to reclaim against.
--
--   services/itc_reversal_service computes which bills are past 180 days. It
--   deliberately posts nothing — the reversal is the CA's decision. But once
--   they make it, the decision had nowhere to live.
--
-- WHY IT REGISTERS A JOURNAL RATHER THAN POSTING ONE
--   CLAUDE.md: one posting kernel, no alternative paths. A reclaimable
--   reversal moves real money on the ledger — credit given back is a credit to
--   GST Input — and that posting already has a home: the CA raises it as a
--   manual journal through phase2_journal_service like any other entry.
--
--   What was missing is not a way to POST it but a way to SAY WHAT IT WAS. A
--   journal crediting GST Input could be a Rule 37 reversal, a cancelled bill,
--   or a correction, and the return has to tell them apart. So each row here
--   points at an already-posted journal and classifies it. The register never
--   creates a GL entry, which is why it cannot drift from one.
--
--   The consequence that matters: because these reversals ARE posted, the
--   books-vs-ledger reconciliation must net them like any other movement. That
--   is the opposite of the note in gst_return_service, which nets permanent
--   reversals only because Rule 37 amounts were unposted. They no longer are.
--
-- A reclaim is a row of kind 'reclaim' pointing at the reversal it releases,
-- so a reversal can be reclaimed in parts across several periods and what is
-- still outstanding is a running sum. Append-only in the same spirit as
-- party_credit_ledger: a mistaken row is corrected by another row, never by
-- an update, because both sides have already been declared on a filed return.
--
-- Additive: a new table only. No existing figure moves.

CREATE TABLE IF NOT EXISTS public.itc_reversal_register (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id           UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

    -- The posted journal that actually moved the credit. NOT NULL: a register
    -- row with no journal behind it is a return figure the ledger cannot
    -- support, which is the whole failure mode this design exists to avoid.
    journal_entry_id  UUID NOT NULL REFERENCES public.journal_entries(id),

    kind              TEXT NOT NULL
                        CHECK (kind IN ('reversal', 'reclaim')),

    -- Why the credit went back. Only reclaimable grounds belong here:
    -- a permanent reversal (Rule 38/42/43, §17(5)) is Table 4(B)(1) and is
    -- derived from the documents, not registered.
    reason_code       TEXT NOT NULL
                        CHECK (reason_code IN ('rule_37', 'rule_37a',
                                               'section_16_2b', 'section_16_2c',
                                               'other')),

    -- MMYYYY of the GSTR-3B this row is declared in.
    period            TEXT NOT NULL CHECK (period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),

    igst_paise        BIGINT NOT NULL DEFAULT 0 CHECK (igst_paise >= 0),
    cgst_paise        BIGINT NOT NULL DEFAULT 0 CHECK (cgst_paise >= 0),
    sgst_paise        BIGINT NOT NULL DEFAULT 0 CHECK (sgst_paise >= 0),
    cess_paise        BIGINT NOT NULL DEFAULT 0 CHECK (cess_paise >= 0),

    -- Which bill's credit this is, where it is known. Rule 37 is per invoice.
    purchase_bill_id  UUID REFERENCES public.purchase_bills(id) ON DELETE SET NULL,

    -- For a reclaim: the reversal it releases. A reversal has none.
    reverses_id       UUID REFERENCES public.itc_reversal_register(id),

    notes             TEXT,
    created_by        UUID REFERENCES public.users(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A reclaim without the reversal it releases could not be reported in
    -- 4(D)(1), which is defined as "reclaimed... reversed under 4(B)(2) in an
    -- earlier tax period". A reversal pointing at another one is nonsense.
    CONSTRAINT itc_reversal_register_reclaim_has_parent
        CHECK ((kind = 'reclaim' AND reverses_id IS NOT NULL)
            OR (kind = 'reversal' AND reverses_id IS NULL)),

    -- A row that moves nothing is not a declaration.
    CONSTRAINT itc_reversal_register_nonzero
        CHECK (igst_paise + cgst_paise + sgst_paise + cess_paise > 0)
);

CREATE INDEX IF NOT EXISTS idx_itc_reversal_register_period
    ON public.itc_reversal_register(firm_id, client_id, period);
CREATE INDEX IF NOT EXISTS idx_itc_reversal_register_reverses
    ON public.itc_reversal_register(reverses_id);
CREATE INDEX IF NOT EXISTS idx_itc_reversal_register_journal
    ON public.itc_reversal_register(journal_entry_id);

-- One register row per journal: the same posting cannot be declared twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_itc_reversal_register_journal
    ON public.itc_reversal_register(journal_entry_id);

ALTER TABLE public.itc_reversal_register ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_manage_itc_reversal_register"
    ON public.itc_reversal_register;
CREATE POLICY "firm_staff_manage_itc_reversal_register"
    ON public.itc_reversal_register
    FOR ALL
    USING (firm_id IN (SELECT firm_id FROM public.users WHERE auth_user_id = auth.uid()))
    WITH CHECK (firm_id IN (SELECT firm_id FROM public.users WHERE auth_user_id = auth.uid()));

COMMENT ON TABLE public.itc_reversal_register IS
  'Reclaimable ITC reversals (GSTR-3B Table 4(B)(2)) and their later reclaims '
  '(Table 4(D)(1)). Each row CLASSIFIES an already-posted journal; it never '
  'creates one. Permanent reversals (Rule 38/42/43, section 17(5)) are Table '
  '4(B)(1) and are derived from the documents, not registered here.';

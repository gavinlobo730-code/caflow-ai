-- Migration 273: give the s.185/s.186 related-party loans feature its own table.
--
-- WHAT WAS WRONG
-- routers/relationships.py has always written its loans to `loans`. It cannot:
-- it names seven columns that table does not have --
--
--     entity_id, interest_rate, sanction_date, due_date,
--     section_185_flagged, section_186_flagged, updated_at
--
-- -- and two loan_type values its CHECK rejects (to_director, inter_company;
-- the CHECK permits term_loan/overdraft/cc/home_loan/vehicle_loan/
-- personal_loan/other). Four of the five loans queries in that router are
-- broken, including POST /relationships/loans, the s.185 report and the
-- client-level rollup. The feature has never worked against a real database.
--
-- WHY A NEW TABLE AND NOT MORE COLUMNS ON `loans`
-- Two unrelated things collided on one name, and BOTH are live.
--
--   `loans` (migration 026, loans_and_fd) is a client's BORROWINGS register:
--   lender_name, account_number, emi_paise, outstanding_paise,
--   disbursement_date, maturity_date. It works, and the browser reads and
--   writes it directly from /accounting/loans, /risks and /reports/cash-flow.
--
--   The relationships feature records a RELATED-PARTY loan for Companies Act
--   compliance: which entity, sanctioned when, and whether s.185 (loans to
--   directors) or s.186 (inter-corporate loans) is engaged. It has no lender,
--   no EMI, no account number, and a bank borrowing has no director.
--
-- Bolting seven columns onto `loans` would leave every borrowings row carrying
-- permanently-null compliance fields and every compliance row carrying
-- permanently-null banking fields, with nothing in the schema saying which
-- half of the table any row belongs to. The two concepts stay apart.
--
-- WHAT THIS DOES NOT DO
-- It does not migrate any data. `loans` holds zero rows written by the
-- relationships feature -- it never managed to write one -- so there is
-- nothing to move, and the borrowings rows already there are not related-party
-- loans and must not be copied.
--
-- interest_rate is NUMERIC, not double precision. The API models it as a float
-- and the code comments it "display only -- not used in calculations", which is
-- exactly the case where an exact type costs nothing and removes the question.
--
-- Idempotent, and safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS public.related_party_loans (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID          NOT NULL REFERENCES public.firms(id)    ON DELETE CASCADE,
    client_id           UUID          NOT NULL REFERENCES public.clients(id)  ON DELETE CASCADE,
    -- The counterparty. RESTRICT, not CASCADE: deleting an entity must not
    -- silently erase the evidence for a s.185 finding recorded against it.
    entity_id           UUID          NOT NULL REFERENCES public.entities(id) ON DELETE RESTRICT,
    loan_type           TEXT          NOT NULL CHECK (loan_type IN (
                            'to_director', 'from_director', 'inter_company', 'other')),
    principal_paise     BIGINT        NOT NULL CHECK (principal_paise > 0),
    -- Annual percent. NUMERIC so it is exact; models/LoanIn documents it as
    -- display-only and nothing computes with it.
    interest_rate       NUMERIC(6,3),
    sanction_date       DATE,
    due_date            DATE,
    notes               TEXT,
    -- Companies Act 2013 s.185 -- a company advancing a loan to its director.
    -- Derived by the API from loan_type at write time, stored so the report can
    -- be a filter rather than a scan, and so a later change to the derivation
    -- cannot silently restate what was already flagged for a CA.
    section_185_flagged BOOLEAN       NOT NULL DEFAULT false,
    -- Companies Act 2013 s.186 -- inter-corporate loans and investments.
    section_186_flagged BOOLEAN       NOT NULL DEFAULT false,
    created_by          UUID,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_related_party_loans_client
    ON public.related_party_loans (firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_related_party_loans_entity
    ON public.related_party_loans (entity_id);
-- The s.185 report and the client rollup both filter on the flags and read
-- nothing else to decide; partial so the index stays the size of the findings
-- rather than the size of the table.
CREATE INDEX IF NOT EXISTS idx_related_party_loans_flagged
    ON public.related_party_loans (firm_id, client_id)
    WHERE section_185_flagged OR section_186_flagged;

ALTER TABLE public.related_party_loans ENABLE ROW LEVEL SECURITY;

-- Firm isolation, the same shape every table created since migration 154 uses.
DROP POLICY IF EXISTS related_party_loans_isolation ON public.related_party_loans;
CREATE POLICY related_party_loans_isolation ON public.related_party_loans
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- Assignment scope, layered RESTRICTIVE so it ANDs with the above rather than
-- widening it -- the pattern journal_entries_assignment_scope uses. The API
-- already calls assert_client_access on every one of these endpoints; this is
-- the same rule where it cannot be skipped. Director-loan records are among
-- the most sensitive rows in the schema and there is no reason a staff member
-- unassigned from a client should read them.
DROP POLICY IF EXISTS related_party_loans_assignment_scope ON public.related_party_loans;
CREATE POLICY related_party_loans_assignment_scope ON public.related_party_loans
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.related_party_loans TO authenticated;
GRANT ALL                            ON public.related_party_loans TO service_role;

COMMENT ON TABLE public.related_party_loans IS
    'Related-party loans for Companies Act s.185 (loans to directors) and s.186 '
    '(inter-corporate loans). Distinct from public.loans, which is a client''s '
    'own borrowings register (lender, EMI, outstanding) -- see migration 273.';

COMMIT;

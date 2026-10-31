-- 568 — a recorded TDS challan can be tied to the ledger entry that paid it (POST-A-272).
--
-- THE GAP
--
-- `tds_challans` carries the challan's own facts (serial, BSR code, date, the tax / surcharge / interest / penalty split, section,
-- quarter) and no reference to the ledger. The product's one path for money leaving a bank is passing a statement line
-- (`bank_posting_service.post` writes Dr <liability> / Cr Bank), so after the tax is deposited and the challan recorded, TDS Payable
-- keeps its whole credit until somebody passes a bank line to it by hand, and nothing says whether a recorded challan HAS a line
-- behind it. A liability nobody has paid and one that was paid and never tied back look identical on the ledger. ESI and professional
-- tax remittances answer this with `statutory_remittances.journal_entry_id` (migration 365); this gives the TDS register the same.
--
-- WHAT THIS ADDS
--
-- One nullable column, `journal_entry_id`, and a partial index on it. It is a LINK, never a posting: posting from the challan as well
-- as from the bank line would debit TDS Payable twice. ON DELETE SET NULL, as in 365: reversing the payment entry unlinks the
-- challan, it does not erase the record that the tax was deposited. NULL means "not tied to a ledger entry", which is the state of
-- every challan recorded before this. No backfill: which entry paid which challan is the CA's answer, not a guess made here.
--
-- Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.tds_challans
    ADD COLUMN IF NOT EXISTS journal_entry_id uuid REFERENCES public.journal_entries(id) ON DELETE SET NULL;

-- Which challan a payment entry is tied to, and the challans with no entry (the month-end question). Partial: most rows start NULL.
CREATE INDEX IF NOT EXISTS idx_tds_challans_journal_entry
    ON public.tds_challans (journal_entry_id)
    WHERE journal_entry_id IS NOT NULL;

COMMENT ON COLUMN public.tds_challans.journal_entry_id IS
    'The ledger entry that paid this challan (Dr TDS Payable / Cr Bank). A link only, never a posting; NULL = not tied to an entry. POST-A-272.';

COMMIT;

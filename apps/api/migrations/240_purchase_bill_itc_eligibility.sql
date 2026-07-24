-- Migration 240 — CGST Act §17(5) blocked-credit ITC eligibility.
--
-- Task #239 audit finding: compute_gstr3b (domain/gst/gstr3b_computer.py)
-- claimed 100% of the GST on every posted purchase as Table 4 ITC, with no
-- way to mark a line as ineligible under CGST Act §17(5) (e.g. motor
-- vehicles for personal use, food & beverages, club/health/fitness
-- membership, works contract services for immovable property, goods/
-- services for personal consumption). GSTR-3B's own Table 4(D)(1)
-- ("ineligible ITC") was hard-coded empty as a result.
--
-- Eligibility is inherently a per-LINE judgment (one bill can mix an
-- eligible office-supplies line with a blocked club-membership line) and
-- can only be a CA-driven manual flag -- it cannot be safely inferred from
-- HSN/SAC or the line's expense_account_id (a firm's chart-of-accounts
-- naming is free-text and not GST-purpose-coded; e.g. a "vehicle expenses"
-- account line IS eligible ITC if the vehicle is used for further supply,
-- passenger transport or driving training -- §17(5)(a) provisos). This
-- mirrors the existing manual-flag pattern already used elsewhere in this
-- schema for CA judgment calls (vendors.tds_applicable, purchase_bills.
-- is_reverse_charge).
--
-- The bill-header ineligible_itc_*_paise columns are an aggregate of its
-- ineligible lines (same "persist a line-level sum onto the header" pattern
-- purchase_bills.total_gst_paise already uses) so gstr3b_from_books (which
-- reads purchase_bills, not purchase_bill_lines) can compute Table 4(D)
-- without a per-line join.

ALTER TABLE public.purchase_bill_lines
    ADD COLUMN IF NOT EXISTS itc_eligible BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS blocked_credit_reason TEXT;

COMMENT ON COLUMN public.purchase_bill_lines.itc_eligible IS
    'CA-set flag -- false means this line''s GST is BLOCKED input tax credit under CGST Act §17(5) and must be excluded from the GSTR-3B ITC claim. Never inferred; defaults true (the pre-existing, unrestricted behavior) so no existing bill changes.';
COMMENT ON COLUMN public.purchase_bill_lines.blocked_credit_reason IS
    'CA-selected reason code when itc_eligible = false, e.g. 17_5_a_motor_vehicle | 17_5_b_food_beverage | 17_5_b_club_membership | 17_5_c_works_contract_immovable | 17_5_g_personal_consumption | other. Free text, not a DB enum -- the §17(5) category list may need CA-facing wording changes without a migration.';

ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS ineligible_itc_igst_paise BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ineligible_itc_cgst_paise BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ineligible_itc_sgst_paise BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ineligible_itc_cess_paise BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.purchase_bills.ineligible_itc_igst_paise IS
    'Sum of igst_paise across this bill''s itc_eligible=false lines (CGST Act §17(5)) -- excluded from the GSTR-3B ITC claim (Table 4(A)) and reported instead under Table 4(D)(1).';

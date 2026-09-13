# 07 — GST Engine

Indian GST is **statutory and filed in INR**. The engine computes tax at source in integer paise and builds the returns; it never auto-submits to any portal.

> Every government-facing action requires an explicit CA confirmation click. Code that would call a government API carries: `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`.

## Identifiers

- **GSTIN**: 2-digit state code + PAN (10) + entity digit + `Z` + check digit. Regex enforced (`routers/customers.py`, CGST Act §25).
- **PAN**: `AAAAA9999A`.

## Tax computation (at source)

`_compute_line_gst` (`routers/sales_invoices.py`) — pure integer-paise math, no float in stored values:
- Rate held as **basis points** (`gst_rate_bps`); `igst = (taxable_paise * gst_rate_bps) // 10000` (floor division).
- **CGST Act §8** place-of-supply split: **intra-state → CGST + SGST** (half each); **inter-state → IGST**. Determined by comparing supplier vs customer state code.
- Stored on the invoice: `taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_gst_paise, total_paise` (and per line).

### Compensation cess

A fourth head, and deliberately not folded into the three above. GST (Compensation to States) Act 2017 §8(2) levies it "on the basis of **value, quantity or on such basis**", so a line carries `cess_rate_bps` (ad valorem) AND `cess_specific_paise_per_unit`, and the charge is their **sum** — coal is per tonne, aerated waters a percentage, cigarettes both (migration 374). `domain/gst/compensation_cess.py` is the authority; `apps/web/lib/money/cessLine.ts` mirrors it and `shared/gst-parity-vectors.json` pins the two. The amount is derived from the rates, never typed, and both roundings match `_compute_line_gst` because §11(2) applies the CGST Act mutatis mutandis.

§11(2)'s proviso — credit of this cess "shall be utilised only towards payment of cess" — is why it stays separate all the way down: its own ledgers (`Compensation Cess Input Credit` / `Compensation Cess Payable`, keys `gst_cess_input` / `gst_cess_output`), out of the §49(5) set-off ladder in Table 6, in `total_paise` and NOT in `total_gst_paise`. On a reverse-charge inward supply it is self-assessed onto Table 3.1(d) like the other heads (`rcm_cess`) and paid in cash. No rate table is held — which cess reaches which HSN is Schedule data a human records. The four §34 note tables have no cess column; a note against a cess-bearing invoice is named in the return's `cess_gaps`.

Every GST posting reaches the ledger through the single kernel (`journal_for_sales_invoice` / `journal_for_credit_note` → `_create_journal`), crediting the GST output heads. GST control accounts resolve via `system_account_key`: `gst_output`, `gst_cgst`, `gst_sgst`, `gst_igst`, `gst_input`.

## Returns

`domain/gst/` (migration `036_gst_engine.sql`):
- **GSTR-1** (`gstr1_builder.py`) — outward supplies; B2B/B2CL/B2CS/HSN sections; paise summed, converted to rupees only for the GSTN JSON (`round(paise/100, 2)`); thresholds (₹2.5L B2CL, HSN turnover tiers) are hardcoded INR constants.
- **GSTR-3B** (`gstr3b_computer.py`) — summary + ITC; Rule 36(4) ITC cap in integer paise.
- **GSTR-2B reconciliation** — ITC matching.
- `classifier.py` categorises transactions (`invoice`, `credit_note`, `debit_note` as a *classification string*, etc.); `validator.py` validates return payloads.
- Router: `routers/gst.py`. Filing status transitions are gated (draft → submitted/filed) and audited; **no auto-submit**.

## Statutory due dates (domain rules)

- GSTR-1: 11th of the following month · GSTR-3B: 20th of the following month · GSTR-9 (annual): 31 December.

## All amounts are INR

GSTN accepts only INR; the whole engine is INR by definition. Every rule cites the relevant CGST Act section in code comments.

## Multi-currency note

GST **stays INR** (`06-multi-currency-phase0.md`). For a foreign-currency invoice, the system must compute and persist the **INR-equivalent taxable value at the CGST Rule 34 notified rate** on the invoice date and feed *that* into `_compute_line_gst` and the return builders. The engines' integer math is unchanged; the work is the upstream conversion (a Phase 2 concern). Exports are typically zero-rated (LUT / with payment).

## Tests

`tests/test_phase3_gst.py`, `tests/test_hardening.py` (GST portions). Several require a live DB (TestClient) and return 503 in the unit environment — a known environmental limitation, not a logic failure.

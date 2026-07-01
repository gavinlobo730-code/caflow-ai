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

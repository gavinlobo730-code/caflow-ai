# 07 — GST Engine

Indian GST is **statutory and filed in INR**. The engine computes tax at source in integer paise and builds the returns; it never auto-submits to any portal.

> Every government-facing action requires an explicit CA confirmation click. Code that would call a government API carries: `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`.

This note says where things are. The reasoning behind each rule, and what each one deliberately does not do, is in `CLAUDE.md` (grep it for the subsystem); it is not restated here, because two copies drift. A module named below without a directory is in `domain/gst/`. `tests/test_the_gst_architecture_doc_names_what_the_code_holds.py` checks that every file named here exists and that the figures quoted are the code's.

## Identifiers

- **GSTIN**: 2-digit state code + PAN (10) + entity digit + `Z` + check digit. The check digit is tested, not just the shape: `problem_with` (`gstin.py`) is the authority, `apps/web/lib/gst/gstin.ts` mirrors it for keystroke feedback and `tests/fixtures/gstin.json` pins the two. It is asked wherever a human types a GSTIN (customer and vendor create, bulk import and PATCH, onboarding) and on the paths that file with one. A shape regex accepts a transposed digit and hands a customer's credit to a stranger (CGST Act §16(2)(aa)).
- **PAN**: `AAAAA9999A`.

## Tax computation (at source)

`compute_line_gst` (`domain/sales/line_tax.py`) is pure integer-paise math, no float in stored values; `routers/sales_invoices.py` keeps the alias `_compute_line_gst`:
- Rate held as **basis points** (`gst_rate_bps`). The **full** tax is floored first, `(taxable_paise * gst_rate_bps) // 10000`, and only then halved on an intra-State supply, SGST carrying the odd paisa, so CGST + SGST always equals the IGST an identical inter-State supply would attract.
- **Intra-State → CGST + SGST; inter-State → IGST** (CGST Act §9, IGST Act §5). Which one is decided by comparing the supplier's State with the place of supply, which `recipient_place_of_supply` (`place_of_supply.py`) resolves in a fixed order: what the document states (Rule 46(n)), the customer's recorded State, the customer's GSTIN prefix, and last the supplier's own State.
- A discount recorded on the invoice reduces the value of supply before tax (CGST Act §15(3)(a)): `discount.py`, line discount first and then the document discount spread pro rata.
- Stored on the invoice: `taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_gst_paise, total_paise` (and per line). The browser's keystroke mirror is `apps/web/lib/money/gstLine.ts`; `shared/gst-parity-vectors.json` pins it to the Python.

### Compensation cess

A fourth head, and deliberately not folded into the three above. GST (Compensation to States) Act 2017 §8(2) levies it "on the basis of **value, quantity or on such basis**", so a line carries `cess_rate_bps` (ad valorem) AND `cess_specific_paise_per_unit`, and the charge is their **sum** — coal is per tonne, aerated waters a percentage, cigarettes both (migration 374). `compensation_cess.py` is the authority; `apps/web/lib/money/cessLine.ts` mirrors it and `shared/gst-parity-vectors.json` pins the two. The amount is derived from the rates, never typed, and both roundings match `compute_line_gst` because §11(2) applies the CGST Act mutatis mutandis.

§11(2)'s proviso — credit of this cess "shall be utilised only towards payment of cess" — is why it stays separate all the way down: its own ledgers (`Compensation Cess Input Credit` / `Compensation Cess Payable`, keys `gst_cess_input` / `gst_cess_output`), out of the §49(5) set-off ladder in Table 6, in `total_paise` and NOT in `total_gst_paise`. On a reverse-charge inward supply it is self-assessed onto Table 3.1(d) like the other heads (`rcm_cess`) and paid in cash. No rate table is held — which cess reaches which HSN is Schedule data a human records. The four §34 note tables have no cess column; a note against a cess-bearing invoice is named in the return's `cess_gaps`.

Every GST posting reaches the ledger through the single kernel (`journal_for_sales_invoice` / `journal_for_credit_note` → `_create_journal`), crediting the GST output heads. GST control accounts resolve via `system_account_key`: `gst_output`, `gst_cgst`, `gst_sgst`, `gst_igst`, `gst_input`.

## Returns

The tables are in `migrations/036_gst_engine.sql` and the migrations after it. What decides what:

| Module | What it decides |
|---|---|
| `gstr1_builder.py` | GSTR-1 sections (B2B, B2CL, B2CS, nil, CDNR, CDNUR, exports), Table 12 HSN summary and Table 13 document series; paise summed, converted to rupees only at the boundary |
| `money.py` | that boundary: 2-decimal rupees for GSTR-1, **whole** rupees for GSTR-3B (CGST Act §170, half rounded up) |
| `classifier.py` | which GSTN table a transaction belongs to. The B2CL limit (CGST Rule 59(4)) is a function of the invoice's date, not a constant: `B2CL_THRESHOLD_PAISE` (₹1 lakh from 01-08-2024, Notification 12/2024-CT) and `B2CL_THRESHOLD_LEGACY_PAISE` (₹2.5 lakh before it), tested on the invoice value of an inter-State supply to an unregistered person |
| `hsn_digits.py` | how many HSN digits Table 12 must carry: two notification tables (the original, and 78/2020-CT from 01-04-2021) chosen by the return period, on the preceding year's aggregate turnover held in `client_gst_turnover` (migration 401); a shortfall is reported, never truncated |
| `uqc.py` | CBIC's unit quantity codes; a wrong or absent unit is reported in the return's gaps, not refused |
| `gstr3b_computer.py` | GSTR-3B. Table 4 follows Notification 14/2022-CT (4(A) gross, 4(B) reversals, 4(C) = 4(A) − 4(B)); Table 6 sets off in four steps (§49(5)) against 4(C) plus the opening credit balance; reverse-charge tax is always cash |
| `credit_ledger.py` | the running electronic credit ledger: a balance a CA keyed, else the previous return's closing, else *not known* (migration 474) |
| `rule_36_4.py` | §16(2)(aa) credit asked of each **document** (in GSTR-2B or not), not a sum per head |
| `gstr2b.py`, `itc_matching.py` | parsing the portal's GSTR-2B and the four-answer match against the purchase books; `gstr2b_intake.py`, `gstr2b_routing.py` and `itc_probable.py` say which month and registration a file is for, route a file by the GSTIN inside it, and suggest (never apply) probable matches |
| `itc_reversal.py`, `rule_37a.py`, `rule_43.py`, `section_18_6.py` | credit that has to be paid back: the register, Rule 37A, Rule 43 and CGST §18(6) on the sale of a capital asset |
| `late_filing.py` | §50 interest (Rule 88B) and the §47 late fee, for the years its table holds |
| `return_period.py` | a return period is not always a month: a QRMP quarter is keyed on its first month |
| `registrations.py` | one client, several GSTINs, each with its own type (regular, composition, ISD …) |
| `iff.py` | the Invoice Furnishing Facility (Rule 59(2)) for months 1 and 2 of a quarter |
| `composition.py`, `gstr8.py`, `gstr4_annual.py`, `gstr9c.py` | the returns a regular registration never files: CMP-08, GSTR-8, GSTR-4 annual and GSTR-9C |
| `gstr9_builder.py` | the annual return, consolidated from the year's own GSTR-1 and GSTR-3B |
| `amendments.py`, `exception_report.py`, `correction_window.py` | §37(3) amendments, what changed since a return was filed, and the §37(3)/§39(9)/§16(4) cut-off |
| `bill_of_entry.py`, `rcm_documents.py`, `bank_charge_gst.py` | IGST on imported goods, the reverse-charge self-invoice and payment voucher, GST on a bank line |
| `treatment.py`, `irn_scope.py`, `irp_validations.py` | what kind of supply an invoice is, whether it must carry an IRN (Rule 48(4)), and the portal's own acceptance rules (`NOT_HELD` names what is not checked) |
| `eway.py`, `eway_validity.py`, `eway_expiry.py` | e-way bill scope, validity and expiry (Rule 138) |
| `validator.py` | validates return payloads |

All builders are pure: they take rows and return a payload plus **gaps** — a particular they could not derive is named, never filed as a nil.

## Routers and services

- `routers/gst.py` is stateless: classify, compute, validate and build-from-books. It writes nothing.
- `routers/gst_workspace.py` is the persisted side: saved GSTR-1 and GSTR-3B returns, the status PATCH, the filing history, GSTR-2B upload and reconciliation, the compute endpoints for IFF, CMP-08, GSTR-8, GSTR-4 annual, GSTR-9 and GSTR-9C, and the ITC registers.
- `services/gst_return_service.py` reads the books and hands the builders their rows.
- A return moves draft → validated → ca_approved → submitted. The last two need an explicit `ca_approved=true` and a Manager or above. **Nothing is transmitted**: `submitted` is the CA recording a filing made on the portal, and `services/gst_filing_record_service.py` writes the `public.filings` row that `journal_period_lock_reason` reads, which is what locks the period.

## Statutory due dates (domain rules)

`services/compliance_engine.py` is the single source. GSTR-1: 11th of the following month (13th after the quarter for a QRMP filer) · GSTR-3B: 20th of the following month (22nd or 24th after the quarter, by the State of registration) · IFF: 13th, optional · GSTR-9 (annual): 31 December.

## All amounts are INR

GSTN accepts only INR; the whole engine is INR by definition. Every rule cites the relevant CGST Act section in code comments.

## Multi-currency note

GST **stays INR** (`06-multi-currency-phase0.md`), and the upstream conversion is built (`06c`): a foreign-currency document freezes its rate and carries authoritative **base (INR)** amounts, which the GL, GST and the return builders read, so `compute_line_gst` and the engines' integer math are unchanged. A rate type `gst_notified` (the CGST Rule 34 notified rate) exists in `domain/currency/rate_types.py`. Exports are typically zero-rated (LUT / with payment).

## Tests

`tests/test_gst_engine.py`, `tests/test_gstr3b_setoff_and_rcm.py`, `tests/test_gst_parity_vectors.py`, `tests/test_phase3_gst.py` and the GST portions of `tests/test_hardening.py`. They run in mock mode with no database; the real-Postgres modules are the ones named `test_*_pg.py`.

Complete. Report follows.

---

# SALES slice — probe against HEAD `92392e2c`

## Already handled (reported per instruction, not re-probed)

SALES-05, SALES-11, SALES-12, SALES-15, SALES-16, SALES-17, SALES-19, SALES-24, SALES-26, SALES-27, SALES-28, SALES-29 — closed (fixed earlier).
**SALES-14 — closed (fixed earlier), and the endpoint is NO LONGER unreached.** `PATCH /api/receipts/{id}/allocate` (`apps/api/routers/receipts.py:203`) is now called by `apps/web/components/sales/AllocateReceiptModal.tsx:136` (`api.receipts.allocate`), mounted at `apps/web/app/clients/[id]/sales/page.tsx:3395` with the reason recorded at `:3186-3189`. The party-credit half (`grant_credit` still has one caller, `services/bank_posting_service.py:676`) is unchanged but is not what the finding's ca_experience turns on.
**SALES-25a — closed (fixed earlier).** SALES-25b probed below.

---

## SALES-01 — VERDICT: closed
EVIDENCE: `apps/api/services/invoice_pdf_service.py:838` `def build_sales_invoice_pdf(invoice, client, customer)`; `:1051` `pdf = build_sales_invoice_pdf(invoice_dict, client, customer)`; `_SUPPLIER_COLUMNS` at `:945-948` selects from `clients`. Statement half: `services/statement_pdf_service.py:128` `def load_account_holder(db, firm_id, client_id)` reads `clients` firm-scoped (`:137`), used at `:152`.
PREMISE: was true; now FALSE. `_load_firm` (`:931`) survives only on the fee-invoice path (`get_invoice_pdf`, `:883`).
FIX / SHAPE / SIZE: n/a.

## SALES-02 — VERDICT: closed
EVIDENCE: `grep -n GST_RATE_PCT apps/api/services/invoice_pdf_service.py` → no match. Rate is derived per line/per document (`_line_rate`, `_document_rate`), Rule 46(g)/(h)/(l) columns are on the sales layout.
PREMISE: FALSE today.

## SALES-03 — VERDICT: closed (the IRN/QR half the 8 Sept rescore left open is now done)
EVIDENCE: `apps/api/services/invoice_pdf_service.py:951` `_einvoice_record_for` selects `irn, ack_number, ack_date, qr_data, status` from `einvoice_records` firm-scoped on `sales_invoice_id`; `:1049` splats `_einvoice_particulars(...)` into `invoice_dict`; `:229-243` refuses anything not `status == "generated"` with a real `irn`; `:245-263` `_qr_flowable` renders the IRP's own signed payload verbatim and returns `None` rather than raising; `:620` `qr_drawing = _qr_flowable(invoice.get("qr_data"))`. Column exists: `migrations/156_missing_tables_f5.sql:206-208`. Reverse charge from the flag at `:732`; place of supply at `:607-609`.
PREMISE: all three halves FALSE today. The module comment at `:206-225` records the refusal that matters — a QR is never composed by this app, only the IRP's is printed.
SHAPE: nothing to change.

## SALES-04 — VERDICT: closed
EVIDENCE: `apps/api/services/numbering.py:82-109` `sequence_after` takes MAX+1 (`highest = max(highest, int(tail))`), with the docstring at `:86-99` naming the count+1 wedge as the defect. `next_sequence` (`:112-138`) reads a 50-row window ordered desc and validates the scope against `NUMBER_SERIES` (`:57-70`). All five series now delegate: `routers/credit_notes.py:105-107`, `routers/sales_debit_notes.py:116-118`, `routers/debit_notes.py:124-126`, `routers/purchase_credit_notes.py:124-126`, `services/receipt_service.py:64-66`, plus `routers/purchase_payments.py:216-217` and `routers/fixed_assets.py:678`. Guard test `apps/api/tests/test_a_deleted_draft_does_not_wedge_numbering.py` exists.
PREMISE: FALSE today.

## SALES-06 — VERDICT: closed
EVIDENCE: `apps/web/lib/invoices/gst.ts:364` is now a re-export — `export { INDIAN_STATES, type IndianState } from "../constants/indianStates.ts";` — so the 30-entry duplicate is gone. `apps/web/lib/constants/indianStates.ts:33-70` carries all 37 live codes including 26, 30, 31, 34, 35, 38, with the docstring at `:1-27` recording why 25/28 (dead codes) and 96/97 are absent. The explicit override props are gone: `components/invoices/InvoiceEditor.tsx:943` and `components/customers/CustomerFormModal.tsx:197` both render `<StateLookup>` with no `states=` prop, so `StateLookup.tsx:23`'s canonical default applies.
PREMISE: the list half is FALSE today. The wrong-tax consequence is also closed independently — `routers/sales_invoices.py:813-818` now resolves the place of supply from four sources including `(customer.gstin)[:2]` and the client's own state (IGST §12(2)(b)(ii)), and `:1856-1864` refuses issue without a valid code.
RESIDUAL: 96/97 still unselectable — deliberately deferred to SALES-10/GST-07 by `indianStates.ts:21-26`, not an oversight. The finding's second suggested_fix half (default `customers.state_code` from `gstin[:2]` server-side) is NOT done — `models/parties.py:158` still takes it raw and `routers/customers.py:238-300` never derives it — but it no longer changes any tax outcome, since the invoice path derives its own.
SIZE: n/a (residual: hours, and low value).

## SALES-07 — VERDICT: open
EVIDENCE: the receipt form's POST body is `apps/web/app/clients/[id]/sales/page.tsx:3600-3624` — `client_id, customer_id, receipt_date, amount_paise, payment_mode, bank_account_id, reference_no, allocations, currency, exchange_rate` plus the three Table 11A fields; **no `tds_paise`**. `grep -n tds` over that file returns only the receipt LIST column (`:3207` selects `tds_paise`) and the type at `:90-92`. Backend is ready and unchanged: `models/invoices.py:546` `tds_paise: int = 0`, validator `:626-641` (`settlement = amount + tds`), `services/phase2_journal_service.py:212-247` posts Dr cash + Dr `%TDS Receivable%` / Cr AR, `services/receipt_service.py:534-535`.
PREMISE: TRUE, and still narrowed exactly as the verifier said — `apps/web/components/banking/SettleDocumentsModal.tsx:194` sends `tds_paise` through the bank-matching path, so a CA who settles from `/clients/[id]/bank → Entries` can capture it. Only the standalone receipt form cannot.
FIX: **SOUND.** Nothing refuses it; the model validator already treats settlement as `amount + tds` so the display change (`amount + tds − allocated`) is required for the screen to agree with the server. Note `page.tsx:3852` currently shows `amountPaise - totalAllocated`, which becomes wrong the moment a TDS field lands — the finding says this and it is still true.
SHAPE: `apps/web/app/clients/[id]/sales/page.tsx` only (field, `paiseFromRupeeInput`, the Unallocated line, and the settlement figure beside the cash amount). **No migration** — `receipts.tds_paise` is live. One blocker the finding omits: `services/receipt_service.py:88-89` refuses `tds_paise != 0` on a FOREIGN receipt (`"TDS on a foreign receipt is not supported yet."`) and `:211` hardcodes `"tds_paise": 0`, so the field must be hidden or disabled when `isForeign` or the save 422s.
SIZE: hours.

## SALES-08 — VERDICT: closed
EVIDENCE: `apps/api/domain/accounting/payment_account.py` is the single resolver, and its docstring at `:19` says "ACC-02, ACC-03 and SALES-08 are three readings of that one line." Order: explicit `bank_account_id` → `bank_accounts.coa_account_id` (`:113-131`), then cash mode → `%Cash in Hand%` (`:64-66`, `:140`), then the generic Bank ledger flagged `is_fallback` (`:70-80`). Both receipt paths call it: `services/phase2_journal_service.py:219-224` (with the old line quoted as the defect at `:214-218`) and `services/receipt_service.py:165-170` for the foreign path. Stored: `services/receipt_service.py:664` `"bank_account_id": data.get("bank_account_id")` with the note at `:660-663`. Sent: `apps/web/app/clients/[id]/sales/page.tsx:3610`.
PREMISE: FALSE today, including the verifier's extra (the firm-scoped `system_key='bank'` lookup is now only the named fallback, and it says so).

## SALES-09 — VERDICT: partial
EVIDENCE (closed half): `models/invoices.py:579-581` adds `gst_rate_bps`, `place_of_supply`, `is_interstate` to `ReceiptIn` with validators at `:584-617`; written at `services/receipt_service.py:672-674` (INR) and `:217-219` (foreign); the enabling flag is settable — `models/client.py:122 gst_advance_tax_applicable`, UI at `apps/web/components/ClientFormModal.tsx:180-181`; the form sends the three fields when the client is marked (`apps/web/app/clients/[id]/sales/page.tsx:3616-3623`); `services/gst_advance_service.py:126-186` now also NAMES undeclarable advances instead of `continue`-ing in silence. Guard test `apps/api/tests/test_an_advance_carries_what_table_11a_declares_it_at.py`.
EVIDENCE (open half): `services/gst_advance_service.py:255-263` — `advances_report` still returns `"table_11_computed": False` and `"why": "PracticeSync does not compute GSTR-1 Table 11..."`, which is now FALSE: `table_11_sections` computes it and `services/gst_return_service.py:1096` merges it into the filed payload.
PREMISE: TRUE when written; now true only of `advances_report`'s self-description.
FIX: the finding's own last sentence ("make `advances_report` report `table_11_computed: true` for those clients") is **SOUND** and is all that is left. Do not make it unconditional — it must read the client's flag, and it should carry the `undeclarable` list `table_11_sections` already builds, or the report and the return still disagree.
SHAPE: `apps/api/services/gst_advance_service.py` (`advances_report` reads `clients.gst_advance_tax_applicable` and the same gap list). **No migration.** Note the endpoint `GET /api/gst-workspace/gstr1/advances` (`routers/gst_workspace.py:1261`) is still called from nowhere in `apps/web` — fixing the payload without a screen changes nothing a CA sees.
SIZE: hours.
DUPLICATE: this residual is **GST-15**, first half, verbatim.

## SALES-10 — VERDICT: partial
EVIDENCE (closed): `migrations/349_an_export_records_its_shipping_bill.sql:56-58` adds `shipping_bill_no`, `shipping_bill_date`, `port_code`; `domain/gst/gstr1_builder.py:78-80` carries them on the dataclass and `:691-694` emits them (`inv.port_code or ""`, date converted by `_format_date_gstn`); `:301` and `:321` build Tables 6B and 6C inside the GSTN `b2b` section with the recipient GSTIN; `domain/gst/classifier.py:164-173` routes `SEZ_with_payment → SEZ_WP`, `SEZ_without_payment → SEZ_WOP`, `Deemed_export → DEEMED_EXPORT`, with the reasoning at `:146-160`; export WPAY/WOPAY is now decided by `igst_paise > 0` (`:181-184`). Editor captures all three: `apps/web/components/invoices/InvoiceEditor.tsx:211-215`, `:617-619`, `:1041-1047`.
EVIDENCE (open): `apps/api/domain/gst/amendments.py:140-141` — `elif section == "expa": node.update({"sbpcode": "", "sbnum": "", "sbdt": ""})`. Still three literals. Reachable: `domain/gst/amendment_proposal.py:192` → `services/gst_amendment_service.py:34`.
PREMISE: TRUE when written; now true only of the §37(3) amendment path.
FIX: the finding's fix is **SOUND** and largely applied. What remains is narrower than it scoped: `_build_node` never receives the corrected invoice's shipping-bill fields, so the plumbing is `amendment_proposal._build_node` passing them through, not a new builder.
SHAPE: `apps/api/domain/gst/amendments.py`, `apps/api/domain/gst/amendment_proposal.py`. **No migration** — columns are live. Blocker the finding does not mention: the amendment proposal's `finding` dicts are built from the exception report, not from `client_sales_invoices`, so the shipping-bill columns have to be threaded into `corrected` first.
SIZE: hours (residual only).
DUPLICATE: **GST-07** carries the SEZ/deemed-export half (now closed on both sides); SALES-10 carries the shipping-bill half.

## SALES-13 — VERDICT: partial
EVIDENCE (closed): `apps/api/services/invoice_pdf_service.py:899-926` `_load_branding` merges `firm_branding` + `invoice_settings`; wired at `:894` `build_invoice_pdf(..., branding=_load_branding(invoice.get("firm_id")))`; rendered at `:581` (accent colour), `:586-588` (logo), `:769-786` (Bank / IFSC / UPI / UPI QR), `:800-802` (footer text).
EVIDENCE (open): `:838-848` `build_sales_invoice_pdf` takes **no** branding argument, deliberately. Templates: `_VALID_TEMPLATE_TYPES` (`routers/branding.py:25`) has five values and the renderer reads none — `grep -n template apps/api/services/invoice_pdf_service.py` → no match. Email templates: `grep -rn email_template apps/api/services/` → no match, so `services/email_service.py` still hard-codes every body.
PREMISE: half FALSE now. The remaining half is deliberate for the sales invoice, and accidental for the templates.
FIX: **the finding's suggested_fix is UNSOUND for the sales-invoice half, and the code says so in words.** `invoice_pdf_service.py:842-847`: *"NO `branding` ARGUMENT, DELIBERATELY. firm_branding and invoice_settings are the PRACTICE's, and the practice's logo, bank account and UPI on this document would ask the client's customer to pay the accountant. It is the same confusion the supplier line, the customer statement and the payslip employer each had."* Doing what the finding says — "load `firm_branding` + `invoice_settings` in `get_sales_invoice_pdf`" — re-introduces SALES-01 in a new place: it would print the CA firm's UPI ID and bank account on the client's own outward invoice, and it would be a *payment-instruction* error, which is worse than the supplier-block error that was just fixed. The finding's other branch ("or take the Settings pages down") is also now wrong: the pages ARE read, on the fee-invoice path.
What is sound and open: (a) the five invoice templates are stored and unread; (b) the email templates are stored and unread; (c) a CLIENT-side branding store, which the docstring correctly calls "a migration, not a wiring job" — `clients` has no logo, bank, UPI or footer column.
SHAPE: (a)+(b) `apps/api/services/invoice_pdf_service.py`, `apps/api/services/email_service.py` — no migration. (c) a migration adding client branding/payment columns (or a `client_branding` table), plus `_SUPPLIER_COLUMNS` and `build_sales_invoice_pdf`, plus a settings screen scoped to the client rather than the firm. (c) is an owner decision, not a wiring job.
SIZE: (a)+(b) day. (c) multi-day.

## SALES-18 — VERDICT: partial
EVIDENCE (closed): the e-way half now has a Python authority and a parity fixture — `apps/web/lib/invoices/compliance.ts:62-66` records it (`"apps/api/domain/gst/eway.py, which is the authority. assessEway below is a FALLBACK ... pinned to that module by shared/eway-parity-vectors.json"`), `shared/eway-parity-vectors.json` exists, and `:218-220` prefers the server's `eway_assessment` with `??` reaching the mirror only on a redeploy skew. The two false alarms the verifier called are also settled in code: `:13-25` explains why the place-of-supply set and the GSTIN prefix set are different questions.
EVIDENCE (open): `apps/web/lib/invoices/compliance.ts:178-197` `irnEligibility` is still the only implementation of the Rule 48(4) B2B/export/SEZ scope test — `grep -rn "48(4)|irn_eligib" apps/api --include=*.py` returns only a docstring line at `routers/einvoice.py:3`. File is now 497 lines, up from 296.
PREMISE: TRUE for the IRN half only. The verifier's downgrade to `low` stands — `routers/einvoice.py` only records what a human generated on the IRP, so there is nothing server-side to bypass.
FIX: **SOUND**, and the repo has already chosen which of the two branches it prefers: the e-way half took "keep the mirror, pin it with a generated fixture", not "move it behind an endpoint". Follow that shape. The "collapse the third GSTIN regex" clause should be dropped — `compliance.ts:13-25` documents that merging the two browser sets would be wrong (96 is a place of supply and never a GSTIN prefix; 99 is the reverse).
SHAPE: a new `apps/api/domain/gst/irn_scope.py`, a `shared/irn-parity-vectors.json`, a Python test and a `node --test` reader — the pattern `shared/gst-parity-vectors.json` and `shared/eway-parity-vectors.json` already set. **No migration.** Blocker not mentioned: the firm turnover threshold that actually decides Rule 48(4) applicability is not held anywhere, so the Python twin can only carry the SCOPE test (B2B/export/SEZ), not eligibility — the same advisory the TS emits at `:196`.
SIZE: day.

## SALES-20 — VERDICT: open
EVIDENCE: DDL against the sales line table is only `migrations/050_sales_purchase_cycle.sql:58` (CREATE), `184:25` (service_catalogue_id) and `364_a_discount_recorded_in_the_invoice.sql:70,83,85,98,100` (discount) — no cess column, and none on the header. `grep -in cess apps/api/models/invoices.py` → no field. `services/gst_return_service.py:280-281` still states "None of the three line tables has a cess column" and hardcodes `cess_paise=0` at `:306`. `grep -in cess apps/api/services/coa_seed_service.py` → no match.
PREMISE: TRUE, unchanged.
FIX: **SOUND but incomplete.** Two things it does not mention. (1) There is **no Cess Output ledger in the seeded chart of accounts** — `coa_seed_service.py` has no cess entry — so "a Cess Output ledger" in `journal_for_sales_invoice` needs the seed extended and a backfill decision for existing clients, or `_find_account` returns nothing and the posting kernel's balance assertion is what the CA meets. (2) `shared/gst-parity-vectors.json` pins `lib/money/gstLine.ts` to the Python authority on exact strings; adding a cess head means regenerating those vectors, and CLAUDE.md's allowlisted `gstLine.ratePaiseFromRupees` exception means the cess RATE must go through `bpsFromPercentInput`, not a second `* 100`.
SHAPE: migration (line + header `cess_rate_bps` / `cess_paise`), `models/invoices.py`, `routers/sales_invoices.py::_compute_line_gst`, `services/phase2_journal_service.py`, `services/coa_seed_service.py`, `services/gst_return_service.py:280-306`, `apps/web/lib/money/gstLine.ts`, `shared/gst-parity-vectors.json`, `InvoiceEditor.tsx`. The GSTR-1 builder already reads `line.cess_paise` (`gstr1_builder.py:634-636`), so nothing there changes. `tests/test_frontend_columns_exist_pg.py` is additive-safe.
SIZE: multi-day.
DUPLICATE: **PUR-20** carries the inward/ITC half of the same absence; SALES-20 carries the outward/GSTR-1 `csamt` half. They share the migration and the ledger seed but not the computation.

## SALES-21 — VERDICT: open
EVIDENCE: `grep -rniE '\b(quotation|proforma|pro forma|delivery challan|delivery note|sales order)\b' apps/api/migrations/*.sql` → zero rows. `apps/web/app/clients/[id]/sales/page.tsx:68-76` — TABS still start at "Sales Invoices".
PREMISE: TRUE, unchanged.
FIX: **SOUND**, and the sequencing (delivery challan first, Rule 55) is right because it is the only one of the four that is a statutory document.
SHAPE: new tables + migration; a `NUMBER_SERIES` entry in `apps/api/services/numbering.py:57-70` with a matching UNIQUE constraint (`next_sequence` at `:125-128` REFUSES a scope that does not match the constraint exactly — a new series that skips this is rejected at runtime, which is the guard working); a router; a Sales tab. Blocker the finding does not mention: `apps/web/components/invoices/CompliancePanel.tsx` posts `invoice_number` on the e-way record, so a Rule 55 challan feeding an e-way bill needs that path widened, not just a new table.
SIZE: multi-day.

## SALES-22 — VERDICT: open
EVIDENCE: `apps/api/routers/firm_hsn_library.py:1-15` and `routers/hsn.py:3-11` still state the shared master is not exposed; `models/invoices.py` still carries the hard 422 on `service_catalogue_id`.
PREMISE: TRUE, unchanged, including both of the verifier's softeners (HSN itself optional; `POST /bulk` and the onboarding step-3 CSV import exist).
FIX: **NOT SOUND AS AN ENGINEERING TASK — it reverses a written owner decision, and the finding does not say so.** `docs/FIRM_HSN_LIBRARY.md:10-45` records "Decision A": *"Caflow does not expose a shared HSN/SAC master to users ... This redesign accepts those costs as a deliberate, informed trade-off ... in exchange for a cleaner liability posture: Caflow asserts no classification content of any kind, anywhere a user can see it."* `apps/web/app/onboarding/page.tsx:111-124` repeats the reasoning and is explicit that even the CSV template carries Caflow-authored column headers only, "so there is nothing here to redistribute or license". Loading the CBIC leaf catalogue and offering "add from master" is exactly the content assertion that decision refuses. The finding's own premise that both are "Government of India publications in the public domain" is the point in dispute, and it cites migration 175 for it — a code comment, not counsel. This needs an owner reversal first; the code change is downstream and easy.
SHAPE: data sourcing + a decision; then `hsn_master` load, `routers/hsn.py` merge, `firm_hsn_library` "add from master". **Migration** only for the data load.
SIZE: multi-day, and gated on a non-engineering decision.
DUPLICATE: **GST-26**, same defect, same evidence. GST-26 is the shorter statement; SALES-22 carries the ca_experience and the seeding proposal.

## SALES-23 — VERDICT: open
EVIDENCE: `apps/api/services/collections_service.py:297-304` still records the removal of `run_due_reminders` verbatim; `REMINDER_DEFAULTS = {"attach_pdf": True}` at `:305`. `send_overdue_reminders` (`:247`) is still the practice's internal fee sweep, called from `jobs/scheduler.py:215` and `routers/billing.py:174`. The only customer-facing path remains one-at-a-time: `apps/web/app/clients/[id]/sales/page.tsx:1683-1688` → `POST /api/sales-invoices/{id}/remind`, behind a single-row modal at `:1852-1856`. No bulk Remind over the DataTable selection.
PREMISE: TRUE, unchanged.
FIX: **SOUND**, and the pattern it names is real — `_paginate_all` exists, and the bank "Pass N ready" chunk-and-resume loop is at `jobs/bank_trusted_rules_job`. One thing the finding does not weigh: the removal was made because an unbounded loop starved every job scheduled after it in the nightly sweep, so a rebuilt cadence has to be per-firm chunked with a cursor AND bounded by wall clock, not only by row cap.
SHAPE: `apps/api/services/collections_service.py`, `apps/api/jobs/scheduler.py`, a `reminder_settings` widening (the columns `enabled`/`interval_days`/`max_reminders` still exist on the table — `:298` says they governed the removed run — so **no migration** is needed to bring them back). Interim bulk Remind is `apps/web/app/clients/[id]/sales/page.tsx` alone.
SIZE: day (bulk Remind: hours; the cadence: day).

## SALES-25b (customer credit limit) — VERDICT: open
EVIDENCE: `grep -rn credit_limit apps/api --include=*.sql` returns only `migrations/030_supplier_tds_and_credit.sql:11,25` — suppliers. `customers` has `credit_days` and no `credit_limit_paise`. Nothing in `_create_invoice_core` (`routers/sales_invoices.py`) checks exposure.
PREMISE: TRUE for (b). (a) is closed — `domain/gst/credit_note_window.py` now warns, per HEAD.
FIX: **SOUND.** "Warning by default, block only when the firm turns it on" is the right shape and matches how the §34(2) window was just built (warn, because the document is lawful even when the tax relief is not). One thing to get right that the finding does not say: the live exposure figure must come from `client_sales_invoices.outstanding_paise` (the generated column, migration 278) plus unallocated receipts, not from a Python loop over invoices — CLAUDE.md's reporting rule applies to any check that scans the ledger.
SHAPE: migration adding `customers.credit_limit_paise BIGINT DEFAULT 0` (mirror migration 030's shape) and a firm-level enforce flag; `models/parties.py::CustomerIn`; `routers/sales_invoices.py::_create_invoice_core`; `apps/web/components/customers/CustomerFormModal.tsx`. Blocker: the customers grid is read directly over PostgREST from `apps/web/app/clients/[id]/sales/page.tsx`, so `tests/test_frontend_columns_exist_pg.py` must see the new column before any select list adds it.
SIZE: day.

## SALES-30 — VERDICT: open, and now WORSE than the finding says
EVIDENCE: `apps/api/routers/credit_notes.py:274-286` — the create-path lookup is
```
db.table("client_sales_invoices")
  .select("is_interstate, invoice_date")
  .eq("id", data["sales_invoice_id"])
  .eq("firm_id", firm_id)
  .limit(1)
```
— `client_id` is still absent, while the issue path filters it (`:628`, `:654`, `:670`, `:688` all carry `.eq("client_id", client_id)`).
PREMISE: TRUE, and the blast radius has GROWN since the finding was written. The same select now also fetches `invoice_date`, and `:277-279` says why: §34(2)'s window is measured from the original supply's financial year. So a cross-client link no longer only mis-sets `is_interstate` (which fails safe at issue) — it computes the **§34(2) window from another client's invoice date**, and that answer is a WARNING, not a refusal (`domain/gst/credit_note_window.py`), so nothing downstream catches it.
FIX: **SOUND** and unchanged — add `.eq("client_id", client_id)` and 422 on a miss, matching the issue path. Add the same 422 rather than silently leaving `original_invoice = None`, because a missed link now silently drops the §34(2) check too.
SHAPE: `apps/api/routers/credit_notes.py` only. **No migration.** Check `routers/sales_debit_notes.py` for the same shape while there.
SIZE: hours.

## SALES-31 — VERDICT: open
EVIDENCE: `apps/api/models/invoices.py:206` `place_of_supply: Optional[str] = None  # 2-digit state code` on `SalesInvoiceIn` (class opens at `:179`), with no validator — unlike `ReceiptIn.place_of_supply` (`:580`), which got one at `:603-617`. It is read only on the mock branch: `routers/sales_invoices.py:707-709`. The real branch (`:813-818`) resolves `supply_state_code → customer.state_code → customer.gstin[:2] → client_state_code` and never looks at it.
PREMISE: TRUE, unchanged. The divergence between the two branches is now WIDER than when the finding was written, because the real branch grew two more sources the mock branch does not have.
FIX: **SOUND with a caveat the finding does not carry.** "Delete the field" is now the riskier of the two options — the mock branch reads it at `:708` and the mock suite is ~7,000 tests, so deleting it changes mock-mode behaviour. "Fold it in" is the safer branch, and the priority is now settled by `:800-812`'s own ordering: `supply_state_code or place_of_supply` at position 1 (they are the same statutory fact under two names), then the existing three. While there, give it the validator `ReceiptIn.place_of_supply` already has — refusing a non-state-code at the model boundary is strictly better than the issue-time 422 at `:1857`.
SHAPE: `apps/api/models/invoices.py`, `apps/api/routers/sales_invoices.py` (both branches). **No migration.**
SIZE: hours.

## SALES-32 — VERDICT: open
EVIDENCE: `apps/api/domain/tds/section_rates.py:308` — `# TCS on sale of goods, Section 206C(1H) — unchanged, 0.1%.` still stands, with the honest "NOT wired to any computation" note at `:309-314` and the entry at `:315`. `_SECTIONS_2025_26` is still shared by FY 2026-27 (`:322`).
PREMISE: TRUE, unchanged. And the correcting source is already in the repo: `docs/audits/2026-09-07-market-research/income-tax-tds-primary.md:566` — *"§206C(1H) TCS on sale of goods ceased to operate from 01-04-2025"*, graded `[S+]`, with `:575` noting the Finance (No. 2) Act 2024 inserted a proviso making it inapplicable rather than omitting it.
FIX: **SOUND**, and it is the cheapest item in the slice. "Leave TCS unbuilt" is right and matches the module's own position. Correct the comment to state the 01-04-2025 cessation and cite the market-research file, and keep the rate row (it is reference data for a pre-2025 period). Do NOT delete the `"206C"` entry — `resolve_tds` reads the section table by key and a historical FY still needs it.
SHAPE: one comment block in `apps/api/domain/tds/section_rates.py`. **No migration, no behaviour change.**
SIZE: hours.
DUPLICATE: **TDS-10** ("TCS does not exist — only a rate row nobody reads") carries the feature half (27EQ, 27D, collection tracking); SALES-32 carries only the stale comment and is the half worth doing now.

---

# 1. Duplicates with other subsystems

| Pair | Which half each carries |
|---|---|
| **SALES-08 ≡ ACC-02 ≡ ACC-03** | Named as one defect by the fix itself (`domain/accounting/payment_account.py:19`). SALES-08 = the receipt path; ACC-02 = cash never reaching Cash in Hand; ACC-03 = the generic firm-wide Bank ledger vs the bank-statement path. **All three closed by 8e34ad60.** |
| **SALES-09 (residual) ≡ GST-15** | Identical: `advances_report` says Table 11 is not computed while `table_11_sections` computes it into the filed payload. GST-15 additionally carries "GSTR-3B never carries the same liability", which is outside this slice. |
| **SALES-10 ≡ GST-07** | GST-07 = SEZ/deemed-export folded into 6A + WPAY/WOPAY misdetection (both now closed). SALES-10 = the shipping-bill fields (closed on the main build, **open on the `expa` amendment path**). |
| **SALES-20 ≡ PUR-20** | SALES-20 = outward cess, GSTR-1 `csamt`. PUR-20 = inward cess, the lost ITC. One migration and one seeded ledger serve both; the computations are separate. |
| **SALES-22 ≡ GST-26** | Same defect, same evidence. GST-26 is the bare statement; SALES-22 adds the ca_experience and the seeding proposal (and is the one whose fix collides with Decision A). |
| **SALES-32 ≡ TDS-10** | SALES-32 = the stale `"unchanged, 0.1%"` comment (hours). TDS-10 = building TCS (27EQ/27D/collection tracking). Only SALES-32 is actionable now. |

# 2. Defects with no finding

**(a) The inter- vs intra-state split for a GSTR-1 Table 11A advance is decided in the browser and stored verbatim.**
`apps/web/app/clients/[id]/sales/page.tsx:3623` — `is_interstate: advancePos !== clientStateCode` — with `clientStateCode` read straight off `clients.state_code` at `:3456-3464`. The backend never re-derives it: `models/invoices.py:581` accepts `is_interstate: Optional[bool]` with no validator tying it to `place_of_supply`, and `services/receipt_service.py:674` (INR) and `:219` (foreign) store `data.get("is_interstate")` as given. Two consequences. It is a statutory rule (IGST Act §§7, 8) living in the frontend, against CLAUDE.md's "zero business logic in the frontend" — and this is the same class the receipt-form comment at `:3617-3620` congratulates itself for avoiding ("DERIVED ... rather than asked as a third question"), except it is derived on the wrong side of the wire. Worse, `clients.state_code` is nullable (`migrations/001_initial_schema.sql:36`) and nothing requires it, so for a client with no state code recorded, `advancePos !== ""` is always true and **every advance is declared INTER-state**, putting IGST in Table 11A where CGST+SGST is due. The invoice path already solved exactly this — `routers/sales_invoices.py:824` derives `is_interstate` server-side from `client_state_code` vs the effective place of supply — so the fix is to do the same in `create_receipt_core` and ignore the request field.

**(b) Server-side request forgery through firm branding URLs.**
`apps/api/services/invoice_pdf_service.py:294-322` `_remote_image` fetches any `http(s)` URL server-side with `follow_redirects=True`, called for the logo (`:326`) and the UPI QR (`:786`) on every fee-invoice PDF render. The URLs are free-form strings: `routers/branding.py:33-34` (`logo_url`, `secondary_logo_url`) and `:54` (`upi_qr_url`) are `Optional[str]` on `BrandingUpdate` / the invoice-settings model, and `PUT /api/settings/branding` (`:124-140`) validates the colours and the font family and **nothing else** — no scheme allowlist beyond `http(s)`, no host allowlist, no check that the URL is in the Supabase storage bucket the upload endpoint (`:143-180`) writes to. A Partner can therefore point the API in Singapore at `169.254.169.254`, `localhost`, or any internal Render address and have it issue the request on PDF render. It is blind (the body is decoded as an image and every failure returns `None` silently, per the docstring at `:295-299`), so it is a probe primitive rather than an exfiltration path, and the 3-second timeout and 2 MB cap bound it — but the missing control is a host allowlist at the write boundary, which costs a few lines. Worth noting the module's own `_accent_colour` docstring (`:266-272`) explains that it re-validates on the way out "rather than trusting a row written before that validation" — the same instinct, not applied to the URL.

# 3. Stale rate for the slice

Against the 18 findings this session inherited as open or partial (32 total minus the 14 the brief declared handled):

- **6 fully closed** on probe — SALES-01, 02, 03, 04, 06, 08 → **33% fully stale**
- **4 materially advanced to partial** — SALES-09, 10, 13, 18 (one half of each closed) → **56% at least partly stale**
- **8 unchanged and open** — SALES-07, 20, 21, 22, 23, 25b, 30, 31, 32 (9 items counting 25b separately)

Across all 32 findings in the file: **19 closed, 5 partial, 8 open.**

Two of the eight remaining suggested fixes should not be executed as written: **SALES-13** (its sales-invoice branch would print the CA practice's UPI and bank account on the client's outward invoice, re-creating SALES-01 as a payment-instruction error — the code refuses it in words at `invoice_pdf_service.py:842-847`) and **SALES-22** (it reverses the written liability-posture decision at `docs/FIRM_HSN_LIBRARY.md:10-45`, which the finding does not acknowledge). The two cheapest real closures are **SALES-32** (one comment, the correcting source already in-repo) and **SALES-30** (one `.eq`, and its blast radius has grown since the §34(2) window started reading through the same unscoped lookup).
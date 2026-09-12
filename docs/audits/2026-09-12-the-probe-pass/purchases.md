Probe complete. Findings below, in the order requested.

---

**PUR-12 — VERDICT: closed**
EVIDENCE: The file the finding cites no longer exists. `/home/user/caflow-ai/apps/web/app/gst/reconciliation/page.tsx` was deleted in commit `0544e486`. The surviving GST screen states the current law: `/home/user/caflow-ai/apps/web/app/gst/gstr3b/page.tsx:7` — `" * CGST Rule 36(4) — ITC restricted to 100% of the eligible GSTR-2B credit. The"` / `:8` — `" *   105% provisional buffer was withdrawn by Notification 40/2021-Central Tax"`. A regression guard exists: `/home/user/caflow-ai/apps/web/scripts/the-gst-challan-figure-is-on-the-screen.test.ts:87` — `test("no GST screen states the withdrawn Rule 36(4) buffer", () => {`, which greps every screen for 120/110/105.
PREMISE: FALSE now — all four strings and the file holding them are gone, and the guard test names this exact finding in its comment at `:92`.
SHAPE: nothing.
SIZE: 0.

---

**PUR-16 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/web/app/accounting/suppliers/page.tsx:151` — `const { data, error: fetchErr } = await sb.from("suppliers").select("*").eq("firm_id", firmId).eq("client_id", selectedClientId).order("supplier_name");`. Nav-linked at `/home/user/caflow-ai/apps/web/app/accounting/page.tsx:16` — `{ label: "Supplier Master", description: "Manage supplier TDS sections, credit limits and payment terms", href: "/accounting/suppliers", icon: Users }`. Backend readers of `suppliers`: zero — only three test allowlists (`test_direct_write_tables_are_role_guarded.py:48`, `test_sql_role_tiers_match_python.py:60`, `test_role_write_policies_pg.py:311`).
PREMISE: sound.
SHAPE: delete `apps/web/app/accounting/suppliers/page.tsx`, the nav entry at `apps/web/app/accounting/page.tsx:16`, and regenerate `apps/web/lib/workspace/knownRoutes.generated.ts:23`. One thing to note that lowers cost: the page is an allowlisted entry in `apps/web/scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts:54` (`RATE_HOLDERS`), but that map is used only as a skip-list (`if (rel in RATE_HOLDERS) continue;` at `:76`), so a stale key does not fail — deleting the page is safe, cleaning the key is cosmetic. Dropping the `suppliers` and `msme_vendors` tables needs a migration plus removal from those three allowlists; `msme_vendors` has an assignment-scope policy in production and still zero readers (migration `303_schedule_iii_ageing_schedule.sql:96` explicitly says the Schedule III ageing does *not* build on it). Backfill only if prod rows exist — not determinable from the repo.
SIZE: day.

---

**PUR-18 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/gst/gstr3b_computer.py:316` — `("IMPG", 0, 0, 0, 0),` and `:317` — `("IMPS", 0, 0, 0, 0),`, with the docstring at `:302` still conceding `"IMPG, IMPS and ISD are zero because nothing upstream distinguishes an"`.
PREMISE: sound on the substance, but **one assertion is stale**. The finding says a grep for "bill of entry" finds "nothing but a comment in migration 309". That is no longer true: the GSTR-2B parser now models a BoE end-to-end — `/home/user/caflow-ai/apps/api/domain/gst/gstr2b.py:88` — `document_type: str              # invoice / credit_note / debit_note / bill_of_entry`, with `impg`/`impgsez` in `SECTIONS` at `:60` and a test at `tests/test_the_2b_reconciliation_reads_the_books.py:134` asserting `d.document_type == "bill_of_entry"`. So the *inbound* (2B) half exists; what is missing is the **books** half (no import flag or BoE document on `purchase_bills`) and the 3B wiring between them.
SHAPE: migration (an `is_import`/BoE table), `routers/purchase_bills.py` compute, `services/gst_return_service.py` around `:724`, `domain/gst/gstr3b_computer.py:284-320`, plus a screen. **Invariant the fix must not break**: the docstring at `gstr3b_computer.py:308-312` says ISRC is capped so the five rows sum to exactly 4(A) — moving credit into IMPG must *subtract* it from OTH, or the filed 4(A) double-counts and will not reconcile with its own 4(C).
SIZE: multi-day.
DUPLICATE: **GST-24** ("Table 4(A) rows for import IGST and ISD are permanently zero") is the same defect at the same lines, from the GST side. PUR-18 adds the BoE document; GST-24 adds ISD. One fix, two entries.

---

**PUR-19 — VERDICT: open**
EVIDENCE: No self-invoice or payment voucher document exists — grep across `apps/api`/`apps/web` returns only prose in docstrings and tests. Table 13 still counts three of twelve: `/home/user/caflow-ai/apps/api/domain/gst/gstr1_builder.py:827` — `counts: dict[str, int] = {` followed by only `"Invoices for outward supply"`, `"Credit Note"`, `"Debit Note"`, while `_DOC_NATURES` at `:801-816` lists all twelve including `"Payment Voucher",  # 7`.
PREMISE: sound.
SHAPE: a numbering series (`services/numbering.py`'s `NUMBER_SERIES` registry plus a UNIQUE constraint → migration), a document row or a derived print, and `_build_doc_summary`. **Invariant**: Table 13's `doc_num` is the fixed 1-based position in `_DOC_NATURES` (`:845` — `"doc_num": _DOC_NATURES.index(doc_type) + 1`), not a running count — the current code got that right after getting it wrong once, so anything added must index the tuple, never enumerate.
SIZE: multi-day.

---

**PUR-20 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/gst_return_service.py:724` — `cess_paise=int(b.get("cess_paise") or 0),` reads a column that does not exist. Production schema fixture for `purchase_bills` carries `ineligible_itc_cess_paise` and `tds_cess_paise` and no `cess_paise`. `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:125` — `def _compute_line_gst(taxable_paise, gst_rate_bps, is_interstate) -> tuple[int, int, int]:` — three heads only.
PREMISE: sound.
SHAPE: migration on both `purchase_bills` and `purchase_bill_lines`; `_compute_line_gst` becomes a 4-tuple (it has an exact twin at `routers/sales_invoices.py`); header totals, `net_payable_paise`, the receive journal (needs a cess ledger head in `phase2_journal_service`), and the editor. **Invariant**: the receive journal must still foot — `apps/api/tests/test_accounting_audit_fixes.py:71` asserts `tb["total_debit_paise"] == tb["total_credit_paise"]`. Adding cess to the payable without a matching Dr GST Input (cess) leg breaks the trial balance, and the finding's suggested fix does not mention the journal leg.
SIZE: multi-day.
DUPLICATE: **SALES-20** ("No GST compensation cess on a sales line") is the same absence on the outward side, in the mirror files. PUR-20's own verification already flags this. Doing one without the other leaves 3B's cess line half-built.

---

**PUR-21 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/document_intelligence_v1.py:229-236` — the loop coerces `taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise` to int and returns; nothing checks they sum. `_estimate_confidence` at `:275` is still field-presence only. Frontend: `/home/user/caflow-ai/apps/web/components/purchases/PurchaseBillEditor.tsx:474` — `if (ex.line_items?.length) {` builds every editor line from `ex.line_items` alone.
PREMISE: sound, with one correction that makes the fix *cheaper* than described. The finding says the editor "discards the extracted `total_paise`/`taxable_amount_paise` entirely". It does not discard them — they are held in component state at `PurchaseBillEditor.tsx:460` (`setAiExtracted(ex as unknown as Record<string, unknown>)`) and simply never rendered; the only thing drawn from `aiExtracted` is the sentence at `:713` (`✓ AI extracted data pre-filled below. Review before saving.`). The comparison figure is already in the component.
SHAPE: `apps/api/routers/document_intelligence_v1.py` (`_parse_extraction_json` plus the response shape at `:128`) and `apps/web/components/purchases/PurchaseBillEditor.tsx`. No migration.
**Warning on the suggested fix**: "block the save when they differ" is wrong as a hard refusal. The model reads a rounded rupee total; the editor recomputes CGST/SGST from paise per line with `sgst` carrying the odd paise (`purchase_bills.py:141-147`). A one- or two-paise difference is the *correct* behaviour, and a refusal would stop a CA saving a right bill. Warn with a tolerance, do not refuse.
SIZE: day.

---

**PUR-22 — VERDICT: open**
EVIDENCE: The engine and the re-allocation route both exist and no screen reaches either — `/home/user/caflow-ai/apps/api/routers/purchase_payments.py:564` — `@router.patch("/{payment_id}/allocate")`; the only frontend calls are `POST /api/purchase-payments` (`apps/web/app/clients/[id]/purchases/page.tsx:2290`, `apps/web/components/purchases/PurchaseBillViewDrawer.tsx:466`) and `.../reverse`. The form is still single-bill: `apps/web/app/clients/[id]/purchases/page.tsx:2165` — `const [billId, setBillId] = useState("");` and `:2299` — `purchase_bill_id: billId || undefined,`.
PREMISE: mostly sound, but **"The backend is done" is not true for the create path**. `PurchasePaymentIn` has no `allocations` field (`/home/user/caflow-ai/apps/api/models/invoices.py:642-659`), and `create_purchase_payment` never calls `create_payment_core` — it runs its own single-bill claim and then `/home/user/caflow-ai/apps/api/routers/purchase_payments.py:447` — `unallocated_paise = 0 if purchase_bill_id else amount_paise`.
That line is the trap. Building the UI as "create, then PATCH /allocate" is **not** equivalent to creating an allocated payment: with no `purchase_bill_id`, the whole amount is an advance, which fires the §194 advance-withholding branch at `:450-456` (`vendor_tds.columns_for_advance(...)`) and deducts tax on the full payment. A later allocation does not undo that, so a one-NEFT-many-bills settlement would withhold twice — once at bill receipt and again on the "advance". The honest fix is to add `allocations` to `PurchasePaymentIn` and route create through `create_payment_core`.
SHAPE: `apps/api/models/invoices.py`, `apps/api/routers/purchase_payments.py`, `apps/web/app/clients/[id]/purchases/page.tsx`, `apps/web/components/purchases/PurchaseBillViewDrawer.tsx`. No migration — `purchase_payment_allocations` exists (migration 226).
SIZE: multi-day (day only if you take the create-then-allocate shortcut, which is the wrong one).
DUPLICATE: **SALES-14** is the exact AR mirror — `PUT /api/receipts/{id}/allocations` exists, correct, and called by no screen. Same shape, same two-sided fix.

---

**PUR-23 — VERDICT: open**
EVIDENCE: only two callers, both in the bill router — `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:1651` — `_tds_sync = _sync_tds_register(db, current_user.get("firm_id", ""), updated_bill)` (receive) and `:1804` — `_sync_tds_register(db, firm_id or "", {**bill, "id": bill_id, "status": "cancelled"})` (cancel). `routers/debit_notes.py` and `routers/purchase_credit_notes.py` contain **zero** occurrences of `tds` or `sync_for_bill`.
PREMISE: sound (line numbers have drifted from the finding's 1587/1740 to 1651/1804; the self-contradiction in `services/tds_register_service.py:21` — *"sync_for_bill() is called on every transition"* — still stands).
SHAPE: this is an **ACC-08-shaped** finding, not a one-line call. `sync_for_bill` takes a bill dict and writes `payment_amount_paise` from the bill's taxable amount; there is no "post-note taxable amount" anywhere — you would derive it from `debited_paise`/`credit_note_paise`, a figure the register has never held. And the 26Q builder reads `purchase_bills` only (`services/tds_return_service.py::_posted_vendor_tds_bills`), so unless the return uses the *same* derived figure, fixing the register makes the register and 26Q disagree instead of the register and the bill. The finding correctly names the live statutory question (adjust the tax, or only the reported gross) — that is an owner decision, not engineering.
SIZE: day for the mechanics, blocked on a decision.
DUPLICATE: **TDS-32** ("Purchase debit and credit notes never reverse TDS, so a return after deduction leaves the register and the 26Q overstated") is the same defect. TDS-32 carries the 26Q half and cites the codebase's own admission at `services/tds_return_service.py:33-37`. Treat as one item — fixing PUR-23 alone leaves TDS-32's return half broken, and vice versa.

---

**PUR-24 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/vendor_statement_service.py:293-300` — the only source is `db.table("purchase_bills")... .gt("outstanding_paise", 0)`; `purchase_payments.unallocated_paise` appears nowhere in `ap_aging`, and no advance/negative row is emitted (the returned dict at `:345` is `{"as_of", "buckets", "total_outstanding_paise", "bills"}`).
PREMISE: sound. One addition to its own verification's correction: sourcing advances from `unallocated_paise` **in cash terms will still not tie** for a foreign payment. `build_statement` deliberately uses `ap_relief_paise` rather than `amount_paise` (`vendor_statement_service.py:110-121`) because a foreign payment relieves AP at the bill's *booked* rate while cash moves at the payment rate, with the delta to Realized FX. An advances section built on raw `unallocated_paise` reconciles the INR case and quietly misses the foreign one — which is exactly the class of thing this finding is about.
SHAPE: `apps/api/services/vendor_statement_service.py` plus whatever renders `ap_aging`. No migration (`unallocated_paise` exists, migration 226).
SIZE: day.

---

**PUR-25 — VERDICT: open**
EVIDENCE: a grep for `purchase_order`, `purchase order`, `goods receipt`, `grn` and `three-way match` across all of `apps/api` and `apps/web` returns **nothing** — not one hit. Stock nonetheless moves at bill receipt: `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:1684` — `from domain.inventory_service import apply_purchase_to_inventory`.
PREMISE: sound. This is an absent module, not a defect. The finding's own caveat is the correct verdict: an owner scope call, not a build.
SHAPE: new tables (migration), router, service, screens, a PO→bill conversion and a quantity-variance flag against the existing inventory path.
SIZE: multi-day (realistically weeks).

---

**PUR-26 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/migrations/107_*.sql:13` — `CREATE TABLE IF NOT EXISTS public.recurring_invoice_templates (`; `routers/recurring_invoices.py` contains no occurrence of `purchase`. The mitigations its verification names are real: `/home/user/caflow-ai/apps/web/components/purchases/PurchaseBillEditor.tsx:187` — `duplicateSeed?: PurchaseBillDetail | null;` and `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:942` — `@router.post("/bulk")`.
PREMISE: sound as amended by its own verification — "keyed by hand every month" overstates it, Duplicate exists.
SHAPE: mirror migration 107's three tables + service + router + a hook in `task_recurring.py` + a screen. Migration: yes. The design question the finding does not raise: a recurring *purchase* bill has no supplier invoice number until the invoice arrives, and the duplicate index (`migration 313`, keyed on `lower(btrim(bill_no))`) excludes only blank numbers — so generated drafts must leave `bill_no` blank, not carry a `DRAFT-<hex>` placeholder the way the sales generator does, or two generated drafts become two distinct "numbered" bills that the guard will never catch as one.
SIZE: multi-day.

---

**PUR-27 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:687` — `required = ["client_id", "vendor_id", "bill_date", "lines"]`, backed by `migrations/050_sales_purchase_cycle.sql:233` — `vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,`. No expenses router, table or nav entry exists.
PREMISE: sound, as amended by its verification (the bank-line coding path covers a paid-from-bank expense; what is absent is receipt capture, a per-employee claim and an approval trail).
SHAPE: a new document type is a new **posting path**, and this repo holds posting paths to a standard: it must stamp `source_type`/`source_id` (the ACC-22 lesson), call `period_lock_service`, and be enumerated by name in `apps/api/tests/test_every_dated_posting_path_asserts_the_client_lock.py`. That is the real cost, not the CRUD. Migration: yes.
SIZE: multi-day.

---

**PUR-28 — VERDICT: partial**
EVIDENCE: the production policy fixture (`apps/api/tests/fixtures/production_guards_2026-09-03.json`, `policy` key) records `purchase_bills.purchase_bills_assignment_scope`, `purchase_payments.purchase_payments_assignment_scope`, `vendors.vendors_assignment_scope` and `service_catalogue.service_catalogue_assignment_scope` as **present**. It records for the other two only `debit_notes.firm_debit_notes` and `purchase_credit_notes.firm_purchase_credit_notes` — no assignment-scope policy on either.
PREMISE: **FALSE as titled.** "enforced on ... none of the Purchases page's direct PostgREST reads" is wrong for four of the six tables. The mechanism is `/home/user/caflow-ai/apps/api/migrations/084_assignment_scoped_rls.sql:75-95`, a one-shot `DO` loop over `information_schema.columns WHERE column_name = 'client_id'` — it caught everything that existed in 2024; `debit_notes` (migration 145) and `purchase_credit_notes` (migration 210) were created afterwards and were never picked up. A fix built on the stated premise would add four policies that already exist and might well `DROP POLICY IF EXISTS` the live ones on the way.
The real hole is exactly two tables, read at `/home/user/caflow-ai/apps/web/app/clients/[id]/purchases/page.tsx:2600` — `.from("debit_notes")` and `:3041` — `.from("purchase_credit_notes")`.
SHAPE: one migration, two RESTRICTIVE policies, no application code. Worth pairing with the durable fix the finding misses: 084's loop never re-runs, so every future `client_id` table repeats this. No test enumerates `client_id` tables against assignment-scope coverage — the fixture tests assert the *recorded* set, not completeness.
SIZE: hours for the two policies; day with the completeness guard.

---

**PUR-17 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:1918` — `"tds_paise":            0,  # TDS requires CA review before application`, inside a `bill_draft` built by hand at `:1902-1923`; `:1859` — `vendor_id = None` is still what a failed match leaves, against `migrations/050:233`'s `NOT NULL` (production schema fixture records `vendor_id` `"nullable": "NO"`). Lines are still inserted with all three GST heads hard-zero while the header carries the extracted tax. No `_compute_bill_lines_and_totals`, no `is_interstate`, no `total_gst_paise`, no `itc_eligible`, no `period_validation_service`. Still zero frontend callers.
PREMISE: sound — with one thing changed since the finding was written: a duplicate guard was retrofitted onto this path (`purchase_bills.py:1933` — `_dup = _duplicate_bill_id(db, bill_draft.get("client_id"), ...)`), so it is no longer entirely un-hardened. That does not narrow the divergence, but it does mean somebody has touched this endpoint since, and deleting it should be checked against whatever prompted that.
SHAPE: delete ~165 lines from `apps/api/routers/purchase_bills.py`, or replace the body with a vendor match plus `_create_purchase_bill_core` and a 422 on no match. Deleting is the honest fix. No migration.
SIZE: hours.

---

**PUR-29 — VERDICT: closed**
EVIDENCE: `/home/user/caflow-ai/apps/api/tests/test_accounting_audit_fixes.py:55` — `def test_rcm_bill_vendor_payable_excludes_self_assessed_gst(monkeypatch):`, driving `pb.create_purchase_bill(_bill_in(rcm=True), CALLER)` and asserting at `:61` — `assert bill["total_paise"] == 10_000_000          # NOT 11,800,000`. The journal half is `:66` — `def test_rcm_receive_posts_output_liability_and_balances(monkeypatch):`, asserting at `:72` — `assert tb["total_debit_paise"] == tb["total_credit_paise"] == 11_800_000`. The §17(5) half is `/home/user/caflow-ai/apps/api/tests/test_r239_gst_computation_gaps.py:177` — `def test_create_purchase_bill_computes_ineligible_itc_totals(monkeypatch):`, asserting `bill["ineligible_itc_cgst_paise"] == 4_50000`.
PREMISE: **FALSE**. All three assertions the finding's own `suggested_fix` asks for already exist, and both tests drive `create_purchase_bill` — the compute path itself, not a GST-side stub. The finding searched for purchase tests **by filename** and concluded from their absence that the branches were untested.
SHAPE: nothing.
SIZE: 0.

---

**PUR-30 — VERDICT: closed**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:30` — `# _TDS_DEFAULT_BPS WAS HERE AND IS DELETED. It mapped six sections to flat`. A repo-wide grep for `_TDS_DEFAULT_BPS` across `apps` and `scripts` returns only that comment. The live rate is `/home/user/caflow-ai/apps/api/domain/tds/section_rates.py:228` — `"194H":  TDSSectionRule(20_000_00, 200, 200, aggregate_threshold_paise=20_000_00),`.
PREMISE: was sound; now moot.
SIZE: 0.

---

**PUR-31 — VERDICT: closed**
EVIDENCE: both copies now delegate. `/home/user/caflow-ai/apps/api/routers/purchase_payments.py:217` — `return next_sequence(db, "purchase_payments", f"VPMT-{fy}-", firm_id=firm_id)`, identical at `/home/user/caflow-ai/apps/api/services/purchase_payment_service.py:43`. And `/home/user/caflow-ai/apps/api/services/numbering.py:102` — `"""Read back the highest number in `table`'s series and return the next one.` — max, not count, with the scope validated against the UNIQUE constraint at `:114-117` and a **raise** rather than `return 1` on a failed read (`:108-111`).
PREMISE: the finding's premise was already refuted by its own verification (the only delete removes the highest-numbered row). Now moot regardless — the fix landed exactly as suggested, via `services/numbering.py`.
SIZE: 0.

---

**PUR-32 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/purchase_bills.py:333` — `key = (bill_no or "").strip().lower()`, matched at `:339` — `.eq("client_id", client_id).eq("vendor_id", vendor_id)`; nothing compares amount or date. Vendor side: `/home/user/caflow-ai/apps/api/routers/vendors.py:108-117` — `_match_existing_vendor` tries GSTIN, then PAN, then returns `None`. The production constraint fixture lists no unique constraint on `vendors` beyond `vendors_pkey`.
PREMISE: sound.
SHAPE: `apps/api/routers/purchase_bills.py` and `apps/api/routers/vendors.py`, plus a response field the editor renders. No migration if the name match stays app-level.
Two hazards the suggested fix does not name. First, the existing number guard **raises 409** (`:880-882`); the new amount+date check must not, or you refuse legitimate same-day same-amount bills (a utility on a standing order). Second, `create_vendor`'s duplicate branch does not warn — it **silently returns the existing row** as success: `routers/vendors.py:271` — `return api_response(True, {**existing, "duplicate": True})`. Extending that path to a fuzzy name match would silently merge two genuinely different unregistered suppliers into one and give no sign it happened. The name match has to be a distinct warning branch, not an extra clause in `_match_existing_vendor`.
Note also `_duplicate_bill_id`'s docstring at `:329-331` — it and migration 313's index "must agree", held together by `tests/test_no_duplicate_purchase_bill.py`. A soft warning is a *different* check and is fine; do not touch the exact-match branch.
SIZE: day.

---

### Cross-subsystem duplicates found

Beyond the PUR-07 ≡ TDS-13 pair the phase plan already names:

- **PUR-23 ≡ TDS-32** — the same defect. PUR-23 is the `tds_deductions` register half, TDS-32 the 26Q half; TDS-32 quotes the codebase's own written admission at `services/tds_return_service.py:33-37`. Fixing either alone leaves the other's symptom.
- **PUR-18 ≡ GST-24** — the same three lines (`gstr3b_computer.py:316-317` and the ISD row). PUR-18 adds the Bill of Entry document, GST-24 adds ISD.
- **PUR-20 ≡ SALES-20** — the same missing cess column, inward and outward. PUR-20's verification already says so. 3B's cess line is only right if both land.
- **PUR-22 ≡ SALES-14** — exact mirror: a correct allocation endpoint on each side (`PATCH /purchase-payments/{id}/allocate`, `PUT /receipts/{id}/allocations`) that no screen calls. Same UI shape, same trap about advance handling.

### Stale rate for this batch

4 of 18 are closed (PUR-12, PUR-29, PUR-30, PUR-31) — 22%, above the ~10% you expected. Two of those four (PUR-29, PUR-31) were closed by the finding being *wrong*, not by a fix; PUR-12 and PUR-30 were genuinely fixed and the fixes carry guard tests. One more (PUR-28) has a materially false premise and is a two-line migration rather than the ~320-read refactor its `suggested_fix` proposes.
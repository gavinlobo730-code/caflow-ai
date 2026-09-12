I have what I need. Here are the sixteen verdicts against the code as it stands today.

---

**GST-06 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/gst/gstr3b_computer.py:545` — `"osup_nongst": {"txval": 0},` still a literal. The accumulation branch at `:748-759` runs `if s.supply_type in ("nil_rated", "exempt") … elif s.supply_type == "zero_rated" … elif s.supply_type == "taxable"` — `non_gst` falls off the end. Counterpart confirmed live at `gstr1_builder.py:532` — `"non_gst":   "ngsup_amt",`.
PREMISE: sound. Line numbers drifted (545 not 424; 748-759 not 663-671) but every assertion holds, including the GSTR-1/3B disagreement on the same invoice.
STATUTE: GSTR-3B Table 3.1(e), Notification 14/2022-CT layout. Nothing in CLAUDE.md's Table 4 / §49(5) / §15(3)(a) / §37(3) rules bears on it, and the finding correctly does *not* claim a tax effect — 3.1(e) is a disclosure line. Correct as cited.
SHAPE: one accumulator field on `GSTR3BResult`, one `elif` in the loop, one payload line; then `services/gst_return_service.py` `working.outward` (the screen contract test `test_gstr3b_screen_contract.py` will demand it), the 3.1(e) row on `apps/web/app/gst/gstr3b/page.tsx`, and `services/filing_demo/gstr3b.py` whose "not tracked upstream" comment must be corrected in the same commit. No migration — `supply_type` already carries `non_gst`.
SIZE: hours

---

**GST-15 — VERDICT: open, and now WORSE than when it was written**
EVIDENCE: `services/gst_advance_service.py:255` — `"table_11_computed": False,` and `:257` — `"PracticeSync does not compute GSTR-1 Table 11. …"`, while `table_11_sections` at `:126-200` computes real `at`/`txpd` rows and `services/gst_return_service.py:1279-1280` merges them (`table_11 = gst_advance_service.table_11_sections(...)` / `for key in ("at", "txpd"):`). `grep -i advance domain/gst/gstr3b_computer.py` → nothing.
PREMISE: sound, and the verification's one mitigation is now DEAD. The verifier's escape hatch was "the enabling data is unreachable from the product". It is reachable now: `apps/web/components/ClientFormModal.tsx:180-181` is a checkbox writing `gst_advance_tax_applicable`, and `apps/web/app/clients/[id]/sales/page.tsx:3615-3616` writes `gst_rate_bps` and `place_of_supply` onto the receipt. So the latent contradiction is live product behaviour: a CA can tick the box, and GSTR-1 will declare a Table 11A liability that GSTR-3B 3.1(a) never pays.
STATUTE: §13(2) (advance for services taxable on receipt) and Notification 66/2017-CT (removed for goods) — both cited correctly, in the code and the finding. The statutory reasoning is not the problem; the internal contradiction is. Note the module docstring at `:27-32` still says "Nothing has ever been declared in 11A", which is now false in the same file that makes it false.
SHAPE: `domain/gst/gstr3b_computer.py` gains an advances input feeding `outward_taxable_*` (3.1(a)); `services/gst_return_service.py` passes it; `gst_advance_service.advances_report` and its `why` text, the module docstring, and `routers/gst_workspace.py:1335-1350` docstring all have to stop saying "computes no tax". `tests/test_gstr1_advances_are_surfaced.py` and `test_an_advance_carries_what_table_11a_declares_it_at.py` pin both halves and will both need editing. No migration (286 did it).
SIZE: multi-day

---

**GST-17 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/gstr1_builder.py:707-715` — `_HSN_DIGITS_1_5CR_PAISE = 1_50_00_000_00  # ₹1.5 Cr → 4-digit HSN (below this: optional)` and `return 0  # optional below ₹1.5 Cr`. The dead slice is at `:740` — `code = (line.hsn_sac_code or "")[:max(required_digits, len(line.hsn_sac_code or ""))]`. `apps/web/lib/data/gst.ts:592` still sends `aggregate_turnover_paise: 0,   // CA can override on the client GST screen`. No HSN check in `domain/gst/validator.py`, `domain/gst/exception_report.py` or `services/gst_exception_service.py`.
PREMISE: partly FALSE, as the verifier already caught and the finding's own title still gets wrong. "The thresholds are the pre-2021 ones" is not true — the ₹5 crore → 6 digits rung IS the current Notification 78/2020 rule. Only the bottom rung is stale (78/2020 requires 4 digits on B2B below ₹5 crore; the code returns 0). And the wrong-threshold half has **zero live effect** because the value feeds only a slice that can never shorten a string, and the input is hardcoded 0 on the web path anyway. Fixing the thresholds alone changes no byte of output.
STATUTE: Notification 78/2020-CT (15-10-2020, w.e.f. 01-04-2021) — correctly cited. The code's own comment says "CGST Rule 46(h)", which is the invoice-content rule, not the GSTR-1 Table 12 requirement; that citation is wrong in the code.
SHAPE: `_required_hsn_digits` rewritten to the 78/2020 two-tier rule, turned into a validation emitting rows into the GSTR-1 exception report (`services/gst_exception_service.py`) rather than a truncation; `apps/web/lib/data/gst.ts:592` has to actually source the client's AATO, which means somewhere to store it — likely a `clients` column, so **yes, a migration**. Table 12 B2B/B2C split is a separate builder change.
SIZE: multi-day

---

**GST-18 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/gstr1_builder.py:847` — `"docs": [{"num": count, "cancel": 0, "net_issue": count}],`. `grep totnum apps/api` → nothing.
PREMISE: sound on the payload shape, with one sub-claim the verifier already killed and which should stay killed: the builder canNOT "see cancelled documents" — `gstr1_from_books` feeds it posted invoices and issued notes only. Note the irony the module itself documents: the docstring at `:819-826` explains carefully that `doc_num` is the form's fixed position and not a running count, then makes exactly that mistake one line later with `num`.
STATUTE: Table 13 of FORM GSTR-1 (Rule 59). Cited correctly. Not touched by any CLAUDE.md rule.
SHAPE: the serial range and cancelled count cannot come from the builder's input at all — they have to be read from `sales_invoices` / credit-note / debit-note tables (min/max of the number series per nature, plus a cancelled count), which means a new query in `services/gst_return_service.py` and a new field on `InvoiceForGSTR1`'s feed. Key names need checking against the current GSTN offline tool before shipping. Probably no migration if `status='cancelled'` already exists on those tables — verify that first.
SIZE: multi-day

---

**GST-21 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/gstr3b_computer.py:648-651` — `"intr_ltfee": { "intr_details": {"iamt": 0, ...}, "fee_details": {"iamt": 0, ...} }`. No `domain/gst/interest.py`; `ls domain/gst/` confirms. Only prose hits: `domain/gst/itc_reversal.py:12` and `:142`.
PREMISE: sound. The refusal is still explicit in `services/filing_demo/gstr3b.py`, and the contrast the verifier drew still holds — income tax DOES compute §234A/B/C in `domain/income_tax/advance_tax_interest_engine.py`, so the absence is GST-specific.
STATUTE: §50(1) with its proviso (interest on the net cash component only, where the return is filed after the due date and the credit was in the ledger), §50(3) with Rule 88B for wrongly-availed-and-utilised credit, and §47 with its nil-return and cap variants. All cited correctly. Nothing in CLAUDE.md contradicts. Watch one trap when building it: the §50(1) proviso's "net cash" base is NOT `cash_payable_paise` — reverse-charge tax is always cash and is outside the credit-ledger question the proviso is about.
SHAPE: new `domain/gst/interest.py`; needs a filed-date input (already available via `filings` / `record_filing`) and the ledger balance at the due date; then Table 5.1 in `gstr3b_computer.as_gstn_payload`, a row on `apps/web/app/gst/gstr3b/page.tsx`, and the Rule 37 report. No migration.
SIZE: multi-day

---

**GST-22 — VERDICT: partial**
EVIDENCE: FIXED — the zero-rated row now prints tax, not value: `apps/web/app/gst/gstr3b/page.tsx:338-340` renders `w.outward.zero_rated_igst_paise` in the IGST column with a §16(3)(b) note, and `:363` totals `taxable_igst_paise + zero_rated_igst_paise`. RCM is now on the page: `:589-594` "Reverse charge, payable in cash … Table 3.1(d)" and `:596-600` a "Total payable in cash" challan line. STILL OPEN — `:345-346`: `<td …>Nil-rated / Exempt</td>` followed by `<td …>{r(w.outward.nil_exempt_paise)}</td>` in the IGST column. There is still no taxable-value column (headers at `:311-314` are Supply Type | IGST | CGST | SGST), no 3.1(e), no 3.1.1, no 3.2, no Table 5, no Table 5.1.
PREMISE: half FALSE now. "prints taxable VALUES in the IGST column" is true for exactly one row, not two; "labels the sum … Total Output Tax" excluding reverse charge is fixed; "a grep for rcm returns nothing" is fixed.
STATUTE: display of Table 3.1 per the Notification 14/2022 form. No statutory error. Nothing filed is wrong — `gstr3b_computer.py` emits both under `txval` correctly.
SHAPE: one file, `apps/web/app/gst/gstr3b/page.tsx`. Adding 3.2 also needs `services/gst_return_service.py` to return `inter_sup_unreg/comp/uin` (computed at `gstr3b_computer.py:772-774` but not in the screen contract), and 3.1(e) depends on GST-06. `services/filing_demo/gstr3b.py:202` already has the correct 5-column layout to copy. No migration.
SIZE: day

---

**GST-23 — VERDICT: closed on the real defect; premise was FALSE and remains FALSE**
EVIDENCE: `apps/web/lib/data/gst.ts:802-806` — `const res = await api.gstWorkspace.setGstr3bStatus(returnId, { status: "submitted", ca_approved: true, arn, });` and `:824-828` the identical `setGstr1Status`. Both check `if (!res.success) throw`. The backend calls `record_filing` at `routers/gst_workspace.py:557-561` (GSTR-3B) and `:784-788` (GSTR-1), each passing `filed_date=body.filed_date, arn=body.arn`. The lock is now pinned by `tests/test_marking_a_return_filed_closes_its_period.py` — 13 tests including `test_the_filings_row_is_what_the_lock_reads` and `test_a_gstr1_tick_records_a_gstr1_filing`.
PREMISE: FALSE, twice over. (1) The finding's literal claim — "GSTR-3B has one, GSTR-1 does not" — was never true and still isn't; both `/gst/gstr1` and `/gst/gstr3b` have a Mark-as-Filed with ARN. (2) The genuine defect the verifier substituted (direct PostgREST write skipping `record_filing`, so §37 period lock never engages) is now fixed for both returns. What survives is cosmetic and symmetric: the client-workspace tab at `apps/web/app/clients/[id]/compliance/gst/page.tsx:631-642` (GSTR-1) and `:1166-1182` (GSTR-3B) both offer only Validate / CA Approve / File (demo). There is no GSTR-1-vs-3B asymmetry anywhere.
STATUTE: §37(3) correction window / the period lock. The lock's actual authority is `migrations/266_editable_journals_until_locked_or_filed.sql` reading `public.filings` with a non-null `filed_date` — the finding never named the statute, and its framing of "period lock never created" is now moot.
SHAPE: nothing needs doing. If you want the shortcut on the client tab, it is one modal reused in one file.
SIZE: hours (and optional)

---

**GST-24 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/gstr3b_computer.py:316-321` — `("IMPG", 0, 0, 0, 0),` / `("IMPS", 0, 0, 0, 0),` / `("ISD", 0, 0, 0, 0),` with the docstring at `:302` still reading "IMPG, IMPS and ISD are zero because nothing upstream distinguishes an import or an ISD distribution from any other purchase yet." No `is_import`/`bill_of_entry`/`icegate` column on `purchase_bills` in any migration — the only hit is a comment in `340_a_2b_document_remembers_which_bill_it_matched.sql:35`.
PREMISE: sound, with the verifier's bound intact and important: total 4(A) is right in AMOUNT — the credit lands in OTH, it is not lost. What breaks is the row-wise tie-up against 2B's ICEGATE-populated IMPG section.
STATUTE: Table 4(A)(1)/(2)/(4) per Notification 14/2022 with Circular 170/02/2022. Correctly cited, and consistent with CLAUDE.md's rule that **4(A) is gross** — misrouting credit between 4(A) rows does not violate that, which is precisely why the amount stays right. The finding's "ISD is now compulsory" is correct statute the verifier could not check: Finance Act 2024 amended §2(61) and §20, notified by 16/2024-CT w.e.f. 01-04-2025. Worth recording — it means an ISD gap is no longer optional-scheme, it is a live obligation for any client with common input services across registrations.
SHAPE: IMPG/IMPS is an `is_import` flag plus bill-of-entry number/date on `purchase_bills` — **migration required** — then `services/gst_return_service.py`'s purchase feed, `PurchaseTransaction`, the row builder, and the 2B `impg` matcher in `domain/gst/itc_matching.py`. ISD is a separate product: own registration, GSTR-6, a distribution engine. Split them; do not bundle.
SIZE: multi-day (IMPG/IMPS alone); ISD is out of scope for a single fix

---

**GST-25 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/gstr3b_computer.py:490-491` — `eco_dtls = ({"eco_dtls": {"eco_sup": dict(eco_zero), …` built from a literal, with `:487` "nothing marks a supply as made through an ECO, and neither side of §9(5) is modelled". `gstr1_builder.py:472` — `"typ": "OE",` hardcoded for the same reason. No composition/scheme/registration-type column on `clients` in any migration. GSTR-9C exists only as prose in `services/filing_demo/gstr9.py:138-175`.
PREMISE: sound. One refinement: the filing demo now explains GSTR-9C properly (Rule 80, self-certified since 2021, Circular 246/03/2025-GST on the §47(2) late fee attaching to the complete annual return) and deliberately refuses to place the client in a turnover band. So GSTR-9C is *documented* but still not *built* — the finding's "entirely absent" is true of the capability, not of the knowledge.
STATUTE: §10 with Rule 62 (CMP-08/GSTR-4), §52 with Rule 67 (GSTR-8 TCS) and §9(5) with Notification 17/2017 (3.1.1), §44 with Rule 80 (GSTR-9C). All cited correctly. The 3.1.1 side is where CLAUDE.md matters: §9(5) has TWO sides — the ECO liable instead of the supplier (`eco_sup`), and the supplier's own turnover through an ECO on which it does not pay (`eco_reg_sup`) — and the code already names both, so whoever builds it must not collapse them.
SHAPE: composition is a `clients` column plus a whole return module — **migration required**. §9(5)/TCS is a per-invoice ECO marker (migration) feeding 3.1.1, GSTR-1 tables 14/15 and `supeco`. GSTR-9C waits on GSTR-9.
SIZE: multi-day each, three separate tracks

---

**GST-26 — VERDICT: open by documented decision — not a defect**
EVIDENCE: `routers/hsn.py:5-8` — "`public.hsn_master`, a Caflow-shipped global code list. It no longer does — … `hsn_master` is retained". The table and its ~204 seeded rows still exist (`migrations/036_gst_engine.sql:29`, `:175`) with a public-read policy at `:147-148`, and `grep hsn_master apps/web` returns nothing.
PREMISE: facts sound, framing FALSE — and the verifier already said so. This is "Decision A" in `docs/FIRM_HSN_LIBRARY.md:36-51`, taken on liability grounds ("Caflow asserts no classification content of any kind, anywhere a user can see it"), with two live mitigations the finding omits: onboarding step 3 (`apps/web/app/onboarding/page.tsx:108`, `:124` links the GST portal's own HSN search) and inline quick-add. Calling it "every firm builds its own library from nothing" describes the cost that was consciously bought.
STATUTE: none. This turns on Rule 46(h)/Notification 78/2020 only insofar as a code is required at all; classification liability is the actual question and it is a business decision, not a statutory one.
SHAPE: reversing it needs no migration at all — `hsn_master` was retained precisely so the decision could be reversed without a schema rebuild (`docs/HSN_SAC_MASTER_MAINTENANCE.md:5-15`). It is `routers/hsn.py::_fetch_library_rows` merging a second source behind the firm's own, plus a data load. The hard part is sourcing ~12k leaf codes, not the code.
SIZE: day for the merge; the catalogue load is a data problem, and the decision to reverse is the owner's, not an engineer's

---

**GST-27 — VERDICT: closed**
EVIDENCE: `apps/web/app/gst/reconciliation/page.tsx` no longer exists (`ls apps/web/app/gst/` → `gstr1`, `gstr3b`, `page.tsx`). CLAUDE.md records it: "**One screen, since 11-09-2026.** There were two. `/gst/reconciliation` matched two uploaded files in the browser, saved nothing … **Deleted on the owner's decision.**" The deletion is guarded — `apps/web/scripts/the-2b-reconciliation-reads-the-books.test.ts` holds `const OLD_SCREEN = "app/clients/…"`-style constants asserting the file is absent and nothing links to the route, "so a second implementation cannot reappear quietly".
PREMISE: was sound; the whole subject is gone. The `parseFloat × 100` violation, the invented 3-paise tolerance and the browser-side matching engine all went with the file.
STATUTE: §16(2)(aa) / Rule 36(4). Was cited only indirectly. The real reconciliation now lives in `services/gst_2b_reconciliation_service.py` reading `purchase_bills` itself, which is the correct posture.
SHAPE: nothing.
SIZE: —

---

**GST-28 — VERDICT: partial**
EVIDENCE: CLOSED half — the register endpoints now have a screen: `apps/web/components/gst/ItcRegisterTab.tsx`, mounted at `apps/web/app/clients/[id]/compliance/gst/page.tsx:1816` — `{tab === "itc" && <ItcRegisterTab clientId={clientId} />}`, and its header names all four endpoints as "Four finished endpoints that no screen reached". OPEN half — `services/itc_reversal_service.py:231-234` returns `{… "bills": items …}` with `days_outstanding`, `payment_due_by`, `reverse_in_period` and no interest field; §50 appears only in prose at `:7`, `:51`, `:227`. `rule_37a` is still just a string in `services/itc_register_service.py:49` and `routers/gst_workspace.py:1234`, with no detector.
PREMISE: partly FALSE now. "There is no screen that registers it" is false. And the finding's suggested fix — a "Post this reversal" action — is explicitly refused by design: `ItcRegisterTab.tsx:12-19` states "IT REGISTERS A JOURNAL, IT DOES NOT POST ONE … the CA raises it as a manual journal like any other entry, through the one posting kernel. What was missing was never a way to POST the reversal; it was a way to say WHAT IT WAS." That reasoning is right and should not be overturned.
STATUTE: Rule 37 (180-day non-payment, reversal in the return for the period *after* expiry) and Rule 37A (supplier's GSTR-3B not filed by 30 September following the FY, reversal by 30 November). Both cited correctly. §50 interest on a Rule 37 reversal is right in principle and depends on GST-21.
SHAPE: interest is a field on `rule37_report` plus a column on the GSTR-3B panel, blocked on `domain/gst/interest.py`. Rule 37A needs supplier GSTR-3B filing status, which 2B does not carry — it is blocked on a data source the product does not have, and should be recorded as such rather than scheduled.
SIZE: day for the §50 column once GST-21 exists; Rule 37A is blocked, not sized

---

**GST-29 — VERDICT: open, unchanged**
EVIDENCE: `domain/gst/validator.py:16` — `GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")`, used at `:79` and `:124` (`if inv.party_gstin and not GSTIN_RE.match(inv.party_gstin)`). `core/validators.py:44` is shape + state code. `domain/gst/gstin.py` is imported by exactly three routers — `customers.py:11`, `vendors.py:12`, `onboarding.py:10` — and called at exactly three sites: `customers.py:270`, `vendors.py:239`, `onboarding.py:72`, all in the single-create POST.
PREMISE: sound, and the verifier's strengthening still holds — `POST /customers/bulk` (`customers.py:372`), `PATCH /customers/{id}` (`:637`) and the vendor equivalents remain unguarded, so a transposed GSTIN still enters by CSV import or by edit and reaches Table 4A untested.
STATUTE: §37 read with §16(2)(aa) — the credit reaches whoever the GSTIN names, so a valid-shaped wrong GSTIN silently gifts the credit to a stranger. CLAUDE.md's own line (`:1208-1214`) says the check digit is "Enforced where a human TYPES a GSTIN — onboarding, the customer and vendor create paths". A bulk CSV and an edit form are both places a human types a GSTIN. **CLAUDE.md overstates what the code does**, and the deliberate carve-out it records covers only `models.client.validate_gstin` (the 512 invented fixtures), not these routes.
SHAPE: `GSTValidator.validate_gstin` delegates to `domain/gst/gstin.problem_with`; add `gstin_problem` to the bulk and PATCH handlers in `routers/customers.py` and `routers/vendors.py`; add counterparty GSTIN checking to the from-books build as *exception-report rows*, never as a hard reject of the whole return. No migration. Existing bad rows are the real cost — the bulk path has been open, so a backfill report is part of the job.
SIZE: hours for the wiring; add half a day for a "which existing GSTINs fail" report

---

**GST-30 — VERDICT: partial, close to closed**
EVIDENCE: The specific test the finding named is gone. `tests/test_gst_rcm_gstr3b.py:38` is now `test_c4_c5_rcm_liability_and_itc_are_equal_but_not_a_wash`, whose docstring says "reading them as 'net effect zero' is exactly the mistake the engine used to make", and which asserts `r.cash_payable_paise == K18`. A whole new file exists: `tests/test_gstr3b_setoff_and_rcm.py`, 24 tests across `TestCrossUtilisationAgainstIGST`, `TestNoCrossUtilisationBetweenCGSTAndSGST`, `TestExcessIGSTCreditIsNotStranded`, `TestReverseChargeIsPaidInCash`, `TestZeroRatedSupplies`, plus `test_one_period_carrying_all_three`. Also `tests/test_the_challan_figure_includes_reverse_charge.py`. Three of the four named scenarios are covered end-to-end; **non-GST outward supplies still have no test**, because the defect (GST-06) is still there.
PREMISE: FALSE as written. "A test encodes the assumption behind the reverse-charge underpayment" no longer describes any test in the repo, and the four underlying defects it listed are three-quarters fixed in the code: `gstr3b_computer.py:940-1023` implements the full four-step §49(5) set-off, `:392-415` adds `cash_payable_*` including RCM, `:758` accumulates `outward_zero_rated_igst`.
STATUTE: §49(5)(a)-(f) with Rule 88A, §49(4) with §2(82), §16(3)(b) with §54. All cited correctly and all now implemented in the order CLAUDE.md prescribes — IGST first, then CGST before SGST because of the proviso to §49(5)(c), and reverse charge outside the ledger entirely.
SHAPE: one test class for non-GST outward supplies, added alongside the GST-06 fix. Separately worth noting: `tests/e2e_gst_verification.py` is still not collected by pytest (no `test_` prefix) — it asserts real end-to-end figures and runs in no CI.
SIZE: hours (fold into GST-06)

---

**GST-31 — VERDICT: partial — the trap is closed, the description still stands**
EVIDENCE: `domain/gst/portal_service.py:91-96` now refuses: `if provider_name != "manual": raise ValueError(f"No GST portal provider named '{provider_name}'. Only 'manual' exists — …")`, with the reason written out at `:85-89`: "It now refuses a name it does not have, so the switch has to be wired in the same commit that adds the provider rather than remembered afterwards." `wc -l routers/gst_portal.py` → 165, unchanged; `grep -rn 'gst-portal|gst_portal|gstPortal|gst_sync_jobs|gst_portal_snapshots' apps/web` → nothing.
PREMISE: one sub-claim now FALSE. The finding says the TODO "warns that `get_provider` ignores its argument" — it no longer ignores it, and the comment has been rewritten to say so. The main claim (complete, honest, screen-unreachable) is still exactly true.
STATUTE: none directly. It turns on GSP empanelment, which `docs/compliance/07-getting-permission-to-file.md` and CLAUDE.md `:1028` both record as a hard gate for reading returns at any turnover.
SHAPE: the finding's own recommendation is "Leave it", and that is right. When a GSP is contracted, one factory branch in `portal_service.get_provider` plus a screen.
SIZE: hours, whenever a GSP exists

---

**GST-32 — VERDICT: open, unchanged**
EVIDENCE: `grep -rn 'INV-01|INV01|SellerDtls|BuyerDtls|ItemList|DocDtls|ValDtls'` across `apps/api` and `apps/web` returns only unrelated hits — `services/stock_position_service.py:2` and `migrations/363_…sql:4`, where "INV-01" is this repo's *inventory* finding ID, not the GST schema. `domain/income_tax/einvoice_service.py:46-47` — `def generate_irn(self, invoice_data: dict) -> dict: return {"irn": None, "ack_number": None, "ack_date": None, "qr_data": None}`. The 30-day limit appears once, as a comment: `routers/einvoice.py:13`. No e-invoice-to-GSTR-1 comparison.
PREMISE: sound on every limb. Note the verifier's aside is still true and is the sharper point: CLAUDE.md's Scope line claims "prepare-only e-invoice/e-way/XBRL rails" are shipped, and for e-invoice that overstates what exists — the rail records an IRN a human already obtained from the IRP.
STATUTE: Rule 48(4) with Notification 13/2020 as amended (₹5 crore AATO from 01-08-2023), and the 30-day reporting window from 01-04-2025 for AATO ≥ ₹10 crore (GSTN advisory, an IRP-side validation). Cited correctly. `docs/compliance/02-gst.md:186-197` records that the NIC sandbox is self-service at any turnover — so unlike GST-31, **the GSP gate does not block this work**, and the doc says so explicitly.
SHAPE: a new INV-01 payload builder in `domain/gst/` fed from the sales-invoice feed (same posture as the GSTR-1 JSON: prepare and download, do not transmit); a document-age check in `apps/web/lib/invoices/compliance.ts::irnEligibility`, which needs the client's AATO — the same missing input as GST-17, so **share the migration with it**; and an e-invoice-vs-GSTR-1-B2B comparison once IRNs are recorded.
SIZE: multi-day

---

**Three things worth carrying back to whoever triages this:**

1. **Stale rate is about 25%, not 10%.** GST-27 is fully closed (screen deleted with a regression guard). GST-23's real defect is closed. GST-30 is three-quarters closed by a new 24-test file. GST-22 and GST-28 are each half closed. Do not schedule these as written.

2. **GST-15 moved the wrong way.** The only thing keeping it latent — an unwritable switch — was wired up in the interim (`ClientFormModal.tsx:180`, `sales/page.tsx:3615`). It is now a live contradiction that can produce a GSTR-1 declaring a liability GSTR-3B never pays. It deserves promotion, not the "medium" the verifier gave it.

3. **GST-17 and GST-32 share a blocker.** Both need the client's annual aggregate turnover, which the product does not store — `apps/web/lib/data/gst.ts:592` hardcodes `aggregate_turnover_paise: 0`. One `clients` column unblocks the HSN digit rule and the e-invoice 30-day/eligibility check together. Do that migration once.
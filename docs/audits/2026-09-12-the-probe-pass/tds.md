I have what I need. Here is the verification.

---

## Slice: TDS-01 … TDS-32, verified against HEAD `92392e2c`

---

**TDS-01 — VERDICT: closed**
EVIDENCE: `apps/api/domain/tds/section_rates.py:199,204,210,220,224,228,286,291` now carry `aggregate_threshold_paise=` on 193/194/194A/194D/194G/194H/194K/194LA; `:273-274` `"194J": TDSSectionRule(50_000_00, 1000, 1000, aggregate_threshold_paise=50_000_00, …)`; `:305-307` gives 194Q both limbs. `tds_computer.py:417-420` unchanged but the second limb is now live; `:435` `charge_base = fy_total`; `:471` `tds = max(0, cumulative_tds - fy_prior_tds_paise)`. Run in this session: `resolve_tds('194J', 45_000_00, fy_prior_taxable_paise=4_00_000_00, fy_prior_tds_paise=40_000_00)` → `applies=True, tds=4,50,000 paise`; `194H` prior ₹1,00,000 → `applies=True`.
PREMISE: FALSE now. The docstring at `section_rates.py:69-108` records the change and names the four sections that deliberately have none (194I, 194B, 192, 206C).
FIX: the finding's fix was *incomplete in the dangerous direction* — it said "the crossing bill must withhold on `fy_total`" and never mentioned §200 credit. Implemented literally it re-charges the whole year on every later bill. What shipped adds `fy_prior_tds_paise` (`tds_computer.py:341-342,471`) and every caller passes both (`services/vendor_tds.py:372-373`, `routers/tds_workspace.py:409-410`); no caller passes one alone. Do not resurrect the finding's wording.
SHAPE: n/a. SIZE: n/a.

---

**TDS-02 — VERDICT: closed**
EVIDENCE: `section_rates.py:143` `charge_on_excess_only: bool = False` on the rule; `:305-307` sets it True for 194Q; `tds_computer.py:436-443` `charge_base = max(0, fy_total - rule.single_threshold_paise)`. Run: `resolve_tds('194Q', 60_00_000_00, fy='2025-26')` → **₹1,000**, not ₹6,000. Two ₹30,00,000 bills → second withholds ₹1,000.
PREMISE: FALSE now.
FIX: sound and shipped, including the `charge_on_excess_only` property-not-name-test shape CLAUDE.md requires. The ₹10-crore buyer-turnover proviso is still a named non-decision (`section_rates.py:110-113`), matching CLAUDE.md.
SHAPE/SIZE: n/a.

---

**TDS-03 — VERDICT: closed** (all three named breaks)
EVIDENCE: (1) `apps/web/lib/data/tds.ts:123,131` now `authedFetch("/api/tds/26q/compute"…)`, with the reason at `:116-121`. (2) `services/tds_register_service.py:283` `"financial_year": fy_label(when)` in the upsert (and `:437` for the payment path). (3) `:284` `"quarter": fy_quarter(when)` — bare `Q3`; `migrations/347_the_tds_register_speaks_one_quarter_vocabulary.sql` backfills and normalises the compound `'Q3 2025-26'`.
PREMISE: FALSE now on all three.
FIX: the second half of the suggested fix — "delete the browser-side assembly and point the screen at `/26q/from-books`" — was **not** done. `apps/web/app/tds/returns/page.tsx:102-167` still assembles in the browser, and that residue carries TDS-29 and a hardcoded TAN (see §2 below). The per-client screen `apps/web/app/clients/[id]/compliance/tds/page.tsx:412-414` does use `from-books`.
SHAPE: residual is one screen; deleting `/tds/returns` in favour of the compliance tab is the cheap answer. SIZE: hours.

---

**TDS-04 — VERDICT: closed**
EVIDENCE: `routers/tds_workspace.py:242-247` `_CERTIFICATE_TYPES` maps `"form 16a"→"16A"`, `"131"→"16A"` etc.; `:267-277` `@field_validator` raises on anything else (422, not a swallowed 200). Screen: `apps/web/app/clients/[id]/compliance/tds/page.tsx:778` seeds `certificate_type: "16A"`, `:855-856` `<option value="16">/<option value="16A">`, and `saveNew` at `:810` `if (!res.success) { setSaveError(…); return; }`.
PREMISE: FALSE now. Note the CHECK is unchanged — `migrations/037_tds_engine.sql:89` still `IN ('16','16A','16B','16C')`; the fix is normalisation at the boundary, which is the right shape (CLAUDE.md: translate at the boundary, never rekey).
FIX: sound; the one part not done is "raise 422 on a constraint violation" — `tds_workspace.py:1074-1075` still `except Exception: return api_response(False, None, str(e))`. Harmless now that the screen checks `success`, but the 200-carrying-a-refusal pattern is still live on this router.
SHAPE: `routers/tds_workspace.py` only, no migration. SIZE: hours (optional).

---

**TDS-05 — VERDICT: closed, with one residual**
EVIDENCE: `apps/web/app/tds/page.tsx:60-89` — `SECTION_LABELS` is names only, with `:65-72` recording the eight ways the old table was wrong; `:56-58` imports `listTdsSections, previewTdsDeduction, createTdsDeduction, createTdsChallan`; the CSV import at `:1006-1014` goes through `createTdsDeduction`. No `.insert(` on `tds_deductions` survives (only `.select(` at `:584,1022`). Guard: `apps/web/scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts:53-66` with a shrink-only allowlist.
RESIDUAL: `apps/web/app/tds/page.tsx:7` still reads `Section 194A: TDS on Interest (threshold ₹40,000 bank, ₹5,000 others)` — the pre-Finance-Act-2025 figures the finding cited. Registry is ₹10,000/₹50,000 (`section_rates.py:210`, docstring `:57-59`). Prose only, no computation reads it.
FIX: sound and shipped, plus the lint the finding asked for.
SHAPE: one comment line. SIZE: hours.

---

**TDS-06 — VERDICT: closed**
EVIDENCE: `apps/api/domain/tds/challan_mapping.py` (new, 192 lines) — `:1-66` states the defect and the FIFO answer; `:51-55` groups by `parent_of` because "a challan records what somebody typed". `services/tds_return_service.py:333` `mapping = challan_mapping.assign(events, challans, fy=fy)`, `:339` `matching_challan = assigned.challan`, `:401` returns `challan_gaps`. `_deposited_challans` at `:253-256`.
PREMISE: FALSE now — no `next((c for c in challans if …), None)` remains, and the largest-remainder apportionment is gone.
FIX: the finding's suggested fix (a `challan_id` FK, or match by deposit MONTH) was **deliberately rejected**, and the rejection is better reasoned than the finding: `challan_mapping.py:32-49` records that the RPU challan row has no deduction-month field and forcing one makes a catch-up challan read as leaving the earlier month unpaid. `:57-64` explains why no `challan_id` column yet. Do not re-apply the finding's fix.
SHAPE/SIZE: n/a.

---

**TDS-07 — VERDICT: closed**
EVIDENCE: `apps/web/app/clients/[id]/purchases/page.tsx:294-301` — the dropdown is 194A/194B/194C/194D/194H/194I/194J/194Q; 194IA and 192 are gone (`:286-293` says why 192 went). `routers/purchase_bills.py:30-39` records `_TDS_DEFAULT_BPS` as deleted. `domain/tds/residency.py:310-401` `deduction_section_refusal` returns a CA-readable sentence naming the section, the sections that *are* computable, and — for `_PROPERTY_SECTIONS` (`:307`) — that there is no way to FILE it. Applied at the vendor master (`models/parties.py:109-111`).
PREMISE: FALSE now (no 422 with a bare `ValueError` string reaches a CA).
FIX: the finding offered two options; the "add it properly" one is **unsound as written** — see TDS-23. The dropdown is still hardcoded rather than served from `GET /api/tds/sections`, but divergence is now caught at the vendor master, so it cannot produce a wedged bill.
SHAPE/SIZE: n/a.

---

**TDS-08 — VERDICT: open**
EVIDENCE: `ls apps/api/domain/tds/` — no `interest.py`. `grep '201(1A)'` across `apps/api` returns only prose (`challan_mapping.py:77,89`, `compliance_engine.py:350,375`, `purchase_bills.py:299,584`, `residency.py:148`, `ai_insight_service.py:270`). `234E` appears only in `services/filing_demo/tds_return.py:32-33,208-226`. `routers/tds_workspace.py:738-756` (`create_challan`) writes `"tds_paise": body.amount_paise, "total_paise": body.amount_paise` and never `interest_paise`/`penalty_paise`; `:743-746` says so in a comment.
PREMISE: TRUE, unchanged.
FIX: sound — two pure functions over dates the system holds. Two things the finding omits: (a) §201(1A) has **two** rates and two clocks — (i) 1% per month from the date tax *was deductible* to the date deducted, (ii) 1.5% from the date *deducted* to the date deposited; `challan_mapping.py:77` already states (ii) correctly, so the new module must not collapse them into one. (b) "month or part of a month" is calendar-month counting, not `days/30`; the repo has a day-count helper family (commit `91a11928`) — reuse it rather than adding a third. §234E's cap is "the amount of tax deductible or collectible", per statement, not per deductee.
SHAPE: new `apps/api/domain/tds/interest.py` + tests; surface on `routers/tds_workspace.py` create_challan and the return screen. No migration (`interest_paise`/`penalty_paise` exist, `migrations/037_tds_engine.sql:66-68`). SIZE: day.

---

**TDS-09 — VERDICT: closed**
EVIDENCE: `domain/tds/tds_computer.py:90-113` `TDS27QDeducteeRecord` (country, TIN, surcharge, cess, nil-with-reason) and `:513-533` `compute_27q`, whose docstring records that it deliberately does not filter by section because §194E/194LB/194LC/196D also report there. `services/tds_return_service.py:464` `tds_27q_from_books`, `:532` writes the nil reason, `:579` resolves the form through the vocabulary. Screen: `apps/web/app/clients/[id]/compliance/tds/page.tsx:413` `"27Q": "/api/tds/27q/from-books"`, `:548` a 27Q-only panel. The stale docstring the finding quoted is corrected at `tds_return_service.py:31-36`.
PREMISE: FALSE now.
FIX: shipped, and sourced from `tds_deductions` as the finding suggested.
SHAPE/SIZE: n/a.

---

**TDS-10 — VERDICT: open**
EVIDENCE: `section_rates.py:308-315` — `"206C": TDSSectionRule(0, 10, 10)` with its own "NOT wired to any computation anywhere in this codebase" comment, unchanged. `grep -n 'tcs\|206C\|27EQ'` over `routers/sales_invoices.py` and `routers/receipts.py`: nothing. `27EQ` exists only as a CHECK value (`migrations/037:13,120`, `014:188`) and a label (`vocabulary.py`), plus the return-type validator at `routers/tds.py:517`.
PREMISE: TRUE, unchanged.
FIX: shape is right (collection on RECEIPT, not on invoice; excess-only base). Two cautions the finding does not carry. (1) **Verify §206C(1H) is still in force before building it** — my understanding is that the Finance Act 2025 omitted it w.e.f. 01-04-2025 on the ground that §194Q covers the same transactions, which would make 1H a *pre-01-04-2025 only* build with the same fork shape as the TDS vocabulary. I cannot confirm that here (egress is refused) and the registry's 2025-26 entry is marked `verified=True`, so this needs a human read of the Finance Act before a line is written. (2) Any excess-only TCS must credit what was already collected in the year, exactly as `tds_computer.py:471` does for §200 — the finding's cross-reference to TDS-02 covers the base but not the credit.
SHAPE: new register table + 27EQ builder + Form 27D + receipt hook; migration required. SIZE: multi-day.

---

**TDS-11 — VERDICT: closed**
EVIDENCE: `migrations/345_the_tds_register_is_role_guarded.sql:70-109` — RESTRICTIVE, PER-COMMAND policies on all four TDS tables, Executive for INSERT/UPDATE, Manager for DELETE, with `:51-60` explaining why restrictive and why not `FOR ALL` (a Reviewer must keep SELECT). The scan cap is gone: `tests/test_direct_write_tables_are_role_guarded.py:124-144` records the old `{0,400}?` regex and replaces it with a statement-bounded scan; `:289-309` is a negative control asserting the old regex could not have seen it. Browser writes now: only `lib/data/tds.ts:447-465` (`tds_returns.upsert`) — the two `tds_deductions.insert` calls in `app/tds/page.tsx` are gone.
PREMISE: FALSE now, both halves.
FIX: both halves shipped. SHAPE/SIZE: n/a.

---

**TDS-12 — VERDICT: open**
EVIDENCE: `services/compliance_obligation_service.py:191-201` emits only `TDS26Q` and, conditionally, `TDS27Q`. `grep '24Q'` over that file and `compliance_engine.py` returns exactly two hits: the false docstring at `compliance_obligation_service.py:301-305` ("THE 24Q RETURN IS NOT HERE EITHER — it is already emitted by `_tds_obligations`") and `compliance_engine.py:322`. `_PAYROLL_OBLIGATION_TYPE` at `:322-326` has only `EPF_DEPOSIT`/`ESI_DEPOSIT`/`TDS_SALARY_DEPOSIT`; there is no vendor-side monthly deposit. `compliance_engine.tds_deposit_due_date` at `:370` is called only from `payroll_deposit_due_dates` (`:386-401`).
PREMISE: TRUE, unchanged. The docstring is still load-bearing misinformation.
FIX: sound. One thing it omits: `_tds_obligations` dedups on `(obligation_type, period_start)` (`:318-321`) and 24Q shares its period_start with 26Q, so a new `TDS24Q` type is required — not a second 26Q row — and the type string must be stable from the first commit or existing rows orphan. Also note `_tds_obligations` already resolves the form name through `vocabulary` (`:187-189`), so a 24Q entry must do the same (138 from FY 2026-27), not hardcode "24Q".
SHAPE: `services/compliance_obligation_service.py` only, no migration. SIZE: hours.

---

**TDS-13 — VERDICT: closed** (≡ PUR-07)
EVIDENCE: `apps/api/domain/tds/lower_deduction.py` (new, 202 lines) — `:14-25` the four facts of a §197 certificate, `:27-43` three named refusals (§197's listed sections only, two live certificates refused rather than guessed, no PAN → no certificate per §206AA(4)). `migrations/359_a_certificate_is_not_a_rate.sql` creates the table. `tds_computer.resolve_tds` now takes `certified_base_paise` and `certificate_rate_bps` (`:346-347`, docs `:397-408`) and SPLITS rather than substitutes (`:459-465`) — Rule 28AA(4)'s ceiling. `vendors.tds_rate_bps` was removed from the vendor form (`apps/web/app/clients/[id]/purchases/page.tsx:1417-1420` "deliberately NOT written any more") and from the importer (`apps/web/lib/imports/mappers.ts:217` "NO RATE IS READ").
PREMISE: FALSE now, both halves.
FIX: shipped, and better than the finding's — the finding proposed `min(section_rate, certificate_rate)`, which ignores Rule 28AA(4)'s certified AMOUNT and would under-deduct past the ceiling; the code splits the base instead (`tds_computer.py:450-458`). `consumed_paise` was deliberately not stored (`lower_deduction.py:45-52`). Do not re-apply the finding's `min()`.
SHAPE/SIZE: n/a.

---

**TDS-14 — VERDICT: closed**
EVIDENCE: `apps/web/components/purchases/PurchaseBillEditor.tsx:342-359` — `estimateForeignTds` replaced by `useServerTdsPreview({clientId, vendorId, billDate, lines, …})` hitting `POST /api/purchase-bills/tds-preview`; `:342-351` states that the save branches on residency first and that none of those inputs is in the browser. `:636-642` renders `tds.data.tds_section` / `tds.data.tds_rate_bps` as returned. The workspace twin at `routers/tds_workspace.py:547-559` records the same rule and explains why `/compute-amount` is not sufficient (no FY aggregate).
PREMISE: FALSE now.
FIX: sound; shipped as a dedicated preview endpoint rather than `/compute-amount`, which is the stronger choice for the reason at `tds_workspace.py:555-558`.
SHAPE/SIZE: n/a.

---

**TDS-15 — VERDICT: closed**
EVIDENCE: Challans — `apps/web/app/tds/page.tsx:458-465` `AddChallanModal` now calls `createTdsChallan({… financial_year: fy …})`, and the list is loaded at `:605` `sb.from("tds_challans").select("*")`. Certificates — `:195-197` type comments `financial_year: string; // not period` and `tds_deducted_paise: number; // not amount_paise`; rendered at `:943-945`. Returns — `:102-119` `STATUS_STYLE` is keyed lower-case against migration 037's CHECK, with `:102-104` recording that the capitalised keys were unreachable; `:896` records that `r.status === "Overdue"` could only ever be 0. Both halves of `getTDSChallans` filter now (`lib/data/tds.ts:410-411`, reason at `:391-397`).
PREMISE: FALSE now on all three tabs.
FIX: shipped. SHAPE/SIZE: n/a.

---

**TDS-16 — VERDICT: open**
EVIDENCE: `lib/data/tds.ts:474-480` still `JSON.stringify`/`.json` download. No FVU writer: `grep -i fvu` over `apps/api` returns only `fvu_json`, workflow step names (`services/workflow_service.py:87,89`), the filing demo, and prose. Correction statements: `routers/tds_workspace.py:904` `allowed = {"pending","prepared","ca_approved","filed"}` — `'revised'` is still unreachable though `migrations/037:24` allows it; no `original_prn`, no C1–C5 anywhere.
PREMISE: TRUE, unchanged.
FIX: sound but the finding under-states the blocker. The FVU record layout is published per FY **per form**, and the file must be validated against a CSI downloaded from the deductor's own TIN account — neither the layout nor the CSI can be obtained from this environment (egress refused), so this is a human-supplied-data item in the same family as the ITR JSON schemas (CLAUDE.md §2), not a code task. The *correction-statement* half is genuinely code-only and could be split out and done first — it needs `original_prn` + a correction type on `tds_returns` and widening the transition set at `:904`.
SHAPE: correction half — `routers/tds_workspace.py` + a migration on `tds_returns`. FVU half — new module + per-form-per-FY layout data a human supplies. SIZE: correction half a day; FVU multi-day and gated on data nobody in the repo has.

---

**TDS-17 — VERDICT: open**
EVIDENCE: `services/tds_return_service.py:371` `"form": _vocabulary.statement_form(_vocabulary.RESIDENT_NON_SALARY, fy_label=fy)` — but `:387` `"section": d.section` untranslated, and `d.section` came off `row.get("tds_section")` at `:206,222`. Same shape at `:598` (27Q) and `:731` (24Q). `routers/tds.py:176-177` translates the form, `:191` and `:273` emit `"section": d.section`. Contrast `domain/payroll/form24q.py`, which resolves `vocab.section(SECTION_192)`. Run in this session: `vocabulary_for('2026-27').section('194J')` → `'393(1)'`, `.section('192')` → `'392'`, `.section('195')` → `'393(2)'`; `statement_form(RESIDENT_NON_SALARY, '2026-27')` → `'140'`. So a FY 2026-27 26Q is named 140 with every line citing 194J.
PREMISE: TRUE, unchanged. This is the exact mistake `vocabulary.py:312-314` says the module exists to prevent.
FIX: sound, with three constraints the finding does not name. (1) **Translate at the emission dict only.** `d.section` also feeds `tds_deductions` and the challan match; rekeying either violates CLAUDE.md and would break `challan_mapping`'s `parent_of` grouping — a challan says "194J" in every period. (2) **§393(1) has no reverse** (CLAUDE.md, and `vocabulary.py`'s own refusal), so once emitted the payload cannot round-trip; anything that reads the payload back to route or reconcile must use the stored 1961 key, not the emitted label. Note `apps/web/lib/data/tds.ts:460` writes the whole payload into `tds_returns.fvu_json`, so the translated label will land in a JSONB store — acceptable as an artefact snapshot, but the routing keys beside it must stay 1961. (3) The 2025-Act statement also wants a **numeric payment code 1001–1067**, which `vocabulary.py` deliberately does not hold — `vocabulary_for('2026-27').gaps()` already returns that sentence and the callers already surface it as `statutory_gaps`; the fix must not imply the line is complete.
SHAPE: `services/tds_return_service.py` (3 sites) + `routers/tds.py` (2 sites); no migration. Add the assertion to the vocabulary test as the finding says. SIZE: hours.

---

**TDS-18 — VERDICT: open**
EVIDENCE: `apps/web/lib/data/tds.ts:79` `form: "24Q" | "26Q";` and `:451` `return_type: payload.form` into `tds_returns`. The API returns whatever `statement_form` gives (`routers/tds.py:176-177,258-259`) — `'140'` for a FY 2026-27 26Q. `migrations/037_tds_engine.sql:12` CHECKs `return_type IN ('24Q','26Q','27Q','27EQ')`. The backend's own writer accepts it verbatim too: `routers/tds_workspace.py:206` `return_type: str = Field(..., description="24Q or 26Q")` and `:847` `"return_type": body.return_type` — no CHECK-value validation.
PREMISE: TRUE. Note the per-client screen is already correct — `apps/web/app/clients/[id]/compliance/tds/page.tsx:440` sends `return_type: computeForm.return_type` (the routing key `"26Q"`/`"24Q"`/`"27Q"`), so the defect survives only through `/tds/returns`.
FIX: sound and is the rule `tds_register_service.py` already applies to `tds_deductions`. Widen the TS type to `string`, and pass the routing key — not `payload.form` — as `return_type`. Worth also constraining `CreateReturnRequest.return_type` to the four CHECK values so a caller cannot reintroduce it; that is a `Literal`, not a migration.
SHAPE: `apps/web/lib/data/tds.ts` + optionally `routers/tds_workspace.py`. No migration. SIZE: hours.

---

**TDS-19 — VERDICT: open**
EVIDENCE: `domain/income_tax/form26as_service.py:186-194` `mapping = {"A": "tds_salary", "B": "tds_other", "C": "advance_tax", "D": "self_assessment", "F": "tds_other"}`, unchanged. `_entries_from_records` at `:324-338` copies `part` and `record_type` onto every entry with no filter; `run_reconciliation` at `:557-561` feeds all of them to `summarise`; `domain/income_tax/form26as_matcher.py:431` `total_26as_paise=sum(e.tds_paise for e in entries)`. So `part` and `record_type` are carried and never read.
PREMISE: TRUE, unchanged.
FIX: **partly unsound as written, and the unsound part is a wrong direction.** The finding says "add A1 for 15G/15H, **A2/F** for 194-IA" and then "filter to the TDS/TCS record types only". Part A2 and Part F point opposite ways: A2 is TDS deducted **from** the client as seller of immovable property — a genuine credit that must stay in the total — while Part F is tax the client **deducted as buyer**, which must not. Lumping them into one record_type and filtering both out drops a real §194-IA credit. Part B (TCS) is also a genuine credit for the collectee and should be reported *separately*, not discarded. Part D (refunds) is the only one that is simply not a credit. The finding's own confidence is `medium` and it says to check against a real statement first — take that seriously; there is no 26AS specimen in this repo.
SHAPE: `domain/income_tax/form26as_service.py` only; no migration, but the reconciliation summary shape changes so `form_26as_reconciliations` consumers need checking. SIZE: hours once the part layout is confirmed by a human.

---

**TDS-20 — VERDICT: open**
EVIDENCE: `form26as_service.py:163-166` still `cols = re.split(r"\t|\|", line)` with `if len(cols) < 5: continue`, fixed positions 1-6 at `:172-177`, and `:180-181` `except (ValueError, IndexError): _logger.debug("Skipping unparseable line…")`. `routers/form_26as.py:51` `raw_text: str` is required and `:99` `parse_26as_text(req.raw_text)`; `document_id` at `:47` is optional and unused for parsing. `apps/web/app/clients/[id]/tax/26as/page.tsx:9` `const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];` — today is 12-09-2026, so the current FY cannot be selected.
PREMISE: TRUE, both halves, unchanged.
FIX: the FY half is sound and trivial (`currentFinancialYearLabel` already exists and `lib/data/tds.ts:15` imports it). The parser half is sound in intent but, like TDS-16, is gated on a real TRACES export nobody in this repo has; report unparsed lines to the CA rather than guessing a layout.
SHAPE: FY half — one line in the 26AS page. Parser — `form26as_service.py`, no migration. SIZE: FY half hours; parser day+, gated.

---

**TDS-21 — VERDICT: open**
EVIDENCE: `routers/tds_workspace.py:1110-1112` `form26as_keys = {(e.get("pan",""), e.get("section","")): e for e in form26as_entries}` — still a dict comprehension; `:1114-1117` compares every book row against that single surviving entry. The docstring at `:1088-1091` is honest that nothing is read from the database. The good matcher (`domain/income_tax/form26as_matcher.py`, four-pass, one-to-one, consuming) sits beside it unused from here.
PREMISE: TRUE, unchanged.
FIX: sound — route through `form26as_matcher.reconcile`. One thing the finding glosses: this endpoint is the **client-as-deductor** direction (self-check on tax the client withheld from its vendors), while `form26as_matcher` was written for the client-as-deductee direction. The passes and the consumption rule do transfer, but the *labels* do not — "missing in books" here means the client's own register is short, not that a deductor failed to file, and the Rule 37BA(1) note the matcher emits is about the wrong party. Rename at the boundary, do not reuse the sentences.
SHAPE: `routers/tds_workspace.py`; no migration. SIZE: hours.

---

**TDS-22 — VERDICT: partial**
EVIDENCE: rates unchanged — `section_rates.py:260-261` `"194I": TDSSectionRule(50_000_00, 1000, 1000, …)` and `:273-274` `"194J": TDSSectionRule(50_000_00, 1000, 1000, aggregate_threshold_paise=50_000_00, …)`; both still 10%. What is new is disclosure and machinery: `TDSSectionRule.parent_section` (`:156`) and `.rate_gap` (`:167`), the two limbs' gap sentences at `:262-268` and `:275-281`, `parent_of()` at `:332-359`, `rate_gap_for()` at `:362-365`, surfaced by `services/vendor_tds.py:439`. `:239-259` records the two refusals — no concessional rate because the repo contradicts itself on it, no split key because the clause code cannot be confirmed.
PREMISE: TRUE on the over-deduction; FALSE on "not modelled at all" — the gap is now named, and the aggregate/challan machinery a split needs is in place.
FIX: sound in shape, **wrong in its key naming, and its stated evidence is available in-repo**. (a) The finding proposes keys `194J(a)/194J(ba)` and `194I(a)/194I(b)`. The department's own code list is in this repository — `apps/api/domain/income_tax/schemas/ITR6_2026_Main_V1.0.json:19469` carries `4-IA:194I(a)- Rent on hiring of plant and machinery`, `4-IB:194I(b) - Rent on other than plant and machinery`, `94J-A:194J(a) - Fees for technical services`, `94J-B:194J(b)- Fees for professional services or royalty etc`. So the return code is `94J-A`, and the professional limb is labelled `194J(b)`, not `194J(ba)`. Using the finding's spelling would put a code no portal accepts on a 26Q line — the exact risk `section_rates.py:249-252` refuses for. (b) Whatever the key, the split must set `parent_section` so the FY aggregate and the challan match stay on the parent (`parent_of`'s docstring, `:337-347`). (c) The **rate** is still not sourced by any of this — an ITR code list gives the label, not the percentage. A guessed 2% is worse than a disclosed over-deduction. (d) 194I must not gain an `aggregate_threshold_paise` in the split — its limit is per month (CLAUDE.md).
SHAPE: `section_rates.py` + the vendor section list + `models/parties.py` refusal set; no migration. SIZE: hours for the keys, blocked on a human reading the rate.

---

**TDS-23 — VERDICT: open (harm mitigated, gap unchanged)**
EVIDENCE: registry keys at `section_rates.py:191-316` are still 192/193/194/194A/194B/194C/194D/194G/194H/194I/194J/194K/194LA/194Q/206C. Run: `resolve_tds('194T', 50_000_00, fy='2025-26')` → `ValueError: Unknown TDS section '194T'`. What changed is that the failure is now a named refusal at the vendor master rather than a wedged bill (`residency.py:310-401`).
PREMISE: TRUE. §194T (live for the whole of FY 2025-26 and FY 2026-27) still cannot be recorded or deducted at all.
FIX: **unsound as written for four of the eight sections.** (1) `194IA`, `194IB` and `194M` are challan-cum-statement sections (26QB/26QC/26QD). Adding a registry row for any of them without building that path converts a visible 422 into a silently mis-routed 26Q row — `return_type_for` (`residency.py:246-253`) picks the statement by **residency alone** and `tds_deductions.return_type` CHECKs only the four quarterly statements. This is pinned: `tests/test_a_section_the_engine_cannot_answer_for_is_refused.py:103` and `:113-120` would both fail on a bare `194IA` row, and `:29-38` states the reasoning. (2) `194N` is charged by a **bank on its customer's cash withdrawal**; it is not a deduction a purchase-bill deductor makes, and putting it in a vendor section list is a category error. (3) `194R` charges a benefit or perquisite that may be wholly in kind — §194R(2) has its own mechanism and there is no bill amount to withhold from; a rate row does not model it. (4) The finding's `194M` at **5%** is a Finance Act behind on my reading (cut to 2% w.e.f. 01-10-2024, same tranche as 194D/194G/194H/194IB) — unconfirmable here, which is precisely why the registry has a `verified` flag. **The safe subset is `194T` alone** (₹20,000, 10%, ordinary 26Q row, resident payee), plus `194S`/`194O` if their rates are read off the Act.
SHAPE: `section_rates.py` + the vendor dropdown + the refusal test's hardcoded list at `:103`. No migration for 194T. SIZE: hours for 194T; multi-day for the 26QB/26QC/26QD family, which is a separate build.

---

**TDS-24 — VERDICT: open**
EVIDENCE: `domain/tds/tds_validator.py:40-48` unchanged — `is_higher_rate_applicable(pan, is_non_filer, base_rate)` returning `max(base_rate * 2, 5.0)`, still documented as current law and still FY-blind, next to `applicable_rate` at `:26` which does take `fy`. `tests/test_tds_engine.py:328-339` still asserts it in three tests. `tds_computer.py:7` still lists §206AB in the module header. `grep '206AB'` over `apps/api` and `apps/web` returns only those four sites — no production caller.
PREMISE: TRUE, unchanged. My understanding matches the finding's (§206AB and §206CCA omitted by the Finance Act 2025 w.e.f. 01-04-2025) but I cannot confirm it from any source in this repo or reachable from this environment.
FIX: the finding offers "delete, or add an `fy` parameter". **Take the second.** Deletion is wrong for the same reason the TDS vocabulary is a fork and not a migration — §206AB governs periods to 31-03-2025 indefinitely, including belated and revised work, and this codebase already computes for arbitrary past FYs. Give it `fy`, return `base_rate` unchanged from FY 2025-26 with the omission cited, keep the three tests and add the post-omission twin. Also fix `tds_computer.py:7`, which advertises a rule with no caller.
SHAPE: `domain/tds/tds_validator.py` + `tds_computer.py:7` + tests. No migration. SIZE: hours, gated on confirming the omission.

---

**TDS-25 — VERDICT: open**
EVIDENCE: `services/tds_register_service.py:238` `if is_195 and not (bill.get("form_15ca_ack_no") or "").strip():` — the gap still fires, and `:408` the same on the payment path. The column exists (`migrations/311_nil_withholding_is_auditable.sql:60-61`) and the API accepts it (`routers/purchase_bills.py:816-817,864-865`, allowlisted for update at `:1263-1264`). `grep -i '15ca'` across `apps/web` excluding `.next` returns **no input and no display** — only three prose comments in `apps/web/app/clients/[id]/purchases/page.tsx:488,937,2027`.
PREMISE: TRUE, unchanged. What did change is that the gap now REACHES the CA (`apps/web/lib/purchases/registerNotes.ts`, the PUR-14 fix), so the CA is now told, on every §195 bill, to record something no screen lets them record.
FIX: sound and small — one conditional field in the bill editor, shown when the vendor is non-resident, plus display on the drawer. `form_15cb_udin` and `form_15ca_filed_on` are on the same allowlist and should go in the same panel rather than a second pass.
SHAPE: `apps/web/components/purchases/PurchaseBillEditor.tsx` + the bill drawer. No migration. SIZE: hours.

---

**TDS-26 — VERDICT: closed**
EVIDENCE: `migrations/348_a_non_resident_payee_has_a_class.sql` adds the recorded payee class, and its header states exactly the finding's arithmetic (a ₹2 crore royalty: ₹80,000 of surcharge where the other ladder gives ₹6,00,000) and the direction (UNDER-deduction → §40(a)(i) disallows the whole expenditure). `domain/tds/section_195.py:225` `payee_class: str = PAYEE_UNKNOWN` replaces the boolean, `:148-179` `payee_class_from_pan` (P, H, C, F, A, B; T and J deliberately unmapped), `:181-200` `_surcharge_percent` indexes `rates.surcharge_by_class[payee_class]`, `:285` picks the "other sums" rate on `payee_class == PAYEE_FOREIGN_COMPANY` rather than on a boolean, `:277` refuses via `_payee_class_refusal`.
PREMISE: FALSE now.
FIX: the finding said "hold one surcharge ladder per class". The code holds them for four classes and **refuses** `firm_llp` and `co_operative` even when recorded, because Part II's ladders for them are not verified (migration header `:39-42`). That is the right call and is consistent with `section_195_rates.py`'s blanket `verified=False`; the finding's own confidence was `medium` on exactly those figures. Do not backfill a 12% ladder from memory.
SHAPE/SIZE: n/a — adding the two ladders later is a pure data change once a human reads Part II.

---

**TDS-27 — VERDICT: open**
EVIDENCE: `migrations/037_tds_engine.sql:114-141` unchanged — `('194J', …, 30000_00, 10, 10)`, `('194I', …, 240000_00, …)`, `('194H', …, 15000_00, 5, 5)`, `('194D', …, 15000_00, 5, 10)`, `('194A', …, 4000_00, …)`, `('194G', …, 15000_00, 5, 5)`, `('194', …, 5000_00, …)`, `('193', …, 1000_00, …)`, `('194K', …, 5000_00, …)`, `('194LA', …, 250000_00, …)`. PK is `section` (`:115`) and both `194C` rows (`:130-131`) insert under `ON CONFLICT (section) DO NOTHING` (`:141`), so the ₹1,00,000 aggregate row never lands. `:166-169` `FOR SELECT TO authenticated USING (true)` — firm-wide. `grep 'tds_section_limits'` across `apps/api` and `apps/web`: zero readers outside migrations 037/041/095.
PREMISE: TRUE, entirely unchanged.
FIX: sound, and the finding's warning is the important half — **do not update the figures in place.** Dropping the table is the clean answer; if it is kept for schema-drift reasons, a `COMMENT ON TABLE` pointing at `domain/tds/section_rates.py` plus a no-readers test is the minimum. One blocker the finding does not mention: `tests/test_schema_matches_production_pg.py` and `test_guards_match_production_pg.py` compare a migration-built database against production snapshots in `tests/fixtures/`, so a DROP needs the fixture refresh described in `docs/schema-drift.md` in the same change.
SHAPE: new migration + fixture refresh, or a comment + test. SIZE: hours.

---

**TDS-28 — VERDICT: open**
EVIDENCE: `routers/tds.py:98-105` `FromBooksRequest` still requires `tan`, `deductor_name`, `deductor_pan`, `deductor_address` from the caller. `apps/web/app/clients/[id]/compliance/tds/page.tsx:357` initialises all four empty and `:496-497` has the CA type the TAN each time; `:512` merely disables the button until they are non-empty. `tds_computer.py:489` still `if not payload.tan or len(payload.tan) != 10` and `:491` the same for the PAN; `TDSValidator.validate_tan` (`domain/tds/tds_validator.py:22-23`, real regex at `:11`) has no caller in `apps/api` outside its own test. `client_statutory_identity` is read only by payroll (`routers/payroll.py:4231,4320`, `services/payslip_pdf_service.py:748`).
PREMISE: TRUE, both halves, unchanged.
FIX: sound. Note the validation half is free — `core/validators.py:61` `validate_tan` is already the one used by `models/parties.py:207,266`, so `_validate_26q`/`_validate_24q` should call that rather than `TDSValidator`'s duplicate, or the codebase gains a third TAN rule. The defaulting half needs `deductor_address` and a responsible-person on `client_statutory_identity` (migration 325 has neither), so it does carry a migration the finding half-acknowledges.
SHAPE: `routers/tds.py`, `tds_computer.py`, the compliance screen, + a migration on `client_statutory_identity`. SIZE: day.

---

**TDS-29 — VERDICT: open**
EVIDENCE: `apps/web/app/tds/returns/page.tsx:124-125` — `tds_deducted_paise: Number(d.tds_paise ?? 0), tds_deposited_paise: Number(d.tds_paise ?? 0)`, unconditionally, for every deductee, whatever `challans` (fetched at `:108`) contains. `tds_computer.py:505-510` then computes `gap = total_tds_deducted_paise - total_tds_deposited_paise` and raises only when `gap > 0`, which by construction cannot happen. The server path is right — `challan_mapping.assign` (`tds_return_service.py:333`) fills FIFO from real challans.
PREMISE: TRUE, unchanged. The finding said it "falls out of TDS-03's fix"; TDS-03's three breaks were fixed *without* deleting the browser assembly, so it did not.
FIX: sound, and the cheap version is right — set it to `0` rather than to the deducted amount, so the validation fires. The right version is deleting `/tds/returns` and pointing at the compliance tab's `from-books`, which is already built for all three statements (26Q/24Q/27Q).
SHAPE: `apps/web/app/tds/returns/page.tsx` (one line) or delete the route. No migration. SIZE: hours.

---

**TDS-30 — VERDICT: open**
EVIDENCE: no deposit-due endpoint anywhere — `grep 'deposit-due\|deposit_due\|challan_281'` over `apps/api/routers`, `apps/api/services`, `apps/web` returns only the payroll family. `routers/tds_workspace.py:738-756` (`create_challan`) still books the typed amount as `tds_paise == total_paise` with no interest/penalty split and never sets `minor_head` (default `'200'`, `migrations/037:72`) — no way to record a 400. `compliance_engine.tds_deposit_due_date` (`:370`) is called only from `payroll_deposit_due_dates` (`:386-401`).
PREMISE: TRUE, unchanged.
FIX: sound. Two additions. (a) The worksheet must group by **deduction month**, and `tds_deductions` now holds `financial_year` + bare `quarter` (migration 347) but no month column — group on `transaction_date`, do not add a stored month, for the same reason `challan_mapping.py:32-49` refused one. (b) The salary side already has a monthly obligation (`TDS_SALARY_DEPOSIT`); a vendor worksheet that sums §192 rows too would double-count, so filter on section as `tds_return_service.py:314` does.
SHAPE: `routers/tds_workspace.py` + a screen; needs TDS-08's interest module to be useful; a migration only if `minor_head` becomes settable. SIZE: day.

---

**TDS-31 — VERDICT: closed**
EVIDENCE: `routers/purchase_bills.py:30-39` — the constant is gone and replaced by a comment recording why (`:32-35`: it was the last place in `apps/api` asserting a rate for §194IA, and it gave §194H 500 bps where the registry records the Finance (No. 2) Act 2024 cut to 200). `grep '_TDS_DEFAULT_BPS'` over the tree returns only that comment.
PREMISE: FALSE now.
FIX: shipped as the finding suggested — deleted, not corrected. SHAPE/SIZE: n/a.

---

**TDS-32 — VERDICT: open** (≡ PUR-23)
EVIDENCE: `grep -c tds` over `apps/api/routers/debit_notes.py` and `apps/api/routers/purchase_credit_notes.py` → **0** in each. `services/tds_return_service.py:46-50` still states it as a known simplification. `services/tds_register_service.py:142` `sync_for_bill(…)` keyed on `purchase_bill_id` (`:261`, `on_conflict="purchase_bill_id"` at `:305`), with a payment counterpart at `:331` and no note counterpart. The 26Q builder reads bills and advances only (`tds_return_service.py:38-44`).
PREMISE: TRUE, unchanged.
FIX: sound in saying the policy is the hard part. Three blockers it does not name. (1) A note reversal is not just a register edit — `services/vendor_tds.py` computes the FY aggregate from posted documents (`:177` `.neq("status","cancelled")`, `:681` the `_IN_THE_BOOKS` filter), so reducing a bill's value has to reduce `fy_prior_taxable_paise` too or later bills re-cross the threshold on a base that no longer exists. (2) It must NOT reduce `fy_prior_tds_paise` for tax already deposited — `resolve_tds` floors at zero for exactly this (`tds_computer.py:467-471`), and the machinery for the analogous case is already written and commented at `vendor_tds.py:221-234` (an absorbed advance that later goes away puts the sum back in the base and the next bill re-charges it). Follow that shape rather than inventing a second one. (3) A quarter already filed cannot be silently restated — the correction is a revised statement, which does not exist (TDS-16), so the honest first version is a **reported adjustment** the CA carries, not a rewrite. Sequence TDS-16's correction half before, or accept that.
SHAPE: `services/tds_register_service.py` (a note counterpart), `routers/debit_notes.py` + `routers/purchase_credit_notes.py`, `services/tds_return_service.py`. A migration only if the register row gains a note reference. SIZE: multi-day, and it is a policy decision first.

---

## 1. Duplicates across subsystems

| Pair | Which half each carries |
|---|---|
| **TDS-01 ≡ PUR-01** — *not previously named* | Same defect, same `section_rates.py:110-149` / `tds_computer.py:305-310` evidence, same worked example. PUR-01 frames it from the purchase-bill path, TDS-01 from the registry. **Both closed by the same change** — resolve one, close two. |
| **TDS-13 ≡ PUR-07** (known) | TDS-13 carries the §197-certificate half *plus* `vendors.tds_rate_bps` being captured-and-ignored; PUR-07 carries the certificate half alone. Both closed by `migrations/359` + `domain/tds/lower_deduction.py`. |
| **TDS-32 ≡ PUR-23** (known) | TDS-32 carries the 26Q half (`tds_return_service.py:46-50`); PUR-23 carries the `tds_deductions` register half (`routers/debit_notes.py`, `routers/purchase_credit_notes.py` never call `sync_for_bill`). Both open, one fix. |

No other TDS id is referenced from another findings file (checked all eight subsystem JSONs).

---

## 2. Defects with no finding

1. **A bill dated in any FY before 2025-26 is withheld at FY 2025-26's post-Finance-Act-2025 thresholds, silently, and the direction is UNDER-deduction.** `section_rates.py:324-327` holds only `2025-26` and `2026-27`; `tds_rates_for` at `:368-374` falls back to `LATEST_VERIFIED_TDS_FY` for **any** unknown year, past as well as future. `services/vendor_tds.py:367,375` passes the bill's own `event_fy`. Run in this session: `resolve_tds('194J', 40_000_00, fy='2024-25')` → `applies=False, tds=0`, where FY 2024-25's threshold was ₹30,000 and ₹4,000 was due; `resolve_tds('194H', 18_000_00, fy='2024-25')` → 0. Nothing warns: the resident path has no equivalent of `section_195_rates.rates_are_verified` (`:290-301`), which `tds_register_service.py:225,399` uses to raise a gap on the §195 side. Under-deduction disallows the whole expenditure under §40(a)(ia), and the module docstring at `section_rates.py:52-56` claims the modelling is conservative.
2. **`/tds/returns` fabricates a TAN and a deductor PAN and saves the return under them.** `apps/web/app/tds/returns/page.tsx:145` `const tan = "MUMB00000A"; // placeholder — must be configured per client`, `:152` `deductor_pan: "AAAAA0000A"`, `:153` `deductor_address: "Address not configured"`. `tds_computer._validate_26q` (`:489-492`) only checks `len(...) != 10`, so both pass, the payload validates clean, and `saveTDSReturn` (`lib/data/tds.ts:446-467`) persists it to `tds_returns` as `status: "prepared"`. This is adjacent to TDS-28 but materially worse — TDS-28 is "the CA re-types it", this is "the CA never sees it".
3. **`test_every_registry_section_resolves_to_a_fileable_statement` cannot fail.** `apps/api/tests/test_a_section_the_engine_cannot_answer_for_is_refused.py:87-96` loops `for section in sorted(_vendor_eligible(fy))` but the body calls `return_type_for(residency)` — whose signature is `return_type_for(residential_status)` (`domain/tds/residency.py:246`) and which never sees `section`. The assertion is identical for every registry key, so the guard its docstring describes ("A section the engine can rate but cannot FILE is the trap that adding s.194IA would spring") does not exist. The trap is caught only incidentally, by the hardcoded list at `:103` and by `:113-120`.
4. **The `/tds` CSV importer requires three columns it discards.** `apps/web/app/tds/page.tsx:39,41,42` make `tds_rate`, `fy` and `quarter` `required: true`; the import body at `:1006-1014` sends only `client_id, deductee_name, deductee_pan, section, payment_amount_paise, transaction_date, challan_no`, and `createTdsDeduction`'s signature (`lib/data/tds.ts:236-246`) has no field for any of the three. The backend derives the rate from the engine and the FY/quarter from `transaction_date`. A CA who types a quarter different from the one the date implies gets the date's, with nothing said.

---

## 3. Stale rate for the slice

**14 of 32 closed, 1 partial, 17 open — 44% fully closed, 47% touched.**

| | ids |
|---|---|
| **closed (14)** | TDS-01, 02, 03, 04, 05, 06, 07, 09, 11, 13, 14, 15, 26, 31 |
| **partial (1)** | TDS-22 |
| **open (17)** | TDS-08, 10, 12, 16, 17, 18, 19, 20, 21, 23, 24, 25, 27, 28, 29, 30, 32 |

The shape of the delta is clean: **every critical and every high on the compute path is closed** (TDS-01/02 the engine, 03/04/05/11/14/15 the pipeline and the screens, 06/09/13 the Phase 11b/11c work), and what remains is one cluster of *emission* defects (17, 18, 29 — the payload names the right form and the wrong section, writes a display name into a routing column, and reports everything as deposited), one cluster of *absent features* (08, 10, 12, 16, 23, 25, 27, 28, 30, 32), and the 26AS trio (19, 20, 21), which sits in `domain/income_tax/` and has not been touched by any TDS tranche.

Two of the 17 have a suggested fix I would not apply as written — **TDS-23** (adding 194IA/194IB/194M to the registry converts a visible 422 into a mis-routed 26Q row, against two pinning tests and a documented refusal) and **TDS-19** (filtering "A2/F" together drops a genuine §194-IA credit the client is owed) — and one, **TDS-22**, has the right shape with clause codes that no portal accepts, while the correct codes are sitting in `ITR6_2026_Main_V1.0.json` in this repo.
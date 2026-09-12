Verified all 34 against `92392e2c` (HEAD). Note the material fact the task brief did not have: commit **`c3c63c35` "Phase 13 — the verification pass"** landed after the 11 September pass and closed IT-08, IT-26 and half of IT-32; and `dba0996f` / `ac7fe5b5` / `714c1c84` closed IT-01, IT-05(part), IT-06, IT-09(most), IT-10(part), IT-12, IT-13(part), IT-16(part), IT-17(part), IT-18.

---

**IT-01 — VERDICT: closed**
EVIDENCE: `apps/api/domain/income_tax/assessee.py:1-116` (`assessee_kind_for_entity_type`; proprietorship→individual, trust/society refused by name); `apps/api/domain/income_tax/itr_engine.py:537` `if req.assessee_kind in ("firm","llp","domestic_company"): return self._compute_entity(req)`; `itr_engine.py:1026-1191` `_compute_entity` (flat rate, no §16(ia), no §87A, then `compute_mat`/`compute_amt` at `:1150`/`:1156` and `apply_minimum_tax` at `:1169`); `apps/api/routers/income_tax.py:131-133` `entity_type`/`assessee_kind` on `ComputeITRRequest`, resolved at `:241-254`; `GET /api/income-tax/assessee-kind` at `:435`; screen wires it at `apps/web/app/clients/[id]/tax/computation/page.tsx:293-306, 424-429`.
Probe: `assessee_kind='domestic_company'`, business ₹1cr, book profit ₹2cr → rate 30%, tax ₹33,38,400, `115JB` applied, credit ₹2,18,400. `firm` ₹50L → 30%, ₹15,60,000, `115JC`.
PREMISE: FALSE of current code. Every clause of the evidence (no entity field, dead `compute_entity_tax`/`compute_mat`/`compute_amt`) is now wrong.
FIX: sound and implemented, and implemented better than asked — the mapping is server-side statutory knowledge rather than a screen enum, and an unmapped/absent entity type REFUSES rather than defaulting to individual. One deliberate residual the fix did not promise: capital gains for a non-individual are refused with a reason (`itr_engine.py:1104-1113`), not charged at the flat rate.
SHAPE: n/a. No migration.
SIZE: n/a.

---

**IT-02 — VERDICT: closed**
EVIDENCE: `itr_engine.py:603-605` `stcg = max(0, …)` / `ltcg` / `ltcg_other`, used for GTI (`:650`), taxable income (`:836`) and each special-rate line (`:875-881`); §71(3)/§74 warnings at `:983-996`; §70(2)/70(3) warning at `:1001`.
Probe: salary ₹20,00,000 → ₹1,92,400; same salary with STCG −₹5,00,000 → ₹1,92,400 (identical).
PREMISE: FALSE now.
FIX: sound as applied. The router still has no `ge=0` on the three CG fields (`routers/income_tax.py:186-188`) — deliberate: the engine floors and the loss surfaces as a named warning instead of a 422.
SHAPE: n/a.
SIZE: n/a.

---

**IT-03 — VERDICT: closed**
EVIDENCE: `itr_engine.py:127-142` (`LIMIT_80G_QUALIFYING_PERCENT`, `LIMIT_80G_CASH_PAISE`); §80G computed last on `adjusted_gti = max(0, ordinary_income - head_reliefs - deductions)` at `:818-822`; `Donation80GInput.subject_to_qualifying_limit` / `paid_in_cash` at `routers/income_tax.py:67-85`.
Probe: ₹9,00,000 donation at 50% on ₹10,00,000 salary → `deduction_80g_paise` ₹47,500.
PREMISE: FALSE now.
FIX: sound. §80G's four categories are carried as the product of two facts, defaulting to "subject to the limit" — matches CLAUDE.md exactly.
SHAPE: n/a.
SIZE: n/a.

---

**IT-04 — VERDICT: closed** (with a named residual in a second module)
EVIDENCE: `capital_gains_engine.py:333` `pre_2024 = sale_date < FINANCE_NO2_ACT_2024`, driving rate, §112A exemption and §2(42A) thresholds (`:206-236`, `:343-451`).
Probe: equity bought 10-Jan-2024 sold 10-Jun-2024, ₹10L→₹15L → 15.0%, ₹75,000, "Section 111A".
PREMISE: FALSE of `capital_gains_engine`. Still TRUE of `itr_engine`, which reads CG rates off `FYTaxRates` (one set per FY, `itr_engine.py:875-881`), so a FY 2024-25 return computed through `/compute` gets post-fork rates. Mitigated two ways: `GET /api/income-tax/financial-years` (`routers/income_tax.py:406-432`) now serves only the years the registry holds (2025-26, 2026-27) and the client screen reads it (`computation/page.tsx:315`); and `_stamp_rate_provenance` (`itr_engine.py:490-521`) sets `rates_verified=False` with a named warning when a substitute year is used.
FIX: **sound for `capital_gains_engine`, UNSOUND if extended to `statutory_rates`.** The obvious next step — "add FY 2024-25 to `RATES_BY_FY`" — cannot be done: 2024-25 straddles 23-07-2024 and one `FYTaxRates` cannot hold two CG rate sets (CLAUDE.md says exactly this). Adding it would put post-fork rates on the whole year under a `verified=True` flag, which is worse than today's refusal-by-omission. If IT-04 is ever "completed", `FYTaxRates` needs pre/post CG buckets first.
SHAPE: `domain/income_tax/statutory_rates.py` only, and only with the bucket split. No migration.
SIZE: multi-day (if attempted at all).

---

**IT-05 — VERDICT: partial**
EVIDENCE: the payload now carries house property, all three CG heads, exempt income, senior flags, §80C, §80D, §80TTA, §24(b), other deductions, brought-forward losses and the entity fields — `computation/page.tsx:376-431`. Still absent from that screen: **HRA/§10(13A), §80G donations, §80CCD(1B), §80CCD(2)/`is_government_employee`, `is_resident`** — `grep -n "hra\|donation\|80g\|nps_80ccd\|is_resident" computation/page.tsx` returns nothing. The planner still writes elsewhere: `apps/web/app/income-tax/deductions/page.tsx:29,346` `saveTaxPlanningRecord`, with no `/api/itr/snapshots` call.
PREMISE: mostly FALSE now — "five figures" is wrong; the five named residuals stand. For an old-regime salaried individual paying rent, the HRA gap alone is the largest remaining understatement of relief on that screen.
FIX: first half sound and done. **Second half ("make the deductions planner write into the same snapshot") is questionable**: that planner is a firm-level two-regime what-if with its own client picker; letting it write the versioned snapshot the filing demo and filing workflow read would let a scenario overwrite the computation of record. The safer shape is an explicit "copy into client snapshot" action, or — as was actually done — move the fields onto the client screen.
SHAPE: `computation/page.tsx` (add HRA/§80G/§80CCD blocks; `ComputeITRRequest` already accepts all of them). No migration, no backend change.
SIZE: day.

---

**IT-06 — VERDICT: closed**
EVIDENCE: `routers/income_tax.py:713-722` `is_presumptive_44ad_44ada` on `ComputeAdvanceTaxRequest`; `:733-738` passed to `compute_234c_interest`; `:781-783` `section_ref` reports "Section 234C(1)(b)" vs "(1)(a)"; screen sends it at `apps/web/app/income-tax/advance-tax/page.tsx:140,165` and renders one instalment at `:274` `(presumptive ? [4] : [1,2,3,4])`. Test: `tests/test_a_presumptive_assessee_has_one_instalment.py`.
PREMISE: FALSE now.
FIX: sound; supplied as a flag rather than inferred, which is right — no figure the endpoint receives decides whether §44AD is opted into.
SHAPE: n/a.
SIZE: n/a.

---

**IT-07 — VERDICT: open (still latent)**
EVIDENCE: `minimum_tax.py:225-227` — `apply_surcharge_with_marginal_relief(base, tax, entity.firm_surcharge, None, …)` for **every** non-corporate assessee; `entity_rates.py:85` `firm_surcharge=(SurchargeBracket(above_paise=1*CRORE_PAISE, rate_percent=12),)`; the individual ladder lives at `statutory_rates.py` and is never read here.
Reachability changed but not for this defect: `compute_amt` now has one non-test caller, `itr_engine.py:1156`, and it is entered only from `_compute_entity`, i.e. only with `assessee_kind` ∈ {`firm`,`llp`} (`itr_engine.py:537`, `:1138`). For those two, `firm_surcharge` is the correct bracket. Individual/HUF/AOP/BOI/AJP still cannot reach `compute_amt`.
PREMISE: TRUE of the code, FALSE of the consequence ("the return under-reports the minimum tax") — no CA can produce it.
FIX: sound. **Ordering caveat the finding does not mention: fix IT-21 first.** Once §115JC(5) carves out a §115BAC assessee, the "25% new-regime cap" limb of IT-07's fix becomes unreachable for an individual and should not be written.
SHAPE: `domain/income_tax/minimum_tax.py` only; `tests/test_minimum_tax.py` pins only the company and firm cases (`:36-39`, `:72-77`), so nothing breaks. No migration.
SIZE: hours.

---

**IT-08 — VERDICT: closed**
EVIDENCE: `itr_engine.py:857-881` calls `_absorb_basic_exemption` (`:1226-1300`) before each special-rate line; nil band read off the slabs at `_basic_exemption_paise` (`:1201-1224`); gated on `assessee_kind == "individual" and is_resident` (`:1258`); allocated highest-resolved-rate first (`:1266`); applied **once** across the three buckets. `is_resident` added at `itr_engine.py:388` and `routers/income_tax.py:145`. Guard: `tests/test_the_six_numbers_a_user_sees_today.py:45-168` (nine cases including "absorbed once, not three times", firm, non-resident, senior old regime).
Probe: STCG-only ₹5,00,000 new regime → **₹20,800** (was ₹1,04,000), `basic_exemption_absorbed_paise` ₹4,00,000. §112A-only ₹5,00,000 → ₹0. §112-other-only ₹5,00,000 → ₹13,000.
PREMISE: FALSE now. The 11 September escalation is resolved.
FIX: sound and superset of what was suggested. Two residuals, neither in the finding: (a) `basic_exemption_absorbed_paise` / `basic_exemption_absorption` are computed and **never leave the engine** — see §2 below; (b) `is_resident` defaults True and no screen collects it, so a non-resident individual is silently granted an absorption the provisos do not reach — documented at `itr_engine.py:375-388`, and `clients` has no residence column.
SHAPE: n/a.
SIZE: n/a.

---

**IT-09 — VERDICT: partial** (≡ FA-06)
EVIDENCE: `domain/income_tax/section_32.py` (329 lines) exists — blocks, §43(6)(c) WDV, the 180-day half-rate (`:85` `HALF_RATE_DAYS = 180`, `:88` `half_rate_cutoff`, `:191-202` a not-yet-put-to-use addition gets **nothing**, not half), §32(1)(iia) additional depreciation (`:112`, `:156`), §50 short-term gain (`:159`). Persistence: migration `357_a_block_of_assets_is_not_the_register.sql` + `services/section_32_service.py`. Endpoints: `GET /api/income-tax/section-32` (`routers/income_tax.py:1231`), `PUT /section-32/blocks` (`:1265`), `POST /book-to-tax-bridge` (`:1309`) which **reads** §32 from the register rather than taking it from the caller (`:1329-1345`). Screen: `apps/web/app/income-tax/section-32/page.tsx` (`:99`, `:322`), linked at `income-tax/page.tsx:819`, guarded by `apps/web/scripts/section-32-is-computed-on-the-server.test.ts`.
Still open: **the bridge has no screen.** `grep -rn "book-to-tax-bridge" apps/web` → nothing; `/api/income-tax` sits inside the 6-path unreachable budget at `tests/test_every_mounted_endpoint_has_a_way_in.py:74`.
PREMISE: mostly FALSE. "§32 is implemented nowhere" is wrong; "the bridge is exposed behind no screen" is now the only true half.
FIX: sound and done, including the "keep the refusal for any block a human has not classified" clause (`section_32.py:47-60` — no rate table held; the block IS the rate under §2(11)).
SHAPE: one screen in `apps/web/app/income-tax/` calling the existing endpoint. No migration.
SIZE: day.

---

**IT-10 — VERDICT: partial**
EVIDENCE: closed half — `ITRComputeRequest.brought_forward_losses` (`itr_engine.py:337`), applied at `:611-640` through `domain/income_tax/loss_set_off.py` (§72/§73/§71B/§74, long-term before short-term, expiry honoured at `:122-135`); `BroughtForwardLossInput` with a `loss_type` validator at `routers/income_tax.py:94-118`; the screen sends `remaining_amount_paise` (`computation/page.tsx:413-420`) and renders the per-loss working (`:893-905`); test `tests/test_a_brought_forward_loss_reaches_only_its_own_head.py`.
Open half — no CRUD screen (`grep -rn "bf-losses" apps/web` → nothing; `POST /api/itr/bf-losses` and `/bf-losses/{id}/utilize` are called from nowhere) and no write-back: the only `/api/itr/` calls from the web are `snapshots`, `disallowances`, `filings`, `filings/{id}/transition`, `filings/{id}/acknowledge`.
PREMISE: half FALSE. "the computed tax is identical whether or not a loss exists" is no longer true; "there is no button to record one" still is.
FIX: mostly sound. **One clause is unsafe as written: "write the utilisation back through `utilize_bf_loss` when a snapshot is saved."** A snapshot is a versioned what-if (`tax_computation_snapshots` UNIQUE on `(firm,client,fy,version)`, migration 319:121) and the screen saves one on every compute; writing the loss down there would consume the loss on drafts that are never filed and would double-consume across versions. Write back on the **filing** transition instead.
SHAPE: a CRUD screen + `routers/itr_workspace.py` unchanged; the write-back belongs in `itr_workflow.transition_itr_status`. No migration.
SIZE: multi-day.

---

**IT-11 — VERDICT: open**
EVIDENCE: `apps/web/app/income-tax/tax-audit/page.tsx:217-221` — the message is still `turnoverPreviewPaise >= THRESHOLD_BUSINESS ? "✓ Exceeds ₹1 crore — tax audit mandatory (business)" : >= THRESHOLD_PROFESSION ? "✓ Exceeds ₹50 lakh — tax audit mandatory (profession)" : …`, decided by amount alone; `apps/web/lib/income-tax/taxAuditThresholds.ts:4-12` still records the ₹10 crore / ₹75 lakh cash tests as "not modeled here". No backend applicability engine: `grep -rn "44AB" apps/api/routers apps/api/services apps/api/domain` returns only the two due-date functions and prose. No Form 3CD anywhere.
PREMISE: TRUE, unchanged.
FIX: sound. **Blocker the finding does not name:** the first proviso to §44AB(a) turns on cash receipts and cash payments each ≤5% of the total, and no client record holds those percentages — so the backend answer has to be a *refusal with a named gap*, the shape `compliance_obligation_service.itr_due_date_for_client` already uses, not a computed yes/no. The business-vs-profession fact is likewise not on `clients`.
SHAPE: new `apps/api/routers` endpoint + `services/compliance_*`; the 3CD clause workspace needs a migration.
SIZE: multi-day for the applicability answer; months for 3CD.

---

**IT-12 — VERDICT: closed**
EVIDENCE: `services/compliance_engine.py:235` `tax_audit_report_due_date(financial_year_end)`, derived from `itr_due_date`; `GET /api/compliance/tax-audit-due-dates` at `routers/compliance.py:325-370`; `apps/web/lib/api/index.ts:1325-1327` `taxAuditDueDates`; the page fetches it at `tax-audit/page.tsx:307-316` and renders `Report due … · return due …` at `:328-333`, with `| due dates unavailable` on failure rather than a guess.
PREMISE: FALSE now, in both surfaces.
FIX: sound and done; the hardcoded string was replaced by a call rather than by a second hardcoded date, which is the right shape.
SHAPE: n/a.
SIZE: n/a.

---

**IT-13 — VERDICT: partial**
EVIDENCE: closed half — `POST /api/income-tax/interest/234ab` at `routers/income_tax.py:861-880+`, deriving the §139(1) date from `itr_due_date_for_client` rather than accepting it, and returning both sections separately; tests at `tests/test_the_income_tax_engines_are_reachable.py:44-130`.
Open half — **no screen**: `grep -rn "234ab" apps/web` → nothing; the advance-tax page shows only §234C. And `net_payable_paise` still carries no interest of any section: `itr_engine.py:936` and `:1190` are both `total_tax_paise - tds_and_advance_paise`. There is still no self-assessment-tax input to the computation.
PREMISE: half FALSE (the endpoint exists), half TRUE (no CA reaches it, and the payable figure is still interest-free).
FIX: sound. **Blocker the finding does not mention:** surfacing an interest block beside a `net_payable` that excludes it puts two numbers on one screen that do not add up. Either fold the three into net payable or label it explicitly as "before interest".
SHAPE: `computation/page.tsx` (or the advance-tax page) + a `self_assessment_tax_paise` field on `ComputeITRRequest`. No migration.
SIZE: day.

---

**IT-14 — VERDICT: closed**
EVIDENCE: `capital_gains_engine.py:206-236` thresholds by transfer date; classification is `sale_date > _add_months(purchase_date, threshold)`; tests pin day precision at `tests/test_capital_gains_engine.py:103-118` (`2024-01-01 → 2025-01-01` False, `→ 2025-01-02` True).
Probe: equity 15-Jan-2024 → 05-Jan-2025 → months 11, `is_long_term` False, 20.0%, "Section 111A".
PREMISE: FALSE now.
FIX: sound and done, including §2(42A)'s "day immediately preceding".
SHAPE: n/a.
SIZE: n/a.

---

**IT-15 — VERDICT: closed**
EVIDENCE: `apps/web/app/income-tax/page.tsx:115-120` `fyFromPeriodStart`, FY-labelled throughout; the due date comes from `GET /api/compliance/itr-due-date`; `AY_PERIOD`/`DUE_DATE_AUDIT`/`DUE_DATE_NON_AUDIT`/`getAYFromDates` survive only inside a comment.
PREMISE: FALSE now.
FIX: sound and done — both writers of a `compliance_calendar` ITR row route through `itr_due_date_for_client`, so they can no longer disagree by a year.
SHAPE: n/a.
SIZE: n/a.

---

**IT-16 — VERDICT: partial**
EVIDENCE: closed half — `POST /api/income-tax/presumptive/44ad|44ada|44ae` at `routers/income_tax.py:966,982,997`; `presumptive_income_paise` on `ComputeITRRequest` at `:229`, honoured at `itr_engine.py:588-596` (it REPLACES business income and disallowances, correctly, per §44AD(2)/§44ADA(3)/§44AE(6)); tests at `tests/test_the_income_tax_engines_are_reachable.py:133-176, 244-266`.
Open half — **no screen**: `grep -rn "presumptive\|44ad\|44ada\|44ae" apps/web/app apps/web/lib` returns only the advance-tax checkbox (IT-06) and one ITR-4 dropdown label. The client computation screen sends no `presumptive_income_paise`.
PREMISE: half FALSE, half TRUE.
FIX: sound; the "it also unlocks the §234C fix in IT-06" clause turned out to be unnecessary — IT-06 was fixed independently with its own flag.
SHAPE: a scheme picker on `computation/page.tsx` calling the three endpoints and feeding `presumptive_income_paise`. No migration.
SIZE: day.

---

**IT-17 — VERDICT: partial**
EVIDENCE: closed half — `POST /api/income-tax/itr/field-placements` at `routers/income_tax.py:1059-1105`, validating the form against all seven (`_ITR_FORMS`, `:1029`), rounding to rupees at the statutory boundary, and **deliberately not** exposing `generate_itr_json` (`:1024-1027`).
Open half — no screen (`grep -rn "placements" apps/web` → nothing) and the payload is still fourteen figures: `grep -c "PayloadValue(" domain/income_tax/itr_json.py` → **14**; no Schedule CG/HP/BP/CFL/AL/FA/FSI/TR.
PREMISE: half FALSE (the endpoint exists), half TRUE (no keying sheet, fourteen figures).
FIX: sound. **Caveat:** "extend `ITRPayload` head by head" is the exact operation CLAUDE.md records going wrong once — an ITR-5/ITR-6 path that resolved to `TaxPayableOnDeemedTI` (the MAT branch) instead of `TaxPayableOnTI` and validated perfectly. Every new path must be added with a `tests/test_itr_schema_paths.py` case against the committed schema, in the same commit.
SHAPE: a printable sheet in `apps/web`; `itr_json.py` + `tests/test_itr_schema_paths.py` together for the schedules. No migration.
SIZE: day for the sheet; multi-day per schedule.

---

**IT-18 — VERDICT: closed**
EVIDENCE: migration `352_the_ais_reconciliation_survives_a_refresh.sql` (three tables: upload / record / reconciliation, with `books_amount_paise` nullable and `status` defaulting to `not_reviewed` — a row nobody has looked at must not read as agreed); `apps/api/routers/ais.py:27` `prefix="/api/ais"` with seven routes, mounted at `apps/api/main.py:346`; the screen now calls them (`apps/web/app/income-tax/ais/page.tsx:114,126,160,187,213,234`). The fabricated figure is gone: `domain/document_intelligence_service.py:528-551` removes the `total_income * 0.85` invention and explains why.
PREMISE: FALSE now.
FIX: sound, and it took the 26AS shape as suggested. Two residuals: the `"AIS shows income ₹8.5L vs books ₹7.3L"` strings survive in `MOCK_RISKS` (`domain/risk_engine.py:65`), `ai_insight_service.py:70` and `notification_service.py:136` — mock-mode demo rows against invented client ids (`c-003 Mehta Consulting`), so they cannot be read as a real client's figures; and **TIS is still absent entirely**, which the finding mentioned but the suggested fix did not ask for.
SHAPE: n/a.
SIZE: n/a.

---

**IT-19 — VERDICT: open**
EVIDENCE: `grep -rni "54F|54EC|section 54\b|55\(2\)\(ac\)|31-01-2018|fmv_31|grandfathered cost" --include=*.py apps/api/domain/income_tax apps/api/routers/income_tax.py apps/api/services` → **zero hits**. `compute_capital_gains` still takes seven inputs (`capital_gains_engine.py:317-324`) with no exemption or FMV parameter; the register has no exemption column (`migrations/030_supplier_tds_and_credit.sql:29-44`). The page header still claims a capability it does not have: `apps/web/app/income-tax/capital-gains/page.tsx:9` `* Section 54: Exemptions`.
PREMISE: TRUE, unchanged.
FIX: sound in outline, incomplete in two ways the finding does not say. (a) **The 31-01-2018 FMV is per-scrip data nobody holds** — it is a human-supplied figure like the ITR schemas, and the code must REFUSE rather than default: defaulting to cost over-taxes by the whole pre-2018 appreciation, defaulting to sale value under-taxes. (b) "records the lock-in for a later year's reversal" is a **new table and therefore a migration**, plus a §54F(2)/§54(2) reversal path in a later year that nothing in the product currently walks. Neither the CGAS deposit nor the lock-in has anywhere to live today.
SHAPE: `capital_gains_engine.py`, `routers/income_tax.py`, `apps/web/app/income-tax/capital-gains/page.tsx`, **plus a migration** for the exemption/lock-in columns.
SIZE: multi-day (the finding's "weeks" is right for the whole of §54/54F/54EC/54B; §55(2)(ac) alone is a day).

---

**IT-20 — VERDICT: open (deliberately, and now visible)**
EVIDENCE: `itr_engine.py:61-62` `LIMIT_80CCD2_GOVT_PERCENT = 14` / `LIMIT_80CCD2_OTHER_PERCENT = 10`, applied with no regime branch at `:677-682`; the docstring at `:42-60` records the doubt. What changed in `c3c63c35` is a warning fired only where the choice bites — non-government, new regime, contribution above 10% (`itr_engine.py:684-711`).
Probe: new regime, non-government, salary base ₹10,00,000, employer NPS ₹1,40,000 → deduction ₹1,00,000, plus a warning naming the amount at stake.
PREMISE: TRUE. **The task brief's PAY-22 caution is confirmed:** `c3c63c35` fixed the §80CCD(2) *base* (gross → basic+DA) and left the *rate* at 10%. They are the same computation and are separate defects.
FIX: **sound in law, but not executable inside this environment as written.** The fix says "after confirming against the Finance (No. 2) Act 2024 text" — egress is refused at the proxy, so confirmation is an out-of-band human step; writing 14% from memory is exactly what CLAUDE.md forbids. Two further consequences the finding does not mention: the change must edit `tests/test_the_six_numbers_a_user_sees_today.py:333` (`test_the_two_percentages_are_still_the_constants_the_docstring_argues_for`), which exists precisely so the edit is deliberate; and the same constant flows into payroll §192 withholding via `domain/payroll/declarations.py`, so a wrong reading **under-withholds** on an obligation §192(1) makes the employer answerable for.
SHAPE: `itr_engine.py` (two constants + a regime branch) and one test. No migration.
SIZE: hours, gated on a verified source.

---

**IT-21 — VERDICT: open (still latent)**
EVIDENCE: `grep -n "115BAC" domain/income_tax/minimum_tax.py` → no match; `compute_amt` (`:177-181`) has no regime parameter; the only regime gate in the file is the company's §115BAA/§115BAB at `:152`. Reachable only for `firm`/`llp` (`itr_engine.py:1138,1156`), neither of which can exercise §115BAC or §115BAD, so nothing wrong is charged today.
PREMISE: TRUE of the code, and the "nobody sees it yet" caveat still holds for a different reason than in September (the module now has a caller, but only for assessees the carve-out does not reach).
FIX: sound, and the finding's own instruction to verify the sub-section number before writing the citation is the right instinct. **Do it before IT-07** — see that entry.
SHAPE: `domain/income_tax/minimum_tax.py`, plus a `regime` argument threaded from `itr_engine._compute_entity`. No migration.
SIZE: hours.

---

**IT-22 — VERDICT: closed**
EVIDENCE: `capital_gains_engine.py:184-204` `ASSESSEE_TYPES` / `ASSESSEE_UNSPECIFIED`; the fifth-proviso branch is gated on both the acquisition date and a resident individual/HUF; `routers/income_tax.py` carries a validated `assessee_type` and the screen collects it.
Probe: property bought 01-Sep-2024, sold 2027, `assessee_type='resident_individual_huf'` → `tax_with_indexation_percent` **None** (option correctly withheld).
PREMISE: FALSE now.
FIX: sound and done, and it withholds-and-explains rather than granting by default — exactly the direction CLAUDE.md requires for the fifth proviso.
SHAPE: n/a.
SIZE: n/a.

---

**IT-23 — VERDICT: open**
EVIDENCE: `apps/web/app/clients/[id]/tax/filing/page.tsx:43` still `const ITR_FORMS = ["ITR-3","ITR-5","ITR-6","ITR-7"];`, rendered at `:254`. `itr_workflow.py:23-28` `"filed": []` terminal; `record_filing_acknowledgement` (`:215-241`) writes `"status": "filed"` in both branches with no read of the current status. `grep -rni "139(8A)|139(5)|return_type|revised return|updated return" --include=*.py apps/api/domain/income_tax apps/api/routers/itr_workspace.py` → nothing.
PREMISE: TRUE in all three limbs.
FIX: sound, but **needs a migration the finding does not mention**: `migrations/319_declare_the_guards_production_enforces.sql:111` records `itr_filings_firm_id_client_id_financial_year_itr_form_key UNIQUE (firm_id, client_id, financial_year, itr_form)` as live in production — a §139(5) revised return cannot be stored beside the original until that key includes `return_type`. Everything else (a `Literal` of seven forms, `status == 'ready_for_filing'` on acknowledge, typing `assessment_year`) is a code-only change.
SHAPE: `routers/itr_workspace.py`, `domain/income_tax/itr_workflow.py`, `filing/page.tsx`, **plus a migration** replacing the unique key.
SIZE: multi-day.

---

**IT-24 — VERDICT: open**
EVIDENCE: `domain/income_tax/form26as_service.py:85` `"parse_errors": []` — never written anywhere else in the file; `:180-181` `except (ValueError, IndexError): _logger.debug("Skipping unparseable line: %s", …)`; `:164-166` `cols = re.split(r"\t|\|", line)` with `if len(cols) < 5: continue`; `parse_status` set to `"parsed"` unconditionally at `:253` (mock) and `:275` (Supabase), regardless of `len(records)`. Screen: `apps/web/app/clients/[id]/tax/26as/page.tsx:421-426` shows a green tick and the word `parsed`.
PREMISE: TRUE, unchanged.
FIX: sound. **Two things it does not say.** (a) It is the same function as **TDS-20** and must be done with it — refusing on zero records while the parser still only accepts tab/pipe would turn a silent zero into an outright refusal for every real TRACES download, which is a regression in usability even though it is honest. (b) `parse_errors` is a column on `form_26as_uploads` already, so no migration is needed for the errors themselves; check the column type before writing structured rows into it.
SHAPE: `domain/income_tax/form26as_service.py` + `apps/web/app/clients/[id]/tax/26as/page.tsx`. No migration.
SIZE: day (with TDS-20: multi-day).

---

**IT-25 — VERDICT: closed**
EVIDENCE: `services/compliance_obligation_service.itr_due_date_for_client` decides on Explanation 2's three settleable facts and REFUSES otherwise with the earlier date plus a named gap; both writers of an ITR row route through it; `AUDIT_ENTITY_TYPES`/`isAuditCase` are gone from `apps/web/app/income-tax/page.tsx` (comment only) and the page calls `GET /api/compliance/itr-due-date`.
PREMISE: FALSE now.
FIX: sound and done, and the implementation is the CLAUDE.md-sanctioned decided/refused split rather than the finding's "take the audit flag from the `tax_audits` row" — which would have been weaker, since a missing row is not evidence of no audit.
SHAPE: n/a.
SIZE: n/a.

---

**IT-26 — VERDICT: closed**
EVIDENCE: `itr_engine.py:660-673` splits one accumulator into `deductions` (Chapter VI-A) and `head_reliefs`; HRA at `:735-742` and §24(b) at `:744-751` go to `head_reliefs`; `:828-829` `result.gross_total_income_paise = gti - head_reliefs` / `result.total_deductions_paise = deductions`; `:836` taxable income is computed on `head_reliefs + deductions`, so no tax figure moves. Guard: `tests/test_the_six_numbers_a_user_sees_today.py:170-199`, including `test_the_tax_does_not_move_because_this_splits_a_presentation`.
Probe: salary ₹10,00,000 old regime with a ₹2,50,000 HRA exemption → GTI ₹7,00,000 (was ₹9,50,000), `total_deductions` ₹0 (was ₹2,50,000), taxable ₹7,00,000 (unchanged).
PREMISE: FALSE now.
FIX: sound and done exactly as suggested, with a no-tax-movement control test.
SHAPE: n/a.
SIZE: n/a.

---

**IT-27 — VERDICT: open**
EVIDENCE: `grep -rn "regime_election|evaluate_election" apps/api/routers apps/api/services apps/web` → **zero hits**. The only 10-IEA references in the product are the payroll withholding-intimation path (`routers/payroll.py:5659,5813`), a comment in `compliance_engine.py:223`, and `apps/web/lib/api/index.ts:597,2417`. The client screen's regime control is still a two-option select (`computation/page.tsx:27-31` label map; company gets §115BAA/§115BAB instead at `:609-611`).
PREMISE: TRUE, unchanged. One nuance: the company half of the dropdown was fixed (a firm no longer reads "Old Regime"), which is IT-01's work, not IT-27's.
FIX: sound. **Caveat CLAUDE.md makes explicit and the finding does not:** the §115BAC(6) election and the Circular 04/2023 withholding intimation are three separate things with the Rule 26C Form 12BB statement, and `domain/payroll/declarations.py` keeps them apart — the fix must not set the election from the payroll intimation, or vice versa. Storing the 10-IEA acknowledgement and prior elections is a **migration**.
SHAPE: new endpoint in `routers/income_tax.py`, `computation/page.tsx`, **plus a migration** for the election history.
SIZE: multi-day.

---

**IT-28 — VERDICT: partial**
EVIDENCE: closed limb — `capital_gains_engine.py:408` `if asset_type in _DEBT_MF_LIKE and purchase_date >= SECTION_50AA_FROM`, so a pre-01-04-2023 unit falls through to ordinary §2(42A)/§112 treatment.
Open limb — `:165-177` records it as a KNOWN GAP: `"bonds"` is treated as an unlisted other asset. Probe: `bonds` bought 01-Jan-2024, sold 01-Jul-2025 → 17 months, `is_long_term` False, 30.0%, "Section 48".
PREMISE: half FALSE, half TRUE.
FIX: sound in direction. **Two blockers it does not mention.** (a) `migrations/030_supplier_tds_and_credit.sql:34` `asset_type TEXT NOT NULL CHECK (asset_type IN ('equity_shares','mutual_funds','property','bonds','other'))` — a listed-security type cannot be persisted without a **migration**. (b) `tests/test_capital_gains_engine.py:121-126` `test_other_assets_boundary_is_twenty_four_months_from_23_jul_2024` explicitly iterates `("property","unlisted","gold","bonds","other")` at 24 months, so the test must change with the code. The current behaviour errs towards MORE tax, which is why it is survivable.
SHAPE: `capital_gains_engine.py`, `routers/income_tax.py` (`REGISTER_ASSET_TYPES`), the capital-gains screen, **plus a migration**.
SIZE: day.

---

**IT-29 — VERDICT: partial**
EVIDENCE: fixed — `capital_gains_engine.py:98-105` `CII_BY_FY` now runs to `"2026-27": 384` with `"2025-26"` corrected to 376; `:115` `LATEST_CII_FY = "2025-26"` held back deliberately; `:128` `_NEWEST_CII_FY = max(CII_BY_FY)` is the fallback anchor at `:150`.
Probe: `cii_for('2025-26')` 376, `('2026-27')` 384, `('2027-28')` 384.
Not fixed — `CapitalGainsResult` (`:290-314`) still has **no `is_estimate` field**; `_cg_response` and `create_capital_gains` still persist `result.indexed_cost_paise` unconditionally (`routers/income_tax.py:555`, `:648`).
PREMISE: **FALSE as stated** — "CII_BY_FY ends at 2025-26: 380" is wrong twice over. The mechanism half is TRUE. There is no live estimate today; it recurs on 1 April 2027.
FIX: half sound, half harmful. Flagging the estimate through `CapitalGainsResult` and the response is right. **"Refuse to PERSIST an indexed cost computed on an estimated index" is not:** the CBDT notifies the CII partway through the year (CLAUDE.md says so), so between 1 April and roughly June every year the register would refuse to record a real transfer that has already happened. Persist with the flag and re-derive, or persist and mark for re-derivation — do not refuse.
SHAPE: `capital_gains_engine.py`, `routers/income_tax.py`; a stored flag would need a **migration** on `capital_gains`.
SIZE: hours (flag only); day (with persistence).

---

**IT-30 — VERDICT: open**
EVIDENCE: `grep -rn "api/itr/" apps/web` returns exactly five paths — `snapshots`, `disallowances`, `filings`, `filings/{id}/transition`, `filings/{id}/acknowledge`. `POST /api/itr/snapshots/{id}/review` is reached from nothing, so a snapshot's status is permanently `draft`. `itr_workflow.py:44,56,73` store `computation_snapshot_id`; `transition_itr_status` (`:105-156`) records `reviewed_by`/`partner_reviewed_by` but never reads the pinned snapshot's status.
PREMISE: TRUE of the code. The verifier's downgrade to low still holds — the filing workflow's own maker-checker is enforced.
FIX: sound. **One thing it does not settle:** `computation_snapshot_id` is nullable (`itr_workflow.py:44`), so "block `ready_for_filing` unless the pinned snapshot is reviewed" has to decide what a filing with *no* snapshot does. Blocking those would break the existing flow, since no screen forces a pin.
SHAPE: `computation/page.tsx` (a Review button) + `domain/income_tax/itr_workflow.py`. No migration.
SIZE: hours.

---

**IT-31 — VERDICT: open**
EVIDENCE: `grep -rn "claimable|prefill" routers/form_26as.py domain/income_tax/form26as_service.py` → prose only (`:345`, `:460`, `:551`). The computation screen's TDS is still free text: `computation/page.tsx:189` `useState("")`, `:659` label `"TDS Deducted (₹)"`, sent raw at `:380` with no variance check. `_load_book_credits` (`form26as_service.py:341-353`) still reads only receipts rows.
PREMISE: TRUE. The verifier's correction still stands — `GET /api/form-26as/reconciliation` does return `total_tds_26as_paise` and `unsupported_credit_paise`, so "no endpoint returning claimable TDS" overstates it.
FIX: sound in shape. **The important caveat:** deriving the claimable total from the *book* side is wrong for the client it matters most to. `_load_book_credits` reads only `receipts` with `tds_paise > 0`, so a salaried client's §192 credit has no books counterpart and the claimable figure would be **nil**. The prefill must come from the 26AS side (26AS total less unsupported), with the books used only for the variance.
SHAPE: `domain/income_tax/form26as_service.py`, `routers/form_26as.py`, `computation/page.tsx`. No migration.
SIZE: day.

---

**IT-32 — VERDICT: partial**
EVIDENCE: closed limb — `S80CInput.other_paise` now exists (`routers/income_tax.py:51-58`, threaded at `:297`), so an §80C item is inside the §80CCE cap; pinned by `tests/test_the_six_numbers_a_user_sees_today.py:241-263`.
Open limbs — `other_deductions_paise` is **still uncapped**, now with a warning naming what could not be checked (`itr_engine.py:753-780`); probe: ₹5,00,000 of "other deductions" → `total_deductions` ₹5,00,000 plus the warning. And `grep -rn "80E\b|80EE|80EEA|80DD\b|80DDB|80U\b|80GG|80JJAA" --include=*.py apps/api/domain apps/api/routers` → **four hits, all inside that warning's own text**. §80D still has no ₹5,000 preventive-checkup sub-limit and no uninsured-senior medical route (`itr_engine.py:118-126`).
PREMISE: half FALSE (the `other_paise` route exists; the silence is gone), half TRUE (no sections modelled, no ceiling).
FIX: sound. Two notes: keeping `other_deductions_paise` uncapped is now a **deliberate** decision with a stated reason, so a fix must not remove it; and §80EE/§80EEA are sunset provisions closed to new loans, so modelling them needs a loan-sanction-date input rather than a flat limit. `tax_deduction_claims.section` is available as the finding says, so per-section lines need no migration.
SHAPE: `itr_engine.py`, `routers/income_tax.py`, the deductions screens. No migration.
SIZE: multi-day.

---

**IT-33 — VERDICT: open**
EVIDENCE: `apps/web/app/income-tax/page.tsx:140-145` — `ADVANCE_TAX_INSTALLMENTS` is still the literal `"15 Jun 2025" / "15 Sep 2025" / "15 Dec 2025" / "15 Mar 2026"`, rendered at `:1042`, under a heading hardcoded at `:1035` `Advance Tax Installments — FY 2025-26`. The backend derivations (`advance_tax_interest_engine.installment_schedule(fy)`, `compliance_engine.advance_tax_due_dates`) are not called from here. On today's date (12-09-2026, FY 2026-27) the hub's first panel shows four elapsed instalments under last year's title.
PREMISE: TRUE, unchanged — and the page was heavily rewritten by `46bd46c` and again by `c3c63c35` without touching this block.
FIX: sound. **One thing to get right:** the FY must come from the server (`GET /api/income-tax/financial-years` already returns `current_fy`, and `core.ist_clock.ist_fy_label` is the authority) rather than `new Date()` in the browser — CLAUDE.md's IST rule, and a browser in another zone would flip the FY on 31 March/1 April.
SHAPE: `apps/web/app/income-tax/page.tsx` only. No migration.
SIZE: hours.

---

**IT-34 — VERDICT: open**
EVIDENCE: `apps/web/app/income-tax/deductions/page.tsx:292-311` — the debounced effect still runs `Promise.all([computeITR(old), computeITR(new)])` inside `setTimeout(…, 400)` with `}, [state]);` at `:311`; the donation `description` is part of `state` (`:275-281`), as are `subjectToLimit` and `paidInCash`.
PREMISE: TRUE, unchanged.
FIX: sound and trivial — derive the request object and key the effect on it, or use an explicit Recompute action.
SHAPE: one file. No migration.
SIZE: hours.

---

## 1. Duplicates with other subsystems

| pair | which half each carries |
|---|---|
| **IT-09 ≡ FA-06** (named in the brief; confirmed) | Both are "IT Act §32 block depreciation does not exist and the bridge is dead code". Both are now largely **closed** by the same work (`section_32.py`, migration 357, `services/section_32_service.py`, the `/income-tax/section-32` screen). The one residual — the bridge has no screen — sits on IT-09; FA-06 carries nothing IT-09 does not. Retire FA-06. |
| **IT-24 ≈ TDS-20** (not previously named) | Same function, `form26as_service.parse_26as_text`, same swallow at `:180-181`. **IT-24 carries the SILENCE** (`parse_errors` never written at `:85`; `parse_status='parsed'` on zero records at `:253`/`:275`). **TDS-20 carries the FORMAT** (only tab/pipe delimited, no PDF path, no current-year option). Fixing IT-24 alone converts a silent zero into a hard refusal for every real TRACES download; they must land together. |
| **IT-20 ≉ PAY-22** (a near-duplicate that is *not* one) | Same computation, different halves. **PAY-22 is the BASE** — gross vs basic+DA — and is **closed** by `c3c63c35`. **IT-20 is the RATE** — 10% vs 14% under §115BAC(1A) — and is **open**. The 11 September pass warned about exactly this confusion and the warning is still warranted. |
| **IT-07 → IT-21** (an ordering dependency, not a duplicate) | Both are in `minimum_tax.compute_amt`. IT-21's §115JC(5) carve-out makes part of IT-07's fix (the new-regime 25% surcharge cap) unreachable for an individual. Do IT-21 first. |

## 2. Defects with no finding at all

**2a. `exempt_income_paise` is collected, transmitted, accepted — and never read.**
`apps/web/app/clients/[id]/tax/computation/page.tsx:671` renders an `Exempt Income (₹)` input; `:389` sends `exempt_income_paise`; `apps/api/routers/income_tax.py:190` declares it and `:283` passes it to the engine; `apps/api/domain/income_tax/itr_engine.py:341` declares it on `ITRComputeRequest` — and `compute()` never reads it. `grep -n "exempt_income_paise" apps/api/domain/income_tax/itr_engine.py` returns exactly one line, the declaration. A CA types a figure into a live field on the client Tax Computation tab, it changes nothing, appears in no result field, and nothing says so. (§10 exempt income legitimately does not enter total income, so the *tax* is right — but the field should either report the figure back or not exist.)

**2b. IT-08's own working never leaves the engine.**
`itr_engine.py:453-457` computes `basic_exemption_absorbed_paise` and `basic_exemption_absorption` — the docstring at `:1246-1252` says it exists "so a CA can see WHICH gain the exemption was set against … a choice a reader is entitled to check". `grep -rn "basic_exemption" apps/api/routers apps/web` returns **nothing**. So a CA sees ₹20,800 on a ₹5,00,000 STCG with no explanation of the ₹4,00,000 that vanished, and cannot check the highest-rate-first allocation the engine chose on their behalf. This is precisely CLAUDE.md's "a figure the computer gets right and no screen shows is not a fixed bug."

**2c. `book_to_tax_bridge.py`'s docstring is now false.**
`apps/api/domain/income_tax/book_to_tax_bridge.py:28-30`: *"they are two systems, and NOTHING IN THIS CODEBASE IMPLEMENTS THE SECOND ONE."* `domain/income_tax/section_32.py` implements it, and `routers/income_tax.py:1329-1345` feeds it into this very module. Prose only, but it is the module's central claim and it will mislead the next reader into rebuilding §32.

## 3. Stale rate and the highest-value fixes

**Stale rate for the slice: 13 of 34 fully closed (38%), 9 partial (26%), 12 still open (35%).** Two-thirds have moved at least partly since the September scoring — much higher than the ~10% the 11 September pass measured across the whole backlog, because income tax absorbed three consecutive tranches (`46bd46c`, `714c1c84`/`ac7fe5b5`, `dba0996f`, `c3c63c35`). Of the 11 September Phase 13a/13c income-tax entries: **IT-08 and IT-26 are closed**, **IT-32 is partial**, **IT-20 and IT-33 are still open exactly as listed**.

**Highest value by "what a CA sees wrong today", in order:**

1. **IT-19** — the biggest wrong *number* left on a reachable screen. `/income-tax/capital-gains` charges LTCG on a long-held listed holding on the gross gain with no §55(2)(ac) 31-01-2018 substitution, and the wrong figure is persisted into the register. The page header (`capital-gains/page.tsx:9`) advertises "Section 54: Exemptions" that do not exist, so the CA has no reason to distrust it.
2. **IT-24 (with TDS-20)** — the worst wrong *conclusion*. A real TRACES dump parses to zero records, is stored `parsed` with a green tick, and the reconciliation then reports the client's entire book TDS credit as unsupported. Nothing on screen says the parse found nothing.
3. **IT-11** — a wrong statutory statement on a compliance screen: a ₹60 lakh trader is told "tax audit mandatory (profession)" when none applies, and a ₹5 crore business under the 5% cash test is not told its threshold is ₹10 crore. §271B is 0.5% of turnover.
4. **IT-33** — cheapest fix on the list and the first thing on the Income Tax hub: on today's date it shows four elapsed FY 2025-26 instalments under a heading that says FY 2025-26.
5. **IT-20** — a real ₹40,000-of-deduction gap per employee at a ₹10 lakh base, now at least visible; blocked on an out-of-band statutory confirmation, not on code.
6. **§2a and §2b above** — a live input that does nothing, and a correct answer with its reasoning withheld. Both are hours.
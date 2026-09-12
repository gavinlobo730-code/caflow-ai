Verified all 30 findings against HEAD `92392e2c`. Read `/home/user/caflow-ai/CLAUDE.md` and `docs/audits/2026-09-01-payroll-can-it-run-a-year.md` first.

---

**PAY-01 — VERDICT: closed**
EVIDENCE: `apps/api/domain/payroll/ecr.py:258-262` — `stored_pf_wages = slip.get("pf_wages_paise"); pf_wages = (int(stored_pf_wages) if stored_pf_wages is not None else int(slip.get("basic_paise") or 0) + int(slip.get("da_paise") or 0)); pf_wages += int(slip.get("one_time_pf_wages_paise") or 0)`. The 30-line comment at `:229-257` states why NULL falls back to basic+DA (pre-migration-334 slips were remitted on basic+DA).
PREMISE: was true; now false.
FIX: the finding's fix is what landed, exactly.
SHAPE / SIZE: n/a.

**PAY-02 — VERDICT: closed**
EVIDENCE: `apps/api/routers/payroll.py:5462-5463` passes both `standard_deduction_paise` and `old_regime_standard_deduction_paise`; `apps/api/domain/payroll/annexure2.py:314-325` selects per row on `uses_new_regime`, and `:316-323` emits a named gap rather than silently using the new figure when the old one is absent.
PREMISE: false now.
FIX: as suggested, plus the gap — better than suggested.

**PAY-03 — VERDICT: closed**
EVIDENCE: `apps/api/services/payslip_pdf_service.py:714` `def load_employer(firm_id, client_id)`, `:715` "The `clients` row the payslip is issued BY — firm-scoped, and refused"; `:731` `db.table("clients")`, `:748` reads `client_statutory_identity`. Callers `:547` and `:603` pass `run.get("client_id")`. No `table("firms")` remains in the file.
PREMISE: false now. The 08b rescore holds.
FIX: landed as suggested.

**PAY-04 — VERDICT: open**
EVIDENCE: `apps/api/routers/payroll.py:715-717` (`_tds_already_deducted_this_fy`) — `db.table("payroll_runs").select("id, month").eq("firm_id",…).eq("client_id",…)`, no status predicate; `_members_contributing_earlier_this_period` the same (`sed` over its body shows `payroll_runs` selected with no `status`). Contrast `:4952` and `:5391` `usable = [r for r in runs if r.get("status") in ("finalized","paid")]`, and `_PAYROLL_RELEASED = ("finalized","paid")` at `:3402`, used only at `:2134`.
PREMISE: the code claim is TRUE. The harm claim in the original evidence is FALSE and stays false — the 7 Sept measurement (over-withheld ₹38,350, October identical to the paise) is unchallenged. What is wrong today is the inconsistency between the withholding and the return, plus the permanence of a draft.
FIX: **sound for the TDS read, questionable for the ESI read.** `_tds_already_deducted_this_fy` moves both `gross_already_paid_paise` and `months_already_paid` together, so filtering is self-consistent. But `_members_contributing_earlier_this_period` answers Rule 50's *"was this member contributing earlier in this contribution period?"*, and `_compute_esi`'s docstring (`routers/payroll.py`, the `covered_at_period_start` paragraph) says the default of False exists so a caller "behaves as before rather than silently over-deducting". Filtering that read to released runs makes an unfinalised April drop a member out of coverage in May the moment their wages cross ₹21,000 — under-deducting ESI, which is the employer's liability with interest, and is the direction the whole Rule 50 fix was written against. Apply the filter to the TDS read; leave the ESI read inclusive (or decide coverage from wage history, not run status) and say why.
SHAPE: `routers/payroll.py` only. No migration. Blocker the finding names but does not size: the second half is PAY-21.
SIZE: hours.

**PAY-05 — VERDICT: open**
EVIDENCE: `apps/api/domain/payroll/professional_tax.py:96-99` returns `PTResult(0, modelled=True, note="No state set; no professional tax withheld.")` for a blank code — `is_gap` is `not modelled and amount==0` (`:80-83`), so False. `routers/payroll.py:438-446` appends only `if pt.is_gap`; `domain/payroll/exceptions.py:123-127` the same. `apps/web/app/clients/[id]/payroll/page.tsx:276` form state has no `pt_state` key and `:470` renders the PT checkbox; `grep pt_state` on that file → nothing. `apps/api/models/payroll.py:61-62`, `:166-167`, `:279-280` accept the two independently with no cross-field validator; `EmployeeUpdateIn.model_config` is `{}`.
PREMISE: TRUE on every limb. One addition the finding misses: `routers/payroll.py:449` runs `classify_lwf_state(emp.get("pt_state"))` on the same blank field, and `domain/payroll/lwf.py` returns not-a-gap for blank too — so the LWF gap is silenced by the same missing field.
FIX: **(a) sound only if it adds a parameter, not if it flips the blank answer.** `tests/test_pt_lwf_state_coverage.py:65-69 test_no_state_set_is_not_a_gap` pins `not classify_state(None).is_gap` and `not classify_state("").is_gap`. Both live callers are already inside `if emp.get("pt_applicable")`, so the smaller correct fix is in the callers. **(b) is unsound as written.** Putting the refusal in `EmployeeIn`/`EmployeeUpdateIn` breaks the PATCH: `EmployeeUpdateIn` is all-Optional and cannot see the stored row, so `pt_applicable=True` alone against a row that already has a state would 422. The refusal belongs in `update_employee`/`create_employee` after merging with the stored row. Second blocker: `apps/web/lib/imports/mappers.ts:613` and `apps/api/domain/payroll/employee_import.py:100` mark PT State optional — a model-level refusal starts rejecting CSVs that import today. Neither half of the fix writes an unmodelled state's slab, which is right.
SHAPE: `domain/payroll/professional_tax.py`, `routers/payroll.py`, `models/payroll.py` or the router, `apps/web/app/clients/[id]/payroll/page.tsx`, `apps/web/lib/imports/mappers.ts`. No migration.
SIZE: day.

**PAY-06 — VERDICT: closed**
EVIDENCE: `apps/api/routers/payroll.py:1461` `months_in_year = max(0, months_employed_in_fy)`; `:1472` `basic_plus_da_paise=(basic + da) * months_in_year`; `:1480` `hra_received_paise=hra * months_in_year`. The 20-line comment at `:1440-1460` carries the ₹85,800/₹73,320 measurement.
PREMISE: false now.

**PAY-07 — VERDICT: closed** (this is the 11 Sept escalation, and it landed)
EVIDENCE: `apps/api/routers/payroll.py:895` `_perquisites_for_run`, whose docstring at `:907-911` says in terms "a CA … saw it confirmed, saw it on Form 16 Part B in May, and never saw it in a single month's deduction. The confirmation message read as reassurance." Wired at `:2265` and `:2336` (`perquisites_paise=perquisites.get(emp["id"], 0)`), consumed at `:1433-1437` `perquisites_in_estimate = max(0, perquisites_paise); annual_gross = … + perquisites_in_estimate`, and stored at `:1553` `"perquisites_in_tds_estimate_paise"` (migration 368). Deliberately not added to gross (`:1428-1430`), so PF wages, ESI and net are untouched. UI now exists: `apps/web/components/payroll/EmployeeDrawer.tsx:58,177-178` `PerquisitesSection`.
PREMISE: false now, including the "reachable from no screen" correction.
FIX: the finding's own fix, minus the "proportionate share on the payslip" — the code takes the year's value into the annual estimate and lets §192(3) spread it, which is the better reading and is argued at `:1424-1427`.

**PAY-08 — VERDICT: closed for the case the finding describes; see NEW DEFECT 1 for the second cycle**
EVIDENCE: `apps/api/routers/payroll.py:671` `_undo_loan_recoveries`, called from `reverse_run` at `:3106` between the journal reversals and the status reset (the ordering argument is at `:3103-3105`). Migration `367_a_payroll_reversal_puts_the_loan_back.sql` adds `payroll_loan_recoveries` with a signed `amount_paise` and a `kind` CHECK (`:63`, `:87-89`). Pre-367 runs fall back to the slip total with a spoken caveat (`:733-781`).
PREMISE: false now for one correction cycle.
FIX: the finding offered two options; the *second* (record the run against each repayment) is the one that landed, and it is the right one — the first (a blind inverse write) could not have handled the multi-loan or closed-loan cases, which the migration header explains at `367:22-30`.

**PAY-09 — VERDICT: closed**
EVIDENCE: `apps/web/lib/payroll/types.ts:80-88` `employerCostOf` reads `pf_employer_paise`, `esi_employer_paise`, `edli_paise`, `pf_admin_paise` off the row and does no arithmetic on wages; `apps/web/app/payroll/reports/page.tsx:628` `const cost = employerCostOf(s)`. The old expression is gone; the docstring at `:603-625` records all four drifts.
PREMISE: false now.

**PAY-10 — VERDICT: open**
EVIDENCE: `apps/web/lib/services/payrollTdsEstimate.ts` still exists, FY 2025-26 slab literals at `:30-38`, header at `:8-23` still calls itself "a standing CLAUDE.md violation tracked as roadmap R2.10" and "deliberately NOT FY-versioned". Imported at `apps/web/app/payroll/reports/page.tsx:38`, used at `:808` and `:834`. Allowlisted at `apps/web/scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts:60-67`.
PREMISE: TRUE, with the 7 Sept corrections intact (display-only; FY-drift latent). One premise in the module itself is now FALSE: its header claims `app/payroll/page.tsx` persists slips computed here — `grep payrollTdsEstimate apps/web/{app,lib,components}` returns only `reports/page.tsx`, and there is no browser-side `payroll_slips` insert anywhere (`grep 'from("payroll_slips")'` → `app/portal/employee/page.tsx:181`, a read). Anyone scoping from that header will over-estimate the blast radius.
FIX: **sound**, and it is the house rule. Three blockers the finding does not name: (1) deleting the file requires removing its `RATE_HOLDERS` entry at `tds-is-computed-by-the-engine-not-the-browser.test.ts:60` — the map's own comment says it "may only shrink", so that is the intended direction, but the test must be edited in the same change; (2) the tab projects employees with **no slip yet** (`reports/page.tsx:834`), so the endpoint has to accept a hypothetical component set, not a slip id; (3) `_monthly_tds` is a module-level function in `routers/payroll.py:1279`, not a service, so it needs a thin endpoint or extraction.
SHAPE: new endpoint in `routers/payroll.py`, `apps/web/app/payroll/reports/page.tsx`, delete `apps/web/lib/services/payrollTdsEstimate.ts`, edit the guard test. No migration.
SIZE: multi-day.

**PAY-11 — VERDICT: closed**
EVIDENCE: `apps/web/components/payroll/EmployeeDrawer.tsx:1-28` names the six capabilities and `:49-62` gives them sections (settlement, revisions, loans, perquisites, relief); mounted at `apps/web/app/clients/[id]/payroll/page.tsx:22,521`. Annexure II is reachable at `apps/web/app/clients/[id]/payroll/page.tsx:1338` via `api.payroll.annexureII` (`lib/api/index.ts:2368`). `salary-structures/{id}/apply` is called from `apps/web/components/payroll/ApplyStructureModal.tsx:91`.
PREMISE: false now — all seven have a screen.

**PAY-12 — VERDICT: partial**
EVIDENCE: `joining_date` is now on `EmployeeUpdateIn` (ran it: `EmployeeUpdateIn(name='A', joining_date='2026-10-01').model_dump(exclude_none=True)` → `{'name':'A','joining_date':'2026-10-01'}`), closed by `5e4649f3`. Still open: `eps_eligible` and `gratuity_act_covered` are in **neither** `EmployeeIn` nor `EmployeeUpdateIn` (printed both field sets), in no CSV column (`domain/payroll/employee_import.py` has no such key), and in no form. They are read defaulting **True** at `routers/payroll.py:1366` (`eps_eligible=emp.get("eps_eligible", True)`), `:6060`, `:6102`, and `:6073` / `:6207` (`covered_by_the_act=bool(emp.get("gratuity_act_covered", True))`). `EmployeeUpdateIn.model_config` is still `{}`.
PREMISE: half true. The consequence is worse than "cosmetic": a member excluded from EPS under GSR 609(E) gets 8.33% diverted to EPS **on the ECR**, a statutory return, and cannot be corrected from anywhere.
FIX: sound but incomplete as written — adding the two to `EmployeeUpdateIn` alone leaves them unsettable at create, and `tests/test_a_field_you_can_create_is_a_field_you_can_correct.py:153` only checks create→update, so it will not notice. They must go on `EmployeeIn`, `EmployeeUpdateIn`, the CSV importer and a form control together. `extra='forbid'` is riskier than the finding implies: `apps/web/app/clients/[id]/payroll/page.tsx` `addEmployee` spreads `...rest`, so a forbid turns today's silent drops into 422s at the create door — correct, but it must land with the form change or employee creation breaks.
SHAPE: `models/payroll.py`, `domain/payroll/employee_import.py`, `apps/web/components/payroll/AddEmployeeModal.tsx`, `apps/web/lib/imports/mappers.ts`. No migration (columns exist, migrations 295/298).
SIZE: hours.

**PAY-13 — VERDICT: partial**
EVIDENCE: the client-workspace form is unchanged — `apps/web/app/clients/[id]/payroll/page.tsx:276` (name, employee_code, date_of_birth, aadhaar, designation, department, basic_paise, hra_percent + three booleans) and `:470` (PF/ESI/PT checkboxes). But the "neither form captures LTA/medical/special" limb is now **FALSE for the client workspace**: `apps/web/components/payroll/EmployeeDrawer.tsx:481-489` posts `basic_paise, hra_percent, da_percent, lta_paise, medical_paise, special_allowance_paise, other_allowances_paise` to `/employees/{id}/salary-revisions` (`routers/payroll.py:6877`), and `_salary_in_force` (`:563`) merges the revision into the month's components at `create_run`. Still uncollectable from that surface: PAN, joining_date, UAN, ESIC number, bank details, pt_state.
PREMISE: partly false, per the above.
FIX: "one employee form" is sound. Blocker it does not mention: a **revision is not the master** — `payroll_salary_revisions` is read only by `_compute_slip`, so components set through the drawer change the payslip and not `payroll_employees`; see NEW DEFECT 2, which the fix would otherwise make more common.
SHAPE: `apps/web/app/clients/[id]/payroll/page.tsx`, `apps/web/components/payroll/AddEmployeeModal.tsx`. No migration.
SIZE: day.

**PAY-14 — VERDICT: closed**
EVIDENCE: `apps/api/routers/payroll.py:4963-4997` — a commented block "A LEAVER'S SETTLEMENT IS A DEDUCTEE ROW TOO (PAY-14)" reads `payroll_settlements` (`:4978`) and appends a slip-shaped row into the same `slips_by_month` bucket, using `taxable_paise` (not `gross_paise`) so it goes through the identical PAN/§206AA/challan path. Landed in `a8c1dacc`.
PREMISE: false now.

**PAY-15 — VERDICT: open**
EVIDENCE: `apps/web/components/panels/TeamPanel.tsx:33` is still the only `href` to `/payroll/attendance` (`grep -rn 'payroll/attendance' app components lib`). `grep -ni attendance apps/web/app/clients/[id]/payroll/page.tsx` → comments at `:522`, `:1443`, `:1926` and the run-gap banner at `:605-622`; no editor.
PREMISE: TRUE.
FIX: sound. Blocker it does not mention: leave balances live on the same page and are written by a **direct PostgREST upsert** (`apps/web/app/payroll/attendance/page.tsx:604`), so moving the page carries PAY-24's unguarded write into the client workspace with it. Decide PAY-24 first or split the page.
SHAPE: `apps/web/app/clients/[id]/payroll/page.tsx`, `apps/web/app/payroll/attendance/page.tsx`, `TeamPanel.tsx`. No migration.
SIZE: day.

**PAY-16 — VERDICT: closed**
EVIDENCE: `apps/web/lib/payroll/useSlips.ts:1-28` (the hook, and `isNarrowed` at `:41-43`) with `null` fetching nothing; `apps/web/app/payroll/reports/page.tsx:295, 455, 647, 790` each ask for one run / one month / one employee-year. Server side, `routers/payroll.py:2495-2516` `GET /slips` calls `payroll_report_service.assert_narrowed` (`services/payroll_report_service.py:192-205`, "THE REFUSAL IS THE FIX") and 422s an unnarrowed request. No `getRunSlips` fan-out remains in `app/payroll/page.tsx`.
PREMISE: false now. Residual, not part of the finding: `apps/web/app/payroll/reports/page.tsx:1325` still selects every `payroll_runs` row for the firm — proportional to client-months, far smaller than slips, but it does grow.

**PAY-17 — VERDICT: closed**
EVIDENCE: `apps/api/routers/payroll.py:342` `_annual_pt_paise`, called at `:1484`; its 45-line docstring (`:346-385`) records that `pt * months_in_year` "looked like a fix and was not". The loop at `:389-394` walks `_FY_MONTH_ORDER[12-n:]` (`:339` `(4,5,6,7,8,9,10,11,12,1,2,3)`), taking the run month at its actual gross and every other month at the recurring gross. TN: Sep+Mar = ₹2,500. MH: 11×₹200 + ₹300 = ₹2,500.
PREMISE: false now. The 08b rescore holds.

**PAY-18 — VERDICT: closed**
EVIDENCE: `grep -n '[^_a-zA-Z]logger\.' apps/api/routers/payroll.py` → no output.

**PAY-19 — VERDICT: closed**
EVIDENCE: `apps/web/app/payroll/reports/page.tsx:131-161` — the docstring names PAY-19 and says the monthly deposits and the four quarterly return dates now come from `GET /api/compliance/payroll-deposit-due-dates/fy`; `:195-224` iterates `served.months[].deposits` and `served.returns[]`. The invented PT row is gone (`grep 'PT Challan'` → nothing), replaced by a named gap. `apps/web/app/payroll/page.tsx:95-113` carries the matching comment, including that the old `else` branch "showed 'Q4, due 31 May' and not the Q3 return due on 31 January". The half-yearly ESI return is kept and explicitly marked unconfirmed (`reports/page.tsx:158-161`) rather than deleted on weak evidence — the right call.
PREMISE: false now.

**PAY-20 — VERDICT: closed**
EVIDENCE: `apps/api/routers/payroll.py:6054-6059` `statutory_position` calls the shared `_pf_wage_base` (defined `:1228`, also called from `_compute_slip` at `:1351`) and `:6060` `_compute_pf(_wb.wages_paise, …)`; the working is surfaced at `:6090-6092` (`pf_wages_paise`, `pf_wages_addback_paise`, `pf_wages_rule_applied`). ESI on the same screen honours Rule 50 (`:6064-6065`).
PREMISE: false now.

**PAY-21 — VERDICT: open**
EVIDENCE: `grep '^@router\.' apps/api/routers/payroll.py | grep runs` → GET/POST `/runs`, `/runs/{id}/slips`, `/runs/summary`, `/runs/{id}/payslips.zip`, PATCH `/runs/{id}/status`, POST `/runs/{id}/finalize|disburse|reverse`, `/runs/{id}/ecr`, `/runs/{id}/ecr/filed`, `/runs/{id}/esic`, `/runs/{id}/handoff`, `/runs/{id}/esic/mapped-ips`. **No DELETE and no recompute.** `reverse_run` at `:3033` sets `status:"review"` (`:3110`) and touches no slip. `_release_gaps` still tells the CA to "Regenerate the run to find out".
PREMISE: TRUE.
FIX: sound. Three blockers it does not name: (1) `reverse_run` reopens a run at exactly `'review'`, so a recompute permitted on `'review'` will rebuild slips for a run whose journals were reversed — that is the intended use, but the `payroll_loan_recoveries` history (migration 367) is keyed on `run_id` and describes slips that would no longer exist; it is the audit history and must be left alone, and NEW DEFECT 1 must be fixed before a recompute makes the cycle easy to hit. (2) A DELETE must refuse any run that ever carried a `journal_entry_id`, since the reversal is the correction path for those. (3) The user-visible promise at `_release_gaps` has to become true or be reworded in the same change.
SHAPE: `routers/payroll.py` only. No migration.
SIZE: day.

**PAY-22 — VERDICT: closed** (and NOT confused with IT-20)
EVIDENCE: `apps/api/routers/payroll.py:1479` `salary_for_80ccd2_paise=(basic + da) * months_in_year`, forwarded through `_monthly_tds` (parameter at its signature, `:1284`) into `decl_domain.withholding_tax_paise`, which forwards it at `domain/payroll/declarations.py:389` to `itr_engine`'s `salary_base_80ccd2` (`domain/income_tax/itr_engine.py:680`). Landed as `5585f7bf`, whose message measures ₹40,560/employee/year and explicitly **corrects** the earlier confusion: "OPEN-QUESTIONS §A1 claimed a '14% cap' … Both wrong … The rate is 10%. 14% is `LIMIT_80CCD2_GOVT_PERCENT`". The parameter is required, not defaulted (`_monthly_tds` has no default for it).
PREMISE: false now.
IT-20 is a **separate, still-open** question in another slice — whether the non-government cap is 14% rather than 10% under §115BAC(1A). `domain/income_tax/itr_engine.py:61-62` still holds `GOVT=14 / OTHER=10`, applied at `:678-679`, with the reason for under-claiming written at `:686-695`. Base (PAY-22) and rate (IT-20) are different facts; the two fixes were not conflated.

**PAY-23 — VERDICT: open**
EVIDENCE: `grep -rn 'bonus_domain\.' apps/api --include=*.py` (non-test) → `routers/payroll.py:59` (import) and `:6237` (the only call), which sits inside `_compose_settlement` (`def` at `:6190`). `grep -rn 'Form C|bonus_register|annual-bonus' apps/api apps/web` → nothing.
PREMISE: TRUE.
FIX: sound in shape. **Blocker the finding does not mention, and it is the CLAUDE.md §3b one:** `domain/payroll/bonus.py:160-168` computes on `CALCULATION_FLOOR_PAISE = 7_000 * 100` and appends a gap saying so, because the §12 base is *the higher of ₹7,000 and the state minimum wage* and no minimum wage is held. So an annual bonus run over the roster produces a Form C with **every line on ₹7,000 and every line carrying a gap** — up to half the real bonus in most states. The screen must present the gaps as blocking, and the minimum wage must be a human-supplied per-state figure, not written from memory.
SHAPE: new router endpoints + a screen; `domain/payroll/bonus.py` unchanged; a table for the supplied minimum wages ⇒ **migration required**.
SIZE: multi-day.

**PAY-24 — VERDICT: open**
EVIDENCE: `apps/web/app/payroll/attendance/page.tsx:316-318` `casual_leave_balance: existing?.casual_leave_balance ?? 12, sick_leave_balance: … ?? 12, earned_leave_balance: … ?? 15`; upserted at `:604`. `grep -rn leave_balances apps/api` → migrations and RLS tests only, no logic module.
PREMISE: TRUE. One thing that lowers it: the invented balance does **not** reach money — leave encashment on a settlement comes from the request body (`routers/payroll.py:6151-6152`, `:6215-6222` `body.leave_encashment_paise` / `body.leave_days_encashed`), not from `leave_balances`.
FIX: the honest option (remove the defaults) is sound and matches the module's gap discipline. Blocker: the 12/12/15 has been **persisted** for every employee a CA has saved since the screen existed, and the table has no provenance column — a stored row cannot be told apart from a typed one. Removing the default silently leaves those rows looking like recorded policy. Either add provenance or accept a one-time review.
SHAPE: `apps/web/app/payroll/attendance/page.tsx`, `apps/web/app/portal/employee/page.tsx`. A provenance column ⇒ migration if that route is taken.
SIZE: hours to remove; multi-day to build a policy model.

**PAY-25 — VERDICT: open**
EVIDENCE: `apps/api/services/phase2_journal_service.py:998` `total_cost = sum(amount for _, amount, _ in credits)`, `:1020` one line `account_ids["salary_exp"]` with `debit_paise: total_cost`. The comment at `:1002` concedes "because the debit is DEFINED as sum(credits), the kernel's balance check can no longer catch a mis-computed run". The range invariant survives at `:1013-1016`. `grep 'Contribution to PF' apps/api` → only the docstring at `:938`.
PREMISE: TRUE, with the 7 Sept correction ("undetectable by construction" is refuted by the range invariant) intact.
FIX: sound and desirable. Three scope items it does not name: (1) `_find_account(db, firm_id, client_id, "%Salaries Expense%")` (`:1078`) is a LIKE lookup, so the two new accounts need seeding or a creation path in every client's chart; (2) posted entries are immutable, so historic runs keep one line and any Schedule III consumer must handle both shapes; (3) the range invariant at `:1013` is replaced by the kernel's exact assertion, so its `ValueError` message and the tests pinning it move with it. Nothing here creates a second posting path — the kernel is still `_create_journal`.
SHAPE: `services/phase2_journal_service.py`, chart-of-accounts seeding. Migration likely (seed accounts).
SIZE: multi-day.

**PAY-26 — VERDICT: open**
EVIDENCE: `apps/web/app/portal/employee/page.tsx` is 482 lines, `:61` `type TabId = "payslips" | "leave" | "declaration" | "profile"`. No TDS working, no 12BB/Form 16 output, no proof upload, no leave apply/approve.
PREMISE: TRUE, and the deliberate-deferral note at `docs/architecture/10-payroll.md:392` still applies.
FIX: sound, and the ordering (TDS working first) is right — every input already exists in `_monthly_tds`. Note in passing that the declaration write path is properly guarded despite being direct PostgREST: `migrations/297_let_an_employee_file_their_own_declaration.sql:159-186` raises on any attempt by an employee to set `proofs_verified`, the three `*_verified_paise` columns, `verified_at`/`verified_by`, or to move the row. So "employee self-verifies" is not a hole here.
SIZE: multi-day+.

**PAY-27 — VERDICT: open**
EVIDENCE: `grep -c department apps/web/app/payroll/reports/page.tsx` → 0. `grep -rni 'neft|bank advice' apps/api --include=*.py` (non-test) → only `payment_mode` enums and `domain/payroll/register.py:8`, which names the bank advice as the thing the register sits *beside* and does not build. Six tabs, none of them variance.
PREMISE: TRUE for the four named absences; the 7 Sept corrections (reimbursements ARE modelled; payslip delivery exists as self-service) still hold.
FIX: sound, and the ordering is right. "Keep bank advice prepare-only" is the correct constraint.
SIZE: multi-day+.

**PAY-28 — VERDICT: open (low)**
EVIDENCE: `apps/web/components/panels/AccountingPanel.tsx:44,46`; `TeamPanel.tsx:33`; `lib/workspace/workspaceConfig.ts:176`; `ls apps/web/app/payroll/` → attendance, declarations, page.tsx, people, reports, statutory — no `setup`.
PREMISE: partly false and already corrected in the file: the PT state-coverage screen exists at `apps/web/app/settings/statutory-values/page.tsx`, so nothing is unreachable.
FIX: sound; navigation only. Do not build a `/payroll/setup` that duplicates `settings/statutory-values` — that is the "second place to say the same thing" mistake CLAUDE.md keeps recording.
SIZE: day.

**PAY-29 — VERDICT: closed**
EVIDENCE: `apps/api/services/payslip_pdf_service.py:99-135` `employer_contribution_lines` (EPF/EPS split, ESI employer, EDLI, admin, with `:71-73` explaining why they are a separate block); `:143-180` YTD, April-to-March; `:323-333` UAN, ESIC No., masked bank a/c + IFSC; `:465` `amount_in_words(net_paise)`. The rupee glyph is fixed at `:212-219` — `return f"Rs.{rupees:,}.{fraction:02d}"`, no U+20B9. Employer block from `load_employer` (PAY-03).
PREMISE: false now, including both limbs the verification added.

**PAY-30 — VERDICT: open**
EVIDENCE: ran at HEAD — `EmployeeIn(client_id='c1', name='A', uan='NOTANUMBER', esi_number='xx', bank_ifsc='bad')` is accepted and dumps those values; `EmployeeUpdateIn(uan='1', bank_ifsc='zzz', esi_number='q')` likewise. `domain/payroll/employee_import.py:72-74` still holds `UAN_RE = ^\d{12}$` and `IFSC_RE = ^[A-Z]{4}0[A-Z0-9]{6}$` and refuses the whole file.
PREMISE: TRUE. Harm stays low: `domain/payroll/exceptions.py:46, 74-77` indexes a bad UAN and `:84-91` a missing ESIC number, and the ECR refuses a bad UAN at file build.
FIX: **sound for UAN and IFSC; the ESIC limb is invented.** "a 10-digit ESIC check" is written from memory — nothing in `apps/api` validates `esi_number`'s format anywhere, and `exceptions.py:84-91` deliberately checks only presence. A wrong-length regex at the create door would refuse legitimate numbers for every client, and that is precisely the class of thing CLAUDE.md says a human supplies. Share the two regexes that already exist and that `ecr.py` already enforces; leave ESIC as the presence check it is.
SHAPE: `models/payroll.py` + import the regexes from `domain/payroll/employee_import.py` (or move them to a shared module). No migration.
SIZE: hours.

---

## 1. Duplicates across subsystems

| Pair | Which half each carries |
|---|---|
| **PAY-03 ≡ SALES-01** (and the customer statement) | Same defect in three PDF services: the CA practice printed where the client belongs. PAY-03 carries the payslip and `client_statutory_identity`; SALES-01 carries the supplier GSTIN/PAN on a tax invoice. **All three are now closed**, but each was fixed file-locally with a file-scoped test — there is still no sweep over `services/*_pdf_service.py`, which is why the payslip survived two rounds. |
| **PAY-09 ≡ FA-03** | "The browser re-derives a figure the backend already computed and stored." PAY-09 carried employer PF/ESI/EDLI/admin on the CTC CSV (now closed); FA-03 carries the depreciation charge on the Fixed Assets tab (other slice). |
| **PAY-10 ≡ TDS-05** | A hardcoded statutory rate table in TypeScript. TDS-05 carries Chapter XVII-B and **writes** its answer to `tds_deductions` over PostgREST; PAY-10 carries §192 salary and is display-only. They are deliberately kept apart — `apps/web/scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts:60-67` allowlists `payrollTdsEstimate.ts` with that exact reason. |
| **PAY-04 ≡ PAY-21** (within the slice) | One root, two halves. PAY-21 carries the missing capability (no discard, no recompute); PAY-04 carries the missing status filter that makes the resulting stale draft count. PAY-04's own `suggested_fix` says so. |
| **PAY-22 vs IT-20** — *not* a duplicate | Base vs rate. PAY-22 was the §80CCD(2) cap taken on gross instead of basic+DA (closed). IT-20 is whether the non-government cap is 14% or 10% under §115BAC(1A) (`itr_engine.py:61-62`, still 10%, still open). Fixing one does not touch the other. |

## 2. Defects with no finding at all

**NEW DEFECT 1 — the second reverse gives nothing back, so PAY-08 reopens on the second correction cycle. `apps/api/routers/payroll.py:713-731`.**
`_undo_loan_recoveries` builds `already` as a set of **loan_id** for the whole run (`:713-718`, query filtered on `run_id` + `kind='reversed'`) and skips any recovered row whose loan is in it (`:726-727`). `_record_loan_movement` (`:637`) is an append-only INSERT with no uniqueness (migration 367 has no unique key over `(run_id, loan_id, kind)`), and `reverse_run` (`:3033`) permits any run in `('finalized','paid')` — which a re-finalised run is. Trace: finalise → `recovered +X`; reverse → restores X, writes `reversed −X`; finalise again → `recovered +X` a second time; reverse again → `already = {loan_id}`, **both** recovered rows skipped, **nothing restored**. Loan written down 2X, restored X — the exact PAY-08 arithmetic, one cycle later. Now live through the UI: reverse is called from `apps/web/app/clients/[id]/payroll/page.tsx:1039`, and loans have a screen at `apps/web/components/payroll/EmployeeDrawer.tsx` (`lib/api/index.ts:2324-2330`), so PAY-08's old "no loan row exists" mitigation is gone. No test covers a second cycle — `tests/test_a_payroll_reversal_puts_the_loan_back_pg.py` has eleven cases and none re-finalises. The fix the table already supports: `test_the_balance_reconstructs_from_the_history` names the invariant — restore the **net signed `amount_paise`** per `(run_id, loan_id)` instead of an all-or-nothing loan_id skip. Hours.

**NEW DEFECT 2 — `/statutory-position` ignores salary revisions, so the projection and the payslip disagree again. `apps/api/routers/payroll.py:6019-6042` vs `:2268` + `:2315-2322`.**
`create_run` reads `_salary_in_force` (`:563`) at `:2268` and merges the revision over the master ("A revision in force REPLACES the master's components for this month"). `statutory_position` reads `payroll_employees` at `:6019` and takes `basic_paise`, `da_percent`, `hra_percent`, `lta_paise`, `medical_paise`, `special_allowance_paise`, `other_allowances_paise` straight off the master at `:6035-6042` — it never calls `_salary_in_force`. So a revision recorded through the new drawer (`EmployeeDrawer.tsx:481-489`) changes the payslip, the PF base, the ECR and the ledger, and leaves the Statutory Deductions screen projecting the old pay. This is the same class of defect PAY-20 closed ("Two PF figures for one employee, and the CA has no way to tell which the challan will carry", `:6049-6051`), reopened through a different input — and PAY-11's drawer is what made it reachable. Hours.

**NEW DEFECT 3 (low, cosmetic but statutory) — two screens still label the PF base as basic.**
`apps/web/app/payroll/page.tsx:433` renders `PF Deduction (12% of Basic)` beside `{fmtRs(slip.pf_employee_paise)}` — a figure computed on the Code on Social Security s.2(88) base (migration 334), which for a low-basic/high-HRA structure exceeds basic. `apps/web/components/payroll/AddEmployeeModal.tsx:200` labels the checkbox `PF Applicable (12% of basic)`. The numbers are right; the labels contradict them on the two screens where a CA decides `pf_applicable` and reads the deduction.

## 3. Stale rate, and where the value is

**Stale rate: 11 of the 23 findings the file still records as `still_open` have moved — 48% of the recorded backlog, 37% of the slice.** Newly closed since the 8 September rescore: **PAY-07, PAY-08, PAY-09, PAY-11, PAY-14, PAY-16, PAY-19, PAY-22, PAY-29**. Newly partial: **PAY-12, PAY-13**. Both 08b rescores (PAY-03, PAY-17) verify true. Final state: **16 closed, 2 partial, 12 open**. Both findings the 11 September pass escalated — PAY-07 and PAY-08 — are the escalations that landed; PAY-08 landed for the case it described and reopens one cycle later (NEW DEFECT 1).

**Highest value, measured by what reaches an employee's pay or a statutory return wrongly today:**

1. **PAY-05** — the only open finding that changes what an employee is paid. Tick "PT" on the client-workspace form and ₹0 is withheld every month forever, with no gap, no exception and nothing on the payslip; Article 276 makes the employer liable, and `_statutory_gaps`'s LWF branch is silenced by the same blank field. Hours, once the fix goes in the caller and the router rather than the domain function and the Pydantic model.
2. **NEW DEFECT 1** — a live, UI-reachable double write-down of an employee's advance on the second correction cycle. Hours, and it should land before PAY-21's recompute makes the cycle routine.
3. **PAY-12 residual** — `eps_eligible` settable from nowhere, defaulting True, diverts 8.33% to EPS on the **ECR** for a member GSR 609(E) excludes; `gratuity_act_covered` defaulting True changes a leaver's gratuity, which is money paid. Hours.
4. **PAY-23** — the one statutory annual payment the engine can already compute cannot be computed for anyone still employed, and §19 gives eight months. The blocker is the minimum wage, not the code.
5. **PAY-14 and PAY-01** are now closed, which is why nothing about a filed return is at the top of this list — what remains open is mostly projections, screens and information architecture.
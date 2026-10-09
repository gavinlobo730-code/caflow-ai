# Before the demo — Mine (Claude can do these alone)

IDs `PRE-A-NNN` are stable: never renumber; add new items at the next free number; delete an item in the same commit that closes it (then `python3 scripts/open_items_counts.py`, and remove the ID from any list in `README.md` and `decisions-and-strategy.md`). Read `README.md` first for the conventions (priority, effort, UNSURE, id namespaces).

## Demo and onboarding

- **PRE-A-002** · `demo-and-onboarding` · normal · days — **Fix whatever the rehearsals and walks turn up.** Task #39: Claude fixes, tests and merges whatever the sign-up rehearsal, the demo-firm seeding, the spine and UAT rehearsals, the browser drives and the other pre-demo click-throughs turn up, then reports. Redeploy again (see the Render redeploy item) if anything merges after the last deploy. _When: Cannot be scoped before the rehearsals happen; reserve the time between them and the demo._ — _Sources:_ session task #39 — _Refs:_ #39
- **PRE-A-004** · `demo-and-onboarding` · normal · days · UNSURE — **Run the seeded firm through GST, year-end and ITR; fill empty screens.** (1) The 1 September 2026 full-year walkthrough (docs/audits/2026-09-01-can-a-ca-run-a-client-for-a-full-year.md) drove one client through FY 2025-26 over a real PostgREST and migrated Postgres 16 stack and did not cover bank statement import and reconciliation, GST return assembly, fixed assets and depreciation, year-end close or ITR; its harness was never committed. apps/api/scripts/seed_demo_firm.py is now a committed, scripted full-year walk that DOES cover banks, statement import, fixed assets and depreciation, payroll, sales and purchases (checked 02-10-2026), so the unwalked areas that remain are GST return assembly (GSTR-1/3B compute), year-end close and statements, ITR computation and Verify Books. Claude extends the in-process seeded run (or a script beside it) to call those endpoints and reports any error or empty result: exactly the areas a CA will click through. (2) The seeder posts only about 25 API doors: clients, customers, vendors, catalogue, HSN library, sales invoices and receipts, purchase bills and payments, payroll runs / attendance / employees, fixed assets and depreciation, bank import and redraft, MSMED classification. A grep of apps/api/domain/demo/fixture.py and apps/api/scripts/seed_demo_firm.py finds none of: composition / CMP-08 / GSTR-4, GSTR-8 operator, GSTR-9C, cost centres, price lists, post-dated cheques, late interest, quotations / orders / delivery challans / ITC-04 job work, CWIP, TDS deductions; nor practice-side data (tasks, compliance calendar and records, engagements and fee invoices, time entries, ITR filings, year-end engagements). Those screens would render empty states in a demo, which is what Track 3 existed to end. UNSURE which gaps are real (compliance obligations, for instance, may be generated at client creation); only a seeded walk can tell, and the fixture was last touched in #616 (25 September). Verified 2 Oct 2026: apps/api/scripts/seed_demo_firm.py and apps/api/domain/demo/fixture.py never mention compliance, obligations or deadlines, while the GST and Income-tax trackers and /deadlines read compliance_calendar / compliance_records (rows come from the generate-obligations routes in routers/compliance_ops.py and routers/engagements.py). Have the seeder call the generator for each seeded client and assert in a test that every seeded client has obligations. _When: Cheapest way to find demo-breaking defects in the areas no end-to-end drive has touched, and to find which screens the seeded firm leaves empty. Needs the seeded firm; cut to the screens the demo script visits once the date and script are known._ — _Sources:_ docs/audits/2026-09-01-can-a-ca-run-a-client-for-a-full-year.md 'What this walkthrough did not cover'; docs/plan/THE-PLAN.md - Track 3 ('every screen rendered its empty state'); checked against domain/demo/fixture.py — _Refs:_ Track3, D7

## Platform, operations, CI and deploy


## AI


## GST returns


## Income tax and ITR


## Sales and purchase documents


## Banking


## Filing, integrations and registrations


## Screens and ease of use

- **PRE-A-015** · `frontend-ux` · normal · days — **Drive the money editors in a browser: double-click guard, keyboard, drafts, dates.** 'Nothing was clicked, because there is no browser.' A scripted Playwright drive against the smoke build (as was done once for the date field) can do all of this without the owner; a permanent version is the browser test tier (frontend_ux-02 / engineering-16). (1) frontend_ux-09/-16/-21/-23: a double-click on Post Entry, Save & Issue and Record Payment; Tab and Enter on a ledger row; reload and Restore on the journal and bill editors; one delete and one prompt; and Escape through a drawer. 211 buttons in 65 files use singleFlight and 15 handlers were rewritten to return their promise, all held only by source guards. (2) frontend_ux-19: DateInput was driven once, in an uncommitted scratch script, on the journal editor only (Chromium under en-US/Los Angeles, en-IN/Kolkata and en-GB/Kiritimati, 22 checks each). None of the other 60 converted fields was clicked: the invoice, bill, receipt, payment and note editors, the record-payment and create-note modals, payroll disbursement, fee engagement and receipt, TDS deduction and challan, Mark-as-filed and the rest are held only by tsc, lint, the suite and the ratchet. _When: Double-posting a journal in a live demo is the failure the guard exists to stop, and invoice, receipt and payment dates are the first things a CA types; none of it has ever been driven in a browser._ — _Sources:_ /home/user/caflow-ai/CLAUDE.md line 5449 (frontend_ux-09/-16/-21/-23); /home/user/caflow-ai/CLAUDE.md line 5465 (frontend_ux-19) — _Refs:_ rm/frontend_ux-09, rm/frontend_ux-16, rm/frontend_ux-21, rm/frontend_ux-23, rm/frontend_ux-19

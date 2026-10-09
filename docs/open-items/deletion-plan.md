# What was deleted on 8 October 2026, and what was kept

**Done.** The owner approved the plan in conversation on 8 October 2026 ("if you are sure about both, go ahead") and it was carried out in one pull request. This file is now the record: what was deleted, what was kept and why, and how to get any deleted file back. Deleting was cheap to reverse (git history keeps everything) but not free, because source comments and prose still name some of these files; where this file says KEEP it says why.

## How to recover a file

Every deleted file is in git exactly as it stood at merge commit `315e6a1980053c5db5e00646d16624d48e358907` (the commit that added this ledger, the last one to contain all of them):

    git show 315e6a19:docs/audits/<file>
    git ls-tree -r --name-only 315e6a19 docs/audits      # every file that was there

An archive **tag** named `audit-archive-2026-10-02` was planned and could not be created: the session that did this work may push only its own branch, and the push of a tag was refused with HTTP 403. The commit hash recovers the same files and cannot be deleted by accident; the owner may add the tag name on that commit in GitHub if a friendlier name is wanted.

## What happened, step by step

1. **The owner accepted the ledger** (8 October 2026).
2. **Tag**: not pushed, see above; the merge commit stands in for it.
3. **Amendment v1.1 design record**: the record is now written from the code in `docs/architecture/11-revenue-ops-and-knowledge.md`. The four `BATCH_6_*` and `BATCH_7_*` files are **still not deleted**: deleting them waits for your go-ahead (POST-B-336, see HELD below).
4. **`scripts/findings_status_md.py` was removed** with the findings files it read, and CLAUDE.md's audit table and its "`docs/audits/findings-status.*` is where to start" paragraph were replaced by a pointer to `docs/open-items/README.md` and a note of the deletion. `docs/plan/THE-PLAN.md` (three rows that named the findings record) and `docs/operations/post-mortems.md` (two bullets that called it the live status record) were repointed to the ledger.
5. **Comments were not repaired.** About 45 source files, test docstrings and migration headers, and prose in KEEP documents, still name `docs/audits/...`. They are comments, not reads (checked on 2 and 8 October 2026: no test, script or workflow opens any deleted file), and a migration's checksum is its identity, so none was edited. `docs/audits/README.md` was left behind as a one-page stub saying where the files went, so a reader who follows a dangling reference lands on the explanation.
6. **The full backend suite and the web checks ran on the branch** that deleted, as for any pull request.

## DELETED on 8 October 2026

84 files and one script. The size column is the size at the recovery commit.

| path | size | why it was safe |
|---|---|---|
| `docs/audits/` (61 files: the 2026-07 to 2026-09 audits, `2026-09-07-findings/`, `2026-09-07-market-research/`, `2026-09-12-the-probe-pass/`, `findings-status.json` and `.md`, `WHERE-WE-STOPPED.md`, `OPEN-QUESTIONS.md`, `questions-for-the-owner.md`, `what-to-fetch-for-me.md`, the checkpoint, the phase plans, the verification pass) | 3883 KB | Dated snapshots, each already measured stale. Their open items were extracted into the ledger (every raw item accounted for by a script); closed items and answered questions are recorded in `checked-closed.md`. The 2026-09-07 market research is search-engine summaries (nothing in it is graded primary) and its re-verify lists are ledger items. |
| `docs/plan/2026-09-24-overnight-run.md`, `QUESTIONS.md`, `STUCK.md`, `2026-09-13-questions-for-the-owner.md` | 70 KB | Log or question files; open questions are ledger items and answered ones are in `checked-closed.md`. |
| 19 top-level early reports (`BATCH_1` to `BATCH_5` completion and hardening reports, `PHASE_5_1` and `PHASE_5_2` reports and E2E plan, `DEAD_CODE_AUDIT.md`, `DEPLOYMENT_READINESS_AUDIT_v1_1.md`, `LOADING_UX_AUDIT.md`, `ENGAGEMENT_ARCHITECTURE_AUDIT.md`, `PRACTICESYNC_AUDIT_v1.md`, `QUICKBOOKS_ACCOUNTING_ROADMAP.md`, `security_audit_phase13b.md`) | 142 KB | Completion, hardening, E2E and audit reports of the early build; closed or superseded, with the open residue in the ledger. `security_audit_phase13b.md` was factually wrong (migration 154 replaced its RLS predicate). |
| `scripts/findings_status_md.py` | 6 KB | Rendered `docs/audits/findings-status.md` from the JSON; both are gone. |

### Every deleted path

`docs/audits/` (61 files):

    docs/audits/2026-07-01-combobox-smart-lookup-audit.md
    docs/audits/2026-07-01-combobox-smart-lookup-migration-summary.md
    docs/audits/2026-07-01-search-sort-filter-migration-summary.md
    docs/audits/2026-07-01-search-sort-filter-premerge-audit.md
    docs/audits/2026-07-01-search-sort-filter-ux-audit.md
    docs/audits/2026-07-02-executive-product-audit.md
    docs/audits/2026-07-04-navigation-routing-investigation.md
    docs/audits/2026-07-05-invoice-workspace-competitive-design.md
    docs/audits/2026-07-05-sales-invoice-ux-workflow-review.md
    docs/audits/2026-07-06-sales-invoice-workspace-density-audit.md
    docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md
    docs/audits/2026-08-02-migration-ledger-drift-audit.md
    docs/audits/2026-09-01-can-a-ca-run-a-client-for-a-full-year.md
    docs/audits/2026-09-01-payroll-can-it-run-a-year.md
    docs/audits/2026-09-02-foreign-vendor-walkthrough.md
    docs/audits/2026-09-03-client-profiles-nine-columns-not-twentynine.md
    docs/audits/2026-09-03-converging-the-last-guard-differences.md
    docs/audits/2026-09-03-declaring-what-production-enforces.md
    docs/audits/2026-09-03-guard-drift-first-run.md
    docs/audits/2026-09-03-rls-off-on-eight-granted-tables.md
    docs/audits/2026-09-03-three-writes-production-refuses.md
    docs/audits/2026-09-07-a-plus-roadmap.md
    docs/audits/2026-09-07-findings/README.md
    docs/audits/2026-09-07-findings/accounting-core-posting-kernel-journal.json
    docs/audits/2026-09-07-findings/banking-statement-import-csv-xlsx-pd.json
    docs/audits/2026-09-07-findings/fixed-assets-and-inventory.json
    docs/audits/2026-09-07-findings/gst-gstr-1-builder-gstr-3b-computer.json
    docs/audits/2026-09-07-findings/income-tax-and-itr-computation-works.json
    docs/audits/2026-09-07-findings/payroll-employee-master-salary-struc.json
    docs/audits/2026-09-07-findings/purchase-cycle-vendors-purchase-bill.json
    docs/audits/2026-09-07-findings/sales-cycle-customers-sales-invoices.json
    docs/audits/2026-09-07-findings/tds-tcs-section-rates-and-thresholds.json
    docs/audits/2026-09-07-findings/verification-verdicts.json
    docs/audits/2026-09-07-market-research/README.md
    docs/audits/2026-09-07-market-research/gst-primary.md
    docs/audits/2026-09-07-market-research/income-tax-tds-primary.md
    docs/audits/2026-09-07-market-research/payroll-primary.md
    docs/audits/2026-09-07-where-we-are-against-the-one-platform-goal.md
    docs/audits/2026-09-08-what-is-left.md
    docs/audits/2026-09-08b-what-is-left.md
    docs/audits/2026-09-08c-the-phase-plan.md
    docs/audits/2026-09-11-the-verification-pass.md
    docs/audits/2026-09-12-the-probe-pass/README.md
    docs/audits/2026-09-12-the-probe-pass/accounting-and-inventory.md
    docs/audits/2026-09-12-the-probe-pass/banking.md
    docs/audits/2026-09-12-the-probe-pass/fixed-assets.md
    docs/audits/2026-09-12-the-probe-pass/gst.md
    docs/audits/2026-09-12-the-probe-pass/income-tax.md
    docs/audits/2026-09-12-the-probe-pass/payroll.md
    docs/audits/2026-09-12-the-probe-pass/purchases.md
    docs/audits/2026-09-12-the-probe-pass/sales.md
    docs/audits/2026-09-12-the-probe-pass/tds.md
    docs/audits/2026-09-14-what-needs-both-of-us.md
    docs/audits/2026-09-15-the-unreachable-sweep.md
    docs/audits/2026-09-19-checkpoint.md
    docs/audits/OPEN-QUESTIONS.md
    docs/audits/WHERE-WE-STOPPED.md
    docs/audits/findings-status.json
    docs/audits/findings-status.md
    docs/audits/questions-for-the-owner.md
    docs/audits/what-to-fetch-for-me.md

`docs/plan/` (4 files):

    docs/plan/2026-09-24-overnight-run.md
    docs/plan/QUESTIONS.md
    docs/plan/STUCK.md
    docs/plan/2026-09-13-questions-for-the-owner.md

`docs/` top level (19 files):

    docs/BATCH_4_COMPLETION_REPORT.md
    docs/PHASE_5_2_E2E_UAT_PLAN.md
    docs/security_audit_phase13b.md
    docs/BATCH_5_COMPLETION_REPORT.md
    docs/PRACTICESYNC_AUDIT_v1.md
    docs/BATCH_2_1_HARDENING_REPORT.md
    docs/DEPLOYMENT_READINESS_AUDIT_v1_1.md
    docs/BATCH_3_COMPLETION_REPORT.md
    docs/PHASE_5_2_E2E_TEST_REPORT.md
    docs/ENGAGEMENT_ARCHITECTURE_AUDIT.md
    docs/DEAD_CODE_AUDIT.md
    docs/LOADING_UX_AUDIT.md
    docs/QUICKBOOKS_ACCOUNTING_ROADMAP.md
    docs/BATCH_1_COMPLETION_REPORT.md
    docs/BATCH_2_COMPLETION_REPORT.md
    docs/BATCH_3_1_HARDENING_REPORT.md
    docs/PHASE_5_1_SECURITY_REMEDIATION_REPORT.md
    docs/PHASE_5_2_WS1_E2E_COVERAGE_REPORT.md
    docs/PHASE_5_2_WS4_RELEASE_READINESS.md

## HELD, not deleted: waiting on a named prerequisite

| path | size | prerequisite |
|---|---|---|
| `BATCH_6_COMPLETION_REPORT.md`, `BATCH_6_DESIGN_REVIEW.md`, `BATCH_7_COMPLETION_REPORT.md`, `BATCH_7_DESIGN_REVIEW.md` | 41 KB | The design record is folded into `docs/architecture/11-revenue-ops-and-knowledge.md`; deleting these four waits for your go-ahead (POST-B-336). |

## KEEP

| path | size | why |
|---|---|---|
| `docs/compliance/` (README, 00–08, `sources/`) | 1110 KB | The statutory playbook and the committed primary-source texts (fetched by hand, unrecoverable from this container). Tests read the README and doc 06. Doc 08 supersedes 07 on registrations. |
| `docs/architecture/` | 110 KB | The design set for the accounting engine, posting kernel, GST engine and the rest. `10-payroll.md` carries a "partly superseded" banner. |
| `docs/operations/` | 93 KB | Runbooks, release and rollback, edge protection, service levels. Several tests read these files by path. |
| `docs/deploy-migrations.md`, `docs/schema-drift.md` | 15 KB | How migrations reach production; how the schema snapshots work. Cited from CLAUDE.md and the fixtures README. (Both need small refreshes: ledger items.) |
| `docs/plan/THE-PLAN.md` | 35 KB | `tests/test_the_operational_notes_say_what_was_measured.py` reads it (it needs a cold-start duration of at least 56.55 s in the file) and it is the only home of decisions D1–D27 and the definitions of the demo and the tracks. Trim it later; do not delete it. |
| `BETA_OPERATIONS.md`, `BULK_IMPORT.md`, `CASH_BASIS_REMEDIATION_DESIGN.md`, `DEMO_FILING.md`, `FIRM_HSN_LIBRARY.md`, `HSN_SAC_MASTER_MAINTENANCE.md`, `MANUAL_TESTING_ROADMAP.md`, `PRACTICE_CLIENT_VISIBILITY_DECISION.md`, `REVENUE_OPS_BRIDGE.md`, `PHASE_5_2_WS2_UAT_PLAN.md`, `PHASE_5_2_WS3_USE_USER_JWT_RUNBOOK.md`, `PracticeSync_Master_Guide.docx`, `PracticeSync_Master_Reference.docx` | 259 KB | Each is the only written statement of something. `BETA_OPERATIONS.md`: read by two required tests, holds the dashboard-only Supabase toggles. `CASH_BASIS_REMEDIATION_DESIGN.md`: the cash-basis rule and locked decisions A–D, cited by a test. `PRACTICE_CLIENT_VISIBILITY_DECISION.md` and `REVENUE_OPS_BRIDGE.md`: Option A and the legacy `fee_*` billing debt. `FIRM_HSN_LIBRARY.md` and `HSN_SAC_MASTER_MAINTENANCE.md`: HSN decisions A–D and the master load procedure. `DEMO_FILING.md`: cited from docs/compliance/01. `BULK_IMPORT.md`: the Aadhaar rule (full number accepted, last four stored). `MANUAL_TESTING_ROADMAP.md`: the only human regression order. `PHASE_5_2_WS2_UAT_PLAN.md`: the only UAT catalogue with sign-off sheets. `PHASE_5_2_WS3_USE_USER_JWT_RUNBOOK.md`: the only V/N/T acceptance checklist for the RLS cut-over. The two `.docx` guides: probably the only surviving copy of the nine original design documents and of Practice OS Module 9.2–9.6. |
| `docs/releases/` | 1 KB | A release note; no open work. |
| `docs/open-items/` | this directory | The ledger itself. |

## Owner's call (not audits, not clearly dead)

| path | size | note |
|---|---|---|
| `docs/plan/2026-09-12-compliance-and-craft.md`, `docs/plan/2026-09-16-the-redesign-plan-revised.md` | 38 KB | Active planning documents: the redesign plan is being worked one module per PR (the named-palette pass). They hold rationale, not open items. Keep until the redesign is finished, then delete. |
| `docs/marketing/` (two 2026-09-16 redesign plans) | 66 KB | Plans for the public site, mostly executed or overtaken (the hero is owner-supplied artwork; `/story` was deleted). Delete if the rationale is no longer wanted. |
| `docs/SALES_INVOICE_IMPORT.md`, `docs/SALES_INVOICE_UX_BLUEPRINT.md` | 41 KB | Design and import notes for the sales invoice editor. Not audits; the editor has moved on. Keep as design reference or delete at the owner's choice. |

## Why not simply delete everything under docs/

Because "an audit report" and "the only record of a decision" look the same from outside. Of the 38 top-level documents, 13 are the only statement of something true that CLAUDE.md does not carry. Deleting them would not make anything wrong today; it would make the next change to that area start from a guess.

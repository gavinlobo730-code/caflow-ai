# Deletion plan for the audit, finding and plan documents

**Nothing here has been done.** This is the proposal, written so the decision can be made once. Deleting is cheap to reverse (git history keeps everything) but it is not free: tests, scripts and hundreds of code comments name some of these files, and a handful of the "audit" documents are in fact the only written record of a design decision. Where this plan says KEEP it says why.

## Verdict in one paragraph

Delete the **status snapshots** — everything under `docs/audits/` (4.0 MB, including 1.9 MB of finding JSON), the overnight-run log and the stale question files under `docs/plan/`, and the early completion and audit reports at the top of `docs/` — once the ledger is accepted. Their open items are in `docs/open-items/`; what they proved closed is in `checked-closed.md`; their history stays in git under a tag. **Do not** delete `docs/compliance/` (the statutory playbook and the committed primary-source texts), `docs/architecture/`, `docs/operations/`, `docs/deploy-migrations.md`, `docs/schema-drift.md`, `docs/plan/THE-PLAN.md` (a required test reads it and it holds decisions D1–D27), or the design-record documents listed under KEEP: they answer "why is it built this way?", which the ledger deliberately does not.

## What must happen first

1. **The owner reads and accepts the ledger** (or asks for changes). Nothing below should be done before that.
2. **Tag the history**: `git tag audit-archive-2026-10-02 <main sha>` and push the tag, so any deleted file is recoverable with `git show audit-archive-2026-10-02:docs/audits/<file>`. Pushing a tag is outward-facing, so it needs the owner's go-ahead.
3. **Preserve the Amendment v1.1 design record** (it is a ledger item): `BATCH_6_*`, `BATCH_7_*`, `REVENUE_OPS_BRIDGE.md` and `PRACTICE_CLIENT_VISIBILITY_DECISION.md` are the only design record of the internal practice client, guardrails G1–G4, the billing lifecycle and idempotency keys, collections and AR rules and knowledge-base versioning; CLAUDE.md carries almost none of it. Fold it into `docs/architecture/` first; then the four BATCH_6/7 files can go.
4. **Remove `scripts/findings_status_md.py`** together with the findings files it reads, and replace the audit table and the "`docs/audits/findings-status.*` is where to start" paragraph in CLAUDE.md with a pointer to `docs/open-items/README.md`.
5. **Do not edit migration files** to repair comments that name a deleted document (a migration's checksum is its identity). About 45 source files, test docstrings and migration headers mention `docs/audits/…`; they are comments, not reads, and will simply dangle. Checked on 2 Oct 2026: **no test or script opens any file under `docs/audits/`** (the only reader is `scripts/findings_status_md.py`). Optionally sweep the source-file comments afterwards.
6. Run the full backend and web suites on the branch that deletes, and ship it as an ordinary pull request.

## DELETE after the ledger is accepted

| path | size | why it is safe |
|---|---|---|
| `docs/audits/` (everything: the 2026-07 to 2026-09 audits, `2026-09-07-findings/`, `2026-09-07-market-research/`, `2026-09-12-the-probe-pass/`, `findings-status.json` and `.md`, `WHERE-WE-STOPPED.md`, `OPEN-QUESTIONS.md`, `questions-for-the-owner.md`, `what-to-fetch-for-me.md`, the checkpoint, the phase plans, the verification pass) | 3883 KB | Dated snapshots, each already measured stale. Their open items were extracted into the ledger (every raw item accounted for by a script); closed items and answered questions are recorded in `checked-closed.md`. The 2026-09-07 market research is search-engine summaries (nothing in it is graded primary) and its re-verify lists are ledger items. |
| `docs/plan/2026-09-24-overnight-run.md` | 48 KB | Log or question file; open questions are ledger items and answered ones are in `checked-closed.md`. |
| `docs/plan/QUESTIONS.md` | 4 KB | Log or question file; open questions are ledger items and answered ones are in `checked-closed.md`. |
| `docs/plan/STUCK.md` | 11 KB | Log or question file; open questions are ledger items and answered ones are in `checked-closed.md`. |
| `docs/plan/2026-09-13-questions-for-the-owner.md` | 7 KB | Log or question file; open questions are ledger items and answered ones are in `checked-closed.md`. |
| top-level early reports: `BATCH_1_COMPLETION_REPORT.md`, `BATCH_2_COMPLETION_REPORT.md`, `BATCH_2_1_HARDENING_REPORT.md`, `BATCH_3_COMPLETION_REPORT.md`, `BATCH_3_1_HARDENING_REPORT.md`, `BATCH_4_COMPLETION_REPORT.md`, `BATCH_5_COMPLETION_REPORT.md`, `PHASE_5_1_SECURITY_REMEDIATION_REPORT.md`, `PHASE_5_2_E2E_TEST_REPORT.md`, `PHASE_5_2_E2E_UAT_PLAN.md`, `PHASE_5_2_WS1_E2E_COVERAGE_REPORT.md`, `PHASE_5_2_WS4_RELEASE_READINESS.md`, `DEAD_CODE_AUDIT.md`, `DEPLOYMENT_READINESS_AUDIT_v1_1.md`, `LOADING_UX_AUDIT.md`, `ENGAGEMENT_ARCHITECTURE_AUDIT.md`, `PRACTICESYNC_AUDIT_v1.md`, `QUICKBOOKS_ACCOUNTING_ROADMAP.md`, `security_audit_phase13b.md` | 142 KB | Completion, hardening, E2E and audit reports of the early build; closed or superseded, with the open residue in the ledger. `security_audit_phase13b.md` is now factually wrong (migration 154 replaced its RLS predicate). |

## HOLD until a named prerequisite is done

| path | size | prerequisite |
|---|---|---|
| `BATCH_6_COMPLETION_REPORT.md`, `BATCH_6_DESIGN_REVIEW.md`, `BATCH_7_COMPLETION_REPORT.md`, `BATCH_7_DESIGN_REVIEW.md` | 41 KB | Fold the Amendment v1.1 design record into `docs/architecture/` first (step 3 above). |

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

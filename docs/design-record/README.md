# Design record

The long per-area decision records that used to sit in `CLAUDE.md`, moved here **verbatim** on 10 October 2026 so that
`CLAUDE.md` (which every session loads) stays small. Each entry is one block of the old file, in its original order, under
the section it came from. Nothing was rewritten, and a test (`test_the_design_record_index_matches_the_files_and_claude_md_stays_small`)
keeps the index in `CLAUDE.md` and these files in step.

**Open the file for an area before changing it.** `CLAUDE.md` has the rules that apply everywhere and a "Design record
index" that lists every entry here by its one-line headline.

Where an entry says "this file" or "CLAUDE.md" it means the design record as a whole (`CLAUDE.md` plus this directory).
References such as "the bullet above" were relative to the old order and may now point into a neighbouring file; the
headline in the index is the way to find the one meant. Finding ids quoted in an entry (`GST-18`, `PAY-27`) name findings in
the audit record deleted on 8 October 2026, recoverable with `git show 315e6a19:<path>`.

To add a long write-up: put it in the matching file, add its headline to the index in `CLAUDE.md`, and keep `CLAUDE.md`
itself to the rule in one line.

| file | entries | what it holds |
|---|---|---|
| [`ai.md`](ai.md) | 5 | AI providers, the model gateway, redaction, budgets and what a model may and may not do |
| [`annual-update-and-statutory-data.md`](annual-update-and-statutory-data.md) | 3 | What changes every financial year and the statutory data a human must supply |
| [`banking-and-multicurrency.md`](banking-and-multicurrency.md) | 5 | Bank entries, credit card accounts, matching rules, multi-currency and the AS 11 revaluation |
| [`banking.md`](banking.md) | 1 | Bank data: Account Aggregator position, bank entries, credit cards, matching rules |
| [`deployment-and-operations.md`](deployment-and-operations.md) | 5 | Deployment, monitoring, request ids, service levels, runbooks and security headers |
| [`documents-sales-purchase.md`](documents-sales-purchase.md) | 10 | Sales and purchase documents and cycles, templates, supplier master, ledger drill-through |
| [`engineering-and-ci.md`](engineering-and-ci.md) | 4 | Tests, lint and coverage ratchets, CI, dependency lock, migrations and the schema-drift check |
| [`filing-and-compliance.md`](filing-and-compliance.md) | 2 | Filing to government portals, trackers and the period lock |
| [`fixed-assets-and-inventory.md`](fixed-assets-and-inventory.md) | 11 | Fixed assets, capital work in progress, stock costing, ageing, godowns, batches and counts |
| [`frontend.md`](frontend.md) | 4 | Frontend rules: payload shapes, the browser's second data path, money input, loading and recurring screens |
| [`identifiers.md`](identifiers.md) | 3 | Identifiers: GSTIN, UAN, IFSC, party identifiers in imports, the firm's own GSTIN, FY and AY labels, ITR forms |
| [`ledger-and-money.md`](ledger-and-money.md) | 5 | The general ledger, posting kernel, period locks, money columns, reports and interest/cheque/price-list features |
| [`opening-balances-and-imports.md`](opening-balances-and-imports.md) | 2 | Opening balances as documents and the bulk imports of a migrated client's books |
| [`payroll.md`](payroll.md) | 7 | Payroll: accrual, PF on actual wages, bonus, monthly review, declarations |
| [`reporting.md`](reporting.md) | 5 | Reporting: Schedule III captions, report performance, paging, exports |
| [`screens-and-site.md`](screens-and-site.md) | 14 | Screens that state what they read, double-click and keyboard rules, the public site's claims, dates and empty states |
| [`tax-gst.md`](tax-gst.md) | 34 | GST: returns, e-invoice and e-way, ITC and the 2B reconciliation, late fees, HSN and UQC, registrations |
| [`tax-income-tax.md`](tax-income-tax.md) | 13 | Income tax: ITR kinds and engines, capital gains, tax audit and 3CD, losses, entity reliefs, section 43B(h) |
| [`tax-tds.md`](tax-tds.md) | 11 | TDS and TCS: sections and thresholds, the 2026 vocabulary fork, interest, 26AS |
| [`tenancy-and-security.md`](tenancy-and-security.md) | 15 | Tenancy, per-person access, principals, RLS tests, uploads, PIN, sessions and storage |
| [`workflow-and-team.md`](workflow-and-team.md) | 3 | Workflow engine slices and the Team screen's permission notice |

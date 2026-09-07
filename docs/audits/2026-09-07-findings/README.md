# Structured findings, 7 September 2026

Machine-readable output of the eight subsystem readers behind
`../2026-09-07-where-we-are-against-the-one-platform-goal.md`. Load these into the
issue tracker rather than re-deriving them.

**These are single-source.** The adversarial verification pass covered 27 findings
before the session's model allowance ran out; `verification-verdicts.json` holds
those verdicts, keyed by finding id. Fifteen of the nineteen CRITICAL findings were
separately reproduced by hand — see §4 of the report. Everything else is a lead with
evidence, not a settled defect.

| File | Subsystem | Grade | Findings |
|---|---|:--:|--:|
| `accounting-core-posting-kernel-journal.json` | Accounting core: posting kernel, journals, chart of accounts | B | 27 |
| `banking-statement-import-csv-xlsx-pd.json` | Banking — statement import (CSV/XLSX/PDF/vision), normalisat | B | 29 |
| `gst-gstr-1-builder-gstr-3b-computer.json` | GST — GSTR-1 builder, GSTR-3B computer, GSTR-9, 2A/2B reconc | C | 32 |
| `income-tax-and-itr-computation-works.json` | "Income tax and ITR — computation workspace, ITR engine and  | C | 34 |
| `payroll-employee-master-salary-struc.json` | Payroll — employee master, salary structures, attendance and | C | 30 |
| `purchase-cycle-vendors-purchase-bill.json` | Purchase cycle — vendors, purchase bills, purchase credit/de | C | 32 |
| `sales-cycle-customers-sales-invoices.json` | Sales cycle: customers, sales invoices, credit/debit notes,  | C | 32 |
| `tds-tcs-section-rates-and-thresholds.json` | TDS/TCS — section rates and thresholds, TDS computer and val | C | 32 |

## Schema

Each file: `subsystem`, `what_exists`, `maturity` (grade, rationale,
would_a_ca_buy_this_module_alone), `strengths[]`, `findings[]`,
`test_coverage_notes`, `open_questions_for_owner[]`.

Each finding: `id`, `kind` (bug | glitch | gap | missing_feature | fine_tune |
security | data_integrity | performance | ux), `severity` (critical | high | medium
| low), `title`, `evidence` (file:line), `ca_experience`, `market_standard`,
`confidence`, `suggested_fix`, `effort`.

Not covered by a reader, and needing a second pass: reporting and year-end,
practice management, the AI layer, fixed assets and inventory, portals and identity,
platform and security, the frontend as a whole, the marketing site.

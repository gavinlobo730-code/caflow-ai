# Structured findings, 7 September 2026

Nine subsystem readers behind `../2026-09-07-where-we-are-against-the-one-platform-goal.md`,
**all 278 findings adversarially verified**. Load these into the issue tracker rather
than re-deriving them.

## Verification status

Every finding was re-read by an independent verifier under three lenses — literal
(does the code do this?), guards (is something else already preventing it?) and reach
(does it get to a user?) — instructed to REFUTE rather than confirm and to default to
refuted where the code could not be made to say it. Twenty criticals were separately
reproduced by hand; see §4 and §13 of the report.

**3 refuted. 45 severities corrected down, 6 up. 275 findings survive.**

Each finding carries a `verification` block:

```json
{"status": "confirmed|refuted", "by": "hand|agent", "corrected_severity": "...",
 "what_is_actually_true": "... with file:line", "probe": "what was run and what it printed"}
```

| File | Subsystem | Grade | Findings | Confirmed | Refuted |
|---|---|:--:|--:|--:|--:|
| `accounting-core-posting-kernel-journal.json` | Accounting core: posting kernel, journals, chart of  | B | 27 | 27 | 0 |
| `banking-statement-import-csv-xlsx-pd.json` | Banking — statement import (CSV/XLSX/PDF/vision), no | B | 29 | 29 | 0 |
| `fixed-assets-and-inventory.json` | Fixed assets and inventory | C | 30 | 30 | 0 |
| `gst-gstr-1-builder-gstr-3b-computer.json` | GST — GSTR-1 builder, GSTR-3B computer, GSTR-9, 2A/2 | C | 32 | 31 | 1 |
| `income-tax-and-itr-computation-works.json` | "Income tax and ITR — computation workspace, ITR eng | C | 34 | 34 | 0 |
| `payroll-employee-master-salary-struc.json` | Payroll — employee master, salary structures, attend | C | 30 | 30 | 0 |
| `purchase-cycle-vendors-purchase-bill.json` | Purchase cycle — vendors, purchase bills, purchase c | C | 32 | 31 | 1 |
| `sales-cycle-customers-sales-invoices.json` | Sales cycle: customers, sales invoices, credit/debit | C | 32 | 31 | 1 |
| `tds-tcs-section-rates-and-thresholds.json` | TDS/TCS — section rates and thresholds, TDS computer | C | 32 | 32 | 0 |

## Schema

Each file: `subsystem`, `what_exists`, `maturity` (grade, rationale,
would_a_ca_buy_this_module_alone), `strengths[]`, `findings[]`,
`test_coverage_notes`, `open_questions_for_owner[]`.

Each finding: `id`, `kind` (bug | glitch | gap | missing_feature | fine_tune |
security | data_integrity | performance | ux), `severity` (critical | high | medium
| low), `title`, `evidence` (file:line), `ca_experience`, `market_standard`,
`confidence`, `suggested_fix`, `effort`, `verification`.

**Sort by `verification.corrected_severity`, not `severity`** — 43 of them differ.

`verification-verdicts.json` holds the first pass's raw verdicts, keyed by finding id.

## Still not covered by any reader

Reporting and year-end, practice management, the AI layer, portals and identity,
platform and security, the frontend as a whole, the marketing site. A second pass
over those seven is the first thing to do after Stage 1.

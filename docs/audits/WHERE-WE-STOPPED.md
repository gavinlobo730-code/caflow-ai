# Where the phase work stopped — 11 September 2026

**Written at the owner's request, mid-Phase 11h, so the thread survives a break
of any length.** Read this first when picking the work back up; then
`docs/audits/2026-09-08c-the-phase-plan.md` for the plan and
`docs/audits/OPEN-QUESTIONS.md` for everything waiting on a human.

## Merged, on `main`

| Phase | Finding | What it did | PR |
|---|---|---|---|
| 11a | PUR-10 | an advance to a contractor withholds | #476 |
| 11b | TDS-06, TDS-09 | the challan a deductee sits under, and the 27Q builder | #477 |
| 11c | PUR-07 ≡ TDS-13 | a §197 certificate is a rate, a number, a period AND an amount | #478 |
| 12a | ACC-21, ACC-27, ACC-12 | one answer to "is this period closed" (migrations 360, 361) | #479 |
| 12b | ACC-17, GST-09 | a report is scoped to its caller; an early GSTR-9 shuts the window | #480 |
| 11d | PUR-09, SALES-05, PAY-09 | the number is already right; stop recomputing it | #481 |
| 11e | INV-06, PAY-14 | a §17(5)(h) reversal reaches GSTR-3B; a leaver's TDS reaches 24Q (migration 362) | #482 |
| 11f | INV-01 | closing stock as at a date; the ledger balance foots (migration 363) | #483 |
| 11g | SALES-11 | invoice discounts under §15(3)(a) (migration 364) | #484 |

## In flight — Phase 11h (ACC-10), committed but NOT merged

One source for Schedule III classification. **The code is green** — 11,890
backend mock tests, the frontend suite, and the PG column guards all pass — and
it is committed on `claude/ca-platform-audit-roadmap-yuoad3`. It has no PR yet.

### What is done

* **`domain/reporting/schedule_iii.py`** — the caption VOCABULARY
  (`BALANCE_SHEET_CAPTIONS`, `PROFIT_LOSS_CAPTIONS`, `CAPTIONS`,
  `RESIDUAL_CAPTIONS`) and `classify()`, which returns the caption AND the basis
  (`"mapping"` | `"subtype"` | `"residual"`).
* **The CA's own `chart_of_accounts.schedule_iii_mapping` is now read**, and
  outranks the free-text subtype scan — it was previously written by the CSV
  importer, shown on a read-only screen, and read by no computation at all.
  Honoured only on the statement the account belongs to.
* **It travels**: `Account` carries it, the reporting source selects it, both
  statement builders resolve the caption through `classify`, and
  `bucket_amounts` groups by the caption the builder put on the line instead of
  re-deriving it from the subtype.
* **The account PATCH accepts it** (`AccountUpdateIn.schedule_iii_mapping`),
  validated against `CAPTIONS` — so a mapping can be corrected without
  re-importing the whole chart of accounts. `""` clears it.
* **A real defect found and fixed**: `pl_bucket` returns
  `"Cost of Materials Consumed"` while `_CAPTION_TO_SCHEDULE_LINE`'s key said
  `"Cost of Materials"`, and the lookup's fallback was
  `"other_current_assets"` — so on a trading or manufacturing client the single
  largest expense on the P&L was classified as a CURRENT ASSET in the year-end
  financial statements. Profit overstated by the whole cost of materials and a
  phantom asset of the same amount. Nothing failed and nothing warned.
* **A second one**: `routers/year_end_mappings` read the `accounts` VIEW, which
  migration 016 created as `SELECT * FROM chart_of_accounts`. Postgres freezes a
  view's `*` at creation, so it carries only the columns that existed then —
  `schedule_iii_mapping` (migration 057) is not among them. Now reads the table.
* **Guards**: `tests/test_one_schedule_iii_vocabulary.py` (420 cases) asserts
  the buckets return only declared captions, every declared caption is
  reachable, and every translation table is TOTAL over the vocabulary — which is
  what would have caught the cost-of-materials defect.
  `tests/test_the_mapping_screen_moves_the_balance_sheet.py` walks the whole
  chain and asserts the RUPEES land on the caption the CA chose.

### What is NOT done, and is what to pick up

1. **No migration.** None is needed for the above — but see (3).
2. **The Schedule III Mapping screen is still read-only.** The backend now
   accepts a mapping on `PATCH /api/accounting/accounts/{id}`; the screen has to
   call it. That is the remaining visible half of ACC-10.
3. **`schedule_iii_mapping` has no CHECK constraint.** The Pydantic validator
   refuses a non-caption on the API path, and the classifier ignores one, but
   the CSV importer writes the column directly. A CHECK would make the column
   honest at rest; it needs a migration and a look at what production already
   holds in it.
4. **The residual count is computed but not surfaced.** `classify` returns the
   basis and the builders put `schedule_iii_basis` on every line — nothing yet
   reports "N balances are on an Other line because nobody decided", which is
   what would make the mapping screen's green count mean something.
5. **No negative control run yet** for 11h, and no PR.

## Phase 11's remaining features, after 11h

`ACC-06` (recurring journals, budgets and retainers out of browser
localStorage), `PUR-15` (§43B(h) MSME tracker), `GST-11` (QRMP), `GST-10`
(GSTR-9), `IT-19` (§54 reinvestment exemptions), then the two months-sized ones:
`IT-11` (Form 3CD) and `GST-20` (multi-GSTIN).

## The two things waiting on the owner

* **E1** — Render deploys fail on a health-check timeout, DIAGNOSED. The fix
  (move the boot work out of module import into a lifespan hook) touches how a
  live service boots and is the owner's call. `OPEN-QUESTIONS.md` §E1.
* **The backend is behind `main`** until somebody clicks Manual Deploy on Render.
  Migrations apply regardless, through a separate GitHub Actions job.

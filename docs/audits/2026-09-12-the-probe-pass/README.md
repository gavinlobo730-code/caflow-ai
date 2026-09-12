# The probe pass — 12 September 2026

Sixty-five findings from `2026-09-07-findings/` re-read against `99ac94b5` by four
read-only agents, one per subsystem. This is a **second** verification pass on top of
`2026-09-11-the-verification-pass.md`, and it exists because that pass re-scored
findings without asking a question this one asks of every single item: **is the
finding's own suggested FIX sound?**

That turned out to matter more than staleness. A stale finding costs an hour of
re-reading. A finding whose suggested fix is wrong costs a regression, and two of
them here would have broken something that currently works.

Each subsystem file carries, per finding: `VERDICT / EVIDENCE / PREMISE / SHAPE /
SIZE`, with file:line for every claim.

| File | Findings | Closed | Notes |
|---|---|---|---|
| `banking.md` | 15 | 0 | none stale; two premises materially wrong |
| `accounting-and-inventory.md` | 16 | 0 (3 partial) | two findings have a **false fix** |
| `gst.md` | 16 | 1 (4 partial) | ~25% stale, one escalation |
| `purchases.md` | 18 | 4 | 22% stale; four new cross-subsystem duplicates |

## 1. The two false fixes — do NOT implement these as written

**ACC-23** says: "make the Balance Sheet stop synthesising the retained-earnings line
once a closing entry exists for the year — otherwise it would double count." It would
not double count. `year_end_financial_service.py:634-645` explains why and
`tests/test_year_end_financial_service.py:614-647`
(`test_a_manually_posted_closing_entry_is_not_double_counted`) pins it: deriving is
self-correcting, because the close reduces cumulative PAT by P at the same moment it
credits equity by P. **Implementing the "stop synthesising" half is what would break
the balance sheet.** Two further limbs of ACC-23 are also false — the Schedule III
reserves split already exists, and appropriations are postable today as manual
journals. The real residue is one line of UI: render `closing_entry_dates`, which is
already computed and already typed. **Do not touch `builders.py`.**

**ACC-25** says: attach files to a manual journal by uploading to the Documents bucket
and sending `[{name, url}]`. That payload is the exact failure
`domain/banking/attachments.py:23-34` was written to refuse — the bucket hands back a
**signed URL that expires in an hour**, so the attachment is a dead link by the time
anyone audits the entry, and `journal_entries.attachments` has no validation at any
layer (`models/accounting.py:277` is a bare `list[dict]`; `migrations/138` adds plain
jsonb with no CHECK), so a `javascript:`/`data:` URL is stored XSS. The working shape
is `{name, document_id}` — `apps/web/components/banking/EntryDetailModal.tsx:124`.
Reuse the banking validators; they are pure and module-agnostic.

## 2. Blockers the findings do not mention

**ACC-16** (`journal_lines.line_no`) — its suggested backfill is **refused outright**.
`migrations/251_restore_posted_journal_line_immutability.sql:105-109` puts
`trg_prevent_posted_journal_line_update` `BEFORE UPDATE OR DELETE` on `journal_lines`,
raising on any row whose parent is posted. A backfill UPDATE therefore fails for every
posted line in the database. 251's own header names the only legitimate route: a
migration that deliberately disables the trigger — "a rare, reviewable act". So the
shape is: add the column with a default (catalog-only in PG11+, no trigger fires),
DISABLE TRIGGER, backfill by `id`, re-enable, then `NOT NULL`.

**BANK-10** — the fix wants to band on "outstanding". `_banded`
(`bank_matching_service.py:220-231`) builds a PostgREST filter on **one named column**,
and outstanding is not a column on either table. Either add a generated column
(migration on `client_sales_invoices` and `purchase_bills`) or filter in Python — but
the Python route breaks `_pool_limit`, because the DB applies the cap before the Python
filter runs.

**PUR-22** — building the multi-bill payment UI as "create, then PATCH /allocate" is
**not** equivalent to creating an allocated payment. `purchase_payments.py:447` sets
`unallocated_paise = amount_paise` when there is no `purchase_bill_id`, which fires the
§194 advance-withholding branch and deducts tax on the whole payment. A later
allocation does not undo it, so one NEFT against many bills would withhold twice. Add
`allocations` to `PurchasePaymentIn` and route create through `create_payment_core`.

**PUR-20 / SALES-20** (cess) — the receive journal must still foot.
`tests/test_accounting_audit_fixes.py:71` asserts the trial balance balances. Adding
cess to the payable without a matching Dr GST Input (cess) leg breaks it, and neither
finding mentions the journal leg.

**INV-05** (freight into stock cost) — CLAUDE.md's own rule binds it: "Σ
`value_delta_paise` to a date is what ties to the Inventory control account." So
apportioned freight cannot just be added to `record_stock_in`'s total — the same amount
must flow into `post_inventory_receipt_journal_entry`'s `items[].value_paise` and be
credited to the freight account, or `stock_position_as_at` and
`check_missing_inventory_receipt_journals` both start reporting drift.

**BANK-29 / BANK-14** — both touch the statement row set that
`domain/banking/tie_out.py` walks. Dropping an opening-balance row changes the first
balance the tie-out sees; merging PDF pages changes row order. The tie-out tests are
the invariant, and are why neither is a one-liner you land unverified.

## 3. Premises that are materially FALSE

**PUR-28** — "no assignment-scope policy on any of the six Purchases tables" is wrong
for **four** of them. `purchase_bills`, `purchase_payments`, `vendors` and
`service_catalogue` all carry one in the production fixture. The mechanism is
`migrations/084_assignment_scoped_rls.sql:75-95`, a one-shot `DO` loop over
`information_schema.columns WHERE column_name = 'client_id'` — it caught everything
that existed in 2024. `debit_notes` (145) and `purchase_credit_notes` (210) came later
and were never picked up. **A fix built on the stated premise might `DROP POLICY IF
EXISTS` the four live ones.** The real hole is two tables, and the durable fix the
finding misses is a completeness guard: 084's loop never re-runs, and no test
enumerates `client_id` tables against assignment-scope coverage.

**BANK-21** — false in two of three claims. Migration 342 already built
`ledger_shape_for_bank` (`routers/banking.py:244-251`), so a card would get a Liability
ledger; and `domain/banking/posting_map.py:43-78` is purely directional, so no
posting-map change is needed. What is real: the CHECK (in **two** migrations, 054 and
093), the picker, and a **Schedule III subtype decision** — `'Bank Overdraft'` was
chosen because `bs_bucket()` substring-scans for "overdraft", which would file a credit
card under "loans repayable on demand from banks". That is the work the finding never
names.

**BANK-26** — there are **seven** adapters, of which only four name a bank; the other
three are shape-based and cover a lot of co-op and PSU exports. And the fix is cheaper
than described: `bank_statement_column_mappings` already carries `firm_id`, so a
firm-scoped fallback is a read-only change in `find_mapping` plus two call sites, no
migration. It must match on **fingerprint** exactly and never fall back on bank name.

**ACC-26** — sound on the defect, false on the consequence: `useLedgerSpan.ts` catches
the error and the period picker falls back to the FY. Zero production reach.

**INV-09** — the stated drift is false; `running_qty_units` is the same NUMERIC(10,3)
column re-read every movement. The real residue is that `unit_cost_paise` is computed
from the unrounded Decimal while the stored quantity is rounded to 3dp.

**PUR-29 / PUR-31** — closed by the finding being **wrong**, not by a fix. PUR-29
searched for purchase tests by filename and concluded the RCM/§17(5) branches were
untested; `tests/test_accounting_audit_fixes.py:55,66` and
`tests/test_r239_gst_computation_gaps.py:177` drive `create_purchase_bill` directly.

**GST-17** — "the thresholds are the pre-2021 ones" is wrong; the ₹5 crore → 6 digits
rung IS current Notification 78/2020. Only the bottom rung is stale. And the
wrong-threshold half has **zero live effect**, because the value feeds only a slice
that can never shorten a string and the input is hardcoded `0` on the web path.

## 4. One escalation

**GST-15 moved the WRONG way.** Its only mitigation was that the enabling data was
unreachable from the product. It is reachable now:
`apps/web/components/ClientFormModal.tsx:180-181` is a checkbox writing
`gst_advance_tax_applicable`, and `apps/web/app/clients/[id]/sales/page.tsx:3615-3616`
writes `gst_rate_bps` and `place_of_supply` onto the receipt. So a CA can tick the box
and **GSTR-1 will declare a Table 11A liability that GSTR-3B 3.1(a) never pays.** That
is a live contradiction between two returns filed for the same period, not a latent
one. It deserves promotion above medium.

## 5. Four new cross-subsystem duplicates

Beyond the PUR-07 ≡ TDS-13 and IT-09 ≡ FA-06 pairs the phase plan already names:

| Pair | One defect, two entries |
|---|---|
| **PUR-23 ≡ TDS-32** | purchase notes never reverse TDS. PUR-23 is the `tds_deductions` register half, TDS-32 the 26Q half. Fixing either alone leaves the other's symptom |
| **PUR-18 ≡ GST-24** | the same three lines at `gstr3b_computer.py:316-317`. PUR-18 adds the Bill of Entry, GST-24 adds ISD |
| **PUR-20 ≡ SALES-20** | the same missing cess column, inward and outward. 3B's cess line is only right if both land |
| **PUR-22 ≡ SALES-14** | an allocation endpoint on each side that no screen calls. Same UI shape, same advance-withholding trap |

## 6. Two shared blockers worth doing once

- **GST-17 + GST-32** both need the client's **annual aggregate turnover**, which the
  product does not store (`apps/web/lib/data/gst.ts:592` hardcodes
  `aggregate_turnover_paise: 0`). One `clients` column unblocks the HSN digit rule and
  the e-invoice eligibility/30-day check together.
- **GST-21** (`domain/gst/interest.py`, §50 and §47) blocks **GST-28**'s interest
  column. Build the interest module once.

## 7. One defect with no finding at all

`migrations/055_v131_hardening.sql:79` and `:100` create indexes
`ON bank_transactions (client_id, bank_account_id, txn_date, …)`. **Neither column
exists on that table** — it has `transaction_date`, and no `bank_account_id` at all
(confirmed against the production database on 12-09-2026: 15 live indexes, none
matching either declaration). Those two statements never took effect. Do not quote
index coverage on `bank_transactions` from migration 055.

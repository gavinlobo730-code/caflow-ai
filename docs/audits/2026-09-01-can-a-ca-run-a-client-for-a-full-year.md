# Can a CA actually run a client on this for a full financial year?

> **Status, 1 September 2026 (same day):** every finding below has been fixed —
> migrations 306 and 307, the migration runner's failure memory, the error
> classifier, the orphan-journal sweep, the signposted onboarding chain, and a
> tenant-scoped accounts endpoint. The findings are left as written, in the
> present tense they were found in, because the reasoning is the record. Each
> section now ends with a **Fixed** line naming the commit.

**Date:** 1 September 2026
**Method:** one client driven through FY 2025-26 over the real API, not a code read.
**Verdict:** the accounting engine and the statutory reporting are sound. Three
things stop a CA before they get there, and one of them is live in production.

---

## How this was run, and what that buys

The earlier client-workspace audit was a reading of screens and code. This one
drives the software.

A local stack was stood up so nothing touched production data:

```
FastAPI (the real app)  ->  PostgREST 12.2.3  ->  Postgres 16 with migrations 001..305
```

`apps/api` speaks only PostgREST, so a real PostgREST binary in front of a real
migrated Postgres exercises the true data path — RLS, GRANTs, SQL functions,
`post_journal_atomic`, the lot. Exactly one thing was replaced: identity.
Supabase Auth's JWKS has no local equivalent, so `get_current_user` was
overridden with the Test Firm's Partner via FastAPI's `dependency_overrides`.
`rbac()` still runs its permission check on that role; every router, service and
the posting kernel are untouched.

Everything below was reached by HTTP calls in the order a CA would make them.
Where a finding could be a harness artefact rather than a product defect, it was
checked against the live database and is labelled accordingly.

**The client:** Tirupati Precision Components Pvt Ltd, a Pune manufacturer,
GSTIN `27AABCT1332L1ZE` (real check digit), two customers (one intra-state, one
inter-state), two vendors (one on 194C), one bank account, FY 2025-26.

---

## What worked, first, because most of it did

| Step | Result |
|---|---|
| Create client, customers, vendors, bank account | clean |
| Opening balances | **auto-posted and balanced** — Bank 25,00,000 Dr / Receivables 12,00,000 Dr / Payables 8,00,000 Cr / Opening Balance Equity 29,00,000 Cr, with a per-client bank ledger account created for it |
| 18 sales invoices, intra- and inter-state | correct CGST/SGST vs IGST split |
| 24 purchase bills | correct, and raw-material bills raised their own inventory-capitalisation journals |
| Trial balance at 31-03-2026 | balanced, difference 0 |
| Balance sheet | balanced |
| Cash flow | reconciles |
| **TDS computation** | **correct and careful** — see below |
| Schedule III statements | built, with comparatives |
| Ageing schedules | built; correctly refused to place unclassified vendors in either MSMED row and said so |
| Ratio note (clause (Q)) | 11 ratios with the right gaps |
| Multi-year trend | found 2025-26, dropped 2023-24 and 2024-25 as having no records |

The TDS engine deserves singling out. Across twelve job-work bills it held off
while the §194C ₹1,00,000 FY aggregate was unmet (bills 1–5 nil), deducted from
bill 6 onward, and floored the rate at **20% under §206AA** because the vendor
had no PAN on file. That is three statutory rules composed correctly without
being asked.

---

## The blockers

### 1. `service_role` cannot write the five money-movement tables — in production

**This one is live.** Verified against the production project, not just the harness.

`service_role` holds `REFERENCES, SELECT, TRIGGER, TRUNCATE` — and **no INSERT,
UPDATE or DELETE** — on:

`receipts` · `receipt_allocations` · `purchase_bills` · `purchase_payments` · `credit_notes`

Every other public table has the write grants. All 24 purchase bills in this
walkthrough failed with `42501 permission denied for table purchase_bills`. One
`GRANT` and all 24 posted.

**How it got there**, from the migrations themselves:

- **050** created these tables and granted only to `authenticated`.
- **096** noticed *reads* failing ("the first read (receipts) raised") and granted
  `SELECT`. Reads fixed; writes not.
- **193** hit the same class of bug on `debit_notes` and its header describes it
  exactly — the base GRANT was never issued, so access is *"rejected by Postgres
  before RLS was even evaluated."* It granted to `authenticated` only.

So the hole has been found twice and patched narrowly twice.

**What it means depends on `USE_USER_JWT`**, whose production value is set in the
Render dashboard (`render.yaml` has `sync: false`) and could not be read from
here. With the flag **off** — the code default — every user-initiated write to
these five tables runs as `service_role` and fails. With it **on**,
browser-initiated writes run as `authenticated` and succeed, but
`get_service_supabase()` is still used for background jobs and privileged paths,
and those fail either way.

The production row counts fit the story: `client_sales_invoices` 5,662 and
`purchase_bills` 759 — both also written directly from the browser as
`authenticated` — against **`receipts` 0, `purchase_payments` 0, `credit_notes`
0**, none ever written, with the receipts screen posting to `/api/receipts/`
rather than writing direct. Consistent with the money-in path never having
worked through the API, though nobody having tried would look the same.

**Fix:** one migration granting `INSERT, UPDATE, DELETE` on the five to
`service_role`. **Systemic fix:** the schema drift check compares columns and
types but not GRANTs, which is why this survived two encounters.

**Fixed** — migration 306, plus a write-side invariant in
`test_r269_service_role_grants_pg.py` ("if `authenticated` can INSERT it,
`service_role` must be able to") so the next occurrence fails by shape rather
than by name. Verified applied to production.

### 2. The migration set cannot rebuild production, and the rebuild breaks journal reversal

Building a database from 001..305 does **not** reproduce production.

Migration **055** fails partway (a known, baselined failure). psql runs the
statements *before* the failure, one of which is `CREATE OR REPLACE FUNCTION
prevent_posted_journal_modification()` with the original body. Migration **213**
later replaces it with a version permitting exactly one change on a posted row —
the `is_reversed` FALSE→TRUE flip that `reverse_entry()` must make. But **a
failed migration never reaches its `INSERT INTO schema_migrations`**, so it is
never recorded and re-runs every time, re-installing the old body over 213's.

In the rebuilt schema, `update journal_entries set is_reversed = true` on a
posted row raises. `reverse_entry()` cannot complete, so **journal reversal — the
only sanctioned correction for a posted entry — is impossible.**

**Production is not affected.** Both guard functions there carry 213's
exemption; production was baselined by hand before the runner existed, so 055 is
recorded as applied and never re-runs.

What *is* affected: any database built from the migrations — disaster recovery, a
new region, a staging clone — and the **required** CI check `migration apply —
real Postgres 16`. CI is green against a schema that differs from production in a
way that breaks a core accounting feature.

**Fixed** — the runner records failures in `schema_migration_failures` and does
not retry a file that failed at the same checksum; editing it (the checksum
changes) or `--retry-failed` are the two ways back. The test asserts the
property rather than any guard's contract: a second run must not change any
function body or trigger definition.

### 3. A new client cannot record a single document until three prerequisites are met, in order

Creating the client, its customers, vendors and bank account all succeed. The
first invoice then returns `422 Product/Service is required on every line item.`
`service_catalogue_id` is mandatory on every line of a sales invoice, credit
note, debit note and purchase bill — a deliberate decision, recorded in
`models/invoices.py`.

Satisfying it reveals the next one: the catalogue refuses an HSN that is not in
the **firm's** HSN library. So the real order is

```
firm HSN library  ->  client service catalogue  ->  the first invoice
```

three levels deep, each discovered by failing the next. Nothing in client
onboarding walks this chain or seeds a starter set, and the invoice error names
what is missing but not where to create it. For a CA onboarding a client
mid-year with a backlog to key in, this stops them at document one.

**Fixed** (partly) — both errors now name the next step: the invoice points at
the "+ Add Product/Service" control and says a new client's catalogue starts
empty; the catalogue points at Settings > Firm HSN/SAC Library. The chain
itself is unchanged — it is a deliberate decision — only its discoverability.

### 4. `GET /api/accounting/accounts` serves demo data to every firm and client

`routers/accounting.py::list_accounts` returns the module-level `MOCK_ACCOUNTS`
list. It takes no `client_id`, no `firm_id`, and never touches the database. In
the walkthrough it returned 22 accounts for a client whose `chart_of_accounts`
table held **zero rows**.

Blast radius today is limited — it is defined in the frontend API client as
`api.accounting.accounts()` but no page appears to call it; the screens read
`chart_of_accounts` directly through PostgREST. It should read the tenant's
accounts or stop existing.

**Fixed** — all three verbs read and write the real table, firm-scoped, with
`client_id = X OR client_id IS NULL` transcribed from
`SupabaseLedgerSource._accounts` so the endpoint and the ledger cannot disagree
about what a client's chart is. POST and PATCH were the same lie from the other
direction: they wrote to the mock and reported success.

---

## The rest

**A rejected payment leaves a posted GL entry behind.** `create_purchase_payment`
posts the journal *first*, then inserts the payment row, compensating with an
append-only reversal on failure. Eleven payments were rejected by a CHECK
constraint; all eleven compensations failed, leaving eleven posted Payment
entries of ₹2,00,000 with nothing behind them — the bank read ₹3,00,000 against a
true ₹25,00,000. *The compensation failed for the harness-only reason in blocker
2*, so on production's schema it would very likely have self-healed. What the run
still shows is the shape of the risk: the ledger is written before the document,
every failure between the two depends on a compensating write succeeding, and
when it does not the books are wrong with only a log line saying so. The log line
is honest — *"manual reconciliation required, a phantom GL entry may remain"* —
but nothing surfaces it to the CA, and no sweep looks for Payment entries with no
payment behind them.

**TDS is withheld but never reaches the register.** The deduction lands on
`purchase_bills.tds_paise` and is netted off what the vendor is paid. But
`tds_deductions` is empty and **nothing in the codebase ever inserts into it** —
`routers/tds.py` and `tds_workspace.py` only read it, and tds_workspace's own
docstring says of the 26AS reconciliation that *"it does not reconcile against
`tds_deductions`, and it never has."* So there is no challan to pay by the 7th
and 26Q cannot be assembled. The money is withheld from the vendor in the books
and then invisible to the compliance side.

**Fixed** — the phantom-entry shape is now an eighth check in the daily
books-integrity reconciliation, reporting one finding with the total and the
list. It cannot prevent the gap; it stops the books being quietly wrong until
somebody reads a log.

**TDS is withheld but never reaches the register — fixed.** Migration 307 links
a deduction to its bill, and `tds_register_service` writes the row when the bill
is *received* (the credit, per §194C(3)) and removes it when the bill is
cancelled.

**The failure reached the CA as "Unable to create purchase bill. Please try
again."** A permission error is not transient and "try again" cannot work — the
24th attempt failed exactly like the first. The cause (SQLSTATE 42501, named
table) was logged and discarded before the response. The journal-entry path
already does better: `capture_posting_failure` plus a non-2xx carrying the
Postgres message.

**Fixed** — `document_failure_detail` classifies before it speaks: a database
business rule is surfaced verbatim, an infrastructure fault says it is a
configuration fault and asks for a report, and only a genuinely unclassified
failure still suggests a retry.

**Documents post nothing until separately issued or received.** All 42 documents
were created as drafts with `journal_entry_id` NULL; after a full year of keying
the trial balance held only opening balances. The separate step is defensible —
a draft should not hit the books — but nothing in the create response says so.

**`good`/`service` vs `goods`/`services`.** The catalogue's `kind` and the HSN
library's `hsn_type` spell the same distinction differently, minutes apart, and
each rejects the other's vocabulary. Costs a retry, not a wrong number.

---

## So: could I run a client on this?

**Yes for the books and the year-end.** Opening balances, a year of trading, the
GST split, inventory capitalisation, TDS computation, the trial balance, the
statements, and every Schedule III note including the ageing schedules, the
clause (Q) ratios and the multi-year trend — all of that worked on real data and
tied out.

**Not yet for the money and the filings.** I could not record a receipt or a
payment through the API at all, and that is a production grant, not a harness
quirk. TDS is deducted but there is nothing to file it from. And a CA onboarding
their first client hits a three-deep prerequisite chain with no signpost.

The gap between "the engine is right" and "a CA can run a client" is smaller
than it looks — one migration for the grants, one for the TDS register wiring,
and a signposted onboarding order. The engine is the hard part and it is done.

---

## What to do next, in order

1. **Grant the five tables to `service_role`.** One migration. Then add GRANTs to
   the schema drift check so it cannot happen a fourth time.
2. **Make a failed migration stop being re-run**, or fix 055 so it applies. Until
   then a rebuild does not match production and CI validates the wrong schema.
3. **Write `tds_deductions` when a bill deducts**, so the register, the challan
   and 26Q have something to read.
4. **Signpost the onboarding chain** — seed a starter HSN set and catalogue, or
   name the next screen in each error.
5. **Surface the phantom-entry log line**, and add a sweep for posted Payment or
   Receipt entries with no document behind them.
6. **Return the real cause on document-creation failures**, as the journal path does.
7. Make `/api/accounting/accounts` tenant-scoped or delete it.

## What this walkthrough did not cover

Payroll (covered end to end in `2026-09-01-payroll-can-it-run-a-year.md`), bank
statement import and reconciliation, GST return assembly beyond the ledger side,
fixed assets and depreciation, the year-end close and ITR. The stack is scripted
and the harness is reproducible, so those are a continuation rather than a
restart.

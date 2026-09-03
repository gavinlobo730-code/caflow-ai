# Converging the last guard differences

*3 September 2026. Migration 321, the end of the guard-drift first run.*

The comparison reports three categories where **both** sides have the object and
they disagree. Migrations 316–320 closed everything that was *missing*; this
closes what *differs*.

| Category | Before | After |
|---|---|---|
| `constraints_differ` | 29 | **0** |
| `policies_differ` | 30 | **0** |
| Policies production runs in the pre-053 form | 7 | **0** |

## 1. Twenty-nine foreign keys the migrations cascade and production does not

Every one is a `client_id`, `firm_id`, `job_id` or `itr_filing_id` key on the
tables Supabase Studio created. The migrations declare `ON DELETE CASCADE`;
production declares no action, which **refuses** the delete.

**Production is right.** Hard-deleting a client under `CASCADE` would silently
destroy that client's ITR filings, tax computation snapshots, disallowances,
deduction claims, XBRL packages, 26AS records and e-invoice/e-way records.
Those are statutory records. A refused delete is recoverable; a cascaded one is
not — and this product soft-deletes clients (`deleted_at`,
`status='archived'`) precisely so nothing has to be.

So the migrations converge downward. Nothing changes in production, which
already refuses; what changes is the CI template and every new environment,
which today would cascade.

**Two are deliberately left alone**, because production declares them
differently on purpose and the migrations already agree:
`tally_migration_jobs.client_id` and `gst_portal_snapshots.sync_job_id` are
`ON DELETE SET NULL`. A migration job outliving its client, and a snapshot
outliving the sync that produced it, are both meaningful.

## 2. Thirty policies: `PUBLIC` here, `authenticated` in production

The migrations' `CREATE POLICY` carries no `TO` clause, which means `PUBLIC` —
every role, `anon` included. Production grants each of these to `authenticated`
only.

Production is the stricter side and the one Supabase's own linter recommends,
so the declarations converge to it. Again a no-op there. What it prevents is a
future migration re-creating one of these from the repository and silently
**widening** it to anon.

All thirty differ in exactly this way and nothing else — no expression
differences hide among them, which is what made a mechanical convergence
defensible.

## 3. Seven tables where production runs the policy migration 053 replaced

Migration 050 created `firm_<table>` policies checking only `firm_id`.
Migration 053 dropped them and substituted `firm_client_isolation`, which
additionally requires the client to belong to the firm. **Production never
received 053's replacement** — it still runs the 050 policy under the old name.

So here, uniquely in this series, production is the side that moves: each table
gains `firm_client_isolation` and loses the superseded name, in that order, so
the table is never momentarily unguarded.

Checked against production before writing:

| Table | Rows | Would be excluded |
|---|---|---|
| client_sales_invoices | 5,662 | 0 |
| client_sales_invoice_lines | 9,495 | 0 |
| purchase_bills | 759 | 0 |
| receipts, receipt_allocations, credit_notes, credit_note_lines | 0 | 0 |

15,916 rows, none of which a caller can reach today and could not after. The
stricter predicate only excludes a row whose client belongs to a *different*
firm, which would be corruption rather than data.

### A correction to migration 319

One of the seven, `client_sales_invoices`, needed fixing on this side too: 319
declared its superseded policy (`firm_client_sales_invoices`) while
deliberately excluding the other six. That was inconsistent — the exclusion
list in 319 simply missed it. Migration 321 drops it, so all seven are treated
the same way.

## What remains, and why

* **Seven tables production does not have** (`notes_to_accounts`,
  `year_end_checklists`, `year_end_reviews`, the four `ri_*`): migration 067's
  never-applied tables, which migration 252 repointed away from. No router
  queries them.
* **Ten tables production has and no migration declares**: three `_backup_*` /
  `_mig247_*` scratch tables and seven from the Studio lineage.
* **Twenty-three policies deliberately not declared**: the eight legacy
  `firm_iso_wf_*` keyed on a setting nothing sets, seven duplicate `ai_*`
  policies, `audit_log_own_firm`, and the seven superseded names above, which
  disappear from this list once 321 applies to production.
* **`check_constraints_differ` (3) and `constraints_missing_from_live` (35)**
  are almost entirely fixture staleness: the guards fixture is production at
  02:15 IST, before migrations 316–321. It should be refreshed once 321 has
  applied, at which point both should fall sharply and whatever survives is
  genuine.

Refreshing that fixture is the natural next step, and is deliberately not done
in the same change as the migration it would be measuring.

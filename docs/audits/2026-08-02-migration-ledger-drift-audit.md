# Migration ledger drift — schema audit

**Date:** 2026-08-02
**Project audited:** `pbgoeyjvmllrafzavkgx` (production)
**Trigger:** while restoring posted-journal-line immutability (migration 251) it turned
out that `055_v131_hardening.sql` had never been applied — the ledger had consumed the
number 055 for a different file. That raised the obvious question: what else never ran?

---

## Method

Name matching is not evidence. The ledger stores Supabase Studio migration *names*, which
often differ from repository filenames (`102_bank_reconciliation_b4.sql` is recorded as
`bank_reconciliation_b4`), and the ledger's earliest entry is `043_…`, so everything
before it predates tracking entirely. A pure filename diff says 95 files are missing and
is wrong about most of them.

So this audit verifies **objects, not names**:

1. Match repository files to ledger entries by filename, then by filename minus its
   numeric prefix. Rollback scripts excluded (never meant to be applied). → 93 files
   unaccounted for.
2. Parse those 93 files for the objects they create: tables, added columns, functions,
   triggers. → 139 tables, 95 columns, 15 functions, 27 triggers.
3. Ask the live database which of those objects **do not exist**.
4. For each missing object, grep the backend for code that queries it.

A migration whose objects are all present was applied, whatever it was called. A
migration whose objects are missing was not — and if live code touches those objects,
that is a broken production endpoint, not a bookkeeping nit.

**Result: 81 of the 93 unaccounted files are fully present. 12 are not.**

---

## Findings

### A. Missing, and live code depends on it — these are broken in production

Each of these is queried by a router with no fallback. The `_USE_MOCK` branch beside
each call only covers the no-Supabase development path; in production the code reaches
the table directly.

| # | Missing object | Defined by | Broken caller |
|---|---|---|---|
| 1 | `reminders.firm_id` | `008_linter_fixes` | `routers/reminders.py:28` passes `firm_id` unconditionally into `find_all`, which filters `.eq("firm_id", …)`. `:45` also inserts it. **`GET`/`POST /api/reminders` fail on the default path.** |
| 2 | `government_notices` (whole table) + `.ca_approved` | `052_phase3_compliance`, `158_…ca_approval_columns` | `routers/document_intelligence_v2.py:191,255,275,306` — notice capture, list, detail, update |
| 3 | `gstr2b_uploads` (whole table) | `052_phase3_compliance` | `routers/gst_workspace.py:527,703` — GSTR-2B upload + fetch |
| 4 | `firm_hsn_rate_history` (whole table) | `181_firm_hsn_rate_history` | `routers/firm_hsn_rate_history.py:69,100,145,176` — the entire router |
| 5 | `notes_to_accounts` (whole table) + `.content` | `067_phase6_year_end`, `155_year_end_schema_repair` | `routers/year_end_notes.py:285,361,362,389` |
| 6 | `year_end_checklists` (whole table) | `067_phase6_year_end` | `routers/year_end_checklist.py:108,136,173,194` |
| 7 | `year_end_reviews` (whole table) + `.event_type` | `067_phase6_year_end`, `155_…` | `routers/year_end_reviews.py:84,457` |

**Items 5–7 have a twist worth naming.** Production *does* have year-end tables — they
are called `year_end_notes`, `year_end_checklist_items` and `year_end_review_events`,
created by a Studio migration recorded as `phase6_year_end_tables`. The repository's
`067_phase6_year_end.sql` creates a **differently named** set. So there are two
generations of the same schema: the tables that exist are referenced by no code, and the
tables the code references do not exist. Three year-end stages are non-functional against
production while their storage sits unused beside them.

This is the same failure mode migration 234 was written to fix for GST/TDS: mock-mode
tests pass, real Postgres never sees the insert, and the endpoint 500s only for a real
user.

### B. Missing, latent — non-default path only

| Missing object | Defined by | Effect |
|---|---|---|
| `clients.is_test` | `042_client_lifecycle` | `client_repository.find_all` only adds `.eq("is_test", False)` when `include_test=False`. Both the repository and `routers/clients.py:156` default it to `True`, so the normal client list works; **`GET /api/clients?include_test=false` fails.** |

### C. Missing, and correctly so — not drift

Listed to bound the scare, because a naive reading of the object diff flags them.

- `transactions`, `transaction_lines` (`006`), `invoice_lines` (`014`), and the columns
  `transactions.is_reverse_charge` / `transaction_lines.cess_paise` (`036`) — these
  tables were **deliberately dropped** by `139_drop_dead_transaction_tables`, which *is*
  applied. Their absence is the intended end state.
- `ri_entities`, `ri_entity_relationships`, `ri_client_entity_links`,
  `ri_cross_client_signals` (`047_relationship_intelligence_foundation`) — superseded by
  `entities` / `entity_relationships` / `entity_client_links` / `cross_client_matches`,
  all of which exist. Zero backend references to the `ri_*` names.
- `automation_executions.firm_id`, `filings.firm_id`, `permission_grants.firm_id`
  (`008`) — the columns are absent but no query filters on them. Cosmetic.

### D. Already fixed this session

`055_v131_hardening` — `prevent_posted_journal_line_modification` and
`trg_prevent_posted_journal_line_update` were missing, leaving posted journal **lines**
mutable by anything. Restored by `251_restore_posted_journal_line_immutability.sql`; see
that migration's header for the full story. 055's other trigger,
`trg_prevent_posted_journal_update` on `journal_entries`, is also absent — but `058`'s
`trg_journal_immutability` / `trg_journal_immutability_delete` cover the same ground and
are present, so entries were never exposed.

---

## Root cause

Two independent application channels have been used against the same database:

1. **The repository runner** (`scripts/db/apply_migrations.py`), which tracks applied
   files with a sha256 in a `public.schema_migrations` table. **That table does not
   exist in production** — this runner has never been used there.
2. **Supabase Studio / the platform migration API**, which records
   `supabase_migrations.schema_migrations` keyed on a timestamp version and a free-text
   name. This is what production actually has: 191 entries.

Because the ledger keys on a name typed at apply time rather than the repository
filename, three things follow:

- **Numbers get consumed by the wrong file.** Two different files have claimed 055; the
  one that ran was `055_journal_reversal_of_column`, and `055_v131_hardening.sql` was
  never applied and never missed. `045` and `056` are duplicated in the repository too.
- **Divergent copies get applied.** `phase6_year_end_tables` created a schema that does
  not match `067_phase6_year_end.sql`. Nothing compared them.
- **Nothing can detect a gap.** There is no checksum, no ordering constraint, and no
  reconciliation between the repository and the ledger. A file can sit in `migrations/`
  for two years, be assumed applied, and never have run.

The real-Postgres CI job masks this: it replays the repository from scratch, so CI's
schema is the schema the repository *describes*, which is not the schema production
*has*. Every one of the seven broken endpoints above would pass CI.

---

## Secondary findings

**Leftover migration scaffolding is still in `public`.** Migration 247 left three tables
behind:

| Table | Approx rows | RLS | Policies | `authenticated` SELECT | `anon` SELECT |
|---|---|---|---|---|---|
| `_backup_247_invoices` | 5,597 | on | 0 | no | no |
| `_backup_247_journal_lines` | 22,928 | on | 0 | no | no |
| `_mig247_targets` | 5,597 | on | 0 | no | no |

**Not a data-exposure hole** — RLS is on with no policies and neither role can read them,
so PostgREST returns nothing. But they are ~34k rows of stale invoice and journal
snapshots frozen at the pre-247 state, and `_mig247_targets` was clearly meant to be a
temporary table. They should be dropped once 247/248/249 are confirmed settled (they are:
zero drifted balance buckets today).

**Possible duplicate-generation tables**, flagged for a separate look rather than
asserted: production carries both `journal_lines` and `journal_entry_lines`, both
`chart_of_accounts` and `accounts`, both `client_sales_invoices` and `sales_invoices`,
and both `client_health_scores` and `health_scores`. Some are certainly dead; confirming
which needs the same object-plus-usage treatment applied above.

---

## Recommendations

**Immediate — restore the seven broken paths.** One repair migration creating the missing
objects, written against what the *code* expects. For items 5–7 there is a design call
first: either create the `067` tables the routers want, or repoint the routers at the
`year_end_*` tables production already has. The second is better — it keeps the data that
exists — but it is a code change, not a migration, so it needs its own testing.

**Then close the detection gap.** The seven findings are symptoms; the absence of any
repository-to-database comparison is the disease. Cheapest effective fix, in order:

1. **A schema-parity check in CI.** The real-Postgres job already builds a database from
   the repository. Add a step that dumps its object list and compares against production's
   — a scheduled job, not a PR gate, since it needs production credentials. Any object CI
   has and production lacks is exactly the class of bug this audit found.
2. **Adopt one application channel.** Either use `scripts/db/apply_migrations.py` against
   production (it already does checksums), or stop keeping files the platform will never
   apply. The current split is what makes the ledger unreadable.
3. **Fail on duplicate migration numbers.** A five-line CI check would have prevented the
   055 collision that started all of this.
4. **Assert critical guards exist**, the pattern used in
   `test_r251_journal_line_immutability_pg.py`: for anything load-bearing, test that it
   is present, not just that it works when present. The 055 trigger was absent for
   roughly two hundred migrations because nothing ever asked.

**Deliberately not done here:** I have not created the repair migration. Six of the seven
items are straightforward, but the year-end trio needs the code-or-schema decision above,
and I would rather that be a choice than an assumption.

---

## Resolution — 2026-08-03

The design call went the way this audit recommended: the routers were repointed at the
`year_end_*` tables production already has, and migration 252 defines them here so a
replayed database matches. Migrations **251–255** are now applied to production and
verified against the live catalog:

| | Applied | Verified behaviourally |
|---|---|---|
| 251 posted-line immutability + `apb_*` repair tools | ✅ | trigger present; an `UPDATE` of a real posted line raises and rolls back; `apb_drifted_clients()` returns **0** |
| 252 the seven missing objects | ✅ | all 3 tables + `reminders.firm_id` + `clients.is_test` present; **0** policies missing `USING`/`WITH CHECK` |
| 253 reconciliation reopen | ✅ | all 5 columns; both CHECKs present |
| 254 bank-rule GST treatment | ✅ | both columns + both CHECKs; an out-of-vocabulary rate and a rate-without-account are each refused; the valid shape is accepted |
| 255 drop superseded year-end policies | ✅ | `yen_firm`/`yeci_firm`/`yere_firm` gone, one `*_isolation` policy per table |

### The delivery gap this exposed — still open

They were applied **by hand**, through the Supabase MCP connection, because the
`apply pending migrations — production` CI job **cannot run**: the `SUPABASE_DB_URL`
secret is unset, so that job has failed on every push to `main` since it was added.
That is the mechanical reason 251–254 sat unapplied, and it is recommendation 2 above
("adopt one application channel") failing in practice rather than in principle.

**Setting `SUPABASE_DB_URL` under Settings → Secrets and variables → Actions is still
outstanding.** Until it is set, every future migration needs the same manual step, and
the red `Backend CI` on `main` is this job and only this job — the pytest and
real-Postgres jobs both pass.

### One correction to migration 252

252's header claimed a policy with `USING` but no `WITH CHECK` leaves an insert hole.
**That is wrong about Postgres**, which reuses the `USING` expression as the `WITH CHECK`
when none is supplied — tenant isolation held on the legacy year-end policies throughout.
The real defect was redundancy: RLS OR-s permissive policies, so a leftover `TO PUBLIC`
policy alongside a stricter `TO authenticated` one means the stricter never binds.
The comment is corrected and migration 255 removes the redundant pair.

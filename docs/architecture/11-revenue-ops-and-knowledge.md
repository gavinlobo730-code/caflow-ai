# 11 — Revenue operations and the knowledge base

> **What this is.** The design record for Amendment v1.1 (Phase 10B): the firm's own
> practice as a client of itself, the billing and collections loop that runs on it, the
> time that is meant to feed it, and the knowledge base with its client instructions.
> Written on 8 October 2026 **from the code**, not from the June 2026 batch reports it
> replaces: those disagree with the code in places, and §9 lists each one. Where this
> file and the code disagree, fix one of them the same day.
> `apps/api/tests/test_the_revenue_ops_design_record_names_what_exists.py` holds every
> route, table, migration, function, resource and path named below, and two sentences in
> it (the knowledge-base search is title-only; the Manager is firm-wide in the knowledge
> base alone) are tested to **expire**: when either stops being true that test fails, and
> this file is what to edit.

## 0. Where the June material went

The Batch 1 to 7 completion reports, the Batch 2.1 and 3.1 hardening reports and the
Batch 6 and 7 design reviews were the only description of any of this. They are folded
into this file and remain exactly as they stood in the merge commit `315e6a19` of 8
October 2026, for anyone who wants the original wording:

```
git show 315e6a19:docs/BATCH_3_COMPLETION_REPORT.md     # Batch 1..7: BATCH_<n>_COMPLETION_REPORT.md
git show 315e6a19:docs/BATCH_6_DESIGN_REVIEW.md          # also BATCH_7_DESIGN_REVIEW.md
git show 315e6a19:docs/BATCH_2_1_HARDENING_REPORT.md     # also BATCH_3_1_HARDENING_REPORT.md
```

Two documents stay in the tree because this file cites them as decisions, not as
design: `docs/REVENUE_OPS_BRIDGE.md` (the register of what the legacy `fee_*` billing
tables still cost; read §9 beside it, a few of its entries are closed) and
`docs/PRACTICE_CLIENT_VISIBILITY_DECISION.md` (Option A below). The V1 to V12, N1 to N5
and T1 to T2 acceptance matrix for the cut-over to per-user database access is not
repeated here: it lives in `docs/PHASE_5_2_WS3_USE_USER_JWT_RUNBOOK.md`, which
`docs/operations/release-and-rollback.md` cites by path.

## 1. The decisions of 14 June 2026

Recorded as decisions, because they were the owner's and the code follows them.

- **Billing model: "Amendment model; bridge `fee_*`".** New revenue operations run on the
  sales engine in the practice's own books (`client_sales_invoices`, `receipts`, the
  general ledger). The legacy `fee_engagements`, `fee_invoices` and `fee_receipts` stay
  readable and unmigrated, and **no new feature extends them**
  (the rule at the foot of `docs/REVENUE_OPS_BRIDGE.md`). Which engine finally survives is
  a separate, open decision (POST-B-193).
- **Option A: the practice client stays Partner-only.** The accounting, reporting and
  banking engines are client-agnostic and never branch on `is_internal`; the restriction
  is an access overlay. The guiding sentence is "the practice is just another client to
  the engines; it is access-restricted to Partners at the visibility layer"
  (`docs/PRACTICE_CLIENT_VISIBILITY_DECISION.md`).
- **Knowledge base (Batch 6).** Client instructions are standing guidance: no
  acknowledgement and no completion state. Manager and above author articles; Executive
  and above write instructions, an Executive only for an assigned client; a Reviewer
  reads; a portal client never sees the knowledge base. "Manager is firm-wide" was part of
  this decision and has since been overtaken everywhere but here (§7, §9).
- **Navigation (Batch 7).** The Practice rail entry is Partner-only and **absent, not
  greyed**, for everybody else; the Knowledge rail entry is for all staff; a client's
  articles and instructions live in the client workspace; the legacy `/billing` screen
  is kept as it was and is titled Fee Billing.

## 2. The internal practice client

The firm is modelled as one `clients` row with `is_internal = true`, pointed at by
`firms.internal_client_id` (a foreign key, `ON DELETE SET NULL`), migration 073. At most
one per firm is a database fact: the partial unique index `uq_clients_one_internal_per_firm`
(migration 080).

**Provisioning** is `internal_client_service.provision()`. It runs when a firm is created
(`apps/api/routers/onboarding.py`, after the firm-wide chart of accounts is seeded) and on
demand through `POST /api/practice/provision`, which is how a firm that pre-dates the
feature gets one. It is idempotent, and when two calls race the loser reads the winner
off the unique index and returns it. It **needs a valid PAN on the firm** (`clients.pan`
is `NOT NULL` and regex-checked): without one it returns nothing, logs, and
`GET /api/practice` says `can_provision` is false so the screen can say why. The entity
type is `Partnership` unless told otherwise and nothing edits it afterwards (POST-A-210).
There is also a SQL function `provision_internal_client()` (migration 073) that the
application does not call; migration 086 revoked it from every role but the service
role. It duplicates the Python path and the two must be kept in step.

**It includes** the practice's own books: accounting, GST, TDS, documents, reports and
billing. The firm-wide chart of accounts is shared, so the practice posts through the
same kernel and the same chart as everybody.

**It excludes** payroll and HR (G4), every client population (G2), every non-Partner
(G1), and staff assignment: `apps/api/routers/assignments.py` refuses to assign it.

## 3. The four guardrails

Each is held in two layers, and the order matters. The **API layer** is checked first on
every request. The **database layer** is row-level security, and it is the effective
control only while `USE_USER_JWT` is on (the API then queries as the caller, not as the
service role). Production defaults that on (`apps/api/core/security_config.py`), and
`GET /api/security/posture` (`apps/api/core/security_posture.py`) reports the value
actually resolved. The June reports and
the module headers say "the service role bypasses RLS, so the API is the effective
control": that is the `USE_USER_JWT=false` world, now the exception.

### G1 — Partner-only access

*The internal client and everything keyed on it are visible to the Partner alone, and a
non-Partner is told 404, never 403, so its existence is not disclosed.*

- **Functions.** `internal_client_service.assert_can_view_client()` (the row is loaded)
  and `internal_client_service.assert_partner_for_internal_id()` (only the id is known).
- **The router guard.** `internal_client_service.require_client_access()` is mounted as
  `_CLIENT_GUARD` in `apps/api/main.py` on the client-scoped routers. It reads
  `client_id` from the path, the query string **or a JSON body**, asserts G1, then the
  caller's assignment scope. It does nothing for a URL that names no client.
- **The id-keyed routes** are therefore outside that guard and carry their own check.
  `POST /api/sales-invoices/{invoice_id}/issue` resolves the invoice's client and calls
  `assert_client_access`; the internal client cannot be assigned, so a non-Partner is
  refused there (a Manager by the 404 of that scope check). That is the whole gate: the
  route holds no explicit Partner assertion, unlike
  `POST /api/sales-invoices/{invoice_id}/repost-journal`, which does. The database layer
  below holds either way.
- **Resources.** `practice` and `billing` are Partner-only in
  `apps/api/core/permissions.py`. `rbac("billing", "read")` or `rbac("billing", "write")`
  guards every `/api/billing` route, and `rbac("practice", "read")` or
  `rbac("practice", "write")` every `/api/practice` one. Because `rbac()` resolves through
  the per-person grid (migration 403), a Partner could in principle grant `billing` to
  someone; the database layer is what would still refuse them. Read from the code, not
  exercised.
- **Database.** Migration 073: `billing_schedules` and `client_firm_customer_links` are
  Partner-only. Migration 074: `my_internal_client_id()` and a RESTRICTIVE
  `<table>_internal_partner_only` policy (`get_my_role() = 'Partner' OR client_id IS
  DISTINCT FROM my_internal_client_id()`) on `clients` and a fixed list of client-keyed
  tables. 074's list names `sales_invoices`, which does not exist, so migration 075 added
  the same policy to `client_sales_invoices`; migration 079 added it to
  `knowledge_articles`. The loop in 074 ran once: **nothing asserts that a client-keyed
  table created later joins it.** The assignment scope of migration 084 covers a table it
  reaches for the same reason (a non-Partner needs an assignment row and the internal
  client has none), and the role-by-table matrix in
  `apps/api/tests/test_rls_role_by_table_matrix_pg.py` tries every actor against every
  table the browser reads.
- **Tests.** `test_batch2_internal_client.py`, `test_batch2_1_client_access_guard.py`,
  `test_batch2_guardrails_migration.py`, `test_billing_client_scope.py`,
  `test_rls_role_by_table_matrix_pg.py` (all under `apps/api/tests/`).

### G2 — Left out of every client population

*The practice is not one of the firm's clients to count, list, score or chase.*

- `client_repo.find_all()` and `count()` exclude it by default; a Partner surface that
  needs it passes `include_internal=True` (`apps/api/repositories/client_repository.py`).
- The queries that bypass the repository carry the filter themselves: the analytics client
  and firm figures (`apps/api/routers/analytics.py`), health recalculation and the
  per-client health read (`apps/api/routers/health.py`), the first-run checklist
  (`apps/api/services/first_run_service.py`) and the platform counts
  (`apps/api/routers/platform.py`).
- **The browser reads `clients` itself over PostgREST**, where only row-level security
  stands in the way and that hides the row from non-Partners only. A picker would offer
  the Partner their own firm. `.eq("is_internal", false)` is on every list read, held by
  `apps/web/scripts/a-client-picker-leaves-out-the-internal-client.test.ts`.
- The view `clients_external` (migration 073, `security_invoker`) was meant to be the
  single source. **Nothing reads it**; the repository default and the per-query filters
  are what enforce G2, and `docs/REVENUE_OPS_BRIDGE.md` B2-2 is right that a new direct
  `clients` query has to remember the filter.

### G3 — One linked customer per practice client

*A practice client the firm bills is exactly one customer in the practice's books.*

- `client_firm_customer_links` has `UNIQUE (firm_id, client_id)` (migration 073), the
  authoritative guarantee. `billing_service.ensure_customer_link()` creates the customer
  and the link on first use, reading the client **scoped to the caller's firm** (a
  foreign client id fails loud rather than copying another firm's PAN into this firm's
  books). When two runs race, the loser deactivates the customer it just made and returns
  the winner's.
- The customer is a **snapshot** (name, GSTIN, PAN, state code) taken at first use.
  Nothing updates it when the client's record changes (§9).
- The portal reads the link as the client's own principal to show them their fee
  invoices: `portal_data_service.resolve_fee_scope()`, with the policy repair of
  migration 442 (`test_r442_portal_client_reads_own_fee_scope_pg.py`).

### G4 — Module cap: no payroll or HR

*The practice gets accounting, GST, TDS, documents, reports and billing, and no payroll.*

- `internal_client_service.assert_not_internal_for_payroll()` is called at the payroll
  write doors that take a client id (`apps/api/routers/payroll.py`); the answer is 403
  with a sentence. Migration 074 also puts the Partner-only policy on the payroll tables
  that carry a `client_id`. Held by `test_batch2_internal_client.py`.

## 4. The billing lifecycle: schedule, draft, issue, receipt

The billing service owns **no ledger and no GST logic**. It turns a schedule into a draft
by calling the sales engine (`routers.sales_invoices.create_invoice`) and leaves the rest
to the engine's own issue, receipt and posting paths (`apps/api/services/billing_service.py`).

```
billing_schedules  (Partner; arrangement retainer | one_time | package;
                    cadence monthly | quarterly | annual | one_time; service_id mandatory, 206)
   |   POST /api/billing/schedules/{schedule_id}/generate     one schedule
   |   POST /api/billing/run                                  every schedule due
   v
period_for(cadence, next_run_date)   "2026-10" | "2026-Q4" | "2026-27" | "ONCE"
   v
an invoice already exists for (schedule, period)?  -- yes -->  return it: created = false,
   | no                                                        and nothing advances
   v
ensure_customer_link()    G3: the client's ONE customer in the practice's books
   v
create_invoice            the sales engine: GST, insert  ->  DRAFT, number DRAFT-xxxxxxxxxx,
   |                      line at SAC 998211, NO journal
   v
_stamp_billing_fields     billing_schedule_id, billing_period, source = 'billing'
   |    unique violation (uq_client_sales_invoices_billing_run): delete the orphan draft
   |    and its lines, return the invoice that won
   v
_advance_schedule         next_run_date moves on; a one_time schedule closes (is_active false)

   ---- a person ----
reads the draft, replaces the number, checks the GST
   v
POST /api/sales-invoices/{invoice_id}/issue     the journal is posted FIRST, then status = issued
   |                                            and journal_entry_id is stored (076)
   v
POST /api/receipts/       settlement = amount_paise + tds_paise  ->  partially_paid -> paid
   v
nightly: collections_service.sweep_overdue()    is_overdue / days_overdue / aging_bucket,
                                                derived; the status never becomes "overdue"
```

**Three layers keep one schedule from billing one period twice**, and they are not the
same thing. The period key is deterministic. The existence check (`_find_generated()`) is
the fast path. The unique partial index `uq_client_sales_invoices_billing_run` on
`(billing_schedule_id, billing_period) WHERE billing_schedule_id IS NOT NULL` (migration
075, held by `apps/api/tests/sql/batch3_billing_verify.sql`) is the authority, and
`_stamp_billing_fields()` is written for the case where two runs both pass the check.

**The CA-confirm gate is the ordinary draft-to-issued transition.** Generation never
issues, posts or sends. Issue posts the journal before it flips the status, so a posting
failure (no chart of accounts, say) leaves a re-tryable draft; `GET
/api/sales-invoices/maintenance/unposted` and `POST
/api/sales-invoices/{invoice_id}/repost-journal` recover an invoice that was issued by an
older path with no journal. The status and the link are written by one update, but the
journal and that update are still two writes, not one transaction (POST-A-092): a crash
between them leaves a posted journal under a draft, and issuing again is safe because the
posting kernel dedupes.

**TDS the client deducts from the firm's fee** rides on the receipt: `receipts.tds_paise`
(migration 077) posts a Dr TDS Receivable leg, and the invoice is settled by cash plus tax
(IT Act s.198 deems the tax deducted to be income received, s.199 gives credit for it).

## 5. Collections and AR

- **Overdue is derived and denormalised, never a status.** `collections_service.assess_invoice()`
  returns the open balance, `days_overdue` (never negative), `is_overdue` and
  `aging_bucket` (`not_due`, `0-30`, `31-60`, `61-90`, `90+`) from the due date, or the
  invoice date plus the invoice's own credit days where there is none. A paid invoice is
  never overdue, and the payment status is untouched.
- **The practice's own receivable** is read from `client_sales_invoices` for the
  internal client only, on the generated `outstanding_paise` column (migration 278). A
  firm with no practice client has an empty fee ledger: the answer is `[]`, never "every
  client".
- **The nightly job** (`apps/api/jobs/scheduler.py`) runs `collections_service.sweep_overdue()`
  and `collections_service.flag_overdue_for_internal_followup()`.
  **Neither contacts anybody.** The second writes a timeline note and its own counter
  (`internal_followup_count`, migration 405); the customer-facing counters
  (`reminder_count`, `last_reminded_at`) belong to the real send alone, because the
  reminder's tone escalates on that number. The route that used to say "send reminders"
  and sent nothing is gone; its replacement is `POST /api/billing/collections/flag-followups`.
- **A customer reminder is manual**, one invoice at a time:
  `POST /api/sales-invoices/{invoice_id}/remind`. An automatic bulk version was deleted
  deliberately (POST-B-196 holds the question of bringing one back).
- **Dashboard.** `GET /api/billing/collections/dashboard` and `GET /api/billing/ar-aging`:
  receivable, five buckets, overdue, TDS receivable, cash collected. Operational figures
  only. What was added later (a paise-weighted collection-days figure, the profitability
  and benchmark pages) sits outside this record; POST-B-321 holds what is wrong with the
  profitability page.

## 6. Time capture

Capture and visibility, not analytics. `time_entries` carries `is_billable`,
`billable_rate_paise` (migration 073) and `billed_invoice_id` (migration 078), and `is_billed` is a
**generated column** derived from the link, so it cannot be written and cannot disagree.
`users.cost_rate_paise` is Partner-only (`GET /api/billing/staff-cost-rates`) and is
**never an input to a figure**: what an hour costs the firm is not what it bills.

A rate is read in a fixed order (`domain/billing/time_rate.py`, migration 451): the
entry's own, the engagement's override, the person's default, and then **nothing, which is
not zero**. The answer is stored on the entry so a later rate change does not re-price
logged work. `GET /api/billing/unbilled-work` aggregates in SQL (`unbilled_time_summary`)
and lists work with no rate apart from work worth a stated amount.

**Nothing bills time yet.** `billing_service.mark_time_entries_billed()` is the intended
way to set the link and has no production caller; a schedule bills a fixed fee (POST-B-194).

## 7. The knowledge base

Three tables from migration 073: `knowledge_articles`, `knowledge_article_versions`,
`client_instructions`.

- **Versions are append-only.** An edit inserts version n+1 and bumps `current_version`;
  `UNIQUE (article_id, version)` is the guard. **Restoring** version n writes its content
  as a **new** version (`knowledge_service.restore_version()`), so history is never
  rewritten. Archiving is a soft flag. Two concurrent edits race on the unique key and the
  loser gets an error: there is no retry (§9).
- **Scope.** `firm` and `department` articles are visible to all staff (`department` is a
  free-text tag, not a boundary, POST-B-331); `client` articles carry a `client_id` and
  are gated by the visibility function below.
- **Search is by title only.** `knowledge_service.search_articles()` filters with
  `ilike` on the title; there is no full-text query and no ranking, although the design
  promised both and migration 073 built the GIN indexes for them (they serve nothing).
  This sentence is tested to expire.
- **Visibility, as implemented** (`knowledge_service.can_view_client_content()`;
  `can_write_instruction()` for instructions):

  | | Partner | Manager | Executive | Reviewer | Portal client |
  |---|---|---|---|---|---|
  | firm and department articles, read | yes | yes | yes | yes | no |
  | author, edit, restore, archive articles (`rbac("knowledge", "write")`) | yes | yes | no | no | no |
  | a client's articles and instructions, read | all | **all** | if assigned | if assigned | no |
  | a client's instructions, write (`rbac("client_instruction", "write")`) | yes | yes | if assigned | no | no |
  | the internal client's anything | yes | no | no | no | no |

  **The Manager column is firm-wide in the knowledge base alone.** `core.authz` has been
  assignment-scoped for the Manager since the M3 decision, and the router guard applies
  that to every URL carrying a client id, so `GET /api/clients/{client_id}/instructions`
  and `GET /api/clients/{client_id}/knowledge` are assignment-scoped for a Manager. The
  URLs that carry an article id or a scope alone (`GET /api/knowledge/articles`,
  `GET /api/knowledge/articles/{article_id}`) reach the service without that guard, and
  there a Manager reads every non-internal client's articles, as does migration 079's
  policy. Whether that is intended is open (POST-B-029). This sentence is tested to expire.
  A per-person grant (migration 403) can also hand `knowledge:write` to someone below
  Manager; the service still asks the assignment question for a client's article.
- **Where events go.** A client-scoped article event and every instruction event go to
  that client's Timeline; a firm or department article event has no client and goes to
  `audit_log`, with the auth id as actor.
- **Database.** Migration 079: `get_my_user_id()`, a RESTRICTIVE assignment policy on
  `knowledge_articles` and `client_instructions` (Partner and Manager through, others by
  `user_client_assignments`), and Partner-only for the internal client on articles.
  `knowledge_article_versions`, where the content lives, has only the firm policy of 073
  (POST-A-009). `test_knowledge_client_scope.py` and `test_batch6_knowledge.py` hold the
  service; `test_batch6_migration.py` holds the policies.

## 8. Client instructions

A client-scoped standing note: title, body, pinned or not, archived or not (the archive
column is migration 430; until then archiving failed). No acknowledgement, no completion,
no due date: a task is a different thing. Read and write follow the table above; the
Timeline records every create, update and archive; the client Overview shows the pinned
ones (`apps/web/components/knowledge/ClientInstructions.tsx`).

## 9. Where the code differs from the June design, and what is open

None of these is decided here.

| The June text said | The code does | Open as |
|---|---|---|
| Search is Postgres full text with ranking | title `ilike` only (§7) | **no ledger line** |
| Manager is firm-wide | firm-wide in the knowledge base alone (§7) | POST-B-029 |
| Department is an organisational tag | the same, by decision, still free text | POST-B-331 |
| Global search may include articles | it does not | POST-B-287 |
| Versions inherit the article's visibility, immutable | only the firm policy, no database-level immutability | POST-A-009 |
| `POST /collections/send-reminders` | gone; `flag-followups` sends nothing (§5) | POST-B-196 |
| Practice context-switches into the internal client's shell | Practice is its own shell | closed |
| Frontend roles Partner, Manager, Article, Staff | the five canonical roles (Module 9.0) | closed |
| Rupee-to-paise conversion in the schedule form | goes through `lib/money/rupeeInput.ts` | closed |
| `billing_schedules.service_id` has no foreign key | mandatory and keyed (migration 206) | closed |
| Practice Billing and AR link to the invoices | they do not yet | PRE-A-018 |
| Fee billing: one engine | two live: `fee_*` and the sales engine | POST-B-193, POST-B-321 |
| Time is billed | nothing bills it | POST-B-194 |
| Bridge residue: two rate columns, two provisioners | both remain | POST-A-169 |

**Observed on 8 October 2026 while writing this, in no ledger line, not changed:**

- `billing_service.generate_for_schedule()` returns early when an invoice exists for the
  period and never calls `_advance_schedule()`. A schedule whose invoice was stamped but
  whose advance failed stays due for ever, and `billing_service.run_due()` counts it as
  skipped every time.
- The cadence arithmetic is its own (`billing_service.next_run_after()`), not
  `domain/recurrence.py`: a run date above the 28th becomes the 28th and stays there. The
  quarterly key is the calendar quarter, not the financial-year quarter; it is a key, not
  a statutory period.
- A draft carries a `DRAFT-` number "the CA must replace". Nothing at issue refuses a
  number that still begins `DRAFT-`: it is sixteen characters of letters, digits and a
  hyphen, which CGST Rule 46(b) allows.
- `knowledge_service.edit_article()` does not retry on a `UNIQUE (article_id, version)`
  collision; the design said it would.
- The G3 customer is never refreshed from the client (§3).
- Nothing schedules draft generation: `billing_service.run_due()` is reached only from
  `POST /api/billing/run`.

## 10. Index

**Migrations** (each has a `_rollback.sql` beside it where the repository wrote one):
073 foundation (tables, `is_internal`, `clients_external`, the Partner-only policies),
074 internal-client policies, 075 billing traceability and the unique index, 076 the
journal link on an invoice, 077 collections columns and `receipts.tds_paise`, 078 billed
capture, 079 knowledge policies, 080 one internal client per firm, 086 provisioning
function revoked, 144 the search path of the policy helpers, 206 mandatory service,
278 generated `outstanding_paise`, 337 (anon still reads the `clients_external` view),
405 the internal follow-up counter, 430 archive for instructions, 442 the portal reads its
own link, 451 time rates, 468 a suspended member is nobody to the database, 478 only a
Partner changes who is assigned.

**Tests** (`apps/api/tests/`): `test_batch2_internal_client.py`,
`test_batch2_1_client_access_guard.py`, `test_batch2_guardrails_migration.py`,
`test_batch3_billing.py`, `test_batch3_1_hardening.py`, `test_batch4_collections.py`,
`test_a_reminder_the_customer_got_is_counted_separately.py`, `test_batch5_capture.py`,
`test_451_a_time_entry_is_priced_pg.py`, `test_batch6_knowledge.py`,
`test_knowledge_client_scope.py`, `test_billing_client_scope.py`,
`test_rls_role_by_table_matrix_pg.py`, and this file's own guard.

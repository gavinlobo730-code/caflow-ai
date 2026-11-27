# 11 — Revenue operations and the knowledge base

> **What this is.** The design record for Amendment v1.1 (Phase 10B): the firm's own
> practice as a client of itself, the billing and collections loop that runs on it, the
> time that is meant to feed it, and the knowledge base with its client instructions.
> Written on 8 October 2026 **from the code**, not from the June 2026 batch reports it
> replaces: those disagree with the code in places, and §9 lists each one. Where this
> file and the code disagree, fix one of them the same day.
> `apps/api/tests/test_the_revenue_ops_design_record_names_what_exists.py` holds every
> route, table, migration, function, resource and path named below, and two sentences in
> it (the knowledge-base search has no ranking; the Manager is firm-wide in the knowledge
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
  (the rule at the foot of `docs/REVENUE_OPS_BRIDGE.md`). Which engine finally survives was
  a separate decision (POST-B-193), **taken by the owner on 20 November 2026: the sales
  engine in the practice's own books.** The earlier screens are a read-only record since
  POST-A-532 (§2, "The earlier fee bills are a record").
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
  is kept as it was and is titled Fee Billing. (Since POST-A-532 it is titled "Earlier fee
  bills", takes no write, and is on the My practice menu and not on Accounting's.)

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
type is recorded as `Partnership` because sign-up does not ask. The practice client is out of every
client list, so no client screen reaches it, and the Partner sets the firm's real legal form on the Practice
screen through `PATCH /api/practice/identity` (which `GET /api/practice` serves the stored value and the
accepted list for). Sign-up still does not ask.
There used to be a SQL function `provision_internal_client()` (migration 073) that the
application never called; migration 086 revoked it from every role but the service
role, and by 16 November 2026 it had drifted from the Python path (no state, no state
code, no race handling). Migration 610 dropped it (POST-A-169), so the Python path is
the only provisioner, and `tests/test_610_the_sql_internal_client_provisioner_nothing_calls_is_dropped_pg.py`
fails a caller added later.

**It includes** the practice's own books: accounting, GST, TDS, documents, reports and
billing, and since 21 November 2026 the payroll of the firm's own staff (G4). The firm-wide chart of accounts is shared, so the practice posts through the
same kernel and the same chart as everybody.

**It excludes** every client population (G2), every non-Partner
(G1), and staff assignment: `apps/api/routers/assignments.py` refuses to assign it.

### My practice: one workspace, on addresses that already existed (POST-A-532, first part)

The owner, walking the live Test Firm on 20 November 2026, could not find where a firm keeps
its own books. They were one small button ("Practice books") on the Accounting overview, and
the practice's other screens sat on a separate menu in the firm's navy frame, as though they
were about something else. The owner asked for one place, with everything a client's
workspace has and more.

**It is a frame, and no address is new.** The live site has 99 of its 100 dynamic address
rules in use, so My practice is the client workspace's own shell drawn over two sets of
addresses that existed: the practice's own client workspace (`/clients/<its id>/...`, which a
Partner could always open) and the fixed `/practice/...` screens.
`apps/web/lib/workspace/practiceWorkspace.ts` is what both halves ask: which fixed addresses
are My practice (`isPracticePath`), which screens are about running the practice
(`PRACTICE_SECTIONS`, held equal to the pages under `/practice` so a screen added there is not
left without a tile), and which client sections are NOT offered for the practice, each with
its reason (`NOT_FOR_THE_PRACTICE`: the client portal, lifecycle, health because of G2, and a
client's knowledge and instructions).

- **The bar has two faces and is one component** (`apps/web/components/shell/ClientTopBar.tsx`).
  Inside `/clients/<id>/...` the open client's own row says it is the practice (`is_internal`,
  which only a Partner can read at all, G1); on a fixed `/practice/...` address the shell is
  told by the address. Either way the bar reads "My practice", leads out to the dashboard and
  not to the client list, and offers no client switcher and no health badge (the practice is
  in neither population, G2). It is not a second bar because the menu's backdrop is a
  hand-built full-window layer, and the overlay guard refuses a second copy of one.
- **The grid is three groups** (`apps/web/components/client/PracticeModuleGrid.tsx`): "Your
  firm's books", the client workspace's sections opened on the practice's own client;
  "Running the practice", the fixed screens; and "People". On a fixed address the practice's
  client id is the server's to give (`GET /api/practice`, read by
  `apps/web/lib/workspace/usePracticeClient.ts`), and four answers are kept apart: ready, not
  set up (only the server's own "not provisioned"), unavailable (a read that failed or was
  refused) and still reading. A practice that is not set up is pointed at Practice home; a
  failed read says so; neither draws a tile that leads nowhere.
- **People is one list of screens with two doors** (the owner's decision of 21-11-2026;
  `apps/web/lib/workspace/practiceWorkspace.ts`). Team, Assignments, Approvals, Workload and
  Login History keep their addresses. Somebody who may open My practice (a Partner) finds
  them in its People group and is drawn them in the My practice frame, and has no separate
  Team entry on the firm menu (`apps/web/lib/workspace/outerMenu.ts`); a Manager, who runs
  the team day to day and has no My practice, reaches the same screens from the firm menu's
  Team entry, in the firm's frame. The first build pointed a Partner out to the firm's menus
  instead, which the owner met as being thrown out of My practice. Time Tracking is in Work,
  where every member of staff records hours, and is not listed here.
- **The firm menu says "My practice"** where it said "Practice" (same entry, same route, a
  Partner alone), and its panel opens with "Your firm's books".
- **Driven in a browser** (`apps/web/scripts/drive/weekly/myPractice.mjs`, four scenarios in
  the weekly set): a fixed practice screen in the frame with its grid; the practice's own
  workspace; not set up and unread; an ordinary client untouched.

**The earlier fee bills are a record (POST-A-532, third part; POST-B-193 decided).** The
owner decided on 20 November 2026 that the firm's fee billing lives in My practice on the
sales engine, that the old Fee Billing screen leaves the menu and that its rows stay
readable (the live database held ten fee invoices and two receipts, all in one test firm,
and nothing was moved).

- `apps/web/app/billing/page.tsx` is titled "Earlier fee bills" and offers no write: one
  constant at the top of the file turns every control that creates, issues, cancels or
  records a receipt off, whatever the caller's permission, and a notice at the head of the
  screen says where fees are billed now (Billing Schedules) and that these rows are kept as
  they were. `apps/web/app/accounting/receivables/page.tsx` is "Earlier fee receivables".
- Both left the Accounting menu and the Accounting overview and are the last two entries
  of the My practice menu and of its grid (`apps/web/components/panels/PracticePanel.tsx`,
  `apps/web/lib/workspace/practiceWorkspace.ts`), and both addresses wear the My practice
  frame. `apps/web/lib/workspace/routeOwnership.ts` says they belong to the practice.
- **What is not done, and it is the rest of POST-B-193.** The server's earlier fee routes
  still accept a Partner's write made by hand; nothing in the product reaches them. Lead
  conversion still creates a `fee_engagements` row and offers no billing schedule, and the
  time-rate and compliance readers of `fee_engagements` are as they were. Which screen reads
  which engine is §9's table.

**Profitability counts the fees billed from the firm's own books (POST-B-193, the readers'
first repoint, 21 November 2026).** Profitability, fee concentration and realization (one
screen, `apps/web/app/practice/profitability/page.tsx`) read the earlier fee tables alone, so
a fee billed from My practice was income in the firm's ledger and nothing on the screen that
judges which client pays.

- `apps/api/services/practice_fee_revenue_service.py` reads both places for a window: the
  earlier fee bills by the read every revenue figure already used, and the practice's own
  books as ONE answer per customer from `public.report_party_totals` (migrations 745 and
  766), asked for the practice's own client. That is the firm Reports page's own function, so
  "what was billed, before GST, net of credit and debit notes" has one definition, and what
  crosses the wire is a line per customer and not a row per invoice.
- `apps/api/domain/practice/fee_sources.py` is the rule. A customer in the practice's books
  is a client only through its link (G3, `client_firm_customer_links`); a customer with no
  link is not a client of the firm, so its total is in no client's revenue and is NAMED
  beside the figures. A client's net can be below nil in a window that holds a credit note
  and not its invoice, and is carried as it is: profitability draws no margin on it and
  concentration leaves it out of the shares.
- Each of the three answers says where its revenue was read from, in the server's words at
  the end of the sentences the screen already draws, and as figures in `revenue_sources`.
  The rupee split is made from the rows AFTER the caller's own narrowing, so a member
  assigned to some clients is told the split of their own book; the unlinked figure belongs
  to no client and is told to a firm-wide caller only. A firm with no practice client is
  told that only the earlier bills are counted.
- A fee bill in the firm's own books names no engagement (a billing schedule is not a fee
  engagement), so realization, which is judged per engagement, names those fees beside its
  ratio and leaves them out of it, as it always did for an invoice that names no engagement.
- **G1 is not widened.** The three routes were already gated on the practice's fee economics
  (a Partner's permission) and nothing of the practice's books leaves the service but a
  total per client; the books themselves stay the Partner's alone.
- Held by `test_the_practices_fee_revenue_is_read_from_both_places.py`, including the rule
  that no analytics route reads the earlier fee tables directly any more.

**What it does not do.** A fee entered in BOTH places would be counted twice, and the screen
says so; nothing reconciles the two. Revenue from the practice's books is the window's net
per client, so the engagement view and realization cannot attribute it to an engagement.

**What the first part does not do.** Payroll for the firm's own staff came with the second part
(G4 below). A non-Partner who types a `/practice/...` address is drawn the frame for
the moment before the page's own guard sends them away, with a books group that says it
could not be read; nothing of the practice is disclosed, because the server refuses the read.
The first paint of the practice's own workspace shows the client bar until the client row
has been read, then the My practice bar.

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
  refused there (a Manager by the 404 of that scope check). The route holds no explicit
  Partner assertion, unlike `POST /api/sales-invoices/{invoice_id}/repost-journal`, which
  does. Since POST-A-433 the scope check asks G1 itself: `core/authz.assigned_client_ids`
  and `is_client_assigned` drop an assignment that names the practice, so even a row the
  service role wrote grants a non-Partner nothing, on every route that asks
  `can_access_client` or `effective_client_ids`. The database layer below holds either way.
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
  table created later joins it** (119 of the 177 tables with an assignment scope had no such
  policy on 22-10-2026; migration 537 added it to nine parents and made the assignment table
  itself refuse the practice from a signed-in session, which is what answers the rest,
  POST-A-306). The assignment scope of migration 084 covers a table it
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
  are what enforce G2. `docs/REVENUE_OPS_BRIDGE.md` B2-2 said a new direct `clients`
  query has to remember the filter; since 16 November 2026 (POST-A-169)
  `apps/api/tests/test_a_read_of_the_clients_table_leaves_the_practice_out_or_says_why.py`
  makes it: every API read of `clients` that is not a lookup by id asks `is_internal` or is
  listed with why the practice is in its answer, and two reads that count or list it among
  the clients (the hub worklist's count and rows, the risk register) are listed as open.

### G3 — One linked customer per practice client

*A practice client the firm bills is exactly one customer in the practice's books.*

- `client_firm_customer_links` has `UNIQUE (firm_id, client_id)` (migration 073), the
  authoritative guarantee. `billing_service.ensure_customer_link()` creates the customer
  and the link on first use, reading the client **scoped to the caller's firm** (a
  foreign client id fails loud rather than copying another firm's PAN into this firm's
  books). When two runs race, the loser deactivates the customer it just made and returns
  the winner's.
- The customer is a **snapshot** (name, GSTIN, PAN, state code) taken at first use and
  **brought back in line with the client's record each time a fee invoice is prepared**
  (`billing_service._refresh_the_customer_snapshot`, POST-A-216): the client's record is the
  truth, so a GSTIN or PAN the client no longer carries is cleared, only the columns that
  differ are written, and a refresh that cannot be made never blocks the run (it is
  reported). Fee invoices already issued are not re-written.
- The portal reads the link as the client's own principal to show them their fee
  invoices: `portal_data_service.resolve_fee_scope()`, with the policy repair of
  migration 442 (`test_442_a_portal_client_reads_their_own_fee_scope_pg.py`).

### G4 — The practice's own payroll is the Partner's alone

*The firm runs its own staff's payroll on the practice client, and only a Partner may.*

**This guardrail was a module cap until 21 November 2026**: "accounting, GST, TDS, documents,
reports and billing, and no payroll", held by a function that refused payroll for the
practice to everybody, the Partner included, with a 403. On 20 November the owner decided
the firm's own staff payroll runs in My practice, with everything else a client's workspace
has (POST-A-532). The cap is lifted, and what stands at the payroll doors is G1.

- `internal_client_service.assert_practice_payroll_is_the_partners()` is called at every
  payroll door that asks whether payroll is switched on for a client, and at the door that
  switches it on (`apps/api/routers/payroll.py`), BEFORE the switch is asked, so a
  non-Partner is not told whether the practice runs a payroll. The answer is G1's: 404, in
  the words used for a client that does not exist.
- It is the third of three layers, and it is asked by name because of what is behind these
  doors. Payroll's own permission is Manager and above, and the rows say what each colleague
  is paid. The router guard (`require_client_access`) asks G1 of any request that names a
  client; the assignment scope refuses a non-Partner the practice on every id-keyed route
  (a run, a payslip, an employee by id), because the practice cannot be assigned and an
  assignment row that names it grants nothing (G1, POST-A-433). Before this change nothing
  of the practice was ever stored behind these doors, so nothing had tried them against it.
- The database: migration 074 put the Partner-only policy on the payroll tables that carry
  a `client_id`, and since POST-A-339 a signed-in session holds no privilege on any payroll
  table at all, so the API is the control and the three layers above are what it is.
- A member of the firm's own staff reads their own payslip through the employee portal, as
  an employee of any client does. That door is keyed on the person's own employee row
  (`apps/api/routers/portal_employee.py`), not on the client, so G1 does not stand in it
  and does not need to: it shows a person their own pay and nobody else's.
- **A payroll list across clients leaves the practice's own staff out, for everybody (G2).**
  The roster with no client named, the runs, the attendance and declaration boards, the hub
  and the exceptions answered "every employee the caller may see", which for a Partner is
  the whole firm. Once the practice could have employees, that put a Partner's own
  colleagues among their clients' employees, under a client name the screens cannot show
  (every client picker leaves the practice out). Each of those lists now goes through one
  helper in `apps/api/routers/payroll.py`, the assignment narrowing and then G2, and a test
  fails a list that narrows by assignment alone. The practice's payroll is reached by NAMING
  the practice, from My practice.
- **Three lists have a door for the practice, and only for a Partner who names it.** Each is
  the only place one thing about the firm's own staff can be read: the attendance sheet
  (`GET /api/payroll/attendance-board`, the one editor of attendance), the leave ledger
  (`GET /api/payroll/leave-ledger`, the only list the Leave tab draws) and the line a
  client's Payroll page reads to say whether payroll is switched on
  (`GET /api/payroll/client-states`). Each takes the client its screen was opened for and
  adds that one client's rows when it is the practice, after the scope check and the
  practice check; the attendance sheet says so in `practice_client_id`, so the screen can
  name it "My practice". Any OTHER id is ignored there and never refused: on these lists it
  only preselects a picker, and a stale id in a bookmarked address must not turn the whole
  sheet into a 404.
- **What an independent review of this change found, all fixed in the same pull request.**
  (1) `GET /api/payroll/reports/year-end` with no client named was not narrowed AT ALL: its
  service reads every run of the firm with the privileged client, so anybody with payroll
  read (a Manager assigned to nothing) was sent the name, PAN, gross, net and TDS of every
  employee of every client. The hole was older than this change; this change would have put
  the firm's own salaries behind it. The service now cannot be called without being told
  which runs may be answered for, and the route passes the same narrowing as every other
  list. (2) The practice's own Payroll page said "Payroll is off" while payroll was on,
  because the list it reads leaves the practice out. (3) The Leave tab could not show the
  firm's own staff. (4) The firm hub's Payroll tile counted the practice's runs, which its
  own list leaves out. (5) The first test of "every list across clients" failed only a call
  spelled one way, so a list with no narrowing passed it; the rule is now over the ROUTE: a
  payroll route that can be called without naming a client, a run or an employee must go
  through the narrowing helper, or be on a short named list with the reason it lists nobody.
- **A member of staff is two records, and one column says they are one person (POST-A-540,
  22-11-2026).** A sign-in on Team is a row of `users`; an employee the firm pays here is a
  row of `payroll_employees` on the practice client. `payroll_employees.staff_user_id`
  (migration 776) links them. A LINK, NEVER A MERGE: neither record is written from the
  other, a name may be spelt differently on each (the list says so and changes neither),
  and removing the link removes neither. The column is on the payroll side on purpose: the
  Team list is a Manager's too and never carries it, so only somebody who may read the
  firm's own payroll can read who is on it. Three rules, each said in a sentence by
  `apps/api/services/practice_staff_link_service.py` before anything is written and each
  also held by the database: the member is this firm's, the employee is in the firm's OWN
  payroll (a client's employee is nobody on the Team screen), and one member is at most one
  employee. Two routes: `GET /api/payroll/practice-staff` (the roster with its links and
  nothing of pay, a Partner's alone and 404 to anybody else) and
  `PUT /api/payroll/employees/{employee_id}/staff-link` (write or clear one link). An
  employee can also be created linked (`POST /api/payroll/employees` with the member named).
  One panel shows both records side by side, on Team and on the practice's Payroll page, and
  offers each from the other. It is NOT the employee portal's sign-in
  (`payroll_employees.auth_user_id`, a different principal with no `users` row); whether one
  sign-in may be both is open (POST-A-549). Held by
  `test_a_team_member_and_their_payroll_record_are_linked_and_never_merged.py` and
  `test_776_an_employee_of_the_firms_own_payroll_names_the_team_member_they_are_pg.py`.
- Held by `test_the_practices_own_payroll_is_the_partners_alone.py` (the rule over every
  door; a door driven as a Manager and as a Partner with the other two layers taken away;
  the lists across clients; the attendance sheet named and not named) and
  `test_batch2_internal_client.py`.

**Not done, and worth knowing before a firm relies on it.** The practice is left out of
every client population (G2), and the compliance calendar is one: the monthly deposit and
quarterly return dates of the firm's OWN payroll are not put on the calendar. The firm-level
Payroll screens are about the firm's clients, so the firm's own payroll is opened from My
practice and not from them; of those screens only Attendance has been given a way to show
the practice (when opened from the practice's own Payroll page, its Leave tab included), and
the firm-level Statutory, Declarations and Reports screens do not list it. The year-end
report and the list of years read their runs without paging, as they did before. Whether an invitation to the employee portal accepts the email
of a colleague who also signs in as staff was not tried. None of this was run against the
live site.

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
an invoice already exists for (schedule, period)?  -- yes -->  return it: created = false;
   | no                                                        if the period is the schedule's
                                                               own current one, the schedule
                                                               advances (a failed advance after
                                                               an earlier run is finished here)
   v
ensure_customer_link()    G3: the client's ONE customer in the practice's books
   v
create_invoice            the sales engine: GST, insert  ->  DRAFT, number DRAFT-xxxxxxxxxx
   |                      (refused at issue until a person replaces it), line at SAC 998211,
   |                      NO journal
   v
_stamp_billing_fields     billing_schedule_id, billing_period, source = 'billing'
   |    unique violation (uq_client_sales_invoices_billing_run): delete the orphan draft
   |    and its lines, return the invoice that won
   v
_advance_schedule         next_run_date moves on, measured from the schedule's anchor_date
                          (migration 511) by domain/recurrence, so a run on the 31st keeps the
                          31st; a one_time schedule closes (is_active false)

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
  and benchmark pages) sits outside this record. The profitability page's rule (revenue
  before GST on issued fee invoices, less each member's cost rate times their hours, and an
  unknown shown as a dash) is the design-record entry in `docs/design-record/screens-and-site.md`
  (POST-B-321, closed 12 November 2026).

## 6. Time capture

Capture and visibility, not analytics. `time_entries` carries `is_billable`,
`billable_rate_paise` (migration 073) and `billed_invoice_id` (migration 078), and `is_billed` is a
**generated column** derived from the link, so it cannot be written and cannot disagree.
`users.cost_rate_paise` is Partner-only (`GET /api/billing/staff-cost-rates`, set on the
Profitability screen) and is the input to ONE figure, the cost in `/api/analytics/profitability`
(POST-B-321): what an hour costs the firm is not what it bills, so it is never a price, never
an input to a rate and never read by anything that values work for a client.

A rate is read in a fixed order (`domain/billing/time_rate.py`, migration 451): the
entry's own, the engagement's override, the person's default, and then **nothing, which is
not zero**. The answer is stored on the entry so a later rate change does not re-price
logged work. `GET /api/billing/unbilled-work` aggregates in SQL (`unbilled_time_summary`)
and lists work with no rate apart from work worth a stated amount.

**Time is billed through the sales engine** (POST-B-194, 21-11-2026). A Partner picks a
client's unbilled entries (`GET /api/billing/unbilled-work/entries`), sees the lines a draft
would carry (`POST /api/billing/time-invoices/preview`) and makes ONE draft sales invoice in
the practice's own books (`POST /api/billing/time-invoices`). `time_billing_service.create_draft()`
resolves the client's customer the way a schedule does (`billing_service.ensure_customer_link()`),
creates the draft with the sales engine's own create function under SAC 998211, and then marks
the entries in a claim that takes only entries still unbilled; if the claim took fewer than
were asked for, the draft is deleted (which releases what was taken: the link is `ON DELETE
SET NULL`) and the request is refused, so an hour is billed once. A line is the SUM of its
entries' worths at a quantity of one, with the hours in its words, so the draft adds up to
what the Unbilled Work panel showed; a line written as hours times a rate would not (a
quantity holds three decimals). The rate of GST and the practice's service are stated on the
request; the route holds no default. Deleting the draft releases its time (the database does
it), cancelling an issued time invoice releases it too (`time_billing_service.release_for_invoice()`,
called by the cancel route), and time on an invoice cannot be deleted or re-priced. The legacy
`from-time` route on the earlier fee tables, which no screen called, is removed. **Not done:**
a signed-in session can still write the link column straight to the database (the table's
grants are the firm's; POST-A-546).

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
- **Search reads the title and the current text** (POST-A-216, 15 November 2026). An
  article is found when every word of the search is in its title or in its current text;
  one word may be in each ("TDS rent" finds an article titled "Rent" whose text says
  "TDS"). For each word, `knowledge_service.search_articles()` reads the articles whose
  title holds it and the version rows whose `content` holds it, both with `ilike` (any
  case, anywhere, a typed `%`, `_` or backslash matched as itself; a typed `*` still
  matches anything, because PostgREST reads it as `%` and has no escape for it), and keeps
  a version only when it is its article's `current_version`: words edited out of an article
  do not find it, and a restore, which writes the old text as a new version, makes it
  findable again. The articles found by their text are read under the same firm, archived,
  scope and client filters as the title match, and the per-row visibility below applies to
  all of them. Each row says where the words were (`matched_in`: title, text or both), and
  both screens say so when it was the text alone. Every read is paged, so no match is lost
  to the server's first thousand rows, and a search of more than eight words is refused in
  words rather than cut short. **There is no ranking**: the list stays last-updated first,
  and there is no full-text query or stemming, although the June design promised both and
  migration 073 built the GIN indexes for them (they still serve nothing; `ilike` does not
  use them). **A known limit, not a defect today:** the version read is sized by how many
  versions in the firm hold a word (old versions and other scopes included), not by the
  answer; production held no article on 17 October 2026, and if a firm's knowledge base
  grows into the thousands, an SQL function that joins each article's current version is
  the next step. The first sentence is held to the code and the ranking sentence is tested
  to expire.
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
  `knowledge_article_versions`, where the content lives, follows its article since
  migration 501: a version is visible only to someone who can see its article, appended
  only by the `knowledge:write` tier and never updated or deleted by a signed-in session
  (POST-A-009, closed). `test_knowledge_client_scope.py` and `test_batch6_knowledge.py` hold the
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
| Search is Postgres full text with ranking | every word in the title or the current text, by `ilike`, no ranking (§7) | **no ledger line** for ranking |
| Manager is firm-wide | firm-wide in the knowledge base alone (§7) | POST-B-029 |
| Department is an organisational tag | the same, by decision, still free text | POST-B-331 |
| Global search may include articles | it does not | POST-B-287 |
| Versions inherit the article's visibility, immutable | the same, by migration 501 | closed |
| `POST /collections/send-reminders` | gone; `flag-followups` sends nothing (§5) | POST-B-196 |
| Practice context-switches into the internal client's shell | it does, since POST-A-532: My practice is the client workspace's shell, on the practice's own client and on the fixed `/practice/...` screens (§2) | closed |
| Frontend roles Partner, Manager, Article, Staff | the five canonical roles (Module 9.0) | closed |
| Rupee-to-paise conversion in the schedule form | goes through `lib/money/rupeeInput.ts` | closed |
| `billing_schedules.service_id` has no foreign key | mandatory and keyed (migration 206) | closed |
| Practice Billing and AR link to the invoices | they do not yet | PRE-A-018 |
| Fee billing: one engine | decided 20-11-2026: the sales engine survives. The `fee_*` screens are a read-only record on My practice (§2); profitability, concentration and realization read both places (§2); the server's `fee_*` routes and the readers of `fee_engagements` remain | POST-B-193 |
| Time is billed | nothing bills it | POST-B-194 |
| Bridge residue: two rate columns, two provisioners | both columns remain, read by one rule (`time_rate.entry_rate`); one provisioner (migration 610) | closed (POST-A-169) |

**Observed on 8 October 2026 while writing this, in no ledger line.** Four of the six were fixed on 18 October 2026
(POST-A-215, POST-A-216): `billing_service.generate_for_schedule()` now advances a due schedule whose period already
has an invoice; billing's cadence is
`domain/recurrence.py` measured from the schedule's `anchor_date` (migration 511), so a run date above the 28th keeps its
day (the quarterly key is still the calendar quarter, which is a key and not a statutory period); a `DRAFT-` number is
refused at issue (`routers/sales_invoices._assert_invoice_no_is_not_a_placeholder`), while a draft may still hold it; and
`knowledge_service.edit_article()` reads the highest version actually written and retries a `UNIQUE (article_id, version)`
collision, so the loser's text is saved as the version after the winner's. The G3 customer is now refreshed from the
client each time a fee invoice is prepared (29-10-2026, §3). One remains:

- Nothing schedules draft generation: `billing_service.run_due()` is reached only from
  `POST /api/billing/run`. **Decided, 18 October 2026: it stays that way.** A billing run prepares drafts that carry a
  placeholder number a Partner has to replace before issue, so an unattended sweep would only fill the Partner's list with
  drafts nobody asked for that morning; the Partner presses Run when they are ready to number them. If a firm wants a
  morning preparation, it is a deliberate, switchable job, not the default.

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

# Design record: Reporting: Schedule III captions, report performance, paging, exports

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Schedule III captions — one vocabulary, and the screen is served it

- **The fixed-assets note is a MOVEMENT, and there is one of it.**
  `domain/reporting/fixed_asset_movement.py` computes opening gross block,
  additions, deductions, closing, the same four for accumulated depreciation,
  and net block at both ends — per asset class, from already-fetched rows, with
  no database handle. Three callers read it and none re-derives it: the
  year-end note (`routers/year_end_notes.py`), `GET
  /api/fixed-assets/movement`, and both year-end PDFs. Its rules are worth
  knowing before touching any of them. **Every asset, disposed included** — an
  asset sold during the year is a DEDUCTION, and filtering it out is what made
  last year's closing fail to tie to this year's opening; only a soft-deleted
  row is excluded, because migration 351 makes that a row created by mistake.
  **The CHARGE comes off the ledger** (`account_period_balances`, twelve
  pre-aggregated rows) and the per-class split from the register's own
  `accumulated_depreciation_paise − depreciation_fy_start_accum_paise`, which
  speaks only for the asset's CURRENT depreciation FY — so an earlier year
  reports `split_known = False` rather than a split that silently omits an
  asset, and **where the two disagree the difference is STATED**
  (`movement_gaps`), never absorbed. **With no financial year it reports the
  register AS IT STANDS**, closing figures only, and says so: a movement with
  no period is not a conservative answer, it is a wrong one. The caveats are
  rendered wherever the figures are — the Reports tab, the notes screen and
  both PDFs — because a movement shown without the sentence saying the ledger
  and the register disagree is exactly the disclosure a reader would rely on.

## From CLAUDE.md section: Reporting performance — the rule, not a preference

**PAGING IS NOT THE SAME AS BOUNDING, AND A RECONCILIATION NEEDED BOTH**
(BANK-07). `bank_reconciliation_service._account_txns` was correctly PAGED and
still read every transaction the account had ever carried, because `_classify`
did the period filtering in Python — so a client three years into an engagement
shipped three years of statement lines to answer a question about one month.
Paging stops a silent truncation; it does nothing about a read that is
proportional to the ledger. `_session_txns` is the bounded one and the four
`_classify` callers use it. **`_index_account_txns` was the worse of the two**
and had no finding: it resolved the handful of ids a CA had just ticked by
reading the whole account, where the answer is `len(txn_ids)` rows.
⚠️ **THE FINDING'S OWN SUGGESTED FIX WAS WRONG, and the reason generalises.**
"Apply the period predicate in the query" is the natural reading and it breaks
the `reconciled` bucket — the ONE bucket `_classify` deliberately does not
date-filter, because a cheque written on 28 March and cleared on 3 April is
claimed by the April session whatever its own date says. A plain `BETWEEN`
would take its amount out of a tie-out that has already been certified. So the
fetch is the UNION of what the four buckets need: **the period, OR claimed by
this session**. Before narrowing any read, check which consumer does NOT apply
the filter you are about to push down.
**TWO QUERIES RATHER THAN ONE `or_`**, which is the opposite trade from the one
`_account_txns` records in its own docstring — there the rejected second
crossing was the SAME SIZE as the first, here it is bounded by what one session
has claimed and it removes an unbounded scan. It also keeps a PostgREST
or-expression out of the code, which matters because two separate fakes stand in
for the database in this suite and each would need to parse one.
**`_classify` IS UNCHANGED and still filters in Python**: it is the definition
of the four buckets, and a narrowed fetch must not become a second, quieter copy
of it. A test asserts the narrowed and unbounded fetches classify IDENTICALLY on
a fixture with a row in each limb.
**AND THE GUARD THAT BROKE WAS NAMING A METHOD AGAIN.**
`test_one_fetch_serves_all_four_buckets` counted calls to `_account_txns` and
expected exactly one — a spelling of "no bucket gets its own query" — so it
failed on a change that made the thing it cares about strictly better. It counts
reads of the TABLE now, bounded by a number that does not grow with the buckets.
That is the fourth time this pattern has been fixed; write the rule, not a
spelling of it.

**A read that IS a row set has its own rule, and it is one line: page it.**
PostgREST caps a response at ~1000 rows (`db-max-rows`) and reports nothing
when it does, so a truncated read is indistinguishable from a complete one and
every figure computed from it is confidently wrong. `core/db_paging.fetch_all`
is the one helper — keyset, never OFFSET, stopping on a short page — and it is
the one to import; no module carries a private `_paginate_all` copy now (ten hand-rolled pagers remain in the frozen list in `tests/test_no_module_carries_its_own_pager.py`),
and adding another is the thing not to do. Two guards state the rule rather
than a spelling of it: `tests/test_paginated_selects_carry_their_key.py` fails a
paged query whose `.select()` omits the cursor column (which works perfectly
until the thousandth row and then cannot advance), and it scans `fetch_all`
alongside the private copies — it did not, so for a while a call site MOVED OUT
of the rule by moving to the shared helper. Two traps at the call site:
`fetch_all` imposes its own `ORDER BY id`, so an ordering the endpoint wants is
applied to the rows it got BACK, never inside the paged query; and sort keys are
coalesced, because a nullable column such as `fixed_assets.asset_code` raises
`TypeError` in Python where the database sorted it happily.
**AND ITS FIRST ARGUMENT IS A CALLABLE, WHICH TWO CALL SITES FORGOT.**
`fetch_all(make_query, key="id", *, label, stats)` CALLS `make_query` once per
page — it has to, because a builder is stateful and reusing one stacks each
page's `.gt(key, cursor)` on the last — so the projection goes INSIDE a
`def one_page(): return db.table(...).select(...)`. Handing it the builder
raises `TypeError: '_Query' object is not callable` on page one, and a third
positional argument raises before the body runs at all. Both happened, and
**neither was visible from its own tests, for two different reasons** — which
is what makes it a class rather than a pair.
`services/reorder_service._catalogue` passed the builder, so the reorder report
has never run against a
database: `routers/inventory.reorder_report` catches it and answers "Unable to
load the reorder report. Please try again.", which reads as transient, and the
mock suite could not reach it because that router's `_USE_MOCK` branch passes
`db=None` and `assess` short-circuits to an empty answer BEFORE the fetch.
`services/hub_service._sum_paise` passed three positional arguments, and its
three tiles are computed inside `_safely`, which swallows a tile's exception by
design — so Sales, Purchases and TDS rendered "—" on the hub. One hidden by a
router's broad `except`, one by a deliberate per-tile one.
`tests/test_fetch_all_is_given_something_it_can_call.py` states the rule on the
ARGUMENTS at every call site, so a module nobody thought of is covered the day
it is written. **The durable half is the second reason: a service whose job is
to FETCH needs a test that FETCHES.** A source scan cannot see an arity error,
and a `db is None` mock branch is not the code that runs in production —
`tests/test_the_reorder_report_runs_against_a_database.py` and
`tests/test_the_hub_actually_answers.py` are the two that now do.
⚠️ **The same test found a THIRD null with no exception behind it**, which is
the `table_4a_gaps` discipline on a screen: the hub's payload defines
`answerable: true` with a null signal as *the fetch for this tile failed*, and
`Tile.no_firm_signal_because` had promised since it was written that the CLIENT
hub answers Inventory — while `_signals` computed nothing for it at any scope.
So a tile nobody had ASKED for was indistinguishable from one that had been
asked and failed. A nil meaning "nothing to do", a nil meaning "nobody can
tell" and a nil meaning "nobody looked" are three different things, and a
payload with a three-state contract has to be exercised to find out which one
it is emitting.

**THE RULE IS ABOUT THE BROWSER TOO, and that is where it was still being
broken.** Everything above is written for `apps/api`, and the frontend reaches
~83 tables directly over PostgREST — where the same ~1000-row cap applies, with
the same silence. `/accounting/budget` read `journal_lines` joined to
`journal_entries`, FIRM-WIDE, once per quarter, unpaged, and computed the
actuals in the browser: on any client with real volume every figure was short
by an unknown amount and every variance wrong, confidently, with no error
(ACC-06). The answer is one row per Revenue and Expense account — about fifty —
so it is now `GET /api/accounting/budgets`, reading `account_period_balances`
through **`ReportingService.period_net_by_account`**, which is the primitive to
reach for whenever one screen needs SEVERAL windows over the same accounts: it
fetches the chart and the buckets ONCE and projects each window through the
same `_passbook_lines` the Trial Balance uses. Four `trial_balance` calls would
have been eight Singapore-to-Mumbai round trips for one screen.
`core.ist_clock.fy_quarters` keeps the windows month-aligned (derived from
`fy_bounds`, never restating April), which is what lets the pre-aggregated
buckets answer exactly with no edge month to replay.

**AN OFFSET-PAGED READ NEEDS A UNIQUE TOTAL ORDERING, and the ordering a screen
already had is usually not one.** Postgres guarantees nothing without an ORDER
BY, and a NON-unique one — `invoice_date`, `account_name`, `client_name` — lets
ties land either side of a page boundary, so a row can come back twice or never.
The fix is a tiebreaker LAST, `.order("id")`, which need not be in the
projection and so changes no exported column. `app/risks` (six reads),
`app/accounting/receivables` and `app/accounting/coa-export` build a CSV
straight from these reads and had none of this: `compliance_calendar` carries a
row per obligation per client per period, so a 50-client book passes 1000 inside
one year, and the file opened, looked complete, and was short by whatever the
cap removed. `app/accounting/recurring` is paged too and is NOT one of them —
its Export reads `templates` from the API and its PostgREST read feeds the
account dropdowns — which the guard says rather than keeping one list by
softening the claim. **The other 68 of the 102 files touching PostgREST still
carry a read that is neither paged nor bounded**, and are left as a finding
rather than swept: most are bounded in practice by one client or one month, a
screen that truncates is at least a screen somebody is looking at, and a budget
over 68 files is the shape that gets raised until it means nothing.

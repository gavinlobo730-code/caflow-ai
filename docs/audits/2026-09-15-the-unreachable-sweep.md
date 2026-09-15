# The unreachable sweep — 15 September 2026

A snapshot, like everything else in this directory except
`findings-status.json`. It exists so the next person does not re-run four
scans that have already been run, and so the two I deliberately did **not**
turn into ratchets are recorded as decisions rather than omissions.

## Why this shape of defect

Three defects found by hand on 14 September shared one shape: something
**built, correct, tested and unreachable**. The UQC list nothing imported. The
AS 11 revaluation with no caller, so `fx_revaluations` was never written and
the Unrealized FX report was a structural nil for every client. The
§115BAC(6) regime election whose only mention outside its own tests was a
comment. ACC-19 was the same: two feature gates read by seven modules and
written by nothing.

None of those is a wrong number. Every one of them is software that knows
something and never says it, which is the failure a test suite is worst at
seeing — the code is right, so the tests pass.

`tests/test_a_domain_module_has_a_reader.py` now asks the first question
permanently. This sweep asked the other four.

## What was scanned, and what it found

| Question | Answer |
|---|---|
| Which relations does `apps/api` name that no migration creates? | **None** — 249 relations and 27 `.rpc()` functions all resolve |
| Which tables does code READ and never WRITE? | 7, **all explained** (below) |
| Which columns does code read and never write? | ~1,100 — **unusable**, see "Not built" |
| Which test files does a test cite that do not exist? | **One**, and it mattered — see below |

### The one real find

`test_backend_tables_exist` was cited by two modules at three sites, each
skipping the missing-relation case because "that is its job". **It did not
exist.** So the case both modules hand off was checked by nobody, and the
hand-off is what hid it: each module reads as covered, and the reader who
verifies is reading a comment rather than a directory listing.

Worst under a rename — rename a table and every stale reference to the old
name stops being checked for its COLUMNS too, because both guards skip a
relation they cannot find. Written as `tests/test_backend_tables_exist_pg.py`,
starting from zero offenders with both exemption lists empty.

### The seven read-only tables, each explained

| Table | Why it is not a defect |
|---|---|
| `accounts` | a compatibility VIEW over `chart_of_accounts` (migration 016) |
| `currencies`, `platform_admins` | reference data seeded by migration |
| `bank_transaction_splits` | written by `replace_bank_transaction_splits` via `.rpc()` |
| `fee_receipts` | written by `record_fee_receipt_atomic` via `.rpc()` |
| `year_end_checklists` | read by two `_page.tsx` files — disabled routes Next.js does not serve |
| `fx_rates` | reachable only through the API; both screens require an explicit rate, so the lookup is never reached. A rate master is a feature with an owner decision inside it — `questions-for-the-owner.md` §13 |

## A trap worth keeping: `public.accounts` has now been called a phantom twice

`test_frontend_tables_exist.py` once claimed it was a missing relation; its
docstring carries the correction. This sweep's first pass said the same thing
for a different reason — migration 016 DROPs the view and recreates it eleven
lines later, and a scan that collects every CREATE and then every DROP loses
the order.

**A view, a materialized view, a rename and a drop-then-recreate are each
enough to make a migration replay lie.** The new guard reads
`information_schema` instead, and pins both traps with their own tests.

## Not built, and why

Two ratchets were considered and declined. Both would have needed a large
exemption list on their first run, which is how a ratchet gets deleted rather
than maintained.

**A guard on stale test citations.** Fifteen unresolved `test_*` references
remain after discounting elisions and line-wraps, and every one is a local
variable or correct prose about a test since renamed. Fourteen exemptions to
catch a class with one historical instance — which this sweep has now fixed.

**A column-level read-but-never-written guard.** This is the one that would
have caught ACC-19, so it was measured properly: **1,100 pairs.** The parser
cannot see writes that go through an RPC, through the browser's own PostgREST
path, or through a `**spread` payload, and the database fills many columns
itself. Without a way to tell those apart the signal is noise.

If it is ever attempted again, the missing piece is a way to attribute a
write to a column across all three paths — not a longer exemption list.

# Checkpoint — 15 October 2026 (IST): the security and truthfulness run of 14 to 15 October, what landed, what is staged, what is owed

**`main` at `9338822c`, the merge of #750, at about 01:34 IST.**

> **A snapshot, not a ledger.** The ledger is `README.md` and its six section files; this note says where a long
> run of pull requests stopped so the next session does not have to reconstruct it. Counts below were true when #750
> merged (`python3 scripts/open_items_counts.py` gives today's). Every claim here about code was true of `main` on
> that day and goes stale like any other snapshot: read the code before acting on one. It follows
> `checkpoint-2026-10-09.md`, whose build waves are not repeated here.

## 1. Where things stand

- Open items: **557** (23 before the demo, 534 after) and **150 parked** (not counted). 12 after-demo items are
  `high` priority; 32 are UNSURE.
- **The demo has no date**, as on 9 October. The goal in `CLAUDE.md` (replace every platform on the market by being
  better; public release only when fully complete; filing the last stage) and the owner's standing instructions
  (#729 to #731) govern how the work is ordered: security gaps, privacy-law deadlines, anything false on a screen and
  statutory correctness first.
- **Production database:** migrations up to **498** are applied; 495, 496 and 497 were each checked in
  the live catalogue after their merge (495 at 21:58, 496 at 23:10 on 14 October, 497 at 00:36 on 15 October);
  498 (the payroll freeze) applied at 02:02 on 15 October and was read back the same way: both triggers are present and enabled, and neither trigger function can be called by a signed-in role.
- **The one thing that unlocks the most remains the owner's:** letting this environment read the government sites
  (`owner-list.md`, section 1). Every statutory figure still graded `[S]` waits on it.

## 2. What landed since the 9 October checkpoint (squash-merged to `main`, #727 to #750; #732 to #734 are not on `main`)

| PR | What | Ledger / migration |
|---|---|---|
| #727, #728 | The 9 October checkpoint; the plan for working through the ledger faster (decision sheets, themed batches, a parked list) | — |
| #729, #730, #731 | The owner's standing working instructions written into `CLAUDE.md`; `CLAUDE.md` slimmed from about 635 KB to about 171 KB with its design write-ups moved verbatim to `docs/design-record/`; the product goal rewritten | — |
| #735, #736 | The 374 owner-question rows answered (what Claude decided) and the owner's single list; 150 wait-until-asked items parked so the headline count means the real queue | `decisions-taken-2026-10-14.md`, `owner-list.md` |
| #737 | Role tiers in the database for vendors, knowledge articles, cross-client matches and year-end notes; the audit log Partner-only; portal contacts scoped | 483, 484 |
| #738, #741 | The database asks the payroll tier and the clients in reach of the employee, run and payslip rows, then of the twelve other payroll tables | 485, 490 |
| #739 | The database functions that write as their owner ask who is calling (the critical one) | 486 |
| #740 | A Reviewer cannot write the books, the returns or the client records | 487 to 489 |
| #742, #743 | GST approval and rebuild, MCA filing and the ITR tick go through the API's rules; a declaration's status, the timeline pin and bank-transfer pairing closed | 491 to 494 |
| #744, #745 | The practice's fee tables readable only by someone with billing access, at every door and then in the database; a client with live fees can no longer be deleted by someone who cannot read fees, and a delete whose checks could not be read is refused | 495 |
| #746 | Only someone who may approve income tax work can record a tax audit as completed or filed | 496 |
| #747 | A portal contact's invite secret is unreadable to signed-in staff; a re-invite no longer locks out a client who already accepted | 497 |
| #748, #749 | The Scheduled Reports screens, the invoice "Viewed" badge and the free-trial, no-card and annual-discount claims on the public site say only what is true; the owner's list refreshed | — |
| #750 | A finalized or paid payroll run, and its payslips, cannot be changed from a signed-in session (an independent review of the diff found five red tests and four overclaiming sentences, all fixed before merge) | 498 |

## 3. Staged and NOT pushed

- **Migration 499 (ledger POST-A-234), on hold at the owner's request.** It revokes the signed-in write privilege on
  seventeen payroll tables the browser never writes, because a Manager can still write a draft payroll run and its
  payslips directly and the finalise journal is built from the run's totals, so a Manager can choose the figure a
  Partner's finalise posts. The migration, its rollback, a rule-shaped guard, the restated grid probes and the
  rewritten Team-screen sentence exist in a scratch copy of the repository; the access-matrix expectation still has to
  be regenerated and reviewed, and the full real-database suite has not been run on it. Nothing of it is on `main` or
  on the work branch. Its design is in the ledger line POST-A-234 until the line is replaced.

## 4. Open items this run created or narrowed

- **POST-A-234** (the 499 work above), **POST-A-233** (a Form 3CD checklist can be marked `finalised` by an Executive),
  **POST-A-228** (timeline actor chosen by the browser), **POST-A-227** (tasks written from the browser),
  **POST-A-221** (`is_fy_locked` answers for a firm that is not the caller's).
- **POST-B-264** narrowed to what is the owner's: plan limits, "Priority support", the phone tier and the onboarding
  specialist. **PRE-B-002** part 1 narrowed: the Scheduled Reports screens no longer promise email, and the prepare
  and Send build is still to do.
- Not started and noted for later: POST-B-011 (a suspended firm at the database), POST-B-041 (narrow the
  `user_client_assignments` read), POST-B-035 (leads scope), POST-B-208 (an invented unit of measure), POST-B-008 and
  -009 (the data-protection access log and request pack), POST-B-013 (the second factor's scope).

## 5. What is owed, and by whom

Everything that is the owner's lives in **`owner-list.md`** (refreshed 15 October): money (13 rows, each with a
recommendation), what only the owner can do (9), and the statutory and legal points Claude will not assume (11).
Added today: row 13 of the money table, what each plan promises; and the Supabase check on whether a new account must
confirm its e-mail before it can sign in, because a client's portal invitation is accepted by signing in with the
invited address.

## 6. How this run was verified, and what was not

- Every migration in this run applied to production only after both required checks were green on the merge and,
  from 495 on, the owner-facing effect was read back from the live catalogue.
- The whole real-database suite was run locally on the final tree before the last two merges (2,576 tests for #747,
  2,655 for #750), because a hand-picked list missed a guard that failed in CI the first time (#747).
- The full mock-mode suite has three failures that occur in this build container only and on `main`
  (`test_an_import_of_services_is_not_a_domestic_reverse_charge…` and two in
  `test_the_server_does_not_fetch_wherever_it_is_pointed.py`).
- **Not verified:** nothing here was driven in a browser against the live deployment; the Supabase sign-in settings and
  the AI-provider tiers are the owner's dashboards and have not been read; the statutory figures `[S]`-graded in
  `CLAUDE.md` remain unconfirmed from primary texts.
- **Working practice that earned its keep:** an independent, read-only review of a single diff (#746, #747 and
  #750; the one on #750 used about 343 thousand tokens) found gaps the author's own run had not: three on the tax-audit
  screen, and on #750 the red tests and the false sentences. A review is given the code and the threat and never the
  conclusion.

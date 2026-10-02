# Service levels — what we aim for, what is measured, and how a budget gets tighter

Written 01-10-2026 for ops-12. **The targets below are proposed, not ratified: a target is a product
decision and the owner confirms or changes each number.** **No thirty-day reading exists yet.** The history
starts accumulating from the first scheduled run after `.github/workflows/smoke.yml` carries this change
to `main`, and the table in §4 will say how many days it covers until it covers thirty.

## 1. Two numbers that are not the same thing

| | what it is | where it lives | what it does |
|---|---|---|---|
| **budget** | the most one answer from one endpoint may take | `budget_s` on each `Check` in `apps/api/scripts/smoke_api.py` | **fails that run.** A tripwire for "something is badly wrong". Deliberately generous (5 to 20 s) so it does not flap |
| **target** | what the 95th percentile of an endpoint's answers should stay under, over 30 days | `target_s` on the same `Check`, and the table in §2 | **fails nothing.** It is judged on the history by `apps/api/scripts/smoke_timings_report.py` and reported |

A budget cannot see a slow drift: the P&L can go from 1.5 s to 6 s and never come near its 20 s budget.
A target cannot be a gate: a single unlucky sample would turn the build red, and a check that cries
wolf is one nobody reads (the cold-start history in `apps/api/scripts/smoke_api.py` is why `wake()` exists).
So each does the one job it can do.

## 2. The targets

The table is read by `apps/api/tests/test_the_smoke_timings_are_kept_and_the_targets_are_written.py`, which
fails if a row disagrees with the `Check` of the same name, if a check has no row, or if a budget is less than
twice its target. **Change the code and this table in one commit.**

| endpoint (smoke name) | target p95 (s) | budget (s) | the one reading on record |
|---|---:|---:|---|
| `health` | 1 | 5 | none recorded |
| `identity/permissions` | 2 | 8 | 0.89 s |
| `clients/obligations` | 3 | 15 | 1.01 s |
| `accounting/profit-loss` | 3 | 20 | 1.50 s |
| `accounting/cash-flow` | 3 | 20 | **10.41 s: not met on that reading** |
| `accounting/trial-balance` | 3 | 20 | 1.31 s |
| `currencies/policy` | 2 | 8 | 1.14 s |

**"The one reading on record" is a single sample, not a percentile.** It is the table in the header of
`render.yaml`, taken by hand on 15-08-2026 after the move to Singapore, with `USE_USER_JWT` on. Nothing
else in the repository records a response time, and the figure for cash flow predates the SQL function that
now computes it (`public.cash_flow_report`, migration 277): **no later reading is recorded**, so whether the
target is met today is unknown, not "met" and not "missed". The first thirty days of the history are what
answer it.

**Why these numbers.** 3 s for a report is the figure the audit that asked for this proposed; nothing in the
repository measures how long a CA will wait, and no screen has been timed with one. Lists and lookups get
2 s and `health` 1 s because they do the least. They are a starting position to be argued with, not a finding.

### The conditions a number is measured under

* **A warm instance.** The wake is untimed and reported on its own line (`wake()`); on the free tier a cold
  start was measured at 56.55 s on 2026-09-06. A target says how fast the service answers when it is up,
  not how long it takes to get out of bed.
* **A client with a real ledger.** The targets assume the client named by the `SMOKE_CLIENT_ID` secret holds
  about 12,000 entries, the volume the 57-second incident was measured on. **The repository cannot see which
  client the secret names. A person must confirm it**: if it names a small client, every number is flattering
  and proves nothing.
* **From a GitHub-hosted runner.** Its region is not chosen by this repository, so a figure includes the
  network distance from wherever that runner is to Render in Singapore, and says nothing exact about what a
  CA in Mumbai sees.
* **As the API actually runs.** Whatever `USE_USER_JWT` is in production is what is measured. Hold it fixed
  when comparing anything: `render.yaml` records a 4.8x "win" that was a deployment doing less work.

## 3. What has no target, and why

* **Availability.** No target. The smoke run is four samples a day and no uptime monitor is attached to
  `/ready` anywhere the repository can see, so a percentage would be a number with no instrument behind it.
  The public site's "SLA & account manager" bullet is already in the claims ledger as unproven
  (`apps/api/tests/_marketing_claims.py`, id `sla-and-account-manager`); writing an availability figure here
  would be the first step towards that claim without the means to keep it. The history does record a run in
  which the API never answered `/health`, and the table counts them.
* **Writes.** The smoke check only reads. A posting or an invoice needs a throwaway client to be timed
  without touching a real ledger, and that does not exist.
* **The ten most-used endpoints.** The audit asked for them. There is no usage telemetry (no analytics, an
  owner decision), so "most used" cannot be derived. The seven above are the ones the first two screens call.
  To add one: a `Check` with a budget and a target in `smoke_api.py`, and a row in §2.
* **Rendering in the browser.** The nightly smoke walk (`.github/workflows/smoke-walk.yml`) records how long
  each screen took to settle, against a local stub rather than the real API. That is useful for noticing a
  screen that became ten times slower to draw; it is not a service level.

## 4. Where the history is, and how to read it

Every smoke run that measured anything uploads `smoke-timings-live-<run id>-<attempt>`, one small JSON file,
kept 90 days. What it holds: each endpoint's name, response time, budget, target and status, the wake time,
the commit and the run id. **What it never holds:** a URL, a path, a client id, an address or a credential
(the artifact is public: so is the repository). A manual run aimed at a candidate deployment is named
`smoke-timings-candidate-…` and is left out of the live history.

The last step of each run reads the live artifacts of the last 30 days back and writes this table to the
run's summary page (Actions, API smoke, the run, Summary):

| column | meaning |
|---|---|
| answered | samples where the endpoint did its job (a 2xx, or the MFA guard refusing a password-grant token, which is the policy working). Percentiles are taken over these only: a 503 that returns in 50 ms is not a fast answer |
| p50, p95, max | nearest-rank percentiles of those samples |
| over budget | answered samples slower than the budget (each of which also failed its own run) |
| failed | samples where it did not answer properly |
| verdict | `within target`, `OVER target`, `not enough samples` (fewer than 20 answered samples: with n of 5 the p95 is simply the maximum), or `no target` |

Under it, the p95 week by week, so a creep shows before the 30-day figure moves. **The table says how many
days it covers.** Until the artifacts span thirty days it says so and does not call a week a month.

To look further back than the summary does, download the artifacts and run
`python3 apps/api/scripts/smoke_timings_report.py <folder> --days 90`.

## 5. Tightening a budget

A budget is tightened when the history supports it, one endpoint at a time:

1. The last 30 days hold at least 100 answered samples of that endpoint and its verdict is `within target`.
2. The new budget is **no less than twice the target and no less than 1.5 times the largest answered
   sample in that window**, rounded up to a whole second. (Every budget above is already at least twice its
   target, so the second condition is the one that will bind first.)
3. It is its own commit, naming the endpoint and quoting the table's row. It changes `budget_s`, and the
   table in §2, and nothing else.

**This change tightened none.** A tighter budget needs the numbers that do not exist yet.

A budget is **raised** only for a reason that is written in the commit and is not "the run was red": a
budget raised to silence a failure is exactly how a tripwire stops being one.

When a target is exceeded, look at the endpoint. Do not move the target to meet the number; changing a
target is the owner's decision.

## 6. What was verified, and what was not

* Verified here: the timings file is written for a passing run, a failing one and a run in which the API
  never answered, and holds none of the secrets the run was given; the report's percentiles, windows,
  weekly table and "not enough samples" rule; that a target never changes an exit status; that the
  workflow's last step builds its table from a fake `gh` and a zipped timings file; that this table equals the code.
* **Not verified: any of it on GitHub.** No workflow can run from here. The artifact upload, the listing and
  download through the API with the run's token, and the summary page are first exercised by the first
  scheduled run after merge. If the last step fails it is `continue-on-error` and the run's own result is
  unaffected, so the signal is a missing table, not a red run: look for it on the first run.
* **Not verified: that the client behind `SMOKE_CLIENT_ID` has a real ledger** (§2).

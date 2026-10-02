# Post-mortems — what has gone wrong before, and where it is written down

Written 01-10-2026 for ops-29. Until now these accounts lived only as prose: comments in `render.yaml`,
docstrings, workflow headers and long paragraphs of `CLAUDE.md`, so "has this happened before?" meant
remembering which file to search. This is the index, and the place the next one is written.

**What was checked and what was not.** Each row was compiled from the source it names, read on 01-10-2026.
Dates are **as that source states them**; a row whose source gives none says so, and none was reconstructed from git
history. Nothing in a row was independently confirmed beyond that, except that every file named here exists
(`apps/api/tests/test_the_runbooks_say_what_has_not_been_done.py` checks the paths). **No entry here is a
blameless review held with the people involved**: they are written records, and "what now guards it" is the part
to trust least until someone has tried to break the guard.

## 1. The index

| # | when | what happened | where it is written | what guards it now |
|---|---|---|---|---|
| 1 | 2026-08-15 | **The move to Singapore took the product down.** The service was recreated and `USE_USER_JWT` and `REQUIRE_MFA` were left unset. With the first unset, the API queried as `service_role`, and 57 tables that live code reads had been granted only to `authenticated`, so reads raised and a bare 500 came back; the Bank page died on exactly that. The same move produced a false "4.8x win" for cash flow, measured while the service was running as `service_role` with RLS bypassed | `render.yaml` ("Security flags", and the region header with the measurements) | production now defaults both switches ON (`apps/api/core/security_config.py`); the running service reports what it resolved (`apps/api/core/security_posture.py`, `GET /api/security/posture`); `/ready` says `config` when the environment is empty (`apps/api/core/readiness.py`) |
| 2 | not dated in the source; "every deploy for weeks" | **Every Render deploy timed out on its health check** ("Timed out after waiting for internal health check…") because three cross-region database round trips ran at import time. A failed deploy left the *previous* image serving while the migration job still applied that commit's migrations, so the database ran ahead of the code until someone deployed by hand | `apps/api/main.py` (the `_lifespan` docstring) | `apps/api/tests/test_health_answers_before_the_slow_boot.py`; the slow half of startup runs on a thread and `/health` answers 200 while the check is outstanding |
| 3 | not dated; migrations 233 to 241 sat "up to 6 days" | **Migrations were committed and green in CI but unapplied to the real database**, while code that depended on them was live and failing quietly behind broad `try/except` | `docs/deploy-migrations.md` | the `deploy-migrations` job (`.github/workflows/backend-ci.yml`); `apps/api/core/schema_guard.py`, which now also re-checks on a timer and covers tables and functions |
| 4 | not dated | **A migration failed partway and kept what ran before the failure** (migration 055 is the named case). Because a failure is remembered and never retried, the half-applied change stayed on the live database; the next push could skip the broken file and go green with the change still missing | `apps/api/scripts/db/apply_migrations.py` (module docstring), `docs/deploy-migrations.md` | each file now runs in one transaction; a remembered failure keeps the run red (`apps/api/tests/test_the_migration_runner_is_atomic_and_remembers.py`) |
| 5 | not dated | **Scheduled jobs never ran on a sleeping instance.** The scheduler runs inside the API process, and a free-tier instance that has spun down cannot fire a timer at 06:00 IST | `.github/workflows/wake-before-scheduler.yml` (header) | that workflow, and the start-up catch-up `run_catchup_if_stale` in `apps/api/jobs/scheduler.py` |
| 6 | 2026-09-06 | **The API smoke check was permanently red** because the first request paid the free-tier cold start, 56.55 s against a 5 s budget on `health`. A check that is always red is one nobody reads | `apps/api/scripts/smoke_api.py` (`wake()`) | the wake is untimed and printed on its own line; `apps/api/tests/test_the_operational_notes_say_what_was_measured.py` stops a note stating a cold start shorter than the measured one |
| 7 | 2026-09-09 | **A required check failed on a pull request that touches neither Chrome nor apt**: Google's Chrome apt repository served a package index that did not match its own release file, and `apt-get update` exits 100 if any source is inconsistent. It failed the same way twenty minutes later | `.github/workflows/backend-ci.yml` (the comment above "Install psql client") | third-party apt sources are dropped before `apt-get update`, in both jobs, and in `.github/workflows/smoke-walk.yml` |
| 8 | 2026-09-29 | **Groq retired the model the product defaulted to** (`llama-3.3-70b-versatile`); a live call returned `model_not_found`, 404 | `apps/api/domain/ai/groq_text.py` ("What happened next") | the default moved; a fallback model can be set with no deploy and no name is built in (`apps/api/tests/test_the_ai_gateway_retries_falls_back_and_says_why.py`) |
| 9 | 2026-09-30 | **Cloudflare dropped redirect rules past its cap, silently.** The product's `_redirects` file is a budget of 100 dynamic rules and Cloudflare counts every rule after the first dynamic one as dynamic, so rules 109 to 138 were ignored. A reload or a shared link into `/clients/<id>/<section>/` returned 404 in production while clicking around the app looked fine | `apps/web/scripts/generate-redirects.js` (header), `CLAUDE.md` (Deployment) | literal rules are emitted first and the count is measured the way Cloudflare counts (`apps/web/scripts/generate-redirects.test.ts`); `.github/workflows/live-redirects.yml` asks the live site about every rule |
| 10 | 2026-09-30 | **The error monitoring could not have worked.** The alert rule on `posting_operation` matched nothing, because the log record's untagged event went out first and Sentry's de-duplication dropped the tagged one; the browser reported nothing because its Sentry config had no importer; and request bodies and local variables were being sent | `docs/operations/error-tracking.md` (§2) | `apps/api/tests/test_the_posting_failure_alert_has_its_tags.py` starts the real client with a capturing transport and reads the event that would have left |

## 2. Where the rest are

* **Defects found by audits** are not incidents, and their long accounts are the bold-headed paragraphs of
  `CLAUDE.md`. Each ends with what was deliberately not done, and most name the test that now holds the rule.
* **Which findings are open or closed** is `docs/audits/findings-status.md`, the only status record kept up to
  date. The dated audit documents beside it are snapshots and were never amended.
* **What was measured and what could not be** for the monitoring work is in `docs/operations/error-tracking.md`
  and `docs/operations/database-monitoring.md`.

## 3. How to add one

Add a row to §1 in the same pull request that fixes it, and fill the five columns:

* **when**: the date it began, in IST, and when it was resolved if that was a different day.
* **what happened**: one or two sentences in plain words, including **how it was noticed** and **who was
  affected**. Say how long it lasted. Do not say what was not checked.
* **where it is written**: the file where the long account lives. If there is none, write it there first; a
  row that points at nothing is the thing this file replaces.
* **what guards it now**: **a test or a check that fails if it recurs**, by path. "Be more careful" is not a
  guard. The repository's habit is a test that states the rule rather than one that pins today's spelling of it,
  because a guard that names a location breaks on a move that does not break the rule.
* If something was found that was **not** fixed, say so in the account and in `docs/audits/findings-status.md`.

The incident itself is handled with `docs/operations/incident-runbook.md`, and undone with
`docs/operations/release-and-rollback.md`.

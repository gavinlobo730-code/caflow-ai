# Releasing a change, and undoing one

Written 01-10-2026 for ops-29, from the workflows, `render.yaml` and `docs/deploy-migrations.md` as they are.

> **THIS HAS NOT BEEN TABLE-TOP TESTED.** No rollback described here has been performed by anyone other than
> its author, and the Render and Cloudflare steps have **never been run** against the real services: they are
> from memory of each product, and the environment this was written in refuses egress.
> `docs/operations/incident-runbook.md` §10 is the exercise that tests them, and its record is empty.

Blanks marked `[FILL IN: ...]` are facts about accounts that the repository cannot see. Nothing here contains a credential.

## 1. How a change reaches production

Three things happen when a pull request merges to `main`, **independently and in no guaranteed order**:

| what | how | where it is defined |
|---|---|---|
| **migrations are applied to the production database** | the `apply pending migrations — production` job runs `scripts/db/apply_migrations.py --only-schema` once the tests and the migration-apply check pass, and only for a push to `main` that touched backend files. **No person reviews it in between** | `.github/workflows/backend-ci.yml`, `docs/deploy-migrations.md` |
| **the API is built and deployed** | Render builds the Docker image from `apps/api` and replaces the running instance once `/health` answers. `render.yaml` sets no `autoDeploy` and no branch, so which branch is linked and whether a push deploys by itself is a setting in Render's dashboard: [FILL IN: branch, auto-deploy on or off] | `render.yaml` |
| **the two sites are built and published** | two Cloudflare Pages projects build `apps/web` and `apps/marketing` from this repository. The product project's build variables (`NEXT_PUBLIC_*`) are baked into the bundle at build time | `CLAUDE.md` (Deployment), `apps/web/wrangler.toml` |

The two **required** checks on `main` are `pytest — mock mode (Python 3.11)` and `migration apply — real Postgres 16`
(`.github/workflows/backend-ci.yml`). Everything else, the smoke runs, the screen walk, the image build, the
dependency audit, is informational.

**Because the order is not guaranteed, the database and the code are routinely out of step for a few minutes,
and the system is built to tolerate one direction of it:**

* **The database ahead of the code** (the migration landed, the deploy has not yet, or failed) is the ordinary,
  safe case. Migrations are additive, so older code runs against a newer schema. A failed Render deploy leaves the
  *previous* image serving while the migration job still applies that commit's migrations, so this can last until
  somebody deploys by hand (`apps/api/main.py`, the `_lifespan` docstring, records this happening for weeks).
* **The code ahead of the database** (the deploy landed, the migration is late or red) is the dangerous one.
  `/health` goes 503 `schema_drift` and says so, and the guard re-checks every two minutes so it clears by
  itself once the migration lands (`apps/api/core/schema_guard.py`). Tables and functions the code calls that the
  database lacks are **reported** in `schema_objects` and do not yet turn `/health` red.

## 2. Before merging something that can hurt

None of this is enforced; it is what to do on purpose.

1. **A migration**: read it as if it runs tonight against the live database, because it does. Additive and
   idempotent: `ADD COLUMN IF NOT EXISTS`, nullable or with a safe default, no data rewrite, no `DROP`, no policy
   removed. `python scripts/db/apply_migrations.py --dry-run --json` (from `apps/api`) shows how each pending file
   would run, and which would not be wrapped in a transaction (`not_atomic`, with its reason).
2. **A migration touching a hot table** (`journal_lines` and the like) holds its locks until it ends; keep it short
   and few in statements, or split it (`docs/deploy-migrations.md`, "What the wrapper costs").
3. **Say how it would be undone in the pull request.** If the honest answer is "it cannot be", say that, and
   say what the owner is accepting.
4. **Do not merge it on a deadline day** if it can wait: the 7th, the 11th and the 20th of the month, the
   advance-tax dates and 31 July are the days a CA is working in the product
   (`apps/api/services/compliance_engine.py` is the authority for every date). A recommendation, not a rule.
5. **After it merges**, watch the migration job, then `/health` and `/ready`, then run the API smoke by hand
   (Actions, API smoke, Run workflow). The smoke run **skips green** when its secrets are not set, so check its
   log says it ran.

## 3. Rolling back the API

**First, the switches that are the rollback and need no deploy.** Several behaviours are controlled by an
environment variable in Render's dashboard, and flipping one is faster and safer than reverting code:

| to undo | set | effect | where it is written |
|---|---|---|---|
| per-user database access causing denials | `USE_USER_JWT=false` | the API queries as `service_role` again (RLS bypassed: this is a security downgrade, so it is a decision, and it logs an ERROR at boot) | `docs/PHASE_5_2_WS3_USE_USER_JWT_RUNBOOK.md`, `apps/api/core/security_posture.py` |
| MFA locking people out | `REQUIRE_MFA=false` | MFA no longer enforced; logs at ERROR at boot | `render.yaml`, `apps/api/core/security_posture.py` |
| a retired or failing AI model | `GROQ_TEXT_MODEL`, `GROQ_TEXT_MODEL_FALLBACK`, `GEMINI_VISION_MODEL`, `GEMINI_VISION_MODEL_FALLBACK` | takes effect with no deploy | `apps/api/domain/ai/groq_text.py` |
| the practice's own mail misbehaving | `PRACTICE_MAIL_ENABLED` unset or `false` | nothing is sent, nothing is logged as sent; in-app notices continue | `render.yaml` |
| the filing walk-throughs | `ENABLE_FILING_SIMULATION=false` | the demo walk-throughs stop | `render.yaml` |
| multi-currency | `MULTI_CURRENCY_ENABLED` unset | everything is INR-only | `render.yaml` |
| the scheduler misfiring | `ENABLE_SCHEDULER=false` | the in-process jobs stop | `render.yaml` |

**Rolling back a deploy** (Render; from memory of its dashboard):

1. Open the service `practicesync-api`, then its Events (or Deploys) page. Find the **last deploy that was
   healthy**, the one before the change that broke it.
2. Choose Rollback (the control that redeploys an earlier build) on that deploy and confirm.
3. Wait for it to report live. `/health` must answer 200; then `/ready` must answer 200.
4. **Check whether the rollback switched automatic deploys off**, and turn them back on when the fix is ready, or
   the next merge will not deploy. Render's behaviour here is from memory and is not checked:
   [FILL IN: what the dashboard showed when this was first done].
5. Run the API smoke by hand and read that its log says it ran.
6. **Make the rollback durable in git**, or the next push to `main` redeploys the same breakage: `git revert` the
   offending commit on a branch and merge it. A revert is a new commit and is itself a release (§1).

**What a rollback of the API does not undo:**

* **Any migration the bad release carried.** It stays applied. The older code now runs against a newer schema,
  which is the safe direction (§1). If the *migration* is what is wrong, see §4.
* **Anything the bad release wrote.** A wrongly posted journal is corrected by an append-only reversal through the
  normal screen, never edited or deleted by hand.
* **Environment changes.** Those are in Render's dashboard and are not part of a build.

## 4. A migration that is red, or wrong

* **Red.** Each file runs in one transaction with its tracking row, so a failure leaves nothing behind (except the
  ten baseline files and any file reported `not_atomic`). The failure is **remembered** and keeps the pipeline red
  until it is cleared: fix the file in a new commit, or `--retry-failed` if the cause was the environment, or
  record a hand-applied migration. `docs/deploy-migrations.md` has the three paths and the SQL.
* **Applied and wrong.** **Never edit an applied migration**: production matches on its checksum, so an edit is a
  different file and re-runs. Write a **new** migration that corrects it, derived from the one that last defined
  the thing, found by number (`CLAUDE.md`, Migrations: `CREATE OR REPLACE FUNCTION` replaces the whole body).
* **`*_rollback.sql`.** Some migrations have one beside them. **Nothing applies them**: the runner excludes them
  and they are read by tests (`apps/api/tests/test_migration_numbering.py` and the real-Postgres tests). Running
  one against production is a deliberate hand action, and is as risky as the migration it undoes.
* **Data was damaged.** That is a restore question, and the answer to "is there a backup" is
  `docs/operations/incident-runbook.md` §6, which says nothing has been confirmed.

## 5. Rolling back a site (Cloudflare Pages)

`apps/web` and `apps/marketing` are separate Pages projects and are rolled back **separately**.

1. Cloudflare dashboard, Workers & Pages, the project (`practicesync-ai` for the product), Deployments.
2. Find the last good **Production** deployment, and use its Rollback to this deployment control (from memory).
3. Verify with the `live-redirects` workflow (Actions, Run workflow, leave the URL blank for production): it asks
   the live site about every redirect rule.

**What it does and does not do:**

* **The whole earlier build comes back**, including the `NEXT_PUBLIC_*` values baked into it. Changing a build
  variable needs a **new build**; a rollback cannot do it, and a variable edited since is not part of the old bundle.
* It restores that build's `_redirects` file. The file has a budget of 100 dynamic rules that fails silently
  (`CLAUDE.md`, Deployment; `docs/operations/post-mortems.md` row 9), so after any rollback request a deep link
  under `/clients/<id>/…` and **reload** it.
* **Front end and API are deployed independently**, so a rolled-back site may be talking to a newer API, or a
  newer site to a rolled-back API. The browser's list and object guards (`lib/api/shape.ts`) exist because the
  front end is routinely live before the backend that serves its new fields. If you roll back one side, look at
  the other.

## 6. What was verified, and what was not

* Checked against the repository: the pipeline in §1, the switches in §3, the migration behaviour in §4, and that
  every file named here exists (a test reads this document's paths).
* **Not verified: any Render or Cloudflare step.** Menu names, the effect of Rollback on automatic deploys, and
  whether an environment edit redeploys are from memory.
* **Not verified: that a rollback works end to end.** The table-top in `docs/operations/incident-runbook.md` §10
  is where that is found out.

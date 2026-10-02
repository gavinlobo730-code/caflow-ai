# Incident runbook — what to do when it is broken and you are the one awake

Written 01-10-2026 for ops-29, from what the repository, `render.yaml` and the workflows actually say.

> **THIS HAS NOT BEEN TABLE-TOP TESTED.** Nobody other than its author has followed it, no step has been
> timed, and no simulated bad deploy or simulated lost key has been run against it. §10 is the exercise and
> its record is empty. Treat every step as a draft until §10 has a date in it.

> **Blanks are deliberate.** Who owns Render, Supabase and Cloudflare, who is on call, and which alerts
> exist in a dashboard are facts about people and accounts that the repository cannot see. Each is written
> as `[FILL IN: ...]` rather than guessed. Filling one in is never blocked, and inventing a new one is noticed:
> `apps/api/tests/test_the_runbooks_say_what_has_not_been_done.py` holds the number of blanks to a ceiling that
> can only come down. **No credential, address or phone number belongs in this file**: it is in a public
> repository, and the same test fails on anything shaped like one.

> **Dashboard labels are from memory of each vendor's product.** The environment this was written in refuses
> egress, so no menu name below was checked against Render's, Supabase's or Cloudflare's documentation (the
> same caveat `docs/operations/error-tracking.md` and `docs/operations/database-monitoring.md` carry). If a
> menu has moved, the intent of the step is what matters.

Times in an incident note are **IST**. The sibling documents are `docs/operations/release-and-rollback.md`
(how to undo a change) and `docs/operations/post-mortems.md` (what has gone wrong before and where it is written).

## 1. Who owns what

| thing | what the repository says it is | owner | second person | how to get in |
|---|---|---|---|---|
| the API | Render web service `practicesync-api`, Docker, Singapore (`render.yaml`) | [FILL IN: name] | [FILL IN: name] | [FILL IN: where the login is kept] |
| the database and auth | the Supabase project named in the header of `render.yaml`, region ap-south-1 (Mumbai) | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| the product site | Cloudflare Pages project `practicesync-ai`, served at `caflow-ai.pages.dev`, built from `apps/web` | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| the marketing site | a different Cloudflare Pages project, served at `practicesync.pages.dev`, built from `apps/marketing` | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| the repository and its Actions secrets | GitHub; migrations are applied to production from here | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| error reports | Sentry (backend and browser are separate projects; `docs/operations/error-tracking.md`) | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| mail | Resend (`RESEND_API_KEY`) | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| AI providers | Groq and Google Gemini (`GROQ_API_KEY`, `GEMINI_API_KEY`) | [FILL IN: name] | [FILL IN: name] | [FILL IN] |
| the domain and DNS | not recorded anywhere in the repository | [FILL IN: name] | [FILL IN: name] | [FILL IN] |

| role | person | how to reach them |
|---|---|---|
| on call, first | [FILL IN: name] | [FILL IN: channel] |
| on call, second | [FILL IN: name] | [FILL IN: channel] |
| the owner, who decides about customers and money | [FILL IN: name] | [FILL IN: channel] |
| who tells customers | [FILL IN: name] | [FILL IN: channel] |
| counsel, for a data incident | [FILL IN: none engaged today, per `docs/compliance/06-data-protection-dpdp.md`] | [FILL IN] |

Where the incident note is kept, and the chat or call everyone joins: [FILL IN: one place, agreed in advance].

## 2. Severity

| level | it means | for example | first response (an internal goal, proposed, not promised to any customer) |
|---|---|---|---|
| **SEV1** | the books or a statutory figure may be wrong, or somebody can see what they must not, or nobody can work | a firm reading another firm's data; a screen showing a wrong figure that a return could be prepared from; the API down; sign-in broken for everyone; a secret exposed | 15 minutes, at any hour |
| **SEV2** | a module or a class of user cannot work, or a feature is wrong and nobody has yet been harmed | one module returning 500; AI extraction down; mail not leaving; reports over their budget | 2 hours, in working hours |
| **SEV3** | degraded or cosmetic, with a workaround | a slow report; a mislabelled screen; one failed scheduled job that the catch-up will redo | the next working day |

**A deadline raises a level.** PracticeSync prepares returns and never files them, so an outage by itself
cannot make a client miss a filing; the CA can still file on the portal. What an outage costs is the
preparation, and that costs most on the days the work is due: the 7th (TDS deposit), the 11th (GSTR-1), the
20th (GSTR-3B), the advance-tax dates and 31 July (ITR). `apps/api/services/compliance_engine.py` is the
authority for every date. **Raise any incident by one level when the broken workflow is due that day.**

The response goals are the owner's to ratify. They are an internal on-call target and not a service level:
the public site's "SLA" claim is recorded as unproven (`apps/api/tests/_marketing_claims.py`, id
`sla-and-account-manager`), and nothing here may be quoted to a customer as one.

## 3. The first ten minutes

1. **Write down the time** (IST), who you are, and what you were told. Open the incident note (§1). Guess a
   severity (§2); you can change it. Everything after this goes in the note with its time.
2. **Is the API up?** `curl -sS -m 70 https://practicesync-api.onrender.com/health`.
   Wait the whole 70 seconds before saying it is down: on the free tier a sleeping instance took **56.55 s**
   to wake on 2026-09-06 (`apps/api/scripts/smoke_api.py`, `wake()`), and a slow first answer is not an outage.
   What the answer says:

   | `/health` says | it means | go to |
   |---|---|---|
   | 200, `"status": "ok"`, `"schema": "ok"` | the process is up and its schema check passed. It does **not** touch the database | step 3 |
   | 200, `"schema": "checking"` | the boot-time check has not finished yet; not a fault | wait two minutes, ask again |
   | 503, `"status": "schema_drift"` | the code calls a column that production lacks: a migration is committed and not applied. It re-checks every two minutes and clears by itself once the migration lands | §4, first row |
   | 200 with names in `schema_objects.missing_tables` or `missing_functions` | the code calls a table or function production lacks. **Reported, not yet a 503** | §4, first row |
   | `"error_reporting": "off"` | no Sentry DSN is set: swallowed posting failures reach the log stream only | note it; fix after |
   | no answer after 70 s | the service is down or not building | `docs/operations/release-and-rollback.md`, and Render's Events page |

3. **Does the database answer, and does it accept our key?** `curl -sS -m 10 https://practicesync-api.onrender.com/ready`.
   It makes one bounded request with the service-role key and says which of three things is wrong
   (`apps/api/core/readiness.py`):

   | `/ready` says | it means | do |
   |---|---|---|
   | 200 | database and key both fine | step 4 |
   | 503 `config` | `SUPABASE_URL` or the key is not set in this process. Nothing was sent | compare Render's environment with `render.yaml` (§4, fourth row) |
   | 503 `database` | the host did not answer in time, or PostgREST or Postgres is failing, or the service role cannot read the tenant table | Supabase's status and dashboard. **Restarting the API helps nobody** |
   | 503 `auth` | the gateway answered 401: the service-role key was rotated or mistyped. The database is fine | set the right key in Render (§5) |

4. **Is it the front end?** Open `https://caflow-ai.pages.dev`. A blank page or a crash is the browser
   bundle; a page that loads and then fails every call is the API (steps 2 and 3). If a **reload** of a deep
   link under `/clients/<id>/…` returns a 404 while clicking around works, the redirect file lost rules:
   `docs/operations/post-mortems.md` row 9 and the `live-redirects` workflow.
5. **What changed?** Almost every incident is the last change. Look, in this order, and write each answer down:
   Render's Events page (the last deploy and its time); the last merge to `main`; the last run of the
   `apply pending migrations — production` job in `.github/workflows/backend-ci.yml`, and whether it is red;
   the last edit to Render's environment variables; Render's, Supabase's and Cloudflare's own status pages.
6. **Is the data being written wrongly?** Sentry: any new issue tagged `posting_operation` means a financial
   posting failed (`docs/operations/error-tracking.md` §5). That is **SEV1**. Post the missing journal through
   the normal screen; **never write a journal row by hand**.
7. **Roll back or fix forward?** If it began right after a deploy and the previous deploy was healthy, **roll back
   first and diagnose after** (`docs/operations/release-and-rollback.md`). A rollback does not undo a migration,
   and says so there.
8. **Tell people** (§8) if it is SEV1, or SEV2 and over thirty minutes old.
9. **Write down what you did and when**, including the things that did not work.

## 4. Symptom to first action

Each row is a symptom someone has already met, and where the evidence is.

| symptom | likely cause | first action | evidence |
|---|---|---|---|
| `/health` 503 `schema_drift`, or names under `schema_objects` | a deploy reached production before its migration, or the migration job is red | open the `apply pending migrations — production` job. Green and recent: wait, the check re-reads every two minutes. Red: the failure is **remembered** and the run exits non-zero; read the file named in the annotation | `docs/deploy-migrations.md` (how a failure is remembered, cleared and retried), `apps/api/core/schema_guard.py` |
| a migration is red | the file failed; each runs in one transaction, so nothing partial is left (unless it is one of the ten baseline files or is marked not atomic) | fix the file in a **new commit**, or `--retry-failed` if the cause was the environment. Never edit an applied migration | `docs/deploy-migrations.md` |
| every request 401 after a deploy | the token's issuer does not match what the API derives. It fails **closed** by design | set `SUPABASE_JWT_ISSUER` (only after decoding a live token's `iss`), or roll back | `render.yaml`, the `SUPABASE_JWT_ISSUER` comment; `apps/api/core/auth.py` |
| `/ready` 503 `config` after the service was recreated, rebuilt or its environment was edited | variables marked `sync: false` in `render.yaml` hold their values in the dashboard only, and a recreated service has none. On 2026-08-15 `USE_USER_JWT` and `REQUIRE_MFA` were left unset after the move to Singapore, and the product went down | set every variable `render.yaml` lists, in the dashboard. `GET /api/security/posture` (a Partner, behind MFA) says what the running process resolved | `render.yaml` ("Security flags"), `apps/api/core/security_posture.py`, `apps/api/core/security_config.py` |
| `/ready` 503 `database` | Supabase is degraded, or a table lacks a grant for `service_role` | Supabase's status page and dashboard first. Do not restart | `apps/api/core/readiness.py`; `render.yaml` on the 57 tables never granted to `service_role` |
| reports slow, or time out at the browser's 45 s | cold start, the database, or one endpoint regressed | the smoke run's summary page (the p95 table, `docs/operations/service-levels.md`) shows which endpoint and since when. Cash flow is the known slow one | `.github/workflows/smoke.yml`, `render.yaml` header |
| an AI feature fails with a `model_not_found` style sentence | the provider retired the model. Groq retired `llama-3.3-70b-versatile` on 2026-09-29 | set `GROQ_TEXT_MODEL` in Render (it needs no deploy), or `GROQ_TEXT_MODEL_FALLBACK` for a second route. A revoked **key** stops, a retired model moves to the next | `apps/api/domain/ai/groq_text.py`, `apps/api/tests/test_the_ai_gateway_retries_falls_back_and_says_why.py` |
| reminders and recurring invoices did not appear | the in-process scheduler was not running at 06:00 IST (a sleeping free-tier instance, or `ENABLE_SCHEDULER` unset) | `ENABLE_SCHEDULER` in Render; the next start runs a catch-up for what was missed | `.github/workflows/wake-before-scheduler.yml`, `apps/api/jobs/scheduler.py` |
| no mail is leaving | `PRACTICE_MAIL_ENABLED` is **off unless explicitly on**; that is not a fault | confirm the switch before looking anywhere else; then `RESEND_API_KEY` | `render.yaml` ("The practice's own mail") |
| a 404 on reload of `/clients/<id>/…` only | Cloudflare dropped redirect rules past its 100-dynamic-rule cap, silently | run the `live-redirects` workflow by hand; roll back the Pages release | `apps/web/scripts/generate-redirects.js`, `docs/operations/post-mortems.md` row 9 |
| sign-in or the authenticator prompt misbehaves for everyone | Supabase Auth, or `REQUIRE_MFA` | Supabase's status; `GET /api/security/posture`. `REQUIRE_MFA=false` is the documented rollback and logs at ERROR at boot | `render.yaml`, `apps/api/core/security_posture.py` |
| a figure on a statutory screen looks wrong | not an outage, and possibly the worst kind | **SEV1 if a return could be prepared from it.** Tell the CAs not to use that screen, keep the evidence, find the rule in the code (`CLAUDE.md` names the authority module for each) and fix it as a defect with a test | `CLAUDE.md` |
| someone can see another firm's or client's data | a tenancy failure | §5, "A data exposure" | `CLAUDE.md`, Tenancy and access |

## 5. A secret was exposed, or data was

### A data exposure (a person can see what they must not)

1. **SEV1.** Write the time you became aware (IST). Under the Digital Personal Data Protection Rules the
   duty to notify runs from awareness, not from the end of the investigation
   (`docs/compliance/06-data-protection-dpdp.md`, Rule 7; that file records the Fiduciary duties as
   commencing 13 May 2027 and every reading in it as secondary-sourced). **Whether and whom to notify is a
   decision for the owner and counsel, not for whoever is on call**: [FILL IN: counsel].
2. **Contain before you understand.** In the product: suspend the member (`suspend_user`) or end their
   sessions (`force_logout`); migration 468 makes the database itself refuse a suspended or signed-out member,
   so this is not only an API check. A firm can be suspended by the platform administrator. Nothing here
   rotates a key: that is the next section.
3. **Keep the evidence.** Do not delete rows, do not "fix" the data yet. Export the relevant Supabase API
   logs for the window and the `audit_log` rows for the people involved (`GET /api/audit?actor_id=` takes the
   Supabase **auth** id, not the internal one).
4. Find the cause, fix it with a test, and write the entry in `docs/operations/post-mortems.md`.

### Rotating a secret

What lives where, as the repository records it. **Never write a value into this file, an issue or a commit.**

| secret | where it lives | what reads it | if it is exposed |
|---|---|---|---|
| **Supabase service-role key** | Render environment, `SUPABASE_SERVICE_ROLE_KEY` | the API's privileged client, background jobs and the `/ready` probe | **SEV1.** It bypasses row-level security: every firm's data, read and write |
| Supabase **database connection string** (the password) | GitHub Actions secret `SUPABASE_DB_URL` | the migration job | **SEV1.** Direct SQL with DDL rights |
| Supabase **anon key** | Render `SUPABASE_ANON_KEY`; Cloudflare Pages build variable `NEXT_PUBLIC_SUPABASE_ANON_KEY` (baked into the bundle at build time); GitHub secrets of the same names (the front-end build and the smoke run) | the browser, the API's per-user client | public by design, so it is not itself a breach. Rotate it only when the project's keys are being re-issued |
| Supabase **JWT signing keys** | Supabase | the API verifies logins through the project's JWKS (`apps/api/core/auth.py`) | **SEV1** if a private key leaked. Rotating signs every user out |
| Groq and Gemini keys | Render, `GROQ_API_KEY`, `GEMINI_API_KEY` | `apps/api/domain/ai/groq_text.py`, `apps/api/domain/ai/gemini_vision.py` | spend and a quota; rotate in the provider's console, then Render. AI features stop until Render has the new one |
| `RESEND_API_KEY` | Render | the mail door | someone sending as the product; rotate in Resend, then Render |
| Sentry DSN | Render `SENTRY_DSN`; build variable `NEXT_PUBLIC_SENTRY_DSN` | the SDK | a send-only identifier, not a secret. Rotate only if events are being flooded |
| the smoke account's password | GitHub secret `SMOKE_PASSWORD`, and the Supabase user itself | `.github/workflows/smoke.yml` | a real user's login. Change it in Supabase and in the secret |
| payment-provider secrets (`RAZORPAY_*`) | not declared in `render.yaml` on purpose (`apps/api/tests/test_render_manifest_matches_code.py`, its exemption map) | the payment service | [FILL IN: where they are held] |

**The service-role key, step by step** (the Supabase steps are from memory; see the note at the top):

1. Declare SEV1. Write down **what** was exposed (the key alone? a whole `.env` file with others?) and **since
   when**. Anything else in the same place is exposed too, and gets this section as well.
2. Decide the order. **Replace first** is minutes of exposure and no outage, if the project allows two
   secret keys at once. **Revoke first** ends the exposure at once and takes the API down until step 4; for a key
   that bypasses row-level security that is a defensible choice, and it is the owner's call. Which key system
   this project uses (the older `service_role` JWT, tied to the JWT secret, or the newer secret keys that can be
   created and revoked one by one): [FILL IN]. **Rotating the older kind means rotating the JWT secret, which
   changes the anon key too and signs every user out.**
3. Create the replacement in Supabase (Project Settings, API keys).
4. Put it in Render (`SUPABASE_SERVICE_ROLE_KEY`, saved in the dashboard). Saving an environment variable
   redeploys the service.
5. **Verify**: `curl -sS https://practicesync-api.onrender.com/ready` answers 200. A 503 `auth` means the
   key in Render is not the new one. Then `/health`, one sign-in, one report, and a manual run of the **API smoke**
   workflow (Actions, API smoke, Run workflow).
6. Revoke the old key (if you did not in step 2). Confirm `/ready` is still 200 afterwards.
7. If the JWT secret changed: update `SUPABASE_ANON_KEY` in Render, `NEXT_PUBLIC_SUPABASE_ANON_KEY` in the
   Cloudflare Pages project **and redeploy it** (the old key is baked into the build, so a variable change alone
   changes nothing live), and the two GitHub secrets of that name. Everyone signs in again.
8. **What did it do while it was exposed?** Supabase's API logs for the window: requests with that key that
   did not come from Render. In `audit_log`, rows with no actor are a lead and not proof: the trigger records
   `auth.uid()`, which is empty under the service key, and the scheduler and webhooks write such rows legitimately
   (an inference from `CLAUDE.md`'s account of migration 111; not tested).
9. **Where did it leak?** Remove it from there. If it was committed, `.github/workflows/secret-scan.yml` (gitleaks)
   should have said so; treat anything ever in the git history as public, whatever you do to the file now.
10. Write it up (`docs/operations/post-mortems.md`).

Known and not fixed: live engagement sign links are stored in the clear (`CLAUDE.md`, security_privacy-24), so
**a read of the database also exposes every live signing link**. After a database read, decide with the owner
whether to expire the open engagement letters.

## 6. Backups and restoring

**The repository records no backup configuration and no restore has ever been rehearsed.** What Supabase keeps
depends on the plan, and the plan is not written anywhere in this repository. Do not assume a backup exists
until a person has opened the dashboard and filled this in:

| fact | answer |
|---|---|
| the Supabase plan | [FILL IN] |
| are daily backups on, and how many days are kept | [FILL IN] |
| is point-in-time recovery on, and to what granularity | [FILL IN] |
| who may start a restore | [FILL IN] |
| how long a restore takes at the current size | [FILL IN: unknown until one has been done] |
| the date of the last restore into a scratch project, and who did it | **never**, until someone writes a date |

If a restore is needed, these follow from restoring to *any* earlier moment, and are worth reading before choosing it:

* **Everything written after that moment is gone**, including documents already sent to customers. A tax
  invoice number issued after the restore point exists on a PDF in someone's inbox and not in the database, and the
  next invoice will reuse it. CGST Rule 46(b) wants the series consecutive and unique; reconcile the issued
  numbers against what customers hold before anyone issues another.
* **Filing records go too.** A return marked filed after the restore point loses its row in `filings`, which is
  what locks the period. Re-record it before anyone posts into that period.
* **The migration runner's memory moves with the database.** Restoring to before migration N means the next push
  to `main` applies N again (`docs/deploy-migrations.md`). That is correct, and is also a surprise at 2 am.
* A posted journal is immutable by design. A restore is the one thing that changes that, which is why it is the
  last resort and the owner's decision.

Restoring into a **new** project and comparing is safer than restoring in place, and costs a change of
`SUPABASE_URL` and every key if you cut over to it (§5).

## 7. Alerts: what exists, and what nobody has set up

| signal | state, as far as the repository can see | who gets it |
|---|---|---|
| backend errors to Sentry | wired; `/health` says `error_reporting` on or off. The alert **rules** are to be created by a person (`docs/operations/error-tracking.md` §4) | [FILL IN: created? by whom? who is paged] |
| browser errors to Sentry | wired in code; needs the `NEXT_PUBLIC_SENTRY_DSN` build variable on the Pages project | [FILL IN] |
| an external monitor on `/ready` | the endpoint exists for exactly this; **no monitor is attached** that the repository can see | [FILL IN: none today?] |
| the API smoke, every six hours | `.github/workflows/smoke.yml`; it **skips green** without its secrets, so a green run proves nothing until they are set | whoever GitHub emails about a failed workflow: [FILL IN] |
| the nightly screen walk | `.github/workflows/smoke-walk.yml`; not a required check | [FILL IN] |
| the live redirect check | `.github/workflows/live-redirects.yml`, every six hours | [FILL IN] |
| the scheduler wake | `.github/workflows/wake-before-scheduler.yml` | nobody: it only pings |
| a failed Render deploy | Render can notify; **whether it is set is not recorded** | [FILL IN] |
| a failed Cloudflare Pages build | Cloudflare can notify; not recorded | [FILL IN] |
| Supabase advisors, usage and disk | the monthly routine in `docs/operations/database-monitoring.md`; the alerts in its §5 are **not set** | [FILL IN] |
| dependency advisories, leaked secrets, the image build | `.github/workflows/dependency-audit.yml`, `.github/workflows/secret-scan.yml`, `.github/workflows/docker-image.yml` | the owner of the repository |

**There is no pager.** Nothing in this table wakes a person at night. Choosing the channel and who is on it is
the first thing to settle after reading §1.

## 8. Telling customers

A CA's clients' books live here, and a CA's deadline does not move for an incident. Say less, sooner, and only
what you know.

* **Who and where.** [FILL IN: who sends it; the channel customers actually read].
* **Say**: what is not working, since what time (IST), what still works, what to do meanwhile, and when the
  next update is. **Do not say** "no data was lost" or "no one's data was accessed" until it has been checked,
  and do not name a cause you have not confirmed.
* **Tell the CAs the one fact that comforts and is true**: PracticeSync prepares and never files, so they can
  still file on the portal from a return they already prepared.

> **Starting.** We are investigating a problem with [what]. It began at about [time] IST. [What still works.]
> If a deadline falls today, [what to do meanwhile]. Next update by [time] IST.

> **Update.** [What we now know, in one line.] [What is being done.] Next update by [time] IST.

> **Resolved.** [What] was not working from [time] to [time] IST. It is working again. [What, if anything,
> they should check or re-enter.] A written account will follow by [date].

## 9. After it

1. Write the entry in `docs/operations/post-mortems.md` the same week, while it is still sharp.
2. **Add the guard in the same change that fixes it.** This repository's habit is a test that states the rule,
   not one that pins today's spelling of it; the post-mortem names that test.
3. If a step in this runbook was missing, wrong or slow, fix this file in that change. A runbook corrected only
   in someone's memory is the one that fails the next person.

## 10. The table-top exercise, and its record

Somebody who did **not** write this file follows it with a stopwatch, on a **staging** project and never on
production. Two scenarios:

**A. A bad deploy.** On a staging service, deploy a commit that makes `/health` return 500. Starting from
"it is broken", follow §3 and `docs/operations/release-and-rollback.md` until the previous deploy is serving
and `/health` and `/ready` answer 200. Time each step.

**B. A lost or exposed service-role key.** On a staging project, treat the key as exposed and follow §5
to a healthy `/ready` with the old key revoked. Time each step.

For each scenario write down every place the reader had to guess, every blank in §1 that was needed and was
still empty, and every step that did not match what the dashboard showed.

| scenario | date | who | total time | steps that were wrong or missing | what was changed |
|---|---|---|---|---|---|
| A. bad deploy | **not run** | | | | |
| B. exposed key | **not run** | | | | |

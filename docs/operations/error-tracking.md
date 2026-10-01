# Error tracking — what is wired, what a person has to do, and how to know it works

Written 30-09-2026 for ops-09 (browser) and ops-10 (backend). **Nothing here has reached a Sentry
project yet**: both halves need a DSN, and a DSN comes from an account the repository cannot see. What
the repository can do is done and tested; what is left is a short list of steps for the owner, in
order, below.

Sentry's interface is written here from memory of its product. Egress is refused in the environment this
was written in, so no label below was checked against Sentry's current documentation — if a menu has
moved, the intent of the step is what matters.

## 1. What is wired

| | browser (`apps/web`) | backend (`apps/api`) |
|---|---|---|
| starts from | `lib/monitoring/index.ts`, mounted by `app/layout.tsx` | `core/observability.init_error_reporting`, called by `main.py` |
| switched on by | `NEXT_PUBLIC_SENTRY_DSN`, a **build-time** variable (a static export has no runtime environment) | `SENTRY_DSN` in Render (`render.yaml`: `sync: false`) |
| with no DSN | nothing starts, nothing is fetched | nothing starts; the boot log says so at WARNING in production |
| reports | uncaught errors, unhandled rejections and — the common case — every error an **error boundary** caught | every swallowed financial-posting failure (`capture_posting_failure`, 45 call sites) and soft failure (`capture_soft_failure`, 63), and every unhandled exception |
| tracing | none | none (`SENTRY_TRACES_SAMPLE_RATE`, default 0) |
| session replay | none, anywhere | not applicable |
| confirm it is on | events appear in the project (§3 step 5) — a static export has no server to ask | `curl https://practicesync-api.onrender.com/health` answers `"error_reporting": "on"` |

The 108 call sites are a count on 30-09-2026 of calls to the two capture functions outside tests; the
finding that asked for this said 151, which matches a broader search that also counts imports and
definitions.

**Why a browser boundary needs its own call.** A React error boundary catches the throw, so the SDK's
global handler never sees it. Wiring the SDK alone would have reported the rare case and missed the
common one. `components/ModuleErrorBoundary.tsx` (which all 65 `error.tsx` files render) and
`app/global-error.tsx` call `reportClientError`.

## 2. Two defects found on the way, both fixed

### 2a. The alert rules could not have matched (backend)

The rule the finding asked for — *any new issue with tag `posting_operation` pages a person* — matches
nothing against the code as it was. `_capture` logged at ERROR with the exception attached and **then**
reported it. Sentry's default logging integration turns an ERROR record into an event, so the log
record's event went first, carrying no tags and no fingerprint, and the explicit capture that has them
was dropped as a duplicate of the same exception (Sentry's `Dedupe` integration, on by default — with it
disabled in a fresh process both events arrive). Measured with the real SDK on 30-09-2026: one event,
`tags: None`, `fingerprint: None`. Every posting failure would have grouped by stack trace, and no rule
on `posting_operation`, `soft_operation`, `firm_id` or `source_id` would ever have fired.

The earlier tests could not see it: they replace `sentry_sdk.capture_exception` and `new_scope` with
fakes. The fix is one line — `ignore_logger("caflow.observability")` — and the line stays in Render's
log stream, where it is the only trace when Sentry is off.
`tests/test_the_posting_failure_alert_has_its_tags.py` starts the real client with a capturing transport
and reads the event that would have left.

### 2b. Request bodies and local variables were being sent (backend)

`main.py` said *"No request bodies, headers or user records"*. Measured with the real SDK, with
`send_default_pii=False` and tracing off exactly as it was, against an endpoint that raised: the
request's **JSON body** (`{"pan": "ABCDE1234F", "amount_paise": 12500000}`) and **every stack frame's
local variables** were attached to the event. Headers were already filtered (`Authorization` and
`Cookie` arrive as `[Filtered]`). `send_default_pii` does not govern either.

`init_error_reporting` sets `max_request_body_size="never"` and `include_local_variables=False`. The
cost is real and is worth stating: a Sentry issue no longer shows what the failing function held, so a
developer reproduces from the tags (`firm_id`, `source_type`, `source_id`) and the stack. That is the
trade the original comment already intended.

## 3. Browser — steps for the owner

1. **Create a Sentry project** for the browser (platform: *Next.js* or *JavaScript*). Copy its DSN.
   A DSN is a public identifier — it lets a browser *send* events, not read them — which is why it may
   sit in a build variable or in `apps/web/wrangler.toml` beside the Supabase anon key.
2. **Set `NEXT_PUBLIC_SENTRY_DSN`** as a build variable on the Cloudflare Pages project
   `practicesync-ai`, for **Production and Preview** (Settings → Environment variables). Do not set
   `NEXT_PUBLIC_SENTRY_RELEASE` or `NEXT_PUBLIC_SENTRY_ENVIRONMENT`: `next.config.mjs` derives them from
   `CF_PAGES_COMMIT_SHA` and `CF_PAGES_BRANCH`, which Cloudflare's build injects — `main` is
   `production` (Cloudflare's production branch is assumed to be `main`), anything else is `preview`, so a preview's crashes do not page anyone for production.
3. **Redeploy.** The variable is inlined at build time; an existing deployment does not see it.
4. **In the Sentry project** (Settings → Security & Privacy): turn on *Prevent Storing of IP Addresses*
   and leave server-side *Data Scrubbing* on. The browser already sends nothing it should not, and this
   is the second layer for the one thing the SDK cannot scrub — the IP the request arrived from.
5. **Verify on a preview build**, not on production: open the preview URL and, in the browser console,
   run `setTimeout(() => { throw new Error("verification " + "ABCDE1234F") }, 0)`. In Sentry the issue
   must show: release = the commit SHA, environment = `preview`, tag `route`, the message as
   `verification [id]`, no user, and a request carrying the URL **without** its query or fragment.
   Then sign in on the preview and open a screen that renders an error boundary, if you can cause one
   in a test client; its issue carries the extra tag `boundary` with the module name.
6. **Alert rule:** *a new issue in environment `production`* → email the person who owns the front end.
   Browser noise is larger than backend noise (extensions, flaky networks); start with *new issue* and
   a weekly digest, not a page.

### What was run here instead of steps 1 to 5

On 30-09-2026 the static export was built twice with `NEXT_PUBLIC_SENTRY_DSN` pointing at a local
stand-in for the ingest host, and loaded in Chromium with a deliberate crash on a public route:

- **With a DSN:** an uncaught error, a render crash caught by `app/sign/error.tsx`, and eight repeats of
  one error arrived as five events. Release `e2ebuild0001abcdef` (the commit variable), environment
  `preview` (a branch that was not `main`), `tags.route`, and `tags.boundary: "Sign"` on the
  boundary-caught one. The address bar held `?t=secretbearertoken123&pan=ABCDE1234F#access_token=eyJ…`
  and the message held a PAN, an amount and an account number: none of it was in anything sent, the
  request object held only the scrubbed URL, there was no `user` and no `extra`, and the console line
  the page logged was not recorded as a breadcrumb. The eight repeats were held to three by the budget.
- **With no DSN:** the same crash showed the boundary and produced zero requests to the ingest host.

That proves the wiring, the scrubbing and the budget. It does not prove that a Sentry *project* accepts
the events or that an alert rule fires: that is steps 1 to 6.

### What still leaves the browser

A report carries the error type, its stack, the route shape (`/clients/:id/payroll/` in a tag; the URL
itself keeps its path and so a client id), the release and the environment. **A free-text name is the
one thing it cannot remove** from an error message: messages are written by programmers and
`scrub.ts` redacts by shape (a PAN, an account number, an amount, an email, a token), not by meaning.
`ModuleErrorBoundary` already refuses to print a message on screen for the same reason.

There is no session replay, deliberately. Turning it on means recording screens that hold PAN, payroll
and bank figures; it is the owner's decision, and it needs the routes that must be blocked named
first (payroll, bank, the client portal). `scripts/the-browser-reports-crashes-without-recording-screens.test.ts`
fails if a replay integration appears.

## 4. Backend — steps for the owner

1. **Confirm it is on.** After this change is deployed: `curl https://practicesync-api.onrender.com/health`.
   `"error_reporting": "on"` means a Sentry client with a DSN is live. `"off"` means `SENTRY_DSN` is unset
   in Render's dashboard, and every swallowed posting failure is reaching the log stream only. The boot
   log says the same at WARNING.
2. **Send a test event.** From a shell that has the DSN (the dashboard value is in Render; do not put it
   on a command line):

   ```
   cd apps/api
   SENTRY_DSN=... python3 scripts/sentry_verify.py                        # dry run: names the project
   SENTRY_DSN=... python3 scripts/sentry_verify.py --send --environment staging
   ```

   It goes through the same two functions every call site uses. In Sentry the issue must carry
   `posting_operation = sentry_verification`, `firm_id`, `source_type`, `source_id`; if it arrives
   without those tags no rule can match. Run it with `--environment production` **only** to test the page
   itself — that event is meant to trip the rule.
3. **Create the rules** (Alerts → Create Alert → Issues), scoped to environment `production`:

   | rule | when | filter | then |
   |---|---|---|---|
   | posting failure | a new issue is created, or an issue regresses | tag `posting_operation` is set | notify the person on call immediately, on the channel you agree |
   | soft failure, rising | an issue is seen more than 10 times in an hour | tag `soft_operation` is set | email |
   | soft failure, new | a new issue is created | tag `soft_operation` is set | email (digest is fine) |

   A posting failure loses money in the books and a soft failure loses the truth of a screen; they need
   different responses, which is why they are separate tags and separate rules.
4. **Quota.** The free tier's error allowance is small, and an exhausted quota makes Sentry *drop*
   events — including the ones this exists for (`main.py` and `init_error_reporting` say the same of
   tracing). In the organisation's Usage & Billing settings, turn on usage notifications at the level
   Sentry offers, and keep *spike protection* on. The browser's per-session budget
   (`lib/monitoring/scrub.ts`, 20 events and 3 of any one error) is what stops one broken page spending
   the month.
5. **A release tag is not sent today** from the backend: the SDK reads `SENTRY_RELEASE` and a few CI
   variables, and Render's `RENDER_GIT_COMMIT` is not among them. Adding it is a one-line change and an
   entry in the render manifest test; it was left alone as outside this finding.

## 5. What to do when an alert fires

- **Posting failure:** the tags name the firm, the client, the document type and its id. Open that
  document; the journal it should have posted is missing or wrong. Post it through the normal path;
  never write a journal row by hand.
- **Soft failure:** a screen or a score is silently wrong for a firm. Find the operation name in
  `apps/api` (`grep -rn "<operation>"`); the `except` around it is the swallowed error.
- **Browser:** the `route` tag names the screen and the `boundary` tag the module that caught it.

# Design record: Frontend rules: payload shapes, the browser's second data path, money input, loading and recurring screens

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Code rules — always follow

**A PAYLOAD IS NOT A LIST UNTIL SOMETHING HAS CHECKED, AND THE STATE TYPE HIDES
IT.** `lib/api/shape.ts` (`arrayOrEmpty`, `objectOrNull`) was written on
16-09-2026 after thirteen screens crashed the first time the smoke walk could
render them, and it says why this is not a test-harness problem: the GST
workspace router answers a refusal as HTTP 200, `lib/api` aborts at 45 seconds
and never retries, and Render's free tier cold-starts. A rolling deploy is a
fourth — the frontend is live before the backend that serves the new field.
**Two components written AFTER that sweep reintroduced it and the walk of
24-09-2026 crashed on both**: `ExpiringEwayBills` guarded `!report` and then
read `report.bills.length` (`[]` and `{}` are both truthy, so the guard passes
them), and `FxRatesPanel` checked the ENVELOPE — `if (t.success && t.data)` —
and then set state from `t.data.rate_types`, so `types` became undefined and
the next line did `types.find(...)`. **`useState<T[]>([])` satisfies TypeScript
on either**, however absent the key is at runtime, which is why no compiler and
no reviewer caught it. A sweep found **28** more live sites. The rule is
`apps/web/scripts/a-payload-field-is-not-a-list-until-it-is-checked.test.ts`:
array state may not be REPLACED from a payload without `arrayOrEmpty`,
`objectOrNull`, a `?? []` fallback, or a function taking `unknown` — the last
being a real narrowing boundary, allowlisted by name and asserted to actually
take `unknown`. **The functional-insert variant is counted APART and not
failed**: `setRows(prev => [json.data, ...prev])` puts undefined in as an
ELEMENT, so a row renders blank and the screen lives — a different defect with
a different fix, and folding it in would make the count bigger and the claim
weaker.
⚠️ **AND THE GUARD COVERS THE ARRAY HALF ONLY, WHICH IS NOT THE HALF THAT
CRASHED.** It matches `useState<…>([])` and says in its own comment that an
object-typed `useState<X | null>(null)` "is a separate shape whose guard is
`objectOrNull` at the read" — and no guard for that shape exists. **Both
components named above are that shape**: `ExpiringEwayBills` held a `report`
object and read `report.bills.length`, `FxRatesPanel` held one and read
`types.find`. Measured 24-09-2026: **66 object-state
variables were set from a payload and then read with a nested
`.map`/`.length`/`.filter` with nothing narrowing the setter. All 66 are
fixed**, and
`scripts/an-object-payload-is-not-its-fields-until-it-is-checked.test.ts`
holds the line — its list is EMPTY, so it is now simply the rule. The two
halves travel together in **`objectWithLists`**, which takes the payload and
the names of the fields that are lists, because doing them separately 66 times
is 66 chances to do one and not the other. It is not a validator: it does not
check a field is present or that its elements are right, only whether a `.map`
on it could throw — a FROZEN LIST rather than a count, because a budget is one
number somebody raises and a named list can only shrink, asserted as an
EQUALITY so a fix that leaves its entry behind fails as loudly as a new
offender. ⚠️ **The first sweep found 62 and was wrong, and its own negative
control is what said so**: it matched `x.field.map` and not `x?.field.map`,
and the optional-chained form is the DANGEROUS one — `?.` guards `x` being
null and says nothing about `field` being absent, so it throws on `{}` exactly
as the plain form does. A probe adding one passed against the narrow regex.
⚠️ **Three files needed hands and TSC is why**: `payroll/page.tsx`,
`EmployeeDrawer.tsx` and `StatutoryHandoff.tsx` each declare the same state
name (`data`, `result`) in several components in one file, so a sweep keyed on
(file, state) pools fields belonging to different variables — every one of
those was a type error rather than a silent wrong render, which is the
argument for typing a payload at all. The worked example is
`components/inventory/ReorderPanel.tsx` — fixed because the
`fetch_all` repair above made its success path reachable **for the first time
ever**, so a latent crash became a live one in the same commit.
**`objectOrNull` IS NECESSARY AND NOT SUFFICIENT**, which is the part to read
before sweeping: it answers whether `data` is the right KIND of thing, so it
converts `[]` and a scalar to `null` — and `{}` passes straight through it, so
`report.groups.map` still throws. A nested list needs `arrayOrEmpty` at the
READ as well as `objectOrNull` at the setter. And `if (!report ||
report.items_considered === 0)` does not help: `undefined === 0` is false, so a
payload missing the field walks past the guard into the map.

## From CLAUDE.md section: The frontend's second data path

- **A THIRD path existed and it was not a database at all: `localStorage`.**
  Three screens kept the CA's own work in the browser (ACC-06). All three are
  on tables now, and the three turned out to be three different jobs — which
  is the lesson worth keeping, because the finding read as one.
  `/accounting/budget` went onto `account_budgets` (migration 376);
  `/accounting/recurring` onto `recurring_journal_templates` (377), the only
  genuine build of the three; and `/accounting/retainer` onto
  **`billing_schedules`, which was already built** —
  `arrangement IN ('retainer','one_time','package')` since migration 073,
  `billing_service.generate_for_schedule` producing a DRAFT through the sales
  engine, and three methods in `lib/api` with no callers. That inverts the
  argument `BrowserOnlyNotice` used to make in its own docstring — that these
  screens "have no alternative" — and makes it exactly the pattern this file
  warns about at `/gst/reconciliation`: a banner disowning a rival
  implementation. **Before writing such a notice onto a fourth screen, grep
  the backend for what it duplicates.**
  Two classes of defect found on the way are worth knowing, because neither
  was in the finding and both are the kind that hide behind "it's only stored
  locally". The retainer screen RENDERED a document headed TAX INVOICE under
  the firm's own GSTIN, numbered from a browser-local counter (two devices
  collide, so Rule 46(b)'s "unique for a financial year" cannot hold) and
  taxed at a hardcoded CGST 9% + SGST 9% — the wrong tax for every
  inter-state client — with a Print button. And the recurring screen's "Post
  Now" wrote `status: "posted"` STRAIGHT TO THE LEDGER, dated TODAY rather
  than the occurrence, so a rent journal due on the 1st and remembered on the
  7th landed on the 7th.
  **`BrowserOnlyNotice` is deleted**: with no screens left it would only invite
  a fourth, and `apps/web/scripts/a-browser-only-screen-says-so.test.ts`
  inverts to state the durable rule — no page under `app/` may store the
  user's WORK in the browser (a remembered tab or an unsent draft is a
  per-viewer convenience and is allowlisted with its reason), and none of the
  three may regress.

- **A RECURRING ANYTHING SHARES ONE CADENCE ENGINE**, `domain/recurrence.py`.
  `recurring_invoice_service` owned the occurrence arithmetic and it was
  right, so recurring journals could have copied it — and two cadence engines
  drifting means one feature posts in a month the other skips. It was MOVED;
  the invoice service imports and re-exports the names so its callers are
  untouched. The rule inside it that is easy to get wrong: **a month end clamps
  against the ORIGINAL day, not the previous occurrence.** A monthly template
  starting 31 January runs 31 Jan, 28 Feb, **31 Mar** — clamping each step
  against its predecessor walks the whole series permanently back to the 28th
  after one February.
  **A generated journal is a DRAFT and is stamped `source_type = 'manual'`**,
  which looks wrong and is not: `manual_journal_service._is_manual` is
  `(source_type or "") == "manual"` and migrations 275/338 refuse the edit and
  discard paths on anything else, so any other value hands the CA a draft they
  are invited to review and forbidden to amend. The trace lives on
  `journal_entries.recurring_template_id` (migration 377), which no guard
  reads. A failed occurrence is RECORDED in `recurring_journal_runs` and the
  template does NOT advance — a template that cannot post needs a CA, and
  advancing past a failure would skip the month silently.
  **There are THREE of these now** — sales invoices (107), journals (377) and
  PURCHASE BILLS (379, PUR-26) — and the third exists because the purchase side
  is where a missed month costs more than an expense: most of the §194 series
  charges on the YEAR'S AGGREGATE, so rent (§194I) or a retainer (§194J) that
  nobody entered changes what the NEXT bill should withhold, and with it the
  Rule 30(2) deposit and the quarterly statement.
  `services/recurring_purchase_bill_service.py` generates a **DRAFT** bill
  through the ordinary bill engine and never RECEIVES one — receiving is what
  posts Dr Expense / Dr GST Input / Cr Trade Payables, withholds the TDS and
  claims the credit. **`bill_no` is left blank on purpose**: it is the VENDOR'S
  own document number, a fact about the landlord's books, and half the key
  `domain/gst/itc_matching` uses — inventing one puts a number the supplier
  never issued onto a document the 2B reconciliation reads. `our_reference` is
  ours and is stamped. The per-line facts that decide money —
  `itc_eligible` (CGST §17(5)), `expense_account_id`, `tds_applicable` — travel
  on the TEMPLATE, because defaulting them at generation would re-decide every
  month what the CA decided once; and a line with no catalogue item is refused
  at SAVE time, since `PurchaseBillLineIn` has required one since migration 206
  and the alternative is failing inside an unattended 06:00 IST job.

## From CLAUDE.md section: CI

- **A LOADING REGION SAYS WHEN THE SERVER IS SLOW, A SIGNED-IN TAB KEEPS IT AWAKE, AND THE WALK SCANS WHAT IT RENDERS FOR ACCESSIBILITY** (frontend_ux-05, -03, -01, 02-10-2026). The API sleeps on a free tier and a cold start was measured at 56.55 s (`wake-before-scheduler.yml` records it; `render.yaml` does NOT, which the audit had said); the only words a CA ever got came AFTER a failure, so a 5-30 s skeleton had no reason, no estimate and no way out, and the one mitigation was a single `/health` ping on mount. `lib/async/slowServer.ts` is the rule (no React, an injectable clock): **quiet for 3 s, then ONE sentence, "The server is waking up. The first screen of the day can take up to a minute.", and at 20 s a Retry where the region can read again.** Each pending region keeps its OWN clock and of those with something to say one speaks (furthest along, then one that can retry, then the oldest), so a page with three skeletons says it once. It lives in the whole loading family, not only the two the audit named: `AsyncBoundary` has one consumer (`DataTable`), `PageLoader` six and 82 files draw another skeleton, so every function in `components/ui/skeleton.tsx` that renders `role="status"` ends with `SlowServerNotice` (the guard is the RULE, derived from what a function renders, with a negative control), `AsyncBoundary` wraps the skeleton it was given in `SlowServerScope` and speaks for it, and a bespoke skeleton built from `<Skeleton>` on a page, and the inline `Spinner`, are NOT covered. **Nothing retries by itself, and Retry exists only where a region hands in an `onRetry`**: `lib/api` does not retry a timeout on purpose (a second copy of the slowest query lands on an instance already struggling, and a retried write is a duplicate voucher), the notice is importable only by `skeleton.tsx` and `states.tsx` so it can never sit inside something that is saving, `onRetry` is called in exactly one place (the button's click), and the click restarts that region's clock so the button cannot be pressed into a pile of requests. The sentence is gone in the very render the data arrives (read from `pending`, not from state an effect resets), the live region is always present and takes no space while empty, and a static-export prerender is quiet. **`lib/api/keepAwake.ts` is the old warm-up ping and a ten-minute repeat, ONE controller**: `AuthContext` warms up on mount as before, starts it while somebody is signed in and stops it on sign-out or unmount; it pings only while the tab is visible, at once on returning to a tab hidden longer than the window, once a window across tabs by a `localStorage` timestamp (every access guarded, never required), as `GET /health` with `credentials: "omit"`, no headers and no body, and fails silently. ⚠️ It keeps a free-tier instance running for as long as anybody is signed in and looking, which is the point and is also instance-hours: the owner's call if that ever matters. **The scan is `scripts/axeAudit.mjs`, run by the smoke walk with `@axe-core/playwright` installed in the walk's own CI job at an exact version (never in `package.json`; a test holds the workflow's pin equal to the helper's).** Sign in, sign up, the dashboard, a client's sales, the journal editor and the firm menu opened FAIL on any serious or critical WCAG A/AA violation with no allowlist (the baseline refuses an entry naming one); every other screen is held by `scripts/axe-baseline.json`, a ratchet that may only shrink: a new (route, rule) pair, a grown count and a line that no longer fires all fail, and a fallen count passes and is reported (a ceiling, as the ruff baseline's figures are, because a node count is measured by a browser). `--axe-init` writes the first baseline and refuses to overwrite one, `--axe-shrink` can only lower. **A walk that scanned nothing exits 2, a missing scanner is a loud skip locally and exit 2 in CI, and a named screen that did not land where it was sent is a failure**, because a scan of the wrong page says "clean" about a page nobody meant. The first scan found real defects: the firm menu and the client module menu were `role="menu"` holding links (critical `aria-required-children`) and are disclosures now (`aria-controls` over a labelled region); the dashboard's deadline badges were 3.57:1 and use the state tokens' own inks; the health pill's label sat at 70% opacity; the workspace panels' headings were `gray-400` at 2.53:1. 102 findings on 70 other screens are baselined, 28 of them one icon-only back link with no name that a single `aria-label` pass would take out, left alone to keep this change out of 56 other pages. The same walk drives the notice live (the API held for 24 s on `/tasks`: the sentence once at about 3 s, Retry at about 20 s, both gone with the data). The baseline's counts were measured against this sandbox's Chromium and axe-core 4.13, and a runner's browser may differ by a node (the ceiling is for that); the first runner run (8 October 2026, green) found none that differed, and the workflow should be run by hand after any bump of the pinned Playwright or axe version. **frontend_ux-01 is decided and unchanged**: a build of 3 min 18 s to 3 min 30 s plus a walk of 7 min 51 s to 9 min 49 s (4 min 53 s without the scan) is fourteen to sixteen minutes on a runner, over the twelve the rule allowed, so the nightly, dispatch and `smoke-walk` label triggers stay, with no `push` trigger, no `paths:` filter and never a required check; what would move it is a cheaper walk (scan only the screens a change touched, which needs a file-to-routes map nothing holds), not a looser line. Deliberately NOT done: no automatic retry, no cap on keep-alive hours, no scan of moderate or minor findings, no fix of the baselined 102, and `tests/test_the_smoke_walk_runs_by_itself.py` was restated to the rule (the pinned Playwright is added to the walk's job and nowhere else; a broken screen or a herd still fails the run and the report is written before the final exit) because it pinned a spelling of the install line and of the `failed` expression.

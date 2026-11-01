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

- **A PREVIEW OF AN AMOUNT IS THE SERVER'S RULE OR THE SERVER'S ANSWER, AND A QUANTITY IS NEVER MULTIPLIED BY A PRICE ON A SCREEN** (POST-A-134, triage closed 19-10-2026). The ledger asked for every browser-side computation of a rate or proportion of money to be found and moved. A scan of the whole web tree found 206 lines that multiply or divide beside a paise or bps name (99 files) and 56 more beside a rate-named identifier, and every one was read. Nearly all are what the rule allows: a unit conversion (paise over 100 for display, an export or a form pre-fill), a formatter, a count ratio behind a progress bar, a plain integer sum of server figures, or a parity-pinned mirror (`lib/money/gstLine`, `cessLine`, `decimalMath`, `lib/invoices/gst`). **Two were real mismatches with the server, and both multiplied a quantity by a price:** the recurring invoice and recurring bill template totals used `Math.round(rate * quantity)`, binary floating point that rounds, where the document engine values a line as `int(Decimal(str(quantity)) * rate_paise)`, exact decimal multiplication and then TRUNCATION (0.335 units at Rs 1 is 33 paise on the server and showed 34); they now go through `lib/recurring/templateBase`, which values every line with `taxablePaise`, the mirror `shared/gst-parity-vectors.json` pins. The inventory write-down modal's preview was a different formula altogether: `Math.round((average cost - NRV) * quantity)` from the item's ROUNDED average cost, where the server compares the stock ledger's exact carrying value with `round_half_up(quantity * NRV)`. For 1,000 units carried at Rs 10,004.00 (an average held as Rs 10.00) and an NRV of Rs 10.00, the modal said nothing would post and the server wrote down Rs 4.00. The preview is now the server's: `POST /api/inventory/items/{id}/writedown-preview` reads the same ledger row and hands it to `_compute_nrv_writedown`, the function the posting runs, so the two cannot disagree (tests pin the previewed amount against what then posts across nine cases, including the half-up one, and that a preview writes no ledger row, journal or audit entry); the modal shows nothing while the answer is awaited and, if it fails, says so and still lets the save through, because the server works the amount out again. **The rule, not the four spellings,** is held by `apps/web/scripts/a-quantity-is-never-multiplied-by-a-price-in-the-browser.test.ts`: outside `lib/money/`, no source file multiplies an operand named like a quantity (comments and strings stripped; shown to find the old forms and to leave an unrelated product, an exponent and prose alone, and run against the previous code it finds exactly the four sites). **Left, and recorded as POST-A-266:** the fixed-deposit maturity estimate, the loans EMI calculator and the currency preview, each of which already says it is an estimate. No migration. Not driven in a browser.

- **A LIST IS NOT GIVEN AN ELEMENT OUT OF AN UNCHECKED PAYLOAD EITHER, AND THE COUNT THAT WAS KEPT APART IS A FAILING TEST** (POST-A-159, 29-10-2026). The rule that array state is not replaced from an API payload until `arrayOrEmpty` has looked at it had a sibling it deliberately left uncounted as a failure: `setRows(prev => [json.data, ...prev])` and `prev.map(r => r.id === id ? res.data : r)`, which put `undefined` into the list as an ELEMENT. It was recorded as "15 on 24-09-2026, a blank row and not a dead screen", and the second spelling is worse than that: the next render reads `r.id` off the `undefined` and throws. Thirteen sites were still there (the year-end checklist three times, the notes twice, the adjustments, the exports, the onboarding workflow twice, the lifecycle workflow and renewal, the relationship register and the copilot's new conversation). Each now narrows the element with `objectOrNull` first and, when the answer cannot be read, says so in the words the screen already uses for a refused save (a toast, the action error, the chat error) and leaves the list as it was; the copilot's conversation create, which read `res.data.id` outside any `try`, now reports a conversation it could not start instead of rejecting silently. `a-payload-field-is-not-a-list-until-it-is-checked.test.ts` asserts none remain, with the same detector that counted them. Not driven in a browser; the typecheck and the 3,784 script tests pass. What it does not see: a payload read through a variable first (`const d = json.data; setRows(prev => [d, ...prev])`), a setter called with the element through a helper, and a list that is not `useState<T[]>([])`.

- **A DIALOG THAT DECLARES ITSELF MODAL KEEPS THE KEYBOARD INSIDE IT AND THE PAGE BEHIND IT STILL, AND A NEW FULL-SCREEN OVERLAY IS NOT BUILT BY HAND** (POST-A-130, first step, 31-10-2026). The shared `Drawer` said `aria-modal="true"`, restored focus on close and closed on Escape, and let Tab walk out of the panel into the page behind it; a screen reader was told everything behind was inert and a keyboard user watched focus vanish. `lib/ui/focusTrap.ts` is the one rule both the Drawer and the Modal now ask: `tabTarget` is pure (it takes the focusable elements in order and the active one and says `first`, `last` or leave it to the browser; focus on the panel itself or outside it is pulled in, so Shift+Tab straight after open no longer leaves), and `trapTabKey` is the DOM wiring. A Tab whose focus is inside a DIFFERENT `aria-modal` dialog, or that a nested handler already took, is left alone, so a Modal opened over a Drawer traps its own Tab and the Drawer's takes over again when it closes. `lib/ui/scrollLock.ts` locks the page behind while a dialog is open, reference-counted so a dialog over a dialog keeps it locked until the last closes and the page gets back the `overflow` it had before the first (the ledger said the Modal already had a scroll lock; it had the Tab trap and no lock, so both have it now). **A NEW OVERLAY IS NOT BUILT BY HAND:** `scripts/an-overlay-is-the-shared-dialog-or-on-the-frozen-list.test.ts` finds a full-screen fixed layer as the RULE, with the TypeScript parser (a class string carrying `fixed` and `inset-0` or all four corners, in any spelling: JSX attribute, braced string, template, `cn(...)`, a conditional), and freezes the 143 that exist in 85 files outside `components/ui` as an EQUALITY that can only shrink, in both directions; it does not see a class assembled at run time, a layer styled in CSS, or whether a listed overlay is accessible, which is the migration each is waiting for. **VERIFIED:** 9 unit tests on the rule and the lock, 5 on the budget (each spelling found, what is not an overlay spared, both directions of the equality), and five scenarios driven in Chromium (group `dialogs`: Tab and Shift+Tab sixty presses each inside the invoice drawer, Shift+Tab straight from the panel, a modal over the drawer trapping its own Tab and the drawer's coming back, the page locked until the LAST dialog closes, Escape returning focus to the row). Built without the Drawer's trap and lock, four of the five fail (the fifth guards behaviour the Drawer already had). **Not done:** the 143 overlays are not migrated (months of work, a screen each); the other shared dialog, `ConfirmDialog`, was not changed; Firefox and Safari were not driven.
- **A NATIVE FORM CONTROL HAS A PROGRAMMATIC NAME, OR ITS FILE IS ON A FROZEN LIST THAT ONLY SHRINKS** (POST-A-127, first step, 1-11-2026, no migration). About 1,200 native `<input>`, `<select>` and `<textarea>` stood in the tree and 591 of them, in 127 files, had no accessible name: a visible `<label>` sat beside the control with no `htmlFor` and the control with no `id`, or there was only a placeholder. A screen reader announces such a field as "edit text" and `getByLabel` cannot find it; the screens a CA types into all day were among them. **THE RULE IS THE PARSER'S** (`scripts/formControlNames.ts`, the TypeScript compiler API and not a regex): a control is named by `aria-label` / `aria-labelledby`, a `<label>` ancestor in the JSX tree, an `id` that a `<label htmlFor>` of the same file points at (compared as the string literal's value or the expression's source text, so `id={id}` pairs with `htmlFor={id}`), a parent `Field` that ties its label to its children (the one imported from `components/ui/field`, or one declared in the same file whose body puts `{children}` inside a `<label>`), or by being a hidden / submit / button / reset / image input. **A placeholder or a title is not a name:** a placeholder vanishes the moment the field has a value, which is when a reader returns to it. A control that spreads props is a wrapper's, named by whoever calls the wrapper, and is counted apart so a spread is never mistaken for a named control. **The first version of the finder started its walk up from the wrong node for a self-closing control, so every `<input />` inside a wrapping label read as unnamed (it counted 850, and 504 after the sweep, where the corrected count was 591 and 245); the unit tests that pin a wrapping label and a `Field` parent caught it, and the sweep was checked against the corrected rule afterwards: every one of the 346 landed on a control that was unnamed before.** **WHAT WAS FIXED NOW, AND HOW:** 346 controls were named in the same commit by giving each the text of the bare `<label>` written just before it, in the same parent with no other control between them, as an `aria-label`: visually identical, and the visible label's words are the accessible name (WCAG 2.5.3, label in name). A label built at run time, a placeholder, and a control with no label beside it were not guessed at. Every one of the 346 landed on a control the corrected rule also counted unnamed. **A wrapping label, or an `id` and `htmlFor`, is the better end state** (the name cannot drift from the visible words) and the rule accepts both; the aria-labels are the interim that makes the field findable today. **THE LIST IS A RATCHET:** the 245 that remain, in 85 files, are in `scripts/form-control-names-baseline.json`, each as its tag and what it is bound to (`select:form.account_type`, or a hash of its text when it is bound to nothing), and asserted as an equality in both directions, so a new unnamed control fails, a fix that leaves its entry behind fails, and, because the entries are the controls themselves and not a count per file, a fix and a new control in one file cannot net out; a control that spreads props is allowed only in `components/ui/` (six today), where the callers name it; `scripts/refresh-form-control-names-baseline.ts` rewrites it and refuses to grow it. **The independent review (1-11-2026) found three faults in the first version, now fixed:** (1) the finder trusted ANY element called `Field`, and the fixed-assets screen declares its own that draws its label BESIDE the children (no `htmlFor`), so all 28 controls in it, 23 of them counted as named, had no name: `Field` is now trusted only when imported from `components/ui/field` or when the file's own declaration wraps `{children}` in a `<label>`, the fixed-assets one now wraps (three radio sets, whose items are labelled one by one and which a label may not contain, are named as a `role="group"` instead), and the corrected count is still 245 unnamed because the 23 were named for real; (2) one aria-label was copied from the wrong label (the reason box of the e-way extension took the date's), and three held a literal `&apos;`; the first is "Reason for the extension" and the others real apostrophes, and a scan of all 316 labels the sweep copied found no other that came from a label wrapping a different control; (3) the baseline was a count per file, which a fix plus a new control in the same file would net out, and spreads were not limited to the primitives: both are now asserted. **What it does not see:** a control inside a component that is not a JSX element of the file, a label in another file, a name computed away from the expression it was written as, and whether a name is GOOD. **Not done:** the 245, and a check that every CALL of a primitive (`Input`, `Select`, `DateInput`, `Combobox`) passes a name. **Verified:** 11 unit tests on the finder (each way of being named, each way of not being, a Field that is imported, one that wraps, one that draws a sibling label, one that is neither, a spread, a placeholder, a title, a self-closing control inside a label, the key of a control) and 4 on the baseline, with two mutants of the baseline (a fix and a new control in one file; a spread outside `components/ui/`) each failing; the whole web suite, types and lint, the Python guards that read the front end; **not driven in a browser and not read by a screen reader**: the names are checked as attributes in the source, not as what a reader announces.

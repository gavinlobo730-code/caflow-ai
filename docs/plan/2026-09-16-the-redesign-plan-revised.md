# The redesign plan, revised against the code

Written 16 September 2026, replacing the sizing and the sequence in
`2026-09-12-compliance-and-craft.md`. That document's JUDGEMENTS still hold —
light only, tables get the width, prose keeps its measure, one PR per module.
Its FACTS were four days old and eight read-only agents plus three adversarial
skeptics found them wrong in ways that change the order of the work.

**Read this before scheduling anything. The 12 September plan is kept for its
reasoning, not its numbers.**

---

## 1. The finding that reorders everything

**Track 1 — the safety net, which the 12 September plan calls the thing the
redesign is blocked on — was built on 13 September. It passes. And two of its
four pieces observe nothing at all.**

`2026-09-13-questions-for-the-owner.md` §5b says "Track 1's safety net is
finished and green." That sentence is true about the tests and false about the
coverage, and it is the most dangerous sentence in either document, because it
is the one an owner reads before authorising Track 4.

### 1a. The smoke walk has never rendered a product screen

`apps/web/scripts/smoke-walk.mjs` answers every PostgREST read `[]` (line 158).
So `resolveUserContext` resolves `hasFirm: false` (`lib/auth/AuthContext.tsx:37`),
`mayRenderProtected` returns false (`lib/auth/guardDecision.ts:42`), `AuthGuard`
returns `null` and redirects to `/onboarding` (`lib/auth/AuthGuard.tsx:33-35,71`).
The page component is never invoked.

Measured on the real artefacts of the 12 September run:

```
$ md5sum apps/web/.smoke/*.jpg | awk '{print $1}' | sort | uniq -c | sort -rn | head -3
    148 0748f10d6595f253ac923308675c4d80
      2 07e70c23b8ed99208d8af745b4858dc3
      1 ecca8923c1412c890ff6878d43a5e0c3
```

**148 of 159 screenshots are the same image**, and that image is the onboarding
wizard — "Welcome! Let's set up your firm, Step 1 of 3". Zero of the fourteen
modules ever rendered. The eleven that differ are auth, portal and signing
pages. The walk reports green because the wizard has a non-empty body and throws
nothing: its only content assertion is `if (!text) errors.push("rendered an
empty body")` (line 264).

So the "visual baseline … so every screen can be seen side by side before and
after" is ten distinct pictures, none of a module, and it is gitignored
(`apps/web/.gitignore:19`) so it exists only on the machine that ran it.

### 1b. The required checks report green without running

`.github/workflows/backend-ci.yml:74` gates the whole backend suite on a diff
touching `apps/api/`. Its own `else` branch says so in words:

> `echo "No backend files changed — the required jobs will report green without running."`

A module conversion is an `apps/web`-only diff. So **the endpoint-reachability
guard — written specifically for this redesign, to catch "a screen that quietly
stops calling the engine behind it" — never runs on the PRs it was built for.**

And the frontend workflow that carries the other 716 guards is not a required
check. Its own header argues it should be (`frontend-ci.yml:10-12`).

Net: today a redesign PR can merge with both required checks green and nothing
having verified it.

### 1c. The reachability guard cannot see a screen

`test_every_mounted_endpoint_has_a_way_in.py:103-107` concatenates `app`, `lib`
and `components` into ONE blob and regex-matches URL literals against it. The
URL literals live in `lib/api/index.ts` — 5,025 lines of client library. So an
endpoint stays "reached" when the literal sits in the API client, whether or not
any screen still calls it.

Measured consequence, re-run by hand against HEAD rather than taken on an
agent's word:

```
mounted endpoints                            1034
reached (app+lib+components, as CI does it)   905
snapshot (what the guard protects)            777

reached by a file under app/ or components/   370
reached ONLY by lib/ (no screen names it)     469   <-- 60% of the snapshot
```

**60% of the endpoints the guard claims to protect are held "reached" purely by
a URL literal in the API client library.**

Stated the way that actually matters — deleting each of the 160 `page.tsx`
files in turn and asking the guard what it lost:

```
SCREENS THAT CAN BE DELETED ENTIRELY WITH THE GUARD REPORTING ZERO LOSS:
   134 of 160   (83%)
   caught: 26
```

**83% of the product's screens can be deleted outright — not degraded, deleted —
and the guard written to protect this redesign reports nothing.** The 26 it
catches are the screens that happen to build a URL inline instead of going
through `lib/api`. A skeptic reproduced the end-to-end case on
`app/clients/[id]/reports/ageing/page.tsx` — deleting the whole file reports
nothing, and with it goes the only writer of `vendors.msme_status`, the MSMED
§2(n) fact CLAUDE.md records as changing taxable income under §43B(h).

The guard also matches PATHS, not (method, path). A rebuilt panel that keeps its
DELETE call and drops list/create/edit is invisible — reproduced against
`/api/banking/rules`.

### 1d. Both snapshots are already behind

128 endpoints are reached today and absent from the snapshot: inventory 16,
sales-cycle 13, purchase-cycle 11, recurring-purchase-bills 11,
recurring-journals 9, cwip 6, bills-of-entry 6, rcm-documents 6,
client-gst-registrations 5, opening-documents 5, fx-revaluation 2,
accounting/budgets 2, and more. Every one is a feature built in the last week.
Dropping any of them is reported by nothing.

### 1e. There are no error boundaries at all

`find apps/web/app -name error.tsx -o -name loading.tsx -o -name global-error.tsx`
returns zero files across 160 routes. Track 4 promises "if something breaks it is
one module and one diff" — in the App Router, without `error.tsx` a render throw
unmounts to the root, so that containment claim is false at runtime. And an
error page has text, so the smoke walk reports green on exactly the failure a
boundary would have contained.

This is the missing fifth piece of the safety net.

---

## 2. The corrected sizes

Every figure below was measured, not estimated from the plan.

| track | plan said | measured | why |
|---|---|---|---|
| 1 — safety net | "does not exist, blocked on it" | **built, 4–6 days to make it observe anything** | §1 |
| 2 — design system + reference module | ~1 week | **11–13 days** | the token layer exists and is 0.2% adopted |
| 2.5 — token adoption | *not in the plan* | **5–8 days** | 10,828 hex literals, 259 files, unowned by any track |
| 3a — PDF restyle | part of 1.5–2 weeks | **6–9 days** | six services produce NINE documents; one is not reportlab |
| 3b — Excel to server | part of 1.5–2 weeks | **10–13 days** | 11 actions, and money is TEXT in every one |
| 4 — navigation | 2–3 weeks | **11–17 days**, excluding per-screen conversion | 2,675 lines across two shells that share nothing |
| 5 — the portals | *not in the plan* | **unsized** | 6 routes, 1,713 lines, outside every track |

**Honest total: 10–14 weeks, not 5–7.** The difference is not padding. It is
three pieces of work the plan did not contain (token adoption, the portals, the
safety-net repair) plus two it under-counted by half.

### What each correction rests on

**Track 2 — the tokens exist and nothing uses them.**
`tailwind.config.ts` has carried `brand`/`gold`/`ps.*` scales and three shadow
tokens all along. `grep -rl 'bg-brand\|text-brand\|bg-ps-\|border-ps-'` over
`app/` and `components/` returns **zero files**. Against that, 10,828 raw
`#RRGGBB` literals across 66 distinct values — and the four commonest
(`#E2E8F0` ×1,493, `#F8FAFC` ×1,192, `#F1F5F9` ×952, `#182350` ×352) are the
token values retyped. Ten of the 13 `globals.css` component classes and 11 of
the 37 CSS custom properties have zero callers.

Track 2 is not "define a vocabulary". The vocabulary is defined and ignored —
the `capital_wip` / `fx_revaluation` shape this codebase keeps finding. The work
is replace-and-migrate across 259 files.

**Track 3b — the Excel defect is worse than the plan's and different in kind.**
The plan says SheetJS CE "cannot style a cell at all. No fonts, no borders, no
number formats, no column widths." Two of those four are wrong: `cell.z` writes
a real `numFmtId` and `ws['!cols']` writes a real `<cols>` element, both proven
by writing a file with the installed 0.18.5. Fonts, fills, borders and frozen
panes genuinely cannot.

The defect the plan does not name: **every money cell in every browser export is
a TEXT cell** — all six builders emit `(paise/100).toFixed(2)` — and SheetJS
writes `<ignoredError numberStoredAsText="1"/>` over the used range, which
suppresses the green triangle Excel would show. A CA who opens a PracticeSync
trial balance and types `=SUM(B:B)` gets **0**, with nothing on screen to explain
why. That is a correctness defect on an output that leaves the building.

And server-side Excel is not from zero: `services/time_export_service.py:57-71`
already builds a styled workbook with openpyxl, is mounted, called and in the
ratchet. `openpyxl>=3.1.0` is deployed. There is a precedent to copy.

**Track 3a — nine documents, two engines, and a live correctness bug.**
`engagement_pdf_service.py:60` is `xhtml2pdf`, not reportlab, so one shared
reportlab style module cannot reach it. Invoice is two documents and year-end is
three, so the restyle surface is 50% larger than "six".

Found on the way, and it should not wait for a design system:
`invoice_pdf_service.py:82` and `payslip_pdf_service.py:212` both use
`f"{rupees:,}"`, which prints ₹12,34,567 as **1,234,567** — Western grouping, on
the Rule 46 tax invoice a CA's own client receives, while the browser shows the
same invoice correctly as 12,34,567. No test pins it. Separately,
`year_end_pdf_service.py:168,726` stamps the signed year-end pack with naked
`datetime.now()` and no TZ is set anywhere, so a pack generated at 01:00 IST on
1 April is dated 31 March — the wrong financial year on the face of the
document, breaking CLAUDE.md's own IST rule, with no finding against it.

**Track 4 — a hard external constraint the plan never mentions.**
Cloudflare Pages ignores `_redirects` rules past position 100, silently — no
build error, no test. The generated file is at **98**. Each new page under a
dynamic segment costs exactly 2 rules. `scripts/generate-redirects.js:16-30`
records that overrunning it "caused the *whole client workspace 404s*
regression", and `year-end/[engagementId]/_workspace.tsx` records collapsing
eight routes into one query-param workspace purely to get back under it.

**A hub drawn as routes rather than as a query-param workspace hits the cliff on
its second screen.** Nothing in CI counts the rules.

---

## 3. Decisions the plan got wrong on the merits

### The reference module should not be Banking Entries — or not only

The plan picks it as "the densest screen in the product" and "the proof that a
dense table reads well at full width". Four independent measures disagree:

- **6 columns**, against 12 on the invoice/bill line editors, 11 on the payroll
  leave table, 10 on the purchase-bill list;
- **4th by composed line count** (5,392, behind purchases 12,538, sales 11,255,
  client payroll 6,154);
- **it is already full-bleed** — `app/clients/[id]/bank/page.tsx` uses bare
  `px-6` with no max-width, and both shells are fluid — so converting it
  exercises *nothing* of the two-tier width decision;
- **3 responsive prefixes across 14 files**, so it proves nothing about narrow
  either.

It is also the single most brittle screen to convert: `bank-entries-is-a-table.test.ts`
is 19,790 bytes pinning exact Tailwind class literals, exact column headers,
exact button labels, component filenames and minimum file lengths.

**Take two reference screens.** The periodic **Trial Balance**
(`app/clients/[id]/accounting/page.tsx:597,1384` — 9 Dr/Cr columns inside
`max-w-4xl`, 896px) is where the width rule actually bites. Banking Entries
second, for density and for the guard rewrite.

Two of Banking's own findings (BANK-13, BANK-28) also land on that screen — so
judging the design system on it means judging a screen that still cannot tell
one cheque from another. Fold BANK-28 into the conversion; leave BANK-13.

### "Fourteen modules" matches nothing in the code

The firm rail holds **12** workspaces; the client sidebar holds **21** sections;
the "fourteen" is the row count of the audit's module scorecard, which includes
rows like "Frontend / UX" that are not nav destinations. Meanwhile the 160 routes
fall into **66** distinct top-level groups, and **39 firm-level routes appear in
no nav component at all** — every `/accounting/*` screen except the hub,
`/gst/gstr1`, `/gst/gstr3b`, seven under `/income-tax/*`, seven under
`/settings/*`, `/reports/cash-flow`, `/tds/returns` and more.

**Choosing the hub's taxonomy is a decision nobody has taken and it is on the
critical path.** The existing `every-screen-has-a-way-in` guard will not force
it: a link from any page body satisfies it, so a hub can silently leave all 39
where they are.

### ⌘K already exists

`AppShell.tsx:53-63` binds it globally today; it opens an entity search over nine
categories. The keybinding is taken and `ClientsPanel.tsx:28` advertises it as
"Search clients…". Re-pointing it at navigation is a smaller job than the plan
implies and collides with an affordance a CA may already use.

### Dark mode needs no removal work

One inert line, `darkMode: ["class"]` at `tailwind.config.ts:4`. Zero `dark:`
classes, no theme provider, no `prefers-color-scheme`, and `globals.css:64`
already declares `color-scheme: light`. The plan's condition is already true.
Delete the line; keep `brand.dark: "#0D1635"`, which is a navy shade and the one
thing a grep-for-dark removal pass takes out by mistake.

---

## 4. What the plan does not contain at all

### The client and employee portals

Six routes, 1,713 lines under `apps/web/app/portal/`. `AppShell.tsx:28-36` puts
`/portal` in `NO_SHELL_PREFIXES`, so they render outside the staff chrome — a
Track 2 design system and a Track 4 navigation change reach **none** of them.
`app/portal/page.tsx` and `app/portal/employee/page.tsx` import zero shared
primitives.

The plan opens by correcting itself: "the CA's client never sees the software"
is "half right and the wrong half to act on". It then defines the whole redesign
over the staff shell — and never notices there IS a surface the client and the
employee see. If the portals keep today's look, the product visibly has two
designs and the one the outside world sees is the old one.

### apps/marketing

Separate Cloudflare project, own Tailwind config, five routes, 2,686 lines. Its
config's first comment says the brand tokens "mirror apps/web/tailwind.config.ts
so the marketing site and the application read as one product". It is a
hand-copy with nothing pinning the two. The moment Track 2 changes a brand value
they diverge silently — the exact drift shape CLAUDE.md warns about three times.
The repo's standing answer is a parity test written from the owning side.

### There is no demo firm, and nothing can make one

`apps/api/seed/seed_data.py` — 164 lines, a full DEMO_FIRM, five users, twenty
named clients with valid PANs and GSTINs — has **zero importers**. No demo-mode
flag, no reset path, no "create sample firm". The only way in is the 940-line,
three-step, OTP-gated onboarding wizard.

This is the direct cause of §1a: with nothing to seed, the walk stubs everything
empty and lands on the wizard. **It is also on the critical path for the CA
demo** — a CA cannot be handed a login and shown populated screens. Both the
safety net and the demo depend on a capability that does not exist as a runnable
thing.

### The most-used text colour fails WCAG AA

`#94A3B8`, **1,690 uses**, is 2.56:1 against white — below AA's 4.5:1 and below
even the 3.0:1 large-text floor. `#CBD5E1` (161 uses) is 1.48:1. Sampled usage
is body and helper copy, not decoration. No axe, no contrast tooling, no
`eslint-plugin-jsx-a11y`; 75 of 298 tsx files carry any `aria-*` and there is one
`aria-live` in the tree.

The plan rejects dark mode because "a CA sits in front of this for eight hours
during a filing week". Sub-3:1 helper text is the same argument pointing the
other way and it was never made. Fixing it during the token migration is nearly
free; afterwards it means re-touching the same 1,851 sites.

### Printing from the screen is broken

Seven `window.print()` buttons exist (reports, three on the client accounting
tab, schedule-iii, payroll). Exactly one `@media print` block exists
(`app/reports/page.tsx:886`) and it is broken: it sets `body > * { display: none
!important }` then re-shows `.report-print-root`, but `AppShell` nests children
inside `<main>` inside the body child, and `display:none` on an ancestor cannot
be overridden by a descendant — **so `/reports` prints blank**. The other six have
no print stylesheet at all, and `AppShell`'s `h-screen overflow-hidden` clips a
printed table to one viewport.

Indian practice still runs on paper for client sign-off and the audit file.
Moving to fluid full-width makes this worse, because the table gets wider.

### The product is an installable PWA with no responsive design on its biggest screens

`layout.tsx:16` declares a manifest, `:30` registers a service worker,
`manifest.json` sets `"display": "standalone"`. Against that: **86 of 160 page
files contain zero responsive prefixes**, including 5 in 3,803 lines (client
purchases), 6 in 4,853 (client sales), 0 in 1,388 (payroll attendance — the
11-column leave table). The density decision settles the upper bound and never
names the lower one.

### There is live production data, and only the API half is instrumented

`.github/workflows/smoke.yml` runs every six hours against the live deployment
with `SMOKE_CLIENT_ID` documented as "a client with a REAL ledger… the endpoint
that took 57s was serving 12,836 entries", enforcing latency budgets on six
endpoints. Its own docstring: "Not a browser test. It makes no attempt to render
pages."

So the redesign's blast radius and its instrumentation are disjoint: five to
seven weeks will change the browser, the only live instrument is explicitly not
a browser test, and the browser instrument renders the onboarding wizard.

That workflow also answers, by itself, a question the owner-questions doc defers:
**there is real client data in production.**

---

## 5. The revised order

Nothing below starts until the one before it is done, except where marked
parallel.

### Track 1.5 — make the safety net observe something · 4–6 days · BLOCKING

1. **CI, 2 hours.** Widen `backend-ci.yml`'s scope grep to include `apps/web/`,
   or add a third always-running job scoped to the two reachability tests. Make
   `frontend-ci` a required check. Without this every item below is decoration.
2. **Attribute reachability to a calling file.** Record the snapshot as
   endpoint → matching files and define a loss as "no file under `app/` or
   `components/` reaches it". This is the change that moves 469 endpoints from
   nominally to actually protected.
3. **Seed the smoke walk.** Answer the `users` read with one row carrying a
   `firm_id` so `hasFirm` resolves true. Expect the walk to turn red across many
   routes at once — that triage is 2–3 days, it is the real work, and it must
   land before the first conversion rather than during it.
4. **Assert content, not non-emptiness**, plus a guard that fails the run if more
   than N screenshots share an md5. That one check would have caught this on
   12 September.
5. **Add `error.tsx` boundaries.** Without them Track 4's containment claim is
   false.
6. **Refresh both snapshots at HEAD**, in a reviewed commit, and treat any later
   movement as a finding.

### Track 1.6 — a demo firm that exists · 2–3 days · parallel with 1.5

Make `seed_data.py` runnable and extend it to a full year of transactions. It
unblocks the smoke walk, the visual baseline and the CA demo at once.

### Track 2 — design system + two reference screens · 11–13 days

Tokens light-only with a type scale that goes DOWN to 10px (the product already
lives there 1,761 times); the eight missing base primitives (there are 856 raw
`<input>`, 300 raw `<select>`, 230 raw `<table>` with nothing to converge on);
the six product-specific components. Reference: Trial Balance first, Banking
Entries second.

Fix the contrast during the token pass, not after.

### Track 2.5 — token adoption · 5–8 days · THE UNBUDGETED MIDDLE

Codemod the 66 hex values; judgement pass over the 8,234 Tailwind named-colour
utilities (`amber` and `red` encode status meaning, `blue` is mostly chrome — a
blanket codemod flattens that distinction silently). **This must land before
module two, or module two re-litigates module one.**

### Track 3 — outputs · 16–22 days · parallel with 2 and 2.5

3a PDF (6–9d), 3b Excel (10–13d), 3c one export vocabulary. **Merge SALES-13
into 3a** — it is the same six files, and scheduling them apart means writing
the style module and retrofitting `invoice_templates` into it a week later.

Two fixes here should not wait for the design system: the Western rupee grouping
on the tax invoice and payslip, and the UTC timestamp on the year-end pack.

### Track 4 — navigation · 11–17 days + per-screen conversion

Blocked on the taxonomy decision and on reclaiming redirect headroom. Add
PAY-28 (`deferred_to_the_redesign`) to its acceptance list or it closes by
accident.

### Track 5 — the portals · unsized

Decide in or out. Out is defensible; leaving it undecided is not.

---

## 6. What runs in parallel, and what does not

**Exactly 8 backlog items can run alongside the redesign**, not 35: PAY-21,
BANK-10, GST-19, INV-09, IT-09, PUR-07, SALES-13, SALES-15 — 14–17 days of
backend work. **17 are screen-shaped** and would be built twice. **10 are
blocked** on a document or a decision.

`docs/audits/what-to-fetch-for-me.md:355` closes with "Everything else I could
build without you is built." That was true on 15 September and false on
16 September — the re-read surfaced 8 items needing no permission, no document
and no decision.

Two splits are worth making rather than treating as whole items:

- **ACC-22** — land the backend half now (carry `source_type`/`source_id`
  through the reporting model and `account_ledger_page`) so the redesigned
  ledger table has something to click on. Do not build the click twice.
- **IT-20** — its statutory branch is blocked; its surfacing branch is one hour
  during any screen pass.

---

## 7. What only the owner can decide

| # | decision | why it blocks |
|---|---|---|
| 1 | **The hub's taxonomy** — 66 route groups into how many tiles, and in what order | Track 4's critical path; three existing taxonomies disagree and none is the answer |
| 2 | **What happens to the 39 firm-level routes with no nav home** — adopt into the hub, or accept them as reachable only from inside another page | same |
| 3 | **Portals in or out** | Track 5 exists or does not |
| 4 | **Density persistence: per device or per user** | per user needs a migration; per device is a localStorage allowlist entry |
| 5 | **Money display policy** — collapsing 11 behaviours to one changes figures on four screens that currently show whole rupees and two that silently drop paise | a CA reading an ITC figure that gained two decimals reads it as a data change |
| 6 | **Invoice rupee grouping** — fixing Western → Indian makes invoices issued after differ from invoices already in customers' hands | presentation, not a statutory particular, so it is safe — but it is your call |
| 7 | **Demo on a seeded firm or on real client data** | decides whether Track 1.6 is a demo seed or a Tally migration |
| 8 | **i18n now or never** | extracting strings from a rewritten screen is nearly free; from a settled one it is a second full pass |

---

## 8. The honest total

**10–14 weeks** to a product that is finished enough to show once, against the
12 September plan's 5–7. The gap is the safety-net repair, token adoption, the
portals, and Excel and PDF each being about twice their stated size.

The owner's decision of 15 September — show CAs only after Track 4, one finished
thing, shown once — is unchanged by any of this and is the reason the sequence
above converges rather than producing reviewable increments.

**One observation, offered once and not pressed.** That decision rests on not
showing the *same* CAs an inconsistent product twice. It does not, on its own,
rule out showing one or two friendly CAs an explicitly-work-in-progress build
early, under that framing, to test the hub taxonomy in decision #7 — which is
the most expensive thing on this list to get wrong and the only one no amount of
reading the code can settle.

---

## 9. What you have to verify before a CA sees this

The owner asked on 15 September for "a plan wherein what all I have to go and
verify in detail before going to the CA", to work through together in one long
session. This is that list.

It is deliberately NOT "click every screen". It is the things that (a) only a
person can judge, or (b) are wrong in a way no test in this repo can see. The
machine-checkable half is §5's Track 1.5 and is my job, not yours.

### Before the session — my job, and you should refuse to start until each is true

| # | gate | how you check it in one command |
|---|---|---|
| 1 | The smoke walk renders the product, not the wizard | `md5sum apps/web/.smoke/*.jpg \| awk '{print $1}' \| sort -u \| wc -l` — must be near 159, is 11 today |
| 2 | Both required checks actually run on a web-only PR | open any frontend-only PR and confirm the backend job says it ran, not "reported green without running" |
| 3 | Reachability is attributed to a screen, not to `lib/` | the number in §1c is 0, not 469 |
| 4 | A demo firm can be created from nothing | one command stands up a firm with a year of transactions |
| 5 | Every module has an `error.tsx` | `find apps/web/app -name error.tsx \| wc -l` — must be ≥14, is 0 today |

### In the session — your job, because no test can answer these

**A. The numbers, on one client, against a source you trust.**
Bring one real client's figures — a filed GSTR-3B, a filed 26Q, a signed
balance sheet. For each, check the product's answer against the filed one. Not
because the engines are unverified (16,800 tests, and every statutory rule is
pinned) but because *you* have to be able to say "I checked this myself" to a CA
who asks. Six is enough: one GSTR-1, one GSTR-3B, one 26Q, one payslip, one
trial balance, one balance sheet.

**B. The documents that leave the building.** Print them. On paper.
- the Rule 46 tax invoice — grouping, GSTIN, HSN, the signature block
- a payslip
- the year-end pack — and check whose name is on it (today it says
  "PracticeSync AI", not the firm's)
- the customer statement

**C. The four judgement calls in §7 that change what gets built.** The hub
taxonomy is the expensive one. Sit with the list of 66 route groups and 39
orphan routes and decide the tile set. Nothing downstream can start without it.

**D. The gaps a CA will hit in the first hour, and whether you are content to
show them.** Each is correct behaviour and a bad first impression:
- payroll in 18 of 22 professional-tax states reports a gap instead of deducting
- §194I(a) and §194J(a) withhold at the higher rate and say so — two numbers off
  the Finance Act close it
- §89 relief does not work for arrears before FY 2025-26 (the rate registry
  holds two years)
- nothing files; the filing demo is honest about it, and a CA may still read
  "cannot file" as "not finished"

**E. One thing to decide in advance: what you say when a CA asks "can I use this
for my practice tomorrow".** The honest answer today is no — not because of the
software but because filing needs a GSP and an ERI registration, and
`docs/compliance/07-getting-permission-to-file.md` says those are months of
commercial work. Decide the sentence before you are asked it.

### What is NOT on this list, and why

Correctness of the statutory engines beyond the six spot-checks in (A). That is
what the test suite is for and re-deriving it by hand would take the session and
prove less. If you want assurance there, the artefact is
`docs/audits/findings-status.md` — 279 findings, every one now carrying a
verdict, 238 closed and re-read.

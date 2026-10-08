# Open items — the single ledger of everything still to do

**Snapshot: 2 October 2026 (IST), `main` at `03acde2a`** (checked again on 7 and 8 October: `main` had not moved apart from this ledger). This directory replaces the audit, finding, "what is left" and plan snapshots that used to answer "what is still open?". If a document and this ledger disagree about whether something is open, this ledger wins; if this ledger and CLAUDE.md disagree about how something works, CLAUDE.md wins.

## How to use it (for a new session, or after a compaction)

1. Read this file, then **only the section file for the work in hand**. The section files are large (about 900 KB in all) and are meant to be searched, not read end to end: `grep -n "POST-B-" docs/open-items/post-demo-B-ours.md`, or grep a theme name, a roadmap id such as `rm/ops-01`, a finding id such as `TDS-16`, or a word.
2. Before building an item, check it is still true: open the code it names. Every line was checked against `main` by its extractor on 2 Oct 2026, and **on 8 Oct 2026 sixty-four of the 788 were checked a second time by reading the code and the CI history yourself: all 39 before-demo items, all 17 high-priority after-demo items and 8 other after-demo items** (corrections from that pass are already in the lines: PRE-A-001, -004, -005, -006 and POST-B-193). The other 724 have not been re-checked since 2 Oct, so an item older than a few weeks is suspect.
3. Items marked **UNSURE** depend on a dashboard or production state the repository cannot show (Render, Supabase, Resend, Sentry, GitHub settings). Reading that state is part of the item.
4. When you close an item, **delete its line in the same commit** as the work, say which ID in the commit message, and remove the ID from the lists in this README and in `decisions-and-strategy.md` (the test fails on a dangling ID). If closing it creates follow-up work, add a new line at the next free number. Never renumber: IDs are quoted in commits and conversations. If you find something new that is open, add it to the right file.
5. `apps/api/tests/test_the_open_items_ledger_is_well_formed.py` enforces the format (unique IDs, one line per item, an allowed theme and priority on every line, no dangling ID in the lists below, counts true). After closing or adding an item run `python3 scripts/open_items_counts.py` to refresh the counts block.

## The two axes

**When — before or after the demo.** The demo is showing practising CAs the seeded demo firm on the live deployment. `docs/plan/THE-PLAN.md` says it has no fixed date (D16; **the owner set 1 November 2026 on 8 Oct, a Sunday, and that supersedes D16**), that the owner decided on 15 Sep to show CAs only once, after a verification session with five gates (Track 4), and that the commercial registrations (GSP, ERI, NIC, Third Party Software Utility; Track 5) start after it. **The pre/post split is a judgement, not a fact:** an item is *before* only if leaving it open could break, embarrass or mislead in front of a practising CA (sign-up and invites, mail, AI answering, a visible wrong number or false claim, a screen that fails, the cold start on the first load, portal behaviour) or it is a cheap check with a large risk reduction. Everything else is *after*. The first pre-demo item now asks only who attends; with 24 days from 8 Oct the whole list fits and nothing has been cut.

**Who — three buckets.**
- **A — Mine** (`…-A-…`): Claude can do it alone: code, tests, docs, CI, a migration under the standing merge convention. No decision, credential, outside document or spend is needed.
- **B — Ours** (`…-B-…`): the owner decides (or approves a spend) first and Claude builds afterwards; or it needs a live session together (rehearsals, single-use email links). The decision question, the options and Claude's recommendation are in the item.
- **C — Yours alone** (`…-C-…`): only the owner or someone outside this container can do it: dashboards, accounts, secrets, payments, registrations, statutory documents a person has to fetch or read (this container's egress to `.gov.in` is blocked), per-client facts.

Line format: `ID · theme · priority · effort [· UNSURE] [· live session] — **Title.** Detail. _When: reason._ — _Sources:_ where it came from — _Refs:_ ids`. Priority is `high` (wrong number, false claim, security or legal exposure, data loss, or gates many items), `normal` or `low`. Effort is Claude's estimate: hours, days, weeks, months.

**Id namespaces — they collide, so read carefully.** Lowercase `area-NN` ids (`gst-18`, `ops-08`) belong to the 30 Sep 2026 roadmap and are written `rm/gst-18` here. UPPERCASE ids (`GST-18`, `TDS-16`, `PAY-27`) belong to the earlier September audit and its status file. `D<n>` are decisions in `docs/plan/THE-PLAN.md`. The same number means different things in the two audit namespaces: `rm/gst-18` is not `GST-18`.

## What is in here

<!-- counts:start -->

| file | items | what it holds |
|---|---|---|
| [pre-demo-A-mine.md](pre-demo-A-mine.md) | 8 | before the demo: Claude can do alone |
| [pre-demo-B-ours.md](pre-demo-B-ours.md) | 16 | before the demo: owner decides, or a live session |
| [pre-demo-C-yours.md](pre-demo-C-yours.md) | 6 | before the demo: only the owner can do |
| [post-demo-A-mine.md](post-demo-A-mine.md) | 198 | after the demo: Claude can do alone |
| [post-demo-B-ours.md](post-demo-B-ours.md) | 332 | after the demo: owner decides first, then Claude builds |
| [post-demo-C-yours.md](post-demo-C-yours.md) | 203 | after the demo: only the owner or outsiders can do |
| [decisions-and-strategy.md](decisions-and-strategy.md) | — | the 15 owner decisions with the items each gates, what is parked until after the demo, the 30 Sep strategy and staged roadmap |
| [checked-closed.md](checked-closed.md) | — | what the sweep tested and found already done, answered or moot, with evidence, so nobody reopens it |
| [deletion-plan.md](deletion-plan.md) | — | which audit and plan documents can be deleted, which must stay and why, and what must be done first |

**763 open items** (30 before the demo, 733 after); 17 after-demo items are `high` priority; 35 are UNSURE.

<!-- counts:end -->

## Before the demo, in the order to do them

Pre-demo items by suggested order. The first is the date; Render and Supabase dashboard checks and the fixes Claude can make come next, then the seeded-firm work, then the rehearsals, then the day-of wake-up.

1. **PRE-C-001** (you) — Tell Claude who attends the 1 November demo (the date is set)
2. **PRE-C-002** (you) — Check the Render dashboard variables
3. **PRE-B-012** (decision) — Check the Supabase dashboard: plan, backups, password and auth limits
4. **PRE-B-016** (decision) — Buy the domain and make mail leave: a verified Resend sender and Supabase sign-up mail
5. **PRE-C-003** (you) — Confirm Resend delivers: verified domain, webhook, one real mail of each kind
6. **PRE-B-004** (decision) — Decide which known gaps the demo fixes, shows or avoids
7. **PRE-B-005** (decision) — Fix the sentence for 'can I use this for my practice tomorrow'
8. **PRE-B-015** (decision) — Decide the marketing-site wording: Privacy/Terms links and 'replaces Tally'
9. **PRE-B-002** (decision) — Stop three screens promising what they do not do
10. **PRE-B-013** (decision) — Look at which tier the Gemini and Groq keys are on
11. **PRE-C-006** (you) — Check the website's support and onboarding promises are staffed
20. **PRE-A-011** (Claude) — Fix invoice and bill importers accepting rows the server refuses
22. **PRE-A-016** (Claude) — Fix on-screen printing: /reports prints blank, others unstyled
23. **PRE-A-018** (Claude) — Link Practice Billing and AR to the practice client's invoices
24. **PRE-A-006** (Claude) — Name the AI provider on the extract and scan screens
25. **PRE-C-004** (you) — Redeploy the latest main on Render and record how it deploys
27. **PRE-A-015** (Claude) — Drive the money editors in a browser: double-click guard, keyboard, drafts, dates
28. **PRE-A-001** (Claude) — Drive the upload screens in a browser: GSTR-2B and the bulk imports
29. **PRE-B-006** (live) — Rehearse sign-up and first Partner sign-in as a stranger would
30. **PRE-B-014** (live) — Press Check now on Settings > AI status for Groq and Gemini
31. **PRE-B-001** (live) — Seed the demo firm with seed_demo_firm.py --confirm and walk it
32. **PRE-B-003** (live) — Check the seeded and a fresh firm can raise a first invoice
33. **PRE-A-004** (Claude) — Run the seeded firm through GST, year-end and ITR; fill empty screens
34. **PRE-B-008** (live) — Rehearse the critical spine on the seeded firm with the console open
35. **PRE-B-007** (live) — Rehearse the core UAT scenarios on the demo firm
36. **PRE-B-009** (live) — Test the client and employee portals end to end
37. **PRE-B-010** (live) — Verification A: check six outputs against one real client's filed figures
38. **PRE-B-011** (live) — Verification B: print the outgoing documents and read them on paper
39. **PRE-A-002** (Claude) — Fix whatever the rehearsals and walks turn up
40. **PRE-C-005** (you) — Wake the API two minutes before the demo; keep a tab open

## The after-demo items marked high priority

- **POST-A-004** (claude) — Hash the year-lock PIN and restrict reading it
- **POST-A-005** (claude) — Make the per-person permission grid reach reads in the database
- **POST-A-108** (claude) — Year-end policy note says moving average even for FIFO clients
- **POST-B-004** (owner-decides) — Decide who may read payroll in the database; add role tiers
- **POST-B-005** (owner-decides) — Stop Reviewer writes on 41 tables the API gives no write resource
- **POST-B-047** (owner-decides) — Open statutory sources to Claude: allowlist .gov.in hosts or hand-fetch
- **POST-B-091** (owner-decides) — Attribute each invoice, bill and note to a GST registration
- **POST-B-132** (owner-decides) — Decide whether to build the TDS RPU/FVU statement file writer
- **POST-B-193** (owner-decides) — Choose surviving fee-billing engine; retire fee_invoices readers
- **POST-B-247** (owner-decides) — After the CA demo: reverse 'no registrations' decision and start wave 0
- **POST-B-259** (owner-decides) — Publish a real Privacy Notice and Terms of Service; footer links dead-end
- **POST-B-295** (owner-decides) — Decide the Tally import rules (decision 8) before building ledger import
- **POST-B-321** (owner-decides) — Make practice profitability true: cost definition, status filter, unbilled clients
- **POST-C-072** (owner-only) — Verify FY 2026-27 statutory figures and promote LATEST_VERIFIED_FY
- **POST-C-120** (owner-only) — Check ECR EPF-contribution-remitted convention against a real EPFO sample
- **POST-C-121** (owner-only) — Confirm Labour Code PF 50% wage-base reading and ceiling notifications
- **POST-C-193** (owner-only) — Engage counsel for data incidents and DPDP opinions

## Counts by theme

| theme | pre | post |
|---|---|---|
| demo-and-onboarding | 16 | 8 |
| security-access-rls | 0 | 68 |
| platform-ops-ci-deploy | 6 | 71 |
| ai | 3 | 23 |
| gst-returns | 2 | 66 |
| gst-einvoice-eway | 0 | 19 |
| income-tax-itr | 1 | 58 |
| tds-tcs | 0 | 31 |
| payroll-statutory | 0 | 63 |
| accounting-gl-reporting | 0 | 37 |
| sales-purchase-docs | 2 | 32 |
| inventory-fixed-assets | 0 | 24 |
| banking | 1 | 30 |
| filing-integrations-registrations | 2 | 38 |
| marketing-commercial-legal | 2 | 29 |
| frontend-ux | 4 | 56 |
| schema-data-migrations | 0 | 31 |
| dependencies | 0 | 7 |
| docs-hygiene | 0 | 27 |
| other | 0 | 31 |

## Things in the repository that are known to be stale or wrong (so nobody trusts them)

Each has its own line in the ledger (search `docs-hygiene`) or is a fact the earlier sweeps recorded; this is the short list. `docs/schema-drift.md`'s tally and the production-guards snapshot (migration 381, against 479 in the repo) are out of date. `apps/api/domain/tds/vocabulary.py` holds payment codes 1001–1067 where docs/compliance/07 and 08 report that research found 1001–1092 (both now say it is unverified either way). The Protean file-format spreadsheet, the Form 3CD source and the ESIC manual that the code cites as primary sources are not committed in `docs/compliance/sources/` (POST-C-199). The CLAUDE.md, architecture and compliance documents were brought in step with the code on 8 October 2026 (the GST, income-tax, payroll, reporting, bank and multi-currency design records, the late-fee and IFF sentences, the smoke-walk paragraphs); a new stale sentence is found by the guards each of those documents now has, or by reading.

## How this ledger was built, and what it cannot tell you

Twenty-eight read-only passes extracted every still-open item from CLAUDE.md (read in four parts), every file under `docs/audits/`, `docs/plan/`, `docs/compliance/`, `docs/operations/` and `docs/architecture/`, the top-level `docs/*.md`, the code's own markers and render.yaml, and the 337-point improvement roadmap of 30 Sep 2026 — which existed only in session data and is now captured here (195 points were Claude's alone and are mostly built; the other 142 need the owner or someone outside, and the roughly 60 of the 195 still unbuilt are included). That gave 1,306 raw items; fourteen group passes and two cross-group passes merged them to 788 with every raw item accounted for by a script. Each reader re-checked its items against the code on 2 Oct 2026 and recorded what it found already done in `checked-closed.md`.

**Second pass, 8 October 2026.** After the ledger was committed, the before-demo items and the high-priority after-demo items were each re-read against the code (files, functions, columns, routes, env vars, the matrix classes, the Actions API for CI state, the repository's own grep results) by one session and no sub-agents. 64 items were checked; 5 needed their text corrected (the fixes are in the lines), the rest held, and the who/when buckets of all 64 stood. Two facts for planning that this pass produced: the nightly smoke walk was red only because axe-baseline entries no longer fired (the baseline was shrunk on 8 October 2026 and the walk dispatched green), and the documents-upload defect was real (closed by migration 479 on 8 October 2026).

Limits: **nothing was exercised against production** except one read-only query (it confirmed the documents-upload defect); dashboard state is unreadable from here, hence UNSURE; nothing was clicked in a browser; about 30 statutory readings are graded `[S]` (a search summary, not the primary text) and need a person with a browser; the pre-demo list is Claude's judgement of the demo's needs; and effort figures are estimates. Source references point at documents that were deleted on 8 October 2026 — recover them with `git show 315e6a19:<path>` (see `deletion-plan.md`).

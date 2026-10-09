# Plan — going faster (decided 9 October 2026, IST)

> **Planning only. Nothing in this plan has been built.** The owner decided on 9 October 2026 that building
> starts when the weekly credits refresh, and that this session only plans. The decisions below are the
> owner's answers that day. A snapshot like the checkpoint note beside it: read the code before acting.

## 1. Why 761 is not 761 jobs

| Bucket | Items | What it is |
|---|---|---|
| Claude alone (`A`) | 201 | 51 hours-sized, 101 days-sized, 42 weeks, 6 months, 1 unsized. Many are one change repeated: 111 date fields, 103 raw buttons, 102 accessibility findings, 80 empty states, 7 dependency bumps. |
| Owner decides, then Claude builds (`B`) | 351 | **200 of these are themselves a question to the owner** ("Decide whether…"): 4 high, 67 normal, 129 low priority. Nothing behind them can start until they are answered. |
| Owner or outsiders only (`C`) | 209 | Dashboard checks, registrations, "watch for" items; 116 are hours-sized. |

The slow part is the 200 decisions, not the building. The plan therefore starts with them.

## 2. Rules decided on 9 October 2026

1. **Batch size.** One theme per pull request. Hours-sized items go ten to a PR; days-sized items four to a PR;
   weeks- and months-sized items one to a PR; a repeated mechanical sweep is one rule per PR.
2. **Flow.** Up to **three** pull requests open at once, merged **one at a time**, each only when both required
   checks are green and it is current with `main`. This replaces the earlier strict one-at-a-time rule. Every other
   standing rule is unchanged: IST in everything said to the owner, no secrets or personal addresses in the repo,
   no tags pushed, no pull request closed and no file deleted without the owner's go-ahead, a migration numbered
   against `origin/main`.
3. **Pace.** Steady: one batch built at a time, the next prepared while the checks of the last run. Not parallel.
4. **Decisions** are taken as **decision sheets, accept-all style** (section 3).
5. **A parked list** with its own count (section 4), so the number the owner tracks is the real queue.
6. **Staleness.** Before each batch, confirm every item in it is still true against the code and close any that
   are already done or moot. No separate sweep of all 761 (it would cost a lot of credits).
7. **The three held clean-up items** were left to Claude's judgement ("do as you think better"):
   - **POST-A-193** (stale agent worktrees in the local checkout): do it, last in a session, only for worktrees whose
     branch is merged or pushed. They are local directories, not repository files.
   - **POST-A-185** (delete four superseded roll-up endpoints): do it inside an ordinary batch, after confirming by
     search that no screen and no test calls them.
   - **POST-A-191** (reorganise the flat test directory, rename ticket-id test files): do it **last, alone, with no other
     pull request open**, because renaming test files conflicts with every other open branch.
8. **Order of work** was not chosen (the owner said planning only). Default when work resumes: the small statutory
   and security fixes first (they touch money and access), then the frontend sweeps, then dependencies and tooling,
   then the big features one at a time. The owner may reorder.

## 3. Step 0 when credits refresh: the decision sheets

Read all 200 decision lines (the `B` items whose title starts "Decide", "Choose", "Confirm", "Settle", "Approve"…).
Write about twelve sheets under `docs/open-items/decisions/`, one per theme, each decision as: the question in one
line, **Claude's recommended answer**, one line of reason, and what it unblocks. Order within a sheet: high, then normal,
then low. For the 129 low-priority decisions the default recommendation is **decline or park unless the owner objects**.
The owner replies "accept all" or lists exceptions. An accepted decision turns its `B` line into an `A` line (or closes it).

Decision lines by theme: security 28, payroll 18, accounting 18, sales/purchase 18, platform/ops 17, frontend 16,
income tax 13, AI 10, filing/registrations 10, TDS 9, marketing/legal 9, inventory 6, other 6, GST 5, banking 5,
schema 4, e-invoice 3, docs 3, demo 2.

## 4. Step 1: the parked list

**Rule:** an item is parked if it is low priority and sized weeks or months, or its title starts "Watch for", "Hold" or
"Keep". A pre-demo item is never parked. By that rule **114 items** qualify (74 in `POST-B`, 24 in `POST-A`, 16 in `POST-C`).
Parked items move to `docs/open-items/parked.md` with their ids unchanged; the README shows both counts (open and parked).
This needs the ledger guard (`tests/test_the_open_items_ledger_is_well_formed.py`) and `scripts/open_items_counts.py` taught
about the new file in the same pull request. It does no work itself; it makes the headline number mean the real queue.

## 5. Step 2: the batches for Claude-alone items

Chunked by the rule in section 2: **18 hours-sized batches**, **33 days-sized batches** and **49 solo items** (weeks, months, one unsized).
Code pull requests wait about 27 minutes for the required checks (the migration check dominates); a docs-only one passes in
under a minute. With three open at once, the 51 batched pull requests are roughly 9 to 10 hours of waiting, so building is the bottleneck.

| Batch | Theme | Size | Items |
|---|---|---|---|
| B1 | accounting-gl-reporting | hours | 094 |
| B2 | accounting-gl-reporting | days | 089, 091, 092, 093 |
| B3 | accounting-gl-reporting | days | 096, 097 |
| B4 | ai | hours | 048 |
| B5 | ai | days | 047, 052, 053, 054 |
| B6 | banking | hours | 116 |
| B7 | banking | days | 117 |
| B8 | demo-and-onboarding | hours | 002 |
| B9 | demo-and-onboarding | days | pre002, pre004, 003 |
| B10 | dependencies | hours | 175, 176 |
| B11 | dependencies | days | 171, 172, 173, 174 |
| B12 | docs-hygiene | hours | 185, 193 |
| B13 | docs-hygiene | days | 191 |
| B14 | filing-integrations-registrations | hours | 118 |
| B15 | frontend-ux | hours | 129, 137, 146, 148, 150, 151, 154, 156, 160, 218 |
| B16 | frontend-ux | days | pre015, 125, 126, 128 |
| B17 | frontend-ux | days | 131, 132, 134, 135 |
| B18 | frontend-ux | days | 136, 140, 141, 142 |
| B19 | frontend-ux | days | 145, 147, 149, 152 |
| B20 | frontend-ux | days | 155, 158, 159, 161 |
| B21 | frontend-ux | days | 217 |
| B22 | gst-einvoice-eway | hours | 065 |
| B23 | gst-einvoice-eway | days | 066, 067 |
| B24 | gst-returns | days | 055, 056, 057, 058 |
| B25 | gst-returns | days | 059, 060, 061, 062 |
| B26 | gst-returns | days | 063, 064 |
| B27 | income-tax-itr | hours | 072, 077 |
| B28 | income-tax-itr | days | 071, 073, 074, 075 |
| B29 | inventory-fixed-assets | days | 109, 110, 111, 112 |
| B30 | inventory-fixed-assets | days | 113, 114, 115 |
| B31 | marketing-commercial-legal | hours | 120, 122 |
| B32 | marketing-commercial-legal | days | 119, 121 |
| B33 | other | hours | 208, 209, 210, 211 |
| B34 | other | days | 215, 216, 198, 212 |
| B35 | payroll-statutory | hours | 085, 087, 088 |
| B36 | platform-ops-ci-deploy | hours | 024, 025, 036, 041, 042, 044 |
| B37 | platform-ops-ci-deploy | days | 022, 026, 027, 028 |
| B38 | platform-ops-ci-deploy | days | 029, 030, 034, 037 |
| B39 | platform-ops-ci-deploy | days | 038, 045 |
| B40 | sales-purchase-docs | hours | 098, 102, 103, 107, 214 |
| B41 | sales-purchase-docs | days | 099, 100, 101, 104 |
| B42 | sales-purchase-docs | days | 105, 106 |
| B43 | schema-data-migrations | hours | 165, 170 |
| B44 | schema-data-migrations | days | 163, 164, 166, 167 |
| B45 | schema-data-migrations | days | 168, 169 |
| B46 | security-access-rls | hours | 013, 014, 015, 020 |
| B47 | security-access-rls | days | 005, 006, 007, 009 |
| B48 | security-access-rls | days | 011, 012, 016, 017 |
| B49 | security-access-rls | days | 018 |
| B50 | tds-tcs | hours | 079, 080, 081 |
| B51 | tds-tcs | days | 078 |

Item numbers are `POST-A-nnn` (`pre015` is `PRE-A-015`). The solo items, one pull request each:

| Item | Theme | Size | What |
|---|---|---|---|
| POST-A-090 | accounting-gl-reporting | weeks | Build remaining ledger-grounded exceptions and stored nightly… |
| POST-A-095 | accounting-gl-reporting | weeks | Make foreign-currency receipts atomic like plain INR receipts |
| POST-A-049 | ai | weeks | Notice intake from a file, rule-derived due date, reply draft… |
| POST-A-050 | ai | weeks | Store results for the four engines the morning digest cannot… |
| POST-A-051 | ai | weeks | AI steps inside workflow automation, each ending in an approv… |
| POST-A-001 | demo-and-onboarding | weeks | Add help menu, per-screen help links and checklist 'dismiss f… |
| POST-A-213 | dependencies | weeks | Plan the held-back major migrations: Next 16, Tailwind 4, Typ… |
| POST-A-123 | frontend-ux | weeks | Add a browser test tier with double-click tests for money scr… |
| POST-A-124 | frontend-ux | weeks | Add a shared stale-while-revalidate read cache for idempotent… |
| POST-A-127 | frontend-ux | weeks | Enforce a programmatic name on every form control (AST rule) |
| POST-A-130 | frontend-ux | weeks | Make every overlay a real dialog and give Drawer a Tab trap |
| POST-A-133 | frontend-ux | weeks | Split the oversized pages and load inactive tabs on demand |
| POST-A-138 | frontend-ux | weeks | Adopt the Input, Select, Textarea and Field primitives with a… |
| POST-A-139 | frontend-ux | weeks | Build a global keyboard layer: chords, voucher hotkeys, Ctrl+… |
| POST-A-144 | frontend-ux | weeks | Convert or analyse the 103 frozen raw async-writing buttons |
| POST-A-153 | frontend-ux | weeks | Move hand-built tables onto DataTable |
| POST-A-157 | frontend-ux | weeks | Several list screens still lack search, sort or pagination |
| POST-A-143 | frontend-ux | months | Continue the named-palette judgement pass, one module per PR… |
| POST-A-162 | frontend-ux | months | Work down the 218 mounted endpoints that reach no screen |
| POST-A-068 | income-tax-itr | weeks | Build the filing-season workflow for hundreds of ITR returns |
| POST-A-069 | income-tax-itr | weeks | Derive Form 3CD clauses 33 and 40 from existing engines |
| POST-A-076 | income-tax-itr | weeks | Build a printable Form 3CD report (PDF or CSV export) |
| POST-A-070 | income-tax-itr | months | Fill ITR-3/5/6 balance sheet, P&L and depreciation schedules… |
| POST-A-199 | other | weeks | Add task checklists, comments with mentions, attachments and… |
| POST-A-200 | other | weeks | Build a workflow builder screen and seed the CA starter templ… |
| POST-A-201 | other | weeks | Client-facing proposals with price acceptance that start the… |
| POST-A-202 | other | weeks | Generalise client e-acceptance from engagement letters to any… |
| POST-A-203 | other | weeks | Give documents folders, versions and open-ended types |
| POST-A-204 | other | weeks | Make workflow triggers fire, delays wait, add email and docum… |
| POST-A-205 | other | weeks | Offer a whole-firm data export in open formats |
| POST-A-206 | other | weeks | Turn each compliance obligation into staged work on the prepa… |
| POST-A-207 | other | weeks | Client organizers and questionnaires for data collection |
| POST-A-082 | payroll-statutory | weeks | Build payroll opening positions for clients who join mid-year |
| POST-A-083 | payroll-statutory | weeks | Give payroll ledger accounts a key and one client-scoped reso… |
| POST-A-084 | payroll-statutory | weeks | Take previous-employer salary and TDS (Form 12B) into s.192 e… |
| POST-A-086 | payroll-statutory | weeks | Let a client define custom earning and deduction heads with f… |
| POST-A-021 | platform-ops-ci-deploy | weeks | Stop swallowing exceptions on money and ledger paths |
| POST-A-023 | platform-ops-ci-deploy | weeks | Add the declined column-level 'read but never written' guard |
| POST-A-031 | platform-ops-ci-deploy | weeks | Decompose the 14 functions over 300 lines behind golden tests |
| POST-A-032 | platform-ops-ci-deploy | weeks | Enforce domain/services/routers layering with an import contr… |
| POST-A-033 | platform-ops-ci-deploy | weeks | Give the API a typed contract and one refusal semantics |
| POST-A-035 | platform-ops-ci-deploy | weeks | Introduce mypy or pyright on domain/ and core/, then ratchet |
| POST-A-040 | platform-ops-ci-deploy | weeks | One faithful database test double and a real-PostgREST test t… |
| POST-A-039 | platform-ops-ci-deploy | months | Move business logic out of the routers into services, payroll… |
| POST-A-043 | platform-ops-ci-deploy | months | Remove the parallel in-memory mock implementation from produc… |
| POST-A-046 | platform-ops-ci-deploy | ? | Work the shrink-only baselines down: current measured sizes |
| POST-A-008 | security-access-rls | weeks | Extend the RLS role-by-table matrix beyond the 89 browser tab… |
| POST-A-019 | security-access-rls | weeks | Tighten the firm-scope query guard so it cannot be fooled |
| POST-A-010 | security-access-rls | months | Shrink the browser-direct database surface for sensitive tabl… |

## 6. What the owner can do meanwhile (no credits)

The 6 `PRE-C` and 14 `PRE-B` items in the README's ordered checklist, and the human steps in section 6 of
`checkpoint-2026-10-09.md` (Razorpay, the domain and sending address, the dashboard checks, the privacy-page contact).
Each answered decision or finished step shortens the queue before work resumes.

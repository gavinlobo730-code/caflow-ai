# PracticeSync — Founding Executive Product Audit

**Date:** 2026-07-02
**Scope:** Full-platform review (architecture, correctness, accounting integrity, security, performance, UX, CA productivity, competitive position, innovation)
**Method:** 14 parallel subsystem readers built a complete architecture model; 22 launch-blocker findings were then adversarially verified (each verifier instructed to *refute*); 6 findings additionally re-verified by hand. Every claim below carries `file:line` evidence.
**Reviewer role:** Founding CPO / Principal Architect / Principal QA / UX Director / Enterprise Security Reviewer / Senior CA consultant.

> **This is a review deliverable. No production code was modified. Implementation awaits your approval and will proceed in the priority order set out in the roadmap.**

---

## 1. Overall assessment & the launch verdict

PracticeSync is an **ambitious, unusually complete-looking** platform: ~673 API endpoints across 95 routers, ~161 frontend routes, 175 SQL migrations, a genuine double-entry general ledger in integer paise, a live recompute-on-demand reporting engine, and real Indian statutory engines for GST, TDS and ITR. The *surface area* rivals commercial suites. The **depth is uneven**: a strong core is surrounded by modules that are partially wired, schema-broken in the real database configuration, or shipped but unreachable.

The audit verified a cluster of defects that sit directly on the money path and the multi-client path — the two things a CA firm cannot tolerate being wrong.

> ### Would I confidently launch PracticeSync today?
> **No.** Not for paying CA firms managing real client money and statutory filings.
>
> The product is a strong **private-beta / design-partner** candidate, but it has **launch-blocking defects in core accounting, multi-client invoicing, payroll, GST output, and year-end** that will produce wrong numbers or hard failures on ordinary use — plus a structural tenant-isolation posture with no database backstop. These are fixable, and most are small, localized fixes. With the Critical tier of the roadmap closed and verified against a real database, PracticeSync becomes launchable to a controlled cohort.

**Production readiness: 38 / 100** (see §10). **Recommendation: do not GA. Close the Critical tier, stand up real-DB CI, then pilot with 3–5 design-partner firms under supervision.**

---

## 2. Architecture — strengths and weaknesses

### The architecture in one paragraph
Next.js 14 **static export** on Cloudflare Pages (no SSR, no middleware, **no server-side route protection**) + FastAPI on Render + a single hosted Supabase Postgres. Persistence is **dual-mode**, switched at import time by `_USE_MOCK = not os.environ.get("SUPABASE_URL")` across 60+ modules; production has the var set, so production is real-Postgres-backed. Schema is defined **only** by 175 hand-applied migrations in `apps/api/migrations/` — there is no migration runner and no tracking table. The backend uses the Supabase **service-role** client, which **bypasses RLS**; the per-user-JWT/RLS path exists but is behind a **dark `USE_USER_JWT` flag** (`core/security_config.py:24`, absent from `render.yaml`). The browser talks to **two data planes** — the FastAPI backend *and* Supabase directly via anon key (**368 call-sites across 103 files**), so roughly half the product bypasses backend auth/audit and relies on RLS alone.

### Strengths
- **A single posting kernel.** Every workflow (invoices, receipts, bills, payroll, bank, assets, opening balances, manual journals, reversals) posts through `Phase2JournalService._create_journal` — integer paise, XOR debit/credit CHECK, balance enforced, posted-journal immutability triggers, linked reversals. This is the right design.
- **A production-grade live reporting engine.** `domain/reporting/*` recomputes TB / P&L / Balance Sheet / AS-3 cash flow / Schedule III on demand from posted `journal_lines` (firm+client scoped, `deleted_at IS NULL`, paged past the 1000-row PostgREST cap). Clean, tested, cumulative-vs-window aware.
- **A well-factored shared design system.** `components/ui/data-table.tsx`, `combobox.tsx`, `states.tsx`, `skeleton.tsx` are accessible, keyboard-aware, and unit-tested.
- **A genuinely good acquisition flow.** Lead → engagement letter → public e-sign → convert-to-client → onboarding is coherent and differentiated.
- **Security intent is real.** `SECURITY.md` documents the isolation model honestly; RLS-hardening migrations, append-only audit triggers, and firm-scoped repository guards exist.
- **Automation runs in production.** `render.yaml:27` sets `ENABLE_SCHEDULER=true`, so the compliance-obligation generator and reminders do fire (correcting an early assumption).

### Weaknesses (root causes of most findings)
1. **No database backstop for tenancy.** Service-role bypasses RLS and `authz.can_access_client()` returns `True` for any `client_id` for a firm-wide (Partner) role without a firm-membership check (`core/authz.py:113-121`). Isolation is *entirely* "every handler remembered `.eq("firm_id")`." Several handlers forget.
2. **No transactions.** supabase-py/PostgREST has no multi-statement transaction; multi-write flows (journal header+lines, receipt→AR→journal, payroll, imports) are sequences of independent commits with ad-hoc or absent compensation.
3. **Schema drift and phantom tables.** No migration runner; duplicate migration numbers; ~13 tables the code uses have no `CREATE TABLE`; confirmed repo-vs-live trigger drift.
4. **A second, divergent business-logic plane in the browser.** Journal posting, GST return building, payroll tax, health scoring, and compliance-calendar generation run client-side — violating "zero business logic in the frontend" and evading the "every financial calc has a unit test" rule.
5. **Mock branches leak into production.** A few endpoints ignore the flag and always serve in-memory data even with `SUPABASE_URL` set.
6. **Scope far beyond the stated phase.** `CLAUDE.md` says "MVP Phase 1 only"; the code is at Phase 14 + multi-currency 1–5 + payments + platform console. ~40 routes / ~9,000 lines are orphaned from navigation.

---

## 3. Verified bug list (launch blockers)

Severity is **post-verification** (independent re-assessment, which downgraded several claims). "Prod-reachable" = manifests in the real config (`SUPABASE_URL` set, service-role, `USE_USER_JWT` off).

| # | Severity | Area | Defect | Verdict | Evidence |
|---|----------|------|--------|---------|----------|
| F6 | **Critical** | Invoicing | Invoice number is per-(firm,client) but UNIQUE is per-firm → a firm's **2nd client can never invoice** (retries 6× then 500) | Confirmed | `routers/sales_invoices.py:64-77`; `migrations/050:36`; `services/numbering.py:34-45` |
| F13 | **Critical** | Payroll | Finalization posts an **unbalanced journal** (omits employer PF/ESI debit) → 500 on essentially every real run | Confirmed | `services/phase2_journal_service.py:568-598,955-961`; `routers/payroll.py:302-303` |
| F15 | **Critical** | Payroll | Frontend TDS thresholds compare paise against rupee-scale constants → **massive over-deduction**, persisted to `payroll_slips` | Confirmed | `apps/web/app/payroll/page.tsx:141-154,924-945` |
| F8 | **Critical** | Banking | Axis statements misrouted to HDFC adapter → **₹500 debit becomes ₹10,000 credit** (reproduced live) | Confirmed (SBI half overstated: SBI loses only the description) | `domain/banking/normalizer.py:54-66` |
| F2 | High | Accounting | Non-atomic journal (header then lines, no txn) → **orphan posted entry**, immutable, dedup returns it forever | Confirmed | `services/phase2_journal_service.py:1049,1087,1051-1058` |
| F7 | High | Accounting | Non-atomic receipt (AR settled before journal; journal errors swallowed) → **settled AR with no GL entry** | Confirmed | `services/receipt_service.py:326-389`; generic exception swallowed at `journal_for_receipt` |
| F16 | High | GST | GSTR-3B GSTN payload emits **raw paise (100× too large)** while GSTR-1 converts correctly; labeled "ready for upload" | Confirmed | `domain/gst/gstr3b_computer.py:86-152` vs `gstr1_builder.py:68-73` |
| F18 | High | ITR | ₹75k standard deduction wrongly applied in **old** regime; no 87A marginal relief (tax cliff at ₹12,00,001); no surcharge marginal relief / 15% CG cap; frontend re-implements slabs 10× wrong | Confirmed | `domain/income_tax/itr_engine.py:38-39,203-205,295-304`; `apps/web/app/income-tax/deductions/page.tsx:117-166` |
| F17 | High | TDS | Stale statutory thresholds; annual-aggregate thresholds applied **per-payment** → under-deduction; hardcoded FY; invalid Q4 due date | Confirmed (minor date detail imprecise) | `domain/tds/tds_computer.py:89-145`; `routers/tds_workspace.py:41-48,301` |
| F9 | High | Year-end | Entire year-end workflow targets tables/columns **no migration creates** → every write 500s in DB mode | Confirmed | `migrations/067` vs `routers/year_end_*.py`; `services/year_end_financial_service.py:206` |
| F10 | High | Year-end | Year-end Balance Sheet aggregates **only FY-window** lines → drops prior-year carry-forward for multi-year clients | Confirmed | `services/year_end_financial_service.py:174-198` |
| F5 | High | Data | ~13 tax/compliance tables have **no CREATE TABLE** (e-invoice, e-way, XBRL, ITR filings, 26AS records…) → 500 in prod | Confirmed | grep `apps/api/migrations/*.sql`; `domain/income_tax/einvoice_service.py:115` etc. |
| F3 | High | Accounting | CoA admin + journal-list endpoints serve **in-memory mock unconditionally** even in prod; all firms share one list | Confirmed (nuance: `POST /journal` is real) | `routers/accounting.py:45-81` |
| F11 | High | Workflows | Phase-10 workflow list endpoints **404** (legacy `/{id}` route shadows `/templates`, `/instances`, …) | Confirmed | `main.py:174` vs `256`; `routers/workflows.py:19-24` |
| F12 | High | Workflows | Phase-10 workflow engine actions are **stubs** (fabricate ids, mutate nothing); analytics report success | Confirmed | `domain/workflow_engine_v2.py:502-544` |
| F14 | High | Frontend | Core accounting/tax **logic + writes in the browser** → user can post unbalanced/backdated journals via direct PostgREST | Confirmed (RLS *does* apply here → integrity issue within firm, not cross-tenant) | `apps/web/app/clients/[id]/accounting/page.tsx:616-640`; `lib/data/gst.ts` |
| F21 | High | Security | `/join?firm=<uuid>&role=Partner` lets the browser insert a `users` row with URL-controlled firm/role; **users-table RLS does not block it** | Confirmed (understated) | `apps/web/app/join/page.tsx:12-62` |
| F1 | High | Security | Tenant isolation is app-layer discipline only; **no DB backstop** — one forgotten `firm_id` filter = silent cross-firm leak | Partially confirmed (structural fragility, not a demonstrated live leak; only Partner is firm-wide, not Manager) | `core/authz.py:42,113-121`; `SECURITY.md:58-60` |
| F4 | High | Security | GSTR-9 save/get not firm-scoped → cross-tenant read/overwrite of annual returns | Confirmed | `routers/gst_workspace.py:538-545,590-598` |
| F22 | High | Security | Portal invites have **no token/expiry**; bind on first email match → recycled/typo'd email grants a stranger a client's data | Partially confirmed | `services/portal_access_service.py:80-156` |
| F19 | High | AI | `groq` **not in `requirements.txt`** → document AI silently returns fabricated data with a key set; v2 persists a fake notice+task; copilot chat 500s on an undefined RPC | Partially confirmed (`pdfminer` is present transitively) | `requirements.txt`; `routers/document_intelligence_v1.py:104-190`; `repositories/ai_copilot_repository.py:216-226` |
| F20 | Medium | Security | RLS policies on 059/067/071 key on a `firm_id` JWT claim never issued (deny-all) — **moot today** (service-role bypasses RLS); migration 127's "now in production" comment is false | Partially confirmed (downgraded) | `migrations/071_rls_policies.sql:33`; `127:14-15` |

**Verification scorecard:** of 22 launch-blocker candidates — **0 refuted**, 14 confirmed as-described, 8 partially confirmed (severity/scope refined). The audit's core findings are sound; the adversarial pass corrected severity inflation on 5 and caught 3 factual slips (Manager-not-firm-wide, SBI-not-money-corruption, pdfminer-present).

---

## 4. Accounting & tax correctness risks (the CA's core trust)

This is where a CA's confidence is won or lost, and where PracticeSync is weakest relative to its ambition.

- **Multi-client invoicing is broken (F6).** For a firm with more than one bookkeeping client, only the first client can issue invoices in a given FY-number space. This is not an edge case — it is the *headline* use case for a firm with 100–500 clients.
- **Payroll cannot close (F13).** The finalization journal is unbalanced by exactly the employer PF+ESI, so it throws for any employee with the default statutory contributions.
- **GST output is 100× wrong (F16).** The GSTR-3B payload the UI calls "ready for GSTN upload" carries paise in rupee fields. A diligent CA would likely notice ₹ figures inflated 100×, but the tool is asserting correctness it doesn't have.
- **Payroll & ITR tax math is statutorily wrong (F15, F18).** Over-deducting salary TDS (frontend), ₹75k standard deduction in the old regime, no §87A marginal relief (a hard cliff at ₹12,00,001), no surcharge marginal relief. Each produces a demonstrably wrong number for a real taxpayer.
- **Non-atomic money writes (F2, F7).** Journals and receipts can leave the sub-ledger and GL out of sync with no rollback and, on one path, no surfaced error. In a double-entry system this is the cardinal sin.
- **Year-end is non-functional in the real DB (F9, F10).** Statutory financial statements either 500 outright or silently drop prior-year balances.
- **Fragile account resolution.** Post-098 firms lack `system_account_key`, so control accounts resolve by ILIKE name match, and CGST/SGST/IGST can collapse into a single "%GST Output%" account — a silent misclassification.
- **Plaintext year-lock PIN**, compared with no rate limiting (`services/year_lock_service.py:63-79`).

**Domain-rule compliance (CLAUDE.md):** integer paise is respected in the backend kernel (good) but violated in the browser payroll path; the "never auto-submit" rule is genuinely honored (record-keeping only, `# CA REVIEW REQUIRED` markers present); the "every financial calc has a unit test" rule is **not** met for the browser-side calcs or for the real-DB paths (CI never touches a DB).

---

## 5. Security & tenancy

- **The structural risk (F1).** With RLS dormant for API traffic, the only thing standing between firms is app-layer `.eq("firm_id")` discipline. Verified holes today: GSTR-9 (F4), payroll finalize/status, year-end checklist/mappings, timeline & copilot context builders, task tags/deps/timeline, time-entry edit/delete. Each requires a foreign client UUID, so blast radius is real but not trivially discoverable — hence **High, not a demonstrated Critical breach**. The right fix is a **DB-level backstop**, not more manual filters.
- **Privilege escalation via `/join` (F21).** The browser self-inserts its `users` row with firm/role from the URL; users-table RLS does not prevent it. This is the most acutely exploitable security finding.
- **Tokenless portal invites (F22).** First-login email match with no expiry.
- **Static export = client-side-only route protection.** Every staff bundle ships to any visitor; `/platform` is a public path inside the staff shell. Data protection rests entirely on API auth + RLS.
- **JWT laxity:** `verify_aud=False`, no issuer pin, HS256 accepted alongside JWKS (`core/auth.py:74-80`).
- **AI abuse surface:** rate limiting declared for 3 prefixes but enforced at exactly one endpoint; client-supplied message roles passed verbatim (system-prompt injection); an unauthenticated Next.js `/api/ai-assistant` edge route spends the server Groq key (though it can't ship under static export).

---

## 6. Data layer, performance & scalability

- **No migration runner / tracking table**; migrations applied by hand; duplicate numbers (045/046/094–097); confirmed drift (line-immutability trigger present in migration 055, absent in live DB).
- **No transactions** anywhere multi-write correctness matters.
- **Unbounded fetch-all + Python-side aggregation** on financial reads (revenue rollups, time analytics, full-FY journal pulls, `count = len(find_all())`) — fine at demo scale, a wall at 100–500 clients × years of journals.
- **Per-request auth cost:** 2–3 uncached service-role lookups on every authenticated request.
- **Frontend:** 368 direct browser→Supabase calls; the good `selectAll` pager exists but isn't used everywhere; two skeleton systems; only ~17 of 161 pages use the shared primitives.
- **Dead schema still referenced in docs:** `ledger_balances` is never read; balances are always recomputed.

At the target scale (thousands of firms, millions of rows) the recompute-everything reporting model and fetch-all aggregations are the first bottlenecks; the missing indexes and per-request auth lookups are the second.

---

## 7. Product-surface & feature-gap analysis

- **~40 routes / ~9,000 lines orphaned from navigation** — the *entire firm-level GST/TDS/Income-Tax/MCA suite*, copilot, memory, workflows, time tracking, executive dashboard. Shipped, reachable only by typing the URL. This is simultaneously a discoverability failure and a signal of unfinished consolidation.
- **Duplicated stacks:** 3–4 parallel invoicing/billing systems (`/billing` fee_* vs `/practice/billing` schedules vs `/clients/[id]/sales` vs `/accounting/invoices`); two fixed-assets modules (one works, one calls an unauthenticated API); two payroll paths.
- **Demo-ware in production paths:** legacy document-intelligence, risk engine (`document_risks` table never written), Tally migration (broken import → 500), XBRL (imports a nonexistent symbol).
- **Governance drift:** `CLAUDE.md` "MVP Phase 1 only" vs Phase-14 reality; several docs actively misleading (sidebar proposal targets a deleted component; BETA_OPERATIONS says multi-currency is unimplemented after it shipped).

---

## 8. UX, CA productivity, benchmark & innovation

### UX (Phase 4) — top issues
- **Must fix:** load failures render as empty/zero on the primary dashboard (looks like "no data," not "error"); the firm-level tax suite is undiscoverable; no cross-client bulk anything; inconsistent/absent success-failure feedback with silent optimistic reverts; hand-rolled modals lack focus-trap/Escape/dialog semantics.
- **Should fix:** two skeleton systems and drifting empty/error UIs; overlapping nav surfaces; no shared client context across firm-level modules (constant re-selection); status-vocabulary/badge-color drift; GSTR-1 "Build" silently regresses approved/filed status.

### CA productivity (Phase 6) — the scale story
The engines are good per-client, but **everything is one-client-at-a-time**. For a firm at 100–500 clients the missing unlocks are, in order:
1. **Cross-client batch return generation** (the single biggest scale unlock — currently absent).
2. **Bulk mark-filed + ARN capture** on a real compliance cockpit.
3. **Fix the filing-correctness bugs** (F6/F13/F15/F16/F17/F18) — a wrong government filing causes tool abandonment.
4. **Automate document collection & deadline reminders** (today 100% manual — the biggest daily admin sink).
5. **Consolidate the fragmented compliance surface** into one cockpit and make the automation trustworthy unattended.

### Competitive position (Phase 7)
Indian firms run a four-layer stack (Tally/Busy/Zoho for books; ClearTax/Winman/Genius/CompuTax for GST & ITR; Karbon/TaxDome/CCH for practice management; WhatsApp for comms). PracticeSync's **differentiation is real** — a single AI-first platform with an integrated GL + compliance + client-memory. It **falls behind** on maturity, statutory accuracy, reliability, and the deliberately prepare-only posture (no GSP/ASP filing, broken Tally import). The opportunity is not to copy ClearTax's filing pipe but to be the **supervised, books-native compliance cockpit** none of the incumbents are.

### Innovation opportunities (Phase 8)
- **Must Have:** statutory rules-as-data registry (FY-versioned) so tax law is data, not code; government-data *ingestion* (AA / GSP-pull) keeping submit CA-confirmed; reliable two-way Tally/Busy/Zoho import; make the AI core real (de-demo-ware extraction + copilot); cross-tenant & integrity hardening.
- **Should Have:** server-side persisted GST reconciliation; WhatsApp Business API + automated document-collection cadence; cross-client batch compliance + real partner cockpit; UDIN + DSC register + signing; unify the AI layer on one deterministic-then-narrate model.
- **Nice to Have:** natural-language practice query; AI-drafted notice responses (CA-approved); narrated MIS on the year-end engine; mobile/PWA companion; firm-wide anomaly insights.
- **Future Vision:** compliance autopilot with a human at the wheel; AA + GSP as a data spine for continuous close; RAG tax-law copilot with citations; DPDP-compliant consent vault as a selling feature.

---

## 9. Module quality scoring (Phase 9)

Scored 0–10 per dimension. **Prod-ready** is the gating column. Reasoning is condensed; full evidence is in §3–§8.

| Module | Func | UX | Perf | Scale | Sec | Acct | Maint | Ent | **Prod** | Note |
|--------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|------|
| Posting kernel (GL) | 8 | – | 6 | 6 | 6 | 7 | 7 | 6 | **6** | Right design; non-atomic writes (F2) + fragile CoA resolution |
| Live reporting engine | 8 | 7 | 6 | 6 | 6 | 8 | 8 | 7 | **7** | Best-built subsystem; recompute cost at scale |
| Sales/Purchase & AR/AP | 7 | 6 | 5 | 3 | 5 | 4 | 6 | 4 | **3** | F6 blocks 2nd client; F7 non-atomic; PDF misrepresents lines |
| Banking & reconciliation | 6 | 6 | 6 | 6 | 6 | 4 | 6 | 5 | **4** | F8 money corruption; draft-as-posted recon; created_by FK risk |
| GST engine | 7 | 6 | 6 | 4 | 5 | 4 | 6 | 4 | **4** | Good from-books build; F16 100× payload; F4 cross-tenant |
| TDS engine | 6 | 5 | 6 | 5 | 5 | 3 | 5 | 4 | **3** | F17 stale/incorrect thresholds; correct impl exists unused |
| Income Tax / ITR | 6 | 5 | 6 | 5 | 5 | 4 | 5 | 4 | **3** | F18 statutory errors; frontend 10× slab bug |
| Payroll | 5 | 5 | 5 | 4 | 4 | 2 | 4 | 3 | **2** | F13 can't close; F15 over-deducts; float math; missing firm_id |
| Year-end / statements / XBRL | 4 | 5 | 5 | 4 | 5 | 3 | 4 | 3 | **2** | F9 schema-broken in DB; F10 drops carry-forward; fabricated notes |
| Practice mgmt (tasks/compliance) | 6 | 6 | 5 | 5 | 5 | – | 5 | 4 | **4** | Obligations run; F11/F12 workflow engine broken; escalation dedup |
| AI & intelligence | 5 | 6 | 5 | 5 | 4 | – | 4 | 3 | **3** | F19 fabricated extraction; 4 overlapping generations; cross-firm prompt context |
| Client portal | 6 | 6 | 6 | 6 | 4 | – | 6 | 4 | **4** | F22 tokenless invites; CA-side write guard gap |
| Platform / Auth / Tenancy | 6 | – | 5 | 5 | 4 | – | 6 | 4 | **4** | F1 no DB backstop; F21 /join escalation; JWT laxity |
| Frontend platform & UX | 6 | 6 | 5 | 5 | 4 | – | 5 | 4 | **4** | Great primitives, low adoption; F14 logic-in-browser; static-export exposure |
| Data layer / migrations | 5 | – | 4 | 4 | 5 | – | 4 | 4 | **4** | No runner/tracking; F5 phantom tables; drift; no transactions |
| Testing / CI / quality | 4 | – | – | – | – | – | 4 | 3 | **3** | ~2,193 tests but CI never touches a DB; prod JWT path untested |

**Overall production readiness: 38 / 100** — a capable, coherent core dragged below the launch line by a concentrated set of correctness and integrity defects in exactly the modules a CA touches daily.

---

## 10. Prioritized implementation roadmap (Final Deliverable)

Each item: **Problem · Evidence · Root cause · Business/Technical impact · Priority · Dependencies · Effort · Rollout order · Risks · Benefit.** Effort in engineer-days (S≤2, M 3–5, L 6–10, XL >10).

### Tier 0 — Do first: make correctness provable (unblocks everything)

**R0.1 — Real-database CI + a transaction/atomicity harness.**
- *Problem:* CI never touches a database; all 43 DB tests skip; constraints/RLS/triggers/concurrency are continuously unproven.
- *Evidence:* `.github/workflows/backend-ci.yml:33-37`; `tests/test_postgres_integration.py:30-35`. *Root cause:* FakeDB-only test tier by design.
- *Impact:* Every fix below is unverifiable without this; it is why the F5/F9 schema breaks shipped. *Priority:* **Critical.** *Deps:* none. *Effort:* L. *Rollout:* first. *Risk:* CI slowdown (mitigate with an ephemeral Postgres service). *Benefit:* turns "looks fixed" into "proven fixed."

### Tier 1 — Critical (launch blockers on the money/multi-client path)

**R1.1 — Fix invoice/credit-note numbering for multi-client firms (F6).**
- *Root cause:* per-(firm,client) sequence vs per-firm UNIQUE. *Fix direction:* make the number space per-(firm,client) — either include a client discriminator in the number or change UNIQUE to `(firm_id, client_id, invoice_no)` (migration + backfill), and make `next_seq` and the constraint agree.
- *Impact:* Unblocks the core 100–500-client use case. *Priority:* Critical. *Deps:* R0.1. *Effort:* M. *Rollout:* 1. *Risk:* numbering-scheme change needs a data migration and CA-visible number continuity — coordinate. *Benefit:* the product becomes usable by any multi-client firm.

**R1.2 — Balance the payroll finalization journal (F13).**
- *Fix:* add the employer PF/ESI expense debits (or credit only employee shares) so debits==credits. *Impact:* payroll can close. *Priority:* Critical. *Deps:* R0.1. *Effort:* S. *Rollout:* 1. *Risk:* get the accounting treatment right (employer cost is an expense). *Benefit:* unblocks payroll; every financial calc gets a test (per CLAUDE.md).

**R1.3 — Move payroll & GST business logic off the browser; fix the TDS scale bug (F15, F14 payroll slice).**
- *Fix:* compute payroll/TDS server-side through a tested endpoint; delete the client-side slab math (or, minimum viable, scale thresholds to paise). *Impact:* stops persisting wrong TDS to `payroll_slips`/payslips/24Q. *Priority:* Critical. *Deps:* R1.2. *Effort:* M. *Rollout:* 2. *Benefit:* correctness + architecture-rule compliance.

**R1.4 — Convert GSTR-3B GSTN payload to rupees (F16).**
- *Fix:* reuse `gstr1_builder._paise_to_rupees` across every `as_gstn_payload` field; add a payload unit test. *Effort:* S. *Deps:* R0.1. *Rollout:* 2. *Benefit:* removes a 100× filing error.

**R1.5 — Fix Axis/SBI bank-format detection (F8).**
- *Fix:* replace greedy substring matching with per-bank column-set/order matching + header-width validation; regression tests for Axis and SBI headers. *Effort:* M. *Deps:* R0.1. *Rollout:* 2. *Benefit:* stops silent debit/credit corruption of the bank feed.

**R1.6 — Make journal & receipt posting atomic (F2, F7).**
- *Fix:* move header+lines (and receipt→AR→journal) into a single Postgres `SECURITY DEFINER` RPC invoked via `db.rpc(...)`, or post the journal first and only mutate AR after it commits; stop swallowing journal exceptions; add idempotency keys. *Impact:* the GL stops diverging from sub-ledgers. *Priority:* Critical. *Deps:* R0.1. *Effort:* L. *Rollout:* 3. *Risk:* touches the hottest code path — stage behind tests. *Benefit:* restores double-entry integrity guarantees.

### Tier 2 — High (correctness, security, core workflows)

**R2.1 — Repair the year-end workflow schema (F9, F10). DELIVERED.** Revalidation found F9's real scope was every one of migration 067's 8 tables, not just the 3 originally-cited wrong table names — fixed via a corrective migration (155) plus code fixes, proven with live-Postgres inserts matching every router's exact payload. F10 fixed by fetching two date windows (FY-only for P&L, cumulative-to-date for Balance Sheet) rather than one uniform window. Also fixed two tenancy gaps (same class as F1/F4) found while re-reading the routers. *Effort:* L (as estimated). *Benefit:* year-end close now actually works against a real database, and multi-year Balance Sheets stop silently dropping prior-year balances.

**R2.2 — Create the ~13 missing tables or gate the features (F5).** Add migrations for e-invoice/e-way/XBRL/ITR-filing/26AS-record tables (and the missing RPC/columns), or feature-flag those modules off until backed. *Effort:* L. *Benefit:* removes 500s; makes the tax-record features real.

**R2.3 — Correct TDS & ITR statutory logic (F17, F18).** Rebuild thresholds as FY-versioned data (see R3.1); apply annual-aggregate correctly; ₹50k old-regime SD; §87A marginal relief; surcharge marginal relief + 15% CG cap; delete the frontend slab re-implementation. **Also (from the R1.2/R1.3 reviews): update to the CURRENT financial year with authoritative sourcing — Budget 2025 revised the new regime, and the backend `_compute_tds_192`/payroll `_compute_slip` still use FY 2024-25 with a stale ₹50,000 standard deduction (new regime is ₹75,000); add surcharge above ₹50L. Elevate F18 (income-tax deductions page `L = 100*100` → tax-slab boundaries 10× off, re-confirmed effectively a blocker for that page) to the front of this item.** *Effort:* L. *Benefit:* correct tax numbers, in step across backend and frontend.

**R2.4 — Add a database tenancy backstop (F1, F4). DELIVERED (scope adjusted).** Investigated both proposed fix directions and found neither was the highest-leverage move available: the `USE_USER_JWT` cutover is a multi-week, zero-test-coverage architectural change (deferred, not attempted); a repository-layer mandate would cover only 28/94 routers. Instead fixed `core/authz.py::can_access_client`'s actual structural flaw (firm-wide roles bypassed firm-membership checking entirely, not just assignment scoping) — hardening the ~35 routers that already depend on it in one change — plus the three real cross-tenant IDORs a systematic sweep found (payroll finalize/status, GSTR-9 as originally cited, ITR version history). *Effort:* M (delivered scope). *Benefit:* the central authz gate can no longer be bypassed by supplying another firm's client_id; three live IDORs closed with regression tests proving both directions.
- **New finding (Tier 2/3 candidate, not yet scheduled):** `core.supabase_client.get_supabase_client` — imported by 9 files (ITR workflow, e-invoice, e-way bill, XBRL, 26AS, GST portal sync, Tally migration) — does not exist anywhere in the codebase. Every call is gated behind `_USE_MOCK` checks, which is why no test has ever caught it. These entire feature areas are non-functional in any real deployment (`ImportError` on first non-mock call). *Effort:* M (define the intended function, fix 9 call sites, add a CI guard against phantom imports hiding behind mock-mode branches). *Benefit:* makes seven advertised feature areas actually work outside of mock/demo mode.

**R2.5 — Close the `/join` privilege escalation and portal-invite gaps (F21, F22). DELIVERED.** Moved `/join` account-linking to a backend endpoint validating a signed single-use invite token; added tokenized, expiring portal invites — and, discovered during implementation, rewired the actual live "Invite to Portal" UI (which bypassed the tokenized service entirely via a raw browser `signInWithOtp` + direct table write) onto the same audited path. See Implementation Log for the full account, including a self-caught UPDATE-based escalation bug and a self-caught regression in the `users`-table RLS hardening. *Effort:* M (actual, incl. the unplanned live-flow rewire). *Benefit:* removes the most exploitable security holes AND makes the client-portal invite feature actually work end-to-end for the first time.

**R2.6 — Fix RLS predicates and migration hygiene (F20 + drift). DELIVERED (partially).** Corrected all 43 remaining policies keyed on the never-issued `firm_id` JWT claim (migration 154); added a database-free ratchet test against duplicate migration numbers growing further. **Not done — needs a human with production access:** actually reconciling repo-vs-live drift requires running the migration runner against the real production Supabase, which this session has no credentials for and would not run autonomously regardless (high-blast-radius, hard-to-reverse). See Implementation Log for the exact command to run. *Effort:* M (delivered portion). *Benefit:* makes the eventual RLS/`USE_USER_JWT` cutover (R2.4) safe on 51 previously deny-all tables.

**R2.7 — Wire the workflow engine or hide it (F11, F12).** Register `workflow_builder_router` before the legacy catch-all (or constrain the `/{id}` route); implement real actions, or feature-flag the module off until done. *Effort:* M. *Benefit:* automation is honest.

**R2.8 — Make AI extraction real (F19).** Pin `groq` in `requirements.txt`; create the missing `increment_message_count` RPC; stop persisting mock-derived notices/tasks; surface extraction failures instead of fabricating. *Effort:* M. *Benefit:* the AI value prop stops silently faking data.

**R2.12 — Full receipt→AR→journal atomicity** *(follow-up from R1.6/F7).* R1.6 made the receipt path journal-first + idempotent (dedup on `receipt_no`), which converges on retry and eliminated the "settled AR with no GL" harm. The stronger guarantee is a single multi-table RPC that writes the receipt, its allocations, the invoice `paid_paise`/status CAS, and the journal in ONE transaction — closing the residual "journal posted, then AR settle fails" window and the manual-path retry double-settle the audit flagged. Extend the `post_journal_atomic` pattern to a `settle_receipt_atomic` function. *Effort:* M. *Deps:* R0.1, R1.6. *Benefit:* receipts can never leave sub-ledger and GL out of step.

**R2.11 — Bank statement parser hardening** *(pre-existing, surfaced by the R1.5 regression review).* `domain/banking/normalizer._to_paise` uses `rstrip("DrCr")`, which is case/char-set sensitive and zeroes balances suffixed `CR`/`DR`/lowercase; single signed-Amount + Dr/Cr-indicator statement layouts are unsupported and misparse every row as a debit; `Dr` (overdraft) balances lose their sign (stored same as `Cr`); and statement opening/closing balances are taken by file position, which inverts on newest-first exports (also noted in §6). Fix the Dr/Cr suffix parsing (regex, case-insensitive), add adapters (or an Amount+indicator mode) for single-amount layouts, preserve overdraft sign, and derive opening/closing by date order. Also add a one-off re-import path for statements imported before R1.5 (their rows keep the old corrupted values and won't re-dedupe). *Effort:* M. *Benefit:* correct bank feeds across more banks and export styles.

**R2.10 — Route payroll compute through the backend** *(the F14 payroll slice, deferred from R1.3).* The web payroll page computes and persists runs/slips client-side (statutory logic in the browser, against CLAUDE.md); it also stores no run totals, so backend finalize can't process frontend-generated runs. Replace the client-side compute + direct `payroll_runs`/`payroll_slips` inserts with a call to `POST /api/payroll/runs` (server-side `_compute_slip` + totals), reconciling the status/`generated_at` column differences and fetching slips via the backend to avoid RLS re-read gaps. *Effort:* M. *Deps:* frontend CI test runner (currently absent — the 12 web test files are dead code). *Risk:* unverifiable without frontend test infra; must not regress the working generate/display flow. *Benefit:* single correct payroll engine; removes the browser tax logic and the missing-totals defect.

**R2.9 — Document-number uniqueness for the remaining statutory docs** *(surfaced by the R1.1 regression review).* `debit_notes.debit_note_no` (medium), `receipts.receipt_no` and `purchase_payments.payment_no` (low) generate numbers but have **no** uniqueness constraint, so the numbering retry is dead code and concurrent duplicates are possible (CGST §34 / Rule 53 require serial uniqueness for debit notes). Add per-client (debit notes/receipts) / per-firm (payments, matching their generator) UNIQUE keys, **preceded by a de-dup migration** for any existing duplicates. *Effort:* M. *Deps:* R0.1. *Risk:* must de-dup live data before adding the constraint. *Benefit:* closes the numbering-integrity gap R1.1 deliberately scoped out.

### Tier 3 — Medium (productivity, consolidation, scale)

- **R3.0 — Harden `client_portal_users` RLS/grants** *(surfaced by the R2.5 regression review)*. Migration 109's `client_portal_users_own_firm` policy is `FOR ALL USING/WITH CHECK (firm_id = get_my_firm_id())` — any authenticated firm staff member can directly INSERT/UPDATE a `client_portal_users` row from the browser (e.g. self-activating an arbitrary contact for any client in their own firm), bypassing `invite_contact`'s token/TTL/audit trail. Not a cross-tenant leak (staff already have equivalent CA-side access to the same client), but a real audit-integrity gap. Mirror the R2.5 `users`-table fix: SELECT-only for `authenticated`, all mutation via service-role (`portal_access_service.py` already covers every legitimate mutation path). *Effort:* S. *Benefit:* closes the last raw-table write path in the portal invite flow.
- **R3.1 — Statutory rules-as-data registry (FY-versioned).** Single source of truth for slabs/thresholds/due-dates; eliminates the class of bugs behind F15/F17/F18. *Effort:* L. *Benefit:* tax law becomes maintainable data.
- **R3.2 — Cross-client batch compliance cockpit** (generate/validate/mark-filed + ARN capture across clients). *Effort:* XL. *Benefit:* the #1 CA scale unlock.
- **R3.3 — De-orphan or delete the ~40 unlinked routes and consolidate duplicate invoicing/fixed-asset/payroll stacks.** *Effort:* L. *Benefit:* coherence + lower maintenance.
- **R3.4 — Automate document collection & reminders** (WhatsApp Business API + cadence). *Effort:* L. *Benefit:* removes the biggest daily admin sink.
- **R3.5 — Performance: paginate/aggregate in SQL, add indexes, cache auth lookups.** *Effort:* M–L. *Benefit:* holds up at 100–500 clients.
- **R3.6 — UX consistency:** one skeleton/empty/error system, real dialog semantics, dashboard load-error states, shared client context. *Effort:* M. *Benefit:* daily usability.
- **R3.7 — Year-end close: post an explicit closing journal entry** *(surfaced by the R2.1/F10 fix)*. There is no mechanism today that transfers a completed year's P&L into `reserves_and_surplus` via an actual posted journal entry — the "add current-year PAT to reserves" step is a live, presentational preview computed fresh on every request, not an accounting fact. A second prior year's retained profit, if that year was also never explicitly closed, would still be invisible in a third year's cumulative reserves. Needs a business/accounting decision first (should this post automatically when a Partner locks the engagement? does it need its own CA-review gate, matching the CLAUDE.md "never auto-submit" spirit even though this is internal not government-facing? which specific reserves sub-account?) — do not implement unilaterally. *Effort:* M. *Benefit:* true multi-year retained-earnings continuity, not just single-year carry-forward.
- **R3.8 — Consolidate the two competing year-end status-transition implementations** *(surfaced by the R2.1 investigation)*. `routers/year_end.py`'s generic `PATCH /engagements/{id}/status` and `routers/year_end_reviews.py`'s four specific `POST /reviews/*` endpoints both drive the same draft→in_review→approved→locked transition on `year_end_engagements`, writing overlapping-but-different column sets (`reviewed_by`/`approved_by` vs. `submitted_by`/`revision_requested_by`/`final_approved_by`). Both work today (migration 155 added columns for both) but the duplication is a maintainability risk — a future change to one easily misses the other. *Effort:* M. *Benefit:* one source of truth for the year-end review workflow.

### Tier 4 — Long-term (differentiation)
Government-data ingestion via GSP/ASP-pull + Account Aggregator (submit stays CA-confirmed); reliable two-way Tally/Busy/Zoho import; unified deterministic-then-narrate AI layer; RAG tax-law copilot with citations; DPDP consent vault; mobile/PWA companion. These are where PracticeSync becomes a *better* product, not a cheaper clone.

---

## 11. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Wrong government filing (GST/TDS/ITR) erodes CA trust irrecoverably | High (bugs are on default paths) | Severe | Tier 1 + R2.3 + R3.1; real-DB tests |
| Multi-client firm can't operate (F6) | Certain for the target segment | Severe | R1.1 (first) |
| Silent cross-firm data leak from a future forgotten filter | Medium | Severe | R2.4 DB backstop |
| GL/sub-ledger divergence from non-atomic writes | Medium | High | R1.6 RPC transactions |
| Scale wall at 100–500 clients | High over time | High | R3.5 |
| Schema drift causes a "worked in dev, 500 in prod" incident | Already happening (F5/F9) | High | R0.1 + R2.6 |

---

## 12. Final recommendation

**Do not GA today.** PracticeSync has a genuinely good spine — one posting kernel, a real reporting engine, a strong design system, honest security documentation, and a differentiated AI-first vision. But the modules a CA touches every day (multi-client invoicing, payroll, GST output, year-end, TDS/ITR math) currently produce wrong numbers or hard failures on ordinary input, and tenancy has no database backstop.

The good news: **the defects are concentrated and mostly small, localized fixes** — the Critical tier is roughly 2–3 focused engineer-weeks once real-DB CI exists. The correct sequence is:
1. **R0.1** — stand up real-database CI so correctness is provable.
2. **Tier 1** — close the money/multi-client blockers (F6, F13, F15, F16, F8, then F2/F7).
3. **Tier 2** — year-end schema, missing tables, tax statutory logic, tenancy backstop, `/join` + portal security.
4. **Pilot** with 3–5 supervised design-partner firms; measure filing accuracy and time saved.
5. **Tier 3/4** — batch compliance cockpit, consolidation, and the differentiating AI/data-spine bets.

Close Tier 0–1 and re-audit against a real database, and PracticeSync moves from "impressive demo" to "a CA can trust it with one client." Close Tier 2 and add batch compliance (R3.2), and it becomes the supervised compliance cockpit the incumbents don't offer.

*Prepared as a review only. Awaiting approval to begin implementation in the order above.*

---

# Implementation Log

Implementation was approved on 2026-07-02 with the directive: revalidate each
finding before implementing, work one milestone at a time in priority order, and
run a regression review after each. This log records what actually shipped and
any changes to the roadmap that the work surfaced.

## Milestone R0.1 — Make correctness provable (DELIVERED)

**Goal:** a migration runner + a real-Postgres schema harness + CI, so the
schema-drift class of bug (F5, F9) can no longer ship invisibly.

**Revalidation:** confirmed the finding still holds — the mock-mode suite (2150
tests) passes but CI never touches a database; all real-DB tests skip.

**What shipped**
- `apps/api/scripts/db/apply_migrations.py` — the repo's first ordered,
  idempotent migration **runner** with a `schema_migrations` tracking table
  (addresses the "no runner / hand-applied" root cause behind the drift). Detects
  duplicate migration numbers; classifies pure data-seeds; supports a
  Supabase-compat mode for plain Postgres.
- `apps/api/migrations/_supabase_compat_bootstrap.sql` — a bootstrap that stands
  up the Supabase surface the migrations depend on (auth/storage schemas,
  anon/authenticated/service_role roles, `auth.uid()/auth.jwt()`,
  `storage.foldername()`) so the full DDL can be applied and asserted on a plain
  PostgreSQL. **Not** applied to production.
- `apps/api/tests/test_schema_contract.py` — **database-free** gate: every
  `.table()/.rpc()` the backend references must be created by some migration.
  Runs in the normal CI job.
- `apps/api/tests/test_migrations_apply.py` — **real-Postgres** ratchet: applies
  the whole set to a throwaway DB and asserts the failing-migration set equals a
  documented baseline (blocks new invalid SQL / drift; forces burn-down).
- `.github/workflows/backend-ci.yml` — added a `migrations` job running the
  ratchet against a Postgres 16 service; the existing job now also runs the
  DB-free contract test.

**Verified locally** against PostgreSQL 16: full suite **2153 passed, 45 skipped**
(no regressions); the 5 new R0.1 tests pass; runner is deterministic and
idempotent (re-run skips 143 already-applied migrations).

**New findings surfaced by the harness (fed into the roadmap):**
1. **Invalid SQL in three migrations that cannot apply to *any* Postgres
   (incl. Supabase) — FIXED as part of enabling the runner:**
   `049`/`050` used `TEXT(n)` (invalid type modifier → `TEXT`); `054` used
   `ON CONFLICT … DO NOTHING WHERE …` (invalid → `DO NOTHING`). That these files
   could never have applied as written is direct evidence the live schema was
   built by out-of-repo DDL — **confirmed repo-vs-live drift**.
2. **F5 is larger than first reported.** The static contract test found **14
   additional phantom tables** the code references but no migration creates,
   beyond the original ~13 — including `year_end_checklist_items`,
   `year_end_notes`, `year_end_review_events` (independently **corroborating F9**),
   `tally_migration_jobs`/`_items` (the broken Tally migration),
   `onboarding_checklists`/`_steps`, `pending_invites`, `gst_returns`, `notices`,
   `work_items`, `entity_to_entity_relationships`, `properties`,
   `client_portal_sessions`. All are pinned in a documented baseline.
   → **R2.2 scope expands** to create/gate these tables.
3. **11 migrations do not cleanly re-apply to a fresh DB** (ordering/collision
   drift). The harness **independently reproduced the audit's workflow_steps
   collision**: migration `002` pre-creates a legacy `workflow_steps`, so `068`'s
   `CREATE TABLE IF NOT EXISTS` no-ops and its `template_id` column/index never
   materialize; `059`/`070` show the same collision on `client_profiles`.
   → **R2.6 now has a concrete, test-enforced 11-migration burn-down list.**

**Roadmap adjustments:** none reversed. R2.2 and R2.6 gained precise scope
(above). No product/runtime code was changed in this milestone — only three
one-line migration SQL fixes plus tooling/tests/CI.

**Next:** Milestone R1.1 (invoice/credit-note numbering for multi-client firms,
finding F6) — the highest-severity launch blocker — after this milestone's
regression review.

## Milestone R1.1 — Multi-client invoice/credit-note numbering, F6 (DELIVERED)

**Goal:** let every bookkeeping client of a firm issue invoices; today only the
first client can.

**Revalidation:** F6 confirmed still live. The number is `SINV-{fy}-{seq}` with a
**per-(firm, client, FY)** sequence (`routers/sales_invoices.py:64`
`_next_invoice_seq`) but a **per-(firm, invoice_no)** UNIQUE constraint
(`050:36`). Client B's first invoice computes `SINV-{fy}-0001` (its own count is
0), collides with client A's, and `services/numbering.py`'s retry recomputes the
same client-scoped number and collides every time → 500. Credit notes share the
identical pattern (`_next_cn_seq` vs `050:176`).

**Root cause & fix:** the numbering-per-client is *correct* — each client is a
distinct supplier and must keep its own continuous series (CGST Rule 46). The
UNIQUE key was simply too narrow. Migration **`151_per_client_document_numbering.sql`**
widens it to `(firm_id, client_id, invoice_no)` and
`(firm_id, client_id, credit_note_no)` via idempotent DO-blocks that drop the old
constraint by column-set and add the new one. No application code changed — the
sequence logic was already per-client, and no code looks up invoices/credit-notes
by number alone (verified), so widening the key breaks no read path. Widening a
unique key only relaxes it, and the bug itself prevented any colliding data, so
the migration is data-safe.

**Verified against real PostgreSQL 16** (`tests/test_per_client_numbering.py`,
runs in the `migrations` CI job): two clients of one firm can each hold
`SINV-2526-0001` / `CN-2526-0001`, while a same-client duplicate is rejected by
the new constraint (statutory per-supplier uniqueness preserved). Migration 151
applies cleanly (drift baseline unchanged at 11); full suite 2153 passed / 49
skipped, no regressions.

**Regression review (3 lenses, adversarially verified):** core F6 fix confirmed
**correct and complete** — "no app-code change needed" verified (the retry in
`numbering.py` still works under the wider key; mock/prod parity holds on the F6
dimension; no read path assumes firm-global number uniqueness; the journal
idempotency dedup keys on `(firm, client, reference_no, entry_date)` so two
clients sharing `SINV-2526-0001` produce distinct journals; recurring invoices
reuse the fixed path). Migration 151 judged safe (nits only). Follow-up applied:
added `tests/test_document_numbering_unit.py` exercising the application
sequence generators (per-client + per-FY scoping), complementing the DB-level
constraint proof.

**Sibling gaps the review confirmed — promoted to a tracked roadmap item (R2.9),
deliberately NOT folded into R1.1** (they are a *different* defect — missing
uniqueness, not a collision — and adding constraints needs a data de-dup step):
`debit_notes.debit_note_no` (medium — per-client numbering but no unique
constraint anywhere, so the retry is dead code and concurrent duplicates are
possible; CGST §34/Rule 53 needs serial uniqueness), `receipts.receipt_no` and
`purchase_payments.payment_no` (low). `fee_invoices`, `purchase_bills` and
recurring invoices were verified fine.

**Next:** Milestone R1.2 (balance the payroll finalization journal, F13).

## Milestone R1.2 — Balance the payroll finalization journal, F13 (DELIVERED)

**Goal:** let payroll finalization post; today it 500s on essentially every run.

**Revalidation:** confirmed. `journal_for_payroll`
(`services/phase2_journal_service.py`) debited only `gross` but credited
`net + PF + ESI + PT + TDS`. Since `net = gross − employee PF − employee ESI −
PT − TDS` and the run's `total_pf`/`total_esi` carry *both* employee and employer
shares (`routers/payroll.py:302-303`), the credits exceed the debit by exactly
the **employer PF + employer ESI** — so `_create_journal`'s balance check
(`:986`) raised and finalization 500'd whenever PF/ESI applied (the defaults). The
code comment even admitted it "simplified" the employer cost away.

**Fix:** the employer's *total* cost of employment (gross wages + employer PF/ESI)
equals, by that same identity, the sum of every payable credit. So the Salaries
Expense debit is now booked as that sum — the entry balances by construction for
any mix of contributions, using only the already-seeded accounts (no new CoA
dependency, no schema change). Line-building was refactored into a pure,
unit-testable helper `_build_payroll_lines`.

**Verified** (`tests/test_payroll_journal_balance.py`, runs everywhere): debits ==
credits across contribution mixes (PF/ESI/PT/TDS, no PF/ESI, TDS present); the
Salaries Expense debit equals gross + employer PF/ESI (and is no longer the bare
gross that was the bug); every line is debit-XOR-credit (satisfies the DB CHECK).
The zero-value-journal guard still refuses degenerate empty runs. Full suite 2160
passed / 49 skipped, no regressions; no existing test encoded the old behavior.

**Noted for the roadmap (not done here):** employer PF/ESI is folded into Salaries
Expense. A cleaner presentation would split it into a dedicated "Contribution to
PF & Other Funds" account for the Schedule III employee-benefit sub-classification
(requires seeding that account + storing the employer/employee split as run
totals). Small enhancement, tracked; does not affect P&L totals or ledger balance.

**Regression review (3 lenses, adversarially verified):** the F13 balance fix
confirmed **accounting-correct** — the Salaries Expense debit equals the true
total cost of employment and the entry balances by construction (verified
numerically; exact integer-paise identity, no double-count). It surfaced one
**high** issue in the same finalize path, now **fixed as part of this milestone**:
`finalize_run` marked a run `finalized` (immutable) and reported success even when
`journal_for_payroll` silently returned `None` on a swallowed posting failure —
leaving an immutable run with no GL entry. Now the run is finalized **only if the
journal posts**; on failure it stays re-runnable (a retry is safe — the kernel
dedupes on `reference_no=PAY-{month}`). Also applied: an empty/zero-gross run is
refused with a clean 400 instead of a 500; a defensive identity invariant in
`_build_payroll_lines` fails loud if a future deduction is ever added to `net`
without a matching credit leg (since the balance check can no longer catch it);
and the stale `finalize_run` docstring was corrected. Schedule III
sub-classification of employer PF/ESI remains the tracked enhancement (low, P&L
total unaffected). Full suite 2161 passed / 49 skipped.

**Next:** Milestone R1.3 (move payroll/GST business logic off the browser; fix the
frontend TDS scale bug, F15/F14 payroll slice).

## Milestone R1.3 — Frontend payroll TDS scale bug, F15 (DELIVERED, scope adjusted)

**Goal:** stop the browser payroll computation from massively over-deducting TDS.

**Revalidation:** confirmed. `apps/web/app/payroll/page.tsx:computeSlip` computes
`gross` in paise (verified: ESI check `gross <= 2100000` = ₹21,000, PT
`gross > 1000000` = ₹10,000) but the TDS slab thresholds were rupee-scale
(`annualGross > 1500000` meaning ₹15,000, not ₹15,00,000) while the base amounts
were paise (`12500 * 100`) — and the slab *structure* itself was wrong. The
computed slips persist to `payroll_slips` (`:945`).

**Fix:** replaced the broken block with `monthlyTdsPaiseNewRegime()` — a correct
new-regime FY 2024-25 computation in integer paise (₹75,000 standard deduction,
slabs 0–3L/3–7L/7–10L/10–12L/12–15L/>15L, §87A rebate up to ₹7,00,000 taxable
with marginal relief, 4% cess, ÷12). Only the TDS block was scale-wrong; PF/ESI/PT
were already paise-correct and were left unchanged.

**Verified:** the exact function run in node against seven salary levels, and
type-checked under `tsc --strict`. Impact of the bug it removes: the old code
deducted **₹6,666–18,666/month from employees earning ₹2.4L–7.2L/year who owe
zero tax**, and ~5× over-deducted at higher incomes (e.g. ₹1L/month: ₹30,666 →
correct ₹5,958).

**Scope adjustment (roadmap updated, not abandoned):** R1.3 originally also
folded in "move payroll compute server-side" (the F14 architectural slice). That
part is **deferred to a dedicated milestone (R2.10)** rather than done blind,
because: (a) the web app is a static export with **no CI test runner** for the
frontend (audit tests/quality finding), so a large refactor of the 1,300-line
payroll page can't be verified here; (b) the run/slip UI keys on frontend-only
columns (`generated_at`, status `"generated"`) that the backend
`POST /api/payroll/runs` doesn't populate (it uses `"draft"`), and slips created
by the service-role backend would need an RLS-safe re-read; (c) a discovered
related defect — **frontend-generated runs store no run totals**, so backend
finalize (which reads `total_gross_paise`) can't process them. R2.10 routes the
frontend through the backend compute (fixing F15 at the source *and* the missing
totals) once frontend test infrastructure exists. The in-place F15 fix removes
the launch blocker now.

**Regression review (3 lenses, adversarially verified):** the corrected TDS
computation was verified **statutorily correct on every element** — ₹75,000
standard deduction, slab floors and cumulative bases, §87A rebate on
post-standard-deduction income, marginal relief at the ₹7L boundary, and cess-then-÷12
ordering (all hand-checked); and the fix is **complete** — a single TDS source
used by both the persist and preview paths, with PF/ESI/PT confirmed already
paise-correct (no sibling scale bug). Findings, all routed to the roadmap (no
further R1.3 code change — the scale fix is correct for its scope):
- **Forward-only (medium):** slips generated before this fix keep the wrong
  `tds_paise`/`net_paise` in `payroll_slips`. Not auto-remediated here — some runs
  are finalized with posted journals, so recompute must be state-aware (regenerate
  un-finalized runs; reverse+repost finalized ones). Tracked as a data-remediation
  task under **R2.10** (payroll convergence).
- **FY-currency (medium):** parameters are FY 2024-25 while the system date is FY
  2026-27; Budget 2025 revised the new regime. This is system-wide (the backend
  `_compute_tds_192`/`_compute_slip` are also FY 2024-25, and the backend standard
  deduction is a stale ₹50,000) — folded into **R2.3 / R3.1** (correct, FY-versioned
  statutory rules across both engines, with authoritative sourcing). A code comment
  now flags it.
- **Surcharge / §80CCD(2) omitted (low):** acceptable for a labelled monthly
  estimate; add when the compute moves server-side (R2.3/R2.10).
- **F18 re-confirmed (separate, pre-existing):** the sweep independently confirmed
  the income-tax deductions page slab bug (`L = 100*100` → tax boundaries 10× off)
  is real and unfixed — verified as **not an R1.3 regression** (a distinct audit
  item). Its severity is effectively blocker for that page; elevated for early
  attention within R2.3.

**Next:** Milestone R1.4 (convert the GSTR-3B GSTN payload to rupees, F16).

## Milestone R1.4 — GSTR-3B GSTN payload in rupees, F16 (DELIVERED)

**Goal:** stop the GSTR-3B upload payload from carrying amounts 100× too large.

**Revalidation:** confirmed. `domain/gst/gstr3b_computer.py:GSTR3BResult.as_gstn_payload`
emitted every monetary field (`txval`, `iamt`, `camt`, `samt`, `csamt`, the RCM
`inter/intra_*`, and all ITC amounts) as raw integer **paise**, while the GSTN
portal — and the sibling GSTR-1 builder — use **rupees**. The endpoint labels the
result "ready for GSTN portal upload" (`routers/gst.py:274`).

**Fix:** every amount in the payload is now converted with `_paise_to_rupees`
(imported from the GSTR-1 builder — a single canonical GST conversion, no
duplicated/driftable copy). Only `as_gstn_payload` changed; the internal
computation stays in integer paise.

**Verified:** ran the payload (₹10,00,000 taxable, ₹1,80,000 IGST, etc.) — every
field now emits rupees (`txval` 10_00_000.00, not 10_00_000_00 paise). Updated the
one existing test that had encoded the bug (`test_h7_...` asserted the payload
equalled the paise value) and added `test_f16_gstn_payload_amounts_are_rupees_not_paise`
covering every section (osup_det, osup_zero/nil, isup_rev, inward RCM, itc_avl,
itc_net). No circular import (gstr1_builder does not import gstr3b_computer). Full
suite 2162 passed / 49 skipped; the standalone e2e GST script only checks key
presence, so it is unaffected.

**Regression review (3 lenses, adversarially verified):** conversion coverage
confirmed **complete and correct** (every field wrapped once, no double-division;
GSTR-1 independently verified clean, no sibling 100× payload found). It raised a
well-grounded **high** correction, now **applied**: GSTR-3B is declared and *paid*
in **whole rupees** (CGST Act §170, half rounds up), not the 2-decimal rupees I
first used — a 2-decimal liability can't be paid exactly from the whole-rupee cash
ledger, causing a reconciliation mismatch and possible portal rejection. Changes
made in response:
- New shared module `domain/gst/money.py` with two conversions —
  `paise_to_rupees_2dp` (GSTR-1) and `paise_to_rupees_whole` (GSTR-3B, §170
  round-half-up via `(paise+50)//100`). This also resolves the **medium** finding
  (GSTR-3B no longer reaches into GSTR-1's private helper; each return uses the
  rounding its statute requires). GSTR-1 now imports the shared 2dp function too
  (single source; all GSTR-1 tests still pass).
- GSTR-3B payload emits whole-rupee **integers**, which also fixed the low
  int-0-vs-float inconsistency.
- Added `test_f16_gstr3b_rounds_to_whole_rupees_section_170` with sub-rupee inputs
  (₹1,23,456.78→123457, .49→45000, .50→45001) to pin §170 rounding — the earlier
  exact-rupee tests couldn't distinguish 2-decimal from whole-rupee.
Full suite 2163 passed / 49 skipped.

**Out of scope (noted, pre-existing):** the payload omits Table 6.1 net tax
payable (a separate GSTN call — defensible) and `osup_zero` hardcodes zero IGST
(exports-with-payment unmodelled). Both are computation-scope items, not part of
the F16 amount-scaling fix.

**Next:** Milestone R1.5 (fix Axis/SBI bank-format detection, F8).

## Milestone R1.5 — Axis/SBI bank-format detection, F8 (DELIVERED)

**Goal:** stop bank-statement import from corrupting debit/credit direction and
amounts for Axis (and mis-describing SBI) statements.

**Revalidation:** confirmed. `domain/banking/normalizer.py:detect_format` tested
`"chq"/"cheque"` **first**, but that substring appears in HDFC "Chq/Ref No", Axis
"CHQNO" *and* SBI "Ref/Cheque No" — so both Axis and SBI routed to the HDFC
adapter. Axis's different column order (`ref,desc,debit,credit,balance` at 1–5 vs
HDFC's `debit,credit,balance` at 4–6) then read the balance column as the credit:
a ₹500 debit became a ₹10,000 credit. SBI's amounts survived (same 4/5/6 layout)
but its description was read from the Value Date column.

**Fix:** reordered `detect_format` so the reliable bank-specific discriminators
run first — `transaction remarks`→ICICI, `txn date`→SBI, `tran date`→Axis — and
the shared cheque/narration heuristic runs **last** for HDFC. (`tran date` is
distinct from SBI's `txn date` and ICICI's `transaction date`.) No adapter column
maps changed.

**Verified:** reproduced the exact F8 case — the Axis ₹500 debit now parses as a
₹500 debit (`debit_paise=50000, credit_paise=0`), SBI reads the real description,
and HDFC/ICICI still route correctly. Added three regression tests
(`test_csv_axis_format_detected_and_directions_correct`,
`test_csv_sbi_format_detected_and_description_correct`,
`test_detect_format_shared_cheque_signal_does_not_shadow_banks`). Full suite 2166
passed / 49 skipped.

**Regression review (3 lenses, adversarially verified):** the F8 reorder was
confirmed **correct** — all four canonical headers route to the right adapter and
the substring-collision safety was verified (`tran date` ≠ inside `transaction
date`, `chq` ≠ inside `cheque`). It raised a **high** of the same class (silent
debit/credit corruption when an *unknown or mismatched* layout is force-fit into
an adapter), and noted the reorder added a small opposite risk (an HDFC export
mislabeled `Txn/Tran Date` would route to sbi/axis). **Fixed as part of this
milestone:** added `_validate_adapter` — after detection, it requires every mapped
column to fit the header width AND the debit/credit columns to actually be
labelled debit/withdrawal and credit/deposit; otherwise it raises
`StatementParseError`. So any misroute or unsupported layout now **fails loud**
instead of silently producing wrong numbers (verified: the four banks + generic
still parse; a 6-column unknown layout and an HDFC-variant-with-`Tran Date` both
now raise). Full suite 2168 passed / 49 skipped.

**Deferred to R2.11 (verified pre-existing, different class — not caused by R1.5):**
the review also found `_to_paise`'s `rstrip("DrCr")` zeroes balances suffixed
`CR/DR` (case/char-set sensitive); single signed-Amount + Dr/Cr-indicator layouts
are unsupported and misparse; `Dr` (overdraft) balance sign is dropped; and
opening/closing balances are taken by file position (wrong for newest-first
exports — this one the original audit also flagged). Plus a data note: rows
imported before R1.5 keep their corrupted values and won't re-dedupe, so affected
statements must be re-imported. All routed to R2.11.

**Next:** Milestone R1.6 (make journal & receipt posting atomic, F2/F7).

## Milestone R1.6 — Atomic journal & receipt posting, F2/F7 (DELIVERED)

**Goal:** stop the general ledger from diverging from the sub-ledgers on a
posting failure.

**F2 — journal atomicity.** The kernel inserted the journal header and its lines
as two separate PostgREST calls; a line failure after the header committed left a
POSTED header with no lines, which the immutability trigger (055) made
**unrepairable**, and dedup then returned that orphan forever. Fix: migration
**152** adds `post_journal_atomic(p_entry, p_lines)` — a plpgsql function (one
transaction) that inserts the header (partial insert, DB defaults preserved) and
all lines together, and resolves the `(firm, client, reference_no, entry_date)`
idempotency race by returning the winner on `unique_violation`. The kernel calls
it via `db.rpc(...)` when rpc is available (real Supabase client + the e2e
FakeDB), falling back to two inserts only for rpc-less in-memory doubles
(trivially atomic; never reached in prod). **Proven on Postgres 16**
(`tests/test_atomic_journal_posting.py`): a line that violates the XOR check makes
the whole call roll back with **no orphan header**; happy path and dedup verified.

**F7 — receipt ordering.** `create_receipt_core` inserted the receipt and settled
AR (`paid_paise`) *before* posting the journal, and `journal_for_receipt`
swallowed non-ValueError errors (returned None) — so a posting failure left
**settled AR with no GL entry**. Fix: post the journal **first** (it needs only
the receipt dict, so no row is written yet), and make `journal_for_receipt`
**re-raise** instead of swallowing. A failure now aborts before any AR mutation;
on success the receipt is written (now stamped with `journal_entry_id`) and AR
settled. **Verified** (`test_f7_journal_failure_does_not_settle_ar`): a forced
journal failure leaves the invoice unpaid and writes no receipt.

FakeDB gained an `rpc()` double mirroring `post_journal_atomic`. Migration 152
applies cleanly (drift baseline unchanged at 11). Full suite 2169 passed / 52
skipped.

**Follow-up noted (R2.12):** the receipt path is now journal-first + idempotent
(dedup on `receipt_no`), which converges on retry — but full receipt→AR→journal
atomicity (a single multi-table RPC) is the stronger guarantee and would also
close the residual "journal posted, then AR settle fails" window and the retry
double-settle on the manual path. Tracked as R2.12.

**Regression review (4 lenses, adversarially verified)** confirmed the RPC itself
is structurally correct (partial insert, line casts, dedup, and true
single-transaction atomicity all hold) and surfaced real, actionable gaps —
**all fixed as part of this milestone**:

- **HIGH — the F7 reorder relocated the danger window, not closed it.** Posting
  the journal *before* the AR-settlement loop meant an over-allocated request (a
  single request, no concurrency needed) could still post a phantom Dr Bank / Cr
  Trade Receivables journal *and* a receipt row before the loop discovered the
  422 — worse than before, since now both the journal and the receipt persisted
  for an operation the API reported as failed. **Fixed:** added upfront
  validation of every allocation against LIVE invoice outstanding, summed per
  invoice, **before** anything posts — the primary, non-concurrent case can no
  longer reach the journal at all. For the now-much-narrower residual (a genuine
  concurrent settlement race exhausting the CAS retry), added a compensation
  path: `reverse_entry` reverses the journal and the orphaned receipt row is
  deleted, so a failure self-heals instead of leaving a permanent phantom entry.
  Applied to both `create_receipt_core` and the foreign-currency
  `create_foreign_receipt` (identical structure, same gap).
- **MEDIUM — retry after a partial commit could double-post.** A consequence of
  the above; closed by the same fix (the reachable single-request case no longer
  commits before failing, so there's nothing to retry into).
- **MEDIUM — re-raising `journal_for_receipt` could strand an online payment in
  the `'capturing'` sentinel forever** (no compensation existed for the new
  non-swallowing behavior). **Fixed:** `_apply_event` now reverts the payment
  status back to the event's status on a settlement failure, so a webhook
  redelivery or manual retry can re-attempt settlement instead of the payment
  being stuck permanently.
- **HIGH (deployability) — hard, unguarded RPC dependency.** Since there is
  deliberately no fallback (a fallback would silently reintroduce F2), a missing
  migration 152 on the target database would 500 every journal post in
  production. **Addressed:** the kernel now catches a missing-function error and
  raises a clear, named error identifying migration 152 by number and path (not
  an opaque 500); migration 152 itself now carries an explicit
  "apply-before-deploy" deployment requirement in its header. No automatic
  fallback was added — correctness over availability for the GL, by design.
- **MEDIUM — the schema-contract test's phantom-RPC guard was blind to
  multi-line `.rpc(` calls**, so `post_journal_atomic` (and `is_fy_locked`,
  pre-existing) passed vacuously rather than being checked against a migration —
  defeating the safety net for the exact dependency this milestone introduced.
  **Fixed:** `test_schema_contract.py`'s reference scanner now searches whole-file
  text (not line-by-line), so a call whose name-string wraps onto the next line
  is still matched; both RPCs are now genuinely validated.
- **LOW — migration 152 lacked `SET search_path`**, re-tripping the
  `function_search_path_mutable` advisor migration 144 was written to clear.
  **Fixed:** added `SET search_path = public, pg_catalog`, matching the project
  convention.

New regression tests added: `test_f7_over_allocated_receipt_posts_no_phantom_journal`
(over-allocation posts nothing), `test_journal_failure_reverts_capturing_claim_not_stranded`
(online payment survives a journal failure and can retry). Full suite 2178
passed / 45 skipped, no regressions.

**Residual, explicitly tracked (not silently left, R2.12 scope stands):** if a
receipt allocates to *multiple* invoices and an *earlier* invoice's
compare-and-set already succeeded before a *later* one fails under a genuine
concurrent race, that earlier invoice's `paid_paise` is not rolled back by the
compensation (safely reverting a concurrent CAS write needs its own
transaction) — the compensation logs the affected invoice ids for manual
review. Also noted but out of scope here: a dedup'd pre-152 orphan header (if
one already existed in a live database before this migration) is still returned
by the idempotency dedup — 152 prevents new orphans, it does not backfill old
ones; a one-time production check query is included in the migration's comments.

This completes **Tier 1** — all six Critical launch blockers (R1.1–R1.6) are fixed
and verified.

**Next:** Tier 2 — R2.1 (year-end schema, F9), R2.2 (missing tables, F5), R2.4
(tenancy backstop, F1/F4), R2.5 (`/join` + portal security, F21/F22), R2.3 (tax
statutory logic incl. the elevated F18), R2.7 (workflow engine, F11/F12).

## Milestone R2.5 — Close `/join` privilege escalation + tokenize portal invites, F21/F22 (DELIVERED)

**Goal:** stop an authenticated Supabase user from self-granting Partner-level
access to an arbitrary firm, and stop a portal invite from silently binding to
whichever stranger happens to reuse or mistype the invited email.

**F21 — `/join` privilege escalation.** `app/join/page.tsx` read `firm`/`role`/
`name` from URL query params and, if no pre-invited `users` row matched, INSERTed
a brand-new row with those attacker-controlled values directly from the browser.
Two PERMISSIVE RLS policies applied to INSERT (`users_own_row`: only checked
`auth_user_id = auth.uid()`, no firm constraint; `partners_can_invite_users`:
checked `firm_id = get_my_firm_id()`) and Postgres ORs permissive policies
together, so satisfying the trivial first policy was sufficient — `/join?
firm=<any-uuid>&role=Partner` was a full account-takeover primitive against any
firm. **Fix:** `create_user` (already Partner-only, RBAC `team:write` — that half
was already correct from M6) now also issues a single-use, 7-day-expiring
`invite_token`; a new `POST /api/identity/accept-invite` (JWT-only auth via
`get_jwt_user`, no `users` row required yet) resolves `firm_id`/`role` **only**
from the server-created invite row, keyed by verified JWT email + token — never
from the request body (`test_accept_invite_cannot_forge_firm_or_role_via_request_body`
proves an attacker-supplied `firm_id`/`role` in the body is silently ignored).
`/join/page.tsx` was rewritten to be purely token-based: it reads `?token=` only
and calls the new endpoint.

**F22 — tokenless, auto-binding portal invites.** `portal_access_service.
list_portal_memberships` auto-bound **any** `client_portal_users` invite whose
email matched the caller's Supabase session email, on **every** portal page
load — no token, no expiry. A recycled or typo'd email silently inherited that
client's invoices/statements/compliance data on first login. **Fix:** the same
invite-token/expiry pattern on `client_portal_users`; a new `accept_portal_invite
(token, auth_user_id, email)` and `POST /api/portal/accept-invite`
(`portal_self.py`); `list_portal_memberships` is now purely read-only (the
auto-bind loop is gone). `/portal/dashboard/page.tsx` reads `?invite=<token>`,
waits for the Supabase session to hydrate (bounded 10×500ms poll — the magic-link
redirect can land before the client SDK finishes processing the auth hash), then
calls accept-invite before loading memberships.

**Schema (migration 153):** adds `invite_token`/`invite_expires_at` to both
`users` and `client_portal_users` (unique partial indexes on the token). Also
hardens `users` RLS/grants, since the INSERT vulnerability's root RLS policies
needed closing at the database layer too (defense in depth), not just by
deleting the vulnerable frontend code path: `REVOKE INSERT, UPDATE, DELETE ON
public.users FROM authenticated`, replacing the dropped `users_own_row`/
`partners_can_invite_users` policies with `users_own_row_select` (read own row
only) plus a narrow `GRANT UPDATE (full_name) ON public.users TO authenticated`
+ `users_own_row_rename` policy so the existing "edit my display name"
self-service feature (`app/settings/page.tsx`) keeps working.

**Self-discovered escalation bug (caught during our own verification, not by the
original audit):** the first draft of the `users` UPDATE fix used only an RLS
policy — `USING/WITH CHECK (auth_user_id = auth.uid())`, no column restriction.
Verified live on Postgres 16 that this let a legitimate authenticated user
`UPDATE public.users SET role='Partner' WHERE id=<their own row>` and succeed —
`WITH CHECK` constrains **which row** may be touched, not **which columns or
values**, so the escalation just moved from INSERT to UPDATE. A second
verification pass (prompted by the same review that would later catch the
settings.tsx regression below) confirmed a blanket `REVOKE UPDATE` would also
work but breaks the legitimate rename feature — the column-level `GRANT UPDATE
(full_name)` closes the escalation **and** preserves the feature, verified with
five live-Postgres proofs: attacker self-INSERT → `permission denied`;
legitimate self-`role` UPDATE → `permission denied`; legitimate self-`firm_id`
UPDATE → `permission denied`; legitimate self-`full_name` rename → succeeds,
`role`/`firm_id` unchanged; cross-row rename attempt → `UPDATE 0` (RLS-filtered).

**Regression review (adversarial) surfaced two more real findings:**

- **HIGH — the fix protected a backend flow the product didn't actually use.**
  `services/portal_access_service.py:invite_contact` (the audited, tokenized
  invite path) was never called from anywhere in the frontend. The **actual**
  live "Invite to Portal" button (`app/clients/[id]/portal/page.tsx`) called
  `supabase.auth.signInWithOtp` directly from the browser with a redirect to
  the legacy `/portal?client=<id>`, and wrote `clients.portal_enabled` via a raw
  browser-side Supabase update — completely bypassing the tokenized service.
  Worse: the legacy `/portal` page's own auto-bind (matching `?client=` against
  `clients.portal_user_id`) was independently confirmed **RLS-unreachable** —
  no `clients` policy (`clients_own_firm`, `clients_assignment_scope`) has ever
  granted a non-staff identity direct access to that table, since both key off
  a `users` row a portal client never has. Net effect: the flagship client
  portal invite flow was silently non-functional for every real client, while
  looking like it worked from the CA's side ("Invite sent!"). **Fixed:**
  `app/clients/[id]/portal/page.tsx` now calls `api.portal.inviteContact(...)`
  to create the tokenized invite server-side, then uses the returned token to
  build the `signInWithOtp` redirect to `/portal/dashboard?invite=<token>` —
  the same pattern already proven for staff invites in `team/page.tsx`. The
  backend's own `_send_invite_email` link (which pointed at the same dead
  `/portal` page) was corrected to the same `/portal/dashboard?invite=` target.
  The now-fully-orphaned legacy `/portal/page.tsx` was replaced with a redirect
  stub to `/portal/dashboard` (preserving `?invite=` if present) rather than
  deleted outright, so any already-sent invite email or bookmark still lands
  somewhere functional.
- **HIGH — migration 153's original blanket `REVOKE UPDATE` broke a live
  feature.** `app/settings/page.tsx`'s "save my display name"
  (`.from("users").update({full_name}).eq("auth_user_id", ...)`) is a real,
  reachable self-service feature the migration's own comment incorrectly
  claimed didn't exist. **Fixed** by the column-level `GRANT UPDATE
  (full_name)` described above — caught independently by both a live-Postgres
  proof pass and an adversarial review agent before commit.
- **MEDIUM (tracked as a Tier 3 follow-up, not blocking):**
  `client_portal_users_own_firm` (migration 109, untouched by this milestone)
  is `FOR ALL USING/WITH CHECK (firm_id = get_my_firm_id())` — any authenticated
  firm staff member can directly INSERT/UPDATE a `client_portal_users` row from
  the browser (e.g. self-activating an arbitrary contact for any client in
  their own firm), bypassing `invite_contact`'s token/TTL/audit trail entirely.
  Not a cross-tenant confidentiality escalation (staff already have equivalent
  CA-side access to the same client data) but a real audit-integrity gap.
  Recommended fix mirrors this milestone's `users` hardening: make
  `client_portal_users` SELECT-only for `authenticated`, all mutation via
  service-role.
- **LOW (not fixed, cosmetic):** `routers/identity.py:accept_invite` parses
  `invite_expires_at` without the `isinstance(..., datetime)` guard that
  `portal_access_service.accept_portal_invite` has; harmless today since
  PostgREST always returns ISO strings, but worth aligning for consistency.

**Verified:** migration 153 applies cleanly on Postgres 16 (`test_migrations_apply.py`,
drift baseline unchanged at 11); `test_schema_contract.py` passes; 7 previously-
passing `test_portal_foundation.py` tests that encoded the old auto-bind
behavior were rewritten to the explicit-accept model, plus new regression locks
(`test_membership_listing_never_auto_binds_a_matching_email`,
`test_accept_invite_wrong_token_rejected`, `test_accept_invite_email_mismatch_rejected`,
`test_accept_invite_expired_rejected`, `test_accept_invite_is_single_use`); 7 new
tests in `test_identity_admin.py` cover the same matrix for staff invites,
including `test_accept_invite_cannot_forge_firm_or_role_via_request_body`. `tsc
--noEmit` and a full `next build` (static export) both pass with no errors
across every touched page. Full backend suite: 2165 passed / 52 skipped (23
pre-existing, unrelated failures in `test_hardening.py`/`test_phase3_*.py`
confirmed present on the pre-R2.5 baseline too — a test-isolation issue, not a
regression from this milestone).

**Next:** R2.6 (RLS predicate + migration-hygiene backlog), R2.4 (tenancy DB
backstop, F1/F4), R2.1 (year-end schema repair, F9/F10).

## Milestone R2.6 — Fix RLS predicates + migration hygiene backlog, F20 (DELIVERED)

**Goal:** close the last `auth.jwt()->>'firm_id'` deny-all RLS holes (F20) and
add a regression guard against the migration-numbering drift the audit flagged.

**F20 — RLS policies keyed on a JWT claim this system never issues.**
Migrations 059 (phase 7/8/9 intelligence layer), 067 (year-end) and 071
(workflow engine / AI copilot / AI memory) created 51 RLS policies of the
shape `USING (firm_id::text = auth.jwt()->>'firm_id')`. This project never
issues a `firm_id` JWT claim — every other firm-scoped table resolves it via
`get_my_firm_id()` (`SELECT firm_id FROM users WHERE auth_user_id = auth.uid()`,
migration 005/019). So the predicate is always NULL, always false: deny-all,
in every direction (no `WITH CHECK` existed, so `USING` governed inserts too).
Migration 127 had already fixed 8 of these (the lead/prospect pipeline) and
explicitly documented that the remaining 43 tables carried the identical
defect. **Fix:** migration **154** finishes that job — drops every old broken
policy (by every name it was ever created under, including the two tables,
`client_profiles`/`firm_profiles`, that had gained a *second*, differently-named
broken policy from 071 on top of 059's) and creates one canonical
`<table>_firm_isolation` policy per table using `get_my_firm_id()`, the same
proven pattern used on dozens of other tables. Existence-guarded via
`information_schema.tables` before every ALTER/DROP/CREATE (idempotent, and
safe against the documented 068/070 cascading apply failures some of these
tables' creating migrations carry).

**Reachability:** confirmed via a repo-wide grep that none of these 51 tables
are queried directly from `apps/web` — they are backend-only, and the backend
connects via the service-role client (bypasses RLS) whenever `USE_USER_JWT` is
off, which it is everywhere today (absent from `render.yaml`). So this was a
real but currently-unreachable defect; it matters the day `USE_USER_JWT` cuts
over (R2.4) and for any direct anon/authenticated-key access. Downgraded
accordingly, matching the audit's own "Partially confirmed (downgraded)"
status for F20.

**Verified on Postgres 16:** `test_migrations_apply.py`/`test_schema_contract.py`
pass, drift baseline unchanged at 11. A live functional proof on
`health_scores` (one of the 43 fixed tables, unaffected by any cascading
apply failure): before the fix, a query as an authenticated Partner returned
zero rows regardless of firm (deny-all); after, the same query returns
exactly the caller's own firm's row and correctly hides another firm's row —
firm isolation now actually works where it previously silently failed closed.
Also verified the `client_profiles`/`firm_profiles` policy consolidation left
exactly one canonical policy per table, not two. Cross-checked the fix's
table list against a fresh, independent regex scan of 059/067/071 for exact
1:1 coverage (43 tables needed, 43 covered, zero missing, zero extraneous).

**Migration hygiene — duplicate migration numbers.** Six pairs of migration
files share a number (045, 046, 94, 95, 96, 97 — discovered via the R0.1
runner's `duplicate_numbers` diagnostic). Investigated whether renumbering was
warranted: in every pair, neither file references a table/column the other
creates (no hidden ordering dependency), and the runner's alphabetical tiebreak
already applies them deterministically — the collision is a naming accident,
not a live correctness bug. Renumbering existing, already-merged migration
files is only fully safe once nothing has tracked them by filename in a live
`schema_migrations` table — and per this investigation, **this project's
production Supabase has never had the migration runner applied to it at all**.
Rather than renumber blind mid-audit, added `tests/test_migration_numbering.py`
— a database-free ratchet (same pattern as `EXPECTED_MIGRATION_FAILURES`) that
fails the moment a *new* migration reuses an existing number, so the known set
of 6 can't silently grow, and flags itself for update the day the known 6 are
finally renumbered (recommended as a one-time cleanup once production tracking
begins — see below).

**Repo-vs-live drift — NOT executed, needs a human with production access.**
The audit's "reconcile repo-vs-live drift" sub-item requires actually running
`apply_migrations.py` (or an equivalent schema diff) against the real
production Supabase project. This session has no production credentials, and
even with them, applying schema/RLS changes to a live production database
autonomously is exactly the kind of high-blast-radius, hard-to-reverse action
that requires a human decision, not an autonomous one. **Explicitly deferred,
not silently skipped:** someone with production DB access should run
`python scripts/db/apply_migrations.py --dsn <prod-dsn> --continue-on-error
--json`, compare its `failed`/`ok` output against the documented
`EXPECTED_MIGRATION_FAILURES` baseline, and apply migration 154 (this
milestone) plus any other still-missing migrations. Once that first live run
has happened, the six duplicate-number pairs above become safe to renumber
opportunistically.

**Verified:** full backend suite 2166 passed / 52 skipped (the same 23
pre-existing, unrelated `test_hardening.py`/`test_phase3_*.py` failures noted
in R2.5 remain, confirmed unaffected by this milestone — no Python code
changed, only a new migration and a new static test).

**Next:** R2.4 (tenancy DB backstop, F1/F4), R2.1 (year-end schema repair,
F9/F10), R2.3 (tax statutory logic, F17/F18).

## Milestone R2.4 — Database tenancy backstop, F1/F4 (DELIVERED, scope adjusted)

**Goal:** close F4's confirmed cross-tenant GSTR-9 IDOR and harden F1's
structural weakness (tenant isolation is app-layer discipline only).

**Scope decision, revalidated before implementing.** R2.4's roadmap text
offered two fix directions: execute the `USE_USER_JWT` cutover, or make
`firm_id` mandatory at the repository layer. Investigated both before writing
any code:
- **`USE_USER_JWT` cutover:** not attempted. It would flip the ENTIRE backend
  from service-role (bypasses RLS) to per-user-JWT (RLS-enforced) in one step
  — the single biggest architectural change this codebase could make. The
  investigation found several tables the backend touches have no `CREATE
  TABLE` in any tracked migration at all (`itr_filings`, `gst_returns`,
  `eway_bill_records`, `einvoice_records`, `xbrl_packages` — real schema drift,
  unverified against production), and there is zero automated RLS test
  coverage (every one of ~172 test files runs against a FakeDB double, never a
  real Postgres+RLS harness in CI). Flipping this in production without that
  coverage is a multi-week initiative, not a same-session fix, and is exactly
  the kind of high-blast-radius architectural decision this mandate's pause
  criteria describes — deferred, not attempted.
- **Mandatory `firm_id` at the repository layer:** investigated and found it
  would cover only a minority of the actual attack surface. `repositories/
  base.py` is a thin, largely-unenforced stub; only 28 of 94 routers even use
  the repository layer at all — the rest (including every endpoint this
  milestone actually fixes) call `get_supabase()`/`get_service_supabase()`
  directly (901 raw `.table()` calls across routers/services/domain vs. 30
  repository files). A repo-layer mandate would not have touched any of the
  three bugs below.
- **What was actually higher-leverage, and what got fixed:** `core/authz.py`'s
  central `can_access_client()` — the single authorization gate `require_
  client_access` already attaches to ~35 routers — had exactly F1's structural
  flaw baked in: `is_firmwide(user)` (Partner) returned `True` unconditionally,
  with **no check at all that the client actually belongs to the caller's own
  firm**. So the central guard that's supposed to prevent cross-tenant access
  was a no-op for any Partner who supplied a client_id from a different firm.
  Fixed by adding `_client_belongs_to_firm()` (reuses the existing, already-
  tested `client_repo.find_by_id(client_id, firm_id=...)`) as a prerequisite
  check before the firm-wide short-circuit. One function, ~35 routers
  immediately hardened.

**F4 and its two sibling IDORs — the systematic sweep this milestone was
actually scoped to.** Rather than fix only the audit's one cited GSTR-9
instance, searched every GST/TDS/income-tax/MCA/payroll/banking router for the
same shape of bug (a query keyed on a client-suppliable id, with no firm_id
filter and no ownership check anywhere in the function). Found three real
instances, all fixed:

- **`routers/payroll.py` `finalize_run`/`update_run_status`** — the more
  severe of the three: `payroll_runs` was looked up by `run_id` alone, then
  `finalize_run` posted a REAL, immutable general-ledger journal entry using
  the row's own `firm_id`/`client_id`. A Partner (payroll:finalize is
  Partner-only) from Firm B who knew/guessed Firm A's `run_id` could trigger
  Firm A's accounting postings. Fixed by scoping both queries with `.eq(
  "firm_id", current_user["firm_id"])`, and switching `finalize_run`'s lookup
  from `.single()` (raises/500s on zero rows) to `.maybe_single()` (cleanly
  404s) — which also fixes a latent robustness bug where a genuinely
  nonexistent run_id crashed instead of 404ing.
- **`routers/gst_workspace.py` `save_gstr9`/`get_gstr9`** (F4 as originally
  cited) — annual-return draft lookup/update scoped only by `client_id` +
  `financial_year` + `return_type`, no `firm_id`. Fixed by adding the missing
  `.eq("firm_id", ...)` to both.
- **`domain/income_tax/itr_workflow.py` `save_itr_version`** — the version-
  numbering lookup was scoped only by `itr_filing_id`, unlike its sibling
  `transition_itr_status` in the same file (which already correctly checks
  `.eq("id", filing_id).eq("firm_id", firm_id)`). Lower severity than the
  other two (no read of existing confidential content, no overwrite — a cross-
  firm caller could only pollute another firm's filing with a stray version
  row and observe its version count), but the same root cause. Fixed by adding
  an upfront `itr_filings` ownership check before touching version history at
  all, raising `ValueError("Filing not found")` (now mapped to HTTP 404 in
  `routers/itr_workspace.py`, which previously only had a blanket 500 handler).

**New finding, out of scope for this milestone, flagged for the roadmap:**
while fixing `itr_workflow.py`, found that its `_supabase()` helper imports
`core.supabase_client.get_supabase_client` — **a function that does not exist
anywhere in this codebase.** The same non-existent import is used by 8 other
files (`routers/form_26as.py`, `domain/gst/portal_service.py`, `domain/
income_tax/{einvoice,eway,xbrl,form26as}_service.py`, `domain/income_tax/
computation_workspace.py`, `domain/tally/migration_service.py`). Every one of
these calls is gated behind `if _USE_MOCK:` branches, which is exactly why 172
test files never caught it: nothing in CI ever runs these modules against a
real (non-mock) Postgres connection. **This means ITR workflow, e-invoice,
e-way bill, XBRL, 26AS reconciliation, GST portal sync, and Tally migration
are all completely non-functional in any real (`SUPABASE_URL` set) deployment
today** — an `ImportError` on the very first non-mock call. This is a distinct,
severe, already-confirmed production-breakage finding (not a security/tenancy
issue) that deserves its own dedicated milestone to fix properly (define what
`get_supabase_client` should actually do — a plain alias for `get_supabase()`,
or the per-user-JWT-aware variant — then fix all 9 call sites and add a CI
guard so a phantom import like this can never hide behind mock mode again).
Tracked as a new Tier 2/3 candidate; see roadmap.

**Verified:** `test_authz_engine.py` (16 tests, 3 new regression locks proving
a Partner/Manager cannot pass `can_access_client` for another firm's client)
and `test_multiuser_authz_validation.py` (21 tests, updated to stub the new
`_client_belongs_to_firm` check) both pass. New `test_tenancy_backstop.py` (9
tests) proves both directions for all three fixed endpoints: the legitimate
same-firm case still succeeds, and the cross-firm case is cleanly denied (404,
or — for the GSTR-9 read — a `null` payload) with no partial writes. Full
backend suite: 2178 passed / 52 skipped (the same 23 pre-existing, unrelated
failures noted since R2.5 remain, reconfirmed unaffected).

**Next:** R2.1 (year-end schema repair, F9/F10), R2.3 (tax statutory logic,
F17/F18), the newly-found `get_supabase_client` production breakage.

## Milestone R2.1 — Repair year-end workflow schema, F9/F10 (DELIVERED)

**Goal:** every year-end close endpoint (engagements, checklist, adjustments,
mappings, notes, reviews, exports, statements) currently 500s in a real
deployment — make the whole module actually work against Postgres, and fix
the Balance Sheet's silent prior-year data loss for multi-year clients.

**F9 — schema drift, all 8 of migration 067's tables.** The audit's own
evidence only cited 3 wrong table names (already tracked in
`test_schema_contract.py`'s baseline); revalidating against 067's actual
`CREATE TABLE` definitions found the real scope is much larger — **every one**
of the 8 year-end tables has at least one column the router code needs but
067 never created, several of which are **NOT NULL**, meaning the very first
write on each table would fail. Root-caused by reading 067 in full alongside
every `routers/year_end*.py` file line by line (not just grepping table
names), then **proved on real Postgres 16** with the exact 8 INSERT payloads
each router now builds — every one succeeded only after two additional gaps
that grep alone couldn't find (a CHECK-constraint vocabulary mismatch and a
genuinely missing column) were caught by that live testing and fixed. Fixed
via migration **155** (additive `ADD COLUMN IF NOT EXISTS` / idempotent
`RENAME COLUMN`, all existence-guarded) plus corresponding code fixes:

- **Wrong table names** (already tracked): `year_end_checklist_items` →
  `year_end_checklists`, `year_end_notes` → `notes_to_accounts` (fixed in
  `year_end_notes.py` **and** a second, previously-unnoticed reference in
  `year_end_exports.py`'s `_get_notes_data`), `year_end_review_events` →
  `year_end_reviews`.
- **Missing NOT NULL columns the router never populated** (would 500 on
  every insert): `year_end_adjustments.client_id` (now derived from the
  already firm-validated engagement, never trusted from client input);
  `account_group_mappings.account_name`/`statement_type` (NOT NULL relaxed —
  the mapping request body has no account_name, and statement_type is now
  derived in code from `schedule_line` via a `_statement_type_for()` helper
  that reuses `year_end_financial_service`'s own BS/PL line classification,
  not a second copy of it); `notes_to_accounts.note_number` (now populated,
  matching the existing `sequence_no`).
- **Two more mismatches surfaced only by the live-Postgres proof, invisible
  to a pure code/migration diff:** `year_end_checklists`' status CHECK
  constraint allowed `not_started`, but the router's `_STANDARD_ITEMS` /
  `_VALID_ITEM_STATUSES` has always written `pending` — every checklist
  auto-initialization (the first thing that happens when any new engagement's
  checklist is opened) would have violated it. Fixed by widening the CHECK
  to the vocabulary the code actually uses (nothing else references
  `not_started`). `account_group_mappings` had **no `updated_at` column at
  all** in 067 (only `created_at`), while the router updates it on every
  write — fixed by adding it.
- **`year_end_reviews`' `review_type`/`action` CHECK-constrained columns**
  don't cover this router's actual event vocabulary
  (`submitted_for_review`/`revision_requested`/`final_approved_and_locked` vs.
  067's `prepared`/`reviewed`/`approved` × `submitted`/`approved`/`rejected`/
  `revision_requested`). Rather than force-fit or widen a CHECK meant for a
  different (never-built) structured review model, added `event_type`/
  `actor_id` as the columns the code actually needs and relaxed the two
  NOT NULL constraints on the unused columns (`reviewed_by`, also NOT NULL,
  **is** populated).
- **Column renames chosen by majority usage, not left as two parallel
  columns:** `year_end_exports.file_path` → `storage_path` (the router uses
  `storage_path` exclusively, extensively, and has zero other consumers,
  grep-confirmed) via an idempotent rename; `year_end_statements.py`'s
  `statements_data` was simply a typo for 067's actual `statement_data` —
  fixed in code, not the schema.

**Two tenancy gaps found and fixed alongside (same bug class as R2.4's F1/F4,
found while re-reading these routers line by line for F9):**
- `routers/year_end_checklist.py`'s `list_checklist`/`update_checklist_item`
  had **zero** firm-ownership check on `engagement_id` — any authenticated
  year-end user could read or mutate another firm's checklist by guessing an
  engagement id. Fixed with a `_fetch_engagement_db` guard (same pattern
  already used correctly by every sibling year-end router) before any
  checklist read or write.
- `routers/year_end_mappings.py`'s `get_mappings` accepted a **client-supplied
  `?firm_id=`** query param and used it verbatim, with zero ownership check —
  a direct, one-request cross-tenant read of another firm's Schedule III
  account mappings. Fixed by removing the override entirely; there is no
  legitimate reason a normal (non-platform-admin) user needs another firm's
  mappings.

**F10 — Balance Sheet dropped prior-year carry-forward.**
`year_end_financial_service.generate_financial_statements` applied the same
FY date window (`gte(fy_start).lte(fy_end)`) to every account uniformly —
correct for P&L (income/expense, which resets each year) but wrong for
Balance Sheet accounts (assets/liabilities/equity, which carry a cumulative
balance across every prior year). A multi-year client's Balance Sheet showed
only the current year's movement, silently dropping everything before it.
Investigated whether `domain/reporting/service.py`'s already-correct
`ReportingService` (which does exactly this cumulative-vs-windowed split
correctly, via `snapshot(firm_id, client_id, None, as_of)`) could just be
swapped in — decided against a full swap: its Schedule III grouping is driven
by a fixed internal account-type resolver, while year-end's is driven by each
firm's own configurable `account_group_mappings`, and every downstream
consumer (PDF generation, notes auto-generation, complete-pack export) keys
off the current output shape. Fixed the actual bug surgically instead:
fetch journal lines in **two** windows (FY-only for P&L, cumulative-to-`fy_end`
for BS) and pick the correct one per account by its `schedule_line`
classification — same output shape, same downstream contract, zero
FakeDB/PDF/notes code touched.

**Deliberately NOT solved here (a distinct, deeper architectural gap, flagged
not fixed):** the codebase has no explicit "close the year" journal-posting
mechanism that transfers a completed year's P&L into `reserves_and_surplus`.
The existing (and unchanged) "add current-year PAT to reserves" step is a
live, presentational preview, not a posted accounting fact — so a **second**
prior year's retained profit, if that year was also never explicitly closed,
would still be invisible in a third year's cumulative reserves figure. This
is a real accounting-process question (should closing happen automatically at
engagement-lock time? does the CA need to approve the specific closing
narration? which reserves sub-account?) that requires a business/accounting
decision, not a unilateral implementation choice — tracked as a roadmap item,
not implemented.

**Also noted, not fixed (architecture, not correctness):** `routers/
year_end.py`'s generic `PATCH /engagements/{id}/status` and `routers/
year_end_reviews.py`'s four specific `POST /reviews/*` endpoints are two
**parallel, competing implementations** of the same draft→in_review→
approved→locked transition, writing overlapping-but-different column sets to
the same `year_end_engagements` row. Both now work (migration 155 added
columns for both), but the duplication itself is a maintainability smell
worth consolidating in a future pass — not attempted here to keep this
milestone's diff to "make it correct," not "also redesign it."

**Verified:** migration 155 applies cleanly on Postgres 16, drift baseline
unchanged at 11. Live-Postgres proof: all 8 tables' exact insert payloads
(matching the fixed router code precisely) succeed on a fresh database — this
is what caught the two mismatches (`year_end_checklists` status CHECK,
`account_group_mappings.updated_at`) that a pure text diff against 067 missed.
`test_schema_contract.py`'s 3 resolved F9 baseline entries removed (ratchet
ready to catch any regression). New `test_year_end_financial_service.py` (4
tests) proves F10 directly: prior-year-only BS postings still appear in a
later year with zero current-year activity; P&L stays correctly FY-windowed
and does not leak across years; a BS account with both prior- and
current-year postings sums both; cross-client/cross-firm lines never bleed
in. New `test_year_end_tenancy.py` (4 tests) proves both tenancy fixes in
both directions (legitimate same-firm access still works; cross-firm access
is denied, with no partial state change). Full backend suite: 2186 passed /
52 skipped (the same 23 pre-existing, unrelated failures noted since R2.5
remain, reconfirmed unaffected).

**Next:** R2.3 (tax statutory logic, F17/F18), R2.2 (missing tables, F5), the
`get_supabase_client` production breakage (R2.4's finding), the year-end
closing-mechanism and duplicate-implementation follow-ups noted above.

## Milestone R2.3 — Correct TDS & ITR statutory logic, F17/F18 (DELIVERED)

**Goal:** the same income-tax slab/rebate/surcharge numbers were hand-copied
into five places (backend ITR engine, backend payroll §192, three frontend
files) and had drifted to three different FYs' law — one copy (the
income-tax deductions page) also carried a 10× paise-scaling bug that made
every slab boundary wrong by an order of magnitude (F18); the vendor-payment
TDS engine (F17) had stale pre-2025 thresholds, float arithmetic, and a
nonexistent "April 31" Q4 due date. Rebuild all of it as FY-versioned data
with one source of truth per domain.

**Governing product decision (explicit user instruction, obtained by pausing
mid-milestone):** FY 2025-26 is the verified statutory baseline; FY 2026-27
must NOT be invented — its entries are carried forward from FY 2025-26 with
an explicit `verified=False` flag, surfaced through the API (`rates_verified`
on `/api/income-tax/compute`, `/api/tds/compute-amount`, `/api/tds/sections`,
and a 26Q builder warning) so a CA sees "pending statutory verification"
rather than silently trusting unconfirmed numbers. Updating a year to
verified figures is a pure data change in one file per domain.

**New single sources of truth (rules as data — this also front-loads the
core of R3.1):**
- `domain/income_tax/statutory_rates.py` — FY-versioned slabs (new regime +
  old general/senior/very-senior), regime-specific standard deductions,
  §87A rebate rules (threshold/cap/`marginal_relief` flag), surcharge
  brackets with the new-regime 25% cap and the capital-gains 15% cap, cess;
  plus pure integer-paise helpers (`slab_tax_paise`, `apply_rebate_87a`,
  `apply_surcharge_with_marginal_relief`, `resolve_surcharge_bracket`,
  `cess_paise`) shared by every consumer.
- `domain/tds/section_rates.py` — FY-versioned vendor-TDS thresholds/rates
  in integer basis points, and `quarter_dates(fy, quarter)` computing the
  24Q/26Q calendar for ANY year per Rule 31A.

**F18 (ITR engine + deductions page) fixes:**
- Old regime standard deduction corrected to ₹50,000 (was applying the new
  regime's ₹75,000 to both regimes — Section 16(ia) has been ₹50k for the
  old regime since Finance Act 2019).
- §87A rebate: marginal relief added for the NEW regime (the famous Budget
  2025 example — taxable ₹12,10,000 → tax ₹10,000, not ₹61,500 — passes
  exactly). The old regime is a statutory hard cliff (no 115BAC(1A)
  proviso): crossing ₹5,00,000 forfeits the whole ₹12,500. Encoded as data
  (`RebateRule.marginal_relief`), not a code branch.
- Surcharge: Section 2(29C) marginal relief on the slab component (crossing
  ₹50L by ₹10,000 can never cost more than ₹10,000 extra), new-regime cap
  at 25%, and the 15% cap on ALL capital-gains tax — 111A/112A (FA 2019)
  and Section 112 LTCG on any asset (FA 2022). Flat-rate CG tax gets the
  flat capped bracket rate; only slab tax rides the marginal-relief math.
- `fy` request field + `fy`/`rates_verified` response fields end to end
  (engine dataclasses → Pydantic models → frontend types).
- `apps/web/app/income-tax/deductions/page.tsx` — the file with the 10×
  scaling bug (`const L = 100 * 100` treating ₹1L as ₹10,000, so e.g. the
  ₹4,00,000 nil band ended at ₹40,000) — no longer computes ANY tax. Its
  duplicate engine (which also wrongly granted HRA exemption against
  new-regime income) is deleted; it now POSTs to `/api/income-tax/compute`
  twice (one call per regime, debounced 400ms), renders the backend's
  deduction/eligibility figures, shows an "unverified FY" banner off
  `rates_verified`, and saves through `saveTaxPlanningRecord` instead of a
  raw browser upsert that previously wrote to a nonexistent `fy` column
  with a mismatched conflict target — two more latent bugs fixed in
  `lib/data/income-tax.ts`: `computeITR()` sent no Authorization header
  (would 401 against any real deployment) and the upsert's `onConflict`
  omitted `firm_id`, not matching the table's actual
  `UNIQUE (firm_id, client_id, financial_year)`.

**F17 (payroll §192 + vendor TDS) fixes:**
- `routers/payroll.py::_compute_tds_192` — was float arithmetic end to end
  (`rupees = paise / 100`, `tax * 1.04`) on FY 2024-25 slabs with no §87A
  and no surcharge; now integer paise via the registry, with rebate +
  marginal relief + surcharge + marginal relief + cess (an employee at ₹5L
  annual taxable now correctly withholds ZERO — the rebate zone — instead
  of ₹866/month). `_compute_slip`'s hardcoded ₹50,000 "(Finance Act 2018)"
  standard deduction → the FY's new-regime ₹75,000 (payroll withholding
  defaults to the new regime per 115BAC(1A)). `create_payroll_run` derives
  the FY from the payroll month, not "today", so a delayed March run posted
  in April uses the right year's law.
- `domain/tds/tds_computer.py` — `SECTION_THRESHOLDS` is now a derived
  legacy view of `section_rates.py`; thresholds updated to Finance Act 2025
  (193/194/194A/194K → ₹10k, 194D/G/H → ₹20k, 194I → ₹50k/month, 194J →
  ₹50k, 194LA → ₹5L; 194C's ₹30k/₹1L-aggregate unchanged) and rates to
  Finance (No. 2) Act 2024 (194D-individual/194G/194H 5% → 2%).
  `compute_tds_amount` (the `/api/tds/compute-amount` calculator) delegated
  to `resolve_tds` — killing its `paise * float_rate` arithmetic AND its
  ignoring of the 194C aggregate. Both take an optional `fy`;
  `purchase_bills.py` passes the BILL's FY (derived from bill_date), so a
  late-entered prior-year bill resolves that year's thresholds.
- Quarter calendar: the FY2025-26-pinned `QUARTER_DATES` dict is gone —
  `quarter_dates(fy, quarter)` computes any year. `routers/
  tds_workspace.py::_tds_return_due_date` no longer returns Q4 =
  `"{start_year}-04-31"` — a date that does not exist, in the wrong month
  AND wrong year (FY2025-26 Q4 was "2025-04-31"; statutory is 2026-05-31
  per Rule 31A). CLAUDE.md's "31st of month following quarter end" summary
  is documented at the fix as not literally applicable to Q4.
- Frontend payroll: the two independently-drifted client-side §192
  calculators (payroll/page.tsx — FY2023-24-ish ₹7L rebate ceiling, no
  surcharge; payroll/reports/page.tsx — ad-hoc slab boundaries matching no
  real FY) are consolidated into ONE shared module
  (`lib/services/payrollTdsEstimate.ts`) with FY 2025-26 figures
  value-for-value cross-verified against the Python engine at 13 income
  levels spanning every slab and surcharge bracket (exact match including
  marginal-relief and 25%-cap zones), plus the stale "≤ ₹7,00,000" help
  text corrected to the FY 2025-26 ₹12L ceiling.

**Adversarial review (fresh-context reviewer instructed to refute):** six
findings, all resolved or expressly tracked —
1. *Confirmed real (high):* my first pass wrongly generalized §87A marginal
   relief to the OLD regime (understating tax by up to ~₹14.5k in the
   ₹5,00,001–₹5,15,625 window). The statute conditions the proviso on
   115BAC(1A). Fixed via the `marginal_relief` data flag; the two tests
   that had enshrined the wrong behaviour now assert the cliff.
2. *Confirmed real (high, documentation):* the shared frontend TDS module's
   docstring claimed the backend is "the authoritative persisted
   computation" — false for `/payroll`'s Generate Payslips, which still
   persists browser-computed slips via direct Supabase inserts (the
   clients/[id]/payroll page correctly posts to `/api/payroll/runs`).
   Docstring rewritten to state this honestly; the actual migration stays
   R2.10 (already tracked, deferred pending frontend test infra).
3. *Confirmed real (medium):* stale ₹7L rebate text on the reports page —
   fixed (above).
4. *Confirmed real (medium):* Section 112 LTCG-other tax was folded into
   the slab marginal-relief bucket, contradicting the code's own rationale
   for excluding equity CG — and understating the statutorily correct
   treatment anyway, since FA 2022 caps 112's surcharge at 15%. Fixed: all
   flat-rate CG (111A/112A/112) now takes the capped flat bracket rate;
   new regression test proves the 112 component pays exactly 15% while the
   assessee's ordinary income pays 25%.
5. *Confirmed real (low-medium):* every keystroke on the deductions page
   fired two backend calls — 400ms debounce added (reviewer verified the
   cancellation flag already prevented stale-response races).
6. *Valid, pre-existing, out of scope:* Section 80CCD(2) (employer NPS) is
   entirely unimplemented — notable because it IS deductible under the new
   regime, unlike the rest of Chapter VI-A. Tracked as a roadmap follow-up,
   not silently ignored.

**Also documented, deliberately not fixed here:** the dead
`tds_section_limits` table (migration 037 — zero runtime readers; candidate
for retirement in R3.1 or a migration-hygiene pass); Section 206AB's
possible omission by Finance Act 2025 (the non-filer doubled-rate check in
`tds_validator.py` may be obsolete for FY 2025-26 — needs verification
against the Act before changing a compliance-conservative behaviour); the
capital-gains rates themselves (111A 20%, 112A/112 12.5%, ₹1.25L exemption)
remain inline constants in `itr_engine.py` — correct today (Budget 2024)
but belonging in the FY registry when R3.1 generalises it; the deductions
page still writes `tax_planning_records` from the browser (RLS-protected,
and now writing correct backend-computed numbers, but portal-write
consolidation belongs with R2.10's frontend-persistence cleanup).

**Verified:** 2,248 backend tests pass (24 new in
`test_tds_section_rates.py`, 43 in the rewritten `test_itr_engine.py`, 26 in
`test_statutory_rates.py`; the same 23 pre-existing DB-dependent failures
noted since R2.5 remain, re-confirmed unrelated by running them against the
pre-change tree). Statutory worked examples pass exactly: the Budget 2025
₹12,10,000 → ₹10,000 marginal-relief illustration; the old-regime ₹5,10,000
cliff (₹14,500, rebate forfeit); ₹20L new-regime cess arithmetic; the 194C
five-bill aggregate-threshold sequence; Q4 due date 31 May of the FY's end
year for any FY. TS port cross-verified value-for-value against the Python
engine (13 income levels). Frontend: `tsc --noEmit` clean, ESLint clean,
`next build` succeeds (165 pages).

**Next:** R2.2 (missing tables, F5), R2.7 (workflow engine, F11/F12), then
the remaining Tier 2 sequence; 80CCD(2), 206AB verification and the CG-rate
registry move queue behind R3.1/R2.10 as noted.

## Milestone R2.2 — Create the missing tables + close the F5 backlog (DELIVERED)

**Goal:** every table/RPC the backend references that no migration ever
created. The audit said "~13"; re-verification against the current tree found
the true scope is **24 phantom table names + 2 missing RPCs** (exactly the
baseline R0.1's `test_schema_contract.py` had pinned), plus a blocking
interaction: 15 of those tables sit behind an import of
`core.supabase_client.get_supabase_client` — an accessor that **does not
exist** (R2.4's flagged production breakage), so those modules died with
ImportError before any SQL could even fail.

**What shipped:**
- **Migration 156** creates 21 tables: the 13 income-tax/GST-workspace tables
  (itr_filings, itr_filing_versions, tax_computation_snapshots,
  tax_disallowances, tax_deduction_claims, brought_forward_losses,
  einvoice_records, eway_bill_records, xbrl_packages, gst_sync_jobs,
  gst_portal_snapshots, form_26as_records, form_26as_reconciliations), 2
  Tally tables (tally_migration_jobs incl. a nullable target `client_id`,
  tally_migration_items), and 6 others (onboarding_checklists,
  onboarding_checklist_steps, pending_invites,
  entity_to_entity_relationships, properties, client_portal_sessions) — each
  with gen_random_uuid PK, `firm_id NOT NULL` FK→firms, the standard
  `firm_id = get_my_firm_id()` RLS policy (DROP-first, idempotent), grants,
  and hot-path indexes; all money BIGINT integer paise. Column sets were
  derived from the exact payloads the referencing code builds and **proven on
  real Postgres 16** by inserting those payloads (fresh-database AND
  re-application/upgrade paths both green; the re-apply proof caught a
  CREATE-TABLE-IF-NOT-EXISTS no-op hiding a new column — fixed with a
  155-style ADD COLUMN IF NOT EXISTS self-heal).
- **Three phantom names got code fixes, not tables** — the audit's
  gst_returns/notices/work_items never deserved to exist: real data lives in
  gstr3b_returns, government_notices and tasks. routers/health.py now reads
  those with their true columns and status vocabularies ('open'/
  'in_progress' not "Open"; response_due_date/issue_date;
  tasks.status='in_progress'), and derives GSTR-3B overdue-ness from the
  MMYYYY period + the statutory due date (20th of the following month) since
  gstr3b_returns has no due-date column. Every one of these health queries
  was try/except-swallowed — they never 500'd, they silently mis-scored
  client health for years of operation.
- **client_portal_sessions got a writer, not just a table** — nothing ever
  inserted rows (the health "responsiveness" signal would have stayed
  permanently empty). core/portal_auth.py's get_current_portal_client (the
  choke point every portal request passes) now records a best-effort,
  6-hour-debounced session touch that can never fail the request.
- **The accessor fix**: all 10 files importing the nonexistent
  get_supabase_client now import the canonical get_supabase — un-dead-ending
  the ITR workspace, e-invoice, e-way, XBRL, GST portal sync, 26AS and Tally
  routers in production.
- **Two RPCs**: get_cash_payments_above_threshold (Section 40A(3) cash-scan
  over POSTED journal lines joined to cash-named chart_of_accounts; SECURITY
  DEFINER with parameter-bound firm/client predicates) and
  increment_message_count (F19; parameter named conv_id to match the
  PostgREST caller).
- **Caller-controlled column spread closed**: tax_computation_snapshots'
  insert used to spread the request's raw `income` dict as columns (any
  unknown key = broken insert). Now whitelisted through `_INCOME_COLUMNS`
  (10 keys, matching the DDL and the actual frontend payload field-for-field).
- **Tally migration made real**: created_record_type is now persisted
  (rollback was a silent no-op — it deleted by a column nothing ever wrote);
  rollback/execute are firm-scoped with an ownership check first
  (cross-firm job ids now 404; previously, once tables existed, any
  authenticated user could roll back another firm's import), and rollback
  deletes only from a {customers, vendors} allowlist.

**Adversarial review (fresh-context) — two real findings, both fixed:**
1. Customer/vendor imports would fail at runtime: customers/vendors.client_id
   is NOT NULL (migration 049) but the importer supplied none and the job
   had no client concept at all. Fixed end-to-end: jobs accept an optional
   firm-validated target client_id, the importer threads it through, and
   client-less jobs refuse customer/vendor items with an actionable error
   instead of an opaque constraint violation.
2. increment_message_count returned void while its caller wrote
   `.data or 0` back into message_count — every message would have reset
   the conversation's count to zero. Fixed both ends: the RPC returns the
   new count (single atomic statement) and the caller no longer wraps the
   RPC in a second, destructive update.

**Ratchet closed:** test_schema_contract.py's KNOWN_MISSING_TABLES and
KNOWN_MISSING_RPCS are now **empty sets** — any future phantom reference
fails CI immediately instead of joining a backlog.

**Verified:** 2,255 backend tests pass (same 23 pre-existing DB-dependent
failures, reconfirmed unrelated); real-Postgres proof of every new table's
exact code payloads on both a fresh database (149 migrations applied; the
same 11 pre-documented R2.6 drift failures, nothing new) and the
upgrade/re-apply path; migration-apply harness tests pass; all changed
modules import clean.

**Documented, not fixed here:** pending_invites' token remains write-only
(tracked with the R2.5 follow-ups); onboarding_checklists' RLS uses the
firm-id predicate while a couple of step reads filter by workflow_id only
after a firm-checked parent fetch (acceptable — same pattern as sibling
child tables, RLS backstops it); ~57 migration-created tables have no
backend reader (some may be frontend-PostgREST-reached — F14's concern —
flagged for the Tier 2 regression review, not dropped).

**Next:** R2.7 (workflow engine, F11/F12), R2.8 (AI extraction + F19's
remaining scope), R2.9 (document numbering), R2.11 (bank parser), R2.12
(receipt atomicity), then the Tier 2 regression review.

## Milestone R2.7 — Make the workflow engine actually execute, F11/F12 (DELIVERED)

**Goal:** the audit's F11 (list endpoints 404) and F12 (engine actions are
stubs) both still held on re-verification, and the investigation traced the
real breakage further than either finding stated: migration 068 (the Phase-10
engine's own schema) never fully applies on a fresh database — its
`workflow_steps` CREATE silently no-ops against 002's legacy same-named
table, then its index on the never-added `template_id` column errors and
aborts the file, so `workflow_instances`/`action_logs`/`executions`/
`failures`/`approvals`/`schedules` never exist and 071's RLS pass fails in
cascade. Only `workflow_templates` (created before the abort) survived, with
no RLS ever enabled on it.

**Schema repair — migration 157** (R2.1/155-pattern: additive, never edits
068/071, which stay in the documented `EXPECTED_MIGRATION_FAILURES`
baseline): reconciles 002's `workflow_steps` to 068's engine shape via
`ADD COLUMN IF NOT EXISTS` (template_id/step_type/name/description/config/
next_step_id/true_branch_step_id/false_branch_step_id) and existence-guarded
`DROP NOT NULL` on the legacy workflow_id/step_name columns (068's dead
`workflow_triggers`/`workflow_conditions` deliberately NOT created — the
engine reads trigger_type/conditions straight off the template's JSONB;
zero code ever referenced those two tables); creates the six tables 068
never managed to (workflow_instances — plus `idempotency_key`, which 068
never had but the repository requires — action_logs, executions, failures,
approvals, schedules); adds RLS + grants across every workflow table
(steps/action_logs scoped via `EXISTS` to their owning template/instance,
since neither carries its own firm_id).

**F11 — routing.** Deleted `routers/workflows.py`: three endpoints of
hardcoded, never-persisted fake data (`GET /{id}`, `POST /{id}/instantiate`)
whose catch-all shadowed every single-segment GET on the shared
`/api/workflows` prefix — `/templates`, `/instances`, `/approvals`,
`/schedules`, `/analytics`, `/failures`, `/executions` all 404'd regardless
of the real `workflow_builder_router`'s own registration. Zero frontend
callers (confirmed by grep); the dead `lib/api/index.ts` client stub
pointing at the deleted endpoints removed too.

**F11 — four router→repository signature mismatches**, proving the
builder's write paths had never been exercised end to end: `cancel_instance`
called `update_instance_status` without `firm_id`; `respond_to_approval`
passed `response_notes`/`responder_id` in swapped positions (the responder's
UUID was landing in the notes column and vice versa); `create_schedule`
passed the whole request payload as the `template_id` positional; `toggle_schedule`
passed a phantom third boolean argument. All four were TypeErrors/silent
corruption, not merely untested — fixed with explicit keyword arguments at
every call site.

**F12 — real actions.** `_execute_action`'s `create_task` and
`send_notification` now write actual rows via `task_repo`/
`notifications_repo` (previously every action type, including these two,
fabricated an id like `task-wf-{uuid}` and wrote nothing — a workflow could
"complete successfully" having done none of what its steps claimed). Every
other action type (`send_email`, `archive_client`, `create_proposal`, the AI
actions, …) has no real implementation yet and now says so explicitly — an
`_action_status: skipped` sentinel the step runner logs as
`workflow_action_logs.status = 'skipped'`, never `'success'`, so analytics
stays honest about what actually ran. `create_task` requires a client
(`tasks.client_id` is NOT NULL) and fails loudly rather than silently
succeeding when the instance has none.

**Scheduler linkage.** `run_due_schedules` existed and was fully wired to
`workflow_schedules`/the engine, but was never registered with APScheduler —
cron-based workflow schedules could not fire under any circumstance. Now
ticks every minute via `jobs/scheduler.py::start_scheduler`.

**Adversarial review (fresh-context reviewer instructed to refute) — four
real findings, all fixed:**
1. *Critical:* migration 157's notification-CHECK widen (for the new
   `send_notification` action's `type='workflow'`) rebuilt the constraint
   from migration 004's original 6-type list — silently REVERTING migration
   122's later widen (`task_reassigned`/`due_soon`/`overdue`/
   `task_overdue`/`recurring_generated`, added after those exact types were
   found to cause 100%-silent notification-write failures in production).
   Fixed: 157's list is now a strict superset of 122's, proven by inserting
   one row of every one of 122's five added types plus `'workflow'` after
   157 applies.
2. *High:* registering the tick didn't make schedules actually fire —
   `create_schedule` left `next_run_at` NULL forever (nothing else ever set
   it, and `list_schedules_due` only matches non-NULL), `run_due_schedules`
   fired every active `'scheduled'`-type template in the firm by
   `trigger_type` instead of the one template each schedule's
   `template_id` actually points to (both over-firing unrelated templates
   and under-firing — recording a false "success" — for any schedule whose
   target declared a different trigger_type), and `_compute_next_run` used
   `croniter`/`pytz`, neither ever added to requirements.txt, so every call
   silently hit the except branch and fell back to "now + 1 day" — no cron
   expression was ever actually honored. Fixed: `create_schedule`/
   `toggle_schedule` (on activation) seed `next_run_at` from the cron
   expression; `fire_trigger` gained a `template_id` parameter that
   `run_due_schedules` uses to target the schedule's own template
   exclusively; `_compute_next_run` rebuilt on APScheduler's own
   `CronTrigger.from_crontab` + stdlib `zoneinfo` — zero new dependencies,
   real cron parsing. A second, same-class pytz fallback in
   `_past_scheduled_hour` (scheduler health reporting) fixed identically.
3. *Medium (security):* the new real-write actions bypass the tenancy
   guard every other write path enforces — `create_task`'s `client_id` and
   `send_notification`'s `user_id` came from the manually-triggerable
   endpoint's unvalidated request payload, so a task-write user could bind
   a task/notification to another firm's client/user by simply naming its
   id in the trigger call. Fixed: both actions now verify the id belongs to
   the executing firm (matching `routers/tasks.py`'s existing guard) before
   writing, raising a validation error otherwise.
4. *Medium:* a deterministic validation failure (missing client, cross-tenant
   id) was going through the generic retry path — 3 attempts, exponential
   backoff, ~6 seconds blocked, three duplicate `workflow_failures` rows for
   one non-retryable error, repeatable every minute once a schedule targets
   such a template. Fixed: a new `WorkflowStepValidationError` bypasses
   retry entirely (same treatment as `_ApprovalPause`), logging exactly one
   failure and failing the instance immediately.

**Verified:** 2,277 backend tests pass (66 in the workflow suites, 13 of
them new route-level tests hitting the REAL `main.app` — proving the F11
routing fix end to end, not just via a per-router test app — plus new
scheduler-targeting, retry-classification, and tenancy-guard tests; same 23
pre-existing DB-dependent failures, reconfirmed unrelated). Real-Postgres
proof of every new/repaired table's exact code payloads, on both a fresh
database (150 migrations applied; the same pre-documented drift failures,
nothing new) and the upgrade/re-apply path (migration 157 applied twice
cleanly, including over a database that had an earlier draft of itself).
`tsc --noEmit` clean after the frontend client-stub removal.

**Next:** R2.8 (AI extraction + F19's remaining scope), R2.9 (document
numbering), R2.11 (bank parser), R2.12 (receipt atomicity), then the Tier 2
regression review and Tier 3.


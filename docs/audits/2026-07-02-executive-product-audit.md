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

**R2.1 — Repair the year-end workflow schema (F9, F10).** Rename router table/column refs to match migration 067 (or ship a corrective migration), fix the FY-window Balance Sheet to carry prior-year balances, add NOT-NULL `client_id`. *Effort:* L. *Deps:* R0.1. *Benefit:* year-end close works and statements are correct.

**R2.2 — Create the ~13 missing tables or gate the features (F5).** Add migrations for e-invoice/e-way/XBRL/ITR-filing/26AS-record tables (and the missing RPC/columns), or feature-flag those modules off until backed. *Effort:* L. *Benefit:* removes 500s; makes the tax-record features real.

**R2.3 — Correct TDS & ITR statutory logic (F17, F18).** Rebuild thresholds as FY-versioned data (see R3.1); apply annual-aggregate correctly; ₹50k old-regime SD; §87A marginal relief; surcharge marginal relief + 15% CG cap; delete the frontend slab re-implementation. **Also (from the R1.2/R1.3 reviews): update to the CURRENT financial year with authoritative sourcing — Budget 2025 revised the new regime, and the backend `_compute_tds_192`/payroll `_compute_slip` still use FY 2024-25 with a stale ₹50,000 standard deduction (new regime is ₹75,000); add surcharge above ₹50L. Elevate F18 (income-tax deductions page `L = 100*100` → tax-slab boundaries 10× off, re-confirmed effectively a blocker for that page) to the front of this item.** *Effort:* L. *Benefit:* correct tax numbers, in step across backend and frontend.

**R2.4 — Add a database tenancy backstop (F1, F4).** Either execute the staged `USE_USER_JWT` cutover (after R2.6 fixes the RLS predicate) or make `firm_id` mandatory at the repository layer so a missing filter fails closed; add the missing `firm_id` filters (GSTR-9 et al.). *Effort:* L. *Benefit:* one mistake no longer equals a silent cross-firm leak.

**R2.5 — Close the `/join` privilege escalation and portal-invite gaps (F21, F22).** Move `/join` account-linking to a backend endpoint validating a signed single-use invite token; add tokenized, expiring portal invites. *Effort:* M. *Benefit:* removes the most exploitable security holes.

**R2.6 — Fix RLS predicates and migration hygiene (F20 + drift).** Correct policies that key on the never-issued `firm_id` claim; add a migration runner + tracking table; reconcile repo-vs-live drift; resolve duplicate migration numbers. *Effort:* M–L. *Benefit:* makes the eventual RLS cutover safe and schema state knowable.

**R2.7 — Wire the workflow engine or hide it (F11, F12).** Register `workflow_builder_router` before the legacy catch-all (or constrain the `/{id}` route); implement real actions, or feature-flag the module off until done. *Effort:* M. *Benefit:* automation is honest.

**R2.8 — Make AI extraction real (F19).** Pin `groq` in `requirements.txt`; create the missing `increment_message_count` RPC; stop persisting mock-derived notices/tasks; surface extraction failures instead of fabricating. *Effort:* M. *Benefit:* the AI value prop stops silently faking data.

**R2.11 — Bank statement parser hardening** *(pre-existing, surfaced by the R1.5 regression review).* `domain/banking/normalizer._to_paise` uses `rstrip("DrCr")`, which is case/char-set sensitive and zeroes balances suffixed `CR`/`DR`/lowercase; single signed-Amount + Dr/Cr-indicator statement layouts are unsupported and misparse every row as a debit; `Dr` (overdraft) balances lose their sign (stored same as `Cr`); and statement opening/closing balances are taken by file position, which inverts on newest-first exports (also noted in §6). Fix the Dr/Cr suffix parsing (regex, case-insensitive), add adapters (or an Amount+indicator mode) for single-amount layouts, preserve overdraft sign, and derive opening/closing by date order. Also add a one-off re-import path for statements imported before R1.5 (their rows keep the old corrupted values and won't re-dedupe). *Effort:* M. *Benefit:* correct bank feeds across more banks and export styles.

**R2.10 — Route payroll compute through the backend** *(the F14 payroll slice, deferred from R1.3).* The web payroll page computes and persists runs/slips client-side (statutory logic in the browser, against CLAUDE.md); it also stores no run totals, so backend finalize can't process frontend-generated runs. Replace the client-side compute + direct `payroll_runs`/`payroll_slips` inserts with a call to `POST /api/payroll/runs` (server-side `_compute_slip` + totals), reconciling the status/`generated_at` column differences and fetching slips via the backend to avoid RLS re-read gaps. *Effort:* M. *Deps:* frontend CI test runner (currently absent — the 12 web test files are dead code). *Risk:* unverifiable without frontend test infra; must not regress the working generate/display flow. *Benefit:* single correct payroll engine; removes the browser tax logic and the missing-totals defect.

**R2.9 — Document-number uniqueness for the remaining statutory docs** *(surfaced by the R1.1 regression review).* `debit_notes.debit_note_no` (medium), `receipts.receipt_no` and `purchase_payments.payment_no` (low) generate numbers but have **no** uniqueness constraint, so the numbering retry is dead code and concurrent duplicates are possible (CGST §34 / Rule 53 require serial uniqueness for debit notes). Add per-client (debit notes/receipts) / per-firm (payments, matching their generator) UNIQUE keys, **preceded by a de-dup migration** for any existing duplicates. *Effort:* M. *Deps:* R0.1. *Risk:* must de-dup live data before adding the constraint. *Benefit:* closes the numbering-integrity gap R1.1 deliberately scoped out.

### Tier 3 — Medium (productivity, consolidation, scale)

- **R3.1 — Statutory rules-as-data registry (FY-versioned).** Single source of truth for slabs/thresholds/due-dates; eliminates the class of bugs behind F15/F17/F18. *Effort:* L. *Benefit:* tax law becomes maintainable data.
- **R3.2 — Cross-client batch compliance cockpit** (generate/validate/mark-filed + ARN capture across clients). *Effort:* XL. *Benefit:* the #1 CA scale unlock.
- **R3.3 — De-orphan or delete the ~40 unlinked routes and consolidate duplicate invoicing/fixed-asset/payroll stacks.** *Effort:* L. *Benefit:* coherence + lower maintenance.
- **R3.4 — Automate document collection & reminders** (WhatsApp Business API + cadence). *Effort:* L. *Benefit:* removes the biggest daily admin sink.
- **R3.5 — Performance: paginate/aggregate in SQL, add indexes, cache auth lookups.** *Effort:* M–L. *Benefit:* holds up at 100–500 clients.
- **R3.6 — UX consistency:** one skeleton/empty/error system, real dialog semantics, dashboard load-error states, shared client context. *Effort:* M. *Benefit:* daily usability.

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


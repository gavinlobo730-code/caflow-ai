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

**R2.2 — Create the ~13 missing tables or gate the features (F5). DELIVERED.** Re-verification found the true scope was 24 phantom table names + 2 missing RPCs (not ~13), plus a blocking interaction: 15 of those tables sat behind an import of `core.supabase_client.get_supabase_client` — a function that doesn't exist anywhere in the codebase — so those modules died with `ImportError` before any SQL could even run. Migration 156 creates 21 tables, proven on real Postgres with every referencing router's exact insert payload (fresh-DB and re-apply paths both green); the phantom-import fix corrects all 10 affected files to import the canonical `get_supabase`, un-dead-ending ITR workspace, e-invoice, e-way bill, XBRL, 26AS, GST portal sync and Tally migration in production (this also closes the finding noted under R2.4 below). Two RPCs added. `test_schema_contract.py`'s missing-table/RPC ratchets are now empty sets — any future phantom reference fails CI immediately. *Effort:* L (scope grew from ~13 to 26 items). *Benefit:* removes 500s and ImportErrors; seven previously non-functional feature areas now work outside mock/demo mode.

**R2.3 — Correct TDS & ITR statutory logic (F17, F18). DELIVERED.** Rebuilt both domains as FY-versioned data (`domain/income_tax/statutory_rates.py`, `domain/tds/section_rates.py`), one source of truth each, per an explicit governing product decision: FY 2025-26 is the verified baseline, FY 2026-27 is carried forward with a `rates_verified=False` flag surfaced through the API rather than invented. Fixed: the old-regime ₹50k standard deduction (was wrongly using the new regime's ₹75k); §87A marginal relief (new regime only — an adversarial review caught and fixed an initial overgeneralization to the old regime, which has a hard cliff instead); surcharge marginal relief with the new-regime 25% cap and the 15% cap on all capital-gains tax; F18's 10× paise-scaling bug on the deductions page, fixed by deleting its whole duplicate tax engine in favor of calling the backend. Vendor-payment TDS (F17) moved off float arithmetic to Finance Act 2025/2024 thresholds and rates. *Effort:* L (as estimated). *Benefit:* correct tax numbers, one source of truth across backend and frontend, and a clear, low-cost path to updating FY 2026-27 once verified (a data change, not a code change). **Deferred, tracked in Tier 3 below:** Section 80CCD(2) (employer NPS deduction) is unimplemented; Section 206AB's continued applicability for FY 2025-26 needs statutory verification.

**R2.4 — Add a database tenancy backstop (F1, F4). DELIVERED (scope adjusted).** Investigated both proposed fix directions and found neither was the highest-leverage move available: the `USE_USER_JWT` cutover is a multi-week, zero-test-coverage architectural change (deferred, not attempted); a repository-layer mandate would cover only 28/94 routers. Instead fixed `core/authz.py::can_access_client`'s actual structural flaw (firm-wide roles bypassed firm-membership checking entirely, not just assignment scoping) — hardening the ~35 routers that already depend on it in one change — plus the three real cross-tenant IDORs a systematic sweep found (payroll finalize/status, GSTR-9 as originally cited, ITR version history). *Effort:* M (delivered scope). *Benefit:* the central authz gate can no longer be bypassed by supplying another firm's client_id; three live IDORs closed with regression tests proving both directions.
- ~~**New finding (Tier 2/3 candidate, not yet scheduled):** `core.supabase_client.get_supabase_client` ... does not exist anywhere in the codebase.~~ **RESOLVED by R2.2** (see above) — fixed in the same Tier 2 pass, not left open.

**R2.5 — Close the `/join` privilege escalation and portal-invite gaps (F21, F22). DELIVERED.** Moved `/join` account-linking to a backend endpoint validating a signed single-use invite token; added tokenized, expiring portal invites — and, discovered during implementation, rewired the actual live "Invite to Portal" UI (which bypassed the tokenized service entirely via a raw browser `signInWithOtp` + direct table write) onto the same audited path. See Implementation Log for the full account, including a self-caught UPDATE-based escalation bug and a self-caught regression in the `users`-table RLS hardening. *Effort:* M (actual, incl. the unplanned live-flow rewire). *Benefit:* removes the most exploitable security holes AND makes the client-portal invite feature actually work end-to-end for the first time.

**R2.6 — Fix RLS predicates and migration hygiene (F20 + drift). DELIVERED (partially).** Corrected all 43 remaining policies keyed on the never-issued `firm_id` JWT claim (migration 154); added a database-free ratchet test against duplicate migration numbers growing further. **Not done — needs a human with production access:** actually reconciling repo-vs-live drift requires running the migration runner against the real production Supabase, which this session has no credentials for and would not run autonomously regardless (high-blast-radius, hard-to-reverse). **This remains the single most important pre-launch action item in this entire document as of the Tier 2 regression review** — every fix delivered across R2.1–R2.12 has been proven against a fresh, disposable Postgres 16 instance with every migration applied from scratch; none of it has been verified against the actual production Supabase project, which may carry historical drift, partially-applied migrations, or manual hotfixes invisible to this session. See Implementation Log for the exact command to run. *Effort:* M (delivered portion). *Benefit:* makes the eventual RLS/`USE_USER_JWT` cutover (R2.4) safe on 51 previously deny-all tables.

**R2.7 — Wire the workflow engine or hide it (F11, F12). DELIVERED.** Root cause went deeper than either finding stated: migration 068 (the engine's own schema) never fully applied on a fresh database at all, so 6 of its 7 tables never existed. Fixed via a corrective migration (157); deleted `routers/workflows.py` (fake, never-persisted data whose catch-all route shadowed the real router's own endpoints, causing F11's 404s); fixed four router→repository signature mismatches that had never been exercised end to end; made two action types (`create_task`, `send_notification`) write real rows instead of fabricating success, with every other action type now explicitly logging `skipped` rather than pretending to have run; registered the due-schedule scheduler tick, which had never been wired to APScheduler so cron-based workflows could never fire. Adversarial review caught and fixed a critical regression risk (a notification-CHECK widen that would have silently reverted an earlier production fix for five notification types) plus three more real bugs (cron scheduling silently never worked at all — `next_run_at` was never set and the cron library wasn't even installed; the new real-write actions bypassed the tenancy guard every other write path enforces; non-retryable validation errors went through the generic 3-attempt retry path). *Effort:* M (as estimated). *Benefit:* automation is now honest — every claimed action either really happened or is explicitly marked as not yet implemented.

**R2.8 — Make AI extraction real (F19). DELIVERED.** Re-verification found the blast radius was larger than F19 stated: four overlapping extraction code paths existed, not one — two of which didn't just fabricate but *persisted* fake data (a government-notice extraction router that inserted a real row, created a task, and notified the partner using hardcoded fields whenever Groq was unavailable or failed), plus a fourth, entirely undisclosed extraction generation found only when a reviewer was explicitly asked to check for code paths the initial pass hadn't touched. All four now return honest 501/502/503 instead of fabricating a success; persistence only happens after a genuine successful extraction. Also fixed two unrelated cross-firm data leaks into the AI copilot's own prompt context, found while tracing extraction's callers — firm-wide task/compliance/risk summaries were being folded into every firm's chat context instead of being scoped to the caller's own firm. *Effort:* M (as estimated). *Benefit:* the AI value prop stops silently faking data; the copilot no longer leaks cross-firm operational data into its own prompts.

**R2.9 — Document-number uniqueness for the remaining statutory docs. DELIVERED.** *(surfaced by the R1.1 regression review)*. `debit_notes.debit_note_no`, `receipts.receipt_no` and `purchase_payments.payment_no` all generated numbers with **no** uniqueness constraint at all — a genuine concurrent race could commit two identical numbers, a live CGST §34/Rule 53 compliance gap for debit notes. Migration 159 de-dups any pre-existing duplicates (suffixing them, never altering the underlying financial row) then adds UNIQUE constraints matching each generator's real scope (per-client for debit notes/receipts, per-firm for payments). Since receipts/payments post their GL journal before the number-bearing insert, a collision now has to reverse that journal — adversarial review found and fixed a critical bug in the reversal logic itself: the journal-posting idempotency fast-path could hand a losing request the *winning* request's already-committed journal id, so the naive compensation path would have reversed the winner's valid journal instead of the loser's failed attempt. Fixed with an ownership check before any reversal. *Effort:* M (as estimated). *Benefit:* closes the numbering-integrity gap R1.1 deliberately scoped out, with the new failure mode it introduces (journal-then-number-collision) itself proven safe.

**R2.10 — Route payroll compute through the backend** *(the F14 payroll slice, deferred from R1.3).* **DELIVERED.** Replaced the web payroll page's client-side compute + direct `payroll_runs`/`payroll_slips`/`payroll_employees` writes with calls to the existing `POST /api/payroll/runs` (server-side `_compute_slip` + totals) and the rest of the backend payroll API. Found and fixed a real backend bug while scoping this: `GET /runs/{id}/slips` filtered on a `payroll_slips.firm_id` column that has never existed, so the endpoint could never return data against real Postgres. Found and fixed a genuine tax-correctness gap: `_compute_pt` accepted a `state` parameter but silently ignored it, always applying Karnataka's slab — undiscovered until this migration because the frontend's own (correct, per-state) logic masked it; would have been a silent regression for every non-Karnataka client had this migration shipped without the fix. Also fixed the missing bearer token in `clients/[id]/payroll/page.tsx`'s `apiFetch` (every call there would 401 against a real backend) and wired the 12 dormant frontend `node:test` files into CI (Node bumped 20→22 for `--experimental-strip-types`). *Effort:* M (as estimated). *Benefit:* one correct payroll engine, real per-state Professional Tax, and CI now actually runs the frontend's existing test suite. **Deferred, tracked in Tier 3 below:** Maharashtra/West Bengal/Tamil Nadu Professional Tax slab values are ported from the pre-existing frontend logic (the only source in this repo) and flagged pending statutory verification, same treatment as FY 2026-27's income-tax figures.

**R2.11 — Bank statement parser hardening. DELIVERED.** *(pre-existing, surfaced by the R1.5 regression review)*. Fixed all five defects the audit's evidence pointed at: the Dr/Cr suffix parser was case/char-set sensitive and could double-negate or mishandle a suffix-plus-parens combination; single signed-Amount + Dr/Cr-indicator statement layouts misparsed every row as a debit; a layout-detection false positive; punctuation-intolerant indicator matching (`"Dr."` not recognised); and opening/closing balances taken by file position, which inverted on newest-first exports — now derived by true date order with a majority-vote direction check across adjacent rows instead of a bare two-endpoint comparison. *Effort:* M (as estimated). *Benefit:* correct bank feeds across more banks and export styles. **Deferred, tracked as R2.11.1 below:** a one-off re-import path for statements imported before this fix (their rows keep the old corrupted values and won't re-dedupe) — not yet scoped, needs a product decision on how aggressive the re-import matching should be.

**R2.12 — Full receipt→AR→journal atomicity. DELIVERED.** *(follow-up from R1.6/F7)*. Extended the `post_journal_atomic` pattern (migration 152) to a much larger transaction: `settle_receipt_atomic` (migration 160) writes the journal header, its lines, the receipt row, and every allocation's row-locked invoice update in ONE plpgsql function body, so no partial state can ever be observed and no app-level compensation is needed for this path. The highest financial-correctness-stakes change of the whole Tier 2 sequence — two independent adversarial-review lenses found 9 confirmed issues (1 refuted), several reproduced directly against real Postgres: a `payment_mode` value real production callers actually send violated the CHECK constraint (fixed by migration 161); the new RPC had no equivalent of the existing balance/zero-value guards (an imbalanced or empty journal both posted successfully and, per the immutability trigger, were permanently unfixable — fixed by migration 162); a second valid allocation row for the same invoice always rolled back the whole settlement; an RPC-error classifier collided with the function's own legitimate error messages; the multi-currency path's CAS had no retry at all (weaker than the path it was meant to match). *Effort:* M (as estimated, scope of the adversarial findings was larger). *Benefit:* receipts can never leave sub-ledger and GL out of step.

### Tier 2 status: **CLOSED.** All 12 items (R2.1–R2.12) delivered as of the Tier 2 regression review (see Implementation Log). Every fix is proven against mock-mode tests and a disposable, freshly-migrated Postgres 16 instance; **none has been verified against the actual production Supabase project** (R2.6's undone sub-item) — see that item above for the exact reconciliation command. New issues surfaced during Tier 2 and not yet scheduled are tracked in Tier 3 below (R3.0, R3.7, R3.8, R2.11.1, and the newly-added R3.9–R3.11).

### Tier 3 — Medium (productivity, consolidation, scale)

- **R3.0 — Harden `client_portal_users` RLS/grants. DELIVERED.** *(surfaced by the R2.5 regression review)*. Migration 109's `client_portal_users_own_firm` policy was `FOR ALL USING/WITH CHECK (firm_id = get_my_firm_id())` — any authenticated firm staff member could directly INSERT/UPDATE/DELETE a `client_portal_users` row from the browser, bypassing `invite_contact`'s token/TTL/audit trail entirely. Fixed via migration 163, mirroring the R2.5 `users`-table pattern exactly: `REVOKE INSERT, UPDATE, DELETE ... FROM authenticated`, then the old policy replaced with a SELECT-only "own firm" policy. Unlike `users`, no column-level UPDATE grant was needed — confirmed via a repo-wide check that `apps/web` has zero direct writes to this table (every frontend interaction already goes through the backend REST API), so there was no legitimate self-service feature to carve out. Proven on real Postgres 16: an authenticated firm-staff session can still `SELECT` its own firm's contacts (and a different firm's contact is invisible), but `INSERT`/`UPDATE`/`DELETE` all fail with `permission denied`; the `service_role`-backed backend path (the only real mutation path) is completely unaffected. *Effort:* S (as estimated). *Benefit:* closes the last raw-table write path in the portal invite flow.
- **R3.1 — Statutory rules-as-data registry (FY-versioned). RE-SCOPED, DELIVERED (R3.1a + R3.1b).** R2.3 already delivered the core of this for income tax/vendor TDS. A full re-audit (see Implementation Log) found the remaining scope split into quick consolidation wins (R3.1a: capital-gains rate constants, GST/MCA due-date duplication, a genuine data-corrupting frozen-date bug in `mca/page.tsx`) and a much larger item, **R3.1b: a real capital-gains engine** — Cost Inflation Index table, Section 2(42A) holding-period classification, and the Section 111A/112A/112/115BBH/50AA tax-rate logic, none of which existed in the backend at all before this. Both delivered: `domain/income_tax/capital_gains_engine.py` is the new single source of truth; `routers/income_tax.py` gained `/capital-gains/compute` (stateless estimator) and full register CRUD (`GET`/`POST`/`DELETE /capital-gains`), all server-computed — `apps/web/app/income-tax/capital-gains/page.tsx`'s own duplicate engine (which computed AND persisted gain_type/tax_rate_percent/indexed_cost_paise client-side, with no server-side validation) is gone; migration 164 hardens the `capital_gains` table's RLS the same way R3.0 did for `client_portal_users`. A genuine inconsistency between the page's two independent implementations was found and fixed while unifying them: the calculator computed the real "12.5% without indexation OR 20% with indexation, whichever is lower" choice for property LTCG, but the register always hardcoded 20% and never computed the 12.5% alternative at all — the register now gets the calculator's more complete logic. Also surfaced, tracked below: Sections 206AA/206AB (hardcoded, unverified, needs Finance Act 2025 confirmation), an orphaned TCS/206C registry entry with no engine behind it, and at least 3 more frontend pages that compute-and-persist statutory calculations independently of any backend (R3.13). *Effort:* R3.1a at S; R3.1b at M (as estimated). *Benefit:* tax law becomes maintainable data; closes the most serious "business logic in the frontend" violation found this session, with a real financial-computation feature (CII indexation) added to the backend for the first time.
- **R3.2 — Cross-client batch compliance cockpit** (generate/validate/mark-filed + ARN capture across clients). *Effort:* XL. *Benefit:* the #1 CA scale unlock.
- **R3.3 — De-orphan or delete the ~46 unlinked routes and consolidate duplicate invoicing/fixed-asset/payroll stacks. PARTIALLY DELIVERED (the dangerous half).** A full re-scan (see Implementation Log) confirmed ~46 routes reachable only by typing the URL, clustering into: 15 real firm-level statutory-suite routes and 14 real shipped-but-unlinked features (recommend: link both into nav — no data risk), 13 routes behind the unlinked `/accounting` admin hub (recommend: link the hub), 8 already-retired 5-line redirect stubs plus 3 dev artifacts and 2 redirect shims (recommend: delete). The urgent finding, delivered now: `/accounting/invoices` and `/accounting/fixed-assets` were not harmless unlinked duplicates but active data-integrity hazards — `/accounting/invoices` wrote directly to a `sales_invoices` table (via raw browser Supabase, with a literal `CREATE TABLE` snippet in a code comment instructing the user to run it manually) that the real, linked invoicing flow never reads, so any invoice entered there was invisible to every report/GST return/dashboard; `/accounting/fixed-assets` wrote to the *same* `fixed_assets` table the real page uses but bypassed the backend's depreciation/journal-linkage logic, silently breaking GL tie-out. Both neutralized via the existing retired-page redirect pattern; RLS hardened (migration 166) so the underlying tables can no longer be written outside the backend either. The remaining ~44 lower-risk routes (link-or-delete, no data hazard) are tracked as a follow-up, not attempted in this pass. *Effort:* S (delivered); M–L remaining. *Benefit:* closes a live silent-data-loss/GL-corruption bug; the rest is coherence + lower maintenance.
- **R3.4 — Automate document collection & reminders** (WhatsApp Business API + cadence). *Effort:* L. *Benefit:* removes the biggest daily admin sink.
- **R3.5 — Performance: paginate/aggregate in SQL, add indexes, cache auth lookups.** *Effort:* M–L. *Benefit:* holds up at 100–500 clients.
- **R3.6 — UX consistency:** one skeleton/empty/error system, real dialog semantics, dashboard load-error states, shared client context. *Effort:* M. *Benefit:* daily usability.
- **R3.7 — Year-end close: post an explicit closing journal entry** *(surfaced by the R2.1/F10 fix)*. There is no mechanism today that transfers a completed year's P&L into `reserves_and_surplus` via an actual posted journal entry — the "add current-year PAT to reserves" step is a live, presentational preview computed fresh on every request, not an accounting fact. A second prior year's retained profit, if that year was also never explicitly closed, would still be invisible in a third year's cumulative reserves. Needs a business/accounting decision first (should this post automatically when a Partner locks the engagement? does it need its own CA-review gate, matching the CLAUDE.md "never auto-submit" spirit even though this is internal not government-facing? which specific reserves sub-account?) — do not implement unilaterally. *Effort:* M. *Benefit:* true multi-year retained-earnings continuity, not just single-year carry-forward.
- **R3.8 — Fix the non-functional year-end review workflow and consolidate its two implementations. DELIVERED.** *(surfaced by the R2.1 investigation; found to be far more serious by the fresh Tier 3 re-scope)*. The original framing was "two competing implementations, both work, pick one" — the re-scope found neither was actually reachable: `apps/web/lib/api/yearEnd.ts` called `/api/year-end/engagements/{id}/review/...` while `routers/year_end_reviews.py`'s real routes were `/api/year-end/{id}/reviews/...` (no `/engagements/` segment at all, unlike every other year-end sub-resource router) — the review page's Submit/Approve/Request Revision/Final Approve buttons all 404'd in production. Fixed by adding the missing `/engagements/` segment to the router (matching convention) and correcting the frontend's paths; added the missing `GET .../reviews` endpoint the review page needs for its step-timeline and history display (previously fetched a route that never existed); extracted the one genuinely-shared behavior (`year_end.py`'s FY-lock-on-completion side effect, which — since its own endpoint was never reachable either — had never actually run for a real review-workflow completion) into `services/year_end_workflow_service.py` and wired it into `year_end_reviews.py`'s `final_approve`, the transition users can actually reach. `year_end.py`'s generic status endpoint and `year_end_reviews.py`'s richer per-step audit/revision-request workflow remain deliberately separate (a real, intentional difference in capability, not accidental duplication) but now share the one behavior that must not diverge. *Effort:* S (as re-scoped). *Benefit:* the year-end review workflow now actually works end-to-end; the FY-lock integration now fires on the real, used completion path.
- **R2.11.1 — Bank-statement re-import path for pre-R2.11 statements** *(surfaced by the R2.11 fix phase, promoted here at Tier 2 close — not yet scoped)*. Statements imported before R2.11's parser fixes keep their old, incorrectly-signed/scaled rows on disk — nothing re-derives them from the fix, and the existing dedupe logic won't treat a corrected re-upload as new rows (by design, to prevent double-counting). Needs a product/design decision before implementation: how aggressive should re-import matching be (exact hash match vs. fuzzy date+amount match), does it replace rows in place or supersede them with an audit trail, and does it need its own CA-confirmation step given it can change historical reconciled balances. *Effort:* M. *Benefit:* firms that imported bank data before R2.11 get correct historical balances without a manual re-entry.
- **R3.9 — Audit the ~57 migration-created tables with no backend reader** *(surfaced by the R2.2 regression review)*. Some may be reached directly from the frontend via PostgREST rather than through a backend router — the same F14 concern (business logic / unmediated table access from the browser) flagged elsewhere in this audit. Needs a systematic per-table check (grep `apps/web` for direct `.from("<table>")` reads/writes against each name) before deciding whether each is dead schema (safe to leave or formally deprecate) or an undocumented frontend-direct access path (a CLAUDE.md violation — "zero business logic in the frontend" — needing the same treatment as R2.10's payroll migration). *Effort:* M. *Benefit:* closes the door on any remaining unmediated-table-access surface; removes schema clutter.
- **R3.10 — Implement Section 80CCD(2) and verify Sections 206AA/206AB's status** *(surfaced by the R2.3 regression review; 206AA scope widened by the R3.1 re-audit)*. Section 80CCD(2) (employer NPS contribution) is deductible under the new regime — unlike the rest of Chapter VI-A — but is entirely unimplemented in `domain/income_tax`. Separately, `tds_validator.py` hardcodes BOTH Section 206AA (missing-PAN, 20% floor — duplicated in `tds_computer.py` too) and Section 206AB (non-filer doubled rate) with no FY registry and no `verified` flag; 206AB in particular may have been altered by Finance Act 2025 and needs verification against the Act's actual text before either changing a compliance-conservative behaviour or leaving a since-repealed check silently in place. *Effort:* S–M. *Benefit:* closes a real deduction gap and confirms/corrects two compliance-sensitive checks.
- **R3.11 — Compensate `debit_notes.create_debit_note`'s header/lines insert** *(surfaced by the R2.9 regression review, low priority)*. The header is inserted via `insert_with_number` (now durably unique per R2.9) and `debit_note_lines` afterward with no compensation — a lines-insert failure leaves an orphaned draft header with zero lines. Not a money- or statutory-correctness issue (a draft, not a posted document) but worth closing for consistency with every other multi-step insert this Tier 2 pass hardened. *Effort:* S. *Benefit:* no orphaned draft rows from a partial write.
- **R3.12 — Verify Maharashtra/West Bengal/Tamil Nadu Professional Tax slabs against current state notifications** *(surfaced by the R2.10 regression review)*. `routers/payroll.py::_PT_SLABS_BY_STATE`'s Karnataka entry is this codebase's original, unit-tested baseline; the other three states were ported verbatim from the frontend's pre-existing (pre-R2.10) client-side logic — the only source for those states anywhere in this repo — and have not been independently re-confirmed against each state's current Profession Tax Act/notification. Same "pending statutory verification" treatment as FY 2026-27's income-tax figures; updating a verified value is a one-line data change in `_PT_SLABS_BY_STATE`, not a code change. *Effort:* S (verification only, assuming the existing slab shape is correct). *Benefit:* removes the one remaining unverified-statutory-value flag from the payroll module.
- **R3.13 — Migrate remaining frontend pages that compute-and-persist statutory calculations independently of the backend. PARTIALLY DELIVERED (R3.13a).** *(surfaced by the R3.1 re-audit; R3.1b covers the capital-gains instance separately given its size)*. Three instances found; a scoping pass ahead of full delivery (see Implementation Log) found the advance-tax item was not just a relocation job but an actual formula bug, and fixed it first (R3.13a) as the highest-value, most isolated piece. Two remain:
  - `apps/web/lib/data/compliance.ts`'s `seedComplianceCalendar()` computes GSTR-1/3B/9 due dates client-side AND writes them directly to a `compliance_calendar` Supabase table from the browser — the same "zero business logic in the frontend" violation R2.3/R2.10 already fixed elsewhere, but for compliance due dates instead of tax slabs. The scoping pass found this is a genuine three-way consolidation, not a one-line swap: the backend already has an equivalent (`POST /api/compliance/seed` in `routers/compliance.py`, using `services/compliance_engine.py`'s due-date functions), but it writes to a *different* table (`compliance_tasks`) than the one the frontend uses (`compliance_calendar`, which has zero backend readers) — and a third system (`compliance_records`/`compliance_obligation_service.py`) also exists. Needs a decision on which becomes canonical before migrating this (also gates R3.2, below). *Effort:* M.
  - `apps/web/app/payroll/page.tsx`'s `generatePfEcr`/`generateEsiStatement` CSV exporters independently re-hardcode PF/ESI rates a third time (after the backend and `payrollTdsEstimate.ts`) purely for export formatting. The scoping pass checked these byte-for-byte against the backend's canonical `_compute_pf`/`_compute_esi` — no discrepancy found; lowest risk of the three, not persisted, arguably not worth touching. *Effort:* S.

  *Benefit:* the last un-migrated "business logic in the frontend" instances close; one fewer place for compliance numbers to silently drift.

### R3.13a — Section 234C advance-tax interest engine (DELIVERED)

Scoping this item (see Implementation Log) found `apps/web/app/income-tax/advance-tax/page.tsx`'s `compute234CInterest()` was not merely unmigrated but structurally wrong: it computed interest as a function of *actual* payment delay (the Section 234B shape) instead of Section 234C's fixed 3-month (instalments 1–3) / 1-month (instalment 4) periods, and had no 12%/36% trigger tolerance for instalments 1/2 at all — both real, user-facing correctness defects, not just a frontend/backend duplication. Fixed with a new `domain/income_tax/advance_tax_interest_engine.py`, backend endpoints, hardened RLS (migration 165), and a frontend rewrite. *Effort:* S–M (as scoped). *Benefit:* closes a live wrong-interest-amount bug in a CA-facing tax calculator, and closes the last raw-table write path on `advance_tax_payments`.

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

## Milestone R2.8 — Make AI extraction real, F19 remainder (DELIVERED)

**Goal:** F19 flagged that document extraction fabricates data; re-verification
found the finding understated the blast radius — there were four overlapping
extraction generations, two of which don't just return fake data but
*persist* it, plus two unrelated cross-firm data leaks into the AI copilot's
own prompt context discovered while tracing the extraction call paths.

**document-intelligence-v1 (invoices).** `_mock_extraction()` — a hardcoded
"Sample Vendor Pvt Ltd" / GSTIN `27AABCS1429B1Z5` / ₹11,800 payload — deleted
outright. `_run_extraction` now returns a `(data, error, status_code)` tuple:
no `GROQ_API_KEY` configured → honest 503; a raised exception from the real
Groq call → honest 502. Never a fabricated success.

**document-intelligence-v2 (government notices) — the consequential one.**
This router didn't just fabricate; on any extraction attempt it unconditionally
persisted a `government_notices` row, created a linked task, and notified the
partner — using `_mock_extract()`'s guessed/hardcoded fields (`reference_no:
"REF-MOCK-001"`) whenever Groq was unavailable or failed. `_mock_extract` is
deleted; `_run_notice_extraction` returns the same honest
`(data, error, status_code)` shape as v1, and extraction now runs *before* any
persistence — the insert/task/notification block only executes on a genuine
successful extraction. A failed or unavailable extraction now creates nothing.

**routers/documents.py `/parse` — a fully dead mock, unconditionally.** No AI
call was ever made here: every request returned one of two hardcoded dicts
(`MOCK_FORM16_EXTRACTION` — fake employee "Rajesh Kumar Sharma", fake PAN,
fake TDS; `MOCK_GST_INVOICE_EXTRACTION`) with a fabricated `confidence_score:
0.94`, regardless of the uploaded file. Both dicts deleted; the endpoint now
returns an honest 501 pointing callers at the real v1/v2 endpoints.

**A 4th, undisclosed generation — found during the fix phase.**
`routers/document_intelligence.py` (the unversioned `/api/document-intelligence`
router, mounted in `main.py` but never mentioned in F19 or the original
implementation pass) served hardcoded fabricated data verbatim via
`GET /{doc_id}/extraction` — same class of issue as the other three, with zero
frontend callers. Retired: the import and `app.include_router(...)` call
removed from `main.py`, with a comment recording why and confirming its
demo `doc-NNN` IDs never collide with real UUID-keyed documents (so
unmounting it is a no-op for real traffic). `apps/web/lib/api/index.ts`'s
matching dead client stub (unused by any page) removed too.

**Cross-firm tenancy leaks into the AI copilot's own prompt context (F19-adjacent,
found while tracing extraction's callers).** `routers/ai_copilot.py`'s
`_build_firm_context` (used by `POST /chat`) and the sibling `get_firm_context`
handler (`GET /firm-context`) both called `TaskDomainService().get_dashboard_summary()`
with no `firm_id` at all — defaulting to a platform-wide aggregation — and
`_build_firm_context` made the same mistake calling
`compliance_record_service.get_firm_summary()` and `risk_engine.get_risk_dashboard_stats()`.
Every one of these callees already correctly honors a `firm_id` parameter when
given one; the bug was purely at the call sites, silently leaking every firm's
task/compliance/risk counts into the system prompt the AI copilot builds for
*any* firm's chat session. Fixed by passing `firm_id` through at all four call
sites. A companion, same-class bug in `domain/task_service.py`'s
`get_dashboard_summary`: `task_repo.find_overdue()` has no `firm_id` parameter
(it scans every firm's tasks) and the `overdue_tasks` count used its raw
length with no post-filter, while every other figure in the same function
correctly threads `firm_id` through its own repo call — fixed with the same
post-hoc Python filter already used for this exact repo method in
`domain/ai_copilot_service.py._build_context`.

**Adversarial review (two independent lenses, fresh-context, run via the
Workflow tool's `pipeline()`/`parallel()` — fabrication-completeness and
tenancy-and-regression — followed by a separate skeptical verification pass
per finding) — findings, all fixed in the fix phase:**
1. *Critical:* the 4th undisclosed extraction generation
   (`routers/document_intelligence.py`) described above — not scoped in the
   original implementation pass, caught only because a reviewer was
   explicitly asked to check for "any other document-extraction code path
   this milestone didn't touch."
2. *High:* migration 052 created `public.government_notices` without
   `ca_approved` / `ca_approved_by` / `ca_approved_at`, but
   `document_intelligence_v2.py` has always read and written all three (the
   extract endpoint inserts `ca_approved: False` on every new notice; the
   approve endpoint updates all three as the required human-in-the-loop
   step). Against real Postgres/PostgREST this means even a genuine,
   non-fabricated extraction was never persisted in production — a
   pre-existing bug this milestone's own mock-mode tests could never catch.
   Fixed via migration 158 (additive-only, `ADD COLUMN IF NOT EXISTS`, same
   repair pattern as 155/157) and proven against a real, freshly-migrated
   Postgres database with the exact insert/update payloads the router
   builds (`test_r2_8_fix_notice_ca_approval_pg.py`).
3. *Medium (my own independent verification pass, not the workflow's
   reviewers):* `risk_engine.get_risk_dashboard_stats`'s `resolved` count
   scanned the raw global `MOCK_RISKS` list unconditionally — no `firm_id`
   filter at all — while every other count in the same dict (including
   `total_open`) correctly goes through the firm-scoped `get_all_risks()`,
   which has a genuine, firm-filtered real-Postgres path via
   `document_risks`. This is the same tenancy surface as finding 3 above
   (it feeds the AI copilot's prompt context) so it's fixed in this
   milestone rather than deferred: `resolved` now calls
   `get_all_risks(firm_id=firm_id, status="resolved")`, mirroring the `open`
   count immediately above it.

**Verified:** 2,294 backend tests pass (67 in the new R2.8 suite, including
mocked-Groq-failure tests that actually raise inside `_groq_extract`/
`_extract_with_groq` — not just presence checks — and assert the honest
502/503 responses, zero persistence on failure, and that both retired mock
helper functions no longer exist on their modules); same 23 pre-existing,
unrelated DB-dependent failures (`test_hardening.py`, `test_phase3_gst.py`,
`test_phase3_mca.py`, `test_phase3_tds.py`), reconfirmed unrelated by rerun.
Migration 158 proven against a real, freshly-migrated Postgres 16 database:
schema check confirms all three columns exist with the right types/defaults,
and both the exact `extract_notice` insert payload and the exact
`approve_notice` update payload succeed and round-trip correctly.

**Next:** R2.9 (document numbering for debit notes/receipts/purchase
payments), R2.11 (bank statement parser hardening), R2.12 (receipt→AR→journal
atomicity), R2.10 (payroll frontend→backend migration), then the Tier 2
regression review and Tier 3.

## Milestone R2.9 — Document-number uniqueness for debit notes, receipts,
purchase payments (DELIVERED)

**Goal:** the R1.1/F6 regression review flagged that `debit_notes.debit_note_no`,
`receipts.receipt_no` and `purchase_payments.payment_no` all generate a
sequenced number (per firm+client+FY for the first two — CGST Rule 46/53's
per-supplier series — per firm+FY only for payments, matching
`_next_payment_seq`'s actual scope) but **none of the three backing tables had
any uniqueness constraint at all**. A genuine concurrent race could commit two
rows with an identical number — a live statutory-compliance gap for debit
notes — and `services/numbering.py`'s retry-on-collision (already used by
debit notes) could never actually fire, since nothing existed for a duplicate
insert to violate.

**Migration 159** de-dups any pre-existing duplicate first (partitions each
table by its real scope, keeps the earliest row's number untouched, and
suffixes every later duplicate with `-DUPn`, logged via `RAISE NOTICE` for
manual review — the underlying financial row is never altered or deleted),
then adds the three constraints matching each generator's real scope. Verified
against real Postgres: two clients of one firm can share a debit-note/receipt
number; a same-client duplicate is rejected; purchase-payments rejects a
duplicate even **across two different clients of the same firm** (per-firm
scope) but allows the same number for a different firm; and a dedicated test
drops the constraint, inserts a genuine pre-existing collision via raw SQL,
re-applies migration 159, and confirms the de-dup + re-enforcement both work.

**A new failure mode this introduces.** Adding the receipts/purchase_payments
constraints makes an insert fail in a way that was previously impossible.
Both services post the GL journal **before** the number-bearing insert (the
existing journal-first ordering from R1.6/F7), so a numbering collision on
that insert must reverse the journal rather than leave a phantom GL entry.
Fixed by wrapping the insert in `receipt_service.py`'s existing settlement
compensation path, and by a new `_insert_payment_or_compensate` helper in
`purchase_payments.py` used by both its INR and foreign-currency paths.
`debit_notes.py` needed no such change — it never posts a journal at creation,
only later when a human explicitly issues the note.

**Adversarial review (2 lenses — correctness/atomicity and migration-safety —
run via the Workflow tool's `pipeline()`/`parallel()`, each finding then
independently re-verified by a separate skeptical agent) — 4 findings, all
CONFIRMED:**
1. **Critical, fixed:** `phase2_journal_service._create_journal`'s
   pre-existing idempotency fast-path (`_find_existing`, intended so a
   retried call with the same reference doesn't double-post) matches on
   `(firm_id, client_id, reference_no, entry_date)` only — no receipt/payment
   id. When two receipts race to the same auto-generated `receipt_no` (the
   exact scenario migration 159 exists to catch), the LOSING request's
   `journal_for_receipt` call can hit that fast-path and receive the WINNING
   request's already-committed journal id back — not one of its own. The new
   compensation code would then reverse the *winner's* valid, successful
   journal, leaving that other receipt's books net-zeroed in the GL while its
   receipt row and settled AR still show paid. Identical mechanism confirmed
   in `create_foreign_receipt` and both purchase-payment paths. Fixed: before
   reversing, `_compensate_failed_settlement` (receipt_service.py) and
   `_insert_payment_or_compensate` (purchase_payments.py) now check whether
   any *other* already-committed row already claims that exact
   `journal_entry_id` — Postgres's own commit-before-conflict-report ordering
   guarantees that row is visible by the time a 23505 is raised — and skip
   the reversal if so, only cleaning up this failed attempt's own artifacts.
2. **High, fixed:** `journal_for_purchase_payment` still swallowed any
   non-`ValueError` exception and returned `None`, unlike `journal_for_receipt`
   (hardened under F7/R1.6 to re-raise) — so the "journal posted first, so a
   posting failure aborts before any sub-ledger mutation" invariant this
   milestone's compensation logic depends on was not actually true for
   purchase payments: a swallowed posting failure would let a vendor payment
   be recorded and the linked bill marked paid with **no GL journal at all**.
   Fixed to re-raise, matching `journal_for_receipt` exactly.
3. **Low, documented, not fixed:** `debit_notes.py`'s `create_debit_note`
   inserts the header via `insert_with_number` (now durably unique) and then
   `debit_note_lines` afterward with no compensation; a lines-insert failure
   leaves an orphaned draft header with zero lines. Pre-existing, untouched by
   this diff, and not a money- or statutory-correctness issue (a draft with no
   lines) — tracked as a follow-up rather than fixed here.
4. **Nit, confirmatory:** reproduced against real Postgres that the
   already-disclosed `-DUPn` suffix collision edge case (an extremely
   contrived coincidence) surfaces as a loud `ALTER TABLE` failure requiring
   manual cleanup, not silent data corruption — confirms the accepted-risk
   framing in the migration's own docstring was accurate.

**Verified:** 2,303 backend tests pass (13 new across two files — real-Postgres
constraint/de-dup proof, and mock-mode compensation-logic unit tests including
the two new ownership-check regression tests and the `journal_for_purchase_payment`
re-raise test), same 23 pre-existing DB-dependent failures. Real-Postgres suite
(numbering proof, R1.1's per-client proof, R2.8's notice-approval proof,
migration-apply baseline, schema contract) rerun clean after the fixes.

**Next:** R2.11 (bank statement parser hardening), R2.12 (receipt→AR→journal
atomicity), R2.10 (payroll frontend→backend migration), then the Tier 2
regression review and Tier 3.

## Milestone R2.11 — Bank statement parser hardening (DELIVERED)

**Goal:** the R1.5 regression review flagged three independent bugs in
`domain/banking/normalizer.py`/`services/banking_service.py`: `_to_paise`'s
Dr/Cr suffix handling was case-sensitive (silently zeroing most real-world
case variants) and discarded the Dr/Cr sign entirely; single signed-Amount +
Dr/Cr-indicator statement layouts (no separate Debit/Credit columns) were
unsupported; and a statement's opening/closing balance was derived from raw
file position, inverting on newest-first exports.

**Fixes shipped:** `_to_paise` now strips a trailing Dr/Cr suffix via a
case-insensitive regex (previously `.rstrip("DrCr")` stripped individual
characters, so only the exact mixed-case "Dr"/"Cr" worked) and applies its
sign (Dr = negative/overdrawn, Cr = positive) — `debit_paise`/`credit_paise`
already wrap the result in `abs()`, so only the signed `balance` column is
affected. A new `generic_amount_drcr` adapter (Date, Description, Amount,
Dr/Cr, Balance) covers the single-amount-column layout, detected via a
combined Dr/Cr header cell and classified per-row by an indicator token
(unrecognized indicators skip the row rather than guess). A new
`_opening_closing_balance` helper in `banking_service.py` derives
opening/closing from the rows' `transaction_date` order instead of file
position, reversing the row list when the file is in descending order.

**Adversarial review (2 lenses — parsing-correctness and
balance-derivation/integration, run via the Workflow tool, each finding
independently re-verified) — 12 findings, all CONFIRMED (5 required code
fixes, 7 were confirmatory/no-defect notes):**
1. **High, fixed:** `_to_paise` double-negated the sign when a string
   carried BOTH an explicit leading `-` and a Dr/Cr suffix — `Decimal()`
   already parses the embedded minus into a negative value, then the Dr/Cr
   override negated it a SECOND time (`"-150.00 Dr"` returned `+15000`
   instead of `-15000`, hiding an overdraft; `"-150.00 Cr"` returned
   `-15000`, silently ignoring the Cr claim). Fixed by always parsing to an
   absolute magnitude first, then applying exactly one sign decision — a
   Dr/Cr suffix (when present) is authoritative over any embedded sign or
   parentheses, matching that the suffix is the statement's own explicit
   accounting label.
2. **Medium, fixed:** a Dr/Cr suffix trailing OUTSIDE a parenthesised amount
   (`"(150.00) Dr"`) silently returned 0 — the parens check ran before the
   suffix was located, so stripping only the leading `(` left an orphaned
   `)` that failed `Decimal()` parsing. Fixed by locating and stripping the
   suffix first, then checking for wrapping parens on what remains.
3. **High, fixed:** the new amount-mode detection fired on any header cell
   shaped like "Dr/Cr" without first checking whether the file *also* has
   separate, clearly-labelled Debit AND Credit amount columns (a statement
   can have both, with "Dr/Cr" marking the running balance's polarity, not
   the transaction's direction) — misrouting that file to the new adapter,
   which then failed every row and rejected the whole statement. Fixed by
   requiring the ABSENCE of separate debit/credit-token columns before
   routing to `generic_amount_drcr`.
4. **High, fixed:** the amount-mode indicator match required an exact token
   (`"dr"`/`"cr"`/etc.), so a bank using dotted abbreviations ("Dr.", "Cr.")
   had every row on that side silently dropped with no error — a materially
   incomplete import that looks like a success. Fixed by stripping trailing
   punctuation before matching.
5. **Medium, fixed:** `_opening_closing_balance`'s original two-endpoint
   compare could be fooled by a non-monotonic file — most concretely, a file
   whose FIRST and LAST rows coincidentally share one date while a row in
   between is on a genuinely earlier date was misclassified as "single-day"
   and silently discarded the true earliest date's balance entirely. Fixed
   by finding the true min/max date across every row (matching how
   `_import_core` already derives `statement_from`/`statement_to` via a full
   sort) and deciding direction by a majority vote across every adjacent
   pair, not just the two endpoints.
6. **High, confirmatory (no code change, documentation strengthened):** the
   deliberately-deferred "one-off re-import path" is a real, bounded risk,
   more significant than originally scoped — historically-imported
   statements hit by the OLD case-sensitivity bug had `balance_paise` (and
   any Dr/Cr-suffixed debit/credit cell) silently stored as **zero**, not
   merely mis-signed, for any non-mixed-case suffix (a common convention).
   Re-uploading the same file post-fix produces different, correct values,
   so the dedup hash won't match and the file re-imports as a **second,
   parallel set of `bank_transactions`** rather than correcting the
   historical rows — silently doubling totals, and risking a double-posted
   ledger entry if a CA matches/posts both copies without realizing it's a
   re-import. No cron or scheduled reprocessing exists anywhere in the repo
   (confirmed by grep), so this can only happen via an explicit re-upload —
   but given the severity, this follow-up (R2.11.1, not yet scheduled) is
   promoted ahead of other Tier 3 items rather than left as a vague
   documentation note.
7. **Nits (3), confirmatory, no defect:** `_opening_closing_balance` runs on
   the full deduped row list before the 500-row chunked insert loop, not per
   chunk; dedup only removes rows and never reorders survivors, so it
   doesn't independently make the direction heuristic less reliable; no
   downstream consumer currently reads a `bank_statements` row's
   opening/closing balance for any business logic (bank reconciliation
   sessions use their own, separately CA-entered opening/closing fields) —
   meaning this fix's benefit is real but presently dormant until something
   wires the derived value into reconciliation/reporting.

**Verified:** 34 unit tests in `test_r2_11_bank_parser_hardening.py` (10 new
beyond the initial 24, each directly proving one of the confirmed findings
above), all pure parsing/derivation logic with no database. Full suite:
2,337 passed, same 23 pre-existing DB-dependent failures as every prior
milestone.

**Next:** R2.11.1 (bank-statement re-import/replace path for pre-fix
statements — promoted by this milestone's own adversarial review), R2.12
(receipt→AR→journal atomicity), R2.10 (payroll frontend→backend migration),
then the Tier 2 regression review and Tier 3.

## Milestone R2.12 — Full receipt→AR→journal atomicity (DELIVERED)

**Goal:** R1.6 made receipt creation journal-first (post the GL journal, then
insert the receipt, then settle each allocated invoice via an app-level
optimistic CAS retry loop), compensating on failure rather than leaving a
phantom entry. Two residual gaps remained: an earlier invoice's CAS in a
multi-invoice settlement isn't rolled back if a later one fails, and R2.9
found the journal-posting idempotency fast-path can hand a losing request
another request's already-committed journal on a numbering collision,
requiring an ownership check before the compensation path could safely
reverse anything. This is the highest financial-correctness-stakes change of
the entire Tier 2 sequence — a new atomic multi-table money-movement
transaction — and was treated with correspondingly higher rigor: two
independent adversarial-review lenses, several findings reproduced directly
against real Postgres rather than argued from reading code alone.

**What shipped:** migration 160 adds `settle_receipt_atomic`, extending the
`post_journal_atomic` pattern (migration 152) to a much larger transaction —
the journal header, its lines, the receipt row, and every allocation's
row-locked (`SELECT ... FOR UPDATE`) invoice update all happen in ONE plpgsql
function body. Any failure rolls back the ENTIRE transaction; no partial
state can ever be observed, so no app-level compensation is needed for this
path. `services/receipt_service.py`'s `create_receipt_core` now prefers this
RPC whenever `db.rpc` is available (always true in production), building
journal lines via a new `phase2_journal_service.receipt_journal_lines`
helper (extracted from `journal_for_receipt`). Scoped to the plain-INR path
only; `create_foreign_receipt` (multi-currency) initially stayed on the
existing compensation pattern.

**Adversarial review (2 lenses — SQL/transaction-correctness and
Python-integration/scope, several findings reproduced directly against real
Postgres) — 10 findings, 9 CONFIRMED, 1 REFUTED (itself just a
mis-attributed restatement of a confirmed finding):**
1. **Critical, fixed (migration 161):** the two real production callers of
   this path supply `payment_mode` values (`"online"` hardcoded in
   `payment_service.py`'s webhook settlement; `"bank_transfer"`, the
   `ReceiptIn`/`PurchasePaymentIn` Pydantic default) that violate the
   `receipts`/`purchase_payments` `payment_mode` CHECK constraint — reproduced
   directly: `settle_receipt_atomic` correctly rolled back everything, but
   the online-payments feature could not successfully create a **single**
   receipt against a real (non-mock) Postgres database. Pre-existing (the
   CHECK dates to migration 050; the Pydantic defaults predate this
   session) but only surfaced by this milestone's own real-Postgres testing.
   Fixed by widening both CHECK constraints to accept `"online"` and
   correcting both Pydantic defaults from the never-valid `"bank_transfer"`
   to `"bank"`.
2. **Medium, fixed (migration 162):** `settle_receipt_atomic` had no
   equivalent of `phase2_journal_service._create_journal`'s debit==credit
   and non-zero guards — reproduced directly: an imbalanced 2-line journal
   (Dr 100000/Cr 1) and an empty-lines zero-value journal both posted
   successfully, and (per the journal-immutability trigger) were permanently
   unfixable afterward. Not reachable via today's only caller
   (`receipt_journal_lines` always builds balanced lines), but the ONLY
   enforcement of this invariant anywhere in the codebase was silently
   bypassed by this new path. Fixed by adding the same two checks before any
   insert.
3. **Low, fixed (migration 162):** a second, arithmetically-valid allocation
   row for the same invoice in one call always rolled back the whole
   settlement (the arithmetic was summed correctly across both rows, but the
   second `receipt_allocations` insert violated its own
   `UNIQUE(receipt_id, sales_invoice_id)` constraint) — contradicting
   `create_receipt_core`'s own pre-validation comment, which states such
   requests are meant to be supported. Fails safe (full rollback, confirmed),
   but a real availability gap. Fixed by pre-aggregating allocations by
   `sales_invoice_id` before the per-invoice loop.
4. **High, fixed:** the RPC-failure classifier in
   `_settle_receipt_via_atomic_rpc` did a bare substring check for the
   function's own name to detect "RPC not found" — but the function's own
   legitimate business-rule errors (invoice-not-found, exceeds-outstanding)
   are themselves prefixed with that same name, so a genuine concurrent-race
   rejection was misdiagnosed as "migration 160 not applied," masking the
   real error and losing the specific 409/422 detail every other caller of
   this exact condition gets. The SAME bug class was found (by inspection,
   once the pattern was known) in the pre-existing, unrelated
   `post_journal_atomic` classifier in `_create_journal` — fixed identically
   in both: require the actual missing-function signature (`PGRST202`, or a
   raw "function ... does not exist"), never the function's own name.
5. **High, fixed:** `create_foreign_receipt`'s per-invoice settlement CAS
   made a SINGLE attempt with no retry (immediate 409 on any concurrent
   write) and read its `paid_paise` baseline before posting the journal — a
   materially weaker, wider-window guarantee than the plain-INR path's
   6-attempt retry loop this milestone replaced, undercutting the framing
   that this excluded path was "adequately protected" by the existing
   pattern. If anything, it was MORE exposed than the path that got fixed.
   Fixed by adding a 6-attempt retry loop that re-reads the invoice fresh on
   every attempt, matching the legacy INR path's robustness (not the new
   atomic transaction's guarantee, but no longer strictly weaker than what
   existed before this milestone).
6. **Low, fixed:** `journal_for_receipt`'s and `receipt_journal_lines`'
   docstrings (written earlier in this same milestone) incorrectly claimed
   `create_foreign_receipt` uses `journal_for_receipt` — it doesn't; it
   builds its own FX-aware lines inline. Corrected.
7. **Low, fixed (migration 162):** the RPC's returned jsonb omitted the full
   receipt row, so the atomic path's audit `log_event` had to reconstruct
   `new_data` from the Python-side payload, silently missing DB-default
   columns (`allocated_paise`, `updated_at`) the pre-atomicity path's
   equivalent entries always included. Fixed by returning the full inserted
   row (`RETURNING * INTO`) alongside the existing keys.
8. **Low, pre-existing, documented not fixed:** `PurchasePaymentIn`'s
   identical `"bank_transfer"` default (same root cause as finding 1) — fixed
   incidentally as part of finding 1's fix, since both models share the same
   correction.
9. **Nits (2), confirmatory:** the receipt-audit and confirmed-safe-rollback
   observations needed no further action beyond findings 1–7 above.

**Verified:** 16 real-Postgres tests in `test_r2_12_atomic_receipt_settlement_pg.py`
(6 proving the core atomicity guarantee — successful settlement, sequential
partial settlements, over-allocation/unknown-invoice/receipt_no-collision all
rolling back EVERYTHING with zero orphan rows, a balanced 3-line TDS journal —
plus 10 fix-phase proofs for every numbered finding above that touched SQL);
9 new mock-mode unit tests (`test_r2_12_python_integration.py`) proving the
RPC-error classifier's precision and the foreign-receipt retry loop actually
retries-then-succeeds and eventually gives up after 6 attempts. Full suite:
2,346 passed, same 23 pre-existing DB-dependent failures as every prior
milestone. Migration-apply baseline and schema contract tests rerun clean.

**Next:** R2.11.1 (bank-statement re-import path), R2.10 (payroll
frontend→backend migration), then the Tier 2 regression review and Tier 3.

## Milestone R2.10 — Route payroll compute through the backend (DELIVERED)

**Goal:** `apps/web/app/payroll/page.tsx` computed payroll (gross/PF/ESI/PT/TDS)
client-side via its own `computeSlip()` and wrote directly to Supabase
(`payroll_runs`/`payroll_slips`/`payroll_employees`), bypassing the backend's
RBAC, Guardrail G4 (no payroll/HR for the internal practice client), and the
already-correct server-side `_compute_slip()` behind `POST /api/payroll/runs`.
It also wrote `payroll_runs.status = "generated"` — a value outside the
`draft`/`review`/`finalized` CHECK constraint — and never populated the run's
`total_*_paise`/`headcount` columns, permanently blocking `finalize_run` for
any run created this way. Ultracode was off for this milestone, so — per its
own standard opt-in rule — this was implemented and verified directly rather
than via the Workflow tool's multi-agent adversarial-review pattern used for
R2.8/R2.9/R2.11/R2.12; the findings below were surfaced by direct code
reading and real-Postgres/browser testing, not a separate review pass.

**What shipped:**
- **Backend bug fix:** `GET /runs/{run_id}/slips` filtered
  `.eq("firm_id", ...)` directly on `payroll_slips` — a column that has
  never existed there (it's tenant-scoped transitively via
  `run_id -> payroll_runs.firm_id`, migrations 014/093). PostgREST rejects
  an unknown-column filter outright against real Postgres, so this endpoint
  could never have returned data in production. Fixed to verify run
  ownership via `payroll_runs.firm_id` first, then query slips by `run_id`
  alone — proven directly against real Postgres (the old query pattern
  reproduced failing, the new one reproduced succeeding).
- **Backend API surface:** made `client_id` optional on `GET /employees` and
  `GET /runs` (the same optional-filter idiom `routers/accounting.py`'s
  journal listing already uses) so a firm-wide payroll dashboard can list
  every client's employees/runs in one call each, instead of an N-calls
  fan-out per client; a per-client workspace still passes `client_id` to
  scope the result. Both forms stay firm-scoped — regression-tested for
  cross-firm isolation in both the scoped and unscoped form.
- **Tax-correctness fix (found while scoping, not part of the original
  ask):** `_compute_pt(gross_paise, state)` accepted a `state` parameter but
  its body ignored it entirely, always applying Karnataka's slab regardless
  of the employee's actual `pt_state` — masked until now because the
  frontend's own client-side PT logic (correct, per-state) was what
  actually ran in production. Naively "just routing through the backend"
  would have silently regressed Professional Tax to Karnataka's rate for
  every non-Karnataka client — a real accounting-correctness regression,
  not a neutral refactor. Fixed with a per-state slab table:
  Karnataka keeps its existing, already-unit-tested 3-tier slab unchanged;
  Maharashtra/West Bengal/Tamil Nadu are ported verbatim from the frontend's
  own `PT_STATES` logic (the only source for those three states anywhere in
  this repo) and explicitly flagged pending statutory verification — the
  same "verified baseline vs. pending verification" split this session uses
  for FY2026-27 income-tax figures, applied here to state PT law instead of
  central IT Act slabs. An unset or unrecognised `pt_state` now returns 0
  instead of silently defaulting to Karnataka's rate.
- **Frontend rewrite (`app/payroll/page.tsx`):** removed `computeSlip()`,
  the raw-Supabase `load()`/`AddEmployeeModal.save()`/`generatePayslips()`/
  CSV-import writes, and the stale `INSTALL_SQL` "tables missing" fallback
  (a leftover from before the real migrations existed). `generatePayslips()`
  now calls `POST /api/payroll/runs` — the existing, already-correct compute
  endpoint — instead of building slip rows client-side.
  `AddEmployeeModal`/CSV import now call `POST /api/payroll/employees`,
  gaining a per-employee Professional Tax (state) field the client-side path
  never captured at all. The Monthly Run tab's pre-generation preview
  (previously a fully computed table using the buggy client-side logic) was
  replaced with a plain employee list — the server is now the ONLY place
  gross/PF/ESI/PT/TDS are computed; building a second, throwaway "dry run"
  compute path just to keep a live preview was judged out of scope for this
  milestone. All data loading and mutation errors now surface through a
  proper error banner (with a working Retry button) instead of an
  unhandled promise rejection or a silent blank state.
- **Frontend bug fix (`app/clients/[id]/payroll/page.tsx`):** its local
  `apiFetch()` helper never attached the caller's bearer token — every call
  from this page would 401 against a real (non-mock) backend, so this whole
  page could never have worked in production. Fixed to attach
  `Authorization: Bearer` exactly like `lib/api/index.ts`'s `request()`
  helper does.
- **`lib/api/index.ts`:** extended the `payroll` namespace with
  `listEmployees`/`createEmployee`/`updateEmployee`/`listRuns`/`createRun`/
  `getRunSlips`/`updateRunStatus`/`finalizeRun` (it previously had only
  `downloadPayslip`).
- **CI / test infra:** the 12 existing zero-npm-dependency `*.test.ts` files
  (pure `node:test` + `node:assert/strict`, 93 tests total) had no CI runner
  at all. `frontend-ci.yml` was pinned to Node 20, which predates
  `--experimental-strip-types` (needs ≥22.6). Bumped CI to Node 22, added a
  `pnpm test` script (`node --experimental-strip-types --test`, which
  auto-discovers every `*.test.ts` file recursively with no glob
  configuration needed), and added a Test step between type-check and build.

**Verified:** Backend — 3 new real-Postgres tests
(`test_r2_10_payroll_slips_pg.py`) proving `payroll_slips` genuinely has no
`firm_id` column, that the pre-fix query pattern fails against real schema,
and that the fixed pattern succeeds and returns the right rows; 6 new
mock-mode tenancy tests (`test_tenancy_backstop.py`: 3 for `get_run_slips`
cross-firm/own-firm/missing-run, 3 for the new optional-`client_id` list
behavior proving both the scoped and firm-wide forms stay firm-isolated);
8 new/updated PT unit tests (`test_v13_payroll_assets.py`) covering
Karnataka's pre-existing slab (now passed explicitly rather than relying on
the old accidental default), Maharashtra, West Bengal, Tamil Nadu, an
unrecognised state code, an unset state, and case/whitespace insensitivity.
Full mock-mode suite: 2,363 passed, same 23 pre-existing DB-dependent
failures as every prior milestone. Frontend — `tsc --noEmit` clean,
`eslint` clean, a full `next build` clean (every route compiles, including
`/payroll` and `/clients/[id]/payroll`), and the new 93-test `node:test`
suite passes via `pnpm test`. Manual dev-server verification via a
headless-Chromium Playwright script: confirmed `/payroll` is correctly
gated by `AuthGuard` when unauthenticated (redirects cleanly, no crash);
then, with a synthetic session forced into `localStorage` to get past that
gate — this sandbox has no live Supabase project, so a real login was not
possible here — confirmed the rewritten page mounts cleanly, its `load()`
effect chain runs to completion, a real backend error
(`503 SUPABASE_URL not set`, since this sandbox's backend has no Supabase
project configured either) is caught and rendered through the new error
banner with a working Retry button, and zero uncaught client-side
exceptions occur throughout. Deeper interactive verification — adding a
real employee, generating an actual run, viewing computed payslips end to
end — requires a live Supabase project and a real authenticated login,
which this sandbox cannot provide; flagged explicitly here rather than
claimed.

**Next:** R2.11.1 (bank-statement re-import path), then the Tier 2
regression review, then Tier 3.

## Tier 2 Regression Review (R2.1–R2.12 — CLOSED)

All 12 Tier 2 items are delivered. This review reads back across every
milestone's own Implementation Log entry, re-runs the full test suite in
one combined pass, and reconciles the roadmap (Section 10) against what
actually shipped — several of its Tier 2 bullets had never been updated
past their original "problem statement" wording despite the underlying work
being long done; that inconsistency is fixed as part of this review.

### Every issue fixed, by milestone

- **R2.1 — Year-end schema (F9/F10).** F9's real scope was all 8 of
  migration 067's tables (not the 3 originally cited), fixed via migration
  155 plus code fixes proven with live-Postgres inserts; F10's Balance Sheet
  fixed to fetch a cumulative-to-date window for BS accounts instead of
  reusing the FY-only window correct only for P&L. Two tenancy IDORs found
  and fixed alongside (year-end checklist, year-end mappings).
- **R2.2 — Missing tables (F5).** Scope grew from ~13 to 24 phantom tables +
  2 RPCs; migration 156 creates 21 tables, proven on real Postgres; the
  `get_supabase_client` phantom-import bug (see R2.4) fixed for all 10
  affected files, un-dead-ending 7 feature areas. Two more real bugs found
  and fixed (customer/vendor import client_id, a message-count RPC that
  reset counts to zero on every write).
- **R2.3 — TDS & ITR statutory logic (F17/F18).** Rebuilt as FY-versioned
  data with FY 2025-26 as the verified baseline (explicit product decision)
  and FY 2026-27 flagged unverified rather than invented. F18's 10×
  paise-scaling bug fixed by deleting its duplicate tax engine; §87A/
  surcharge marginal relief corrected (adversarial review caught and fixed
  an old-regime overgeneralization); payroll §192 moved off float math.
- **R2.4 — Tenancy backstop (F1/F4).** Fixed `can_access_client`'s actual
  structural flaw (firm-wide roles bypassed firm-membership checking) plus
  3 real cross-tenant IDORs found by a systematic sweep (payroll, GSTR-9,
  ITR version history).
- **R2.5 — `/join` escalation + portal invites (F21/F22).** Moved account
  linking to a token-validated backend endpoint; added tokenized, expiring
  portal invites; found and fixed that the actual live "Invite to Portal"
  button bypassed the audited service entirely; self-caught an
  UPDATE-based escalation bug and a regression in the fix itself before
  either shipped.
- **R2.6 — RLS predicates + migration hygiene (F20).** Fixed 43 tables'
  deny-all RLS policies keyed on a JWT claim this system never issues;
  added a migration-numbering ratchet. Production-drift reconciliation
  explicitly NOT done — no credentials, and it's the wrong kind of action
  to take autonomously regardless.
- **R2.7 — Workflow engine (F11/F12).** Migration 068 never fully applied
  on a fresh database; fixed via migration 157. Deleted a dead router
  whose catch-all shadowed the real one (F11); made 2 action types write
  real rows, with every other type honestly marked `skipped` (F12).
  Adversarial review found and fixed a critical regression risk plus 3
  more real bugs (cron scheduling never actually worked at all).
- **R2.8 — AI extraction (F19).** Found four overlapping fabrication code
  paths (not one), two of which persisted fake data; a fourth, undisclosed
  generation found only by adversarial review. All four now fail honestly
  instead of fabricating. Two unrelated cross-firm prompt-context leaks in
  the AI copilot fixed alongside.
- **R2.9 — Document-number uniqueness.** Added UNIQUE constraints (with a
  de-dup migration first) for debit notes, receipts, and purchase payments.
  Adversarial review found and fixed a critical bug in the new
  collision-compensation logic itself (it could reverse a different
  request's already-committed journal).
- **R2.10 — Payroll frontend→backend (F14 slice).** Routed the payroll
  page through the existing, correct `POST /api/payroll/runs` instead of
  client-side compute + raw Supabase writes. Found and fixed a real
  backend bug (`get_run_slips` filtered on a nonexistent column) and a
  genuine tax-correctness gap (`_compute_pt` silently ignored its own
  `state` parameter). Wired the frontend's 12 dormant test files into CI.
- **R2.11 — Bank statement parser hardening.** Fixed 5 defects: Dr/Cr
  suffix parsing (case sensitivity, double-negation, parens interaction),
  unsupported single-Amount+indicator layouts, punctuation-intolerant
  indicator matching, and opening/closing balances taken by file position
  instead of true date order.
- **R2.12 — Receipt→AR→journal atomicity.** Extended the atomic-journal
  pattern to a single transaction covering the journal, receipt, and every
  allocation's row-locked invoice update. Two adversarial-review lenses
  found 9 confirmed issues (1 refuted) — a `payment_mode` CHECK violation
  real production code actually triggers, a missing balance/zero guard, a
  duplicate-allocation bug, an RPC-error misclassification, and a
  multi-currency CAS with no retry at all.

### Full-suite regression evidence (this review, combined)

Ran the complete backend suite with the real-Postgres harness enabled
(`HARNESS_PG` set), which runs every mock-mode test plus every
`HARNESS_PG`-gated real-Postgres proof across all 12 milestones in one
pass: **2,396 passed, 23 failed, 36 skipped.** The 23 failures are the
same pre-existing, unrelated `test_hardening.py`/`test_phase3_gst.py`/
`test_phase3_mca.py`/`test_phase3_tds.py` failures documented as present
since R2.5 (a test-isolation issue, not a Tier 2 regression) —
reconfirmed unrelated by their unchanged identity and count across every
single milestone in this sequence. `test_migrations_apply.py`,
`test_schema_contract.py` and `test_migration_numbering.py` (the
migration-drift/phantom-table/duplicate-number ratchets spanning the
whole Tier 2 sequence) all pass cleanly — no migration regression, no new
phantom table/RPC reference, no new duplicate migration number introduced
across 12 milestones and the 10 migrations Tier 2 added (153 through 162).

### Every newly discovered or deferred issue (consolidated)

Everything below is now tracked in the roadmap (Section 10) rather than
living only in a milestone's own notes:

1. **Highest priority — R2.6's production-drift reconciliation.** Not yet
   run against the real Supabase project; every Tier 2 fix is proven only
   against a disposable, freshly-migrated Postgres 16 instance. This is a
   human-with-production-credentials action, not something this session
   can or should do autonomously.
2. **R3.0** — `client_portal_users` RLS allows any firm staff member to
   directly write a row, bypassing the tokenized invite service (R2.5).
3. **R3.7** — no explicit year-end closing journal exists; a second
   never-closed prior year's retained profit would stay invisible (R2.1) —
   needs a business/accounting decision, not a unilateral fix.
4. **R3.8** — two competing year-end status-transition implementations
   write overlapping column sets to the same table (R2.1).
5. **R3.9** *(new)* — ~57 migration-created tables have no backend reader;
   some may be reached directly from the frontend via PostgREST, the same
   F14-class concern R2.10 just fixed for payroll (R2.2).
6. **R3.10** *(new)* — Section 80CCD(2) (employer NPS) is unimplemented;
   Section 206AB's FY 2025-26 applicability needs verification (R2.3).
7. **R2.11.1** — a one-off re-import path for bank statements imported
   before R2.11's fixes; needs a product decision on re-import matching
   aggressiveness before implementation (R2.11).
8. **R3.11** *(new)* — `debit_notes.create_debit_note`'s header/lines
   insert has no compensation; a lines-insert failure orphans a
   zero-line draft header. Low priority — not a money or statutory issue
   (R2.9).
9. **R3.12** *(new)* — Maharashtra/West Bengal/Tamil Nadu Professional Tax
   slabs are ported from the pre-existing frontend and flagged pending
   statutory verification, same treatment as FY 2026-27's tax figures
   (R2.10).
10. **Roadmap bookkeeping corrected by this review** — R2.2, R2.3, R2.7,
    R2.8, R2.9, R2.11 and R2.12's Section 10 bullets had never been
    updated from their original pre-delivery wording despite being fully
    shipped and documented here; all seven rewritten to reflect what
    actually happened. R2.4's `get_supabase_client` finding was marked
    "not yet scheduled" in the roadmap even though R2.2 had already fixed
    it — corrected to point at R2.2 instead of appearing as a second,
    still-open item.

None of the above are launch-blocking in the sense R2.1–R2.12 themselves
were (wrong numbers, cross-tenant reads, or endpoints that could never
work) — they are either genuine business decisions this session
correctly declined to make unilaterally, narrow low-severity gaps, or
verification/consolidation work. The one exception is item 1, which is
not a code defect but a process gap: **nothing in this entire Tier 2 body
of work has been proven against the real production database**, and that
should happen before any of it is considered load-bearing in production.

**Next:** Tier 3, starting with whichever item the user prioritizes —
R3.1 (statutory rules-as-data registry) and R3.2 (cross-client batch
compliance cockpit) are flagged in Section 9 as the highest-leverage
scale unlocks; R2.6's production-drift reconciliation should happen
first regardless of which Tier 3 item comes next, since it requires
credentials this session doesn't have and blocks nothing else.

## Milestone R3.0 — Harden `client_portal_users` RLS/grants (DELIVERED)

**Goal:** close the audit-integrity gap this review's own consolidated list
flagged: migration 109's `client_portal_users_own_firm` policy was `FOR ALL`,
scoped only by `firm_id` — any authenticated firm staff member (any role)
could directly INSERT/UPDATE/DELETE a `client_portal_users` row from the
browser, bypassing `services/portal_access_service.py`'s `invite_contact()`
(its token/TTL/audit trail) entirely. Not a cross-tenant confidentiality leak
(staff already have equivalent CA-side access to the same client's data) but
a real audit-integrity gap — a staff member could self-activate an arbitrary
contact, or read another contact's plaintext `invite_token` (a bearer secret)
via the same broad grant.

**Investigation before implementing:** confirmed `portal_access_service.py`'s
`invite_contact`/`resend_invite`/`deactivate_contact`/`accept_portal_invite`
(all running through `get_service_supabase()`, the service-role client which
bypasses RLS regardless) collectively write every column this table has
other than `id`/`created_at` — so a SELECT-only RLS/grant change cannot break
any backend functionality. A repo-wide check confirmed `apps/web` has zero
direct `.from("client_portal_users")` calls of any kind (read or write) —
every frontend interaction already goes through the backend REST API
(`api.portal.*`). This is the key difference from the R2.5 `users`-table
fix, which needed a column-level `GRANT UPDATE (full_name)` to preserve a
real "rename yourself" frontend feature: `client_portal_users` has no
analogous frontend-initiated write dependency at all, so a clean
`REVOKE INSERT, UPDATE, DELETE` with no replacement grant is the correct,
simpler fix here.

**What shipped:** migration 163 — `REVOKE INSERT, UPDATE, DELETE ON
public.client_portal_users FROM authenticated`, then
`client_portal_users_own_firm` (previously `FOR ALL`) dropped and recreated
as `FOR SELECT` only, same name, same `firm_id = get_my_firm_id()` predicate.
The sibling `client_portal_users_self` policy (already SELECT-only, relied on
by OR-combined policies on `client_documents`/`document_requests`/
`portal_messages`/`shared_reports`) is untouched.

**Verified:** 6 new real-Postgres tests
(`test_r3_0_client_portal_users_rls_pg.py`), simulating an authenticated
PostgREST session via `SET request.jwt.claims` + `SET ROLE authenticated`
(matching `_supabase_compat_bootstrap.sql`'s `auth.uid()`/`auth.jwt()`
shims) against a freshly-migrated Postgres 16 database: an authenticated
firm-staff session can still `SELECT` its own firm's contact (and a
different firm's contact is invisible — the pre-existing scoping, unchanged);
`INSERT`/`UPDATE`/`DELETE` from that same session all fail with
`permission denied for table client_portal_users`; and the
`service_role`-backed path (the actual backend mutation path) still
completes an insert/update/delete cycle without issue. Full mock-mode suite:
2,363 passed, same 23 pre-existing unrelated failures. Migration/schema
ratchets (`test_migrations_apply.py`, `test_schema_contract.py`,
`test_migration_numbering.py`) and the full `test_portal_foundation.py`
suite (27 tests, FakeDB-based service-logic proofs, unaffected by this
database-layer change) all pass clean.

**Next:** R3.1 (statutory rules-as-data registry) or R3.2 (cross-client
batch compliance cockpit), per the user's priority; R2.6's production-drift
reconciliation remains the standing highest-priority action for whoever has
production credentials.

## Milestone R3.1 — Statutory rules-as-data registry, re-scoped (DELIVERED — R3.1a + R3.1b)

**Goal:** the original roadmap text ("single source of truth for slabs/
thresholds/due-dates; eliminates the class of bugs behind F15/F17/F18")
undersold the item — R2.3 already delivered the core of it for income tax
and vendor TDS. Before building more, audited the ENTIRE backend (and,
where relevant, the frontend) for statutory numbers still living outside
those registries. The audit found the scope is both narrower (some of what
R3.1 implied is already done) and wider (several categories R2.3 never
touched at all) than the roadmap suggested.

**Audit findings, in full:**
1. **Confirmed by R2.3's own notes:** `itr_engine.py` had 4 inline
   capital-gains constants (§111A 20% STCG-equity, §112A 12.5% LTCG-equity +
   ₹1.25L exemption, §112 12.5% LTCG-other) never migrated into
   `statutory_rates.py`.
2. **New, most serious finding:** `apps/web/app/income-tax/capital-gains/page.tsx`
   is a complete SECOND capital-gains tax engine in TypeScript — its own
   hardcoded Cost Inflation Index (CII) table (which doesn't exist in the
   backend AT ALL — a missing capability, not just a duplicate), its own
   holding-period classification (12/24 months, Section 2(42A)), the same
   111A/112A/112/115BBH rates computed three separate ways within one file,
   and results persisted directly to a `capital_gains` Supabase table with
   zero backend validation. A genuine "business logic in the frontend"
   violation with real financial consequences. Properly fixing this means
   building real CII/holding-period support in the backend first — tracked
   separately as **R3.1b** (not a quick win; see below).
3. **Compliance due dates:** a good backend source of truth exists
   (`services/compliance_engine.py`) but was bypassed by
   `routers/gst_workspace.py`'s own duplicate GSTR-1/GSTR-3B due-date
   arithmetic, and MCA due-date offsets (AOC-4/MGT-7/ADT-1) were hardcoded
   independently in TWO backend files with no shared constant at all. The
   frontend independently re-implements the entire due-date domain in at
   least 4 places, three of which (`lib/data/compliance.ts`,
   `app/payroll/page.tsx`, `app/income-tax/advance-tax/page.tsx`) compute
   and PERSIST data rather than merely displaying it — `lib/data/compliance.ts`
   writes straight to a `compliance_calendar` table from the browser, and
   `advance-tax/page.tsx` has a frontend-only Section 234C interest
   calculator with no backend equivalent.
4. **A genuine, separate bug (not just duplication):**
   `apps/web/app/mca/page.tsx` hardcoded `const TODAY = new Date("2026-06-02")`
   — a FROZEN fake "current date" used throughout the page, not just for a
   display list. This corrupted real data: marking an MCA filing "Filed"
   wrote this frozen date as `filed_date` regardless of when the filing
   actually happened, and every "Overdue" status calculation compared
   against June 2026 forever. `KEY_DEADLINES` was also hardcoded to a single
   non-recurring year and would have shown stale dates from 2027 onward.
5. Sections 206AA (missing-PAN 20% rate) and 206AB (non-filer doubled rate)
   are hardcoded in two places each, with no `verified` flag and no FY
   registry — 206AB in particular needs re-verification against Finance Act
   2025, which cannot be confirmed from the repository alone.
6. TCS (Section 206C) has a rate entry in `section_rates.py` but zero
   runtime readers anywhere — effectively unimplemented as a feature despite
   looking, from the registry alone, like a supported section.
7. Confirmed operationally relevant: both FY-versioned registries currently
   resolve to their `verified=False` FY 2026-27 entry by default (today's
   date falls in that FY) — the carried-forward-pending-verification state
   is not hypothetical, it is what every unpinned computation uses right now.

**Scope decision (with the user):** tackle the quick, safe consolidation
wins first (R3.1a, below), then take on the capital-gains backend build
(R3.1b) as a distinct follow-up — not because it's lower priority (it's
arguably the single most serious frontend violation found this session),
but because it requires new backend capability, not just moving constants
around, and deserves to be scoped and verified on its own.

### R3.1a — Quick consolidation wins (DELIVERED)

- **Capital-gains rates migrated:** `FYTaxRates` (statutory_rates.py) gained
  `stcg_111a_rate_bps`, `ltcg_112a_rate_bps`, `ltcg_112a_exemption_paise`,
  `ltcg_112_other_rate_bps` (basis points, matching the registry's existing
  convention for non-whole-percent rates); `itr_engine.py`'s 4 inline
  constants replaced with reads from `rates`. Proven with a test that swaps
  in a `FYTaxRates` with different capital-gains rates via `dataclasses.replace`
  and confirms the engine's computed tax changes accordingly — not just that
  the old hardcoded values still happen to match.
- **`gst_workspace.py`'s duplicate GSTR-1/GSTR-3B due-date arithmetic**
  replaced with calls to `services/compliance_engine.py`'s canonical
  `gstr1_due_date`/`gstr3b_due_date` (the same functions every other GST/TDS/
  ITR due date in the codebase already used) — thin string-in/string-out
  adapters over the canonical `date`-returning functions.
- **MCA due-date offsets consolidated:** new `compliance_engine.MCA_AGM_OFFSET_DAYS`
  (`{"ADT-1": 15, "AOC-4": 30, "MGT-7": 60}`) and `mca_due_date(agm_date, form_type)`
  — both `compliance_obligation_service.py::_roc_obligations` and
  `routers/mca_workspace.py`'s `/calendar` endpoint now read the same table
  instead of two independently hardcoded copies (the latter previously also
  covered ADT-1, which the former still doesn't generate as a tracked
  obligation — a deliberate, out-of-scope-for-this-pass observation, not a
  fix, since adding a new tracked obligation type is a feature decision).
- **`apps/web/app/mca/page.tsx`'s frozen fake "today" bug fixed:**
  `TODAY` is now `new Date()`, not a hardcoded string — closing the
  `filed_date`-corruption bug described in finding 4 above. `KEY_DEADLINES`
  rewritten to compute the next occurrence of each deadline relative to the
  real current date (same 30-Sep statutory-AGM-fallback convention the
  backend uses) instead of a single hardcoded year.
- **TCS (206C) entry:** left in place (the rate itself — 0.1% — appears
  correct for Section 206C(1H)) but both the entry and the module docstring
  now explicitly flag that no computation anywhere reads it, so it can't be
  mistaken for a supported feature. Building real TCS/27EQ support is a
  distinct feature decision, not part of this consolidation.

**Verified:** 11 new backend tests (`test_statutory_rates.py`,
`test_itr_engine.py`, `test_r3_1_statutory_registry_consolidation.py`); full
mock-mode suite 2,373 passed, same 23 pre-existing unrelated failures.
Frontend: `tsc --noEmit` clean, `eslint` clean, full `next build` clean.

**Next:** R3.1b (capital-gains backend engine + frontend migration) — a
distinct, larger piece of work, not a quick win.

## Milestone R3.1b — Build a real capital-gains engine (DELIVERED)

**Goal:** `apps/web/app/income-tax/capital-gains/page.tsx` was a complete
capital-gains tax engine written in TypeScript — a hardcoded Cost Inflation
Index (CII) table, Section 2(42A) holding-period classification, and the
full Section 111A/112A/112/115BBH/50AA tax-rate logic, all computed AND
persisted to a real `capital_gains` Supabase table entirely client-side,
with zero server-side validation. The backend had no equivalent capability
at all — `domain/income_tax/itr_engine.py` only accepts already-classified,
already-computed STCG/LTCG paise amounts as input. Properly fixing the
"business logic in the frontend" violation this represents required
building the missing capability first, not just moving constants around
(unlike R3.1a's quick wins).

**What shipped:**
- **New `domain/income_tax/capital_gains_engine.py`** — the CII table
  (ported verbatim from the frontend, the only source for these figures
  anywhere in this repo), Section 2(42A) holding-period classification
  (12 months for listed equity/equity MF, 24 months for everything else —
  Budget 2024's simplified two-tier system), and the full tax-rate logic
  for all six asset types (equity, debt MF, property, unlisted shares, VDA,
  gold), each faithfully porting the frontend's existing section references
  and Budget 2024 dates. Integer round-half-up arithmetic throughout (no
  float intermediate steps, unlike the frontend's `Math.round`).
- **A genuine inconsistency found and fixed while unifying two
  independent frontend implementations into one:** the page's interactive
  calculator computed the REAL "12.5% without indexation OR 20% with
  indexation, whichever is lower" choice for property LTCG (the actual
  Budget 2024 grandfather-clause mechanism for resident individuals/HUFs on
  immovable property acquired before 23 Jul 2024) — but the SAME page's
  register (a persisted transaction log, not just a calculator) always
  hardcoded a flat 20% for every non-equity LTCG asset type and never even
  computed the 12.5% alternative. Every register entry saved under the old
  code for property/unlisted/gold LTCG could have recorded a higher tax
  rate than the law actually allows. The unified engine now gives the
  register the calculator's more complete logic.
- **New backend endpoints** (`routers/income_tax.py`): `POST
  /capital-gains/compute` (stateless estimator, no persistence), `GET
  /capital-gains` (firm+client-scoped list), `POST /capital-gains` (computes
  AND persists — the request model has no `gain_type`/`tax_rate_percent`/
  `indexed_cost_paise` field at all, so there is no way for a caller to
  supply and have stored a value the engine itself didn't compute), `DELETE
  /capital-gains/{id}` (firm-scoped), and `GET /capital-gains/cii-table` (so
  the frontend's reference table display reads from the same source the
  engine computes with, instead of keeping a second hardcoded copy that
  could silently drift from it).
- **`capital_gains` table RLS hardened** (migration 164) — the same
  `FOR ALL` / firm-id-only gap R3.0 fixed for `client_portal_users`: any
  authenticated firm staff member could directly INSERT/UPDATE/DELETE a
  capital-gains row with self-reported values. Migration 030 (`capital_gains`)
  predates migration 084 (assignment-scoped RLS), so — unlike
  `client_portal_users` — this table also carries an automatically-applied
  `AS RESTRICTIVE` policy requiring `can_access_client()`; this was
  discovered while debugging why a first draft of the real-Postgres RLS
  proof failed for a non-Partner role, not a new bug this migration
  introduces.
- **Frontend rewrite:** `capital-gains/page.tsx`'s hardcoded CII table,
  `computeGains`/`getRegGainType`/`getRegTaxRate` all removed. The
  calculator now calls the compute endpoint with a 400ms debounce (matching
  the deductions-page pattern); the register's add-transaction modal's live
  preview does the same instead of re-implementing the classification
  inline; `loadRecords`/`handleSaveRecord`/`deleteRecord` call the new
  backend endpoints instead of raw Supabase reads/writes. The "tax without
  indexation" / "tax with indexation" comparison display was changed to
  render two explicit paise amounts the backend now returns, rather than
  the frontend re-deriving `rate * gain` itself — a JS float `Math.round`
  re-derivation of a value the backend already computed via integer
  round-half-up could, in principle, disagree by a paise at the boundary.
  Also found and fixed: two unused, dead functions in
  `lib/data/income-tax.ts` (`getCapitalGains`/`saveCapitalGain`, zero
  callers anywhere) that did the identical raw-Supabase-write violation —
  replaced with the new backend-calling equivalents so the file's public
  API doesn't quietly re-offer a broken pattern to some future caller.

**Verified:** 29 new backend tests (18 in `test_capital_gains_engine.py`
cross-checking exact worked examples — including a clean 3.8× CII-ratio
case chosen so the indexed-cost arithmetic could be hand-verified
precisely, and both directions of the "which is lower" property-LTCG
comparison; 9 in `test_r3_1b_capital_gains_endpoints.py` proving the create
endpoint's request model cannot accept a caller-supplied gain_type/tax_rate,
and firm-scoping on list/delete; 5 in `test_r3_1b_capital_gains_rls_pg.py`
against real Postgres 16, plus the 2-fold "not property, but still gets the
correct new registry fields" cross-check added to
`test_capital_gains_engine.py`). Full mock-mode suite: 2,402 passed, same 23
pre-existing unrelated failures; combined with `HARNESS_PG` enabled (every
real-Postgres proof across all of Tier 2 + R3.0 + R3.1a + R3.1b in one
pass): 2,444 passed, same 23 failures, zero new. Frontend: `tsc --noEmit`
clean, `eslint` clean, full `next build` clean (`/income-tax/capital-gains`
compiles at 8.95 kB, down from the old bundle that shipped the whole
compute engine to the browser). Manual dev-server verification via
Playwright (same synthetic-session technique as R2.10, since this sandbox
has no live Supabase project): the rewritten page mounts cleanly, the
calculator's debounced compute call fires against the real backend
(observed failing with a real `503 SUPABASE_URL not set` in this sandbox,
surfaced through the new error banner rather than crashing), and zero
uncaught client-side exceptions occur throughout.

**Next:** R3.1 is now fully closed. Remaining Tier 3 items per the user's
priority — R3.2 (cross-client compliance cockpit), R3.13 (the remaining
frontend pages that compute-and-persist independently of the backend), or
R2.6's standing production-drift reconciliation.

## Milestone R3.13 scoping — R3.2 and R3.13 sized before full delivery

**Goal:** per the user's decision, scope R3.2 and R3.13 in detail before committing
to full delivery of either — R3.1's re-audit had already shown that roadmap
text can undersell (or, in R3.1b's case, mis-scope entirely) what a Tier 3
item actually requires.

**Findings:**
- **R3.13's three instances are not uniform risk.** The advance-tax
  Section 234C calculator turned out to be an actual formula bug (see
  R3.13a below), not just unmigrated logic. The compliance-calendar item
  (`lib/data/compliance.ts`) is a genuine three-way data-model
  consolidation — a backend equivalent already exists (`POST
  /api/compliance/seed`) but writes to a *different* table
  (`compliance_tasks`) than the frontend's `compliance_calendar` (zero
  backend readers), and a third system (`compliance_records`) also exists;
  this needs a canonical-table decision before it can be migrated cleanly.
  The payroll CSV-export item was checked byte-for-byte against the
  backend's canonical PF/ESI logic and found to already match exactly —
  lowest risk, arguably not worth a dedicated pass.
- **R3.2's backend aggregation half is smaller than the roadmap assumed.**
  `compliance_obligation_service.py`'s `generate_due`/`dashboard`/`calendar`
  already loop across all of a firm's clients when `client_id` is omitted
  — real, working cross-client aggregation exists today for the
  generic due-date/status layer. What's still genuinely large: new
  batch-aware "generate real GSTR-1/3B/TDS/MCA records" and
  "mark-filed+ARN-capture" endpoints across N clients (the per-client
  workspaces — `gst_workspace.py`/`tds_workspace.py`/`mca_workspace.py` —
  all currently require a single mandatory `client_id`), a new firm-wide
  cockpit UI, and the same compliance-data-model consolidation R3.13 needs.
  Re-split estimate: backend batch endpoints M/L, cockpit UI L, data-model
  decision blocking both.

**Decision (with the user):** fix the 234C bug first (R3.13a) as the
smallest, highest-value, most isolated finding — a live correctness defect
in a CA-facing calculator, not just an architecture cleanup. The
compliance-data-model consolidation (blocking the rest of R3.13 and all of
R3.2) remains open, tracked under R3.13's roadmap entry.

## Milestone R3.13a — Section 234C advance-tax interest engine (DELIVERED)

**Goal:** `apps/web/app/income-tax/advance-tax/page.tsx`'s
`compute234CInterest()` was not merely unmigrated frontend logic (the
original framing) but a genuine formula bug: it computed interest as
`shortfall × 1% × ceil(days-late / 30)` — the Section 234B ("interest for
default") shape — instead of Section 234C's actual rule, a FIXED period per
instalment (3 months for instalments 1–3, 1 month for instalment 4)
regardless of how late the payment actually was. It also had no equivalent
of Section 234C(1)'s 12%/36% trigger tolerance for instalments 1 and 2, so
a CA who cleared that tolerance (e.g. paid exactly 12% by 15 Jun) would
still see the old code charge interest they don't legally owe. The backend
had no Section 234C capability at all.

**What shipped:**
- **New `domain/income_tax/advance_tax_interest_engine.py`** —
  `INSTALLMENT_RULES` encodes Section 208's 15/45/75/100% cumulative
  schedule together with Section 234C(1)'s 12/36/75/100% trigger
  thresholds and 3/3/3/1-month fixed interest periods; `compute_234c_interest`
  computes, per instalment, the cumulative amount actually paid *as of that
  instalment's own due date* (a payment recorded late against an earlier
  instalment's slot still correctly counts toward a later instalment's
  cumulative, since by then it has genuinely been paid), whether the
  trigger tolerance was breached, the shortfall, and the interest. Treats
  Section 234C's numeric structure as settled statutory text (like
  111A/112A were in R3.1b) rather than an annually-revised rate table —
  no "pending verification" flag needed. Documented, not attempted:
  Section 234C's proviso exempting shortfall caused by unforeseeable income
  (capital gains, lottery winnings, certain dividends), since the existing
  data model has no per-income-type breakdown to evaluate it.
- **New endpoints** (`routers/income_tax.py`): `POST /advance-tax/compute`
  (stateless), `GET /advance-tax` (firm+client+FY scoped), `POST
  /advance-tax` (persists the recorded payment facts — paid amount/date/
  challan — with `due_date`/`required_percent` always derived server-side
  from the FY's Section 208 schedule; the request model has no field for
  either, so a caller cannot supply and have stored a value the schedule
  itself didn't dictate; interest itself is never persisted, since it's
  derived, not a fact).
- **`advance_tax_payments` RLS hardened** (migration 165) — the same
  `FOR ALL`/firm-id-only gap R3.0/R3.1b fixed elsewhere: any authenticated
  firm staff member could directly write a row with a self-reported
  `paid_amount_paise`/`due_date`/`required_percent`. This table also
  predates migration 084's assignment-scoped RLS sweep, so the real-Postgres
  proof test uses a Partner-role fixture for the same documented reason as
  R3.1b's capital-gains proof.
- **Frontend rewrite:** `compute234CInterest()` removed entirely; the page
  now calls the compute endpoint with the same 400ms-debounce pattern as
  the capital-gains calculator, and renders the due date/required amount/
  shortfall/interest the backend returns rather than deriving any of it
  client-side. Also removed a dead, zero-caller raw-Supabase reader
  (`getAdvanceTaxPayments` in `lib/data/income-tax.ts`) found during the
  rewrite, replaced with the new backend-calling equivalent.

**Verified:** 19 new backend tests (11 in
`test_advance_tax_interest_engine.py` — including hand-worked cases for
the trigger tolerance itself, the fixed-period-regardless-of-actual-delay
behavior that was the core bug, and the late-payment-cascades-to-later-
instalments cumulative logic; 8 in `test_r3_13a_advance_tax_endpoints.py`
proving the save endpoint's request model cannot accept a caller-supplied
`due_date`/`required_percent`); 5 in `test_r3_13a_advance_tax_rls_pg.py`
against real Postgres 16. Full mock-mode suite: 2,421 passed, same 23
pre-existing unrelated failures, 85 skipped (real-Postgres tests skip
without `HARNESS_PG`). Combined with `HARNESS_PG` enabled (every
real-Postgres proof across the whole repo in one pass, including all 41
`-k pg` tests and this milestone's 5): 2,463 passed, same 23 failures, 43
skipped, zero new. `tsc --noEmit` clean,
`eslint` clean, full `next build` clean (`/income-tax/advance-tax`
compiles at 7.75 kB). Manual dev-server verification via Playwright (same
synthetic-session technique as R2.10/R3.1b): the rewritten page mounts
cleanly, the debounced compute call fires against the real backend
(observed failing with a real `503 SUPABASE_URL not set` in this sandbox,
surfaced through the existing error banner), and zero uncaught client-side
exceptions occur throughout.

**Next:** the compliance-data-model consolidation (three parallel systems
— `compliance_tasks`/`compliance_calendar`/`compliance_records` — blocking
the rest of R3.13 and all of R3.2) remains the standing decision point;
R2.6's production-drift reconciliation remains blocked on production
credentials this session does not have.

## Final Engineering Completion & Production Readiness Mission — fresh Tier 3 re-scope

**Goal:** per a new mission directive, complete the remaining Tier 3 engineering
work to genuine production-readiness (excluding R3.2's Compliance Cockpit and
R3.4's WhatsApp integration, both explicitly deferred as separate future
product initiatives, not engineering-foundation work). Before implementing,
re-scoped every remaining item against current code — not the original
roadmap text — via 7 parallel, independent investigations. Several findings
substantially changed the priority order.

**Findings, by item:**

1. **R3.3 (orphaned routes).** Confirmed ~46 routes reachable only by typing
   the URL. Most are harmless (real features just missing a nav link, or
   already-retired 5-line stubs safe to delete). Two are not: `/accounting/
   invoices` and `/accounting/fixed-assets` are active data-integrity hazards
   — see the dedicated milestone below, delivered in this pass.
2. **R3.9 (unused-table audit).** 53 of ~226 real tables have zero backend
   Python reader (matching the roadmap's "~57" estimate). 34 are truly dead
   schema (safe to ignore). 18 have unmediated frontend-direct WRITES — the
   same defect class fixed for payroll (R2.10), `client_portal_users` (R3.0),
   `capital_gains` (R3.1b), and `advance_tax_payments` (R3.13a) — spanning 7
   financial-amount tables (including the `sales_invoices`/`invoice_lines`
   pair R3.3 also flagged), 5 compliance/statutory tables (including
   `compliance_calendar`, tied to the compliance consolidation below), 3
   general-metadata tables (`client_health_scores` is the worst: it computes
   real weighted health-score logic in the browser before writing, not just
   an unmediated write), and 3 lower-urgency UI-state tables. Tracked as a
   follow-up batch, not all fixed in this pass — see Remaining Limitations.
3. **Compliance data-model consolidation** (blocking R3.13's remainder and
   R3.2). Investigated all three systems' schemas, callers, and test
   coverage. Clear answer: `compliance_records` (+
   `compliance_obligation_service.py`/`compliance_ops.py`) is the correct
   canonical system — richest status machine, the only cross-client
   aggregation engine, ~30 dedicated tests, the only one covered by the
   newer RLS-hardening pass, and the frontend API client already has a
   comment calling it canonical. `compliance_tasks` and `compliance_calendar`
   have no capability it lacks. Three gaps must close before the losers can
   be retired: a no-engagement seeding fallback, reconciling
   `health-score-compute.ts`'s client-side formula against the backend's, and
   a `UNIQUE(client_id, obligation_type, period_start)` constraint. Not yet
   implemented — tracked as a follow-up.
4. **R3.5 (performance).** Confirmed a systemic unbounded-fetch-then-
   aggregate-in-Python pattern, worst in `analytics.py`'s dashboard/report
   endpoints and the compliance-calendar full-firm fetch+sort — real at
   300-500 clients, not a distant concern. Separately, `core/auth.py`'s
   `get_current_user()` does 2-3 serialized DB round-trips on every single
   protected request with zero caching — a real latency/DB-load cost today,
   compounding with concurrency well before any row-count wall. Indexes are
   mostly present from prior hardening passes; a few composite gaps remain.
   Tracked as a follow-up, not yet implemented.
5. **R3.6 (UX consistency).** Both a loading-skeleton system and an empty/
   error-state system (`EmptyState`/`ErrorState`/`AsyncBoundary`, wired into
   `DataTable`) already exist and are well-designed — this is a ~20-25%
   adoption gap, not a design-system build. The shared client-context
   (`ClientNavContext`) covers only the `/clients/[id]/*` workspace; 30 other
   global tool pages (capital-gains, advance-tax, GST, TDS, invoices,
   payroll, etc.) each roll their own independent client-selector state —
   real, separate, larger scope. Tracked as a follow-up.
6. **R3.8 (year-end status-transition duplication).** More serious than the
   original framing: neither `year_end.py`'s nor `year_end_reviews.py`'s
   endpoints are reachable from the live frontend at all —
   `lib/api/yearEnd.ts` calls a third, different URL scheme matching
   neither router. The year-end review workflow is non-functional in
   production today, not just architecturally duplicated. Tracked as a
   follow-up (needs a merge of the two implementations' distinct
   capabilities — one has the FY-lock side effect, the other has the richer
   per-step audit/revision-request trail — plus fixing the frontend's paths).
7. **R3.11 (debit_notes compensation).** Confirmed the header/lines
   insert gap still exists exactly as described, with a direct, ready-to-
   mirror precedent (`post_journal_atomic`/`settle_receipt_atomic`'s atomic-
   RPC pattern). Tracked as a follow-up.
8. **R3.10 (80CCD(2) + 206AA/206AB).** 80CCD(2) is cleanly implementable
   following the existing per-section deduction-dataclass pattern, but needs
   a new employer-type input and must be gated *outside* the new-regime
   Chapter VI-A block (unlike the rest of Chapter VI-A, it survives both
   regimes). 206AA is genuinely duplicated in two files, AND — the more
   serious finding — its PAN-missing 20% floor is only ever surfaced as a
   validation *warning*; the actual computed `tds_deducted_paise` never
   applies it, a live compliance gap. 206AB is not actually duplicated (the
   roadmap was wrong on that detail) and has no live enforcement either;
   migrating it needs new `is_non_filer` domain modeling that doesn't exist
   in the schema at all, and its rate is genuinely unverifiable from this
   repo pending Finance Act 2025 confirmation. Tracked as a follow-up.
9. **R2.11.1 (bank re-import).** Confirmed this cannot be safely automated:
   the dedupe hash includes amounts, so a corrected re-upload already
   imports as new rows (mechanically works) — but old, wrong rows are never
   superseded, and the bug was conditional on Dr/Cr suffix casing, so a
   blanket `created_at` cutoff would over-flag rows that were never wrong.
   Genuinely needs a manual audit/product decision first, exactly as
   originally scoped. Not implemented — documented as a standing limitation.
10. **R3.12 (PT slabs), R2.6 (production drift), R3.7 (closing journal).**
    Unchanged from prior scoping: R3.12 needs external statutory
    verification this repository cannot provide; R2.6 needs production
    database credentials this session does not have; R3.7 needs a business/
    accounting decision (auto-post timing, reserves sub-account) that must
    not be made unilaterally. All three remain documented, not guessed at.

**Next:** execute the actionable items in priority order — starting with
R3.3's dangerous-duplicate fix (below), then R3.8 (broken-in-production
workflow), R3.9's highest-risk unmediated-write tables, R3.11, R3.10,
the compliance consolidation, R3.5, and R3.6, in roughly that order of
severity — followed by a fresh, assumption-free production-readiness
review and the mission's final deliverables.

## Milestone R3.3 (critical half) — neutralize dangerous orphaned duplicate pages (DELIVERED)

**Goal:** two of the ~46 orphaned routes found by the fresh re-scope above
were not merely unlinked — they were live, fully-functional pages a user
could reach by typing the URL, silently corrupting or losing real financial
data if they did.

**What shipped:**
- **`apps/web/app/accounting/invoices/page.tsx`** wrote directly to a
  `sales_invoices` table via the browser's raw Supabase client — including a
  code comment with a literal `CREATE TABLE IF NOT EXISTS sales_invoices...`
  snippet instructing the user to run it manually, a clear tell this was
  abandoned pre-consolidation scaffolding. The real, linked invoicing flow
  (`clients/[id]/sales/page.tsx` → `routers/sales_invoices.py`) writes a
  completely different table, `client_sales_invoices`, with RBAC, numbering,
  period-lock validation, and audit logging. Any invoice entered through the
  orphaned page was invisible to every report, GST return, and dashboard in
  the app. (Its companion line-item write into `invoice_lines` already fails
  outright today — migration 139 dropped that table years ago as verified
  dead/empty schema, unrelated to this discovery — so only the orphaned
  header row actually persisted.)
- **`apps/web/app/accounting/fixed-assets/page.tsx`** wrote to the *same*
  `fixed_assets` table the real, linked page (`clients/[id]/fixed-assets/
  page.tsx` → `routers/fixed_assets.py`) uses, including its own independent
  client-side depreciation calculation — but bypassed the backend's
  depreciation/disposal logic entirely, so rows it inserted never got a
  `journal_entry_id`, silently breaking depreciation/GL tie-out for any
  asset entered that way.
- Both pages replaced with the project's existing retired-duplicate redirect
  stub (`MovedToClientWorkspace`, the same component already used for the 8
  previously-retired journal/ledger/trial-balance/bank-* pages) — zero data
  access, points the user at the real client-workspace equivalent. Removed
  their cards from the `/accounting` admin hub's list (which had described
  them as if they were legitimate standalone registers).
- **Migration 166** hardens RLS on `sales_invoices` and `fixed_assets` the
  same way as every prior R2.10/R3.0/R3.1b/R3.13a fix — `REVOKE INSERT,
  UPDATE, DELETE ... FROM authenticated`, SELECT-only policy — so the
  underlying tables can no longer be written outside the backend even via a
  direct REST call, not just via the now-removed frontend page.

**Not done — needs a human with production access:** this session cannot
query production data. Before (or immediately after) this ships, someone
with production database access should check `sales_invoices` for any
non-test rows (a real user's stranded invoice, needing manual migration
into `client_sales_invoices`) and `fixed_assets` for rows with a NULL
`journal_entry_id` (an asset whose depreciation never posted to the GL,
needing manual journal correction). This mirrors R2.6's existing "needs
production access" treatment — flagged clearly, not guessed at or skipped
silently.

**Verified:** 5 new tests (`test_r3_3_legacy_invoice_fixed_asset_rls_pg.py`)
against real Postgres 16 — SELECT still works for the owning firm,
INSERT/UPDATE/DELETE all denied, service_role unaffected. Full mock-mode
suite: 2,421 passed, same 23 pre-existing unrelated failures (90 skipped, up
from 85 — the 5 new real-Postgres-only tests correctly skip without
`HARNESS_PG`). `tsc --noEmit` clean, `eslint` clean, full `next build`
clean — both retired pages now compile to 1.13 kB, matching every other
already-retired stub (down from the original pages' 799 and 756 lines of
now-deleted client-side business logic and raw-Supabase calls).

**Next:** the remaining ~44 lower-risk orphaned routes (link-or-delete, no
data hazard) are a follow-up, not attempted in this pass — proceeding to
R3.8's broken-in-production year-end workflow next.

## Milestone R3.8 — fix the non-functional year-end review workflow (DELIVERED)

**Goal:** the original roadmap framing ("two competing implementations, both
work today, pick one") undersold the item — the fresh Tier 3 re-scope found
that neither implementation was actually reachable from the frontend at all,
so real users could not progress a year-end engagement through review.

**Root cause:** `apps/web/lib/api/yearEnd.ts`'s `review.*` functions called
`/api/year-end/engagements/{id}/review/...` (singular "review", and
`/review/submit` rather than `/review/submit-for-review`). The real router,
`routers/year_end_reviews.py`, registered its routes as
`/api/year-end/{id}/reviews/...` — no `/engagements/` path segment at all,
unlike `year_end.py` and every other year-end sub-resource router
(checklist/adjustments/statements/notes/exports), which all use
`/engagements/{id}/...`. Neither side matched the other. Every button on
the review page (Submit for Review, Approve, Request Revision, Final
Approve & Lock) 404'd.

**What shipped:**
- `year_end_reviews.py`'s four `POST` routes gained the missing
  `/engagements/` segment, matching every other year-end router's own
  convention — a real backend inconsistency fixed at the source, not just
  papered over in the frontend.
- New `GET /engagements/{engagement_id}/reviews` endpoint — the review
  page's step-timeline (`prepared`/`reviewed`/`approved`, each with the
  completing user's resolved name/role) and full audit history, built from
  the engagement's own per-step actor/timestamp columns and the
  `year_end_reviews` audit table (`_record_review_event`), resolving
  `auth_user_id` → name/role via a `users` lookup. This endpoint never
  existed before — the frontend was calling a route with no backend
  implementation whatsoever, not just a wrong path.
- **New `services/year_end_workflow_service.py`** — extracts the one
  behavior that genuinely must not diverge between the two routers
  (`year_end.py`'s auto-lock-the-financial-year-on-completion side effect)
  into a shared function, wired into both `year_end.py`'s status endpoint
  (unchanged behavior, now delegating) and `year_end_reviews.py`'s
  `final_approve` (previously missing it entirely — since
  `year_end.py`'s own endpoint was never reachable either, this side effect
  had never actually fired for a real review-workflow completion in
  production). The two routers' genuinely different capabilities (a
  generic transition vs. a richer 4-step audit/revision-request workflow)
  are deliberately left separate — a real difference, not accidental
  duplication, per the re-scope's finding.
- Frontend `yearEnd.ts` corrected to call the fixed paths.

**Verified:** 7 new tests (`test_r3_8_year_end_review_workflow.py`) proving
the corrected paths are reachable, `final_approve` locks the financial year
(the behavior only the unreachable endpoint had before), and the new GET
endpoint returns correctly-built steps/history including resolved actor
names and fixed from/to status pairs. All 11 pre-existing year-end tests
(including `test_year_lock_management.py`'s FY-lock integration test)
still pass unchanged. Full mock-mode suite: 2,428 passed, same 23
pre-existing unrelated failures. `tsc --noEmit` clean, `eslint` clean.
Manual dev-server verification via Playwright: navigated to the review
page and confirmed the browser's network request now hits
`/api/year-end/engagements/_placeholder/reviews` (the corrected path) and
receives a real `503 SUPABASE_URL not set` *from inside the route
handler* — proof the route now resolves at all (a path mismatch 404s
before reaching any handler code; this sandbox has no live Supabase
project to complete the request past that point).

**Next:** R3.11 (debit_notes header/lines compensation) — small, well-
scoped, with a direct precedent to mirror.


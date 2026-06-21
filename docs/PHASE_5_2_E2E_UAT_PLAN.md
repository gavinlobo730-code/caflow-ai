# Phase 5.2 — End-to-End Testing & UAT Preparation (Kickoff Plan)

**Predecessor:** Phase 5.1A–5.1C security remediation (merged `b9f6394`) — see
`PHASE_5_1_SECURITY_REMEDIATION_REPORT.md`.
**Goal:** Prove the platform works end-to-end for real CA workflows, prepare a
UAT program, and validate the `USE_USER_JWT` RLS cutover in staging.
**Constraint carried from Phase 5:** no new feature development — this is
testing, validation, hardening, and bug-fixing only.

---

## Workstreams

### WS-1 — End-to-End business-cycle tests (headless-feasible)
Today's `1551`-test suite is strong at unit/integration level but is mostly
per-endpoint. E2E here means **full business cycles** exercised through the API
in sequence, asserting cross-module state (ledgers, AR/AP, GST/TDS outputs).

Candidate cycles (each becomes one E2E test module):
1. **Sales cycle** — customer → invoice (draft) → issue (journal posted) →
   receipt + allocation → AR outstanding reconciles → credit note → AR adjusts.
2. **Purchase cycle** — vendor → bill (draft) → receive (journal + TDS payable) →
   payment → AP outstanding reconciles → cancel path.
3. **GST preparation** — invoices/bills for a period → GSTR-1 / GSTR-3B drafts →
   figures reconcile to the ledger. *(CA REVIEW REQUIRED — never auto-filed.)*
4. **TDS** — vendor bills with TDS → 24Q/26Q draft → challan → reconciles.
5. **Online payments** — invoice → payment link → mock provider webhook
   (`capturing` → `paid`) → receipt auto-created → AR closes.
6. **Compliance & year-end** — obligations roll-forward, year-end close.

Each cycle asserts the `{success, data, error}` envelope and integer-paise
arithmetic, and includes a **negative cross-firm** leg (reusing the 5.1 pattern)
so isolation stays regression-covered at the cycle level.

### WS-2 — UAT preparation (headless-feasible)
- UAT scenario catalogue mapped to CA personas (Partner, Manager, Article).
- Acceptance criteria + seed/test-data fixtures for a demo firm.
- A UAT runbook (steps, expected results, sign-off sheet).

### WS-3 — `USE_USER_JWT` staging validation (needs staging env — runbook below)
The systemic fix for the C1 posture. Code seam is already in place and ships
dark; this workstream flips it on **in staging only** and validates.

### WS-4 — Tenant-isolation hardening sweep — OOS-6 + OOS-7 (headless-feasible)
Per-endpoint RCA of the non-core by-id writes/reads flagged in 5.1, closing the
confirmed-exploitable ones with the same firm-scoping pattern + negative tests.

### WS-5 — Production hardening & bug-fixing (ongoing)
Triage from WS-1/WS-3 runs; performance/index review; error-envelope and
logging consistency.

---

## WS-3 runbook — `USE_USER_JWT` staging validation

**Why staged:** with the flag OFF, `get_supabase()` returns the service-role
client (RLS bypassed). With it ON **and** a request bearer token present,
`get_supabase()` returns a per-user client (anon key + caller JWT) so Postgres
RLS applies on the backend path too. Privileged/bootstrap paths
(`get_service_supabase()`) and tokenless paths (background jobs, public webhooks)
**always** use service-role — so the cutover is reverted by the flag alone.
(`apps/api/core/supabase_client.py`, `apps/api/core/security_config.py`.)

**Pre-requisites (staging):**
1. `SUPABASE_ANON_KEY` (or `NEXT_PUBLIC_SUPABASE_ANON_KEY`) **must be set** in the
   API environment — `get_user_supabase()` raises without it.
2. RLS enabled with PERMISSIVE policies + `GRANT`s for the `authenticated` role on
   every user-facing table (validated on the live DB during 5.1B — re-confirm in
   staging via `get_advisors` before flipping).
3. Request middleware is populating the per-request token
   (`set_request_token`) from the `Authorization` header.

**Procedure:**
1. Deploy current `main` to staging with `USE_USER_JWT=false`; run the WS-1 E2E
   suite as the baseline (all green).
2. Set `USE_USER_JWT=true` in staging. Redeploy.
3. **Positive:** as a Partner and as a Manager of Firm A, run every WS-1 cycle —
   all legitimate same-firm flows must still pass (no new 403/empty-result
   regressions).
4. **Negative (the point of the cutover):** as Firm A, attempt by-id reads/writes
   against Firm B ids across the OOS-2/-4/-5 endpoints — must be denied **at the
   DB layer** (RLS), independent of the app-layer scope.
5. **Tokenless paths:** trigger a background job and a payments webhook — must
   still succeed (they fall back to service-role).
6. **MFA (optional, same milestone):** if validating `REQUIRE_MFA`, confirm aal2
   enforcement for `MFA_REQUIRED_ROLES` (default `Partner`).
7. Soak; monitor logs for RLS-denied errors on legitimate flows. Roll back by
   setting `USE_USER_JWT=false` (no redeploy of code required).

**Exit criteria:** WS-1 green under the flag, cross-firm denied at the DB layer,
tokenless paths unaffected, zero RLS-denials on legitimate traffic during soak.

---

## Sequencing & headless feasibility

| WS | Can run headlessly here? | Start |
|----|--------------------------|-------|
| WS-1 E2E cycles | ✅ yes (API-level, mock DB / test harness) | first |
| WS-2 UAT prep | ✅ yes (docs + fixtures) | parallel |
| WS-4 OOS-6/7 sweep | ✅ yes | parallel |
| WS-3 USE_USER_JWT | ⚠️ needs staging env + anon key | runbook ready; execute in staging |
| WS-5 hardening | ongoing | as issues surface |

**Recommended first step:** build the WS-1 sales-cycle and purchase-cycle E2E
modules (highest coverage value, fully headless), then the WS-4 OOS-6/7 RCA.
WS-3 executes once a staging environment is available.

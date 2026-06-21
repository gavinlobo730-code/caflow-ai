# Phase 5.2 WS-3 — USE_USER_JWT Staging Validation Runbook

**Deliverable 3.** The systemic hardening of the tenant-isolation posture: move
the backend's DB access from the service-role key (bypasses RLS) to a per-user
JWT client (RLS enforced). Ships dark behind a flag; this runbook enables and
validates it **in staging only**.

## Background (verified in code)

- `core/security_config.py` → `use_user_jwt()` reads `USE_USER_JWT` (default **false**).
- `core/supabase_client.py`:
  - `get_supabase()` → when `USE_USER_JWT` is **on AND a request token is present**,
    returns a per-user client (anon key + caller JWT) so Postgres RLS applies;
    otherwise the service-role client.
  - `get_service_supabase()` → **always** service-role (privileged/bootstrap paths,
    background jobs, public webhooks). These are never downgraded by the flag.
- Tokenless paths (schedulers, the payment webhook) carry no request token, so
  they fall back to service-role even with the flag on — by design.
- **Rollback is the flag alone** — no code redeploy needed to revert.

## Pre-requisites (staging)

1. `SUPABASE_ANON_KEY` (or `NEXT_PUBLIC_SUPABASE_ANON_KEY`) **must be set** in the
   API environment — `get_user_supabase()` raises without it.
2. Request middleware populates the per-request token (`set_request_token`) from
   the `Authorization` header.
3. RLS enabled with PERMISSIVE policies + `GRANT`s for the `authenticated` role on
   every user-facing table. Re-confirm with `get_advisors` before flipping
   (write-policy completeness was validated on the live DB during Phase 5.1B).

## Deployment procedure

1. Deploy current `main` to **staging** with `USE_USER_JWT=false`.
2. Load the WS-2 demo dataset (`PHASE_5_2_WS2_UAT_PLAN.md` §2).
3. Run the validation matrix below as the **baseline** — all green.
4. Set `USE_USER_JWT=true` in staging config. Redeploy/restart the API.
5. Re-run the validation matrix (positive + negative + tokenless).

## Rollback procedure

- Set `USE_USER_JWT=false` and restart the API. No code change, no migration.
- Trigger: any legitimate same-firm workflow returns an RLS-denied/empty result,
  or error rate on authenticated DB reads rises after the flip.
- Because the flag is read per request, a config flip + restart fully reverts.

## Validation procedure

For each row of the matrix, run as the named persona (from the demo dataset) and
record Pass/Fail under both flag modes. **Acceptance = identical positive results
under both modes AND every negative case denied at the DB/RLS layer under
`true`.**

## Validation matrix — workflows that must pass under RLS

| # | Workflow | Persona | Expected under USE_USER_JWT=true |
|---|----------|---------|----------------------------------|
| V1 | Create + issue a sales invoice (journal posts) | Executive/Manager (assigned C1) | Succeeds; journal posted |
| V2 | Record a receipt; AR clears | Executive (C1) | Succeeds; invoice paid |
| V3 | Create + receive a purchase bill; AP posts | Manager (C1) | Succeeds |
| V4 | Record a vendor payment | Manager (C1) | Succeeds |
| V5 | Bank import → reconcile → complete | Manager (C1) | Succeeds; ties out |
| V6 | Generate + file a compliance obligation | Executive→Manager (C1) | Succeeds through state machine |
| V7 | Generate a customer statement | Partner/Manager (C1) | Reconciles |
| V8 | Send a payment reminder (overdue) | Manager (C1) | Succeeds |
| V9 | Create + run a recurring template (DRAFT) | Manager (C1) | DRAFT invoices generated |
| V10 | Online payment webhook → receipt | (tokenless/system) | Succeeds via service-role fallback |
| V11 | Portal client lists own invoices/statement/compliance | Portal client (C1) | Sees only own data |
| V12 | Trial Balance / P&L / Balance Sheet read | Executive+ (C1) | Returns figures |
| **N1** | Firm-A user reads/mutates a **Firm-B** invoice/bill/customer/obligation by id | Partner (Firm-A) | **Denied at DB (RLS)** — 404/empty, no rows |
| **N2** | Manager reads a client they're **not assigned** to (C2) | Manager (C1) | **Denied** — RLS returns no rows |
| **N3** | Receipt/payment allocates a **foreign** invoice/bill | Manager (Firm-A) | **Rejected** (422) |
| **N4** | Portal client accesses **another** client's invoice | Portal client (C1) | **Denied** — 404, ownership gate + RLS |
| **N5** | Online payment link for a **foreign** invoice | Partner (Firm-A) | **404** |
| T1 | Scheduler job (reminders/recurring) runs tokenless | system | Succeeds (service-role) |
| T2 | Payment webhook (no Authorization header) | system | Succeeds (service-role) |

> Every positive (V*) and negative (N*) case has an automated analogue in
> `tests/test_e2e_*.py` and the Phase 5.1 security suites; this matrix validates
> them against the **live RLS layer** in staging, which cannot be exercised
> headlessly.

## Exit criteria

- V1–V12 all Pass under `true` (no new RLS-denials on legitimate same-firm flows).
- N1–N5 all denied **at the DB layer** under `true`.
- T1–T2 unaffected (service-role fallback works).
- Soak ≥ 24h with no RLS-denied errors on legitimate authenticated traffic.

On meeting exit criteria, `USE_USER_JWT=true` may be promoted to production as a
config change (no code release). Until then, production stays on the
app-layer-scoping control validated by WS-1.

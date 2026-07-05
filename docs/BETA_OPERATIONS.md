# Beta Operations & Production Hardening Guide

Operational checklist for running the accounting engine in Beta with production-like
data. Covers configuration, security toggles, monitoring, and the known-issues list.

## 1. Required configuration (validated at startup)

The API validates configuration at boot (`core/config_validation.py`) and logs a
single report. Ensure these are set:

| Variable | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | ✅ | Postgres/PostgREST endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Backend DB access (bypasses RLS — **server-only, never ship to the client**) |
| `SUPABASE_ANON_KEY` | ⬜ | Client key |
| `GROQ_API_KEY` | ⬜ | AI document extraction (disabled if unset) |
| `SENTRY_DSN` | ⬜ | Error monitoring (recommended for Beta) |

Watch the boot log for `CONFIG: missing REQUIRED environment variables: …`.

## 2. Security toggles (operator action — not code)

- **Enable leaked-password protection** (audit L11). Supabase Dashboard →
  Authentication → Policies / Password security → enable "Check against HaveIBeenPwned".
  This is a dashboard setting and cannot be set via migration.
- **Confirm MFA (aal2)** is available to platform admins — destructive platform
  actions (firm purge) require it (`require_platform_admin_mfa`).
- **Rotate the service-role key** if it was ever exposed; it bypasses RLS.

## 3. Security posture (already enforced in code — for awareness)

- Tenant isolation: every accounting query is firm-scoped; the service-role key
  bypasses RLS, so the app-layer `firm_id` filter is the primary control, with
  firm-scoped RLS policies on all accounting tables as defense-in-depth.
- SECURITY DEFINER surface is minimal, `search_path`-pinned; `platform_purge_firm`
  is service-role-only with an in-body platform-admin guard.
- Posted journals are immutable (DB triggers); corrections are append-only reversals.
- The advisor still reports (all **intentional**): `platform_admins`/`platform_audit`
  RLS-enabled-no-policy (deny-all by design), and the identity-only RLS-helper
  functions being callable by `authenticated` (required for RLS evaluation).

## 4. Monitoring & operations

- Enable Sentry (`SENTRY_DSN`).
- Scheduler: set `ENABLE_SCHEDULER=true` or configure an external cron to POST
  `/api/scheduler/run`, else compliance reminders / recurring jobs never fire (the
  boot log states which mode is active).
- Audit trail: every mutation logs via `audit_service.log_event`; `audit_logs` are
  append-only (mutation-blocked by trigger). Spot-check that actor id/email are
  populated on financial mutations.

## 5. Pre-Beta verification (run on staging against a real DB)

The core accounting engine is covered by the automated suite, but these need a live DB
(they cannot run in the sandbox CI and are currently unverified there):

- GSTR-1 / GSTR-3B **filing storage & status** endpoints (`test_phase3_gst`).
- MCA company/filing endpoints (`test_phase3_mca`).
- TDS challan/return/certificate endpoints (`test_phase3_tds`).
- Pagination/list endpoints under real data volume (`test_hardening`).

Run a scripted UAT: full customer + vendor cycle, GST period close, year lock,
cross-year reports, and a large-client (10k+ entries) report timing.

## 6. Known issues carried into Beta (non-blocking)

| Ref | Issue | Impact | Workaround |
|---|---|---|---|
| H18 | No receipt/payment *void* document UX | Reversal exists at the journal layer only | Reverse the journal manually |
| H22 | Some frontend lists fetch without pagination | Truncation only past ~1000 rows on FE-direct pages | Backend list endpoints paginate; use those |
| M15/M17/M18 | Money formatter duplication; infinite skeleton on `success:false`; list load-errors render as "no data" | Cosmetic/UX correctness | Being addressed incrementally |
| M2/M3/M10 | Negative-qty / zero-value validators, inactive-master posting guards | Guards added on core paths (invoice/bill/receipt/payment); a few edge documents remain | — |
| Perf | In-memory report projection loads the full ledger per request | Fine for SMB clients; a ceiling for very large ledgers | Paginated fetch prevents truncation; SQL-side aggregation is a post-Beta item |

## 7. Do NOT enable in Beta

Multi-currency (implemented across Phases 1-5 and wired into posting/reports,
but kept OFF by default via `MULTI_CURRENCY_ENABLED` plus firm/client
entitlement gates — leave disabled for Beta), e-invoice/e-way bill,
GST return **submission** to the portal (always CA-review-gated; never auto-submit).

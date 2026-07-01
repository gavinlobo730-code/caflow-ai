# Release — Multi-Currency (Phases 1–5) + accounting/statutory/security hardening & polish

**Date:** 2026-07-01
**Branch → main:** `claude/dazzling-curie-a55bpf`
**Rollup:** promotes all work merged in PR #134 to production.

This release note marks the production promotion of the following, already merged into
`main` and verified. It carries no code change of its own — it exists to record the
release and to trigger a fresh Cloudflare Pages production build of `main`.

## Included
- **Multi-Currency (Capability A) Phases 1–5** — currency master + gating + rate service;
  currency-aware GL + posting kernel; foreign sales/purchase/receipt/payment documents;
  realized + unrealized FX accounting (idempotent period-end revaluation); FX reporting,
  dual-currency statements/aging, foreign-currency bank accounts, and the FX Reports UI.
  Migrations 146–150 (additive). See `docs/architecture/06*-multi-currency-*.md`.
- **Accounting hardening** — correction-document integrity, vendor/AP completeness,
  ledger pagination, journal idempotency, lost-update prevention.
- **Statutory** — GST/TDS reconcile to the ledger; RCM, TDS engine, from-books returns.
- **Security** — closed an anon-executable purge path, cross-tenant reads, `search_path`
  pinning, missing RLS.
- **Product polish** — frontend list pagination, Schedule III on the backend, formatter/UX.

## Guarantees
Additive and feature-gated: Multi-Currency is OFF by default (env + firm + client gates),
so INR-only behaviour is byte-for-byte unchanged. GL always balances in base (INR);
integer paise throughout; historical rates immutable; tenant isolation (RLS) preserved.

## Verification
Backend suite green except pre-existing DB-connectivity integration tests; frontend
`tsc` / `eslint` / `next build` clean; migrations 146–150 applied to the live project
with no new advisors.

# HSN/SAC Master — Maintenance Guide

How the `hsn_master` table is kept current, and why updating it never
disturbs invoices that have already been raised.

> **Architecture note (HSN/SAC redesign):** `hsn_master` is retained
> UNCHANGED but is no longer read by any user-facing endpoint. Caflow does
> not expose a shared HSN/SAC master to users — the invoice-line picker,
> the Product/Service form, and every other user-facing surface now source
> from each firm's own `firm_hsn_library` instead. See
> [`FIRM_HSN_LIBRARY.md`](./FIRM_HSN_LIBRARY.md) for the current
> architecture. This document is kept for historical/internal reference —
> the table and its provenance discipline below still apply if `hsn_master`
> is ever reactivated for internal tooling (e.g. import plausibility
> checks), but nothing in this codebase currently reads it that way.

_Scope: the code/description/rate table that historically powered the
invoice line picker and is now an internal-only implementation detail. It
is a convenience layer only — see "Why historical invoices are safe" below._

---

## What this table is (and is not)

`public.hsn_master` (introduced in migration `036`, expanded in `175`) is the
searchable directory behind the HSN/SAC picker (`GET /api/hsn/search`,
`HsnLookup`). Each row carries:

| Column | Meaning |
|---|---|
| `hsn_code` | HSN chapter/heading or SAC code (primary key) |
| `description` | Official title shown in the picker |
| `gst_rate_pct` | **Pre-fill hint only** — `NULL` when the code spans multiple rates |
| `hsn_type` | `goods` (HSN) or `services` (SAC) |
| `uqc` | Default unit-quantity code |
| `keywords` | Lay synonyms to aid description search |
| `source`, `version` | Provenance of the row (e.g. `cbic_tariff_2025`, `2025-26`) |
| `updated_at` | Last time the row was seeded/corrected |

The returned GST rate is a **hint**, never an input to any tax or journal
computation (CGST Rule 46(g)). The CA always confirms or overrides it.

---

## Official source

- **Goods (HSN):** the Customs Tariff Act, First Schedule (CBIC), which India's
  GST rate schedule is built on.
- **Services (SAC):** the Service Accounting Codes in the Annexure to
  **Notification 11/2017 – Central Tax (Rate)**, derived from the UN CPC.
- **Rates / reclassifications:** CBIC rate notifications and GST Council
  decisions, as published on the CBIC-GST portal.

All of the above are Government of India publications in the **public domain** —
no third-party licence is required to embed them. Record the exact source in the
`source` column of every row so its origin is auditable.

---

## Update frequency

Refresh on these triggers, not on a fixed calendar:

1. **GST Council rate changes / reclassifications** — apply within the
   notification's effective date. These are the changes that matter to users.
2. **Annual tariff revision** — review each financial year (April) and bump the
   `version` string (e.g. `2025-26` → `2026-27`).
3. **Coverage gaps** — when firms repeatedly free-type a code that isn't in the
   master (visible via `hsn_sac_preferences`), add it in the next routine load.

A quarterly glance at CBIC notifications is enough between these triggers.

---

## Versioning strategy

- Every load stamps `source` + `version` on the rows it writes, and `updated_at`
  is set to load time. This makes "which edition is this row from?" answerable
  with a single query and lets a newer load supersede an older one in place.
- Each change ships as a **new numbered migration** (never edit a past one), so
  the history of the master is reproducible on a fresh database. Migration `175`
  is the reference template.
- Loads are **idempotent upserts**: `INSERT … ON CONFLICT (hsn_code) DO UPDATE`.
  Re-running a migration re-asserts the same state; it never duplicates rows.
- The full 8-digit HSN leaf catalogue (~12k codes) is large and better loaded by
  a **versioned data pipeline** into this same table and schema rather than by a
  hand-written migration. The columns above already support that; only the seed
  volume differs.

---

## Applying a future government change

1. Write a new migration `NNN_hsn_master_<change>.sql`.
2. Upsert the affected rows with the new `source`/`version` and `updated_at`:

   ```sql
   INSERT INTO public.hsn_master
       (hsn_code, description, gst_rate_pct, hsn_type, uqc, source, version, keywords)
   VALUES
       ('9954', '…updated title…', NULL, 'services', 'OTH', 'cbic_sac_2026', '2026-27', '…')
   ON CONFLICT (hsn_code) DO UPDATE SET
       description  = EXCLUDED.description,
       gst_rate_pct = EXCLUDED.gst_rate_pct,
       hsn_type     = EXCLUDED.hsn_type,
       uqc          = EXCLUDED.uqc,
       source       = EXCLUDED.source,
       version      = EXCLUDED.version,
       keywords     = EXCLUDED.keywords,
       updated_at   = now();
   ```

3. **Retire, don't delete.** If a code is withdrawn, set `is_active = false` so
   it stops appearing in new searches but the row survives for reference. Never
   `DELETE` a code that firms may have used.
4. Keep chapter- and group-level rows at `gst_rate_pct = NULL`. Only put a
   concrete rate on a specific leaf code when the standard rate is unambiguous;
   when in doubt, leave it `NULL` and let the CA choose.
5. Verify the migration applies cleanly and idempotently against a throwaway
   PostgreSQL before merging (the migration-apply ratchet enforces this in CI).

---

## Why historical invoices are safe

Updating the master **cannot** change a previously raised invoice, because the
master is not wired into stored documents:

- **Invoices snapshot their own values.** A sales-invoice line stores its
  `hsn_sac` as **free text** plus its own description, rate and computed
  amounts. There is **no foreign key** from an invoice line to `hsn_master`.
- **Nothing joins the master to produce financial output.** GSTR-1, the invoice
  PDF and the ledger all read the invoice's own stored fields; the master is
  read **only** by the lookup search endpoint. So editing a title, rate hint or
  keyword changes what the *picker suggests next*, never what an existing
  invoice, return or PDF says.
- **The ledger is immutable regardless.** Posted journals cannot be mutated by a
  master refresh; correctness lives in the posting kernel, not the lookup.

In short: the master is a **forward-looking suggestion source**. Refreshing it
improves future data entry and leaves the historical record exactly as it was
issued and posted.

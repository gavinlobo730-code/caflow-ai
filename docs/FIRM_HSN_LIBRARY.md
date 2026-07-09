# Firm HSN/SAC Library — Architecture

How HSN/SAC classification works across Caflow after the HSN/SAC
architecture redesign. Read this alongside
[`HSN_SAC_MASTER_MAINTENANCE.md`](./HSN_SAC_MASTER_MAINTENANCE.md), which
covers the retained-but-now-internal `hsn_master` table.

---

## The decision

Three earlier review documents (architecture review, official-source
research, and this redesign's own decision gate) converged on the same
model, with one deliberate refinement in this implementation:

- **Caflow does not expose a shared HSN/SAC master to users.** There is no
  Caflow-authored "canonical" code list a CA browses or picks from directly.
- **Every firm owns and curates its own `firm_hsn_library`.** Codes are
  added by manual entry or import, edited, retired (never hard-deleted).
  Products/Services and every invoice line select their HSN/SAC **only**
  from the firm's own library.
- **`public.hsn_master`** (migrations 036 → 178) **is retained unchanged**
  as an internal implementation detail. It is not read by any user-facing
  endpoint in this redesign. It exists for possible future internal
  tooling (e.g. import plausibility checks) — nothing in this codebase
  currently reads it outside its own legacy `GET /api/hsn/search` history,
  which itself now sources from `firm_hsn_library`, not `hsn_master`.

Caflow performs no classification and offers no suggestion of *which* code
is correct for a given good/service — every validator in this system checks
only **structural shape** (digits, non-blank description), never semantic
correctness. That judgement belongs to the CA.

## Why this is not a contradiction of the prior architecture reviews

The prior reviews recommended a vendor-owned, GSTN-mirrored shared master
specifically to avoid the *per-tenant-copy-of-public-data* anti-pattern and
the *cold-start* problem. This redesign accepts those costs as a deliberate,
informed trade-off (Decision A, redesign session) in exchange for a cleaner
liability posture: Caflow asserts no classification content of any kind,
anywhere a user can see it. The costs are mitigated, not eliminated:

- **Cold-start** is addressed by the onboarding import step (below) and by
  the inline "Add to Firm HSN/SAC Library" quick-add modal, which lets a
  code be added without leaving the transaction being drafted.
- **Per-tenant duplication of public codes** is an accepted cost — there is
  no shared backbone to duplicate against, so this is simply how the system
  works now. `hsn_master`'s continued existence means a future decision to
  reintroduce a shared, opt-in suggestion layer would not require a schema
  rebuild — the backbone data is still there, unused.

## Data model

```
firm_hsn_library        Firm-scoped. id, firm_id, hsn_code, description,
                         hsn_type (goods|services), gst_rate_pct (CA-entered
                         hint, nullable), uqc, notes, source (manual|import),
                         is_active, audit columns. Unique (firm_id, hsn_code).

firm_hsn_rate_history    Per-firm-owned, validity-dated rate versions keyed
                         to a firm_hsn_library row (Decision D). CA-entered
                         only — Caflow asserts no authoritative rate. See
                         "Rate history" below.

service_catalogue        Product & Service master (goods + services since
(aka "Products &          migration 180). CLIENT-owned since migration 182
 Services")               ("Client B must never inherit Client A's
                         products") — every row belongs to exactly one
                         client, not the firm as a whole; see "Products &
                         Services are client-owned" below. Name mandatory;
                         hsn_sac must be a code from the FIRM's firm_hsn_library
                         (the library itself stays firm-wide even though the
                         product/service row referencing it is client-owned
                         — app-enforced, no DB FK, see service_catalogue.py's
                         _hsn_in_library). Still explicitly NOT an inventory
                         master: no stock/valuation/quantity/SKU/barcode/
                         warehouse (migration 176's lock stands; see
                         "What was deliberately deferred" below).

client_sales_invoice_lines,   Unchanged. hsn_sac stored as free text,
purchase_bill_lines,          gst_rate_bps as an integer snapshot. No FK to
credit_notes, debit_notes     firm_hsn_library or hsn_master. Editing or
                               retiring a library code can never change a
                               past transaction — the same safety argument
                               hsn_master has always relied on.
```

## Consuming surfaces

- **`GET /api/hsn/search`** (`routers/hsn.py`) — the shared search endpoint
  behind every HSN/SAC picker. Merges the firm's own `hsn_sac_preferences`
  history with `firm_hsn_library` (never `hsn_master`). One endpoint, one
  ranking function (`_rank_library_rows`), reused by `LineItemAutocomplete`,
  `HsnLookup`, and the Product/Service form.
- **`HsnLookup.tsx`** — the shared combobox component used on Sales Invoice
  lines, Purchase Bill lines, Debit Note lines, and the Product/Service
  form's default-HSN field (now at `/clients/[id]/products-services/`, a
  client-workspace page — see "Products & Services are client-owned"
  below). Fixing it once (rather than each call site) is what makes "avoid
  duplicate HSN logic" hold across every module.
- **No free-text escape hatch.** `HsnLookup` used to let a CA type an
  arbitrary code directly onto a line ("Use…"). That has been replaced with
  `FirmHsnLibraryQuickAddModal`: the "+" row now adds the code to the firm's
  library first, then hands it back to the caller exactly like a normal
  pick. Master data is never created directly inside a transaction
  (Decision C).
- **Onboarding** (`app/onboarding/page.tsx`, Step 3) — "Import your HSN/SAC
  library": add codes one at a time, import a list (a Caflow-authored blank
  CSV template — no government content, so there is nothing to redistribute
  or license, per the official-source research), or skip. Reuses the same
  `POST /api/firm-hsn-library/` endpoint the quick-add modal and the library
  management page use — one create path.
- **Settings → Firm HSN/SAC Library** (`/settings/firm-hsn-library`) — full
  CRUD: add, edit, search, retire/restore, filter by type.

## Rate history (Decision D)

`firm_hsn_rate_history` exists so a CA can record that a code's GST rate
changed on a given date (e.g. the 22-Sep-2025 "GST 2.0" rationalization)
without losing the ability to answer "what rate applied on this code on
that date." It is deliberately **not** a tax-determination engine:

- Every row is CA-entered; Caflow ships no seed data and asserts no
  Caflow-authoritative rate for any code.
- `GET /api/firm-hsn-rate-history/resolve` returns a **pre-fill hint only**.
  Nothing calls it automatically; the CA must still confirm the value on
  the product/invoice form, exactly as `gst_rate_pct`/`gst_rate_bps` always
  have been.
- No slab/cess/RCM branching logic. A code whose rate depends on value
  slabs or buyer type gets two rows with a note — Caflow never tries to
  compute which one applies to a given transaction.
- Because the shared master is gone, this history is necessarily per-firm.
  That is an accepted duplication cost, same as the code data itself.

## Products & Services are client-owned (migration 182)

The HSN/SAC workflow alignment (approved product vision) drew a sharp line
between two tenancy models that this codebase previously conflated:

- **Firm HSN/SAC Library** — one per CA workspace, shared across every
  client that firm manages. "Configure once, reuse everywhere."
- **Products & Services** — always client-specific. "Client B must never
  inherit Client A's products." A firm serving a laptop retailer and a
  cement supplier must never show one client's items to the other.

`service_catalogue` was firm-scoped only until migration 182 added a
required `client_id` and the matching RLS (`can_access_client`, mirroring
`hsn_sac_preferences`'s three-policy stack). The management UI moved from a
firm-level Settings page (`/settings/service-catalogue`, now removed) to a
client-workspace page (`/clients/[id]/products-services/`), alongside Sales
and Purchases in `ClientNavContext.tsx`.

`service_catalogue` had no production data at the time of this change
(MVP Phase 1, pre-launch), so the migration clears existing rows rather than
backfilling a client onto them — see migration 182's own comment.

**Future enhancement (not implemented):** invoices should offer a "New
Product/Service" action that opens the Product/Service creation dialog
inline, without leaving the invoice — the same pattern
`FirmHsnLibraryQuickAddModal` already uses for HSN/SAC codes ("open/manage
the library instead of entering arbitrary values"). This keeps master-data
creation in the correct place (the client's own Products & Services list)
while giving a smooth workflow when the CA is drafting a line for an item
that doesn't exist yet. Noted here as a backlog item; not built in this
pass.

## What was deliberately deferred

- **Full inventory** (stock, valuation, quantity-on-hand, SKU, barcode,
  warehouses) remains out of scope. Migration 176's lock on
  `service_catalogue` stands; `CLAUDE.md`'s "MVP Phase 1 only" scope
  restriction was not overridden. `service_catalogue`/"Products & Services"
  now covers goods as billing presets (name, HSN, price, unit, category)
  without becoming an items/inventory master.
- **Quotations, Delivery Challans** do not exist as modules yet — Phase 5's
  "reuse across modules" applies only to the modules that exist today
  (Sales Invoices, Purchase Bills, Credit Notes, Debit Notes).
- **A validity-dated, Caflow-maintained rate table** (the ideal end-state
  from the first architecture review) was not built — Decision D chose the
  per-firm-owned mechanism instead, to avoid the liability tension of
  Caflow asserting a shared, authoritative rate value.

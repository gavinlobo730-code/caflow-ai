# Sales Invoice Workspace — Density & Loading-Fidelity Audit

**Date:** 2026-07-06 · **Status:** audit only — no code changed · **Scope:** why the implemented editor reads as sparse/empty compared to the Blueprint's dense QuickBooks-inspired workspace.

This audit compares the shipped Create/Edit editor and Invoice Hub against `docs/SALES_INVOICE_UX_BLUEPRINT.md` Parts 1 and 3 (spec + wireframes). It does not revisit locked architecture decisions and proposes no code — only a categorized punch list for a follow-up pass.

---

## Bottom line

The **loaded, populated editor is structurally close to the Blueprint** (two-column body, sticky summary rail, dense line grid, party-block grid). The "large empty areas / sparse workspace" perception comes from three systemic, mostly-accidental gaps that sit **around** that content, not inside it:

1. The loading state **collapses the two-column shell** to a single unstyled column — no toolbar, no summary rail — so the workspace looks empty for every navigation into Create/Edit (and the Hub drawer has the same pattern).
2. `InvoiceWorkspaceLayout` is the **only top-level page shell in the whole client workspace with zero padding** — every sibling page wraps its content in `px-6 pt-4/5 pb-6`; the invoice editor doesn't, so content sits flush against the viewport edges.
3. A few Blueprint-specified elements were **quietly dropped** during Batch 3 (a `Unit` column, the edit-mode "Activity mini") without being logged as deferred anywhere, so the page is thinner than spec even once padding/loading are fixed.

None of this touches accounting, posting, or the API surface. All of it is CSS/skeleton/UI-only.

---

## What was compared

- `docs/SALES_INVOICE_UX_BLUEPRINT.md` §1.1–§1.12 (spec) and Part 3 (wireframes: desktop/tablet/mobile Create, Edit, Hub).
- `apps/web/components/invoices/InvoiceWorkspaceLayout.tsx` (the shell).
- `apps/web/components/invoices/InvoiceEditor.tsx` (the loaded editor).
- `apps/web/app/clients/[id]/sales/invoices/new/page.tsx` and `.../[invoiceId]/edit/{page,_page}.tsx` (route wrappers + their loading/empty branches).
- `apps/web/components/invoices/InvoiceViewDrawer.tsx` (Hub loading branch).
- `apps/web/components/ui/skeleton.tsx`, `states.tsx` (the shared loading/empty primitives).
- `apps/web/app/clients/[id]/layout.tsx`, `ClientWorkspaceShell.tsx`, `ClientHeader.tsx` (the ambient chrome the editor renders inside).
- `apps/web/app/clients/[id]/sales/page.tsx` (the sibling page used as the "normal" padding/shell baseline).
- `apps/web/lib/invoices/gst.ts` (`InvoiceLine` shape) and `components/lookups/HsnLookup.tsx` (`HsnPick` shape).

---

## Findings

### F1 — Loading state discards the two-column shell entirely
**Blueprint:** §1.12 — *"Loading: page → skeleton for header + grid rows; summary → shimmer."* The loading state is specified to **approximate the final two-column silhouette** (a shaped grid skeleton on the left, a shimmering summary rail on the right), not to degrade to something else.

**Implemented:** `new/page.tsx:56-77` and `edit/_page.tsx:61-73` render, while `ctx` is `null`:
```tsx
<InvoiceWorkspaceLayout breadcrumbs={...} title={...} statusPill={...}>
  {error ? <ErrorState .../> : !ctx ? <FormSkeleton fields={6} /> : <EmptyState .../>}
</InvoiceWorkspaceLayout>
```
Neither `toolbar` nor `summary` props are passed. Look at `InvoiceWorkspaceLayout.tsx:72-93`: both the sticky toolbar and the summary `<aside>` are conditionally rendered (`{toolbar && …}`, `{summary && …}`) — so when they're `undefined`, **the entire right rail and the action bar disappear**, and the body flex row (`InvoiceWorkspaceLayout.tsx:79-86`) collapses to one full-width column holding nothing but the raw skeleton.

**Effect:** every time a user opens Create or Edit, for as long as `loadInvoiceEditorContext`/`loadInvoiceDetail` takes, they see a bare page with no action bar and no summary card — a structurally different, emptier layout than what appears a moment later. On a slow connection this is the *first impression* of the "professional" editor.

**Classification: Accidental.** Nothing in the Blueprint calls for this collapse; §1.12 explicitly asks for the opposite (a shaped, two-column-preserving skeleton).

---

### F2 — Skeletons are generic, unshaped, and uncarded (repeated in 3 places)
**Blueprint:** the skeleton is meant to mirror the real layout ("no jump when data arrives" — this principle is even stated verbatim in the shared primitives' own doc-comment at `components/ui/skeleton.tsx:11-14`).

**Implemented:**
- Create/Edit loading (`FormSkeleton`, `skeleton.tsx:177-188`): six bare `label + h-9 bar` rows in a plain `space-y-4` div — **no white card, no border, no grid** — while every real section of the loaded editor is a bordered white card (`InvoiceEditor.tsx:447`, `530`, `610`: `bg-white rounded-xl border border-[#F1F5F9] p-4`).
- Hub drawer loading (`InvoiceViewDrawer.tsx:191-194`): six bare `h-10 bg-[#F8FAFC] animate-pulse` divs, again with no card framing and no resemblance to the Hub's actual header/status-badges/action-bar/line-grid/compliance structure.

**Effect:** the loading placeholder looks like a handful of thin grey bars floating on the page background — visually the definition of "sparse" — right before the real, densely-carded content appears. The same unshaped pattern is used in three independent places (Create, Edit, Hub), so this isn't a one-off oversight, it's a systemic habit.

**Classification: Accidental**, and systemic — `FormSkeleton` is a generic primitive (correctly reused elsewhere for actual small forms/modals); it was reached for here as a placeholder rather than a purpose-built, content-shaped skeleton, and nobody came back to replace it once the real editor (Batch 3) and Hub (Batch 4) were built.

---

### F3 — `InvoiceWorkspaceLayout` is the only page shell with no padding
**Blueprint:** doesn't specify exact padding, but the whole client workspace has one established convention.

**Implemented:** `InvoiceWorkspaceLayout.tsx:47`:
```tsx
<div className="max-w-screen-2xl mx-auto pb-24 lg:pb-6">
```
No `px-*`, no `pt-*`. Compare the sibling Sales list page, `app/clients/[id]/sales/page.tsx:218`:
```tsx
<div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
```
— which then nests `<div className="space-y-4 max-w-screen-2xl">` five times for its tabs (lines 328/808/1256/2186/2803/3275). Every one of those tab bodies gets its `px-6 pt-4 pb-6` gutter for free from this outer wrapper. `ClientWorkspaceShell`'s `<main>` (`ClientWorkspaceShell.tsx:21`) adds no padding of its own either — so `InvoiceWorkspaceLayout` is genuinely the **only** top-level route content in the client workspace that renders with zero horizontal/top gutter.

**Effect:** the breadcrumb touches the very top edge of the content area, and the white-carded sections (and, worse, the unframed loading skeleton from F2) touch the left/right edges of the browser viewport directly — no breathing room, inconsistent with literally every other screen in the product. This alone makes an otherwise-reasonably-dense page *read* as unpolished/edge-to-edge.

**Classification: Accidental regression from an established convention** — `InvoiceWorkspaceLayout` was authored as a fresh standalone shell in Batch 2 rather than adapted from the existing content-wrapper pattern, and the omission was never caught because no visual diff against a sibling page was part of any batch's test plan.

---

### F4 — `Unit` column/field silently dropped from the line grid
**Blueprint:** §1.6 and every wireframe in Part 3 list `Qty · Unit · Rate` as three distinct columns (e.g. §3.1: `Qty Unit  Rate    GST%`).

**Implemented:** `InvoiceLine` (`lib/invoices/gst.ts:57-63`) has no `unit` field at all:
```ts
export interface InvoiceLine {
  description: string; hsn_sac: string; qty: string; rate: string; gst_rate: number;
}
```
and the grid header (`InvoiceEditor.tsx:544-550`) has no Unit column. Notably the data is *available and thrown away*: `HsnLookup`'s pick payload already carries `uqc` (`components/lookups/HsnLookup.tsx` `HsnPick.uqc`), but the editor's `onPick` handler only reads `gst_rate_bps` (`InvoiceEditor.tsx:569`) and discards `uqc`.

**Effect:** the grid has one fewer column than the wireframe, and it's a column the backend already has data for (`hsn_master.uqc`) — this isn't a deliberate simplification, it's a half-wired feature: the plumbing exists up to the last step.

**Classification: Accidental, undocumented scope-narrowing.** No batch summary (1 through 8) lists "Unit column deferred" — it simply never made it into `InvoiceLine` during Batch 3 and was never revisited.

---

### F5 — Edit-mode "Activity mini" never implemented
**Blueprint:** §1.1 right-column bullet: *"(Edit mode) Activity mini"* in the summary rail.

**Implemented:** the summary panel (`InvoiceEditor.tsx:398-433`) shows Taxable/CGST/SGST/IGST/Round-off/Grand Total/Due date/Outstanding — no activity feed of any kind, in either mode.

**Effect:** minor relative to F1–F3, but it's another line item from the spec's own right-rail wireframe that's simply absent, contributing to the rail (and therefore the page) feeling thinner than designed.

**Classification: Accidental omission**, not documented as deferred in any batch.

---

### F6 — Server-preview "computed on server" shimmer never implemented
**Blueprint:** §1.7: *"Shows a subtle 'computed on server' affordance while a debounce recompute is in flight."*

**Implemented:** totals are computed instantly and entirely client-side (`previewTotals`, `InvoiceEditor.tsx:162`) — there's no server round-trip per keystroke, so there's nothing to debounce or shimmer.

**Classification: Superseded, not a defect.** The Blueprint anticipated a server-roundtrip preview; the shipped design (client-side pure preview, server-authoritative only on save) is a legitimate, arguably better architecture (Batch 1's design-review answer on rounding logic made this trade-off explicitly). No action needed — worth noting in the Blueprint as superseded so it stops looking like an open item.

---

### F7 — Attachments section absent
**Blueprint:** §1.9, wireframes §3.1/§3.2 show an `Attachments [⬆ drag files or browse]` row at the bottom of the editor.

**Implemented:** not present anywhere in `InvoiceEditor.tsx`.

**Classification: Intentional, documented deferral.** Blueprint's own Part 7 schedules this as **Batch 9**, which was never in scope for Batches 1–8 (confirmed across every batch's "Deferred for Batch N" deliverable). Its absence does make the page shorter than the full wireframe, but this is a known, tracked gap — not drift.

---

### F8 — Per-line `GoodsServicesToggle` replaced by grouped-lookup chips
**Blueprint:** §1.6 and the component hierarchy (`docs/SALES_INVOICE_UX_BLUEPRINT.md` line 54) call for a dedicated `<GoodsServicesToggle>` per line that filters `HsnLookup` by `hsn_type` and swaps the field label between "HSN" and "SAC".

**Implemented:** Batch 5 (HSN modernization) instead grouped `HsnLookup`'s own results by Services/Goods with an inline SAC/HSN chip per row, and the grid column is a single hardcoded "HSN/SAC" header with no per-line toggle or `type` filter wired from the row.

**Effect:** the grid has one fewer control/column than the wireframe.

**Classification: Intentional, documented substitution.** Batch 5's own deliverables explicitly describe this grouping-in-the-lookup approach as the chosen mechanism; it satisfies the same user need (distinguish goods vs. services) through fewer controls. This is a legitimate design substitution, not a bug — flagged here only because it's one more contributor to "fewer columns than the wireframe," not because it needs reverting.

---

## Categorization summary

| # | Finding | Category | Blocking for "professional workspace" feel? |
|---|---|---|---|
| F1 | Loading state drops toolbar + summary rail | **Accidental** | Yes — biggest contributor |
| F2 | Generic, uncarded skeletons (3 places) | **Accidental**, systemic | Yes |
| F3 | Zero page padding, unlike every sibling page | **Accidental** regression | Yes |
| F4 | `Unit` column/field missing | **Accidental**, undocumented | Minor |
| F5 | Edit-mode Activity mini missing | **Accidental**, undocumented | Minor |
| F6 | Server-preview shimmer missing | **Superseded** (design changed for the better) | No |
| F7 | Attachments absent | **Intentional**, documented (Batch 9) | No |
| F8 | GoodsServicesToggle → grouped-lookup chips | **Intentional**, documented (Batch 5) | No |

**Why this happened, systemically:** `InvoiceWorkspaceLayout` and its loading branches were scaffolded in Batch 2 *before* the dense final editor existed (Batch 3 built the real content afterward). Once the real, dense layout landed, nobody went back to reshape the loading/empty states or check the shell's padding against a sibling page — every subsequent batch's test plan verified *function* (tsc/lint/build/tests, accounting invariants) but never a visual diff against the Blueprint's own wireframes. Batch 8 ("Premium Polish") fixed accessibility, modals, and several logic bugs, but its audit didn't include a wireframe-vs-implementation visual pass, so these gaps survived it too.

---

## Proposed restoration plan (no code yet)

**P0 — structural, zero risk, do first:**
1. Add the missing gutter to `InvoiceWorkspaceLayout`'s root container (`px-6 pt-4 lg:pt-5 pb-6`, matching `app/clients/[id]/sales/page.tsx:218`).
2. Build one purpose-built `InvoiceEditorSkeleton` (party-block grid + line-grid rows + notes, each inside the same bordered white cards the real sections use) and a `SummaryPanelSkeleton` (shimmer version of the sticky totals rail). Render **both** — plus a disabled toolbar shell — during the loading branch of `new/page.tsx` and `edit/_page.tsx`, so the two-column silhouette never collapses.
3. Apply the same shaped-skeleton treatment to `InvoiceViewDrawer`'s loading branch for consistency with the Hub's real layout.

**P1 — restore quietly-dropped spec items, low risk, additive only:**
4. Add `unit` to `InvoiceLine`, wire `HsnPick.uqc` into it (the data already arrives at the pick callback and is currently discarded), and add the `Unit` column back to the grid.
5. Add a compact Edit-mode "Activity mini" to the summary rail, reusing the Hub's existing `buildActivity`/timeline data source (no new endpoint).

**P2 — documentation only, no code:**
6. Mark F6 (server-preview shimmer) as *superseded* directly in the Blueprint, so it stops reading as an open gap.
7. Explicitly list Attachments (F7) and the GoodsServicesToggle substitution (F8) in the workspace's "known deferred/superseded" notes so future audits don't re-flag them.

**Guardrail for next time:** add a one-line item to every future batch's regression checklist — *"loading state preserves the two-column shell; page padding matches sibling pages"* — so this class of drift is caught before merge instead of surfacing as a release-blocking audit.

**Risk assessment:** P0 and P1 are pure UI/CSS/component-composition changes — no new endpoints, no schema changes, no touch to `_compute_line_gst`, posting, or any accounting invariant. P1's `unit` field is additive and optional (mirrors how `hsn_sac` is already optional free text), so it cannot break existing drafts or posted invoices.

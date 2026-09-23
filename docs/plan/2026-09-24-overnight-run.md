# Overnight run — 24 September 2026

Written at 04:31 IST at the start of an unattended run, from the code rather
than from any status table. Tick each item as it lands, with its evidence.

**Read this before adding to it.** THE-PLAN.md's own markers have been wrong in
both directions this month — PR #568 existed to correct exactly that — so every
state below was established by grep, by reading the file, or by running the
guard, and each row says which.

---

## A correction, made before any work started

The 19 September checkpoint recorded **"hardcoded hex literals 116 → 170, T4-a's
own metric going backwards"**. That is wrong, and it matters because it would
have sent this run hunting a regression that never happened.

The plan's metric command is a coarse grep:

```
grep -rEoh '#[0-9a-fA-F]{6}' apps/web/app apps/web/components | wc -l   # 170
```

The **guard** — `apps/web/scripts/a-colour-and-a-type-size-come-from-the-token-file.test.ts`
— deliberately counts three different populations, and the coarse grep is their
sum plus comments plus an allowlist:

| population | now | budget | what it is |
|---|---|---|---|
| hex in a Tailwind arbitrary class — `border-[#E2E8F0]` | **98** | 98 | always a class; always has a token |
| bare hex outside a class — `style={{}}`, an SVG attr, a prop default | **46** | 46 | same literal, same drift, no token existed to use |
| arbitrary font size — `text-[13px]` | **392** | 405 | |

All eight guard assertions pass on `352dec8c`. Nothing regressed. **Both hex
budgets sit exactly at their ceiling**, so any new colour written today fails
CI — which is the ratchet working, not a problem.

The checkpoint is corrected in the same commit as this file.

---

## The decision that unblocks the bare-hex half

The guard's own note says a bare hex was left uncounted because a chart colour,
an SVG attribute and an inline style "are not classes and have no token to
use". That is the whole defect: `tailwind.config.ts` is a *Tailwind* config, so
its values reach a class and nothing else. Three screens thread colour through
`style={{}}` and prop defaults and had literally nothing to reach for.

**`apps/web/lib/design/tokens.ts` is the answer, and it is `services/pdf_style.py`'s
shape exactly** — one module, values mapped BY ROLE, each carrying the name of
the Tailwind token it came from so a guard can pin the two together. The PDF
pass proved the shape on six documents that had picked four different header
fills; this is the same fix on the browser side of the same palette.

### Decisions taken tonight, defaults recorded rather than waited on

| § | question | decision | why it is not a coin-toss |
|---|---|---|---|
| **G** | the rival indigo, 55 sites | **indigo loses; `brand` navy wins** | `tailwind.config.ts` already names the problem in its own comment — *"there was no single primary, so three were in use at once — brand navy here, indigo #4338CA in banking, blue-700 on the Team screen"* — and declares `brand.DEFAULT` navy. The rival was already identified as the rival. |
| **I** | a band lighter than `ps.bg` | **add `brand.surface: #EFF6FF`** | Not an invented colour: it is the value three screens already use for one role (a tinted fill behind a brand-ish or active icon). Naming a value the product already writes is the token file's own stated method. |
| — | the 4-band health-score ramp | **three bands, not four** | `#EA580C` appears once, at score ≥55. The state vocabulary is deliberately three-valued — is it ready, does it need me, did it go wrong — and a fourth shade nobody can name is what the token file's "a numbered scale is just slate with different names" note refuses. Collapsed **upward** into `attention`, so a middling score reads as needing attention rather than as a failure; the conservative direction. |

Each is recorded in `docs/audits/questions-for-the-owner.md` as a decision
taken, with this reasoning, so it can be reversed in one edit.

### The contrast fix that falls out of it

`app/workflows/page.tsx:296` colours an inactive template's icon **`#94A3B8`**
— the exact value the token file records moving `ps.hint` **off** at
**2.56:1 on white**, below WCAG 1.4.3 and below 1.4.11's 3:1 for a non-text
component. Same shape as the two contrast defects T5a-2 turned up in the PDFs:
found by doing the consistency sweep, real on its own.

---

## Batch 1 — the browser has a palette it can read outside a class ✅ **LANDED**

- [x] **1.1** ✅ `lib/design/tokens.ts`, 28 values by role. `scripts/one-palette-and-the-browser-reads-it.test.ts` pins it to the config **both ways** — every value equals the config's at its named path, and every export must declare a path, so a value invented here fails. Two negative controls fire on exactly their own defect: changing `READY` to green-600 fails only assertion 1, adding an undeclared export fails only 2 and 3.
- [x] **1.2** ✅ `brand.surface: #EFF6FF`, with the reason and the `ps.hover` trap written beside it. No other token moved — assertion 6 of the older guard still passes.
- [x] **1.3** ✅ 29 → 0.
- [x] **1.4** ✅ 9 → 0.
- [x] **1.5** ✅ 8 → 0, and the inactive-template icon moves off `#94A3B8` (2.56:1) onto `ps.hint` `#64748B` (4.76:1 on white).
- [x] **1.6** ✅ bare-hex budget **46 → 0**, arbitrary font size **405 → 392**. `lib/design/tokens.ts` is allowlisted — hex is its data, the colour picker's exemption. The vacuity floor MOVED rather than being deleted: `total >= 1` becomes self-contradictory at a budget of 0 (the assertion the ratchet exists to reach would fail on reaching it), and the property it protected — that the probe still matches and still reads bodies — is already proved by the allowlist test, which asserts each exempt file still holds a literal.

## Batch 2 — the 98 hex classes ✅ **LANDED**

Worst first, and they are concentrated: `components/ui/data-table.tsx` (18),
`app/clients/[id]/sales` (12), `app/clients/[id]/compliance` (8),
`app/clients` (8), `components/portal/TaxDeclarationTab.tsx` (8) — 54 of 98 in
five files.

- [x] **2.1** ✅ `data-table.tsx`, 18 → 0. Every one was the SELECTION affordance — the bar, the selected-row fill, the checkbox accent, the bulk-action links — so every screen using `DataTable` inherited the rival indigo.
- [x] **2.2–2.5** ✅ the four screens, 36 → 0. Three carry the same bulk-action bar; `components/portal/TaxDeclarationTab.tsx` held the OTHER two rivals the config names, blue-700 as a primary and its own emerald for "ready".
- [x] **2.6** ✅ class budget **98 → 44**.
      *Verified by rendering:* the built stylesheet is grepped for the emitted utilities, so `bg-brand-surface` and `bg-ps-hover` are proved to reach CSS rather than assumed — a Tailwind class naming a token the config does not declare is simply absent, and the element renders unstyled.

## Batch 3 — T6-a, redirect headroom

98 of Cloudflare's hard cap of 100. THE-PLAN says do this before anything else
in T6, and it is independent of T4.

- [ ] **3.1** Read `apps/web/public/_redirects` and `scripts/generate-redirects.js`; establish which rules a pattern could collapse.
      *Accept:* `grep -v '^#' apps/web/public/_redirects | grep -c '200$'` ≤ 90, and `scripts/generate-redirects.test.ts` still passes.

## Batch 4 — T5b, the exports that bypass `rbac()`

Default taken on T5b-3's open scope question: **convert the `rbac()`-bypassing
exports first**. That is the security half and cannot be the wrong call,
whichever way the full-scope question is eventually answered.

- [ ] **4.1** Enumerate the 7 `XLSX.write` sites and say which bypass `rbac()`.
- [ ] **4.2** The shared workbook module in `apps/api`, copying `services/time_export_service.py`.
- [ ] **4.3** T5b-2 — money as a NUMBER, so `=SUM(B:B)` on an exported trial balance returns the total.
- [ ] **4.4** The bypassing exports become endpoints.

## Batch 5 — the backlog residue and the unpaged reads

- [ ] **5.1** Account for all 14 open+partial findings; close what needs no document.
- [ ] **5.2** The unpaged PostgREST reads that feed an export or a statutory figure. The ones bounded by one client or one month stay as recorded findings.

---

## Blocked — do not start

| what | why |
|---|---|
| the TDS FVU/RPU writer | needs the NSDL file layout; egress is refused here |
| the GSTR-9 filing demo | needs the GST offline utility's own screens |
| the annual ITR schema refresh | the ITD publishes them per form per AY; they cannot be inferred |
| professional tax slabs (18 states), LWF amounts | per-state notifications |
| Form 3CD, the bank salary file format | same |
| anything needing spend, a licence purchase, or a registration | GSP, ERI, NIC, Account Aggregator FIU |

A design preference is **not** on this list. Take the defensible default,
record it above, move on.

# Sidebar UI Refresh Proposal

> Do not implement until user approves.

## Current sidebar background

File: `apps/web/components/sidebar.tsx`

The sidebar currently uses:
- Background: `bg-[hsl(224,71%,4%)]` — a near-black navy (~#030712)
- Active item: `bg-indigo-600` with `text-white`
- Hover: `hover:bg-white/5` with `hover:text-white/90`
- Inactive text: `text-white/50`
- Icons (active): `text-white`
- Borders/dividers: `border-white/5`
- Section labels: `text-white/25`
- Mobile hamburger button: `bg-[hsl(224,71%,4%)]`

The login page left panel uses `bg-gradient-to-br from-indigo-900 via-indigo-800 to-violet-900` as its brand panel — this is the design inspiration.

---

## Option A — Deep Indigo (Recommended)

**Feel:** Professional, trustworthy, CA-firm grade. Lifts the sidebar from near-black to a rich branded indigo that aligns with the login panel aesthetic.

| Element | Current class | Replace with |
|---|---|---|
| Sidebar background | `bg-[hsl(224,71%,4%)]` | `bg-indigo-950` |
| Active item background | `bg-indigo-600` | `bg-indigo-700` |
| Active item text | `text-white` | `text-white` (no change) |
| Hover background | `hover:bg-white/5` | `hover:bg-indigo-900` |
| Hover text | `hover:text-white/90` | `hover:text-white` |
| Inactive text | `text-white/50` | `text-indigo-300/70` |
| Icons (active) | `text-white` | `text-white` (no change) |
| Icons (inactive) | inherits text color | `text-indigo-300` |
| Dividers/borders | `border-white/5` | `border-indigo-800` |
| Section labels | `text-white/25` | `text-indigo-400/60` |
| Mobile hamburger | `bg-[hsl(224,71%,4%)]` | `bg-indigo-950` |

Hex reference: `bg-indigo-950` = `#1e1b4b`

---

## Option B — Sapphire Navy

**Feel:** Enterprise SaaS, clean modern, neutral and familiar to B2B users.

| Element | Current class | Replace with |
|---|---|---|
| Sidebar background | `bg-[hsl(224,71%,4%)]` | `bg-slate-900` |
| Active item background | `bg-indigo-600` | `bg-blue-600` |
| Active item text | `text-white` | `text-white` (no change) |
| Hover background | `hover:bg-white/5` | `hover:bg-slate-800` |
| Hover text | `hover:text-white/90` | `hover:text-white` |
| Inactive text | `text-white/50` | `text-slate-400` |
| Icons (inactive) | inherits text color | `text-blue-400` |
| Dividers/borders | `border-white/5` | `border-slate-700/50` |
| Section labels | `text-white/25` | `text-slate-500` |
| Mobile hamburger | `bg-[hsl(224,71%,4%)]` | `bg-slate-900` |

Hex reference: `bg-slate-900` = `#0f172a`

---

## Option C — Professional Purple

**Feel:** Premium, distinctive, strong brand identity for CA firms. Gradient gives depth.

| Element | Current class | Replace with |
|---|---|---|
| Sidebar background | `bg-[hsl(224,71%,4%)]` | `bg-gradient-to-b from-[#1e1b4b] to-[#312e81]` |
| Active item background | `bg-indigo-600` | `bg-violet-600` |
| Active item text | `text-white` | `text-white` (no change) |
| Hover background | `hover:bg-white/5` | `hover:bg-violet-900/50` |
| Hover text | `hover:text-white/90` | `hover:text-white` |
| Inactive text | `text-white/50` | `text-violet-200/60` |
| Icons (inactive) | inherits text color | `text-violet-300` |
| Dividers/borders | `border-white/5` | `border-violet-800/50` |
| Section labels | `text-white/25` | `text-violet-300/40` |
| Mobile hamburger | `bg-[hsl(224,71%,4%)]` | `bg-[#1e1b4b]` |

Gradient reference: `from-[#1e1b4b]` (indigo-950) → `to-[#312e81]` (indigo-900)

---

## Recommendation

**Option A — Deep Indigo** is recommended.

Reasons:
1. Matches the login page left panel brand colour family (`from-indigo-900 via-indigo-800`) — creates visual consistency across the product.
2. The existing active item colour (`bg-indigo-600`) is kept, minimising change surface.
3. `bg-indigo-950` is noticeably warmer and more branded than the current near-black without being distracting.
4. Suitable for long work sessions — not overly saturated.

To implement Option A, the implementer only needs to update `apps/web/components/sidebar.tsx` — no other files are affected.

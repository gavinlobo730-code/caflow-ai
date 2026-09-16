# PracticeSync website redesign — plan

**Date:** 16 September 2026
**Source brief:** `PracticeSync_Complete_Website_Redesign_Brief_for_Claude_UPDATED.docx`
(21 sections + a hero concept reference image)
**Scope:** `apps/marketing` only. `apps/web` (the product) is not redesigned here;
where this document names a product defect it is flagged, not fixed, unless
called out as in scope.

This plan is written against the code as at `3d66b5c`. Where the brief and the
code disagree, the disagreement is named rather than resolved silently.

---

## 0. The question that was asked first: is the employee portal there?

**Yes. It is shipped, it works, and the website barely mentions it.**

What exists in the platform:

| Piece | Where |
|---|---|
| Employee portal screen | `apps/web/app/portal/employee/page.tsx` — five tabs: payslips (with PDF download), leave balance, tax declaration, tax deducted (the employee's own §192 projection, added on `main` this week), read-only profile |
| Invite activation | `apps/web/app/portal/employee/activate/page.tsx` — deliberately separate from the client portal's `/portal/activate`; binds a `payroll_employees` row, not a `client_portal_users` membership |
| Tax declaration | `components/portal/TaxDeclarationTab.tsx` — the employee's own Form 12BB (Rule 26C) |
| Tax deducted | `components/portal/TdsProjectionTab.tsx` — the §192 working, resolved from the caller's own identity so it cannot be pointed at a colleague |
| Backend | `apps/api/services/employee_portal_service.py`; `routers/payroll.py` → `POST /employees/{id}/portal-invite`, `POST /employees/{id}/portal-revoke`, `GET /employees/{id}/portal-status` |
| Isolation | migration 262's `employee_sees_own_record` RLS policy, scoped to the employee's own rows; gated on `payroll_employees.auth_user_id` + `portal_enabled` |

What the website says about it: **one bullet.** `apps/marketing/app/(site)/products/page.tsx:49`
— "Employee self-service portal", inside the Payroll module's feature list. It is
not on the homepage, not in the sign-in chooser, and has no page of its own.

### Two real gaps this exposes

**(a) The sign-in chooser has no door for an employee.** `/access` offers exactly
two cards — "Chartered Accountant / Firm workspace" and "Client & SME / Client
portal", the second described as "For clients invited by their firm". An employee
of a CA's client is neither. They have no route in from the website at all.

**(b) — platform defect, not a website one —** `/portal/login` pushes every
successful sign-in to `/portal/dashboard` (`apps/web/app/portal/login/page.tsx:42`),
and that dashboard resolves *client* memberships only. An activated employee who
comes back and signs in normally therefore lands on the zero-memberships branch
(`apps/web/app/portal/dashboard/page.tsx:234`) and reads:

> "You don't have access to a client portal right now. If you believe you should
> have access, ask your accountant to invite you."

They *do* have access — to a different portal. Their only working route to
`/portal/employee` is the original activation link or typing the URL. **Fixing
this is a prerequisite for marketing the employee portal at all**, because the
site would be advertising a door that closes in the visitor's face. It is a small
fix (resolve employee identity alongside memberships and route accordingly) but
it is in `apps/web`, outside this brief's scope, and needs its own decision.

---

## 1. What else the platform has that the website does not say

The product has 160 routes. `/products` describes six modules. These shipped
subsystems have no representation on the site at all:

| Shipped | Evidence | Site coverage |
|---|---|---|
| Banking & reconciliation | `clients/[id]/bank`, statement import, bank rules, trusted rules, `bank_posting_service` | none |
| GSTR-2B reconciliation | `/gst/reconciliation`, `services/gst_2b_reconciliation_service.py` | none |
| Sales & purchases | invoices, bills, credit/debit notes, e-invoice & e-way rails | none (only "ledgers") |
| Inventory | `clients/[id]/inventory`, `public.stock_position_as_at` | none |
| Workflow automation | `/workflows`, `/workflows/approvals`, `/approvals`, task templates | "Tasks" only |
| Tally migration | `/migration` | none — although the homepage says "replaces Tally" |
| Employee portal | above | one bullet |

This is a bigger content gap than anything in the brief, and it is free to close:
the work is words, not engineering.

---

## 2. Three accuracy problems live on the site today

The brief is explicit (§16): *"Do not invent customers, integrations,
certifications, savings, accuracy percentages or performance statistics"* and
(§18) *"Do not add invented product claims or fake testimonials."* Three things
currently on the site fail that test.

**2.1 An invented testimonial.** `practicesync-homepage.html:215-216` carries a
pull-quote attributed to *"CA Rohan Agarwal — Partner, Agarwal & Co., Bengaluru"*
claiming four cancelled subscriptions. Unless that is a real, consenting
customer, it must go.

**2.2 The site implies PracticeSync files returns. It cannot.** The homepage
marquee reads "ITR FILING" and "MCA FILINGS"; `/products` promises "MCA filings
for companies and LLPs". PracticeSync **prepares** — it computes the return and
produces the JSON, and a human files it on the portal. Filing through the
software is gated on GSP registration (GSTN) and ERI registration (CBDT), neither
of which is held; see `docs/compliance/07-getting-permission-to-file.md`. Even
e-invoice IRN and e-way bill — the only two statutory outputs software can
complete end to end — are prepare-only rails today.

This is the single biggest credibility risk in the whole site, precisely because
the audience is CAs: the first one who signs up finds out in an afternoon. The
honest version is also the better pitch — *"every return computed from the books
and file-ready, and nothing leaves your hands without your click"* — and the
homepage's own "Nothing is filed without your click" section already sets it up.

**2.3 Unverifiable hero claim.** "Set up in a day" (hero trust chips). Either
someone stands behind it or it goes.

Two things in the **reference image** would import the same problem and must not
be reproduced literally: the chip *"Trusted by Growing Practices"* (a customer
claim with no customers), and *"Secure & Compliant"* used as a badge (compliant
with what?). The brief itself says (§18) not to treat the supplied hero as final
production art.

**On the stat counters** (`11+ modules`, `4 tools replaced`, `100% filings
reviewed by a CA`, `4 compliance domains`): these are defensible. "100% reviewed"
is a policy statement that is always true, and the other three are countable
facts about the product, not performance claims. Keep, but re-count them against
the module list after §1's additions.

---

## 3. The architectural decision this redesign turns on

**Recommendation: port the homepage into the React app and do the redesign once,
there.**

Today the homepage is `apps/marketing/public/practicesync-homepage.html` — 717
lines of inline-styled HTML with a hand-rolled JS engine — served at `/` by a
Cloudflare `_redirects` rewrite. The inner pages (`products`, `pricing`,
`support`, `resources`) are React sharing `SiteHeader`, `SiteFooter`,
`cinematic.tsx` and `ui.tsx`.

Every homepage↔inner-page inconsistency fixed in the last week was a symptom of
that split — logo size and position, CTA colour, header typeface, nav gaps,
content max-width, light-panel inset, header vertical alignment, scroll
mechanics. Each was found separately, fixed twice, and verified twice.

The brief's §21 asks for the opposite of that: *"The dynamic hero word, premium
globe/network visual, typography and motion must feel like one designed system"*
and *"Every major section should maintain the same level of craft established by
the hero."* That is not reachable while half the site cannot use the other half's
components.

A redesign is the cheapest moment this will ever be, because the homepage is
being rewritten anyway. The cost is that the globe, kinetic type, focus-reveal,
marquee, parallax and counters have to become React components — and the brief
needs all six of them in *other* sections too (§5 ecosystem, §7 product UI, §12
motion), so that work is not overhead, it is the work.

If the answer is to keep the static file: everything below still applies, it just
gets built twice and starts drifting again immediately.

---

## 4. The plan

Staged against the brief's own priorities (§17), except that Stage 0 comes before
P0 because shipping a beautiful page with a fake testimonial on it makes the
problem worse, not better.

### Stage 0 — Truth pass (ship on its own, before any redesign)

Independent of every decision below. Small, and it makes the rest safe.

1. Remove the invented testimonial and either drop that section or replace it
   with a product-truth section.
2. Reword every filing claim to prepare/file-ready, on the homepage marquee, the
   platform-domains line, and `/products`' Compliance bullets. Keep and promote
   "Nothing is auto-submitted — a CA confirms every government filing".
3. Drop "Set up in a day".

The CTA change from §5.1 is deliberately **not** in this stage. It is a strategy
change, not a correction, and it needs the `/demo` page to exist before the
button can point anywhere honest. It lands in Stage 2 with the new hero.
4. Add the six missing subsystems from §1 to `/products`: banking &
   reconciliation, GSTR-2B recon, sales & purchases, inventory, workflow
   automation, Tally migration. Promote the employee portal out of a bullet.
5. Give `/access` a route for employees — a third card, or a relabelled client
   card that names both. **Blocked on the `/portal/login` routing fix** (§0b):
   pointing employees at a door that tells them they have no access is worse than
   the silence we have now.

### Stage 1 (P0) — Foundation

- New `app/(site)/page.tsx`; retire `practicesync-homepage.html` and its
  `_redirects` rewrite once parity is proven side by side.
- Extract the homepage's engine into components: `HeroGlobe`, `KineticLines`,
  `FocusReveal`, `Marquee`, `Counters`, `Parallax` — into `components/cinematic.tsx`
  and `components/motion.tsx`.
- One token pass: the static file uses raw `oklch()` literals, the React side
  uses Tailwind tokens. Unify on `tailwind.config.ts` so one edit moves both.

### Stage 2 (P0) — The hero

- **Copy** to the brief: eyebrow `THE AI-FIRST PLATFORM FOR INDIAN CA FIRMS`;
  the rotating word; fixed `Run your entire practice on one intelligent platform.`;
  then the brief's supporting line.
- **The rotating word already exists** and needs three small changes, not new
  work. `practicesync-homepage.html:261` holds
  `['Compliance.','Clarity.','Control.','Automation.','Trust.']` on a 2200ms
  interval doing a bare `textContent` swap with no transition. Change to the
  brief's sequence starting on `Automation.`, keep ~2.4s (inside the brief's
  1.5–3s), and add the smooth fade/vertical transition the brief asks for.
- **Globe:** evolve, don't replace (brief §2). The reference image wants India
  central, fine network points, orbital trails and eight connected feature cards.
  Today there is a globe plus three unrelated tilt-cards (a client row, an "AI
  flagged" chip, a filing calendar). Rework to the eight modules on orbital
  anchors. Cards stay **DOM, not WebGL**, so they are readable, selectable,
  translatable and keyboard-reachable; SVG lines connect them to the globe.

**Performance budget — the hard constraint, stated up front.** Measured last
week: with the globe running, the hero holds 11–14fps; blocking `three.min.js`
restores it to 60fps, exactly matching the React pages. (That measurement is from
a GPU-less sandbox on software SwiftShader, so it overstates real cost — but the
direction is right and the user reported the same slowness on a real low-end
laptop.) The brief now adds orbits, floating cards and parallax on top of that.
So the budget is explicit:

- globe capped at 30fps and quiet for 150ms after each scroll event (both already
  implemented);
- globe paused entirely once the hero leaves the viewport (already implemented);
- cards animate on `transform`/`opacity` only — compositor, never layout;
- static SVG fallback under `prefers-reduced-motion`, on mobile, and on
  `navigator.deviceMemory <= 4`;
- the hero's box is reserved so nothing shifts while Three.js loads.

### Stage 3 (P0) — Real product UI

The brief calls this *"one of the most important additions after the hero"* (§7).

**Recommendation: build faithful HTML/CSS recreations from the actual `apps/web`
component source, rather than pasting screenshots.** They are crisp at every DPR,
roughly 2KB instead of 200KB, animatable between states (which §7 explicitly
asks for), themable, accessible, and they do not silently go stale when the
product moves. Fidelity is not a concern because the source of truth is in this
repo.

Four candidates that are both genuinely impressive and genuinely shipped:

1. the client workspace overview,
2. the GSTR-3B workspace showing the four-step §49(5) set-off,
3. the bank reconciliation queue with "Pass 12 ready",
4. the AI copilot answering a practice question.

### Stage 4 (P1) — Ecosystem, problem→solution, AI, trust

- **Ecosystem (§5):** PracticeSync at the centre, modules around it, each with a
  small real UI preview rather than an icon and a paragraph. Reuse the hero's
  orbital system so the two read as one idea.
- **Problem→solution (§6):** the existing "THE PROBLEM" section already carries
  this in type — add the visual. No invented metrics (§6 says so explicitly).
- **AI in action (§8):** the brief's chain — request → understood → documents and
  tasks identified → workflow created → deadlines monitored → team notified —
  maps cleanly onto shipped surfaces (`/copilot`, `/memory`, document
  intelligence, `/workflows`, `/deadlines`, `/notifications`). Every step shown
  must be one of those.
- **Trust (§9):** role-based access (Partner > Manager > Executive > Reviewer >
  Client), TOTP MFA, full audit log, data in India (Supabase ap-south-1, Mumbai),
  an append-only general ledger where corrections are reversals rather than
  edits, and nothing auto-submitted. All verifiable. **No certification badges,
  no compliance logos, no customer logos** (§9).

### Stage 5 (P1→P2) — Inner pages, logo, QA

- Re-lay `/products`, `/pricing`, `/support`, `/resources` on the new system.
- **Logo (§4):** explore the tick inside a continuous ring. `LogoIcon` in
  `apps/web` already spins the ring for loading states, which is exactly the
  behaviour §4 describes — so the concept is half-built. Static mark must stay
  recognisable. Low risk; do it late.
- **Final:** Lighthouse, visible keyboard focus, contrast, alt text, mobile
  layout, CLS, and a conversion pass on the CTA path.

---

## 5. Decisions taken (owner, 16 September 2026)

Four questions changed the work rather than the polish, so they were asked before
any of it started. All four are now settled.

**5.1 Primary CTA — Book a Demo, with a real booking page.** The brief's funnel
wins over the current self-serve one. *Start free trial* is demoted to secondary
everywhere, and a first-party demo-request page is built: name, firm, firm size,
message. **No third-party scheduler** — no Cal.com, no Calendly, no embedded
widget.

How it sends, since a static export has no server: `apps/api` already has a
working transport — `services/email_service.py` on Resend (`RESEND_API_KEY`,
declared optional in `core/config_validation.py`). The form therefore posts to a
**new public, unauthenticated endpoint on `apps/api`** that reuses it. That
carries four obligations, none optional:

- the endpoint is the only unauthenticated write surface on the API, so it needs
  a honeypot field, a rate limit and a hard payload cap;
- it writes no tenant data and touches no `firm_id`-scoped table;
- `apps/marketing` does not currently know the API origin — it only has
  `NEXT_PUBLIC_APP_URL`. A `NEXT_PUBLIC_API_URL` must be added to
  `next.config.mjs` **and** `wrangler.toml`;
- any new backend env var must be declared in `render.yaml` —
  `tests/test_render_manifest_matches_code.py` enforces that in both directions.

If Resend is unset the endpoint must fail loudly to the visitor rather than
returning success, or demo requests vanish silently. That is the same
false-clean-result failure the codebase has fixed repeatedly elsewhere.

**5.2 Architecture — port the homepage into React.** §3's recommendation is
adopted. `practicesync-homepage.html` and its `_redirects` rewrite are retired
once parity is proven.

**5.3 Product UI — recreations built from source.** Stage 3's recommendation is
adopted. No screenshots.

**5.4 The testimonial is not real — remove it.** The Rohan Agarwal pull-quote and
its section go in Stage 0. Nothing replaces it with another customer claim.

---

## 6. What this plan deliberately does not do

- It does not touch `apps/web` beyond naming the `/portal/login` routing defect.
- It does not add a certification, badge, customer logo or metric that nobody can
  stand behind.
- It does not reproduce the reference image pixel for pixel — §18 says not to,
  and two of its trust chips would import claims the product cannot support.
- It does not trade page speed for motion. Where the brief's motion and the
  performance budget conflict, the budget wins and the effect is simplified.

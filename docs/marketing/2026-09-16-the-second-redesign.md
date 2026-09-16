# The second redesign — 16 September 2026

> **STATUS: BUILT.** All six items below are done, plus the two findings the
> audit turned up (a second unused design system, and three descriptions of what
> the product is). Guards are in
> `apps/api/tests/test_the_marketing_site_says_what_the_product_does.py`; against
> the pre-change tree **9 of the 10 new assertions fail**, and the tenth is
> covered by its own vacuity test — see "Guards" at the foot of this document
> for why that one needed it.


The first redesign (PR #525) ported the homepage into React and gave the whole
site one component library. It fixed the *drift*. It did not make the site
**look** like the reference, and the owner's review of the live site named six
things by hand. This document is the plan for those six, plus what auditing
them turned up.

Read `2026-09-16-website-redesign-plan.md` first — it is the brief and the
record of stages 0–5. This is the follow-on.

---

## What the owner said, and what each one turns out to be

| # | Said | What it actually is |
|---|---|---|
| 1 | "I dont think you have perfectly imported the image … you can clearly see the difference" | The globe is a **wireframe**, not an Earth. No continents, a visible graticule grid, 1,400 sparse dots, thin arcs. |
| 2 | "the diagonal cards dont look good" | `SEAM_CLIP` — three `clip-path` polygons in `cinematic.tsx`, on 20 panels across 6 pages. |
| 3 | "the top bar is grey … we should keep it blue" | `SiteHeader`'s scrolled state is `bg-[#f3f5f8]/80` — an off-white the palette does not contain. |
| 4 | "the 01 and the numbering … dont look asthetic" | `Panel`'s `numeral` prop: `clamp(200px,28vw,400px)` at 5% opacity, 12 occurrences. |
| 5 | "our story is a big page … we have to split it" | There is no Our Story page. The nav links to `/#story`, an anchor onto a homepage panel headed "Every CA firm runs like this." |
| 6 | "consistency the wordings and everything must be consistent on all pages" | Measured below. Four CTA spellings, three eyebrow vocabularies, and a whole unused rival component system. |

---

## 1. The globe

### Why it looks wrong

`geography.ts` records the decision that produced it:

> a land texture … would have to be written from memory here, and a world map
> with the wrong coastline on the homepage of a product sold to Indian
> professionals is a worse error than no map at all.

That reasoning was right **and its premise is now false**. `world-atlas@2` and
`topojson-client` install from npm in this environment (verified 16-09-2026),
which is Natural Earth's own public-domain coastline, not a recollection of one.

### The fix

A **build-time rasteriser**, not a runtime dependency.
`apps/marketing/scripts/build-landmask.mjs` reads `land-110m.json`, scanline-fills
every ring with an even-odd test at 0.5° resolution, and writes a 720×360 bitmask
into `components/home/landmask.ts` as base64.

Measured on the generated mask:

```
edges                4,997
land cells          75,484 of 259,200  = 29.1%   (real land ≈ 29%)
raw                 32,400 bytes
base64              43,200 chars
gzip (what ships)    5,332 bytes
```

Eleven coordinate spot-checks pass — Delhi, Bengaluru, London, the Sahara, the
Amazon and Antarctica are land; the Arabian Sea, the Bay of Bengal, the mid
Atlantic and the mid Pacific are not. Those checks move into the test suite, so
a regenerated mask that puts Mumbai in the sea fails rather than ships.

**The generated file is committed and the two packages are `devDependencies`.**
A Cloudflare Pages build never runs the rasteriser, so it cannot break the
deploy, and the mask can only change when somebody deliberately regenerates it.

### Three bugs found while building it, worth recording

**The first render was a solid white disc.** Three compounding faults, and the
one that did the damage was arithmetic rather than taste:

1. `gl_PointSize = aSize * (canvasHeight * 0.55) / -z` with `aSize` starting at
   1 made every land dot **about 70 pixels across**. Point sizes are world
   units and the shader has to do the real projection —
   `s · H / (2·tan(fov/2)) / d` — which is now derived in `projScale()` with the
   derivation written beside it rather than tuned by eye.
2. The land field was **additively blended**. It is the planet's lit *surface*,
   and foreshortened dots overlap near the limb, so summing them saturates the
   continents to white before the atmosphere is drawn. Hubs and arcs stay
   additive because those genuinely are light sources.
3. The atmosphere sat at `uIntensity: 1.15` (a full-strength additive rim) and
   the bloom sprite opened at `0.60` alpha over the planet's face. Now `0.5` and
   `0.30`, and the sprite is pushed behind the globe so it haloes rather than
   washes.

**The centre badge was covering India.** A 52px mark sat at exactly 50%/50% of
the composition — which is exactly where the globe now puts the subcontinent, so
the one feature the brief asks to be "visibly central" was underneath it. It
made sense over an abstract sphere and stopped making sense the moment the
sphere became an Earth. Removed; the eight connectors converge on the lit
subcontinent instead.

**Light panels became visibly empty.** With the seams gone a light panel is a
card rather than a band running off both edges, and a stacked heading occupies
its left 55%. Two changes: light cards take less vertical padding than
full-bleed dark ones, and `SerifHeading` gained `layout="split"`, which sets the
headline and its standfirst in two columns from `lg` up.

### The scene, against the reference image

| Reference shows | Now | After |
|---|---|---|
| Continents picked out in light | graticule grid, no land | ~9,000 land-only points from the mask; **no grid at all** |
| A luminous blue atmosphere | a flat radial sprite | a real fresnel shell (`ShaderMaterial`, additive) plus the sprite for bloom |
| Thick, bright orbital sweeps | 1-pixel `LineBasicMaterial` | ribbon arcs built from `TubeGeometry`, with a travelling comet head and tail |
| Big glowing network nodes | 3px dots | sprite-haloed hubs that pulse |
| Larger cards, colour-tinted icons | small monochrome cards | larger glass cards, per-module accent tint |

Every performance guard in the current file is kept unchanged — the 30fps cap,
the scroll-quiet window, the viewport and visibility stops, the capped DPR, and
`canRunGlobe()` deciding whether three.js is downloaded at all. The land points
are one extra `THREE.Points` in the same draw call budget; the tube arcs replace
lines one-for-one.

The **SVG fallback gets continents too**, from the same mask at a coarser step.
It is what a phone and a reduced-motion visitor actually see, so it cannot stay
a wireframe while the WebGL scene gets an Earth.

## 2. The diagonal seams

`SEAM_CLIP` goes, and with it `marginTop: -64px` and the `pt-[calc(…+64px)]`
compensation that existed only to clear the diagonal.

What replaces it is not "a straight edge" — that would be flat. A light panel
becomes a **rounded card floating on the navy canvas** (`rounded-[40px]`, a
hairline, a soft shadow), and a dark panel carries a subtle top gradient so the
boundary still reads. The seam was doing a job: telling the eye a section
changed. The rounded inset does the same job without the wedge.

`seam` is removed from `Panel`'s props entirely rather than defaulted to
`"none"`, so the 20 call sites have to be edited and none can quietly keep it.

## 3. The header

Scrolled state becomes `bg-brand-dark/85` with the blur, and a `brand-light/15`
hairline.

This **deletes a whole class of bug rather than recolouring one**. The current
header cross-fades the logo, every nav link, the mobile toggle and the mobile
sheet between a dark-on-light and a light-on-dark palette, because the scrolled
bar was a different colour family from the page it sits on. Navy in both states
means the logo is white always, links are white always, and there is no
`onNavy` fork to get wrong. `SiteHeader` loses ~20 lines.

The 68px height and the inset-shadow hairline stay exactly as they are — that
was a real fix (commit `830fd21f`) and a border would put the 69th pixel back.

## 4. The numerals

`numeral` and `numeralCorner` are removed from `Panel`. The hero's inline `01`
goes with them.

Wayfinding is kept, differently: `SerifHeading` gains an `index` prop rendering
a **small tabular figure with a short gold rule** beside the eyebrow —
`02 —— The platform`. It is 12px, not 400px; it reads as an editorial section
marker rather than a watermark.

## 5. Our Story

A real `/story` page, and the nav points at it.

The homepage keeps a **short** positioning panel (the five-tools problem, three
lines) with a link through. The story page carries what a CA actually wants
before they trust a new platform: why this exists, what was decided and why,
what it deliberately does **not** do, and where the product is today. The last
of those is the distinctive part and it is all true — this software prepares
returns and refuses to file them, it holds no rate nobody has read off a
Finance Act, and it names what it cannot compute rather than guessing.

The anchor `/#story` keeps working (it redirects), because it is in the wild.

## 6. Consistency — measured, not asserted

Counted across `app/` and `components/`:

| Defect | Count | Resolution |
|---|---|---|
| `Book a demo` | 18 | canonical |
| `Book a Demo` | 1 | → `Book a demo` |
| `Start free trial` | 6 | canonical |
| `Start a free trial` | 4 | → `Start free trial` |
| `Get started` as a CTA | 1 | → `Start free trial` |

Eyebrow vocabulary, three labels for two ideas:

- `Security & trust` (products) vs `Trust, security & reliability` (home) → **`Security & trust`** both.
- `FAQ` (pricing) vs `Common questions` (support) → **`Common questions`** both.
- `Control & trust` (home) is a *different* idea — it is the filing boundary, not security — so it becomes **`How filing works`**, which is what the panel says.
- `The platform` appears on both home and products for different sections; products' hero becomes `The platform`, home's ecosystem panel becomes `One connected workspace`.

### The finding nobody asked for

**`components/ui.tsx` is a second, unused design system.** Nine exports; exactly
one — `Button` — is imported anywhere. `Section`, `Eyebrow`, `SectionHeading`,
`Card`, `IconBadge`, `FeatureCard`, `PageHero` and `CTASection` have no callers,
and `CTASection` carries its own closing copy that has already drifted from
`CineCTA`'s ("Start a free trial today, or talk to us about moving your firm
across…" against "Book a demo and we'll walk a real client's month…").

This is the pattern `CLAUDE.md` names repeatedly — *two implementations drift,
and one of them is the one somebody reaches for next*. The eight dead exports
are deleted and `ui.tsx` becomes what it is: the `Button`. A guard asserts no
second heading or CTA primitive comes back.

---

## Guards

All in the backend suite, because `apps/marketing` has no test runner and
`test_the_marketing_site_says_what_the_product_does.py` already reads its source.

1. The land mask decodes, is 29% ± 2 land, and puts **eleven named coordinates**
   on the right side of the coastline. The list is deliberately of *unambiguous*
   points — an earlier draft used Chennai, which at 0.5° cells falls in a cell
   centred offshore of Mahabalipuram and reported "sea" correctly. A coastal
   city tests the grid resolution, not the coastline.
2. `world-atlas` and `topojson-client` are **not** in `package.json`, and the
   vendored source keeps its licence beside it.
3. No `clip-path` polygon seam and no `seam=` prop anywhere.
4. No `numeral` prop, and no type size at or above 100px — the rule rather than
   the one spelling that shipped.
5. The header's filled state uses `bg-brand-dark`, carries no off-palette hex,
   and keeps the 68px height and the inset-shadow hairline from `830fd21f`.
6. `/story` exists, `NAV` points at it, no nav entry is a fragment, **and no
   "Our Story" link anywhere still points at `/#story`** — that last clause
   exists because the first version of this guard checked `NAV` only and left
   `SiteFooter`'s Company column on the anchor. A guard that names one of two
   doors is one edit from naming neither.
7. One spelling each of the demo CTA and the trial CTA.
8. The product is described as a **platform for Indian CA firms** everywhere —
   asserted on the noun and the customer rather than on a whole sentence, so
   copy may still be phrased for its position.
9. `ui.tsx` exports `Button` and nothing that duplicates `cinematic.tsx`.

### Two of these needed a vacuity test, and one of them proves the point

`Book a Demo` fires on **nothing** in the pre-change tree: its single occurrence
was inside a JSX comment quoting the brief, which the scan skips by design. A
rule with nothing to catch reads as enforcement and is not, so
`test_the_canonical_calls_to_action_are_actually_on_the_site` requires the
canonical labels to appear in live markup.

The same shape, found in the *existing* guard: `\bSet up in a day\b` had been
sitting there while the support FAQ said "most firms are up and running within a
day" — the identical unmeasured claim, in words the literal pattern could not
see. The entry is now about any promise that setting up takes a stated length of
time, and the vacuity test carries both spellings.

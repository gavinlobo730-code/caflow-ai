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

---

# Addendum — the globe, again (same day)

The redesign merged as #526 and the owner compared the deployed hero with the
reference once more: *"even if the globe is not moving its fine but i want you
to exactly copy the globe as it is in the image if you yourself compare you can
spot the difference right?"*

They were right, and holding the two side by side there were six differences,
not one.

| Reference | What #526 shipped | Fix |
|---|---|---|
| Sphere is near-**black** | Navy `0x10203f` | `0x071223` / limb `0x01040c` |
| Continents are fine bright **white-cyan lights** | Coarse blue-grey `(0.34, 0.46, 0.74)` dots at 0.0125 | `(0.62, 0.79, 0.97)` at 0.0088, 90k candidates (~26k points) |
| India sits **above** the centre | Dead centre | `INDIA_TILT_X = -0.045` |
| The white tick badge is **on the globe** | Removed in #526 | Restored |
| **Four-plus** bright thin sweeps | Two thick dim ones | Four at 0.004–0.0045, brighter |
| Connector web is **clearly visible** | Flat 0.22 | 0.42, thinner stroke |

## The badge: a fix that addressed the symptom

#526 removed the centre mark *because it was covering India*. That reasoning
only holds if India has to be at the centre — and the reference has both, at
different heights. **The planet was in the wrong pose, not the mark in the wrong
place.** `INDIA_TILT_X` is derived rather than dialled in: rotating about +X by
`a` sends a surface point to `y' = y·cos a − z·sin a`, and India at 22°N facing
the camera is `(0.375, 0.927)`, so `0.375·cos a − 0.927·sin a = 0.41` gives
`a ≈ −0.045`. The old `+0.28` pushed India *down* to 10% of the radius, which is
how it ended up under a badge at 50%/50%.

## The Earth is now locked

Owner's call — *"even if the globe is not moving its fine"*. It used to
oscillate ±15° in Y and ±3° in X, which cannot be reconciled with copying a
still frame: for most of every cycle the planet is **not** in the reference's
pose, and India drifts out from under the composition built around it. The
sweeps still turn, the arc pulses run, the hubs breathe and the particles fall.
Only the globe holds its mark.

## Two corrections to #526's own reasoning

- **"Three thin rings read as a diagram; two heavier ones read as motion."**
  Wrong about this picture. The reference has four or five *fine bright* arcs at
  different inclinations, and the count is what makes it an orbital system
  rather than a ringed planet. Thin and bright, not thick and dim.
- **Limb darkening at `0.16 + 0.84·limb`.** Too aggressive: the outer third of
  every continent dissolved, so Africa and East Asia were ghosts at the edges.
  The reference keeps its coastlines lit almost to the silhouette and lets the
  atmosphere do the rounding. Now `0.48 + 0.52·limb` over a tighter ramp.

## And a real bug the redesign shipped

**Two hero cards were clipped off the side of the screen**, at every common
laptop width:

```
Payroll    71px past the right edge at 1280,  56px at 1366,  19px at 1440
Documents  71px                               56px           19px
```

`MAX_RIGHT_ANCHOR` now carries the derivation and a test reads the anchors.

**It shipped because the hero is `overflow-hidden`.** The cards were clipped
rather than pushed out, so the document never gained a horizontal scrollbar —
and #526's verification measured exactly that (`scrollWidth` vs `clientWidth`,
"no horizontal overflow on any of the seven routes at 390px or 768px") and saw a
clean page. The check was sound and measured the wrong thing: *only measuring
the cards finds it.*

Two further things only measurement caught:

- **"Fits inside the stage" is not the rule.** It is tempting because it needs no
  page arithmetic — and it yields 69.4%, which drags every right-hand card onto
  the face of the globe where they overlap each other and the centre mark. The
  cards belong outside the disc. The binding constraint is the viewport at
  1024px, the narrowest width that still shows cards.
- **Non-overlap is not a gap.** Practice analytics and Banking measured 17px
  apart and read as one block — and `.floaty` bobs each card 12px on its own
  delay, so two cards in a column drift up to 12px relative and that 17px closes
  for part of every cycle. The check now requires a 24px moat, and the pair is
  laid out far enough apart to survive the bob.

## `side: "left"` had never worked, and the guard for it was vacuous

Two findings from measuring the card layout, both worth recording because each
one was invisible in review and in the rendered page.

### The placement transform was being thrown away every frame

Each card carried both its placement transform — `translate(-100%, -50%)`, what
hangs a left-hand card off its anchor — **and** the `.floaty` class. `.floaty`'s
keyframes set `transform` outright, and an animation's value beats an inline
one, so the placement was discarded on every frame.

**`side: "left"` therefore did nothing at all.** Every card grew rightward from
its anchor, left and right alike, and the vertical `-50%` centring went with it.
Measured: the Compliance card's *left* edge sat exactly at its own `x%`, where a
left-hand card should have its *right* edge there.

It reads as a styling detail and it is not. It is why the left column had to be
crowded onto the globe to stay clear of the headline, and why two cards laid out
218px apart measured 21px apart. The fix is structural — an outer element
positions, an inner one bobs — because CSS has no error for this and the page
looks plausible either way.

It also means the two anchor rules are **not** mirrors of one another, and that
asymmetry is real rather than an oversight:

- **Right**: past the stage is background, so the limit is the viewport at
  1024px. "Fits inside the stage" was tried and is wrong — it crowds every card
  onto the globe's face.
- **Left**: past the stage is the hero's own headline and buttons, so the card
  must stay inside the stage. `MIN_LEFT_ANCHOR = 37` is the widest card
  (232px) over the 640px stage.

### And the guard written for it passed having examined nothing

The first version of the pattern was edited in through `sed`, which turned the
`\b` into a literal **backspace byte**. `<div\x08[^>]*>` matches nothing, so the
loop ran zero times and the test reported green — while the bug it describes sat
in the file two lines from the assertion. It survived a negative control, twice,
because reintroducing the bug changed nothing about a loop that never ran.

This is precisely the failure #527 landed on `main` for — *"the redesign's
safety net was reporting green having observed nothing"* — reproduced one
directory over, within the hour. The test now asserts the match **count** before
it asserts the rule, and a repo-wide scan confirmed no other source file carries
a stray control byte.

---

# Addendum 2 — the golden globe (17 September 2026)

A second reference image, and the owner's read of it: *"the golden effect the
shadow the finish the premium look … can you exactly copy the same image … even
i can see its reflection"*, with *"im okay if it is a stable image … even a
static image is perfect for me"*.

## What was taken

| Reference | Built |
|---|---|
| Golden city lights | Land points are amber; India gold-white at the core of the falloff |
| A warm sunrise on the limb | A real terminator — `SUN_DIR` in the shader, narrowed to an arc |
| A reflection under the globe | A mirrored copy of the land, fading over ¾ of a unit |
| Vertical rail | PEOPLE / DATA / COMPLIANCE / GROWTH / ALL IN SYNC |
| Closing tagline | SYNC TODAY. A STRONGER TOMORROW. |
| A stats row | Same shape, different figures — see below |

**The sun is in VIEW space, not world space.** The terminator is a composition
decision — the reference puts its sunrise on the upper right — so anchoring it
to the camera keeps it there whatever pose the globe is in. A world-space sun
would swing the gold edge around every time `INDIA_TILT_X` is touched, which is
two things fighting over one number.

**The window is what makes it a sunrise rather than a ring.** At
`smoothstep(0.05, 0.85)` the warm band ran from about 11 o'clock round to 6 —
half the limb, which reads as an orange hoop bolted to the planet. `(0.42, 0.97)`
is an arc.

**India gets brighter, not whiter.** Lifting blue to 0.74 at the centre of the
falloff turned the subcontinent white against an amber world, inverting the
reference, where India is the most intensely *gold* part of the picture. Blue now
rises far less than red and green.

**The reflection reuses the land geometry** — 26,000 points already uploaded,
drawn again through a mirrored matrix. No second buffer, no second build, one
extra draw call. The fade is a shader term reading world Y, not a gradient
overlay, because an overlay would sit above the canvas and dim the real globe
too. **Hubs, arcs and sweeps are deliberately not mirrored**: a reflection of a
glow is a smear, and doubling every additive element is what turned this scene
into a white disc the first time.

## What was refused, and why

The reference's stats row reads **"500+ CA Firms · 10M+ Documents Processed ·
99.9% Uptime · 4.8/5 Customer Rating"**. Not one is true: there are no
customers, nothing measures uptime, there is no status page or SLA, and there
are no ratings. §16 rules out unverified claims, and the guard already forbade
"Trusted by Growing Practices" from the *first* reference for the same reason.

The row keeps the shape — it is good composition and the hero was thin without
it — and takes the four figures the page already states further down, each
countable in this repository. A number that appears twice on one page had better
agree with itself.

`FORBIDDEN` gained four entries written as the **claim** rather than the four
literals, because the onboarding-speed entry already taught that a literal bans
only its own spelling: any customer count, any uptime percentage, any star
rating, any processed-document volume. Checked both ways — all four reference
strings caught, none of the honest figures touched.

Also refused: the reference's **search icon** in the nav. There is no site
search, and a control that does nothing is worse than no control.

## And the scan that fired on its own explanation

Adding those entries made five tests fail — on the comment in `Hero.tsx`
explaining why the strings are banned.

Every scan in the guard file skipped comments by asking whether a line *started*
with `//`, `*` or `/*`. A multi-line JSX comment has continuation lines that
begin with ordinary words, so they were read as shipped copy. The hole had been
there since the file was written; it only surfaced when a comment first needed
to quote something forbidden.

`_live_lines` blanks comment spans while preserving line numbers, and every scan
goes through it. `://` is excluded, or the `//` in each https URL would blank the
rest of its line — and one scan looks for a path inside a URL. Two tests hold it:
one on the stripper directly, one confirming the three banned strings are still
caught when they appear in live markup rather than in a comment.

## Fitting above the fold

The stats row pushed the hero past the viewport — measured at 46px over at
1440×900 and 150px over at 1366×768. Rather than drop the row, the vertical
rhythm was tightened and the headline reduced about 20%: now −84px at 1440×900,
−23px at 800-tall, and 2px at 1366×768.

---

# Addendum 3 — the hero globe, rebuilt static (17 September 2026)

A third brief, and this one is about one element only:

> "I want to work ONLY on the HERO GLOBE right now. Do not modify the rest of
> the website."
>
> "Study the reference carefully and recreate the globe as a high-quality static
> 3D/WebGL-style visual first. IMPORTANT: Do NOT make it interactive or animated
> yet … First we need to get the STATIC visual looking exceptional."
>
> "The current globe is too small and too flat. Do not solve this simply by
> increasing its CSS width. The actual visual complexity and depth need to
> increase."

Both halves of that are structural, so both were answered structurally rather
than by tuning colours.

## The scene is drawn ONCE, and that is what pays for everything else

There is no `requestAnimationFrame` loop in `HeroGlobe.tsx` any more. `draw()`
renders a single frame and runs again only when the stage resizes.

That is not a lesser version of the animated scene — it is the budget that
everything below is bought with. The previous revision was redrawing thirty
times a second on integrated GPUs, and every decision in it was shaped by fill
rate:

| | before | after |
|---|---|---|
| device pixel ratio | capped at **1.25** | capped at **2** |
| land points | ~26,000 | ~38,000 |
| orbital paths | 4 torus rings, 128 segments | 7 tube ellipses, 240 segments |
| surface network | none | ~50 nodes, ~80 great-circle links |
| star field / motes | 190 drifting points | 460 + 150, positioned |
| frame budget | 33 ms, scroll-quiet, viewport check | none — it draws once |

The DPR change alone does more for "premium" than any amount of colour work: at
1.25 the one-pixel city lights were being resampled and the continents read as
a smear.

**Every animatable thing is still parameterised by time.** `uTime` stays on the
arc, hub and orbit materials, and each already produces a fixed, varied state at
t = 0 — a head parked partway along each arc, twenty hubs at twenty
brightnesses, each orbit's bright stretch somewhere different. Animation is
"advance the uniforms and call `draw()`" in a rAF; the look does not have to be
rebuilt for it, which is what the brief asked to be left possible.

**And a scene with no loop cannot repair a lost WebGL context**, which an
animated one does for free on its next frame. The buffers go with the context so
there is nothing to redraw; `webglcontextlost` uncovers the SVG globe that has
been sitting underneath all along. A `ResizeObserver` on the stage went in for
the mirror-image reason: without a loop, that observer and the window listener
are the *only* things that will ever draw a second frame, and a grid cell can
change width from a late font metric with no window event at all.

## 81% wider, and the width is the smallest part of it

`CAMERA_Z` went from 5.05 to 4.3. A sphere of radius r at distance d projects to
a circle whose radius, as a fraction of half the canvas height, is
`(r / sqrt(d² - r²)) / tan(fov/2)` — 0.55 before, **0.657** now.

The rest came from the canvas rather than from the grid. **The globe's canvas is
hung outside its cell**: 132% of the stage's width and 136% of its height,
offset by half the overhang so the planet stays centred on the cell. The grid
column is still `minmax(0, 640px)`, every card anchor is still a percentage of
it, and `MAX_RIGHT_ANCHOR` / `MIN_LEFT_ANCHOR` are still derived from that 640 —
so the brief's "may extend beyond the normal boundaries of the hero composition
slightly" cost the hero's layout nothing. What spills over is the atmosphere,
the outer orbits and the star field, and the section is `overflow-hidden`.

`Hero.tsx` changed by one number: `min(80vh, 640px)` → `min(84vh, 720px)`. That
is the whole of the diff to the hero's own layout, which was the constraint.

Net: **355 → 643 CSS pixels** of planet. The camera accounts for a fifth of
that (0.555 of the canvas height to 0.657); the oversized canvas is the rest.

## What made it stop being flat

Six things, none of them a colour tweak:

1. **The palette inverted.** The world is cool blue and white; gold is confined
   to India and its neighbourhood. The previous revision had it the other way
   round, which made a warm planet under cool orbits — attractive, and not what
   this brief asks for.
2. **Coastlines are detected from the mask** (four probes per land cell) and
   drawn brighter and larger than inland. A continent is recognised by its
   *edge*; a uniform fill at the same value as its outline is a blob with a
   shape.
3. **Density varies.** A smooth field over the sphere decides whether a land
   cell is lit at all, so the Sahara, the Amazon and Siberia are sparse and the
   coasts are dense. Drawing every land cell is the single thing that makes a
   masked point field read as a stencil.
4. **A global surface network** — nodes on land, linked to their nearest
   neighbours by fine great-circle lines, cool and faint. This one is the
   brief's own argument: India "should naturally emerge from the Earth's
   network/light structure", and it cannot emerge from a structure that only
   exists over India, which is all the previous scene had.
5. **The orbits are ellipses** with their own inclinations, eccentricities and
   centre offsets, each knowing whether it is passing in front of the planet or
   behind it, each with a bright stretch and a faint one, each fading out before
   the canvas edge rather than being guillotined by it.
6. **Three real depth layers** — a star slab and a nebula wash behind, the
   orbits and motes in the middle, the Earth and its atmosphere in front — with
   `renderOrder` set explicitly, because Three sorts transparents by object
   centre and the planet, the orbits and the sprites all share one.

## Four things that were wrong on the way, and only one of them was visible

**The atmosphere was a hoop.** The alpha ran `band × intensity × (1 + lit × 1.2)`,
so the shaded side's rim was at full strength and the ring was the brightest
thing in the frame all the way round. The floor is 0.45 now and the lit
multiplier 1.7 — a lit atmosphere is nearly invisible on the night side and
fierce on the day side, and that ratio is the whole difference between a limb
and a band bolted to the planet.

**Two edge-on orbits both ran horizontal**, and stacked across the middle of the
planet — which is where the control node is — they drew a clean X over it. An
orbit's screen angle is set by its normal after the Y then X rotations, so the
fix is in `ry`; `rz` turns the ellipse inside its own plane, which does nothing
at all to a near-circle.

**The Fibonacci lattice was visible.** At this density the spiral showed as fine
diagonal pinstripes across Europe and Russia — the one thing that says
"generated" about an otherwise photographic field. Each point is now jittered by
under half a lattice spacing, *after* the mask test so the land decision is
still made at the lattice point. The first attempt used a whole spacing and
killed the coastlines with the pattern.

**And the silent one: `opacity` on a card's positioning element kills its
glass.** An element with opacity below 1 is a *backdrop root*, so
`backdrop-filter` on anything inside it samples that element's own contents
instead of the page — the card renders as a flat translucent rectangle with no
blur, and there is no warning, no failed style and nothing in a computed-style
dump that says so. It is also the first thing anyone reaches for to express
depth. Depth is expressed in the card's own colours instead — fill, border, blur
radius, shadow and text contrast — which is the truer cue anyway: something
further away is lower in *contrast*, not see-through.

## Measured, not eyeballed

An overlap harness drives the built site at 1024, 1280, 1366, 1440, 1600 and
1920, and reports every pair of hero elements closer than the 12px `.floaty` bob
can survive — cards, interface fragments, the vertical rail, the tagline and the
copy column. It found four real collisions this brief introduced:

- **Payroll landed inside the vertical rail** at 1280 and 1440. The rail is
  viewport-centred, so it sits in the same band as the middle of the globe; the
  right-hand column now avoids roughly 36-61% of the stage height.
- **A 62×76 document-sheet fragment had nowhere to go.** Measured at every
  position on both sides, it fouled Payroll, the rail, or both. A document reads
  as a document from three ruled lines and a highlighted one; the page around
  them was what needed the room, so it is 78×26 now.
- The sparkline and the gauge each sat under a card.

## What was refused

**The reflection is gone, and that is a decision.** The previous revision
mirrored the land field below the south pole, because the reference it was
copying stood the globe on a dark surface and the owner asked for it by name.
This brief replaces that reference with a *space* composition — "deep navy/black
atmospheric space", three depth layers, orbits passing behind and in front — and
a floor reflection contradicts it. At this size it would also be clipped to a
56px sliver by the bottom of the stage. Restoring it is a mirrored group and a
fade window; it is left out rather than lost, and the shader still carries the
`uFadeFrom`/`uFadeTo` window it needs.

**The card scale never exceeds 1.** Both anchor limits are derived from a card's
own width, and a card scaled above 1 grows past its anchor in both directions
and silently invalidates them. Depth works downward from full size.

**`GLOBE_RX` is deliberately understated.** The connector SVG's viewBox is a
unit square stretched over the stage, so the planet's radius in x depends on the
stage's aspect — about 41% of the width on a short laptop, 50% on a tall
monitor. Taking the short end lands every data line further *inside* the
planet's face; taking the tall end would put an endpoint past the limb on
exactly the screens where the stage is shortest.

**Nothing else on the site was touched.** No navigation, no other section, no
new section, and no hero typography: the rotating word, the fixed line beneath
it, the standfirst, the buttons, the chips and the four figures are all exactly
as they were.

## Guards added

| Test | What it catches |
|---|---|
| `test_a_card_that_bobs_is_not_inside_something_with_an_opacity` | a backdrop-filtered card inside an `opacity` ancestor — the glass dies with no error anywhere. Walks the div/span tree and asserts both vacuity directions: that it saw a backdrop filter at all, and that its stack balanced |
| `test_the_globe_canvas_is_larger_than_the_cell_it_is_given` | the canvas oversize being "tidied" back to `inset-0`, which costs the planet a third of its diameter, changes no anchor, breaks no layout and produces no error |

Both were negative-controlled: restoring the `opacity`, shrinking the canvas to
100%, unbalancing the tree and off-centring the offset each fail the intended
test and only that test.

---

# Addendum 4 — the hero globe against a reference (17 September 2026, later)

A reference image this time, and a twenty-point brief with it. The owner's
verdict on Addendum 3's globe, in its own words: *"The current globe looks like
a flat dotted world map wrapped onto a sphere"*, *"oversized and visually
heavy"*, and the tick *"a giant checkmark sitting on top of the Earth"*.

All three are right, and the first one is the one that matters.

## The Earth is a shaded planet now, not a dark ball with dots on it

The reference shows Africa, Arabia, India and Australia as **landmass** — a
dark blue-grey fill against a near-black ocean, shaded by the light and
darkened toward the limb — with the lights on top of that. Addendum 3 drew a
radial-gradient sphere and let the dots imply the continents. However dense the
dots, that reads as a stencil.

So the core shader samples the land mask as a **texture**. `buildLandTexture`
renders the same 0.5-degree bitmask the point field walks into a canvas — one
pixel per cell, row 0 at +90, column 0 at −180 — upscaled 2× with bilinear
smoothing and a canvas blur so a coastline is an edge rather than a staircase.
Three's `SphereGeometry` lays its UVs out exactly that way (u is
(lon + 180) / 360, and because it pushes `1 − v`, the image's top row is the
north pole), so the fill and the lights cannot disagree about where a coastline
is. Four terms in the fragment, in order: the land/ocean mix; the terminator;
limb darkening; and a fresnel rim *added* on top, brighter on the lit side —
the planet's own blue edge before the atmosphere shell adds the glow outside it.

With the fill carrying the shape, the dots stop having to. **200,000 candidates
→ 160,000**, and each surviving point now has its own brightness (0.55–1.0),
its own size (0.55–1.45×) and a ~3% chance of being a **beacon** — larger,
near-white, the thing the eye reads as a city rather than as texture. The
brief: *"avoid making every dot identical."*

## The network is the nervous system, so it has more than fifty neurons

Addendum 3's surface mesh was ~50 nodes and ~80 links, and it was invisible
under the lights. The reference's mesh is one of its strongest elements. Now
5.2° apart with three links each — roughly a hundred nodes, two hundred links,
still one `LineSegments` draw call.

## Smaller, and the size is arithmetic

`CAMERA_Z` 4.3 → **5.3**: 0.657 → 0.528 of the canvas height, which on the
hero's stage is **643 → 517 CSS pixels**. That is 72% of the right half's width
and 57% of the viewport height at 1440×900 — inside the brief's *"55–65% of
the right-side visual area"* — with room around it for the system it is
supposed to be the centre of. `GLOBE_RX`/`GLOBE_RY` re-derived (33 / 35.9).

## Three kinds of orbit and a fourth depth layer

The reference draws several of its paths as **chains of dots**, one of them
warm. `OrbitDef` gained `kind: "solid" | "dotted"`; a dotted orbit is a `Points`
object sampled along the same ellipse, each point with its own size and
brightness, the far half dimmed by depth the same way the tubes are. Seven
orbits: four solid, three dotted, one of those gold.

And `FAR_ORBITS` — the brief's *"Layer 2 — far network: small orbital paths and
distant data points, low brightness"*, which Addendum 3 did not have. Three
large dim orbits whose **centres sit behind the planet** (oz −1.15 to −1.6), so
the disc hides the middle of each and only the outer sweep shows, plus 110 dim
points in the space behind. They are what makes the layer read as *far* rather
than merely faint.

## The tick is a core, not a mechanism

Addendum 3's housing was 124px with a 36-graduation ring, two bright arcs and
four registration ticks — at the middle of the frame, the first thing the eye
landed on. The brief: *"The viewer's first impression should be 'What is this
incredible digital system?' not 'There is a checkmark in the middle.'"*

Now: a 40px badge, one hairline ring at 9% and one dashed ring at 17%, both far
below the brightness of anything on the planet. It is there when looked for.
The mark itself is unchanged.

## Cards and fragments

Cards moved to an organic set — AI assistant to bottom-centre overlapping the
planet's lower limb, Compliance and Clients overlapping its left edge — and the
glass gained what the reference's has: a bright hairline along the **top edge**
(`inset 0 1px 0`) and a soft blue glow standing off the card, both scaling with
depth. Accounting's line is the brief's own: *"A ledger that looks ahead."*

Fragments: four → seven, all at 40%, several **over the planet's face** as the
reference's are. **The gauge is gone** — a ring inside a ring with a dot in the
middle is the exact thing the brief names as clutter (*"decorative circles
inside circles"*); a three-line data block took its place. A `Sheet` helper
draws the document shape at any size so the markup is not repeated.

## Measured

The overlap harness found four near-misses on the new layout, each 1–5px short
of the 26px bob clearance (Accounting × sheet, Banking × bars, Clients × doc,
and AI assistant × the tagline at 1280×800). Sheet to the very top, doc up 1%,
Banking down 2%, AI assistant up 2%. All six widths clear.

## Not done, and said so

**React Three Fiber + Drei.** The brief prefers them *"if compatible with the
existing project."* The project vendors `three.min.js` r128 and has no R3F; the
scene is already a single static frame with explicit `renderOrder` and shader
materials, which is the part R3F would abstract. Adding a dependency and a
component model for the same pixels is a refactor with no visual outcome, so it
is left for the interactive stage, if it earns its place there.

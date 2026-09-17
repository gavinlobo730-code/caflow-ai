"use client";

import { RotatingWord, HERO_WORDS } from "./RotatingWord";
import { Magnetic } from "../Cursor";
import { ArrowRight } from "../icons";
import { Parallax } from "../motion";

/**
 * THE HERO'S EARTH IS ARTWORK, NOT CODE, AND THAT IS AN OWNER DECISION.
 *
 * Three passes tried to build this scene in the browser — a dotted globe, a
 * shaded planet, then a WebGL night Earth generated from a coastline mask and
 * a table of world cities. The owner reviewed the last one on a deploy
 * preview and it was still not the thing they had in mind, so on 17-09-2026
 * they supplied the finished artwork and the instruction was explicit: *"This
 * is a static image, not something to draw with code ... Do not attempt to
 * recreate the globe, city lights, starfield, or card artwork with SVG,
 * Canvas, or CSS shapes."*
 *
 * So `components/home/hero/` is gone — ten modules, and with it the vendored
 * three.min.js, the lazy loader, the Natural Earth coastline mask and its
 * generator, since nothing imported any of them once the scene went. 3,365
 * lines. It is all in git at e566d9f5 if the animated version is ever wanted.
 *
 * WHAT IS IN THE IMAGE AND WHAT IS NOT. The artwork carries the Earth, the
 * network, the orbits, the starfield, the asteroids, the moon AND the eight
 * capability cards — all baked in. Everything textual stays real HTML on top:
 * the eyebrow, the rotating word, the headline, the paragraph, both calls to
 * action, the trust chips and the figures. None of that is in the image, so it
 * is still selectable, still scales with the type system, still translatable
 * and still read by a screen reader.
 *
 * ⚠️ THE CARDS ARE NO LONGER TEXT, and that is the one real cost of this
 * approach rather than a detail. "Compliance", "Payroll", "AI assistant" and
 * the five others are pixels now: a screen reader cannot read them, they do
 * not reflow, and they cannot be translated. The image therefore carries an
 * `alt` that NAMES all eight in order, which is the only way that content
 * reaches assistive technology at all. If those labels ever change, the
 * artwork has to be re-exported — they cannot be edited here.
 */
const ARTWORK = "/hero/earth-network.webp";

/**
 * The deep-space field that carries the artwork across the rest of the hero.
 *
 * DERIVED FROM `ARTWORK`, not drawn: `scripts/build-space-field.py` cuts the
 * artwork's own stars out of its cleanest deep-space tiles and re-scatters
 * them, so the left of the hero is the same picture's sky rather than a
 * starfield somebody generated. Purely decorative — it carries no content, so
 * unlike the artwork it takes an empty `alt`.
 *
 * Re-run that script if the artwork is ever re-exported; the stars come from
 * it.
 */
const STARS = "/hero/space-field.webp";

/**
 * The eight modules the artwork has baked into it, in reading order.
 *
 * Kept as a list rather than written into one long string so that it is
 * obvious this is content the image is carrying, and so a future change has
 * one place to make it.
 */
const ARTWORK_CARDS = [
  "Compliance — GST, TDS, ITR and ROC",
  "Clients — every entity, one record",
  "Practice analytics — the whole firm at a glance",
  "Banking — statements become vouchers",
  "Accounting — a ledger that looks ahead",
  "Payroll — salary, PF, ESI and TDS",
  "Documents — read by AI, checked by you",
  "AI assistant — it knows your practice",
];

/**
 * The hero.
 *
 * Copy is the brief's own (§2), verbatim where it specifies wording: the
 * eyebrow, the rotating keyword, the fixed line beneath it, the supporting
 * paragraph and both calls to action.
 *
 * THE TRUST CHIPS ARE NOT THE REFERENCE IMAGE'S. That image shows "Built for CA
 * Firms · Secure & Compliant · Trusted by Growing Practices", and the last two
 * cannot ship: there are no customers to be trusted by and no certification
 * behind "compliant". §16 forbids inventing either. What is here instead are
 * three facts — the trial takes no card, Supabase runs in ap-south-1, and the
 * software genuinely never transmits a return to a government portal.
 *
 * THE HEADLINE IS ONE <h1> AND A SCREEN READER GETS IT WHOLE. The rotating word
 * is aria-hidden and a visually-hidden sentence carries the real text, so
 * assistive technology reads a fixed headline rather than a word that changes
 * underneath it mid-sentence.
 */
/**
 * The hero's four figures.
 *
 * Every one is countable in this repository — the module directories, the tools
 * the product replaces, the confirmation step in front of every filing, and the
 * statutory domains it computes. Deliberately the same four the "Control &
 * trust" panel states further down the page: a figure that appears twice had
 * better agree with itself.
 */
const HERO_FACTS = [
  { value: "11+", label: "Modules, one connected workspace" },
  { value: "4", label: "Separate tools replaced by one login" },
  { value: "100%", label: "Filings reviewed by a CA before submit" },
  { value: "4", label: "Compliance domains — GST, ITR, TDS, MCA" },
];

export function Hero() {
  return (
    <section
      className="relative flex min-h-screen flex-col justify-center overflow-hidden text-white"
      /*
        THE HERO'S BACKGROUND IS THE ARTWORK'S OWN EDGE COLOUR, MEASURED, AND
        IT IS DELIBERATELY NOT `bg-brand-dark`.

        The brief asks that "the section's background color is a plain dark
        navy/black behind it so the fade blends cleanly", and this is that
        requirement met exactly rather than approximately. The artwork is
        letterboxed — it is 1117x853 shown at 66% of the viewport width, so at
        1440x900 it is 950x726 with 87px of section showing above and below —
        and its top, bottom and right edges are OPAQUE. So wherever the
        section's colour differs from the artwork's border, that difference
        draws a hard line.

        It did. `brand-dark` is #0D1635 and the artwork's opaque border has a
        median of #010918, which put a visible horizontal edge across the hero
        at the top of the image. Sampled rather than guessed: top row mean
        rgb(4,14,33), bottom row (5,13,29), right column (1,7,19).

        The token itself is left alone. `brand-dark` is shared by the header,
        the footer, the demo form, the cinematic panels and the access page,
        and recolouring it to suit one image would restyle the site — which the
        brief forbids. So the colour lives here, on the one section that needs
        to disappear behind a specific asset.
      */
      /*
        AND THE TWO GRADIENTS ARE THE COLOUR OF SPACE ON THE HALF THE ARTWORK
        DOES NOT REACH.

        Owner review, 17-09-2026: *"can we you know create the background image
        a bit more universy like see the image is already right but only the
        right side it is but the left is blank so i was thinking that the whole
        screen gets that look"*, then, on scope: *"there should be only one
        page and the page with the hero that is the original page"* — this
        section, not the site.

        BOTH COLOURS ARE MEASURED OFF THE ARTWORK rather than picked: #0c254b
        is the mean of its own pixels in the 26-46 luminance band, its haze,
        and #010817 the mean below 14, its deep space, which is the #010918
        this section already carried. So the left half is lit in the picture's
        own palette and reads as the same photograph continuing, not as a
        tinted panel beside it.

        WHY A GRADIENT AND NOT MORE IMAGE. Two attempts put this wash in the
        asset, derived from the artwork as a tiny flipped thumbnail — see
        `scripts/build-space-field.py`, which records both. The first kept
        enough of the artwork's bright limb to read as a galaxy arm, which §12
        prohibits outright; the second was structureless and then BANDED into
        concentric rings, because a smooth gradient at that strength spans
        about twenty of the 256 levels 8-bit gives you. Dithering fixed the
        rings and multiplied the file by ten. The browser renders a gradient at
        higher precision than the file format can hold, so it simply does not
        band, and it weighs nothing. It is also not one of the four things the
        brief says not to recreate — the globe, the city lights, the starfield
        and the cards are all still the owner's own pixels.

        Sized in PERCENTAGES, so the wash is a proportion of the hero at every
        width; a px-sized ellipse is most of a phone and a corner of a 27-inch
        monitor. Off-centre and of two different sizes because one centred
        ellipse reads as a vignette.
      */
      style={{
        backgroundColor: "#010918",
        backgroundImage: [
          "radial-gradient(115% 95% at 20% 36%, rgba(12,37,75,0.50), rgba(12,37,75,0) 68%)",
          "radial-gradient(85% 70% at 46% 88%, rgba(12,37,75,0.30), rgba(12,37,75,0) 72%)",
        ].join(","),
        boxShadow: "inset 0 0 180px rgba(0,0,0,0.4)",
      }}
    >
      {/*
        ── The stars ──────────────────────────────────────────────────────────

        EVERY STAR HERE IS ONE OF THE ARTWORK'S OWN, MOVED.
        `scripts/build-space-field.py` cuts them out of the artwork's cleanest
        deep-space tiles and scatters them at new positions under a fixed seed,
        which is the one way to extend the picture leftwards without either
        drawing a starfield in code (§23 of the brief forbids it by name) or
        mirroring a patch, which the eye catches immediately because repeated
        constellations are the easiest pattern there is to see.

        BEFORE the artwork in the DOM and at the same z-index, so it paints
        underneath: the artwork is the subject and this is the room it is in.

        `object-cover` with `object-left`. On a box wider than 16:9 cover
        scales by width and the horizontal anchor does not matter; on a
        narrower one it scales by height and crops WIDTH, and anchoring left
        keeps the populated side and throws away the faded side rather than the
        other way round. The asset's own alpha already fades it out before the
        artwork's opaque half begins, so the two star populations never overlap
        and there is no density step down the middle of the hero.
      */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={STARS}
          alt=""
          width={1920}
          height={1080}
          loading="eager"
          decoding="async"
          className="h-full w-full object-cover object-left"
        />
      </div>

      {/* The 460px watermark "01" that used to sit here is gone, with the rest
          of the panel numerals — owner review, 16-09-2026: "the 01 and the
          numbering in the big light on all pages they also dont look asthetic".
          Section numbering now lives in SerifHeading's `index`, at 13px. */}

      {/*
        ── The artwork ────────────────────────────────────────────────────────

        A DIRECT CHILD OF THE SECTION, not of the grid, and that is the whole
        reason this is positioned here rather than inside a component in the
        right-hand cell. The brief asks for it on "the right ~65-70% of the
        hero section, bleeding off the right edge, vertically centered" —
        against the SECTION. The grid container below is itself `relative` and
        is capped at max-w-[1320px] with responsive padding, so anything
        absolutely positioned inside it measures against that padded box and
        stops short of the viewport edge. There would be no bleed.

        NO GRADIENT, NO MASK, AND NONE IS NEEDED. The artwork's own left edge
        fades out over its first ~200px: measured, alpha 0 at x=0 rising
        linearly to 255 by x=200 of 1117. So the only requirement is that what
        sits behind it is a plain dark field of the same colour, which is why
        the section carries #010918 above. Adding a CSS gradient on top would
        double the fade and show as a band.

        `object-contain` with `object-right`: the container is the full height
        of the hero and 68% of its width, and the image is wider than it is
        tall (1.309), so contain fits it by WIDTH and centres it vertically —
        which is exactly the brief's "vertically centered" without a magic
        offset. Right-anchored so its own right edge stays flush as the
        viewport changes shape.

        ⚠️ 62%, NOT THE BRIEF'S 65-70%, AND THE THREE POINTS ARE A REAL
        TRADE-OFF RATHER THAN A ROUNDING.

        The artwork's own Clients and Practice analytics cards sit at its far
        left, INSIDE its fade, and they are pixels: they cannot be nudged.
        Where exactly they start is measured on the RENDER rather than on the
        asset, and the difference mattered — see the copy column's note below,
        which records the collisions that reached production because this
        figure was first derived from the asset's alpha instead.

        Re-tested at 66% and 68% once the copy stopped drifting: both collide,
        at five and six widths respectively, and in both cases the failures are
        at the LAPTOP end (1039-1600) rather than on a wide screen. The
        constraint is not the wide monitor and it is not the image — it is that
        the hero's EXISTING type is larger relative to the viewport than the
        type in the reference composition, where the eyebrow occupies 26% of
        the width against 35% here. The brief says not to redesign the hero
        typography, and of the two instructions the one that cannot be broken
        silently is the collision: overlapping text is a defect at any size,
        three percentage points is not.

        If the artwork should be bigger, the copy has to be smaller — that is
        one max-width change away and is an owner call, not something to
        decide here.

        AND IT STOPS GROWING AT 1400px, WHICH IS NOW ABOUT HEIGHT RATHER THAN
        WIDTH. The cap was added when the copy still centred and the two edges
        converged; the copy is anchored now, so on the horizontal axis the
        clearance only ever grows. What the cap still earns is the vertical: at
        3440 an uncapped artwork is 1622px tall inside a 1440px viewport and
        crops its own top and bottom. 1400px keeps the height under 1070px, so
        it fits a 1080p screen whole, and beyond that the hero reads as a
        capped composition on a dark field — which is what the rest of the page
        already does.

        On mobile it sits across the bottom instead, under the stacked copy,
        which is where the visual has always been below `lg`.
      */}
      <div
        aria-hidden="false"
        className="pointer-events-none absolute inset-x-0 bottom-0 z-0 lg:inset-x-auto lg:bottom-auto lg:right-0 lg:top-1/2 lg:w-[62%] lg:max-w-[1400px] lg:-translate-y-1/2"
      >
        {/*
          A plain <img>, deliberately. next/image earns its place by resizing
          and reformatting at request time, and this project is `output:
          "export"` with `images.unoptimized` already set — so next/image here
          is a wrapper that emits the same tag with extra client JS. One
          artwork, one format, already compressed to 186KB.

          Eager and high priority: it is the largest thing above the fold, so
          it IS the Largest Contentful Paint. Lazy-loading it would delay the
          only image that matters.
        */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={ARTWORK}
          alt={
            "An illuminated night-time Earth centred on India, wrapped in a " +
            "network of data links and orbital paths, with eight floating " +
            "panels naming the platform's modules: " +
            ARTWORK_CARDS.join("; ") +
            "."
          }
          width={1117}
          height={853}
          loading="eager"
          fetchPriority="high"
          decoding="async"
          className="block h-auto w-full"
          /*
            A SHORT FADE ON THE TOP AND BOTTOM EDGES ONLY, and this is the one
            place the brief's "no extra gradient/mask needed" does not apply —
            because that sentence is about the LEFT edge, which the artwork
            already fades for itself.

            The top and bottom are a different problem and they come from
            letterboxing. The image is shown at 62% of the viewport width with
            its natural 1.309 aspect, so at 1440x900 it is 893x682 with 109px
            of section above and below it — and its own top and bottom rows are
            OPAQUE. No single background colour can hide that, because the
            artwork's top edge is not one colour: it carries the moon's glow
            and a faint nebula. Measured on the render, the boundary stepped
            from rgb(0,8,23) to rgb(16,27,46) — a line right across the hero.

            7% of the height at each end, which is about 48px: enough to
            dissolve the edge, short enough that it only touches the outermost
            orbital arcs and the dark space above the asteroids. Left and right
            are deliberately untouched — left is the artwork's own fade and
            right is meant to bleed.
          */
          style={{
            maskImage:
              "linear-gradient(to bottom, transparent 0%, #000 7%, #000 93%, transparent 100%)",
            WebkitMaskImage:
              "linear-gradient(to bottom, transparent 0%, #000 7%, #000 93%, transparent 100%)",
          }}
        />
      </div>

      {/*
        ── The copy, ANCHORED LEFT RATHER THAN CENTRED ────────────────────────

        THE HERO IS THE ONE SECTION THAT MUST NOT USE A CENTRED CONTAINER, and
        the reason is the artwork beside it. Every other section on this site
        sits in a column that is capped and then centred, so its left gutter
        grows by half of every pixel added to the window. The artwork is pinned
        to the VIEWPORT's right edge and grows at 62% of it. Two things
        measured from different origins, advancing at different rates: they
        converge, and then they overlap.

        Owner review, 17-09-2026: *"will you be able to see the headlines and
        all move to the left as it looks odd right as the globe is on extreme
        right it doesnt look aligned"*. Measured on the shipped page, the copy's
        left gutter was 72px at 1280, 125 at 1440, 205 at 1600 and 365 at 1920
        while the artwork's right gutter stayed 0 at every one of them.

        ⚠️ IT WAS NOT ONLY A COMPOSITION PROBLEM — TEXT WAS ON THE ARTWORK.
        `tests/…/collide` harness (scratch): with the copy column hidden so
        every bright pixel belongs to the image, the supporting paragraph
        overlapped visible artwork at 1366, 1440, 1600 and 1920, and at 1920 so
        did the rotating word, the second headline line and a trust figure.
        Those are the four commonest desktop widths there are. The 62% ceiling
        derived when the artwork landed was computed from the asset's first
        NEAR-OPAQUE card body at x=157 of 1117 (14.1%) — which is a real
        measurement of the wrong thing, because the cards' outer glow and the
        Practice analytics card's leading edge are visible well before they are
        opaque, from about 9% of the width. Arithmetic on the asset cannot see
        that; a render can.

        So: no `mx-auto`, no cap, and a fixed 72px gutter from `lg` up, which
        is the same clamp the padding already used — the copy simply stops
        drifting. Clearance to the artwork goes from +45/+40/+29px at
        1440/1600/1920 to +104/+129/+278, and the harness reports no text over
        artwork at 1039, 1100, 1280, 1366, 1440, 1600, 1920, 2560 or 3440.

        THE COPY COLUMN IS CAPPED SO THE FIX CANNOT UNDO ITSELF. With the
        container uncapped, `1fr` would hand the copy the whole viewport and the
        headline would run back under the planet, so the column takes
        `clamp(330px,34vw,540px)`: 484px at 1440 against the 496px it had
        before, so nothing re-wraps, and it stops growing at 1585px where the
        artwork is still advancing. The 34vw middle term is what keeps the
        laptop widths clear — a flat 540px collides at 1039.

        AND IT IS 62%, STILL. Raising the artwork to the brief's 65-70% was
        re-tested now that the copy has moved, since more clearance was the
        whole point: 66% collides at five widths and 68% at six, both from
        1039 up to 1440-1600. The ceiling is the laptop, not the wide screen.

        ⚠️ THE HEADLINE NO LONGER LINES UP WITH THE NAV LOGO, and that is a
        deliberate trade rather than an oversight. `container-ps` caps the
        header at 1200px and centres it, so the logo also drifts — 137px at
        1440, 377 at 1920 — and by coincidence of those two numbers it used to
        track the hero copy within 12px. It cannot track it and stop drifting
        at the same time. Aligning them would mean either re-centring the hero
        (which is the defect) or moving the header's own container, which is
        shared by every page and would then sit 164px left of all six pages'
        content. The nav is a bar with its own bounding box and the brief says
        not to redesign it, so the hero goes full-bleed and the header stays.
      */}
      <div className="relative z-[1] mx-auto grid w-full max-w-[1320px] items-center gap-12 px-[clamp(20px,6vw,72px)] pb-14 pt-[clamp(88px,11vh,132px)] lg:mx-0 lg:max-w-none lg:grid-cols-[minmax(0,clamp(330px,34vw,540px))_minmax(0,1fr)] lg:gap-10">
        {/* ── Copy ──────────────────────────────────────────────────────── */}
        <div>
          <Parallax speed={0.05}>
            <p className="text-[12px] font-semibold uppercase leading-none tracking-[0.18em] text-white/55">
              The AI-first platform for Indian CA firms
            </p>
          </Parallax>

          <h1 className="mt-7">
            <span className="sr-only">
              {HERO_WORDS.join(" ")} Run your entire practice on one intelligent platform.
            </span>
            <span
              aria-hidden="true"
              className="block font-display italic leading-[0.96] tracking-[-0.02em] text-[clamp(46px,7.6vw,112px)]"
            >
              <RotatingWord />
            </span>
            <span
              aria-hidden="true"
              className="mt-3 block max-w-[17ch] font-display leading-[1.05] tracking-[-0.015em] text-[clamp(28px,3.9vw,54px)]"
            >
              Run your entire practice on one intelligent platform.
            </span>
          </h1>

          <p className="mt-6 max-w-[48ch] text-[16.5px] leading-[1.65] text-slate-300">
            From clients and compliance to accounts and advisory — PracticeSync brings
            everything together, so you can focus on what truly matters.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-6">
            <Magnetic max={10}>
              <a
                href="/demo"
                className="btn-shine inline-flex items-center gap-2 rounded-lg bg-[#5876c7] px-7 py-[15px] text-[14px] font-semibold leading-none text-white transition-colors hover:bg-[#4d68af]"
              >
                Book a demo
                <ArrowRight size={16} />
              </a>
            </Magnetic>
            <a
              href="/products"
              className="inline-flex items-center gap-2 border-b border-white/40 pb-1 text-[14px] font-semibold leading-none text-white/85 transition-colors hover:border-white hover:text-white"
            >
              Explore products
              <ArrowRight size={14} />
            </a>
          </div>

          <ul className="mt-8 flex flex-wrap gap-x-7 gap-y-3 text-[12.5px] font-medium leading-none text-white/45">
            <li>No credit card needed</li>
            <li>Data hosted in India</li>
            <li>Nothing filed without your click</li>
          </ul>

          {/* THE FIGURES ARE THE PRODUCT'S, NOT A CUSTOMER BASE'S.

              The reference image this composition follows carries a stats row
              reading "500+ CA Firms · 10M+ Documents Processed · 99.9% Uptime ·
              4.8/5 Customer Rating". Not one of those can ship: there are no
              customers, nothing has measured uptime, and there are no ratings.
              §16 of the brief rules out unverified claims, and
              test_the_marketing_site_says_what_the_product_does.py already
              forbids "Trusted by Growing Practices" from the same image for the
              same reason.

              So the row keeps the SHAPE — it is good composition, and the hero
              was thin without it — and takes figures that are facts about the
              software, each one countable in this repository. They are the same
              four the page already states further down, which is deliberate: a
              number that appears twice on one page had better agree with
              itself. */}
          <dl className="mt-7 grid max-w-[32rem] grid-cols-2 gap-x-8 gap-y-5 border-t border-white/10 pt-6 sm:grid-cols-4 sm:gap-x-5">
            {HERO_FACTS.map((f) => (
              <div key={f.label}>
                <dt className="sr-only">{f.label}</dt>
                <dd className="font-display text-[clamp(22px,2.2vw,29px)] leading-none text-white">
                  {f.value}
                </dd>
                <p className="mt-1.5 text-[11px] leading-[1.4] text-white/45">{f.label}</p>
              </div>
            ))}
          </dl>
        </div>

        {/* ── The space the artwork occupies ─────────────────────────────

            AN EMPTY CELL, ON PURPOSE, AND ITS JOB IS NOW MOBILE-ONLY. The
            artwork is a section-level layer above, so nothing is rendered
            here. On `lg` the track is the `1fr` that soaks up everything the
            capped copy column does not take — it no longer has to hold the
            copy back, because the copy column caps itself; keeping the cell
            costs nothing and removing it would make the grid single-column,
            which changes the mobile stack.

            Below `lg` it IS load-bearing: it is the clearance the artwork
            needs at the bottom of the hero, the height the stacked visual has
            always had. */}
        <div aria-hidden="true" className="h-[300px] lg:h-auto" />
      </div>

      {/*
        THE VERTICAL RAIL AND THE CLOSING TAGLINE ARE GONE, BECAUSE THE ARTWORK
        ALREADY SAYS IT.

        Two decorative text elements used to sit on the right edge of this
        section: a rail reading PEOPLE / DATA / COMPLIANCE / GROWTH / ALL IN
        SYNC, and a closing "SYNC TODAY. A STRONGER TOMORROW." at the bottom
        right. Both were written for a hero whose right half was empty canvas.

        The supplied artwork carries "A STRONGER PRACTICE TOMORROW" baked into
        its own right side, so keeping the HTML versions produced two defects
        at once: the same sentiment stated twice, and the rail rendering
        directly ON TOP of the Payroll card at 1440px, where the image is
        opaque. Neither could be nudged clear — the card is pixels and cannot
        move, and the rail has nowhere left to go.

        So the artwork wins and the markup gives way. Nothing is lost: the
        words are still on the page, they are simply in the image now, and the
        `alt` text names what the image carries.
      */}

      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-9 left-1/2 z-[1] flex -translate-x-1/2 flex-col items-center gap-2.5 opacity-45"
      >
        <span
          className="scroll-cue block h-[38px] w-px bg-current"
          style={{ animation: "ps-bob 2s ease-in-out infinite" }}
        />
        <span className="text-[10px] font-medium leading-none tracking-[0.16em]">SCROLL</span>
      </div>
    </section>
  );
}

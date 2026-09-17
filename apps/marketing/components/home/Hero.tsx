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
      style={{
        backgroundColor: "#010918",
        boxShadow: "inset 0 0 180px rgba(0,0,0,0.4)",
      }}
    >
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
        left, INSIDE its fade — measured, the first near-opaque card body is
        at x=157 of 1117 (14.1% of the width) and the first legible card TEXT
        at x=181 (16.2%). Those cards are pixels: they cannot be nudged.

        With the image right-flush at a fraction f of the viewport, its content
        begins at `V x (1 - 0.859f)`. Setting that against the copy's measured
        right edge at six widths (415px at 1024 through 874px at 1920, the
        widest case being the eyebrow line and the rotating word "Automation.")
        gives a ceiling of 63.8% before card text lands on copy, and 62.2%
        before card bodies do. At the brief's 68% the Practice analytics card
        sat directly on the second line of the paragraph.

        So the constraint is not the image, it is that the hero's EXISTING type
        is larger relative to the viewport than the type in the reference
        composition — where the eyebrow occupies 26% of the width against 35%
        here. The brief also says not to redesign the hero typography, and of
        the two instructions the one that cannot be broken silently is the
        collision: overlapping text is a defect at any size, three percentage
        points is not. Taking 62% keeps the card BODIES clear, not merely
        their text.

        If the artwork should be bigger, the copy has to be smaller — that is
        one max-width change away and is an owner call, not something to
        decide here.

        AND IT STOPS GROWING AT 1400px, because the copy does. The content
        container is capped at max-w-[1320px] and then centres, so past about
        1460px the copy's right edge advances at half the rate the viewport
        does while a percentage-width artwork advances at 62% of it. The two
        therefore converge and cross: measured, the clearance falls from +44px
        at 1440 to +16 at 1920, +7 at 2200 and -5 at 2560 — a collision on an
        ordinary 27-inch monitor. At 3440 the artwork was also 1622px tall in
        a 1440px viewport, cropping its own top and bottom.

        1400px holds the clearance positive at every width tested up to 3440
        and keeps the height under 1070px, so it fits a 1080p screen whole.
        Beyond that the hero reads as a capped composition on a dark field,
        which is what the rest of the page already does.

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

      <div className="relative z-[1] mx-auto grid w-full max-w-[1320px] items-center gap-12 px-[clamp(20px,6vw,72px)] pb-14 pt-[clamp(88px,11vh,132px)] lg:grid-cols-[minmax(0,1fr)_minmax(0,640px)] lg:gap-10">
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

            AN EMPTY CELL, ON PURPOSE. The artwork is a section-level layer
            above, so nothing is rendered here — but the column still has to
            be RESERVED, because it is what keeps the copy in the left half
            where the brief's composition puts it. Deleting the cell would
            widen the copy column to the full 1320px and run the headline and
            the paragraph out under the planet.

            On mobile it becomes the clearance the artwork needs at the bottom
            of the hero, which is the height the stacked visual always had. */}
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

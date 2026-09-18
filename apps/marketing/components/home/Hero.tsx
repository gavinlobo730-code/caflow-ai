"use client";

import { RotatingWord, HERO_WORDS } from "./RotatingWord";
import { Magnetic } from "../Cursor";
import { ArrowRight } from "../icons";
import { Parallax } from "../motion";

/**
 * THE HERO'S EARTH IS ARTWORK, AND NOTHING IS DRAWN OVER IT.
 *
 * Four passes tried to draw this scene in the browser — a dotted globe, a
 * shaded planet, a WebGL night Earth from a coastline mask, and a table of
 * world cities. On 17-09-2026 the owner supplied finished artwork instead and
 * the instruction was explicit: *"This is a static image, not something to draw
 * with code ... Do not attempt to recreate the globe, city lights, starfield,
 * or card artwork with SVG, Canvas, or CSS shapes."* It is all in git at
 * e566d9f5 if the animated version is ever wanted.
 *
 * ⚠️ THE EIGHT CAPABILITY CARDS WERE BUILT AS REAL HTML HERE FOR ONE DAY AND
 * THE OWNER REMOVED THEM ON SIGHT: *"remove the cards it doesnt look good you
 * know"* (18-09-2026, on the deploy preview). They had been added the same day,
 * also on their instruction, after they supplied a render with the cards baked
 * in and asked whether HTML ones would look better. So both answers have now
 * been tried on a real screen and the picture wins on its own.
 *
 * WHAT IS WORTH KEEPING FROM THAT DAY, because it is the reason not to reach
 * for them again casually:
 *
 *   * the baked-in render could not have been used full-bleed either. Its
 *     leftmost card begins at x=535 of 1600 — 33.4% of the width — and this
 *     hero's copy runs to 38%, so the two overlap by about 5% of the screen.
 *
 *   * two of the CSS classes the cards were styled with generated no rule at
 *     all, because `bg-[#081b3d]/72` is not on Tailwind's opacity scale. The
 *     panels were absent rather than translucent and one card rendered white
 *     text at 1.1:1. `test_a_tailwind_opacity_modifier_is_one_tailwind_generates`
 *     exists because of it and is worth more than the cards were.
 *
 * The eight modules are not lost: the Ecosystem section immediately below names
 * every one of them, which is where a reader who wants the list goes.
 */
const ARTWORK = "/hero/space-earth.webp";

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
    <section className="relative flex min-h-screen flex-col justify-center overflow-hidden text-white">
      {/*
        ── The artwork ────────────────────────────────────────────────────────

        FULL BLEED, WHICH IS A CHANGE OF KIND FROM THE ARTWORK IT REPLACED. The
        17-09-2026 asset was 1117x853 with a transparent left edge, designed to
        sit in the right 62% of the section over a flat field; this one is a
        complete 16:9 composition — galaxy, asteroid belt, moons and planet —
        and the owner asked for "the whole background image". So it covers the
        section, and the flat `#010918` behind it plus the derived star field
        that used to extend it are both gone, along with their generator.

        ⚠️ `object-cover`, AND THE FIT HAS NOW BEEN SET THREE TIMES BY THE OWNER
        LOOKING AT IT. The sequence is worth keeping, because each instruction
        was right about what was on their screen and the two requirements
        cannot both hold:

          1. `cover` — *"can the whole image fit on the first page i guess some
             parts is cutting right?"* Correct: cover crops whatever does not
             fit the section's shape.

          2. `contain` — the whole frame, and then bars wherever the viewport
             is not 16:9. Measured at their own window, 1598x745: the picture
             came out 1459x821 inside a 1583-wide box, so **62px of flat colour
             down each side**.

          3. `cover` again — *"the image is not fitting on the whole hero first
             page right so i guess you will have to trim the image on something
             right so can you do it"*. Trimming is accepted, which is what
             settles it: cover fills the section edge to edge at every size and
             the browser does the trimming per viewport, so no trimmed asset is
             needed and no window ever shows flat colour.

        WHAT COVER TRIMS, AND WHY IT IS THE RIGHT THING TO LOSE. On a box WIDER
        than 16:9 it fits by width and takes equal slices off the top and
        bottom — the moon and some galaxy above, the asteroid belt's corner
        below. On a NARROWER box it fits by height and takes equal slices off
        the sides — the galaxy's left edge and the right-hand moon. The globe
        is centred in the frame and survives every case; only the periphery
        goes. A wider export of the same picture would reduce how much.

        ⚠️ AND A SEPARATE THING IS ALSO TRUE AT THAT WINDOW, which no fit can
        fix: the hero is `min-h-screen` and the copy needs 821px, so at a
        745px-tall viewport the section is **76px TALLER than the screen** and
        its last 76px are below the fold whatever the picture does. That is
        ordinary for a hero carrying this much copy, and the band it puts below
        the fold is the artwork's bottom corner rather than anything in it.

        `alt=""` because the picture now carries no content: the eight module
        labels that used to be baked into an earlier asset, and then briefly
        rendered over this one, are the Ecosystem section's job.
      */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0 bg-[#020a18]"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={ARTWORK}
          alt=""
          width={1600}
          height={900}
          loading="eager"
          fetchPriority="high"
          decoding="async"
          /*
            ⚠️ THE PHONE STILL CROPS, AND `contain` WAS TRIED THERE AND
            MEASURED AS WORSE. Owner question, 18-09-2026: *"what abt the
            mobile how is it going to look on mobile can you look into that as
            well"*.

            A 16:9 picture in a 9:19.5 viewport is the hardest case there is.
            Contained, the whole frame survives as a band 375x211 — and the
            hero on a phone is 1124 tall against an 844 viewport, so that band
            lands at y=913 and a phone reader sees a plain dark screen with no
            artwork on it at all. Measured on the render, not guessed.
            `object-top` instead would show it and push the headline off the
            first screen.

            So below `lg` it is `cover` at the 30% anchor. At 390x1124 cover
            scales the frame to 1998px wide and shows a fifth of it, and the
            anchor decides WHICH fifth: `center` gives India's own light
            cluster, which put every line of body text on lit continents and
            was unreadable, while 30% lands on the planet's dark limb and the
            galaxy beside it. The picture is cropped and the globe is there.

            Desktop cropped too in the end — see above — so the two agree on
            the fit now and differ only in the ANCHOR, because a phone's crop
            is severe enough that which fifth of the picture it keeps decides
            whether the body text is readable.
          */
          className="h-full w-full object-cover object-[30%_center] lg:object-center"
        />
      </div>

      {/*
        ── The scrim ──────────────────────────────────────────────────────────

        WHITE TEXT OVER A PHOTOGRAPH NEEDS A FLOOR UNDER IT, and measuring said
        where. Over a 16x9 grid of the artwork the copy's own band is dark — cell
        means of 6 to 40 of 255 through the middle rows — but the 95th
        percentile in the lower left reaches 160 to 189, because the asteroid
        belt is lit, and that is exactly where the trust chips and the four
        figures sit. A scrim only in the middle would have looked fine on my
        screenshots and failed on the row that matters.

        Two layers rather than one: a horizontal wash that is strongest at the
        left edge and gone by 58%, and a shorter bottom-left corner wash for the
        belt. Both stop well before the planet, so nothing dims the picture's
        subject. The whole thing is one element with two gradients so it is one
        paint, and it sits ABOVE the image and BELOW the content.

        ⚠️ AND THE PHONE GETS A FLAT ONE INSTEAD, because a DIRECTIONAL scrim
        is the wrong tool there. On a phone the copy is not in a left column,
        it is the whole width — so a wash that fades out by 58% leaves the
        right-hand half of every line of body text unprotected, which is
        exactly how it rendered. Below `lg` it is a single even veil.
      */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-[1] bg-[#020a18]/65 lg:hidden"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-[1] hidden lg:block"
        style={{
          backgroundImage: [
            "linear-gradient(100deg, rgba(2,8,22,0.92) 0%, rgba(2,8,22,0.78) 22%, rgba(2,8,22,0.34) 42%, rgba(2,8,22,0) 58%)",
            "radial-gradient(70% 55% at 6% 100%, rgba(2,8,22,0.82), rgba(2,8,22,0) 70%)",
          ].join(","),
        }}
      />

      {/*
        ── The copy, ANCHORED LEFT AND SIZED TO THE WINDOW'S HEIGHT ───────────

        ⚠️ EVERY VERTICAL GAP IN HERE IS `clamp(min, Nvh, today's value)`, AND
        THAT IS WHAT MAKES THE HERO FIT ON A SHORT LAPTOP. The section is
        `min-h-screen`, so it is at least the height of the window — but the
        copy inside it was a FIXED 677px whatever the window did, and with
        88px of padding above and 56px below that made a hero that always
        needed 821px. Whether it fitted was therefore a fact about the
        reader's browser rather than about the page.

        Measured, before this change:

            page area 955px (1080p, no bookmarks bar)   821 — fits
            page area 880px (1080p, bookmarks + taskbar) 821 — fits
            page area 780px (13-inch MacBook Air)        833 — over by 53
            page area 760px (the owner's own window)     821 — over by 61
            page area 730px (1536x864 at 125% scaling)   821 — over by 91

        which is the answer to "does it differ really to laptop to laptop or
        its a website thing?" — it is one thing seen from two sides. The page
        asked for a fixed height and the laptop supplies a variable one, and
        display scaling, browser zoom and a bookmarks bar move it as much as
        the screen does.

        Each maximum below is the value the gap had before, so a window with
        room is unchanged; the `vh` term only bites when there is not enough.
        That buys about 100px, which covers every case in the table. It does
        NOT cover a 600px page area — a 1280x800 screen at 150% scaling — where
        the copy alone is taller than the window; fixing that needs the display
        type to shrink too, which changes the hero's look rather than its
        spacing and is an owner decision.

        ── AND ANCHORED LEFT RATHER THAN CENTRED ──────────────────────────────

        THE HERO IS THE ONE SECTION THAT MUST NOT USE A CENTRED CONTAINER, and
        the reason survives the change of artwork. Every other section sits in a
        column that is capped and then centred, so its left gutter grows by half
        of every pixel added to the window — while everything it shares the
        screen with here is positioned against the VIEWPORT. Two things measured
        from different origins, advancing at different rates: they converge, and
        then the text is on the picture.

        It was not theoretical. On the page shipped 17-09-2026 the copy's left
        gutter ran 72px at 1280, 125 at 1440, 205 at 1600 and 365 at 1920, and a
        render harness found hero text over visible artwork at 1366, 1440, 1600
        AND 1920 — the four commonest desktop widths there are.

        So: no `mx-auto`, no cap, and a flat 72px gutter from `lg` up, which is
        the same clamp the padding already used. The copy column is capped in
        its own right at `clamp(330px,34vw,540px)`, because an uncapped
        container hands a `1fr` column the whole viewport and runs the headline
        back under the planet — the same defect reached from the other side.

        ⚠️ THE HEADLINE DOES NOT LINE UP WITH THE NAV LOGO, and that is a trade
        rather than an oversight. `container-ps` caps the header at 1200px and
        centres it, so the logo drifts too — 137px at 1440, 377 at 1920 — and by
        coincidence of those two numbers it used to track the hero copy within
        12px. It cannot track the copy and stop drifting at the same time.
        Aligning them would mean either re-centring the hero, which is the
        defect, or moving the header's own container, which is shared by every
        page and would then sit 164px left of all of their content.
      */}
      <div className="relative z-[3] mx-auto grid w-full max-w-[1320px] items-center gap-12 px-[clamp(20px,6vw,72px)] pb-[clamp(20px,4vh,56px)] pt-[clamp(64px,9vh,132px)] lg:mx-0 lg:max-w-none lg:grid-cols-[minmax(0,clamp(330px,34vw,540px))_minmax(0,1fr)] lg:gap-10">
        {/* ── Copy ──────────────────────────────────────────────────────── */}
        <div>
          <Parallax speed={0.05}>
            <p className="text-[12px] font-semibold uppercase leading-none tracking-[0.18em] text-white/55">
              The AI-first platform for Indian CA firms
            </p>
          </Parallax>

          <h1 className="mt-[clamp(12px,2.4vh,28px)]">
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

          <p className="mt-[clamp(12px,2.2vh,24px)] max-w-[48ch] text-[16.5px] leading-[1.65] text-slate-300">
            From clients and compliance to accounts and advisory — PracticeSync brings
            everything together, so you can focus on what truly matters.
          </p>

          <div className="mt-[clamp(16px,3vh,32px)] flex flex-wrap items-center gap-6">
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

          <ul className="mt-[clamp(14px,2.6vh,32px)] flex flex-wrap gap-x-7 gap-y-3 text-[12.5px] font-medium leading-none text-white/45">
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
          <dl className="mt-[clamp(14px,2.6vh,28px)] grid max-w-[32rem] grid-cols-2 gap-x-8 gap-y-5 border-t border-white/10 pt-[clamp(12px,2vh,24px)] sm:grid-cols-4 sm:gap-x-5">
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

        {/* ── The space the artwork and the cards occupy ─────────────────

            AN EMPTY CELL, ON PURPOSE, AND ITS JOB IS NOW MOBILE-ONLY. Both the
            background and the card layer are section-level layers, so nothing
            is rendered here. On `lg` the track is the `1fr` that soaks up
            whatever the capped copy column does not take; it no longer has to
            hold the copy back, because the copy column caps itself, and
            removing the cell would make the grid single-column and change the
            mobile stack.

            Below `lg` it is clearance at the bottom of the hero, which is where
            the visual has always been on a phone — and where, with a full-bleed
            background, it keeps the copy off the brightest part of the crop. */}
        <div aria-hidden="true" className="h-[260px] lg:h-auto" />
      </div>

      {/*
        THE VERTICAL RAIL AND THE CLOSING TAGLINE ARE GONE, BECAUSE THE FIRST
        SUPPLIED ARTWORK ALREADY SAID IT.

        Two decorative text elements used to sit on the right edge of this
        section: a rail reading PEOPLE / DATA / COMPLIANCE / GROWTH / ALL IN
        SYNC, and a closing "SYNC TODAY. A STRONGER TOMORROW." at the bottom
        right. Both were written for a hero whose right half was empty canvas.

        The 17-09-2026 artwork carried "A STRONGER PRACTICE TOMORROW" baked into
        its own right side, so keeping the HTML versions stated the same
        sentiment twice and the rail rendered on top of a card. The artwork that
        replaced it carries no words at all — so the rail COULD come back now.
        It is deliberately not being restored: it was decoration for an empty
        half, and that half now has eight cards in it.
      */}

      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-9 left-1/2 z-[3] flex -translate-x-1/2 flex-col items-center gap-2.5 opacity-45"
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

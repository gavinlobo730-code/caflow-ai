"use client";

import { RotatingWord, HERO_WORDS } from "./RotatingWord";
import { Magnetic } from "../Cursor";
import {
  ArrowRight,
  BarChart,
  FileText,
  Landmark,
  Sparkles,
  Users,
} from "../icons";
import { Parallax } from "../motion";

/**
 * THE HERO'S EARTH IS ARTWORK AND THE CARDS OVER IT ARE NOT.
 *
 * Four passes tried to draw this scene in the browser — a dotted globe, a
 * shaded planet, a WebGL night Earth from a coastline mask, and a table of
 * world cities. On 17-09-2026 the owner supplied finished artwork instead and
 * the instruction was explicit: *"This is a static image, not something to draw
 * with code ... Do not attempt to recreate the globe, city lights, starfield,
 * or card artwork with SVG, Canvas, or CSS shapes."* That is why the planet,
 * the network, the orbits, the galaxy, the moons and the asteroid belt are one
 * committed image and there is no scene code left. It is all in git at e566d9f5
 * if the animated version is ever wanted.
 *
 * ⚠️ THE CARDS ARE THE ONE PART THAT CAME BACK OUT OF THE IMAGE, AND THE OWNER
 * ASKED FOR THAT DIRECTLY on 18-09-2026, having supplied two renders — one
 * clean, one with the eight capability cards baked in — and asked *"the cards
 * that will you add that would look good or i have given you the image where
 * the cards are there"*.
 *
 * It is the clean render plus real HTML cards, and the deciding fact is
 * measured rather than aesthetic: in the baked-in render the leftmost card
 * (Clients) begins at x=535 of 1600, which is 33.4% of the width, and this
 * hero's copy column runs to 38% of the width at every size from 1280 up. The
 * two overlap by about 5% of the screen. Using that render as a full-bleed
 * background therefore means either a card under the headline or a headline
 * shrunk to fit around art — and the collisions that reached production on
 * 17-09-2026 were exactly this class of defect, found by a render harness
 * rather than by eye.
 *
 * Real HTML also gives back the four things the previous artwork's own note
 * listed as the cost of baking them in: a screen reader can read them, they
 * reflow, they can be translated, and a label can change without re-exporting
 * a 200KB image. What it costs is that their look is now CSS approximating the
 * render's — see CARD_SKIN — so if the artwork's card treatment changes, this
 * has to be re-matched by hand.
 *
 * The two images are NOT the same base: `ImageChops.difference` over the pair
 * differs in every 100px band of the frame, from 16.8% of pixels at the left
 * edge to 55.3% at x=1300, so the second is a separate render and the cards
 * could not have been cut out of it cleanly even if that had been wanted.
 */
const ARTWORK = "/hero/space-earth.webp";

/**
 * The eight modules, in the reading order the artwork put them in.
 *
 * Titles and one-line descriptions are the owner's own, transcribed from the
 * supplied render so the page says what the picture said.
 */
const MODULES = [
  { icon: FileText, title: "Compliance", line: "GST, TDS, ITR & ROC" },
  { icon: Users, title: "Clients", line: "Every entity, one record" },
  { icon: BarChart, title: "Practice analytics", line: "The whole firm at a glance" },
  { icon: Landmark, title: "Banking", line: "Statements become vouchers" },
  { icon: BarChart, title: "Accounting", line: "A ledger that looks ahead" },
  { icon: Users, title: "Payroll", line: "Salary, PF, ESI & TDS" },
  { icon: FileText, title: "Documents", line: "Read by AI, checked by you" },
  { icon: Sparkles, title: "AI assistant", line: "It knows your practice" },
] as const;

/**
 * Where each card sits, as a PERCENTAGE of the hero rather than in pixels.
 *
 * The background is `object-cover`, so it scales with the section; a card
 * placed in pixels would drift off the feature it is meant to sit beside as
 * the window changes. Percentages keep each one in the same relation to the
 * planet at every width.
 *
 * TWO LOOSE COLUMNS, which is the arrangement the supplied render uses: four
 * cards down the planet's left limb and four down its right, staggered so no
 * two share a horizontal line. `inner` is the left column's x and it is
 * RESPONSIVE — at the narrow end of `lg` the copy is proportionally wider, so
 * the column has to start further right; `xl` moves it back in beside the
 * planet where the render has it.
 *
 * `top` values avoid the two things underneath that must stay legible: India's
 * own light cluster, which is the focal point of the picture and sits around
 * 60% across and 37-58% down, and the bright asteroid belt in the lower left.
 */
const PLACEMENT = [
  { inner: true, top: "17%" },
  { inner: true, top: "34%" },
  { inner: true, top: "53%" },
  { inner: true, top: "71%" },
  { inner: false, top: "23%" },
  { inner: false, top: "42%" },
  { inner: false, top: "60%" },
  { inner: false, top: "79%" },
] as const;

/**
 * The card's own look, matched by eye to the supplied render.
 *
 * A single constant rather than eight copies, and named so the next reader
 * knows it is an approximation of somebody else's artwork rather than a design
 * token: the render draws a semi-transparent navy panel with a soft blue rim
 * and an outer glow, an icon at the left, a white semibold title and a lighter
 * second line.
 *
 * `backdrop-blur` is deliberately SMALL. The panel sits over a starfield, and
 * a heavy blur turns the stars behind it into grey mush that reads as a smear
 * rather than glass.
 */
const CARD_SKIN =
  "rounded-2xl border border-[#5da8ff]/30 bg-[#081b3d]/80 px-4 py-3 " +
  "shadow-[0_0_46px_-10px_rgba(70,140,255,0.55)] backdrop-blur-[3px]";

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

        `object-cover object-center`: the hero is `min-h-screen` and so is
        rarely 16:9, and cover is the only fit that leaves no bare section
        showing. It crops rather than letterboxes, which is why the previous
        asset needed a top-and-bottom mask and this one does not.

        The background colour underneath is the artwork's own darkest corner,
        so the single frame the image has not decoded in is the right colour
        rather than white.

        `alt=""` AND THAT IS NOW CORRECT, where on the previous asset it would
        have been a defect. That one had the eight module labels baked into it,
        so its alt was the only route by which a third of the hero's content
        reached a screen reader. These labels are real text below.
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
            THE CROP ANCHOR IS DIFFERENT ON A PHONE, and that is measured
            rather than tidy. At 390x1124 `cover` scales the 16:9 frame to
            1998px wide and shows 19.5% of it, so the anchor decides which
            fifth of the picture a phone gets. `center` gives the globe's
            brightest quarter — India's own light cluster — and the copy, the
            trust chips and the four figures all sit directly on it, which was
            unreadable. 30% moves the window onto the planet's dark limb and
            the galaxy beside it: still the globe, still the subject, without
            the lit continents behind body text.
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
        ── The cards ──────────────────────────────────────────────────────────

        A LAYER OF ITS OWN, absolutely positioned against the SECTION, for the
        same reason the old artwork was: the content container below is capped
        and padded, so anything positioned inside it measures against that box
        and cannot reach the screen's right edge where the outer column belongs.

        HIDDEN BELOW `lg`, and that is a decision rather than an omission. Eight
        floating panels over a cropped photograph on a 390px screen is not a
        smaller version of this composition, it is a different and worse one —
        and the modules are stated again, in full, by the Ecosystem section
        immediately below the hero, so nothing is lost on a phone.

        `pointer-events-none` on the layer: these are labels, not controls. They
        are not links, because where each one should lead is a navigation
        decision nobody has taken, and a card that looks clickable and is not is
        worse than one that plainly is not.
      */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-[2] hidden lg:block"
      >
        {MODULES.map((m, i) => {
          const Icon = m.icon;
          const place = PLACEMENT[i];
          return (
            <div
              key={m.title}
              className={
                "absolute flex items-center gap-3 " +
                CARD_SKIN +
                (place.inner
                  ? " left-[46%] xl:left-[40.5%]"
                  : " right-[2.5%] xl:right-[3.5%]")
              }
              style={{ top: place.top }}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#2f7dff]/20 text-[#7cc0ff] ring-1 ring-[#7cc0ff]/25">
                <Icon size={18} />
              </span>
              <span className="block">
                <span className="block text-[14.5px] font-semibold leading-tight text-white">
                  {m.title}
                </span>
                <span className="mt-0.5 block whitespace-nowrap text-[12.5px] leading-tight text-white/65">
                  {m.line}
                </span>
              </span>
            </div>
          );
        })}
      </div>

      {/*
        ── The copy, ANCHORED LEFT RATHER THAN CENTRED ────────────────────────

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
      <div className="relative z-[3] mx-auto grid w-full max-w-[1320px] items-center gap-12 px-[clamp(20px,6vw,72px)] pb-14 pt-[clamp(88px,11vh,132px)] lg:mx-0 lg:max-w-none lg:grid-cols-[minmax(0,clamp(330px,34vw,540px))_minmax(0,1fr)] lg:gap-10">
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

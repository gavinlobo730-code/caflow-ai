"use client";

import { RotatingWord, HERO_WORDS } from "./RotatingWord";
import { HeroVisual } from "./HeroVisual";
import { Magnetic } from "../Cursor";
import { ArrowRight } from "../icons";
import { Parallax } from "../motion";

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
      className="relative flex min-h-screen flex-col justify-center overflow-hidden bg-brand-dark text-white"
      style={{ boxShadow: "inset 0 0 180px rgba(0,0,0,0.4)" }}
    >
      {/* The 460px watermark "01" that used to sit here is gone, with the rest
          of the panel numerals — owner review, 16-09-2026: "the 01 and the
          numbering in the big light on all pages they also dont look asthetic".
          Section numbering now lives in SerifHeading's `index`, at 13px. */}

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

        {/* ── Visual ────────────────────────────────────────────────────── */}
        {/* Square-ish on desktop so the connector SVG's unit viewBox barely
            distorts; a short fixed band on mobile, where §14 asks for the
            headline first and a simplified globe beneath it. */}
        <HeroVisual className="h-[320px] w-full sm:h-[420px] lg:h-[min(80vh,640px)]" />
      </div>

      {/* The vertical rail, from the reference. Four words for what the platform
          keeps in one place, set small down the right edge. Hidden below xl —
          there is no room for it beside the composition, and a rail that
          collides with a card is worse than no rail. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-8 top-1/2 z-[1] hidden -translate-y-1/2 xl:block"
      >
        <ul className="flex flex-col gap-2 text-[10px] font-semibold leading-none tracking-[0.2em] text-white/25">
          {["PEOPLE", "DATA", "COMPLIANCE", "GROWTH"].map((w) => (
            <li key={w}>{w}</li>
          ))}
          <li className="mt-1 text-gold/50">ALL IN SYNC</li>
        </ul>
      </div>

      {/* The closing line, bottom right in the reference. A statement of intent
          rather than a claim, so it carries nothing that needs verifying. */}
      <p
        aria-hidden="true"
        className="pointer-events-none absolute bottom-9 right-8 z-[1] hidden text-right text-[10px] font-semibold leading-[1.8] tracking-[0.2em] text-white/25 lg:block"
      >
        SYNC TODAY.
        <br />
        A STRONGER TOMORROW.
      </p>

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

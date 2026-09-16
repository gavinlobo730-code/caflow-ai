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
export function Hero() {
  return (
    <section
      className="relative flex min-h-screen flex-col justify-center overflow-hidden bg-brand-dark text-white"
      style={{ boxShadow: "inset 0 0 180px rgba(0,0,0,0.4)" }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-5 -top-[60px] z-0 select-none font-display leading-none text-white/[0.045] text-[clamp(220px,32vw,460px)]"
      >
        01
      </div>

      <div className="relative z-[1] mx-auto grid w-full max-w-[1320px] items-center gap-12 px-[clamp(20px,6vw,72px)] pb-20 pt-[clamp(120px,16vh,180px)] lg:grid-cols-[minmax(0,1fr)_minmax(0,640px)] lg:gap-10">
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
              className="block font-display italic leading-[0.96] tracking-[-0.02em] text-[clamp(56px,9.5vw,138px)]"
            >
              <RotatingWord />
            </span>
            <span
              aria-hidden="true"
              className="mt-3 block max-w-[17ch] font-display leading-[1.05] tracking-[-0.015em] text-[clamp(32px,4.6vw,62px)]"
            >
              Run your entire practice on one intelligent platform.
            </span>
          </h1>

          <p className="mt-8 max-w-[48ch] text-[17px] leading-[1.65] text-slate-300">
            From clients and compliance to accounts and advisory — PracticeSync brings
            everything together, so you can focus on what truly matters.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-6">
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

          <ul className="mt-11 flex flex-wrap gap-x-7 gap-y-3 text-[12.5px] font-medium leading-none text-white/45">
            <li>No credit card needed</li>
            <li>Data hosted in India</li>
            <li>Nothing filed without your click</li>
          </ul>
        </div>

        {/* ── Visual ────────────────────────────────────────────────────── */}
        {/* Square-ish on desktop so the connector SVG's unit viewBox barely
            distorts; a short fixed band on mobile, where §14 asks for the
            headline first and a simplified globe beneath it. */}
        <HeroVisual className="h-[320px] w-full sm:h-[420px] lg:h-[min(80vh,640px)]" />
      </div>

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

"use client";

import { useCallback, useState, type CSSProperties } from "react";
import Link from "next/link";
import { CountUp, TiltCard } from "@/components/motion";
import { Magnetic, useCursorGlow } from "@/components/Cursor";
import { ScrollJack } from "@/components/ScrollJack";
import { IntroLoader } from "@/components/IntroLoader";
import { ThreeScene } from "@/components/ThreeScene";
import { FilmGrain } from "@/components/FilmGrain";
import { DiagonalSection } from "@/components/DiagonalSection";
import {
  KineticLine,
  FocusReveal,
  ParallaxLabel,
  SectionReveal,
  ReactiveMarquee,
  RotatingWord,
} from "@/components/Kinetic";
import { SiteFooter } from "@/components/SiteFooter";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { ArrowRight } from "@/components/icons";
import { appLinks } from "@/lib/site";

// Rotating hero word — exact list/copy from the design reference. Instrument
// Serif italic, cycling every 2.2s as the hero's visual centrepiece.
const HERO_WORDS = ["Compliance.", "Clarity.", "Control.", "Automation.", "Trust."];

// Cinematic corner-darkening — exact per-section blur/alpha from the design
// reference (hero is deliberately the odd one out: 180px/0.4, not 160/0.45).
const HERO_VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 180px rgba(0,0,0,0.4)" };
const VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 160px rgba(0,0,0,0.45)" };

// Fluid side padding shared by every below-the-fold section — no fixed
// breakpoint scale, per the reference's "everything is clamp()" spacing rule.
const SIDE_PAD = "px-[clamp(20px,6vw,72px)]";

// Per-card shadows from the reference (tinted toward this codebase's brand
// navy rather than the reference's literal OKLCH — see the colour-token
// decision already made for this rebuild).
const CARD_SHADOW_A: CSSProperties = { boxShadow: "0 24px 55px rgba(13,22,53,0.45)" };
const CARD_SHADOW_B: CSSProperties = { boxShadow: "0 16px 40px rgba(13,22,53,0.35)" };
const CARD_SHADOW_C: CSSProperties = { boxShadow: "0 30px 70px rgba(13,22,53,0.5)" };

const TICKER = [
  "GSTR-1",
  "GSTR-3B",
  "GSTR-9",
  "ITR FILING",
  "TDS 24Q",
  "TDS 26Q",
  "MCA FILINGS",
  "ADVANCE TAX",
  "PAYROLL & PF/ESI",
  "SCHEDULE III",
  "AI DOCUMENT EXTRACTION",
];

const TRUST_ROWS = [
  "Explicit CA confirmation on every government submission",
  "Full audit log of who reviewed and filed what",
  "Role-based access, MFA and data hosted in India",
];

// Real PracticeSync figures (the reference's 11+/4/100%/4 are flagged as
// placeholder in its own README — "swap for real data before shipping").
const STATS = [
  { value: 6, suffix: "", label: "Modules, one connected workspace" },
  { value: 5, suffix: "", label: "Separate tools replaced by one login" },
  { value: 100, suffix: "%", label: "Filings reviewed by a CA before submit" },
  { value: 4, suffix: "", label: "Compliance domains — GST, ITR, TDS, MCA" },
];

// ── Hero ──────────────────────────────────────────────────────────────────
function Hero({ revealed }: { revealed: boolean }) {
  const glow = useCursorGlow();

  // Hero copy (subhead, paragraph, CTA row, trust row) staggers in when the
  // intro loader exits — 90ms per element, fade + translateY(16px→0), exactly
  // as the reference triggers from its loader's exit. Once `revealed` flips
  // true these settle and stay.
  const fade = (i: number): CSSProperties => ({
    opacity: revealed ? 1 : 0,
    transform: revealed ? "none" : "translateY(16px)",
    transition: "opacity 0.8s ease, transform 0.8s ease",
    transitionDelay: `${i * 90}ms`,
  });

  return (
    <section
      id="hero"
      className="relative flex min-h-screen flex-col justify-center overflow-hidden bg-brand-dark text-white"
      style={HERO_VIGNETTE}
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-40 -top-48 h-[560px] w-[560px]" />
      <div className="aurora aurora-2 -right-48 top-1/4 h-[620px] w-[620px]" />
      <div className="aurora aurora-3 bottom-[-200px] left-1/3 h-[520px] w-[520px]" />
      <div className="bg-noise absolute inset-0" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />

      {/* 3D centrepiece — fills the right ~54% of the section, behind the
          content, per the reference. Its own wrapper is what ThreeScene
          measures (size + scroll-fade progress). */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 top-0 hidden h-full w-[min(54vw,700px)] lg:block"
      >
        <ThreeScene className="h-full w-full" />
      </div>

      {/* Decorative page-number "01" bleeding off the top-right corner. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-5 -top-[60px] z-[1] select-none font-display text-[clamp(220px,32vw,460px)] leading-none text-white/[0.045]"
      >
        01
      </div>

      <div
        className="relative z-[1] mx-auto grid w-full max-w-[1200px] items-center gap-10 px-[clamp(20px,6vw,72px)] pb-20 pt-[clamp(100px,14vh,160px)] lg:grid-cols-[1.15fr_1fr]"
      >
        <div>
          <ParallaxLabel factor={0.05}>
            <span className="block text-[12px] font-semibold uppercase tracking-[0.18em] text-gold">
              The AI-first platform for Indian CA firms
            </span>
          </ParallaxLabel>

          {/* Giant rotating italic serif word — the hero centrepiece. */}
          <ParallaxLabel factor={0.11} className="mt-[28px]">
            <RotatingWord
              words={HERO_WORDS}
              decorative
              className="font-display text-[clamp(60px,11vw,168px)] italic leading-[0.96] tracking-[-0.02em] text-white"
            />
          </ParallaxLabel>

          <h1
            className="mt-2 max-w-[16ch] font-display text-[clamp(36px,5.6vw,76px)] font-normal leading-[1.05] tracking-[-0.015em] text-white"
            style={fade(0)}
          >
            Run your entire practice on one intelligent platform
          </h1>

          <p className="mt-[34px] max-w-[46ch] text-[17px] leading-[1.6] text-slate-300" style={fade(1)}>
            PracticeSync replaces Tally, ClearTax, Winman and WhatsApp with a single
            workspace for compliance, accounting, payroll, clients and documents.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-7" style={fade(2)}>
            <Magnetic>
              <a
                href={appLinks.signup}
                className="btn-shine inline-flex items-center justify-center gap-2 rounded-md bg-brand-light px-[26px] py-3.5 text-[14px] font-semibold text-brand-dark transition-transform duration-300 hover:scale-[1.03]"
              >
                Start free trial
              </a>
            </Magnetic>
            <Link
              href="/#control"
              className="inline-flex items-center gap-1.5 border-b border-current pb-[3px] text-[14px] font-semibold text-white/85 transition-colors hover:text-white"
            >
              See how it works
              <ArrowRight size={15} />
            </Link>
          </div>

          <div className="mt-11 flex flex-wrap gap-7 text-[12.5px] font-medium text-white/50" style={fade(3)}>
            <span>No credit card needed</span>
            <span>Data hosted in India</span>
            <span>Set up in a day</span>
          </div>
        </div>

        {/* Three overlapping mockup cards floating over the 3D scene. */}
        <div
          className="relative mx-auto hidden h-[360px] w-[min(90vw,380px)] lg:block"
          style={{ perspective: "900px" }}
        >
          <TiltCard
            base="rotate(-6deg)"
            className="absolute bottom-5 left-0 w-[210px] rounded-[10px] bg-white p-4"
            style={CARD_SHADOW_A}
          >
            <div className="flex items-center gap-2.5">
              <span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full bg-brand-light/40 text-[12px] font-semibold text-brand">
                PS
              </span>
              <div>
                <p className="text-[12.5px] font-semibold leading-tight text-brand-dark">Priya Sharma</p>
                <p className="text-[11px] font-medium leading-tight text-slate-400">Documents received</p>
              </div>
            </div>
          </TiltCard>

          <TiltCard
            base="rotate(4deg)"
            className="absolute right-0 top-2.5 max-w-[180px] rounded-[10px] bg-brand-light px-4 py-3 text-brand-dark"
            style={CARD_SHADOW_B}
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.06em] opacity-[0.85]">AI flagged</p>
            <p className="mt-0.5 text-[12.5px] font-medium">2 mismatches before filing</p>
          </TiltCard>

          <TiltCard
            base="translate(-50%,-50%) rotate(-2deg)"
            className="absolute left-1/2 top-[52%] w-[250px] rounded-[14px] bg-white p-5"
            style={CARD_SHADOW_C}
          >
            <p className="mb-[13px] text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              Filing calendar
            </p>
            {[
              ["GSTR-3B", "20 Aug"],
              ["GSTR-1", "11 Aug"],
              ["TDS 26Q", "31 Jul"],
              ["Advance Tax", "15 Sep"],
            ].map(([name, date], i, arr) => (
              <div
                key={name}
                className={`flex justify-between py-[9px] text-[13px] font-medium text-brand-dark ${
                  i < arr.length - 1 ? "border-b border-slate-900/10" : ""
                }`}
              >
                <span>{name}</span>
                <span className="text-slate-400">{date}</span>
              </div>
            ))}
          </TiltCard>
        </div>
      </div>

      {/* Scroll cue: bobbing 1px hairline + SCROLL label. */}
      <div className="pointer-events-none absolute bottom-9 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-2.5 text-white/45 lg:flex">
        <div className="scroll-cue h-[38px] w-px bg-current" />
        <span className="text-[10px] font-medium uppercase tracking-[0.16em]">Scroll</span>
      </div>
    </section>
  );
}

// ── Marquee band (its own darkest-navy strip, per the reference) ────────────
function MarqueeBand() {
  return (
    <div className="relative overflow-hidden border-y border-white/[0.12] bg-brand-dark py-5">
      <ReactiveMarquee>
        {TICKER.map((item) => (
          <span key={item} className="flex items-center gap-1.5 whitespace-nowrap pr-[26px]">
            <span className="text-[13px] font-semibold uppercase tracking-[0.1em] text-white/60">{item}</span>
            <span className="text-brand-light">&bull;</span>
          </span>
        ))}
      </ReactiveMarquee>
    </div>
  );
}

// ── The Problem ─────────────────────────────────────────────────────────────
function Problem() {
  return (
    <DiagonalSection id="story" numeral="02" numeralCorner="bottom-left" seam="rising-right" className="bg-ps-bg text-brand-dark">
      <div className={`mx-auto max-w-[1100px] ${SIDE_PAD} pt-[calc(clamp(90px,14vw,150px)+64px)] pb-[clamp(90px,14vw,150px)]`}>
        <div className="ml-auto max-w-[640px]">
          <ParallaxLabel factor={0.05}>
            <span className="block text-[12px] font-semibold uppercase tracking-[0.18em] text-gold">The problem</span>
          </ParallaxLabel>
          <h2 className="mt-[26px] font-display font-normal tracking-[-0.015em] text-brand-dark">
            <KineticLine text="Every CA firm runs like this." className="text-[clamp(28px,4vw,46px)] leading-[1.18]" />
            <KineticLine text="Five tools. Five logins." italic className="mt-1.5 text-[clamp(30px,4.6vw,54px)] leading-[1.18]" />
            <KineticLine text="One deadline falling through the cracks." className="mt-1.5 text-[clamp(28px,4vw,46px)] leading-[1.18]" />
          </h2>
          <FocusReveal targetOpacity={0.65} className="mt-[34px] max-w-[52ch] text-[17px] leading-[1.65] text-brand-dark">
            <p>Compliance in one app, client chats in another, ledgers in a third — and nothing talks to anything else.</p>
          </FocusReveal>
        </div>
      </div>
    </DiagonalSection>
  );
}

// ── The Platform ─────────────────────────────────────────────────────────────
function Platform() {
  const glow = useCursorGlow();
  return (
    <DiagonalSection numeral="03" numeralCorner="top-right" seam="rising-left" className="bg-brand-dark text-white" style={VIGNETTE}>
      <div className="relative" {...glow.handlers}>
        <div className="bg-grid absolute inset-0 opacity-70" />
        <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
        <div className={`relative mx-auto max-w-[1100px] ${SIDE_PAD} pt-[calc(clamp(90px,14vw,150px)+64px)] pb-[clamp(90px,14vw,150px)]`}>
          <ParallaxLabel factor={0.05}>
            <span className="block text-[12px] font-semibold uppercase tracking-[0.18em] text-gold">The platform</span>
          </ParallaxLabel>
          <h2 className="mt-[26px] font-display font-normal tracking-[-0.015em] text-white">
            <KineticLine text="One workspace." className="text-[clamp(28px,4vw,46px)] leading-[1.18]" />
            <KineticLine text="Every compliance domain." italic className="mt-1.5 text-[clamp(30px,4.6vw,54px)] leading-[1.18]" />
            <KineticLine text="Nothing falls through." className="mt-1.5 text-[clamp(28px,4vw,46px)] leading-[1.18]" />
          </h2>
          <FocusReveal targetOpacity={0.6} className="mt-11 max-w-[900px] text-[14px] font-medium leading-[1.9] text-white">
            <p>
              GSTR-1 &nbsp;/&nbsp; GSTR-3B &nbsp;/&nbsp; GSTR-9 &nbsp;/&nbsp; ITR filing &nbsp;/&nbsp; TDS 24Q &amp; 26Q
              &nbsp;/&nbsp; MCA filings &nbsp;/&nbsp; Advance tax &nbsp;/&nbsp; Payroll &amp; PF/ESI &nbsp;/&nbsp; Schedule III
              &nbsp;/&nbsp; AI document extraction &nbsp;/&nbsp; Client portal &nbsp;/&nbsp; Practice analytics
            </p>
          </FocusReveal>
        </div>
      </div>
    </DiagonalSection>
  );
}

// ── Control & Trust ──────────────────────────────────────────────────────────
// Preserves the CLAUDE.md compliance stance: the headline "Nothing is filed
// without your click" + row 01 "Explicit CA confirmation on every government
// submission" carry the never-auto-submit guarantee.
function Trust() {
  return (
    <DiagonalSection
      id="control"
      numeral="04"
      numeralCorner="bottom-left"
      numeralStyle={{ bottom: "-50px" }}
      seam="rising-right"
      className="bg-ps-bg text-brand-dark"
    >
      <div className={`mx-auto max-w-[1100px] ${SIDE_PAD} pt-[calc(clamp(90px,14vw,150px)+64px)] pb-[clamp(90px,14vw,150px)]`}>
        <div className="ml-auto max-w-[640px]">
          <ParallaxLabel factor={0.05}>
            <span className="block text-[12px] font-semibold uppercase tracking-[0.18em] text-gold">Control &amp; trust</span>
          </ParallaxLabel>
          <h2 className="mt-[26px] font-display font-normal tracking-[-0.015em] text-brand-dark">
            <KineticLine text="Nothing is filed" className="text-[clamp(28px,4vw,46px)] leading-[1.18]" />
            <KineticLine text="without your click." italic className="mt-1.5 text-[clamp(30px,4.6vw,54px)] leading-[1.18]" />
          </h2>
          <div className="mt-10 flex max-w-[60ch] flex-col gap-4">
            {TRUST_ROWS.map((row, i) => (
              <FocusReveal
                key={row}
                targetOpacity={0.7}
                className={`flex items-baseline gap-4 border-t border-slate-900/[0.12] pt-4 text-[16px] leading-[1.6] text-brand-dark ${
                  i === TRUST_ROWS.length - 1 ? "border-b border-slate-900/[0.12] pb-4" : ""
                }`}
              >
                <span className="min-w-[40px] font-display text-[26px] italic text-slate-900/50">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span>{row}</span>
              </FocusReveal>
            ))}
          </div>
        </div>
      </div>
    </DiagonalSection>
  );
}

// ── Stats ────────────────────────────────────────────────────────────────────
function Stats() {
  return (
    <DiagonalSection seam="rising-left" className="bg-brand-dark text-white" style={VIGNETTE}>
      <StatsInner />
    </DiagonalSection>
  );
}

function StatsInner() {
  const glow = useCursorGlow();
  return (
    <SectionReveal>
      <div className="relative" {...glow.handlers}>
        <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
        <div className={`relative mx-auto grid max-w-[1100px] grid-cols-1 gap-12 ${SIDE_PAD} pt-[calc(clamp(90px,14vw,150px)+64px)] pb-[clamp(90px,14vw,150px)] sm:grid-cols-2 lg:grid-cols-4`}>
          {STATS.map((s, i) => (
            <div key={s.label} className={i % 2 === 1 ? "sm:mt-8" : ""}>
              <p className="font-display text-[clamp(48px,6vw,84px)] leading-none text-white">
                <CountUp to={s.value} suffix={s.suffix} duration={1200} linear />
              </p>
              <p className="mt-2.5 text-[13px] font-medium leading-[1.5] text-white/55">{s.label}</p>
            </div>
          ))}
        </div>
      </div>
    </SectionReveal>
  );
}

// ── Testimonial ──────────────────────────────────────────────────────────────
function Testimonial() {
  return (
    <DiagonalSection
      numeral={"“"}
      numeralCorner="top-left"
      numeralItalic
      numeralFontSize="clamp(260px,34vw,440px)"
      numeralOpacity={0.06}
      seam="rising-right"
      className="bg-ps-bg text-brand-dark"
    >
      <div className={`mx-auto max-w-[960px] ${SIDE_PAD} pt-[calc(clamp(100px,16vw,170px)+64px)] pb-[clamp(100px,16vw,170px)] text-center`}>
        <FocusReveal className="font-display text-[clamp(26px,3.6vw,40px)] italic leading-[1.4] tracking-[-0.01em] text-brand-dark">
          <p>
            &ldquo;We shut down four subscriptions and a dozen spreadsheets. My team finally sees every
            client&apos;s deadlines, books and documents in one screen — and the AI catches mismatches before
            we file.&rdquo;
          </p>
        </FocusReveal>
        <FocusReveal targetOpacity={0.6} className="mt-[34px] text-[13px] font-semibold text-brand-dark">
          <p>CA Rohan Agarwal — Partner, Agarwal &amp; Co., Bengaluru</p>
        </FocusReveal>
      </div>
    </DiagonalSection>
  );
}

// ── Final CTA ────────────────────────────────────────────────────────────────
function FinalCTA() {
  const glow = useCursorGlow();
  return (
    <DiagonalSection seam="rising-left" className="bg-brand-dark text-white" style={VIGNETTE}>
      <SectionReveal>
        <div className="relative text-center" {...glow.handlers}>
          <div className="bg-grid absolute inset-0" />
          <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
          <div className={`relative mx-auto max-w-[1100px] ${SIDE_PAD} pt-[calc(clamp(90px,14vw,160px)+64px)] pb-[clamp(90px,14vw,160px)]`}>
            <h2 className="mx-auto max-w-[16ch] font-display text-[clamp(34px,5.4vw,64px)] italic font-normal leading-[1.12] tracking-[-0.015em] text-white">
              Bring your whole practice into one place.
            </h2>
            <div className="mt-10 flex flex-wrap justify-center gap-6">
              <Magnetic>
                <a
                  href={appLinks.signup}
                  className="btn-shine inline-flex items-center justify-center rounded-md bg-brand-light px-7 py-[15px] text-[14px] font-semibold text-brand-dark transition-transform duration-300 hover:scale-[1.03]"
                >
                  Start free trial
                </a>
              </Magnetic>
              <Link
                href="/support"
                className="inline-flex items-center justify-center rounded-md border border-white/30 px-7 py-[15px] text-[14px] font-semibold text-white transition-colors hover:bg-white/10"
              >
                Book a demo
              </Link>
            </div>
            <p className="mt-[26px] text-[13px] text-white/50">
              Already using PracticeSync?{" "}
              <Link href="/access" className="font-semibold text-white underline underline-offset-4">
                Log in here
              </Link>
            </p>
          </div>
        </div>
      </SectionReveal>
    </DiagonalSection>
  );
}

export default function HomePage() {
  const [heroIn, setHeroIn] = useState(false);
  // Stable identity so IntroLoader's effect doesn't re-run (and restart the
  // loader count) when heroIn flips.
  const handleExit = useCallback(() => setHeroIn(true), []);

  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      <FilmGrain />
      <IntroLoader onExit={handleExit} />
      <ScrollJack>
        <Hero revealed={heroIn} />
        <MarqueeBand />
        <Problem />
        <Platform />
        <Trust />
        <Stats />
        <Testimonial />
        <FinalCTA />
        <SiteFooter />
      </ScrollJack>
    </div>
  );
}

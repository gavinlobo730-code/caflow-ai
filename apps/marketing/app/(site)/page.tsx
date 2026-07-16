"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button, Section, SectionHeading, Card } from "@/components/ui";
import { Reveal, CountUp, Tilt, Parallax, WordReveal, Marquee } from "@/components/motion";
import { Magnetic, useCursorGlow } from "@/components/Cursor";
import { ProblemSolutionStory, ChapterRail, useSectionActive } from "@/components/StoryStage";
import {
  ArrowRight,
  Check,
  Shield,
  Sparkles,
  Lock,
  Calendar,
  Star,
  Calculator,
  FileText,
  Receipt,
  MessageCircle,
  BookOpen,
} from "@/components/icons";
import { appLinks } from "@/lib/site";

const TICKER = [
  "GSTR-1",
  "GSTR-3B",
  "GSTR-9",
  "ITR filing",
  "TDS 24Q / 26Q",
  "MCA filings",
  "Advance tax",
  "Payroll & PF/ESI",
  "Schedule III",
  "AI document extraction",
  "Client portal",
  "Practice analytics",
];

const DEADLINES = [
  { t: "GSTR-3B — July", d: "20 Aug", c: "bg-amber-100 text-amber-700" },
  { t: "GSTR-1 — July", d: "11 Aug", c: "bg-rose-100 text-rose-700" },
  { t: "TDS 26Q — Q1", d: "31 Jul", c: "bg-emerald-100 text-emerald-700" },
  { t: "Advance tax — Q2", d: "15 Sep", c: "bg-slate-100 text-slate-600" },
];

const SCATTER_TOOLS = [
  { name: "Tally", pain: "Ledgers, kept offline", icon: <Calculator size={18} />, pos: "top-[12%] left-[9%] -rotate-6" },
  { name: "ClearTax", pain: "GST filed on its own", icon: <FileText size={18} />, pos: "top-[15%] right-[11%] rotate-3" },
  { name: "Winman", pain: "ITR, another login", icon: <Receipt size={18} />, pos: "bottom-[26%] left-[7%] rotate-[8deg]" },
  { name: "WhatsApp", pain: "Clients chasing on chat", icon: <MessageCircle size={18} />, pos: "bottom-[15%] right-[9%] -rotate-[7deg]" },
  { name: "Excel", pain: "Everything else, scattered", icon: <BookOpen size={18} />, pos: "bottom-[9%] left-[40%] rotate-2" },
];

// Chapter 1 — the problem, stated plainly (deliberately no WordReveal here;
// chapter 2's polished entrance is meant to feel like the "arrival").
function ScatterChapter() {
  const glow = useCursorGlow();
  return (
    <div
      className="relative flex h-full min-h-[94vh] flex-col justify-center overflow-hidden bg-brand-dark text-white"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-40 -top-48 h-[560px] w-[560px] opacity-70" />
      <div className="aurora aurora-3 bottom-[-200px] left-1/3 h-[520px] w-[520px] opacity-60" />
      <div className="bg-noise absolute inset-0" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />

      {SCATTER_TOOLS.map((tool) => (
        <div
          key={tool.name}
          className={`absolute hidden w-[168px] rounded-2xl border border-white/12 bg-white/[0.05] p-3.5 shadow-modal backdrop-blur-md lg:block ${tool.pos}`}
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/[0.07] text-rose-300/80">
            {tool.icon}
          </span>
          <p className="mt-2.5 text-[13px] font-bold text-white">{tool.name}</p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{tool.pain}</p>
        </div>
      ))}

      <div className="container-ps relative py-20 text-center">
        <span className="inline-flex items-center gap-2.5 rounded-full border border-white/15 bg-white/[0.06] px-4 py-1.5 text-[12.5px] font-medium text-rose-200/90 backdrop-blur-sm">
          <span className="h-2 w-2 rounded-full bg-rose-400/80" />
          Every CA firm runs like this
        </span>
        <h2 className="mx-auto mt-7 max-w-2xl text-[32px] font-bold leading-[1.15] tracking-tight md:text-[46px]">
          Five tools. Five logins. One deadline falling through the cracks.
        </h2>
        <p className="mx-auto mt-5 max-w-md text-[15px] leading-relaxed text-slate-400 md:text-[16px]">
          Compliance in one app, client chats in another, ledgers in a third —
          and nothing talks to anything else.
        </p>
      </div>
    </div>
  );
}

// Chapter 2 — the settled hero. Unchanged from the previous build; it is now
// simply the "arrival" state of the scroll-pinned convergence above it.
function SettledHero() {
  const glow = useCursorGlow();
  return (
    <section
      className="relative flex min-h-[94vh] flex-col overflow-hidden bg-brand-dark text-white"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-40 -top-48 h-[560px] w-[560px]" />
      <div className="aurora aurora-2 -right-48 top-1/4 h-[620px] w-[620px]" />
      <div className="aurora aurora-3 bottom-[-200px] left-1/3 h-[520px] w-[520px]" />
      <div className="bg-noise absolute inset-0" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-brand-dark to-transparent" />

      <div className="container-ps relative grid flex-1 items-center gap-16 py-20 md:py-24 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <span
            className="fade-up inline-flex items-center gap-2.5 rounded-full border border-white/15 bg-white/[0.06] px-4 py-1.5 text-[12.5px] font-medium text-brand-light backdrop-blur-sm"
            style={{ animationDelay: "80ms" }}
          >
            <span className="pulse-dot h-2 w-2 rounded-full bg-emerald-400" />
            The AI-first platform for Indian CA firms
          </span>

          <h1 className="mt-7 text-[42px] font-bold leading-[1.04] tracking-tight md:text-[64px]">
            <WordReveal text="Run your entire practice" startDelay={200} stagger={80} />
            <br />
            <WordReveal
              text="on one intelligent platform"
              startDelay={620}
              stagger={80}
              accent={["one", "intelligent", "platform"]}
            />
          </h1>

          <p
            className="fade-up mt-6 max-w-xl text-[17px] leading-relaxed text-slate-300 md:text-[18px]"
            style={{ animationDelay: "1050ms" }}
          >
            PracticeSync replaces Tally, ClearTax, Winman and WhatsApp with a
            single AI-first workspace — compliance, accounting, payroll,
            clients and documents, working as one.
          </p>

          <div className="fade-up mt-9 flex flex-col gap-3 sm:flex-row" style={{ animationDelay: "1200ms" }}>
            <Magnetic>
              <a
                href={appLinks.signup}
                className="btn-shine group inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-4 text-[15px] font-semibold text-brand shadow-[0_8px_30px_rgba(175,210,250,0.25)] transition-transform duration-300 hover:scale-[1.03]"
              >
                Start free trial
                <ArrowRight size={16} className="transition-transform duration-300 group-hover:translate-x-1" />
              </a>
            </Magnetic>
            <Link
              href="/#security"
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/20 px-7 py-4 text-[15px] font-semibold text-white transition-colors duration-300 hover:bg-white/10"
            >
              See how it works
            </Link>
          </div>

          <div
            className="fade-up mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-slate-400"
            style={{ animationDelay: "1350ms" }}
          >
            <span className="inline-flex items-center gap-1.5">
              <Check size={15} className="text-emerald-400" /> No credit card needed
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Check size={15} className="text-emerald-400" /> Data hosted in India
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Check size={15} className="text-emerald-400" /> Set up in a day
            </span>
          </div>
        </div>

        <Parallax speed={0.05} className="relative hidden lg:block">
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-[130%] w-[130%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(175,210,250,0.14)_0%,rgba(175,210,250,0.05)_45%,transparent_70%)]" />

          <Tilt max={6}>
            <div className="fade-up relative rounded-3xl border border-white/12 bg-white/[0.05] p-3 shadow-modal backdrop-blur-md" style={{ animationDelay: "500ms" }}>
              <div className="rounded-2xl bg-white p-6 text-brand-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      Live · Compliance calendar
                    </p>
                    <p className="mt-0.5 text-[16px] font-bold">Upcoming deadlines</p>
                  </div>
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand/[0.06] text-brand">
                    <Calendar size={18} />
                  </span>
                </div>

                <div className="mt-5 space-y-2.5">
                  {DEADLINES.map((row, i) => (
                    <div
                      key={row.t}
                      className="fade-up flex items-center justify-between rounded-xl border border-ps-border bg-ps-bg px-3.5 py-3"
                      style={{ animationDelay: `${800 + i * 130}ms` }}
                    >
                      <span className="text-[13px] font-medium">{row.t}</span>
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${row.c}`}>
                        {row.d}
                      </span>
                    </div>
                  ))}
                </div>

                <div
                  className="fade-up mt-5 flex items-center gap-3 rounded-xl bg-gold-surface px-3.5 py-3 ring-1 ring-gold/25"
                  style={{ animationDelay: "1400ms" }}
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gold/15 text-gold">
                    <Sparkles size={16} />
                  </span>
                  <p className="text-[12.5px] leading-snug text-brand-dark">
                    <span className="font-semibold">AI insight:</span> 3 clients have
                    GSTR-1 vs 3B mismatches to review before filing.
                  </p>
                </div>
              </div>
            </div>
          </Tilt>

          <div
            className="fade-up floaty absolute -right-8 -top-9 rounded-2xl border border-white/12 bg-brand-dark/85 px-4 py-3 shadow-modal backdrop-blur-md"
            style={{ animationDelay: "1550ms" }}
          >
            <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <Shield size={13} className="text-emerald-400" />
              Collected this month
            </p>
            <p className="mt-1 text-[22px] font-bold text-white">
              ₹ <CountUp to={248600} duration={2200} />
            </p>
          </div>

          <div
            className="fade-up floaty-2 absolute -bottom-9 -left-10 flex items-center gap-3 rounded-2xl border border-white/12 bg-brand-dark/85 px-4 py-3.5 shadow-modal backdrop-blur-md"
            style={{ animationDelay: "1700ms" }}
          >
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Check size={17} />
            </span>
            <div>
              <p className="text-[13px] font-bold text-white">GSTR-3B filed</p>
              <p className="text-[11.5px] text-slate-400">Confirmed by CA · 2 min ago</p>
            </div>
          </div>
        </Parallax>
      </div>

      <div className="relative border-t border-white/[0.08] py-5">
        <Marquee duration={38}>
          {TICKER.map((item) => (
            <span key={item} className="mx-5 flex items-center gap-5 whitespace-nowrap text-[13px] font-medium text-slate-500">
              {item}
              <span className="h-1 w-1 rounded-full bg-slate-600" />
            </span>
          ))}
        </Marquee>
      </div>

      <div className="scroll-cue pointer-events-none absolute bottom-24 left-1/2 hidden -translate-x-1/2 lg:block">
        <div className="flex h-9 w-5 items-start justify-center rounded-full border border-white/25 p-1.5">
          <div className="h-2 w-1 rounded-full bg-white/60" />
        </div>
      </div>
    </section>
  );
}

// Chapter 3 — Trusted. Extracted so useCursorGlow (a hook) has a component
// body of its own to live in, scoped to just this card rather than the
// whole padded Section around it.
function TrustedCard() {
  const glow = useCursorGlow();
  return (
    <div
      className="relative overflow-hidden rounded-3xl border border-white/10 bg-white/[0.03] p-10 md:p-14"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0 opacity-70" />
      <div className="aurora aurora-2 -right-40 -top-40 h-[420px] w-[420px] opacity-60" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
      <div className="relative grid items-center gap-10 lg:grid-cols-[1.3fr_1fr]">
        <Reveal variant="left">
          <div className="flex">
            <span className="inline-flex items-center gap-2.5 text-[12px] font-semibold uppercase tracking-[0.15em] text-gold">
              <Lock size={15} /> Control &amp; trust
            </span>
          </div>
          <h2 className="mt-4 text-[30px] font-bold leading-tight tracking-tight text-white md:text-[38px]">
            Nothing is filed without your click
          </h2>
          <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
            AI prepares the working papers and flags what needs attention —
            but the CA always makes the final call. No return, no challan and
            no MCA form is ever submitted to a government portal
            automatically.
          </p>
          <ul className="mt-6 space-y-3">
            {[
              "Explicit CA confirmation on every government submission",
              "Full audit log of who reviewed and filed what",
              "Role-based access, MFA and data hosted in India",
            ].map((point) => (
              <li key={point} className="flex items-start gap-3 text-[15px] text-slate-200">
                <Check size={18} className="mt-0.5 shrink-0 text-emerald-400" />
                {point}
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal variant="right" delay={150}>
          <div className="rounded-2xl border border-white/10 bg-brand-dark/60 p-6 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-500/15 text-emerald-400">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                  <path className="draw-check" d="m9 12 2 2 4-4" />
                </svg>
              </span>
              <div>
                <p className="text-[14px] font-bold text-white">GSTR-3B ready to file</p>
                <p className="text-[12px] text-slate-400">Reviewed by CA · awaiting confirmation</p>
              </div>
            </div>
            <div className="mt-5 rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/10">
              <p className="text-[12px] text-slate-400">Tax payable</p>
              <p className="text-[24px] font-bold text-white">
                ₹ <CountUp to={248600} duration={1800} />
              </p>
              <div className="mt-4 flex gap-2">
                <span className="btn-shine flex-1 rounded-lg bg-brand-light py-2.5 text-center text-[13px] font-semibold text-brand-dark">
                  Confirm &amp; file
                </span>
                <span className="rounded-lg border border-white/15 px-3 py-2.5 text-center text-[13px] font-medium text-slate-300">
                  Review
                </span>
              </div>
              <p className="mt-3 text-center text-[11px] text-slate-500">
                You click. We never auto-submit.
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </div>
  );
}

export default function HomePage() {
  const [activeChapter, setActiveChapter] = useState(0);
  const trustedRef = useSectionActive<HTMLDivElement>(setActiveChapter, 2);
  const finalCtaGlow = useCursorGlow();

  // The rail's job ends when the story does — visible exactly while any part
  // of the chapters 1–3 wrapper is on screen, not derived from activeChapter
  // (which has no event that ever marks "chapter 4 reached" to turn it off).
  const storyRef = useRef<HTMLDivElement>(null);
  const [storyVisible, setStoryVisible] = useState(false);
  useEffect(() => {
    const el = storyRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => setStoryVisible(entries.some((e) => e.isIntersecting)),
      { threshold: 0 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <>
      <ChapterRail active={activeChapter} visible={storyVisible} />

      {/* ── Chapters 1–3: the story ─────────────────────────────────────── */}
      <div id="story" ref={storyRef}>
        <ProblemSolutionStory scatter={<ScatterChapter />} onActiveChange={setActiveChapter}>
          <SettledHero />
        </ProblemSolutionStory>

        {/* ── Chapter 3 — Trusted ──────────────────────────────────────── */}
        <div ref={trustedRef}>
          <Section id="security" className="bg-brand-dark">
            <TrustedCard />
          </Section>
        </div>
      </div>

      {/* ── Chapter 4 — Visible. Deliberately shifts to a light ground: the
          story's build-up is over, the rail has already faded out, and this
          is the "arrived, everything is clear" payoff. ─────────────────── */}
      <Section className="bg-white">
        <Reveal variant="blur">
          <SectionHeading
            title="The whole practice, finally visible"
            subtitle="Deadlines, revenue, clients and filings — one screen, not five tabs."
          />
        </Reveal>
        <div className="mt-14 grid gap-8 rounded-3xl border border-ps-border bg-ps-bg p-10 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { value: <CountUp to={6} duration={1200} />, label: "Modules, one connected workspace" },
            { value: <CountUp to={5} duration={1200} />, label: "Separate tools replaced by one login" },
            { value: <><CountUp to={100} duration={1600} />%</>, label: "Filings reviewed by a CA before submit" },
            { value: <CountUp to={4} duration={1200} />, label: "Compliance domains — GST, ITR, TDS, MCA" },
          ].map((s, i) => (
            <Reveal key={s.label} variant="scale" delay={i * 100}>
              <div className="text-center">
                <p className="text-[40px] font-bold tracking-tight text-brand md:text-[46px]">{s.value}</p>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-500">{s.label}</p>
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal delay={250}>
          <div className="mt-10 text-center">
            <Button href="/products" variant="secondary" className="btn-shine">
              See everything inside PracticeSync
              <ArrowRight size={16} />
            </Button>
          </div>
        </Reveal>
      </Section>

      {/* ── Testimonial ──────────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <Reveal variant="blur">
          <Card className="mx-auto max-w-3xl text-center">
            <div className="flex justify-center gap-1 text-gold">
              {Array.from({ length: 5 }).map((_, i) => (
                <Star key={i} size={18} />
              ))}
            </div>
            <blockquote className="mt-5 text-[20px] font-medium leading-relaxed text-brand-dark md:text-[24px]">
              “We shut down four subscriptions and a dozen spreadsheets. My team
              finally sees every client&apos;s deadlines, books and documents in
              one screen — and the AI catches mismatches before we file.”
            </blockquote>
            <div className="mt-6 flex items-center justify-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-full bg-brand text-[14px] font-bold text-white">
                RA
              </span>
              <div className="text-left">
                <p className="text-[14px] font-bold text-brand-dark">CA Rohan Agarwal</p>
                <p className="text-[13px] text-slate-500">Partner · Agarwal &amp; Co., Bengaluru</p>
              </div>
            </div>
          </Card>
        </Reveal>
      </Section>

      {/* ── Final CTA ────────────────────────────────────────────────────── */}
      <section
        className="relative overflow-hidden bg-brand text-white"
        {...finalCtaGlow.handlers}
      >
        <div className="bg-grid absolute inset-0" />
        <div className="aurora aurora-1 -left-32 -top-32 h-[420px] w-[420px] opacity-70" />
        <div className="aurora aurora-3 -bottom-40 -right-32 h-[460px] w-[460px] opacity-70" />
        <div ref={finalCtaGlow.ref} className="cursor-glow" aria-hidden="true" />
        <div className="container-ps relative py-24 text-center md:py-28">
          <Reveal variant="blur">
            <h2 className="mx-auto max-w-2xl text-[30px] font-bold leading-tight tracking-tight md:text-[44px]">
              Bring your whole practice into one place
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
              Start a free trial today, or talk to us about moving your firm across
              from Tally, ClearTax or Winman.
            </p>
          </Reveal>
          <Reveal delay={150}>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Magnetic>
                <a
                  href={appLinks.signup}
                  className="btn-shine group inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-4 text-[15px] font-semibold text-brand shadow-sm transition-transform duration-300 hover:scale-[1.03]"
                >
                  Start free trial
                  <ArrowRight size={16} className="transition-transform duration-300 group-hover:translate-x-1" />
                </a>
              </Magnetic>
              <Link
                href="/support"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/25 px-7 py-4 text-[15px] font-semibold text-white transition-colors duration-300 hover:bg-white/10"
              >
                Book a demo
              </Link>
            </div>
            <p className="mt-7 text-[13px] text-slate-400">
              Already using PracticeSync?{" "}
              <Link href="/access" className="font-semibold text-white underline-offset-4 hover:underline">
                Log in here
              </Link>
            </p>
          </Reveal>
        </div>
      </section>
    </>
  );
}

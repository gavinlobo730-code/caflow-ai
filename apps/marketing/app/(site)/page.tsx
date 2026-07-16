"use client";

import Link from "next/link";
import { Button, Card, IconBadge, SectionHeading } from "@/components/ui";
import { CountUp, Tilt, WordReveal } from "@/components/motion";
import { Magnetic, useCursorGlow } from "@/components/Cursor";
import { ScrollJack } from "@/components/ScrollJack";
import { IntroLoader } from "@/components/IntroLoader";
import { ThreeScene } from "@/components/ThreeScene";
import { DiagonalSection } from "@/components/DiagonalSection";
import { KineticLine, FocusReveal, ParallaxLabel, SectionReveal, ReactiveMarquee, RotatingWord } from "@/components/Kinetic";
import { SiteFooter } from "@/components/SiteFooter";
import { instrumentSerif, manrope } from "@/lib/fonts";
import {
  ArrowRight,
  Check,
  Shield,
  Lock,
  Star,
  Calculator,
  FileText,
  Receipt,
  Building,
  Bot,
  MessageCircle,
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

const PAIN_POINTS = [
  { name: "Tally", pain: "Ledgers, kept offline in a desktop app nobody else can reach.", icon: <Calculator size={20} /> },
  { name: "ClearTax", pain: "GST filed on its own, in its own login, on its own timeline.", icon: <FileText size={20} /> },
  { name: "Winman", pain: "ITR season means a third tool with a third password.", icon: <Receipt size={20} /> },
  { name: "WhatsApp", pain: "Clients chasing deadlines on chat threads nobody can audit.", icon: <MessageCircle size={20} /> },
  { name: "Excel", pain: "Everything that doesn't fit anywhere else, scattered across sheets.", icon: <Building size={20} /> },
];

const MODULES = [
  { icon: <FileText size={20} />, title: "GST & compliance", desc: "GSTR-1, GSTR-3B and GSTR-9 prepared and tracked against every due date, automatically." },
  { icon: <Calculator size={20} />, title: "Accounting & books", desc: "Real ledgers and reconciliation in one workspace — no more offline Tally file." },
  { icon: <Receipt size={20} />, title: "TDS & payroll", desc: "24Q/26Q returns, PF/ESI and payroll runs handled without a separate tool." },
  { icon: <Building size={20} />, title: "ITR & MCA filings", desc: "Individual and corporate returns, ROC forms — one calendar, one workspace." },
  { icon: <Bot size={20} />, title: "AI document intelligence", desc: "Invoices and statements extracted automatically, mismatches flagged before you file." },
  { icon: <MessageCircle size={20} />, title: "Client portal", desc: "Secure client chat and document requests — replaces the WhatsApp thread entirely." },
];

const STATS = [
  { target: 6, suffix: "", label: "Modules, one connected workspace" },
  { target: 5, suffix: "", label: "Separate tools replaced by one login" },
  { target: 100, suffix: "%", label: "Filings reviewed by a CA before submit" },
  { target: 4, suffix: "", label: "Compliance domains — GST, ITR, TDS, MCA" },
];

function Hero() {
  const glow = useCursorGlow();
  return (
    <section
      id="hero"
      className="relative flex min-h-screen flex-col overflow-hidden bg-brand-dark text-white"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-40 -top-48 h-[560px] w-[560px]" />
      <div className="aurora aurora-2 -right-48 top-1/4 h-[620px] w-[620px]" />
      <div className="aurora aurora-3 bottom-[-200px] left-1/3 h-[520px] w-[520px]" />
      <div className="bg-noise absolute inset-0" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-brand-dark to-transparent" />

      <div className="container-ps relative grid flex-1 items-center gap-16 py-28 md:py-32 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <span
            className="fade-up inline-flex items-center gap-2.5 rounded-full border border-white/15 bg-white/[0.06] px-4 py-1.5 text-[12.5px] font-medium text-brand-light backdrop-blur-sm"
            style={{ animationDelay: "1600ms" }}
          >
            <span className="pulse-dot h-2 w-2 rounded-full bg-emerald-400" />
            The AI-first platform for Indian CA firms
          </span>

          <h1 className="mt-7 font-display text-[44px] font-normal leading-[1.05] tracking-tight md:text-[68px]">
            <WordReveal text="Run your entire practice" startDelay={1750} stagger={60} />
            <br />
            <WordReveal
              text="on one intelligent platform"
              startDelay={2050}
              stagger={60}
              accent={["one", "intelligent", "platform"]}
              className="italic"
            />
          </h1>

          <p
            className="fade-up mt-6 max-w-xl text-[17px] leading-relaxed text-slate-300 md:text-[18px]"
            style={{ animationDelay: "2350ms" }}
          >
            PracticeSync replaces Tally, ClearTax, Winman and WhatsApp with a single
            AI-first workspace for{" "}
            <RotatingWord
              words={["GST filings", "TDS returns", "client books", "payroll runs", "MCA filings"]}
              className="font-semibold text-white"
            />
            .
          </p>

          <div className="fade-up mt-9 flex flex-col gap-3 sm:flex-row" style={{ animationDelay: "2500ms" }}>
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
            style={{ animationDelay: "2620ms" }}
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

        <div className="relative hidden h-[520px] lg:block">
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-[130%] w-[130%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(175,210,250,0.14)_0%,rgba(175,210,250,0.05)_45%,transparent_70%)]" />

          <ThreeScene className="absolute inset-0 h-full w-full" />

          <div
            className="fade-up floaty absolute -right-4 top-6 rounded-2xl border border-white/12 bg-brand-dark/85 px-4 py-3 shadow-modal backdrop-blur-md"
            style={{ animationDelay: "2700ms" }}
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
            className="fade-up floaty-2 absolute -bottom-2 -left-6 flex items-center gap-3 rounded-2xl border border-white/12 bg-brand-dark/85 px-4 py-3.5 shadow-modal backdrop-blur-md"
            style={{ animationDelay: "2850ms" }}
          >
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Check size={17} />
            </span>
            <div>
              <p className="text-[13px] font-bold text-white">GSTR-3B filed</p>
              <p className="text-[11.5px] text-slate-400">Confirmed by CA · 2 min ago</p>
            </div>
          </div>
        </div>
      </div>

      <div className="relative border-t border-white/[0.08] py-5">
        <ReactiveMarquee>
          {TICKER.map((item) => (
            <span key={item} className="mx-5 flex items-center gap-5 whitespace-nowrap text-[13px] font-medium text-slate-500">
              {item}
              <span className="h-1 w-1 rounded-full bg-slate-600" />
            </span>
          ))}
        </ReactiveMarquee>
      </div>

      <div className="scroll-cue pointer-events-none absolute bottom-24 left-1/2 hidden -translate-x-1/2 lg:block">
        <div className="flex h-9 w-5 items-start justify-center rounded-full border border-white/25 p-1.5">
          <div className="h-2 w-1 rounded-full bg-white/60" />
        </div>
      </div>
    </section>
  );
}

function Problem() {
  return (
    <DiagonalSection id="story" numeral="02" seam="rising-right" className="bg-ps-bg">
      <div className="container-ps pt-32 pb-20 md:pt-40 md:pb-28">
        <div className="flex justify-center">
          <span className="inline-flex items-center gap-2.5 rounded-full border border-rose-200 bg-rose-50 px-4 py-1.5 text-[12.5px] font-medium text-rose-600">
            <span className="h-2 w-2 rounded-full bg-rose-400" />
            Every CA firm runs like this
          </span>
        </div>
        <h2 className="mx-auto mt-6 max-w-2xl text-center font-display text-[32px] font-normal leading-[1.15] tracking-tight text-brand-dark md:text-[48px]">
          <KineticLine text="Five tools. Five logins." className="text-center" />
          <KineticLine text="One deadline falling through the cracks." italic className="mt-1 text-center text-brand" />
        </h2>
        <FocusReveal className="mx-auto mt-5 max-w-md text-center text-[15px] leading-relaxed text-slate-500 md:text-[16px]">
          <p>
            Compliance in one app, client chats in another, ledgers in a third —
            and nothing talks to anything else.
          </p>
        </FocusReveal>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-5">
          {PAIN_POINTS.map((tool, i) => (
            <ParallaxLabel key={tool.name} factor={i % 2 === 0 ? 0.03 : -0.03}>
              <Card className="h-full">
                <span className="grid h-10 w-10 place-items-center rounded-lg bg-rose-50 text-rose-500">
                  {tool.icon}
                </span>
                <p className="mt-4 text-[15px] font-bold text-brand-dark">{tool.name}</p>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">{tool.pain}</p>
              </Card>
            </ParallaxLabel>
          ))}
        </div>
      </div>
    </DiagonalSection>
  );
}

function Platform() {
  return (
    <DiagonalSection numeral="03" seam="rising-left" className="bg-white">
      <div className="container-ps pt-32 pb-20 md:pt-40 md:pb-28">
        <SectionHeading
          eyebrow="One platform"
          title="Every module your practice needs, already connected"
          subtitle="No exports, no re-keying, no second login — GST, books, payroll and clients share one source of truth."
        />
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => (
            <FocusReveal key={m.title}>
              <Card className="h-full">
                <span className="icon-pop inline-flex">
                  <IconBadge>{m.icon}</IconBadge>
                </span>
                <h3 className="mt-5 text-[17px] font-bold text-brand-dark">{m.title}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{m.desc}</p>
              </Card>
            </FocusReveal>
          ))}
        </div>
      </div>
    </DiagonalSection>
  );
}

function Trust() {
  const glow = useCursorGlow();
  return (
    <DiagonalSection id="security" numeral="04" seam="rising-right" className="bg-brand-dark text-white">
      <div className="container-ps pt-32 pb-20 md:pt-40 md:pb-28">
        <div
          className="relative overflow-hidden rounded-3xl border border-white/10 bg-white/[0.03] p-10 md:p-14"
          {...glow.handlers}
        >
          <div className="bg-grid absolute inset-0 opacity-70" />
          <div className="aurora aurora-2 -right-40 -top-40 h-[420px] w-[420px] opacity-60" />
          <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
          <div className="relative grid items-center gap-10 lg:grid-cols-[1.3fr_1fr]">
            <div>
              <span className="inline-flex items-center gap-2.5 text-[12px] font-semibold uppercase tracking-[0.15em] text-gold">
                <Lock size={15} /> Control &amp; trust
              </span>
              <h2 className="mt-4 font-display text-[30px] font-normal leading-tight tracking-tight md:text-[42px]">
                <KineticLine text="Nothing is filed without your click" />
              </h2>
              <FocusReveal className="mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
                <p>
                  AI prepares the working papers and flags what needs attention —
                  but the CA always makes the final call. No return, no challan and
                  no MCA form is ever submitted to a government portal
                  automatically.
                </p>
              </FocusReveal>
              <ul className="mt-6 space-y-3">
                {[
                  "Explicit CA confirmation on every government submission",
                  "Full audit log of who reviewed and filed what",
                  "Role-based access, MFA and data hosted in India",
                ].map((point) => (
                  <FocusReveal key={point}>
                    <li className="flex items-start gap-3 text-[15px] text-slate-200">
                      <Check size={18} className="mt-0.5 shrink-0 text-emerald-400" />
                      {point}
                    </li>
                  </FocusReveal>
                ))}
              </ul>
            </div>

            <FocusReveal>
              <Tilt max={6}>
                <div className="rounded-2xl border border-white/10 bg-brand-dark/60 p-6 backdrop-blur-sm">
                  <div className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-500/15 text-emerald-400">
                      <Shield size={20} />
                    </span>
                    <div>
                      <p className="text-[14px] font-bold text-white">GSTR-3B ready to file</p>
                      <p className="text-[12px] text-slate-400">Reviewed by CA · awaiting confirmation</p>
                    </div>
                  </div>
                  <div className="mt-5 rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/10">
                    <p className="text-[12px] text-slate-400">Tax payable</p>
                    <p className="text-[24px] font-bold text-white">₹ 2,48,600</p>
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
              </Tilt>
            </FocusReveal>
          </div>
        </div>
      </div>
    </DiagonalSection>
  );
}

function Stats() {
  return (
    <DiagonalSection numeral="05" seam="rising-left" className="bg-white">
      <div className="container-ps pt-32 pb-20 md:pt-40 md:pb-28">
        <SectionHeading
          title="The whole practice, finally visible"
          subtitle="Deadlines, revenue, clients and filings — one screen, not five tabs."
        />
        <SectionReveal className="mt-14 grid gap-8 rounded-3xl border border-ps-border bg-ps-bg p-10 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-[40px] font-bold tracking-tight text-brand md:text-[46px]">
                <CountUp to={s.target} suffix={s.suffix} duration={1400} />
              </p>
              <p className="mt-1 text-[13px] leading-relaxed text-slate-500">{s.label}</p>
            </div>
          ))}
        </SectionReveal>
        <div className="mt-10 text-center">
          <Button href="/products" variant="secondary" className="btn-shine">
            See everything inside PracticeSync
            <ArrowRight size={16} />
          </Button>
        </div>
      </div>
    </DiagonalSection>
  );
}

function Testimonial() {
  return (
    <DiagonalSection numeral="06" seam="rising-right" className="bg-ps-bg">
      <div className="container-ps pt-32 pb-20 md:pt-40 md:pb-28">
        <FocusReveal>
          <Tilt max={3}>
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
          </Tilt>
        </FocusReveal>
      </div>
    </DiagonalSection>
  );
}

function FinalCTA() {
  const glow = useCursorGlow();
  return (
    <DiagonalSection numeral="07" seam="rising-left" className="bg-brand text-white">
      <div className="relative" {...glow.handlers}>
        <div className="bg-grid absolute inset-0" />
        <ParallaxLabel factor={0.04} className="pointer-events-none absolute inset-0">
          <div className="aurora aurora-1 -left-32 -top-32 h-[420px] w-[420px] opacity-70" />
        </ParallaxLabel>
        <ParallaxLabel factor={-0.03} className="pointer-events-none absolute inset-0">
          <div className="aurora aurora-3 -bottom-40 -right-32 h-[460px] w-[460px] opacity-70" />
        </ParallaxLabel>
        <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
        <div className="container-ps relative pt-32 pb-24 text-center md:pt-40 md:pb-28">
          <FocusReveal>
            <h2 className="mx-auto max-w-2xl font-display text-[30px] font-normal leading-tight tracking-tight md:text-[46px]">
              Bring your whole practice into one place
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
              Start a free trial today, or talk to us about moving your firm across
              from Tally, ClearTax or Winman.
            </p>
          </FocusReveal>
          <FocusReveal>
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
          </FocusReveal>
        </div>
      </div>
    </DiagonalSection>
  );
}

export default function HomePage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      <IntroLoader onExit={() => {}} />
      <ScrollJack>
        <Hero />
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

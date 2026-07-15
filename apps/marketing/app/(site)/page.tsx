import Link from "next/link";
import { Button, Section, SectionHeading, Card, FeatureCard } from "@/components/ui";
import {
  ArrowRight,
  Check,
  Shield,
  Sparkles,
  TrendingUp,
  FileText,
  Users,
  Calculator,
  Receipt,
  Bot,
  Lock,
  Calendar,
  Star,
  Building,
} from "@/components/icons";
import { appLinks } from "@/lib/site";

const REPLACES = ["Tally", "ClearTax", "Winman", "WhatsApp", "Excel sheets"];

const WHY = [
  {
    icon: <FileText size={20} />,
    title: "All compliance in one place",
    desc: "GST, Income Tax, TDS and MCA — deadlines, working papers and filings tracked together, per client, all financial year long.",
  },
  {
    icon: <Sparkles size={20} />,
    title: "AI does the busywork",
    desc: "Auto-extract invoices, draft client replies, surface mismatches and never miss a due date — powered by AI, checked by you.",
  },
  {
    icon: <Shield size={20} />,
    title: "You always stay in control",
    desc: "Nothing is ever filed to a government portal automatically. Every submission waits for an explicit click from a CA.",
  },
  {
    icon: <Building size={20} />,
    title: "Built for India",
    desc: "GSTIN and PAN validation, FY April–March, advance-tax dates and Schedule III — the rules of Indian practice, baked in.",
  },
];

const MODULES = [
  {
    icon: <FileText size={20} />,
    title: "Compliance",
    desc: "GSTR-1 & 3B, ITR, TDS returns (24Q/26Q) and MCA filings with built-in due-date tracking.",
  },
  {
    icon: <Calculator size={20} />,
    title: "Accounting",
    desc: "Ledgers, trial balance, Schedule III mapping, fixed assets and year-end financial statements.",
  },
  {
    icon: <Receipt size={20} />,
    title: "Payroll",
    desc: "Salary runs, payslips and statutory PF/ESI/TDS — with employee self-service.",
  },
  {
    icon: <Users size={20} />,
    title: "Clients & CRM",
    desc: "A single record per client — entities, relationships, health, tasks and a secure portal.",
  },
  {
    icon: <Bot size={20} />,
    title: "AI Assistant",
    desc: "Ask about any client, draft notices and reminders, and get proactive practice insights.",
  },
  {
    icon: <TrendingUp size={20} />,
    title: "Practice analytics",
    desc: "Revenue, receivables, deadlines and client-health dashboards for the whole firm.",
  },
];

const STATS = [
  { value: "5-in-1", label: "Tools replaced by one platform" },
  { value: "GST · ITR · TDS · MCA", label: "Compliance covered end-to-end" },
  { value: "100%", label: "Filings reviewed by a CA before submit" },
  { value: "1 login", label: "For your whole practice" },
];

export default function HomePage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-brand-dark text-white">
        <div className="bg-grid absolute inset-0" />
        <div className="pointer-events-none absolute -right-24 top-1/2 h-[420px] w-[420px] -translate-y-1/2 rounded-full bg-brand-light/20 blur-[120px]" />
        <div className="container-ps relative grid items-center gap-14 py-20 md:py-28 lg:grid-cols-2">
          <div className="fade-up">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-[12px] font-medium text-brand-light">
              <Sparkles size={14} />
              AI-first practice management for Indian CAs
            </span>
            <h1 className="mt-6 text-[38px] font-bold leading-[1.1] tracking-tight md:text-[54px]">
              Run your entire practice from{" "}
              <span className="text-brand-light">one platform</span>
            </h1>
            <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-slate-300">
              PracticeSync replaces Tally, ClearTax, Winman and WhatsApp with a
              single AI-first workspace — compliance, accounting, payroll,
              clients and documents, all in one place.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Button href={appLinks.signup} external className="px-6 py-3.5">
                Start free trial
                <ArrowRight size={16} />
              </Button>
              <Button href="/products" variant="ghost-light" className="px-6 py-3.5">
                Explore the platform
              </Button>
            </div>
            <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-slate-400">
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

          {/* Stylised product preview */}
          <div className="fade-up relative">
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3 shadow-modal backdrop-blur-sm">
              <div className="rounded-xl bg-white p-5 text-brand-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      Compliance calendar
                    </p>
                    <p className="text-[15px] font-bold">Upcoming deadlines</p>
                  </div>
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand/[0.06] text-brand">
                    <Calendar size={18} />
                  </span>
                </div>
                <div className="mt-4 space-y-2.5">
                  {[
                    { t: "GSTR-3B — July", d: "20 Aug", c: "bg-amber-100 text-amber-700" },
                    { t: "GSTR-1 — July", d: "11 Aug", c: "bg-rose-100 text-rose-700" },
                    { t: "TDS 26Q — Q1", d: "31 Jul", c: "bg-emerald-100 text-emerald-700" },
                    { t: "Advance tax — Q2", d: "15 Sep", c: "bg-slate-100 text-slate-600" },
                  ].map((row) => (
                    <div
                      key={row.t}
                      className="flex items-center justify-between rounded-lg border border-ps-border bg-ps-bg px-3 py-2.5"
                    >
                      <span className="text-[13px] font-medium">{row.t}</span>
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${row.c}`}>
                        {row.d}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex items-center gap-3 rounded-lg bg-gold-surface px-3 py-2.5 ring-1 ring-gold/20">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-gold/15 text-gold">
                    <Sparkles size={15} />
                  </span>
                  <p className="text-[12px] leading-snug text-brand-dark">
                    <span className="font-semibold">AI insight:</span> 3 clients
                    have GSTR-1 vs 3B mismatches to review before filing.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Replaces the stack ───────────────────────────────────────────── */}
      <div className="border-y border-ps-border bg-white">
        <div className="container-ps flex flex-col items-center gap-6 py-8 md:flex-row md:justify-between">
          <p className="text-[14px] font-semibold text-slate-500">
            One platform instead of five
          </p>
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
            {REPLACES.map((name) => (
              <span
                key={name}
                className="rounded-full border border-ps-border bg-ps-bg px-3.5 py-1.5 text-[13px] font-medium text-slate-400 line-through decoration-rose-300/80"
              >
                {name}
              </span>
            ))}
            <ArrowRight size={18} className="mx-1 text-slate-300" />
            <span className="rounded-full bg-brand px-3.5 py-1.5 text-[13px] font-semibold text-white">
              PracticeSync
            </span>
          </div>
        </div>
      </div>

      {/* ── Why ──────────────────────────────────────────────────────────── */}
      <Section id="why" className="bg-ps-bg">
        <SectionHeading
          eyebrow="Why PracticeSync"
          title="Everything a modern CA firm needs, working together"
          subtitle="No more juggling tools, spreadsheets and WhatsApp groups. One source of truth for your clients, your compliance and your team."
        />
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {WHY.map((item) => (
            <FeatureCard key={item.title} icon={item.icon} title={item.title} desc={item.desc} />
          ))}
        </div>
      </Section>

      {/* ── Products preview ─────────────────────────────────────────────── */}
      <Section id="products" className="bg-white">
        <SectionHeading
          eyebrow="The platform"
          title="Six modules. One workspace."
          subtitle="Each part of your practice, connected — so a client's compliance, books, payroll and documents all live in the same place."
        />
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => (
            <FeatureCard key={m.title} icon={m.icon} title={m.title} desc={m.desc} />
          ))}
        </div>
        <div className="mt-10 text-center">
          <Button href="/products" variant="secondary">
            See everything inside PracticeSync
            <ArrowRight size={16} />
          </Button>
        </div>
      </Section>

      {/* ── Control / never auto-submit band ─────────────────────────────── */}
      <Section id="security" className="bg-brand-dark">
        <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-white/[0.03] p-10 md:p-14">
          <div className="bg-grid absolute inset-0 opacity-70" />
          <div className="relative grid items-center gap-10 lg:grid-cols-[1.3fr_1fr]">
            <div>
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
            </div>
            <div className="rounded-2xl border border-white/10 bg-brand-dark/60 p-6">
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
                  <span className="flex-1 rounded-lg bg-brand-light py-2.5 text-center text-[13px] font-semibold text-brand-dark">
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
          </div>
        </div>
      </Section>

      {/* ── Stats ────────────────────────────────────────────────────────── */}
      <Section className="bg-white">
        <div className="grid gap-8 rounded-2xl border border-ps-border bg-ps-bg p-10 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-[26px] font-bold tracking-tight text-brand md:text-[30px]">
                {s.value}
              </p>
              <p className="mt-2 text-[13px] leading-relaxed text-slate-500">{s.label}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ── Testimonial ──────────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
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
      </Section>

      {/* ── Final CTA ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-brand text-white">
        <div className="bg-grid absolute inset-0" />
        <div className="container-ps relative py-20 text-center md:py-24">
          <h2 className="mx-auto max-w-2xl text-[30px] font-bold leading-tight tracking-tight md:text-[42px]">
            Bring your whole practice into one place
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
            Start a free trial today, or talk to us about moving your firm across
            from Tally, ClearTax or Winman.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button href={appLinks.signup} external variant="light" className="px-6 py-3.5">
              Start free trial
              <ArrowRight size={16} />
            </Button>
            <Button href="/support" variant="ghost-light" className="px-6 py-3.5">
              Book a demo
            </Button>
          </div>
          <p className="mt-6 text-[13px] text-slate-400">
            Already using PracticeSync?{" "}
            <Link href="/access" className="font-semibold text-white underline-offset-4 hover:underline">
              Log in here
            </Link>
          </p>
        </div>
      </section>
    </>
  );
}

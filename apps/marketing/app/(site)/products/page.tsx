import { Panel, SerifHeading, CineReveal, Checklist, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { ArrowRight, Shield } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { appLinks } from "@/lib/site";

export const metadata = {
  title: "Products",
  description:
    "Explore the PracticeSync platform — compliance, accounting, payroll, clients & CRM, an AI assistant and practice analytics in one workspace built for Indian CA firms.",
};

const MODULES = [
  {
    eyebrow: "Compliance",
    title: "Every return and every deadline, tracked per client",
    desc: "GST, Income Tax, TDS and MCA — from working papers to the final filing — with a due-date tracker that watches the whole financial year for you.",
    points: [
      "GST returns — GSTR-1 (due the 11th), GSTR-3B (due the 20th) and the GSTR-9 annual return (due 31 December)",
      "Income Tax — ITR preparation, tax computation and advance-tax scheduling",
      "TDS returns — quarterly 24Q and 26Q",
      "MCA filings for companies and LLPs",
      "Built-in due-date tracking across every client, GSTIN and PAN",
      "Nothing is auto-submitted — a CA confirms every government filing",
    ],
  },
  {
    eyebrow: "Accounting",
    title: "Books that are ready for the balance sheet",
    desc: "From daily ledgers to signed year-end statements, structured the way Indian statutory accounts are meant to be.",
    points: [
      "Ledgers and a live trial balance",
      "Trial-balance import from your existing books",
      "Schedule III mapping for statutory financial statements",
      "Fixed-asset register with depreciation",
      "MSME dues tracker for reporting",
      "Year-end financial statements",
    ],
  },
  {
    eyebrow: "Payroll",
    title: "Salary runs with the statutory built in",
    desc: "Run payroll for your clients' teams, generate payslips and keep PF, ESI and TDS on salary in line — with a portal employees can use themselves.",
    points: [
      "Monthly salary runs",
      "Payslip generation",
      "Statutory PF, ESI and TDS on salary",
      "Employee self-service portal",
    ],
  },
  {
    eyebrow: "Clients & CRM",
    title: "One record for everything about a client",
    desc: "Every entity, relationship and engagement in a single place, with health scoring and a secure portal to collect documents and share updates.",
    points: [
      "One record per client, with all their entities together",
      "Entity relationships and ownership maps",
      "Client-health scoring",
      "Tasks and engagement letters",
      "Secure client portal for documents and updates",
    ],
  },
  {
    eyebrow: "AI Assistant & Document Intelligence",
    title: "An assistant that already knows your practice",
    desc: "Ask about any client in plain language, pull data straight out of invoices and documents, and let proactive insights surface what needs attention — always reviewed by you before anything is acted on.",
    points: [
      "Chat and ask about any client or engagement",
      "Auto-extract data from invoices and documents",
      "Draft client replies and notices",
      "Proactive insights and deadline reminders",
    ],
  },
  {
    eyebrow: "Practice analytics",
    title: "See how the whole firm is doing",
    desc: "Revenue, receivables and deadline load in one executive view — so partners can run the practice, not just the compliance.",
    points: [
      "Firm revenue and billing",
      "Receivables and collections",
      "Deadline load across the team",
      "Executive dashboard for partners",
    ],
  },
];

const SECURITY = [
  { title: "Data hosted in India", desc: "Your firm's and your clients' data is stored on infrastructure hosted in India." },
  { title: "Role-based access", desc: "Give every team member exactly the access their role needs — and nothing more." },
  { title: "Two-factor authentication", desc: "TOTP-based MFA protects every firm sign-in to the platform." },
  { title: "Full audit logs", desc: "A complete record of who viewed, edited and filed what, for every client." },
];

export default function ProductsPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Panel theme="dark" seam="none" numeral="01" numeralCorner="top-right">
        <SerifHeading
          eyebrow="The platform"
          lines={[
            { text: "One platform for" },
            { text: "every part of your practice.", italic: true },
          ]}
          subtitle="PracticeSync brings compliance, accounting, payroll, clients, documents and analytics into a single AI-first workspace — replacing Tally, ClearTax, Winman and WhatsApp for Indian CA firms."
        />
        <div className="mt-10 flex flex-wrap items-center gap-5">
          <Button href={appLinks.signup} external variant="accent" className="px-6 py-3.5">
            Start free trial
            <ArrowRight size={16} />
          </Button>
          <Button href="/pricing" variant="ghost-light" className="px-6 py-3.5">
            See plans &amp; pricing
          </Button>
        </div>
      </Panel>

      {/* ── Intro ────────────────────────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right">
        <SerifHeading
          eyebrow="Six modules, one workspace"
          theme="light"
          align="center"
          lines={[{ text: "Everything your practice" }, { text: "runs on, connected.", italic: true }]}
          subtitle="Compliance, accounting, payroll, clients, documents and analytics share one source of truth — so a client's returns, books and paperwork never live in separate tools again."
        />
      </Panel>

      {/* ── Modules ──────────────────────────────────────────────────────── */}
      {MODULES.map((m, i) => {
        const theme = i % 2 === 0 ? "dark" : "light";
        const seam = theme === "dark" ? "rising-left" : "rising-right";
        const flip = i % 2 === 1;
        const headTone = theme === "dark" ? "text-white" : "text-brand-dark";
        return (
          <Panel
            key={m.eyebrow}
            theme={theme}
            seam={seam}
            numeral={String(i + 1).padStart(2, "0")}
            numeralCorner={theme === "dark" ? "top-right" : "bottom-left"}
          >
            <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
              <Reveal variant={flip ? "right" : "left"} className={flip ? "lg:order-2" : ""}>
                <span
                  className={`block text-[12px] font-semibold uppercase tracking-[0.18em] ${
                    theme === "dark" ? "text-white/50" : "text-brand-dark/50"
                  }`}
                >
                  {m.eyebrow}
                </span>
                <h2 className={`mt-5 font-display text-[clamp(26px,3.4vw,42px)] font-normal leading-[1.15] tracking-[-0.015em] ${headTone}`}>
                  {m.title}
                </h2>
                <p className={`mt-5 max-w-[46ch] text-[16px] leading-[1.65] ${theme === "dark" ? "text-slate-300" : "text-slate-600"}`}>
                  {m.desc}
                </p>
              </Reveal>
              <Reveal variant={flip ? "left" : "right"} delay={120} className={flip ? "lg:order-1" : ""}>
                <p className={`mb-1 text-[12px] font-semibold uppercase tracking-[0.14em] ${theme === "dark" ? "text-white/40" : "text-slate-400"}`}>
                  What&apos;s included
                </p>
                <Checklist points={m.points} theme={theme} />
              </Reveal>
            </div>
          </Panel>
        );
      })}

      {/* ── Security & trust ─────────────────────────────────────────────── */}
      <Panel id="security" theme="light" seam="rising-right">
        <SerifHeading
          eyebrow="Security & trust"
          theme="light"
          lines={[{ text: "Your clients' data —" }, { text: "and your sign-off — protected.", italic: true }]}
          subtitle="PracticeSync is built around how Indian CA firms actually work: sensitive data stays in the country, access is controlled, everything is logged, and no filing ever leaves your hands without your confirmation."
        />

        <div className="mt-12 grid gap-x-12 gap-y-8 sm:grid-cols-2">
          {SECURITY.map((s, i) => (
            <Reveal key={s.title} variant="up" delay={i * 90}>
              <div className="border-t border-slate-900/10 pt-5">
                <h3 className="font-display text-[22px] italic text-brand-dark">{s.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{s.desc}</p>
              </div>
            </Reveal>
          ))}
        </div>

        {/* Never auto-submit — the principle at the heart of the platform. */}
        <CineReveal delay={120}>
          <div className="mt-12 flex flex-col items-start gap-5 rounded-2xl border border-gold/30 bg-gold/[0.06] p-6 sm:flex-row sm:items-center md:p-8">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-gold/15 text-gold ring-1 ring-gold/25">
              <Shield size={22} />
            </span>
            <p className="text-[15px] leading-relaxed text-brand-dark md:text-[16px]">
              <span className="font-semibold">Nothing is auto-submitted.</span>{" "}
              Every GST return, income-tax filing, TDS statement and MCA form waits for an explicit
              confirmation click from a Chartered Accountant before it is sent to any government portal.
            </p>
          </div>
        </CineReveal>
      </Panel>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CineCTA />
    </div>
  );
}

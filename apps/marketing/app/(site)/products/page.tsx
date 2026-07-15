import {
  PageHero,
  Section,
  SectionHeading,
  Card,
  IconBadge,
  Button,
  CTASection,
} from "@/components/ui";
import {
  ArrowRight,
  Check,
  FileText,
  Calculator,
  Receipt,
  Users,
  Bot,
  BarChart,
  Globe,
  Lock,
  Shield,
} from "@/components/icons";
import { appLinks } from "@/lib/site";

export const metadata = {
  title: "Products",
  description:
    "Explore the PracticeSync platform — compliance, accounting, payroll, clients & CRM, an AI assistant and practice analytics in one workspace built for Indian CA firms.",
};

// Six modules that make up the platform. Each renders as an alternating
// two-column section: a left-aligned SectionHeading paired with a Card that
// lists the sub-features. Kept data-driven so the rhythm stays consistent.
const MODULES = [
  {
    icon: <FileText size={20} />,
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
    icon: <Calculator size={20} />,
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
    icon: <Receipt size={20} />,
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
    icon: <Users size={20} />,
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
    icon: <Bot size={20} />,
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
    icon: <BarChart size={20} />,
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
  {
    icon: <Globe size={20} />,
    title: "Data hosted in India",
    desc: "Your firm's and your clients' data is stored on infrastructure hosted in India.",
  },
  {
    icon: <Users size={20} />,
    title: "Role-based access",
    desc: "Give every team member exactly the access their role needs — and nothing more.",
  },
  {
    icon: <Lock size={20} />,
    title: "Two-factor authentication",
    desc: "TOTP-based MFA protects every firm sign-in to the platform.",
  },
  {
    icon: <FileText size={20} />,
    title: "Full audit logs",
    desc: "A complete record of who viewed, edited and filed what, for every client.",
  },
];

export default function ProductsPage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <PageHero
        eyebrow="The platform"
        title="One platform for every part of your practice"
        subtitle="PracticeSync brings compliance, accounting, payroll, clients, documents and analytics into a single AI-first workspace — replacing Tally, ClearTax, Winman and WhatsApp for Indian CA firms."
      />

      {/* ── Intro + early CTA ────────────────────────────────────────────── */}
      <Section className="bg-white">
        <SectionHeading
          eyebrow="Six modules, one workspace"
          title="Everything your practice runs on, connected"
          subtitle="Compliance, accounting, payroll, clients, documents and analytics share one source of truth — so a client's returns, books and paperwork never live in separate tools again."
        />
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button href={appLinks.signup} external className="px-6 py-3.5">
            Start free trial
            <ArrowRight size={16} />
          </Button>
          <Button href="/pricing" variant="secondary" className="px-6 py-3.5">
            See plans &amp; pricing
          </Button>
        </div>
      </Section>

      {/* ── Modules ──────────────────────────────────────────────────────── */}
      {MODULES.map((m, i) => {
        const flip = i % 2 === 1;
        return (
          <Section
            key={m.eyebrow}
            className={i % 2 === 0 ? "bg-ps-bg" : "bg-white"}
          >
            <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
              <div className={flip ? "lg:order-2" : ""}>
                <IconBadge>{m.icon}</IconBadge>
                <div className="mt-6">
                  <SectionHeading
                    align="left"
                    eyebrow={m.eyebrow}
                    title={m.title}
                    subtitle={m.desc}
                  />
                </div>
              </div>
              <Card className={`lg:p-8 ${flip ? "lg:order-1" : ""}`}>
                <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  What&apos;s included
                </p>
                <ul className="mt-5 space-y-3.5">
                  {m.points.map((point) => (
                    <li
                      key={point}
                      className="flex items-start gap-3 text-[15px] leading-relaxed text-slate-700"
                    >
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand/[0.06] text-brand ring-1 ring-brand/10">
                        <Check size={13} />
                      </span>
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          </Section>
        );
      })}

      {/* ── Security & trust ─────────────────────────────────────────────── */}
      <Section id="security" className="bg-brand-dark">
        <SectionHeading
          tone="dark"
          eyebrow="Security & trust"
          title="Your clients' data — and your sign-off — protected"
          subtitle="PracticeSync is built around how Indian CA firms actually work: sensitive data stays in the country, access is controlled, everything is logged, and no filing ever leaves your hands without your confirmation."
        />

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {SECURITY.map((s) => (
            <div
              key={s.title}
              className="rounded-2xl border border-white/10 bg-white/[0.03] p-6"
            >
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                {s.icon}
              </span>
              <h3 className="mt-5 text-[16px] font-bold text-white">{s.title}</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                {s.desc}
              </p>
            </div>
          ))}
        </div>

        {/* Never auto-submit — the principle at the heart of the platform. */}
        <div className="mt-6 flex flex-col items-start gap-5 rounded-2xl border border-gold/30 bg-gold/[0.06] p-6 sm:flex-row sm:items-center md:p-8">
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-gold/15 text-gold ring-1 ring-gold/25">
            <Shield size={22} />
          </span>
          <p className="text-[15px] leading-relaxed text-slate-200 md:text-[16px]">
            <span className="font-semibold text-white">
              Nothing is auto-submitted.
            </span>{" "}
            Every GST return, income-tax filing, TDS statement and MCA form waits
            for an explicit confirmation click from a Chartered Accountant before
            it is sent to any government portal.
          </p>
        </div>
      </Section>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CTASection />
    </>
  );
}

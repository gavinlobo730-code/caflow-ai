import type { Metadata } from "next";
import type { ReactNode } from "react";
import {
  Section,
  SectionHeading,
  Button,
  Card,
  IconBadge,
  PageHero,
  CTASection,
} from "@/components/ui";
import { Reveal } from "@/components/motion";
import {
  Calendar,
  ArrowUpRight,
  Receipt,
  TrendingUp,
  Calculator,
  FileText,
  ArrowRight,
  Shield,
  Check,
} from "@/components/icons";

export const metadata: Metadata = {
  title: "Resources",
  description:
    "Quick-reference guides, filing calendars and key GST, TDS and income-tax due dates for Indian CA firms — from the PracticeSync team.",
};

// Each guide card is a self-contained quick reference: the key facts live on the
// card itself, so nothing links out and nothing is pending. Statutory dates are
// legally significant — reproduced exactly, never altered.
const GUIDES: {
  icon: ReactNode;
  title: string;
  desc: string;
  points: string[];
}[] = [
  {
    icon: <Calendar size={20} />,
    title: "The GST filing rhythm",
    desc: "The monthly cadence every GST-registered client runs on, all financial year long.",
    points: [
      "GSTR-1 — 11th of the following month",
      "GSTR-3B — 20th of the following month",
      "GSTR-9 annual return — 31 December",
    ],
  },
  {
    icon: <ArrowUpRight size={20} />,
    title: "Moving from Tally",
    desc: "Bring a client's books across without losing history — in three passes.",
    points: [
      "Export ledgers, masters and the trial balance",
      "Import masters, then map account groups",
      "Load opening balances and reconcile the TB",
    ],
  },
  {
    icon: <Receipt size={20} />,
    title: "TDS returns 24Q & 26Q",
    desc: "The two quarterly statements most practices file, and how they differ.",
    points: [
      "24Q — TDS on salaries · 26Q — non-salary payments",
      "Due the 31st of the month after each quarter ends",
      "Reconcile deductee entries against Form 26AS",
    ],
  },
  {
    icon: <TrendingUp size={20} />,
    title: "Advance-tax instalments",
    desc: "The cumulative schedule to plan client cash flows around.",
    points: [
      "15 June — 15% · 15 September — 45%",
      "15 December — 75% · 15 March — 100%",
      "Estimate early; interest under 234B/234C hurts",
    ],
  },
  {
    icon: <Calculator size={20} />,
    title: "Schedule III statements",
    desc: "From trial balance to Companies Act-compliant financials.",
    points: [
      "Map every TB head to a Schedule III line item",
      "Generate the balance sheet and P&L from the mapping",
      "Keep notes and disclosures tied to the same source",
    ],
  },
  {
    icon: <FileText size={20} />,
    title: "Year-end close, in order",
    desc: "The 31 March sequence that keeps audits calm.",
    points: [
      "Reconcile banks, GST ledgers and Form 26AS",
      "Book provisions, depreciation and statutory dues",
      "Lock the year before the first audit query lands",
    ],
  },
];

// Indicative statutory due dates. These are legally significant — the strings are
// reproduced exactly and must not be altered.
const ADVANCE_TAX = [
  { d: "15 June", p: "15%" },
  { d: "15 September", p: "45%" },
  { d: "15 December", p: "75%" },
  { d: "15 March", p: "100%" },
];

const CALENDAR: {
  name: string;
  freq: string;
  icon: ReactNode;
  due: ReactNode;
}[] = [
  {
    name: "GSTR-1",
    freq: "Monthly",
    icon: <Receipt size={16} />,
    due: "11th of the following month",
  },
  {
    name: "GSTR-3B",
    freq: "Monthly",
    icon: <Receipt size={16} />,
    due: "20th of the following month",
  },
  {
    name: "GSTR-9 (annual return)",
    freq: "Annual",
    icon: <FileText size={16} />,
    due: "31 December",
  },
  {
    name: "TDS returns (24Q / 26Q)",
    freq: "Quarterly",
    icon: <Calculator size={16} />,
    due: "31st of the month following the quarter end",
  },
  {
    name: "Advance tax",
    freq: "Quarterly",
    icon: <TrendingUp size={16} />,
    due: (
      <div className="flex flex-wrap gap-1.5">
        {ADVANCE_TAX.map((i) => (
          <span
            key={i.d}
            className="inline-flex items-center gap-1.5 rounded-full border border-ps-border bg-ps-bg px-2.5 py-1 text-[12px] font-medium text-brand-dark"
          >
            <span className="whitespace-nowrap">{i.d}</span>
            <span className="font-semibold text-brand">{i.p}</span>
          </span>
        ))}
      </div>
    ),
  },
];

export default function ResourcesPage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <PageHero
        eyebrow="Resources"
        title="Guides & tools for Indian CA practices"
        subtitle="Practical references for running a CA firm — filing rhythms, migration steps and close checklists, plus a quick-reference due-date table you can keep close at hand."
      />

      {/* ── Quick-reference guides ───────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="Quick references"
            title="The essentials, on one card each"
            subtitle="The filings, migrations and close processes practices deal with every year — condensed to the facts you actually reach for."
          />
        </Reveal>
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {GUIDES.map((g, i) => (
            <Reveal key={g.title} delay={(i % 3) * 110 + Math.floor(i / 3) * 60}>
              <Card className="h-full">
                <span className="icon-pop inline-flex">
                  <IconBadge>{g.icon}</IconBadge>
                </span>
                <h3 className="mt-5 text-[17px] font-bold text-brand-dark">{g.title}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{g.desc}</p>
                <ul className="mt-4 space-y-2 border-t border-ps-border pt-4">
                  {g.points.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-[13px] leading-relaxed text-slate-600">
                      <Check size={14} className="mt-0.5 shrink-0 text-emerald-500" />
                      {p}
                    </li>
                  ))}
                </ul>
              </Card>
            </Reveal>
          ))}
        </div>
        <Reveal delay={150}>
          <div className="mt-12 flex flex-col items-center gap-4 text-center">
            <p className="text-[14px] text-slate-500">
              PracticeSync tracks all of this automatically — per client, per deadline,
              all financial year long.
            </p>
            <Button href="/products" variant="secondary">
              Explore the platform
              <ArrowRight size={16} />
            </Button>
          </div>
        </Reveal>
      </Section>

      {/* ── Compliance calendar ──────────────────────────────────────────── */}
      <Section id="calendar" className="scroll-mt-24 bg-white">
        <Reveal variant="blur">
          <SectionHeading
            eyebrow="Compliance calendar"
            title="Key statutory due dates at a glance"
            subtitle="The deadlines every Indian practice tracks, in one place. PracticeSync watches these for each client so nothing slips through."
          />
        </Reveal>

        <Reveal variant="scale" delay={120}>
          <div className="mt-12 overflow-x-auto rounded-2xl border border-ps-border bg-white shadow-card">
            <table className="w-full min-w-[720px] border-collapse text-left">
              <thead>
                <tr className="border-b border-ps-border bg-ps-bg">
                  <th className="px-6 py-4 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    Return / obligation
                  </th>
                  <th className="px-6 py-4 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    Frequency
                  </th>
                  <th className="px-6 py-4 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    Statutory due date
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {CALENDAR.map((row) => (
                  <tr key={row.name} className="transition-colors duration-300 hover:bg-ps-bg/60">
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-3 text-[14px] font-bold text-brand-dark">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand/[0.06] text-brand ring-1 ring-brand/10">
                          {row.icon}
                        </span>
                        {row.name}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex whitespace-nowrap rounded-full bg-brand/[0.06] px-2.5 py-1 text-[12px] font-semibold text-brand">
                        {row.freq}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-[14px] leading-relaxed text-slate-700">
                      {row.due}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>

        <Reveal delay={200}>
          <p className="mx-auto mt-5 flex max-w-2xl items-start justify-center gap-2 text-center text-[13px] leading-relaxed text-slate-500">
            <Shield size={15} className="mt-0.5 shrink-0 text-gold" />
            Indicative statutory due dates — always confirm the latest CBIC/CBDT
            notifications.
          </p>
        </Reveal>
      </Section>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CTASection />
    </>
  );
}

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
import {
  Calendar,
  ArrowUpRight,
  Receipt,
  TrendingUp,
  Calculator,
  FileText,
  ArrowRight,
  Shield,
} from "@/components/icons";

export const metadata: Metadata = {
  title: "Resources",
  description:
    "Guides, filing calendars and a quick-reference table of key GST, TDS and income-tax due dates for Indian CA firms — from the PracticeSync team.",
};

// Guides are previews only — the site has no article pages yet, so every card is
// informational (non-clickable) and carries a "Coming soon" pill. No dead links.
const GUIDES = [
  {
    icon: <Calendar size={20} />,
    title: "GST filing calendar FY 2026-27",
    desc: "Month-by-month GSTR-1 and GSTR-3B due dates for the financial year, mapped to every client.",
  },
  {
    icon: <ArrowUpRight size={20} />,
    title: "Moving from Tally to PracticeSync",
    desc: "Export ledgers and masters from Tally and bring your books across without losing history.",
  },
  {
    icon: <Receipt size={20} />,
    title: "TDS returns 24Q & 26Q explained",
    desc: "When each quarterly statement is due, what goes in it, and how to reconcile against Form 26AS.",
  },
  {
    icon: <TrendingUp size={20} />,
    title: "Advance-tax planning for clients",
    desc: "Estimate liability and schedule the 15 Jun / 15 Sep / 15 Dec / 15 Mar instalments with room to spare.",
  },
  {
    icon: <Calculator size={20} />,
    title: "Schedule III financial statements",
    desc: "Map your trial balance to Schedule III and generate compliant balance sheets and P&L.",
  },
  {
    icon: <FileText size={20} />,
    title: "Year-end close checklist",
    desc: "A step-by-step close for 31 March — reconciliations, provisions and statutory dues, nothing missed.",
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
        subtitle="Practical references for running a CA firm — filing calendars, migration guides and compliance checklists, plus a quick-reference due-date table you can keep close at hand."
      />

      {/* ── Guides ───────────────────────────────────────────────────────── */}
      <Section className="bg-ps-bg">
        <SectionHeading
          eyebrow="Guides"
          title="Guides for running an Indian CA firm"
          subtitle="Deep-dives on the filings, migrations and close processes practices deal with every year. We're writing these now — here's what's on the way."
        />
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {GUIDES.map((g) => (
            <Card key={g.title}>
              <div className="flex items-start justify-between gap-3">
                <IconBadge>{g.icon}</IconBadge>
                <span className="inline-flex items-center rounded-full bg-ps-muted px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 ring-1 ring-ps-border">
                  Coming soon
                </span>
              </div>
              <h3 className="mt-5 text-[17px] font-bold text-brand-dark">{g.title}</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{g.desc}</p>
            </Card>
          ))}
        </div>
        <div className="mt-10 flex flex-col items-center gap-4 text-center">
          <p className="text-[14px] text-slate-500">
            Guides are on the way. In the meantime, see how PracticeSync handles all of
            this for you.
          </p>
          <Button href="/products" variant="secondary">
            Explore the platform
            <ArrowRight size={16} />
          </Button>
        </div>
      </Section>

      {/* ── Compliance calendar ──────────────────────────────────────────── */}
      <Section id="calendar" className="scroll-mt-24 bg-white">
        <SectionHeading
          eyebrow="Compliance calendar"
          title="Key statutory due dates at a glance"
          subtitle="The deadlines every Indian practice tracks, in one place. PracticeSync watches these for each client so nothing slips through."
        />

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
                <tr key={row.name}>
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

        <p className="mx-auto mt-5 flex max-w-2xl items-start justify-center gap-2 text-center text-[13px] leading-relaxed text-slate-500">
          <Shield size={15} className="mt-0.5 shrink-0 text-gold" />
          Indicative statutory due dates — always confirm the latest CBIC/CBDT
          notifications.
        </p>
      </Section>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CTASection />
    </>
  );
}

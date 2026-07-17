import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Panel, SerifHeading, CineReveal, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
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
import { instrumentSerif, manrope } from "@/lib/fonts";

export const metadata: Metadata = {
  title: "Resources",
  description:
    "Quick-reference guides, filing calendars and key GST, TDS and income-tax due dates for Indian CA firms — from the PracticeSync team.",
};

// Each guide card is a self-contained quick reference: the key facts live on the
// card itself, so nothing links out and nothing is pending. Statutory dates are
// legally significant — reproduced exactly, never altered.
const GUIDES: { icon: ReactNode; title: string; desc: string; points: string[] }[] = [
  {
    icon: <Calendar size={18} />,
    title: "The GST filing rhythm",
    desc: "The monthly cadence every GST-registered client runs on, all financial year long.",
    points: [
      "GSTR-1 — 11th of the following month",
      "GSTR-3B — 20th of the following month",
      "GSTR-9 annual return — 31 December",
    ],
  },
  {
    icon: <ArrowUpRight size={18} />,
    title: "Moving from Tally",
    desc: "Bring a client's books across without losing history — in three passes.",
    points: [
      "Export ledgers, masters and the trial balance",
      "Import masters, then map account groups",
      "Load opening balances and reconcile the TB",
    ],
  },
  {
    icon: <Receipt size={18} />,
    title: "TDS returns 24Q & 26Q",
    desc: "The two quarterly statements most practices file, and how they differ.",
    points: [
      "24Q — TDS on salaries · 26Q — non-salary payments",
      "Due the 31st of the month after each quarter ends",
      "Reconcile deductee entries against Form 26AS",
    ],
  },
  {
    icon: <TrendingUp size={18} />,
    title: "Advance-tax instalments",
    desc: "The cumulative schedule to plan client cash flows around.",
    points: [
      "15 June — 15% · 15 September — 45%",
      "15 December — 75% · 15 March — 100%",
      "Estimate early; interest under 234B/234C hurts",
    ],
  },
  {
    icon: <Calculator size={18} />,
    title: "Schedule III statements",
    desc: "From trial balance to Companies Act-compliant financials.",
    points: [
      "Map every TB head to a Schedule III line item",
      "Generate the balance sheet and P&L from the mapping",
      "Keep notes and disclosures tied to the same source",
    ],
  },
  {
    icon: <FileText size={18} />,
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

const CALENDAR: { name: string; freq: string; icon: ReactNode; due: ReactNode }[] = [
  { name: "GSTR-1", freq: "Monthly", icon: <Receipt size={16} />, due: "11th of the following month" },
  { name: "GSTR-3B", freq: "Monthly", icon: <Receipt size={16} />, due: "20th of the following month" },
  { name: "GSTR-9 (annual return)", freq: "Annual", icon: <FileText size={16} />, due: "31 December" },
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
            className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-2.5 py-1 text-[12px] font-medium text-white"
          >
            <span className="whitespace-nowrap">{i.d}</span>
            <span className="font-semibold text-brand-light">{i.p}</span>
          </span>
        ))}
      </div>
    ),
  },
];

export default function ResourcesPage() {
  return (
    <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Panel theme="dark" seam="none">
        <CineReveal>
          <SerifHeading
            eyebrow="Resources"
            lines={[{ text: "Guides & tools for" }, { text: "Indian CA practices.", italic: true }]}
            subtitle="Practical references for running a CA firm — filing rhythms, migration steps and close checklists, plus a quick-reference due-date table you can keep close at hand."
          />
        </CineReveal>
      </Panel>

      {/* ── Quick-reference guides ───────────────────────────────────────── */}
      <Panel theme="light" seam="rising-right">
        <CineReveal>
          <SerifHeading
            eyebrow="Quick references"
            theme="light"
            lines={[{ text: "The essentials," }, { text: "on one card each.", italic: true }]}
            subtitle="The filings, migrations and close processes practices deal with every year — condensed to the facts you actually reach for."
          />
        </CineReveal>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {GUIDES.map((g, i) => (
            <Reveal key={g.title} variant="up" delay={(i % 3) * 100}>
              <div className="flex h-full flex-col rounded-2xl border border-slate-900/10 bg-white p-6">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand/[0.06] text-brand ring-1 ring-brand/10">
                  {g.icon}
                </span>
                <h3 className="mt-5 font-display text-[22px] italic leading-snug text-brand-dark">{g.title}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{g.desc}</p>
                <ul className="mt-4 space-y-2 border-t border-slate-900/10 pt-4">
                  {g.points.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-[13px] leading-relaxed text-slate-600">
                      <Check size={14} className="mt-0.5 shrink-0 text-brand" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          ))}
        </div>
        <CineReveal delay={120}>
          <div className="mt-12 flex flex-col items-center gap-4 text-center">
            <p className="text-[14px] text-slate-500">
              PracticeSync tracks all of this automatically — per client, per deadline, all financial year long.
            </p>
            <Button href="/products" variant="secondary">
              Explore the platform <ArrowRight size={16} />
            </Button>
          </div>
        </CineReveal>
      </Panel>

      {/* ── Compliance calendar ──────────────────────────────────────────── */}
      <Panel id="calendar" theme="dark" seam="rising-left" innerClassName="scroll-mt-24">
        <CineReveal>
          <SerifHeading
            eyebrow="Compliance calendar"
            lines={[{ text: "Key statutory due" }, { text: "dates at a glance.", italic: true }]}
            subtitle="The deadlines every Indian practice tracks, in one place. PracticeSync watches these for each client so nothing slips through."
          />
        </CineReveal>

        <Reveal variant="scale" delay={120}>
          <div className="mt-12 overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.03]">
            <table className="w-full min-w-[720px] border-collapse text-left">
              <thead>
                <tr className="border-b border-white/10">
                  {["Return / obligation", "Frequency", "Statutory due date"].map((h) => (
                    <th key={h} className="px-6 py-4 text-[12px] font-semibold uppercase tracking-[0.12em] text-white/45">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {CALENDAR.map((row) => (
                  <tr key={row.name} className="transition-colors duration-300 hover:bg-white/[0.04]">
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-3 text-[14px] font-semibold text-white">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-light/10 text-brand-light ring-1 ring-white/10">
                          {row.icon}
                        </span>
                        {row.name}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex whitespace-nowrap rounded-full bg-brand-light/10 px-2.5 py-1 text-[12px] font-semibold text-brand-light">
                        {row.freq}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-[14px] leading-relaxed text-slate-200">{row.due}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>

        <Reveal variant="up" delay={200}>
          <p className="mx-auto mt-5 flex max-w-2xl items-start justify-center gap-2 text-center text-[13px] leading-relaxed text-slate-400">
            <Shield size={15} className="mt-0.5 shrink-0 text-gold" />
            Indicative statutory due dates — always confirm the latest CBIC/CBDT notifications.
          </p>
        </Reveal>
      </Panel>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CineCTA />
    </div>
  );
}

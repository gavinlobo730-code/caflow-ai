"use client";

import { useState, type ReactNode } from "react";
import {
  FileText,
  Calculator,
  Landmark,
  Users,
  Building,
  Boxes,
  Workflow,
  Sparkles,
} from "../icons";
import { Reveal } from "../motion";

/**
 * The platform ecosystem (brief §5).
 *
 * "Do not present products as a disconnected grid of ordinary SaaS cards. Make
 * the platform feel like one connected system. Show PracticeSync at the centre,
 * with modules connected around it."
 *
 * So it is a ring, not a grid, and choosing a module changes what the panel
 * beside it says — which is the §5 requirement that each module carry "a small,
 * polished UI preview or interaction rather than only an icon and paragraph".
 * The deeper screen recreations live in the showcase section further down; this
 * one is about the SHAPE of the platform, and the interaction is what makes the
 * connectedness something the reader does rather than reads.
 *
 * WHAT EACH MODULE SAYS IS CHECKABLE. Every line below names a route, a table
 * or a rule that exists in this repo today. The five subsystems the site was
 * silent about until the September 2026 truth pass — banking, sales and
 * purchases, inventory, workflow automation, the Tally migration — are in here
 * deliberately, because their absence was a bigger content gap than anything
 * the brief raised.
 *
 * The ring is SVG and the labels are DOM, for the reason the hero's cards are:
 * text in a canvas is text nobody can select, translate or hear read out.
 */

type Module = {
  key: string;
  label: string;
  icon: ReactNode;
  headline: string;
  body: string;
  points: string[];
};

const MODULES: Module[] = [
  {
    key: "compliance",
    label: "Compliance",
    icon: <FileText size={16} />,
    headline: "Every return, computed from the books",
    body: "GST, income tax, TDS and MCA in one calendar, per client, per GSTIN, per PAN — with the working papers behind each figure.",
    points: [
      "GSTR-1, GSTR-3B and the GSTR-9 annual return",
      "GSTR-2B reconciliation against the purchase register",
      "ITR preparation against the department's own JSON schemas",
      "Quarterly 24Q, 26Q and 27Q, with the 2026 Act's renumbered forms handled beside the old ones",
    ],
  },
  {
    key: "accounting",
    label: "Accounting",
    icon: <Calculator size={16} />,
    headline: "A ledger that cannot quietly stop balancing",
    body: "Double entry with one posting path. Every accounting event in the product — sales, purchases, banking, payroll, depreciation — is written by the same kernel, which asserts the entry balances before it inserts.",
    points: [
      "Trial balance, P&L, balance sheet and cash flow",
      "Schedule III mapping, with both MCA ageing schedules",
      "Corrections are append-only reversals, so the audit trail always foots",
      "Every rupee in integer paise — never floating point",
    ],
  },
  {
    key: "banking",
    label: "Banking",
    icon: <Landmark size={16} />,
    headline: "A statement line arrives as a voucher",
    body: "Upload a statement and each line comes back with a proposed entry already on it — Receipt, Payment or Contra, decided by direction rather than chosen. You review a page at a time and pass the ones that are right.",
    points: [
      "CSV and XLSX, parsed and normalised on the server",
      "Every draft graded ready or proposed, with a reason sentence",
      "Pass the ready ones in bulk — chunked and resumable",
      "Rules a manager marks trusted post their lines unattended",
    ],
  },
  {
    key: "payroll",
    label: "Payroll",
    icon: <Users size={16} />,
    headline: "Salary runs with the statutory built in",
    body: "The monthly cycle, the leaver and the statutory registers — with an employee portal your client's staff use themselves, so nobody emails HR for a payslip.",
    points: [
      "EPF on the Code on Social Security wage base, ESI, and §192 TDS",
      "Employee portal: payslips, leave, Form 12BB and tax deducted",
      "Full-and-final settlement, gratuity and leave encashment",
      "Where a state's professional tax is not modelled, the run says so rather than deducting nothing silently",
    ],
  },
  {
    key: "clients",
    label: "Clients",
    icon: <Building size={16} />,
    headline: "One record for everything about a client",
    body: "Every entity, relationship and engagement together, with a secure portal for collecting documents and sharing what you have done.",
    points: [
      "All of a client's entities under one record",
      "Ownership maps and cross-client relationships",
      "Engagement letters the client signs on a link",
      "Client portal for documents, invoices and updates",
    ],
  },
  {
    key: "inventory",
    label: "Sales, purchases & stock",
    icon: <Boxes size={16} />,
    headline: "The documents the returns are made of",
    body: "Invoices, bills, credit and debit notes, and the stock they move — with GST computed per line so the books and the return agree by construction rather than by reconciliation.",
    points: [
      "Per-line GST, including §15(3)(a) invoice discounts",
      "TDS resolved by section as a purchase bill is entered",
      "Closing stock as at any date, summed from the movements themselves",
      "E-invoice IRN and e-way bill records, prepared for the IRP",
    ],
  },
  {
    key: "workflow",
    label: "Workflow",
    icon: <Workflow size={16} />,
    headline: "The parts of the month that are the same every month",
    body: "Templates that fire on a trigger and walk a job through its steps, with approvals routed by role wherever a human has to look.",
    points: [
      "Workflow templates with a record of every run",
      "Approvals routed by role — Partner, Manager, Executive, Reviewer",
      "Task templates for recurring engagements",
      "Deadline reminders and team notifications",
    ],
  },
  {
    key: "ai",
    label: "AI assistant",
    icon: <Sparkles size={16} />,
    headline: "Intelligence across the practice, not a chatbot in a corner",
    body: "Ask about any client in plain language, pull figures straight out of a bill, and let the deadline and health signals surface what needs attention — reviewed by you before anything is acted on.",
    points: [
      "Extracts data from typed PDFs and photographed bills",
      "Answers about any client, engagement or deadline",
      "Drafts client replies and responses to notices",
      "Surfaces what needs attention; never acts on a filing by itself",
    ],
  },
];

/** Where each node sits on the ring, in degrees clockwise from twelve. */
const ANGLE_STEP = 360 / MODULES.length;

function nodePosition(i: number, radius: number) {
  const deg = i * ANGLE_STEP - 90;
  const rad = (deg * Math.PI) / 180;
  return { x: 50 + Math.cos(rad) * radius, y: 50 + Math.sin(rad) * radius };
}

export function Ecosystem() {
  const [active, setActive] = useState(0);
  const chosen = MODULES[active];

  return (
    <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] lg:gap-16">
      {/* ── The ring ────────────────────────────────────────────────────── */}
      <Reveal variant="left">
        <div className="relative mx-auto aspect-square w-full max-w-[420px]">
          <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden="true">
            <circle cx="50" cy="50" r="36" fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="0.4" />
            <circle cx="50" cy="50" r="15" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="0.4" />
            {MODULES.map((m, i) => {
              const p = nodePosition(i, 36);
              const on = i === active;
              return (
                <line
                  key={m.key}
                  x1={p.x}
                  y1={p.y}
                  x2="50"
                  y2="50"
                  stroke={on ? "#AFD2FA" : "rgba(175,210,250,0.22)"}
                  strokeWidth={on ? 0.8 : 0.4}
                  vectorEffect="non-scaling-stroke"
                  style={{ transition: "stroke 300ms ease, stroke-width 300ms ease" }}
                />
              );
            })}
          </svg>

          {/* Centre */}
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
            <span className="grid h-[68px] w-[68px] place-items-center rounded-full border border-white/15 bg-[#0b1430] shadow-[0_0_44px_rgba(88,122,217,0.4)]">
              <svg width="30" height="30" viewBox="0 0 64 64" fill="none">
                <circle cx="32" cy="32" r="24" strokeWidth="3" stroke="rgba(255,255,255,0.2)" />
                <circle
                  cx="32"
                  cy="32"
                  r="24"
                  strokeWidth="5"
                  strokeLinecap="round"
                  className="logo-arc"
                  stroke="#7fa0ec"
                  strokeDasharray="29.3 121.5"
                />
                <path
                  d="M20,33 L28,41 L45,22"
                  strokeWidth="6.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  stroke="#ffffff"
                />
              </svg>
            </span>
            <span className="mt-2.5 block text-[11px] font-semibold uppercase tracking-[0.14em] text-white/45">
              PracticeSync
            </span>
          </div>

          {/* Nodes */}
          {MODULES.map((m, i) => {
            const p = nodePosition(i, 36);
            const on = i === active;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => setActive(i)}
                onMouseEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                aria-pressed={on}
                className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-brand-light focus-visible:ring-offset-2 focus-visible:ring-offset-brand-dark"
                style={{ left: `${p.x}%`, top: `${p.y}%` }}
              >
                <span
                  className={`grid h-11 w-11 place-items-center rounded-full border transition-all duration-300 ${
                    on
                      ? "scale-110 border-brand-light/60 bg-brand-light/20 text-white"
                      : "border-white/10 bg-white/[0.05] text-white/60 hover:border-white/30 hover:text-white"
                  }`}
                >
                  {m.icon}
                </span>
                <span className="sr-only">{m.label}</span>
              </button>
            );
          })}
        </div>

        {/* Names, below the ring — a label per node would collide at this size. */}
        <div className="mt-8 flex flex-wrap justify-center gap-2">
          {MODULES.map((m, i) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setActive(i)}
              className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                i === active
                  ? "border-brand-light/50 bg-brand-light/15 text-white"
                  : "border-white/10 text-white/50 hover:border-white/25 hover:text-white/80"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </Reveal>

      {/* ── The selected module ─────────────────────────────────────────── */}
      <Reveal variant="right" delay={120}>
        {/* min-height stops the panel resizing as modules are chosen, which
            would drag the ring around beside it. */}
        <div className="min-h-[360px] rounded-2xl border border-white/10 bg-white/[0.03] p-7 md:p-9">
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-brand-light/80">
            {chosen.label}
          </p>
          <h3 className="mt-4 font-display text-[clamp(24px,2.6vw,32px)] leading-[1.2] text-white">
            {chosen.headline}
          </h3>
          <p className="mt-4 max-w-[52ch] text-[15.5px] leading-[1.7] text-slate-300">
            {chosen.body}
          </p>
          <ul className="mt-7 space-y-0">
            {chosen.points.map((p) => (
              <li
                key={p}
                className="flex items-start gap-3 border-t border-white/10 py-3.5 text-[14.5px] leading-relaxed text-slate-300 last:border-b"
              >
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand-light" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </Reveal>
    </div>
  );
}

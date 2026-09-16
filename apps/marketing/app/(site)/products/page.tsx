import { Panel, SerifHeading, CineReveal, Checklist, CineCTA } from "@/components/cinematic";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui";
import { ArrowRight, Shield } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { appLinks } from "@/lib/site";

export const metadata = {
  title: "Products",
  description:
    "Explore the PracticeSync platform — compliance, accounting, sales & purchases, banking, inventory, payroll and the employee portal, clients & CRM, an AI assistant, workflow automation and practice analytics in one workspace built for Indian CA firms.",
};

// One entry per shipped subsystem. Five were added in the September 2026 truth
// pass — banking, sales & purchases, inventory, workflow automation and the
// Tally migration were all live in the product and entirely absent from this
// page, which is a bigger content gap than anything in the redesign brief.
//
// Every claim here is checked against a route or a service in this repo. The
// verb for anything statutory is PREPARE: PracticeSync computes the return and
// produces the file, and a human uploads and signs it on the government portal.
// Filing through the software needs GSP (GSTN) and ERI (CBDT) registration,
// neither of which is held — see docs/compliance/07-getting-permission-to-file.md.
const MODULES = [
  {
    eyebrow: "Compliance",
    title: "Every return computed from the books, and every deadline tracked",
    desc: "GST, Income Tax, TDS and MCA — from working papers to a file-ready return — with a due-date tracker that watches the whole financial year for you.",
    points: [
      "GST returns — GSTR-1 (due the 11th), GSTR-3B (due the 20th) and the GSTR-9 annual return (due 31 December), computed from your ledgers",
      "GSTR-2B reconciliation — which bills your supplier has not filed, and how much input credit to hold back",
      "Income Tax — ITR preparation against the department's own JSON schemas, tax computation and advance-tax scheduling",
      "TDS — quarterly 24Q, 26Q and 27Q statements, with the 2026 Act's renumbered forms handled alongside the old ones",
      "MCA and ROC forms for companies and LLPs, dated from the AGM",
      "Built-in due-date tracking across every client, GSTIN and PAN",
      "You file and sign on the portal, then record the ARN here — and the period locks",
    ],
  },
  {
    eyebrow: "Accounting",
    title: "Books that are ready for the balance sheet",
    desc: "A double-entry general ledger where every posting balances and nothing posted can be quietly rewritten — through to signed year-end statements, structured the way Indian statutory accounts are meant to be.",
    points: [
      "Ledgers and a live trial balance",
      "Trial-balance import from your existing books",
      "Schedule III mapping for statutory financial statements, with both ageing notes",
      "Fixed-asset register with Schedule II depreciation",
      "MSME dues tracker, for the §43B(h) disclosure",
      "Corrections are append-only reversals, so the audit trail always foots",
    ],
  },
  {
    eyebrow: "Sales & purchases",
    title: "The documents the returns are made of",
    desc: "Raise invoices, record bills and issue credit and debit notes — with GST computed per line, in integer paise, so the books and the return agree by construction rather than by reconciliation.",
    points: [
      "Sales invoices with per-line GST and §15(3)(a) invoice discounts",
      "Purchase bills, with TDS resolved by section as you enter them",
      "Credit and debit notes under §34",
      "E-invoice IRN and e-way bill records, prepared for the IRP",
      "Customer and supplier masters, with GSTIN checked to its check digit",
    ],
  },
  {
    eyebrow: "Banking",
    title: "A bank statement becomes a voucher, not a spreadsheet",
    desc: "Upload a statement and every line arrives with a proposed entry already on it — Receipt, Payment or Contra, decided by direction. You review a page of them at a time and pass the ones that are right.",
    points: [
      "CSV and XLSX statement import, parsed and normalised on the server",
      "A drafted voucher on every line, graded ready or proposed with a reason",
      "Pass the ready ones in bulk — chunked and resumable",
      "Rules you can mark trusted, so recurring lines post themselves",
      "Bank book and reconciliation per account",
    ],
  },
  {
    eyebrow: "Inventory",
    title: "Stock that ties back to the control account",
    desc: "Item-wise movements that post to the ledger as they happen, so closing stock as at any date is a figure you can stand behind rather than one you assemble at year end.",
    points: [
      "Item master with a movement ledger",
      "Closing stock as at any date, summed from the movements themselves",
      "Every movement posts its own journal, so the Inventory control account agrees",
    ],
  },
  {
    eyebrow: "Payroll & the employee portal",
    title: "Salary runs with the statutory built in — and a portal your client's staff use themselves",
    desc: "Run payroll for your clients' teams, generate payslips and keep PF, ESI and TDS on salary in line. Employees get their own secure login for payslips, leave and their tax declaration, so nobody emails HR for a salary slip again.",
    points: [
      "Monthly salary runs and payslip generation",
      "EPF on the Code on Social Security wage base, ESI, and §192 TDS on salary",
      "Employee portal — payslips to download, leave balance, and the tax deducted so far",
      "Form 12BB tax declarations filed by the employee, not retyped by you",
      "Full-and-final settlement, gratuity and leave encashment",
      "Where a state's professional tax or LWF is not modelled, the run says so instead of deducting nothing silently",
    ],
  },
  {
    eyebrow: "Clients & CRM",
    title: "One record for everything about a client",
    desc: "Every entity, relationship and engagement in a single place, with health scoring and a secure portal to collect documents and share updates.",
    points: [
      "One record per client, with all their entities together",
      "Entity relationships and ownership maps",
      "Client-health scoring and lifecycle tracking",
      "Tasks and engagement letters, signed by the client on a link",
      "Secure client portal for documents and updates",
    ],
  },
  {
    eyebrow: "AI Assistant & Document Intelligence",
    title: "An assistant that already knows your practice",
    desc: "Ask about any client in plain language, pull data straight out of invoices and documents, and let proactive insights surface what needs attention — always reviewed by you before anything is acted on.",
    points: [
      "Chat and ask about any client or engagement",
      "Auto-extract data from invoices and bills — typed PDFs and photographed ones",
      "Draft client replies and notices",
      "Proactive insights and deadline reminders",
    ],
  },
  {
    eyebrow: "Workflow automation",
    title: "The routine work of a practice, running itself",
    desc: "Templates that fire on a trigger and walk a job through its steps, with approvals where a human has to look. The parts of the month that are the same every month stop needing somebody to remember them.",
    points: [
      "Workflow templates with triggers, and a record of every run",
      "Approval steps routed by role",
      "Task templates for recurring engagements",
      "Deadline reminders and team notifications",
    ],
  },
  {
    eyebrow: "Practice analytics",
    title: "See how the whole firm is doing",
    desc: "Revenue, receivables and deadline load in one executive view — so partners can run the practice, not just the compliance.",
    points: [
      "Firm revenue and billing",
      "Receivables, collections and time recorded",
      "Deadline load and work allocation across the team",
      "Executive dashboard for partners",
    ],
  },
  {
    eyebrow: "Moving from Tally",
    title: "Bring the history with you",
    desc: "A staged import that parses, validates and shows you a preview before anything is written — and rolls the whole batch back if the preview is wrong.",
    points: [
      "Ledgers, journals, customers, vendors, masters and opening balances",
      "Parse → validate → preview → import, with the preview before the write",
      "Roll a completed batch back if it went in wrong",
      "Imported entries post through the same ledger as everything else",
    ],
  },
];

const SECURITY = [
  { title: "Data hosted in India", desc: "Your firm's and your clients' data is stored on infrastructure hosted in India." },
  { title: "Role-based access", desc: "Give every team member exactly the access their role needs — and nothing more." },
  { title: "Two-factor authentication", desc: "TOTP-based MFA protects every firm sign-in to the platform." },
  { title: "Full audit logs", desc: "A complete record of who viewed, edited, approved and recorded as filed — for every client." },
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
          <Button href="/demo" variant="accent" className="px-6 py-3.5">
            Book a demo
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
          eyebrow="Eleven modules, one workspace"
          theme="light"
          align="center"
          lines={[{ text: "Everything your practice" }, { text: "runs on, connected.", italic: true }]}
          subtitle="Compliance, accounting, sales and purchases, banking, inventory, payroll, clients, documents and analytics share one ledger and one source of truth — so a client's returns, books and paperwork never live in separate tools again."
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
            {/* Reworded in the truth pass: the old line said returns "are sent to
                any government portal", which implied the software transmits them.
                It does not — filing needs GSP and ERI registration that is not
                held (docs/compliance/07). PracticeSync prepares; a CA files. */}
            <p className="text-[15px] leading-relaxed text-brand-dark md:text-[16px]">
              <span className="font-semibold">Nothing leaves your hands on its own.</span>{" "}
              PracticeSync computes the GST return, the income-tax return, the TDS statement and the MCA
              form from your books and hands you a file that is ready to go. A Chartered Accountant
              uploads and signs it on the government portal — and then records it here, which is what
              locks the period. No return is ever transmitted by the software.
            </p>
          </div>
        </CineReveal>
      </Panel>

      {/* ── Closing CTA ──────────────────────────────────────────────────── */}
      <CineCTA />
    </div>
  );
}

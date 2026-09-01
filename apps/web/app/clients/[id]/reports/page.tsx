"use client";

import { useRouter } from "next/navigation";
import {
  BarChart3, Scale, ClipboardList, TrendingUp, Receipt,
  Landmark, Users, Boxes, ArrowRight,
} from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

/**
 * The client's reporting hub.
 *
 * THIS IS A DIRECTORY, NOT A SECOND COPY OF ANYTHING. Every entry opens the
 * screen that already computes that report. A reporting section that
 * re-derived the same numbers beside the module that owns them is how two
 * P&Ls end up disagreeing six months later, and the one a CA quotes to their
 * client is whichever they opened last.
 *
 * A previous "Reports" section was removed from this sidebar for being a
 * static "Coming in Phase 1" card with nothing behind it — a permanent dead
 * link on every client. That is why this one ships pointing only at reports
 * that exist TODAY, and says plainly which are not built yet rather than
 * implying they are a click away.
 *
 * WHEN A REPORT IS BUILT TO LIVE HERE rather than inside a module, it must
 * obey the rule in CLAUDE.md: no report may fetch rows proportional to
 * transaction volume. It reads a pre-aggregated table maintained by triggers
 * (account_period_balances) or a SQL function that aggregates server-side
 * (public.cash_flow_report). Fetching raw rows and looping in Python is not an
 * option — it is what made cash-flow take 54 seconds on one real client.
 */

interface ReportLink {
  id: string;
  title: string;
  desc: string;
  href: string;          // relative to /clients/{id}/
  statute?: string;
}

interface ReportGroup {
  id: string;
  title: string;
  desc: string;
  icon: typeof BarChart3;
  reports: ReportLink[];
}

const GROUPS: ReportGroup[] = [
  {
    id: "financial",
    title: "Financial statements",
    desc: "Schedule III statements, exportable to XLSX or shareable to the client portal",
    icon: Scale,
    reports: [
      { id: "pl", title: "Profit & Loss", desc: "Statement of P&L for the year",
        href: "accounting?tab=pl", statute: "Schedule III Part II" },
      { id: "bs", title: "Balance Sheet", desc: "Balance Sheet as at year end",
        href: "accounting?tab=balance-sheet", statute: "Schedule III Part I" },
      { id: "tb", title: "Trial Balance", desc: "Unadjusted trial balance",
        href: "accounting?tab=trial" },
      { id: "cf", title: "Cash Flow", desc: "Indirect-method cash flow statement",
        href: "accounting?tab=cashflow", statute: "AS-3" },
      { id: "ageing", title: "Ageing schedules",
        desc: "Trade receivables and trade payables ageing — the notes to the balance sheet, and the open documents behind them",
        href: "reports/ageing", statute: "Schedule III (2021 amendment)" },
      { id: "trend", title: "Multi-year trend",
        desc: "Three to ten years of Schedule III captions and the clause (Q) ratios side by side, with the movement between them — a management view, not the statements",
        href: "reports/trend" },
      { id: "ratios", title: "Ratio analysis",
        desc: "The eleven prescribed ratios, both years, with the numerator and denominator disclosed and 25% movements flagged",
        href: "reports/ratios", statute: "Schedule III clause (Q)" },
      { id: "hub", title: "Export & share", desc: "Print, XLSX export, and reports already shared to the portal",
        href: "accounting?tab=reports" },
    ],
  },
  {
    id: "ledgers",
    title: "Ledgers and balances",
    desc: "Account-level detail behind the statements",
    icon: ClipboardList,
    reports: [
      { id: "coa", title: "Chart of Accounts", desc: "Every account, its group and its balance",
        href: "accounting?tab=coa" },
      { id: "journal", title: "Journal", desc: "Entries written by hand — auto-posted entries appear per account, not here",
        href: "accounting?tab=journal" },
      { id: "verify", title: "Verify Books", desc: "Integrity checks across the ledger",
        href: "accounting?tab=verify-books" },
    ],
  },
  {
    id: "gst",
    title: "GST",
    desc: "Returns computed from the books, and the reconciliations behind them",
    icon: Receipt,
    reports: [
      { id: "gst", title: "GST returns & reconciliation", desc: "GSTR-1, GSTR-3B, 2A/2B matching, ITC reversal register",
        href: "compliance", statute: "CGST Act §37, §39" },
    ],
  },
  {
    id: "tax",
    title: "Income tax",
    desc: "Computation, ITR preparation and TDS credits",
    icon: TrendingUp,
    reports: [
      { id: "comp", title: "Tax computation", desc: "Income, disallowances, deductions and losses",
        href: "tax/computation" },
      { id: "26as", title: "26AS reconciliation", desc: "TDS credits matched against the books",
        href: "tax/26as", statute: "IT Act §285BB" },
    ],
  },
  {
    id: "operational",
    title: "Operational",
    desc: "Banking, payroll, inventory and fixed assets",
    icon: Landmark,
    reports: [
      { id: "bank", title: "Bank reconciliation", desc: "Reconciliation status per bank account",
        href: "bank" },
      { id: "payroll", title: "Salary register & statutory summary", desc: "Per-run salary register, PF/ESI/PT/TDS summary",
        href: "payroll" },
      { id: "assets", title: "Fixed asset register", desc: "Additions, disposals and depreciation",
        href: "fixed-assets", statute: "Schedule II" },
      { id: "stock", title: "Stock ledger", desc: "Movement and valuation by item",
        href: "inventory" },
    ],
  },
];

/** Named honestly. These do NOT link anywhere, because they do not exist.
 *
 *  "Aged receivables & payables" used to be on this list and was wrong twice
 *  over: customer_statement_service.ar_aging and its AP mirror have existed for
 *  a long time and were made query-bounded by migration 278, and nothing in
 *  this app had ever called them — the computation was built and unreachable.
 *  They are now under Ageing schedules above, beside the statutory note that
 *  migration 303 added. Which is the lesson worth leaving here: check whether a
 *  report is missing a SCREEN before recording it as missing entirely. */
const NOT_BUILT: { title: string; why: string }[] = [
  { title: "Unbilled dues",
    why: "Schedule III requires them disclosed separately under both ageing schedules. Nothing in this platform holds an unbilled revenue or accrued-liability document keyed to a party, so the ageing report says so rather than showing a zero." },
];

export default function ClientReportsPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id is the literal "_placeholder". useClientNav reads the real
  // UUID out of window.location.
  const { clientId } = useClientNav();
  const router = useRouter();

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-[#1E293B]">Reports</h2>
        <p className="text-xs text-[#94A3B8] mt-0.5">
          Everything this client&apos;s books can tell you, in one place. Each report opens
          where it is computed, so there is only ever one set of figures.
        </p>
      </div>

      {GROUPS.map((group) => {
        const GroupIcon = group.icon;
        return (
          <div key={group.id} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg border border-blue-100 bg-blue-50 flex items-center justify-center flex-shrink-0">
                <GroupIcon size={15} className="text-blue-600" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#334155]">{group.title}</p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">{group.desc}</p>
              </div>
            </div>
            <div className="divide-y divide-gray-50">
              {group.reports.map((r) => (
                <button
                  key={r.id}
                  onClick={() => router.push(`/clients/${clientId}/${r.href}`)}
                  className="w-full px-5 py-3 flex items-center gap-4 hover:bg-[#F8FAFC] text-left transition-colors group"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-medium text-[#1E293B]">{r.title}</p>
                      {r.statute && (
                        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[#F1F5F9] text-[#64748B]">
                          {r.statute}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-[#64748B] mt-0.5">{r.desc}</p>
                  </div>
                  <ArrowRight size={14} className="text-[#CBD5E1] group-hover:text-[#64748B] flex-shrink-0" />
                </button>
              ))}
            </div>
          </div>
        );
      })}

      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] flex items-center justify-center flex-shrink-0">
            <Boxes size={15} className="text-[#94A3B8]" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-[#334155]">Not built yet</p>
            <p className="text-[10px] text-[#94A3B8] mt-0.5">
              Listed so the gap is visible. These are not links.
            </p>
          </div>
        </div>
        <div className="divide-y divide-gray-50">
          {NOT_BUILT.map((n) => (
            <div key={n.title} className="px-5 py-3">
              <p className="text-xs font-medium text-[#64748B]">{n.title}</p>
              <p className="text-[11px] text-[#94A3B8] mt-0.5">{n.why}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-start gap-2.5 bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-4 py-3">
        <Users size={14} className="text-[#94A3B8] flex-shrink-0 mt-0.5" />
        <p className="text-[11px] text-[#64748B]">
          Sharing a report with the client sends it to their portal — see{" "}
          <button
            onClick={() => router.push(`/clients/${clientId}/accounting?tab=reports`)}
            className="text-blue-600 hover:underline font-medium"
          >
            Export &amp; share
          </button>
          . Firm-wide reporting across every client lives outside this workspace, under Reports in the main sidebar.
        </p>
      </div>
    </div>
  );
}

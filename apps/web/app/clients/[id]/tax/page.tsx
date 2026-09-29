"use client";

import { useRouter } from "next/navigation";
import {
  Calculator, FileText, RefreshCw, ArrowRight, AlertTriangle,
  Landmark, TrendingUp, Percent, Layers, ArrowLeftRight, ShieldCheck,
  ClipboardList, FileSearch, Bell,
} from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

const MODULES = [
  {
    id: "computation",
    title: "Tax Computation",
    desc: "Versioned computation workspace — income, disallowances, deductions, losses",
    icon: Calculator,
    href: "tax/computation",
    badge: "IT Act §40A, §43B, §80C",
  },
  {
    id: "filing",
    title: "ITR Preparation",
    desc: "Workflow: Draft → Review → Partner Review → Ready for Filing → Filed",
    icon: FileText,
    href: "tax/filing",
    // Form-agnostic on purpose — GET /api/itr/forms serves all seven forms
    // (domain/income_tax/itr_json.ITR_FORMS), and naming only four of them
    // here read as though ITR-1/2/4 (most of a practice's salaried and
    // presumptive filings) were not handled.
    badge: "ITR-1 to ITR-7",
  },
  {
    id: "26as",
    title: "26AS Reconciliation",
    desc: "Upload 26AS, match TDS credits, detect mismatches against books",
    icon: RefreshCw,
    href: "tax/26as",
    badge: "IT Act §285BB",
  },
];

// The nine tools below live under the firm-wide /income-tax/* tree, not under
// /clients/[id]/tax/* — each picks its client from its own page-local picker
// rather than from the URL segment. Linking with ?client_id= and having the
// target page read it (sweep-income-tax-hub-04) is what lets a CA reach them
// without leaving this client's workspace and re-picking the same client.
const FIRM_TOOLS = [
  {
    id: "advance-tax",
    title: "Advance Tax",
    desc: "Instalments, §234A/B/C interest and self-assessment challans",
    icon: Landmark,
    path: "/income-tax/advance-tax",
    badge: "§207/208/234A-C",
  },
  {
    id: "capital-gains",
    title: "Capital Gains",
    desc: "Calculator and register — indexation, CII, s.54 reinvestment exemptions",
    icon: TrendingUp,
    path: "/income-tax/capital-gains",
    badge: "§45, §48, §54",
  },
  {
    id: "deductions",
    title: "Chapter VI-A / Deductions",
    desc: "80C/80D/80G/80TTA, HRA and s.24(b) planning with regime comparison",
    icon: Percent,
    path: "/income-tax/deductions",
    badge: "Chapter VI-A",
  },
  {
    id: "section-32",
    title: "Section 32 Depreciation",
    desc: "Block-of-assets depreciation, separate from the Schedule II charge",
    icon: Layers,
    path: "/income-tax/section-32",
    badge: "IT Act §32",
  },
  {
    id: "book-to-tax",
    title: "Book to Tax Bridge",
    desc: "Profit per the accounts, down to taxable income, one adjustment at a time",
    icon: ArrowLeftRight,
    path: "/income-tax/book-to-tax",
    badge: "Book-to-tax",
  },
  {
    id: "tax-audit",
    title: "Tax Audit",
    desc: "§44AB applicability, Form 3CA/3CB tracking and due dates",
    icon: ShieldCheck,
    path: "/income-tax/tax-audit",
    badge: "IT Act §44AB",
  },
  {
    id: "form-3cd",
    title: "Form 3CD",
    desc: "Statement of particulars annexed to the tax audit report",
    icon: ClipboardList,
    path: "/income-tax/tax-audit/form-3cd",
    badge: "Form 3CD",
  },
  {
    id: "ais",
    title: "AIS Reconciliation",
    desc: "Review the Annual Information Statement against the books",
    icon: FileSearch,
    path: "/income-tax/ais",
    badge: "IT Act §285BB",
  },
  {
    id: "notices",
    title: "Notices",
    desc: "IT notices, response deadlines and uploaded documents",
    icon: Bell,
    path: "/income-tax/notices",
    badge: "§143, §148, §271",
  },
];

export default function TaxPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id is the literal string "_placeholder" — every card below then
  // pushed to /clients/_placeholder/tax/... , a dead route. useClientNav reads
  // the real UUID out of window.location.
  const { clientId } = useClientNav();
  const router = useRouter();

  function openFirmTool(path: string) {
    router.push(`${path}?client_id=${encodeURIComponent(clientId)}`);
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-ps-ink">Income Tax</h2>
        <p className="text-xs text-ps-hint mt-0.5">
          Computation workspace, ITR preparation, and 26AS reconciliation
        </p>
      </div>

      <div className="flex items-center gap-2.5 bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
        <AlertTriangle size={14} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs font-medium text-amber-800">
          CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal.
          All computations and filings require explicit CA confirmation.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {MODULES.map((mod) => {
          const Icon = mod.icon;
          return (
            <button
              key={mod.id}
              onClick={() => router.push(`/clients/${clientId}/${mod.href}`)}
              className="w-full bg-white rounded-xl border border-ps-border px-5 py-4 flex items-center gap-4 hover:bg-ps-bg hover:border-ps-border-strong text-left transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg border border-blue-100 bg-blue-50 flex items-center justify-center flex-shrink-0">
                <Icon size={18} className="text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold text-ps-ink">{mod.title}</p>
                  <span className="text-3xs font-medium px-2 py-0.5 rounded-full bg-ps-muted text-ps-label">
                    {mod.badge}
                  </span>
                </div>
                <p className="text-2xs text-ps-label mt-0.5">{mod.desc}</p>
              </div>
              <ArrowRight size={14} className="text-ps-disabled flex-shrink-0 group-hover:text-ps-hint" />
            </button>
          );
        })}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-ps-ink">More income tax tools</h2>
        <p className="text-xs text-ps-hint mt-0.5">
          Firm-wide tools, opened with this client already selected
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {FIRM_TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <button
              key={tool.id}
              onClick={() => openFirmTool(tool.path)}
              className="w-full bg-white rounded-xl border border-ps-border px-4 py-3 flex items-center gap-3 hover:bg-ps-bg hover:border-ps-border-strong text-left transition-colors group"
            >
              <div className="w-9 h-9 rounded-lg border border-ps-border bg-ps-muted flex items-center justify-center flex-shrink-0">
                <Icon size={16} className="text-brand" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold text-ps-ink">{tool.title}</p>
                  <span className="text-3xs font-medium px-2 py-0.5 rounded-full bg-ps-muted text-ps-label">
                    {tool.badge}
                  </span>
                </div>
                <p className="text-2xs text-ps-label mt-0.5">{tool.desc}</p>
              </div>
              <ArrowRight size={13} className="text-ps-disabled flex-shrink-0 group-hover:text-ps-hint" />
            </button>
          );
        })}
      </div>

      <div className="bg-ps-bg border border-ps-border rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-ps-body">Tax Filing Rules</p>
        <ul className="text-2xs text-ps-label space-y-1">
          <li>• Advance tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)</li>
          <li>• ITR due date: 31st July (individuals), 31st October (audited entities)</li>
          <li>• Tax audit report (§44AB) due date: 30th September — one month before the ITR itself</li>
          <li>• ITR due date: 30th November where a §92E transfer-pricing report is required</li>
          <li>• All monetary values computed in integer paise — never floating point</li>
          <li>• Every adjustment requires evidence document attachment</li>
          <li>• Partner review mandatory before marking Ready for Filing</li>
        </ul>
      </div>
    </div>
  );
}

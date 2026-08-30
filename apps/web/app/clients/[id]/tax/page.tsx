"use client";

import { useRouter } from "next/navigation";
import { Calculator, FileText, RefreshCw, ArrowRight, AlertTriangle } from "lucide-react";
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
    badge: "ITR-3 / ITR-5 / ITR-6 / ITR-7",
  },
  {
    id: "26as",
    title: "26AS Reconciliation",
    desc: "Upload 26AS, match TDS credits, detect mismatches against books",
    icon: RefreshCw,
    href: "tax/26as",
    badge: "IT Act §203AA",
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

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-[#1E293B]">Income Tax</h2>
        <p className="text-xs text-[#94A3B8] mt-0.5">
          Computation workspace, ITR preparation, and 26AS reconciliation
        </p>
      </div>

      <div className="flex items-center gap-2.5 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
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
              className="w-full bg-white rounded-xl border border-[#F1F5F9] px-5 py-4 flex items-center gap-4 hover:bg-[#F8FAFC] hover:border-[#E2E8F0] text-left transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg border border-blue-100 bg-blue-50 flex items-center justify-center flex-shrink-0">
                <Icon size={18} className="text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold text-[#1E293B]">{mod.title}</p>
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[#F1F5F9] text-[#64748B]">
                    {mod.badge}
                  </span>
                </div>
                <p className="text-[11px] text-[#64748B] mt-0.5">{mod.desc}</p>
              </div>
              <ArrowRight size={14} className="text-[#CBD5E1] flex-shrink-0 group-hover:text-[#94A3B8]" />
            </button>
          );
        })}
      </div>

      <div className="bg-[#F8FAFC] border border-[#F1F5F9] rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-[#334155]">Tax Filing Rules</p>
        <ul className="text-[11px] text-[#64748B] space-y-1">
          <li>• Advance tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)</li>
          <li>• ITR due date: 31st July (individuals), 31st October (audited entities)</li>
          <li>• All monetary values computed in integer paise — never floating point</li>
          <li>• Every adjustment requires evidence document attachment</li>
          <li>• Partner review mandatory before marking Ready for Filing</li>
        </ul>
      </div>
    </div>
  );
}

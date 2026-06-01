"use client";
export const runtime = "edge";

import { useState } from "react";
import { FileText, Clock, CheckCircle2, Send } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { AIInsightBanner } from "@/components/ai-insight-banner";

const STATS = [
  { label: "ITRs Due", value: "6", icon: Clock, iconColor: "text-amber-600", iconBg: "bg-amber-50", alert: true },
  { label: "Awaiting Documents", value: "4", icon: FileText, iconColor: "text-purple-600", iconBg: "bg-purple-50" },
  { label: "Ready for Review", value: "2", icon: CheckCircle2, iconColor: "text-green-600", iconBg: "bg-green-50" },
  { label: "Ready to File", value: "1", icon: Send, iconColor: "text-blue-600", iconBg: "bg-blue-50" },
];

const TABS = ["Individuals", "Businesses", "AIS Review", "Form 26AS Review", "Tax Planning"];

const ITRS = [
  { client: "Rajesh Kumar Sharma", pan: "ABCRS1234D", type: "ITR-1", ay: "2025-26", due: "31 Jul 2025", status: "Awaiting Docs", regime: "New" },
  { client: "Joshi Textiles Pvt Ltd", pan: "AAJCS3329B", type: "ITR-6", ay: "2025-26", due: "31 Oct 2025", status: "Draft", regime: "Old" },
  { client: "Priya Patel", pan: "AAPCS4229B", type: "ITR-2", ay: "2025-26", due: "31 Jul 2025", status: "Ready for Review", regime: "New" },
  { client: "Mehta Consulting LLP", pan: "AACCS7829B", type: "ITR-5", ay: "2025-26", due: "31 Oct 2025", status: "Ready to File", regime: "Old" },
  { client: "Vijay Desai", pan: "AADCS9929B", type: "ITR-1", ay: "2025-26", due: "31 Jul 2025", status: "Awaiting Docs", regime: "New" },
];

const statusStyle: Record<string, string> = {
  "Draft": "bg-gray-100 text-gray-600",
  "Awaiting Docs": "bg-purple-100 text-purple-700",
  "Review Required": "bg-amber-100 text-amber-700",
  "Ready for Review": "bg-amber-100 text-amber-700",
  "Ready to File": "bg-green-100 text-green-700",
};

const INSIGHTS = [
  { type: "high" as const, message: "AIS mismatch detected for Rajesh Kumar Sharma — income discrepancy of ₹45,000", action: "Review AIS data before filing ITR" },
  { type: "medium" as const, message: "4 individual clients have ITR due in 60 days — begin document collection now" },
  { type: "info" as const, message: "New regime is beneficial for 3 clients based on deduction analysis" },
];

export default function IncomeTaxPage() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Income Tax</h1>
        <p className="text-sm text-gray-500 mt-0.5">ITR management — AY 2025-26</p>
      </div>

      <AIInsightBanner insights={INSIGHTS} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {STATS.map((s) => <StatCard key={s.label} {...s} />)}
      </div>

      {/* Status flow */}
      <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Filing Status Flow</p>
        <div className="flex items-center gap-2 flex-wrap">
          {["Draft", "Review Required", "Ready to File"].map((step, i, arr) => (
            <div key={step} className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-600 bg-gray-50 border border-gray-200 px-3 py-1 rounded-full">{step}</span>
              {i < arr.length - 1 && <span className="text-gray-300 text-sm">→</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)} className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {tab}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">ITR Tracker — {TABS[activeTab]}</h2>
        </div>
        <div className="divide-y divide-gray-50">
          {ITRS.map((itr, i) => (
            <div key={i} className="flex items-center gap-4 px-5 py-3.5">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900">{itr.client}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{itr.pan} · {itr.type}</p>
              </div>
              <div className="text-right hidden sm:block">
                <p className="text-xs text-gray-500">AY {itr.ay}</p>
                <p className="text-xs text-gray-400 mt-0.5">Due {itr.due}</p>
              </div>
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-50 text-gray-500 border border-gray-200 shrink-0">{itr.regime} Regime</span>
              <span className={`status-pill shrink-0 ${statusStyle[itr.status] ?? "bg-gray-100 text-gray-600"}`}>
                {itr.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

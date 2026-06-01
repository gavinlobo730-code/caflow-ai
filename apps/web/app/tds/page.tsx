"use client";
export const runtime = "edge";

import { useState } from "react";
import { Clock, FileText, AlertTriangle } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { AIInsightBanner } from "@/components/ai-insight-banner";

const STATS = [
  { label: "Returns Due", value: "4", icon: Clock, iconColor: "text-amber-600", iconBg: "bg-amber-50", alert: true },
  { label: "Certificates Pending", value: "12", icon: FileText, iconColor: "text-purple-600", iconBg: "bg-purple-50" },
  { label: "Reconciliation Issues", value: "2", icon: AlertTriangle, iconColor: "text-red-600", iconBg: "bg-red-50", alert: true },
];

const TABS = ["Quarterly Returns", "Form 16", "Form 16A", "TDS Reconciliation"];

const RETURNS = [
  { client: "Joshi Textiles Pvt Ltd", pan: "AAJCS3329B", form: "26Q", quarter: "Q4 FY 2024-25", due: "31 May 2025", status: "Filed", challan: "OLTAS/2025/001234" },
  { client: "Mehta Consulting LLP", pan: "AACCS7829B", form: "26Q", quarter: "Q4 FY 2024-25", due: "31 May 2025", status: "Pending", challan: null },
  { client: "Sharma Enterprises", pan: "AABCS1429B", form: "24Q", quarter: "Q4 FY 2024-25", due: "31 May 2025", status: "Pending", challan: null },
  { client: "Patel & Sons", pan: "AAPCS4229B", form: "26Q", quarter: "Q1 FY 2025-26", due: "31 Jul 2025", status: "Draft", challan: null },
];

const statusStyle: Record<string, string> = {
  "Filed": "bg-green-100 text-green-700",
  "Pending": "bg-amber-100 text-amber-700",
  "Draft": "bg-gray-100 text-gray-600",
};

const INSIGHTS = [
  { type: "high" as const, message: "TDS reconciliation mismatch for Mehta Consulting — TRACES vs books gap: ₹3,400", action: "Reconcile before filing Q4 return" },
  { type: "medium" as const, message: "Form 16A certificates pending for 12 deductees — due within 15 days" },
];

export default function TDSPage() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">TDS</h1>
        <p className="text-sm text-gray-500 mt-0.5">Tax Deducted at Source — quarterly returns and certificates</p>
      </div>

      <AIInsightBanner insights={INSIGHTS} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {STATS.map((s) => <StatCard key={s.label} {...s} />)}
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
          <h2 className="text-sm font-semibold text-gray-900">{TABS[activeTab]}</h2>
        </div>
        <div className="divide-y divide-gray-50">
          {RETURNS.map((r, i) => (
            <div key={i} className="flex items-center gap-4 px-5 py-3.5">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900">{r.client}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{r.pan} · Form {r.form}</p>
              </div>
              <div className="text-right hidden sm:block">
                <p className="text-xs text-gray-600">{r.quarter}</p>
                <p className="text-xs text-gray-400 mt-0.5">Due {r.due}</p>
              </div>
              {r.challan && <p className="text-xs font-mono text-gray-400 hidden lg:block">{r.challan}</p>}
              <span className={`status-pill shrink-0 ${statusStyle[r.status] ?? "bg-gray-100 text-gray-600"}`}>
                {r.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

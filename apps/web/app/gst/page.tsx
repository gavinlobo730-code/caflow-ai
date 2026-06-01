"use client";
export const runtime = "edge";

import { useState } from "react";
import { FileText, Clock, CheckCircle2, AlertCircle } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { AIInsightBanner } from "@/components/ai-insight-banner";

const STATS = [
  { label: "Returns Due", value: "8", icon: Clock, iconColor: "text-amber-600", iconBg: "bg-amber-50", alert: true },
  { label: "Ready for Review", value: "3", icon: CheckCircle2, iconColor: "text-green-600", iconBg: "bg-green-50" },
  { label: "Awaiting Documents", value: "2", icon: FileText, iconColor: "text-purple-600", iconBg: "bg-purple-50" },
  { label: "High Risk Returns", value: "1", icon: AlertCircle, iconColor: "text-red-600", iconBg: "bg-red-50", alert: true },
];

const TABS = ["GSTR-1", "GSTR-3B", "GSTR-9", "GST Notices", "Reconciliation"];

const STATUS_FLOW = ["Draft", "Awaiting Docs", "Ready for Review", "Approved", "Ready to File"];

const RETURNS = [
  { client: "Sharma Enterprises", gstin: "27AABCS1429B1ZB", type: "GSTR-1", period: "May 2025", due: "11 Jun 2025", status: "Awaiting Docs", daysLeft: 10, risk: "medium" },
  { client: "Patel & Sons", gstin: "27AAPCS4229B1ZC", type: "GSTR-3B", period: "May 2025", due: "20 Jun 2025", status: "Draft", daysLeft: 19, risk: "low" },
  { client: "Mehta Consulting", gstin: "27AACCS7829B1ZD", type: "GSTR-1", period: "Apr 2025", due: "11 May 2025", status: "Ready to File", daysLeft: -21, risk: "high" },
  { client: "Desai Traders", gstin: "27AADCS9929B1ZE", type: "GSTR-3B", period: "May 2025", due: "20 Jun 2025", status: "Approved", daysLeft: 19, risk: "low" },
  { client: "Joshi Textiles", gstin: "27AAJCS3329B1ZF", type: "GSTR-1", period: "May 2025", due: "11 Jun 2025", status: "Ready for Review", daysLeft: 10, risk: "medium" },
];

const statusStyle: Record<string, string> = {
  "Draft": "bg-gray-100 text-gray-600",
  "Awaiting Docs": "bg-purple-100 text-purple-700",
  "Ready for Review": "bg-amber-100 text-amber-700",
  "Approved": "bg-blue-100 text-blue-700",
  "Ready to File": "bg-green-100 text-green-700",
};

const INSIGHTS = [
  { type: "critical" as const, message: "GSTR-1 for Mehta Consulting is 21 days overdue", action: "File immediately to avoid late fees under CGST Act Section 47" },
  { type: "high" as const, message: "ITC mismatch detected for Joshi Textiles — GSTR-2B vs purchase register gap: ₹7,200" },
  { type: "info" as const, message: "3 clients have GSTR-1 due in 10 days — begin data collection" },
];

export default function GSTPage() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">GST</h1>
        <p className="text-sm text-gray-500 mt-0.5">Returns management across all clients</p>
      </div>

      <AIInsightBanner insights={INSIGHTS} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {STATS.map((s) => <StatCard key={s.label} {...s} />)}
      </div>

      {/* Status flow */}
      <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Filing Status Flow</p>
        <div className="flex items-center gap-2 flex-wrap">
          {STATUS_FLOW.map((step, i) => (
            <div key={step} className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-600 bg-gray-50 border border-gray-200 px-3 py-1 rounded-full">{step}</span>
              {i < STATUS_FLOW.length - 1 && <span className="text-gray-300 text-sm">→</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)} className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* Returns table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            {TABS[activeTab]} Returns
          </h2>
          <span className="text-xs text-gray-400">{RETURNS.length} returns</span>
        </div>
        <div className="divide-y divide-gray-50">
          {RETURNS.map((r, i) => (
            <div key={i} className="flex items-center gap-4 px-5 py-3.5">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900">{r.client}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{r.gstin}</p>
              </div>
              <div className="text-right hidden sm:block">
                <p className="text-xs text-gray-600">{r.period}</p>
                <p className={`text-xs mt-0.5 font-medium ${r.daysLeft < 0 ? "text-red-600" : r.daysLeft <= 7 ? "text-amber-600" : "text-gray-400"}`}>
                  {r.daysLeft < 0 ? `${Math.abs(r.daysLeft)}d overdue` : `Due ${r.due}`}
                </p>
              </div>
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

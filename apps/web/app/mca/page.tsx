"use client";

import { useState } from "react";
import { Building2, Calendar, UserCheck, AlertTriangle } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { AIInsightBanner } from "@/components/ai-insight-banner";

const STATS = [
  { label: "Companies Managed", value: "8", icon: Building2, iconColor: "text-blue-600", iconBg: "bg-blue-50" },
  { label: "Annual Filings Due", value: "3", icon: Calendar, iconColor: "text-amber-600", iconBg: "bg-amber-50", alert: true },
  { label: "DIR-3 KYC Due", value: "5", icon: UserCheck, iconColor: "text-purple-600", iconBg: "bg-purple-50" },
  { label: "ROC Actions Required", value: "2", icon: AlertTriangle, iconColor: "text-red-600", iconBg: "bg-red-50", alert: true },
];

const TABS = ["AOC-4", "MGT-7", "DIR-3 KYC", "Company Master"];

const COMPANIES = [
  { name: "Joshi Textiles Pvt Ltd", cin: "U17200MH2010PTC205678", type: "Private Limited", aoc4: "31 Oct 2025", mgt7: "31 Oct 2025", dir3: "30 Sep 2025", status: "Active" },
  { name: "Mehta Consulting LLP", cin: "AAC-1234", type: "LLP", aoc4: "30 Oct 2025", mgt7: "N/A", dir3: "30 Sep 2025", status: "Active" },
  { name: "Sharma Industries Pvt Ltd", cin: "U15200MH2015PTC301234", type: "Private Limited", aoc4: "31 Oct 2025", mgt7: "31 Oct 2025", dir3: "Overdue", status: "Active" },
];

const INSIGHTS = [
  { type: "critical" as const, message: "DIR-3 KYC overdue for Sharma Industries Pvt Ltd directors", action: "File DIR-3 KYC immediately to avoid director disqualification" },
  { type: "medium" as const, message: "AOC-4 and MGT-7 due in 4 months for 3 companies — begin annual return preparation" },
];

export default function MCAPage() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">MCA</h1>
        <p className="text-sm text-gray-500 mt-0.5">Ministry of Corporate Affairs — company filings</p>
      </div>

      <AIInsightBanner insights={INSIGHTS} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
          <h2 className="text-sm font-semibold text-gray-900">Company Master — {TABS[activeTab]}</h2>
        </div>
        <div className="divide-y divide-gray-50">
          {COMPANIES.map((co, i) => (
            <div key={i} className="flex items-center gap-4 px-5 py-4">
              <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                <Building2 size={16} className="text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900">{co.name}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{co.cin} · {co.type}</p>
              </div>
              <div className="text-right hidden md:block space-y-0.5">
                <p className="text-xs text-gray-500">AOC-4: <span className="font-medium">{co.aoc4}</span></p>
                <p className="text-xs text-gray-500">MGT-7: <span className="font-medium">{co.mgt7}</span></p>
              </div>
              <span className={`status-pill shrink-0 ${co.dir3 === "Overdue" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
                DIR-3: {co.dir3}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

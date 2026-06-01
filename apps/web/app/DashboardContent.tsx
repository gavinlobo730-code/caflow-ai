"use client";

import { useState, useEffect } from "react";
import { Users, Clock, AlertTriangle, MessageSquare, Shield, Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import type { DashboardSummary, ApiResponse, RiskStats, AIInsightV2 } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const statusColor: Record<string, string> = {
  review_required: "bg-amber-100 text-amber-700",
  waiting_client: "bg-purple-100 text-purple-700",
  in_progress: "bg-blue-100 text-blue-700",
  todo: "bg-gray-100 text-gray-600",
  completed: "bg-green-100 text-green-700",
};

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-6 gap-3">
        {[1, 2, 3, 4, 5, 6].map((i) => <div key={i} className="h-28 bg-gray-100 rounded-xl" />)}
      </div>
      <div className="grid grid-cols-5 gap-6">
        <div className="col-span-3 h-64 bg-gray-100 rounded-xl" />
        <div className="col-span-2 h-64 bg-gray-100 rounded-xl" />
      </div>
    </div>
  );
}

export default function DashboardContent() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [riskStats, setRiskStats] = useState<RiskStats | null>(null);
  const [insightsFeed, setInsightsFeed] = useState<AIInsightV2[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE_URL}/api/tasks/summary/dashboard`).then((r) => r.json()),
      fetch(`${BASE_URL}/api/risks/stats`).then((r) => r.json()).catch(() => null),
      fetch(`${BASE_URL}/api/ai-insights/feed`).then((r) => r.json()).catch(() => null),
    ])
      .then(([dashRes, riskRes, feedRes]: [ApiResponse<DashboardSummary>, ApiResponse<RiskStats> | null, ApiResponse<AIInsightV2[]> | null]) => {
        if (dashRes.success) setSummary(dashRes.data);
        if (riskRes?.success) setRiskStats(riskRes.data);
        if (feedRes?.success) setInsightsFeed((feedRes.data ?? []).slice(0, 5));
      })
      .catch(() => { /* silently degrade */ })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner />;

  const s = summary ?? {
    active_clients: 0,
    tasks_due_today: 0,
    overdue_tasks: 0,
    waiting_client: 0,
    review_required: 0,
    total_open_tasks: 0,
    compliance_overdue: 0,
    high_risk_clients: 0,
  };

  const DASHBOARD_STATS = [
    { label: "Active Clients", value: String(s.active_clients), icon: Users, color: "text-blue-600", bg: "bg-blue-50", href: "/clients" },
    { label: "Tasks Due Today", value: String(s.tasks_due_today), icon: Clock, color: "text-amber-600", bg: "bg-amber-50", href: "/tasks" },
    { label: "Overdue Tasks", value: String(s.overdue_tasks), icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50", href: "/tasks?status=overdue" },
    { label: "Compliance Overdue", value: String(s.compliance_overdue ?? 0), icon: Shield, color: "text-orange-600", bg: "bg-orange-50", href: "/compliance" },
    { label: "High-Risk Clients", value: String(s.high_risk_clients ?? 0), icon: Activity, color: "text-red-700", bg: "bg-red-50", href: "/compliance" },
    { label: "Pending Reviews", value: String(s.review_required), icon: MessageSquare, color: "text-purple-600", bg: "bg-purple-50", href: "/tasks?status=review_required" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Operations Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Gavin Lobo &amp; Associates — CA Practice</p>
        </div>
        <Badge variant="outline" className="text-blue-700 border-blue-200 bg-blue-50 px-3 py-1">
          FY 2025-26
        </Badge>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {DASHBOARD_STATS.map((stat) => (
          <Link key={stat.label} href={stat.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
              <CardContent className="pt-5 pb-4">
                <div className={`w-9 h-9 rounded-lg ${stat.bg} flex items-center justify-center mb-3`}>
                  <stat.icon className={stat.color} size={18} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-tight">{stat.label}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Tasks summary */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-sm">Task Overview</CardTitle>
              <Link href="/tasks" className="text-xs text-blue-600 hover:underline">View all →</Link>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Total Open", value: s.total_open_tasks, status: "in_progress" },
                  { label: "Waiting Client", value: s.waiting_client, status: "waiting_client" },
                  { label: "Review Required", value: s.review_required, status: "review_required" },
                  { label: "Due This Week", value: s.compliance_due_week ?? 0, status: "todo" },
                ].map((item) => (
                  <div key={item.label} className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-50">
                    <span className="text-sm text-gray-700">{item.label}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor[item.status]}`}>
                      {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Compliance summary */}
        <div className="lg:col-span-2">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Compliance Summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                { label: "Overdue Filings", value: s.compliance_overdue ?? 0, color: "text-red-600" },
                { label: "Due This Week", value: s.compliance_due_week ?? 0, color: "text-amber-600" },
                { label: "High Risk Clients", value: s.high_risk_clients ?? 0, color: "text-orange-600" },
                { label: "Documents Pending", value: s.documents_pending_review ?? 0, color: "text-blue-600" },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <span className="text-xs text-gray-600">{item.label}</span>
                  <span className={`text-sm font-bold ${item.color}`}>{item.value}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Risk Overview */}
      {riskStats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link href="/risks?severity=critical">
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardContent className="pt-5 pb-4">
                <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center mb-3">
                  <AlertTriangle className="text-red-600" size={18} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{riskStats.critical}</p>
                <p className="text-xs text-gray-500 mt-0.5">Critical Risks</p>
              </CardContent>
            </Card>
          </Link>
          <Link href="/risks?severity=high">
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardContent className="pt-5 pb-4">
                <div className="w-9 h-9 rounded-lg bg-orange-50 flex items-center justify-center mb-3">
                  <AlertTriangle className="text-orange-600" size={18} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{riskStats.high}</p>
                <p className="text-xs text-gray-500 mt-0.5">High Risks</p>
              </CardContent>
            </Card>
          </Link>
          <Link href="/risks">
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardContent className="pt-5 pb-4">
                <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center mb-3">
                  <Shield className="text-amber-600" size={18} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{riskStats.total_open}</p>
                <p className="text-xs text-gray-500 mt-0.5">Open Risks Total</p>
              </CardContent>
            </Card>
          </Link>
        </div>
      )}

      {/* AI Insights Feed */}
      {insightsFeed.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-sm">AI Insights Feed</CardTitle>
            <Link href="/ai-assistant" className="text-xs text-blue-600 hover:underline">Open Copilot →</Link>
          </CardHeader>
          <CardContent className="space-y-3">
            {insightsFeed.map((insight) => (
              <div key={insight.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                <Badge
                  className={`text-xs shrink-0 ${
                    insight.severity === "critical" ? "bg-red-100 text-red-700" :
                    insight.severity === "high" ? "bg-orange-100 text-orange-700" :
                    insight.severity === "medium" ? "bg-amber-100 text-amber-700" :
                    insight.severity === "low" ? "bg-green-100 text-green-700" :
                    "bg-gray-100 text-gray-600"
                  }`}
                >
                  {insight.severity}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900">{insight.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5 truncate">{insight.description}</p>
                </div>
                {insight.client_name && (
                  <span className="text-xs text-gray-400 shrink-0">{insight.client_name}</span>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

    </div>
  );
}

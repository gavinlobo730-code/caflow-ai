"use client";

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, Shield } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { RiskItem, RiskStats, InsightSeverity } from "@/lib/types";
import { formatRelativeTime } from "@/lib/services/formatting";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const severityBadge: Record<InsightSeverity, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-green-100 text-green-700",
  info: "bg-blue-100 text-blue-700",
};

const resolutionBadge: Record<string, string> = {
  open: "bg-red-100 text-red-700",
  acknowledged: "bg-amber-100 text-amber-700",
  resolved: "bg-green-100 text-green-700",
  false_positive: "bg-gray-100 text-gray-600",
};

function formatCategory(cat: string): string {
  return cat.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function firmScoreColor(score: number): string {
  if (score > 70) return "text-red-600 bg-red-50 border-red-200";
  if (score >= 40) return "text-orange-600 bg-orange-50 border-orange-200";
  return "text-green-600 bg-green-50 border-green-200";
}

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-24 bg-gray-100 rounded-xl" />
        ))}
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-14 bg-gray-50 rounded" />
      ))}
    </div>
  );
}

export default function RisksPage() {
  const [risks, setRisks] = useState<RiskItem[]>([]);
  const [stats, setStats] = useState<RiskStats | null>(null);
  const [firmScore, setFirmScore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<Record<string, boolean>>({});

  const [filterSeverity, setFilterSeverity] = useState("all");
  const [filterCategory, setFilterCategory] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [riskRes, statsRes, scoreRes] = await Promise.all([
        fetch(`${BASE_URL}/api/risks`).then((r) => r.json()),
        fetch(`${BASE_URL}/api/risks/stats`).then((r) => r.json()),
        fetch(`${BASE_URL}/api/risks/firm/score`).then((r) => r.json()),
      ]);
      if (riskRes.success) setRisks(riskRes.data ?? []);
      if (statsRes.success) setStats(statsRes.data);
      if (scoreRes.success) setFirmScore(scoreRes.data?.score ?? scoreRes.data);
    } catch {
      setError("Failed to load risk data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function updateRisk(riskId: string, status: string) {
    setUpdating((prev) => ({ ...prev, [riskId]: true }));
    try {
      await fetch(`${BASE_URL}/api/risks/${riskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution_status: status }),
      });
      await loadData();
    } finally {
      setUpdating((prev) => ({ ...prev, [riskId]: false }));
    }
  }

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-5 py-4 flex items-center justify-between">
          <span className="text-sm">{error}</span>
          <button onClick={loadData} className="text-xs underline hover:no-underline">Retry</button>
        </div>
      </div>
    );
  }

  const s = stats ?? { critical: 0, high: 0, medium: 0, low: 0, info: 0, resolved: 0, total_open: 0 };

  const STAT_CARDS = [
    { label: "Critical", value: s.critical, color: "text-red-600", bg: "bg-red-50" },
    { label: "High", value: s.high, color: "text-orange-600", bg: "bg-orange-50" },
    { label: "Medium", value: s.medium, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Low + Info", value: s.low + s.info, color: "text-blue-600", bg: "bg-blue-50" },
    { label: "Resolved", value: s.resolved, color: "text-green-600", bg: "bg-green-50" },
  ];

  const categories = Array.from(new Set(risks.map((r) => r.category)));

  const filtered = risks.filter((r) => {
    if (filterSeverity !== "all" && r.severity !== filterSeverity) return false;
    if (filterCategory !== "all" && r.category !== filterCategory) return false;
    if (filterStatus !== "all" && r.resolution_status !== filterStatus) return false;
    return true;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Risk Intelligence</h1>
          <p className="text-sm text-gray-500 mt-1">Real-time risk monitoring across all clients</p>
        </div>
        {firmScore !== null && (
          <div className={`px-5 py-3 rounded-xl border ${firmScoreColor(firmScore)} text-center`}>
            <p className="text-xs font-medium mb-0.5 opacity-70">Firm Risk Score</p>
            <p className="text-3xl font-bold">{firmScore}</p>
            <p className="text-xs font-medium opacity-70">/100</p>
          </div>
        )}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {STAT_CARDS.map((card) => (
          <Card key={card.label}>
            <CardContent className="pt-5 pb-4">
              <div className={`w-9 h-9 rounded-lg ${card.bg} flex items-center justify-center mb-3`}>
                <Shield className={card.color} size={18} />
              </div>
              <p className="text-2xl font-bold text-gray-900">{card.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{card.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={filterSeverity}
          onChange={(e) => setFilterSeverity(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="info">Info</option>
        </select>

        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{formatCategory(c)}</option>
          ))}
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="false_positive">False Positive</option>
        </select>
      </div>

      {/* Risk table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle size={15} />
            Risks ({filtered.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Severity</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Client</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Category</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Title</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Description</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Status</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Created</th>
                  <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center text-gray-400 py-10 text-sm">
                      No risks found
                    </td>
                  </tr>
                ) : (
                  filtered.map((risk) => (
                    <tr key={risk.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${severityBadge[risk.severity]}`}>
                          {risk.severity}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700 text-sm">{risk.client_name ?? "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className="text-xs">{formatCategory(risk.category)}</Badge>
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900 text-sm">{risk.title}</td>
                      <td className="px-4 py-3 text-xs text-gray-500 max-w-[200px]">
                        {risk.description.length > 80 ? `${risk.description.slice(0, 80)}…` : risk.description}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${resolutionBadge[risk.resolution_status] ?? "bg-gray-100 text-gray-600"}`}>
                          {risk.resolution_status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{formatRelativeTime(risk.created_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1.5">
                          {risk.resolution_status !== "resolved" && (
                            <button
                              onClick={() => updateRisk(risk.id, "resolved")}
                              disabled={updating[risk.id]}
                              className="text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                            >
                              Resolve
                            </button>
                          )}
                          {risk.resolution_status === "open" && (
                            <button
                              onClick={() => updateRisk(risk.id, "acknowledged")}
                              disabled={updating[risk.id]}
                              className="text-xs px-2 py-1 bg-amber-500 text-white rounded hover:bg-amber-600 disabled:opacity-50"
                            >
                              Ack
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

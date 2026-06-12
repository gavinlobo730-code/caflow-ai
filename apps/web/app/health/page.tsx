"use client";

import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ─── Types ───────────────────────────────────────────────────────────────────

type Grade = "A" | "B" | "C" | "D" | "F";

interface HealthDimensions {
  compliance: number;
  accounting: number;
  documents: number;
  responsiveness: number;
  relationship_risk: number;
  financial_risk: number;
  engagement_health: number;
}

interface ClientHealth {
  id: string;
  client_id: string;
  client_name: string;
  overall_score: number;
  grade: Grade;
  dimensions: HealthDimensions;
  last_calculated: string | null;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

type FilterTab = "All" | "Critical" | "At-Risk" | "Healthy";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

function gradeBadge(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: "bg-green-800 text-green-300",
    B: "bg-blue-800 text-blue-300",
    C: "bg-yellow-800 text-yellow-300",
    D: "bg-orange-800 text-orange-300",
    F: "bg-red-800 text-red-300",
  };
  return map[grade];
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

// ─── Mini dimension dots ─────────────────────────────────────────────────────

function DimensionDots({ dimensions }: { dimensions: HealthDimensions }) {
  const scores = [
    dimensions.compliance,
    dimensions.accounting,
    dimensions.documents,
    dimensions.responsiveness,
    dimensions.relationship_risk,
    dimensions.financial_risk,
    dimensions.engagement_health,
  ];

  return (
    <div className="flex items-center gap-1">
      {scores.map((score, i) => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-full ${scoreBg(score)}`}
          title={`${score}/100`}
        />
      ))}
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [clients, setClients] = useState<ClientHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  const [filterTab, setFilterTab] = useState<FilterTab>("All");

  useEffect(() => {
    loadHealthData();
  }, []);

  async function loadHealthData() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/health/scores");
      const json: ApiResponse<ClientHealth[]> = await res.json();
      if (!json.success) throw new Error(json.error ?? "Failed to load health data");
      setClients(json.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleRecalculateAll() {
    setRecalculating(true);
    try {
      const res = await fetch("/api/health/recalculate", { method: "POST" });
      const json: ApiResponse<{ updated: number }> = await res.json();
      if (!json.success) throw new Error(json.error ?? "Recalculation failed");
      await loadHealthData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Recalculation failed");
    } finally {
      setRecalculating(false);
    }
  }

  // ─── Derived stats ─────────────────────────────────────────────────────────

  const avgScore =
    clients.length > 0
      ? Math.round(clients.reduce((s, c) => s + c.overall_score, 0) / clients.length)
      : 0;
  const criticalCount = clients.filter((c) => c.overall_score < 40).length;
  const atRiskCount = clients.filter((c) => c.overall_score >= 40 && c.overall_score < 70).length;
  const healthyCount = clients.filter((c) => c.overall_score >= 70).length;

  // Score distribution (A/B/C/D/F)
  const gradeCounts: Record<Grade, number> = { A: 0, B: 0, C: 0, D: 0, F: 0 };
  for (const c of clients) gradeCounts[c.grade]++;
  const maxGradeCount = Math.max(...Object.values(gradeCounts), 1);

  const filtered = clients.filter((c) => {
    if (filterTab === "Critical") return c.overall_score < 40;
    if (filterTab === "At-Risk") return c.overall_score >= 40 && c.overall_score < 70;
    if (filterTab === "Healthy") return c.overall_score >= 70;
    return true;
  });

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-6 bg-white/[0.08] rounded w-48" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 bg-white/[0.05] rounded-xl" />
          ))}
        </div>
        <div className="h-32 bg-white/[0.05] rounded-xl" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-white/[0.05] rounded-xl" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-900/30 text-red-400 rounded-lg px-5 py-4 text-sm border border-red-800">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Client Health Monitor</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            {clients.length} clients tracked
          </p>
        </div>
        <button
          onClick={handleRecalculateAll}
          disabled={recalculating}
          className="flex items-center gap-1.5 text-sm text-emerald-400 border border-emerald-700 px-3 py-1.5 rounded-md hover:bg-emerald-900/30 disabled:opacity-50"
        >
          <RefreshCw size={13} className={recalculating ? "animate-spin" : ""} />
          {recalculating ? "Recalculating…" : "Recalculate All"}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-4 text-center">
            <p className={`text-3xl font-bold ${scoreColor(avgScore)}`}>{avgScore}</p>
            <p className="text-xs text-slate-400 mt-1">Avg Score</p>
          </CardContent>
        </Card>
        <Card className="bg-red-900/30 border-red-800">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-red-400">{criticalCount}</p>
            <p className="text-xs text-red-400/70 mt-1">Critical (&lt;40)</p>
          </CardContent>
        </Card>
        <Card className="bg-yellow-900/30 border-yellow-800">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-yellow-400">{atRiskCount}</p>
            <p className="text-xs text-yellow-400/70 mt-1">At-Risk (40–69)</p>
          </CardContent>
        </Card>
        <Card className="bg-green-900/30 border-green-800">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-400">{healthyCount}</p>
            <p className="text-xs text-green-400/70 mt-1">Healthy (≥70)</p>
          </CardContent>
        </Card>
      </div>

      {/* Score distribution bar chart */}
      <Card className="bg-gray-800 border-gray-700">
        <CardContent className="p-5">
          <p className="text-xs text-slate-400 font-medium mb-4">Score Distribution</p>
          <div className="flex items-end gap-4 h-20">
            {(["A", "B", "C", "D", "F"] as Grade[]).map((grade) => {
              const count = gradeCounts[grade];
              const heightPct = maxGradeCount > 0 ? (count / maxGradeCount) * 100 : 0;
              const colors: Record<Grade, string> = {
                A: "bg-green-500",
                B: "bg-blue-500",
                C: "bg-yellow-500",
                D: "bg-orange-500",
                F: "bg-red-500",
              };
              return (
                <div key={grade} className="flex flex-col items-center gap-1 flex-1">
                  <span className="text-xs text-slate-400">{count}</span>
                  <div className="w-full flex items-end" style={{ height: "60px" }}>
                    <div
                      className={`w-full rounded-t ${colors[grade]} transition-all`}
                      style={{ height: `${Math.max(heightPct, 4)}%` }}
                    />
                  </div>
                  <span className="text-xs font-bold text-slate-300">{grade}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {(["All", "Critical", "At-Risk", "Healthy"] as FilterTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setFilterTab(tab)}
            className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              filterTab === tab
                ? "border-emerald-500 text-emerald-400"
                : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab}
            <span className="ml-1 text-slate-600">
              (
              {tab === "All"
                ? clients.length
                : tab === "Critical"
                ? criticalCount
                : tab === "At-Risk"
                ? atRiskCount
                : healthyCount}
              )
            </span>
          </button>
        ))}
      </div>

      {/* Table */}
      <Card className="bg-gray-800 border-gray-700">
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-sm text-slate-500">No clients in this category</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-gray-700">
                  <th className="px-5 py-3 text-left font-medium">Client</th>
                  <th className="px-3 py-3 text-left font-medium">Score</th>
                  <th className="px-3 py-3 text-left font-medium">Grade</th>
                  <th className="px-3 py-3 text-left font-medium">Dimensions</th>
                  <th className="px-3 py-3 text-left font-medium">Last Calculated</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {filtered.map((client) => (
                  <tr key={client.id} className="hover:bg-gray-700/30 group">
                    <td className="px-5 py-3 text-white font-medium">{client.client_name}</td>
                    <td className="px-3 py-3">
                      <span className={`text-lg font-bold ${scoreColor(client.overall_score)}`}>
                        {client.overall_score}
                      </span>
                      <span className="text-xs text-slate-500">/100</span>
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs font-bold ${gradeBadge(client.grade)}`}>
                        {client.grade}
                      </Badge>
                    </td>
                    <td className="px-3 py-3">
                      <DimensionDots dimensions={client.dimensions} />
                    </td>
                    <td className="px-3 py-3 text-slate-400 text-xs">
                      {formatDate(client.last_calculated)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        href={`/health/${client.client_id}`}
                        className="text-xs text-emerald-400 hover:text-emerald-300 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

// Normalize backend shape to frontend shape
// Supports both legacy flat columns and new Product Bible Chapter 16 dimensions dict
function normalizeScore(raw: Record<string, unknown>): ClientHealth {
  // New shape: raw.dimensions is an object keyed by dimension name
  const dims = raw.dimensions as Record<string, { score: number }> | undefined;
  return {
    id: String(raw.id ?? ""),
    client_id: String(raw.client_id ?? ""),
    client_name: String(raw.client_name ?? "—"),
    overall_score: Number(raw.overall_score ?? 0),
    grade: (raw.grade ?? raw.health_grade ?? "Critical") as Grade,
    dimensions: {
      compliance_health:     Number(dims?.compliance_health?.score     ?? raw.compliance_score        ?? 0),
      accounting_quality:    Number(dims?.accounting_quality?.score    ?? raw.accounting_score        ?? 0),
      work_progress:         Number(dims?.work_progress?.score         ?? raw.engagement_health_score ?? 0),
      document_health:       Number(dims?.document_health?.score       ?? raw.documents_score         ?? 0),
      ai_risk_signals:       Number(dims?.ai_risk_signals?.score       ?? 100),
      open_notices:          Number(dims?.open_notices?.score          ?? raw.financial_risk_score    ?? 0),
      client_responsiveness: Number(dims?.client_responsiveness?.score ?? raw.responsiveness_score   ?? 0),
    },
    last_calculated: String(raw.last_calculated_at ?? raw.calculated_at ?? raw.last_calculated ?? ""),
  };
}

// ─── Types ───────────────────────────────────────────────────────────────────

// Product Bible Chapter 16 score bands
type Grade = "Healthy" | "Good" | "Needs Attention" | "At Risk" | "Critical";

// Product Bible Chapter 16 — 7 dimensions
interface HealthDimensions {
  compliance_health: number;
  accounting_quality: number;
  work_progress: number;
  document_health: number;
  ai_risk_signals: number;
  open_notices: number;
  client_responsiveness: number;
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
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

function scoreBg(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

function gradeBadge(grade: Grade): string {
  const map: Record<Grade, string> = {
    "Healthy":         "bg-green-100 text-green-700",
    "Good":            "bg-blue-100 text-blue-700",
    "Needs Attention": "bg-yellow-100 text-yellow-700",
    "At Risk":         "bg-orange-100 text-orange-700",
    "Critical":        "bg-red-100 text-red-700",
  };
  return map[grade] ?? "bg-gray-100 text-gray-700";
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
    dimensions.compliance_health,
    dimensions.accounting_quality,
    dimensions.work_progress,
    dimensions.document_health,
    dimensions.ai_risk_signals,
    dimensions.open_notices,
    dimensions.client_responsiveness,
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
      const json: ApiResponse<Record<string, unknown>[]> = await apiFetch("/api/health/scores");
      if (!json.success) throw new Error(json.error ?? "Failed to load health data");
      setClients((json.data || []).map(normalizeScore));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleRecalculateAll() {
    setRecalculating(true);
    try {
      const json: ApiResponse<{ updated: number }> = await apiFetch(
        "/api/health/recalculate-all", { method: "POST" }
      );
      if (!json.success) throw new Error(json.error ?? "Recalculation failed");
      await loadHealthData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Recalculation failed");
    } finally {
      setRecalculating(false);
    }
  }

  // ─── Derived stats — Product Bible Chapter 16 score bands ─────────────────
  // Healthy: 80-100, Good: 65-79, Needs Attention: 50-64, At Risk: 35-49, Critical: 0-34

  const avgScore =
    clients.length > 0
      ? Math.round(clients.reduce((s, c) => s + c.overall_score, 0) / clients.length)
      : 0;
  const criticalCount = clients.filter((c) => c.overall_score < 35).length;
  const atRiskCount = clients.filter((c) => c.overall_score >= 35 && c.overall_score < 50).length;
  const healthyCount = clients.filter((c) => c.overall_score >= 80).length;

  // Score distribution (Product Bible bands)
  const gradeCounts: Record<Grade, number> = { "Healthy": 0, "Good": 0, "Needs Attention": 0, "At Risk": 0, "Critical": 0 };
  for (const c of clients) {
    if (gradeCounts[c.grade] !== undefined) gradeCounts[c.grade]++;
    else gradeCounts["Critical"]++;
  }
  const maxGradeCount = Math.max(...Object.values(gradeCounts), 1);

  const filtered = clients.filter((c) => {
    if (filterTab === "Critical") return c.overall_score < 35;
    if (filterTab === "At-Risk") return c.overall_score >= 35 && c.overall_score < 50;
    if (filterTab === "Healthy") return c.overall_score >= 80;
    return true;
  });

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse bg-[#F8FAFC] min-h-full">
        <div className="h-6 bg-gray-200 rounded w-48" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-xl" />
          ))}
        </div>
        <div className="h-32 bg-gray-100 rounded-xl" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-gray-100 rounded-xl" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-[#F8FAFC] min-h-full">
        <div className="bg-red-50 text-red-600 rounded-lg px-5 py-4 text-sm border border-red-200">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#182350]">Client Health Monitor</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {clients.length} clients tracked
          </p>
        </div>
        <button
          onClick={handleRecalculateAll}
          disabled={recalculating}
          className="flex items-center gap-1.5 text-sm text-emerald-700 border border-emerald-300 px-3 py-1.5 rounded-md hover:bg-emerald-50 disabled:opacity-50"
        >
          <RefreshCw size={13} className={recalculating ? "animate-spin" : ""} />
          {recalculating ? "Recalculating…" : "Recalculate All"}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <Card className="bg-white border-gray-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className={`text-3xl font-bold ${scoreColor(avgScore)}`}>{avgScore}</p>
            <p className="text-xs text-gray-500 mt-1">Avg Score</p>
          </CardContent>
        </Card>
        <Card className="bg-red-50 border-red-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-red-600">{criticalCount}</p>
            <p className="text-xs text-red-500 mt-1">Critical (&lt;40)</p>
          </CardContent>
        </Card>
        <Card className="bg-amber-50 border-amber-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-amber-600">{atRiskCount}</p>
            <p className="text-xs text-amber-500 mt-1">At-Risk (40–69)</p>
          </CardContent>
        </Card>
        <Card className="bg-green-50 border-green-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">{healthyCount}</p>
            <p className="text-xs text-green-500 mt-1">Healthy (≥70)</p>
          </CardContent>
        </Card>
      </div>

      {/* Score distribution bar chart */}
      <Card className="bg-white border-gray-200 shadow-sm">
        <CardContent className="p-5">
          <p className="text-xs text-gray-500 font-medium mb-4">Score Distribution</p>
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
                  <span className="text-xs text-gray-500">{count}</span>
                  <div className="w-full flex items-end" style={{ height: "60px" }}>
                    <div
                      className={`w-full rounded-t ${colors[grade]} transition-all`}
                      style={{ height: `${Math.max(heightPct, 4)}%` }}
                    />
                  </div>
                  <span className="text-xs font-bold text-gray-700">{grade}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(["All", "Critical", "At-Risk", "Healthy"] as FilterTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setFilterTab(tab)}
            className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              filterTab === tab
                ? "border-[#182350] text-[#182350]"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab}
            <span className="ml-1 text-gray-400">
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
      <Card className="bg-white border-gray-200 shadow-sm">
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-sm text-gray-500">No clients in this category</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-gray-200">
                  <th className="px-5 py-3 text-left font-medium">Client</th>
                  <th className="px-3 py-3 text-left font-medium">Score</th>
                  <th className="px-3 py-3 text-left font-medium">Grade</th>
                  <th className="px-3 py-3 text-left font-medium">Dimensions</th>
                  <th className="px-3 py-3 text-left font-medium">Last Calculated</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((client) => (
                  <tr key={client.id} className="hover:bg-[#AFD2FA]/10 group">
                    <td className="px-5 py-3 text-gray-800 font-medium">{client.client_name}</td>
                    <td className="px-3 py-3">
                      <span className={`text-lg font-bold ${scoreColor(client.overall_score)}`}>
                        {client.overall_score}
                      </span>
                      <span className="text-xs text-gray-400">/100</span>
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs font-bold ${gradeBadge(client.grade)}`}>
                        {client.grade}
                      </Badge>
                    </td>
                    <td className="px-3 py-3">
                      <DimensionDots dimensions={client.dimensions} />
                    </td>
                    <td className="px-3 py-3 text-gray-500 text-xs">
                      {formatDate(client.last_calculated)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        href={`/health/${client.client_id}`}
                        className="text-xs text-[#182350] hover:text-[#182350]/70 opacity-0 group-hover:opacity-100 transition-opacity"
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

"use client";

import { useState, useEffect, useMemo } from "react";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatDate as formatDateShared } from "@/lib/services/formatting";

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

const GRADES: Grade[] = ["Healthy", "Good", "Needs Attention", "At Risk", "Critical"];
// Sort order for the grade column (Healthy best → Critical worst).
const GRADE_RANK: Record<Grade, number> = {
  "Healthy": 5,
  "Good": 4,
  "Needs Attention": 3,
  "At Risk": 2,
  "Critical": 1,
};

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
    return formatDateShared(dateStr);
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
  const router = useRouter();
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
      // Direct Supabase, not /api/health/scores — a plain firm-scoped select
      // (routers/health.py:list_scores with no is_critical/is_at_risk
      // params). RLS (health_scores_assignment_scope, migration 084)
      // enforces the same can_access_client() assignment scoping list_scores
      // applies in Python via filter_by_client() — verified against the
      // live DB. Every stat on this page (avg score, band counts, the
      // distribution chart) is already computed client-side below from the
      // raw rows, same as before.
      const supabase = getSupabaseClient();
      const { data, error: sbError } = await supabase
        .from("health_scores")
        .select("*")
        .order("overall_score");
      if (sbError) throw sbError;
      setClients(((data as Record<string, unknown>[]) ?? []).map(normalizeScore));
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

  // The band tabs (All / Critical / At-Risk / Healthy) pre-scope the rows fed to
  // the DataTable; the grade/band selects and search then run inside the table.
  const filtered = useMemo(
    () =>
      clients.filter((c) => {
        if (filterTab === "Critical") return c.overall_score < 35;
        if (filterTab === "At-Risk") return c.overall_score >= 35 && c.overall_score < 50;
        if (filterTab === "Healthy") return c.overall_score >= 80;
        return true;
      }),
    [clients, filterTab],
  );

  const columns: Column<ClientHealth>[] = useMemo(() => [
    {
      key: "client_name",
      header: "Client",
      accessor: (c) => c.client_name,
      searchable: true,
      sortable: true,
      sticky: true,
      hideable: false,
      render: (c) => <span className="font-medium text-gray-800">{c.client_name}</span>,
    },
    {
      key: "overall_score",
      header: "Score",
      accessor: (c) => c.overall_score,
      sortable: true,
      align: "right",
      render: (c) => (
        <span>
          <span className={`text-lg font-bold ${scoreColor(c.overall_score)}`}>{c.overall_score}</span>
          <span className="text-xs text-gray-400">/100</span>
        </span>
      ),
    },
    {
      key: "grade",
      header: "Grade",
      accessor: (c) => GRADE_RANK[c.grade] ?? 0,
      sortable: true,
      render: (c) => (
        <Badge className={`text-xs font-bold ${gradeBadge(c.grade)}`}>{c.grade}</Badge>
      ),
    },
    {
      key: "dimensions",
      header: "Dimensions",
      accessor: () => "",
      sortable: false,
      hideable: true,
      render: (c) => <DimensionDots dimensions={c.dimensions} />,
    },
    {
      key: "last_calculated",
      header: "Last Calculated",
      accessor: (c) => c.last_calculated ?? "",
      sortable: true,
      align: "right",
      render: (c) => <span className="text-gray-500 text-xs">{formatDate(c.last_calculated)}</span>,
    },
  ], []);

  const filters: FilterDef<ClientHealth>[] = useMemo(() => [
    {
      key: "grade",
      label: "Grade",
      type: "select",
      accessor: (c) => c.grade,
      options: GRADES.map((g) => ({ value: g, label: g })),
    },
    {
      key: "band",
      label: "Band",
      type: "select",
      accessor: (c) =>
        c.overall_score >= 80 ? "Healthy"
          : c.overall_score >= 50 ? "Good"
          : c.overall_score >= 35 ? "At Risk"
          : "Critical",
      options: [
        { value: "Healthy", label: "Healthy (80–100)" },
        { value: "Good", label: "Good (50–79)" },
        { value: "At Risk", label: "At Risk (35–49)" },
        { value: "Critical", label: "Critical (0–34)" },
      ],
    },
  ], []);

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
            <p className="text-xs text-red-500 mt-1">Critical (0–34)</p>
          </CardContent>
        </Card>
        <Card className="bg-amber-50 border-amber-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-amber-600">{atRiskCount}</p>
            <p className="text-xs text-amber-500 mt-1">At Risk (35–49)</p>
          </CardContent>
        </Card>
        <Card className="bg-green-50 border-green-200 shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">{healthyCount}</p>
            <p className="text-xs text-green-500 mt-1">Healthy (80–100)</p>
          </CardContent>
        </Card>
      </div>

      {/* Score distribution bar chart */}
      <Card className="bg-white border-gray-200 shadow-sm">
        <CardContent className="p-5">
          <p className="text-xs text-gray-500 font-medium mb-4">Score Distribution</p>
          <div className="flex items-end gap-2 h-20">
            {(["Healthy", "Good", "Needs Attention", "At Risk", "Critical"] as Grade[]).map((grade) => {
              const count = gradeCounts[grade];
              const heightPct = maxGradeCount > 0 ? (count / maxGradeCount) * 100 : 0;
              const colors: Record<Grade, string> = {
                "Healthy":         "bg-green-500",
                "Good":            "bg-blue-500",
                "Needs Attention": "bg-yellow-500",
                "At Risk":         "bg-orange-500",
                "Critical":        "bg-red-500",
              };
              const shortLabel: Record<Grade, string> = {
                "Healthy":         "H",
                "Good":            "G",
                "Needs Attention": "N",
                "At Risk":         "R",
                "Critical":        "C",
              };
              return (
                <div key={grade} className="flex flex-col items-center gap-1 flex-1" title={grade}>
                  <span className="text-xs text-gray-500">{count}</span>
                  <div className="w-full flex items-end" style={{ height: "60px" }}>
                    <div
                      className={`w-full rounded-t ${colors[grade]} transition-all`}
                      style={{ height: `${Math.max(heightPct, 4)}%` }}
                    />
                  </div>
                  <span className="text-xs font-bold text-gray-700">{shortLabel[grade]}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Filter tabs (band scope) */}
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

      {/* Table — shared DataTable (search, sort, grade/band filters, pagination, export, prefs) */}
      <DataTable
        data={filtered}
        columns={columns}
        filters={filters}
        getRowId={(c) => c.id}
        loading={loading}
        error={error}
        onRetry={loadHealthData}
        onRefresh={loadHealthData}
        searchPlaceholder="Search by client name…"
        initialSort={{ key: "overall_score", dir: "asc" }}
        exportFilename="client-health"
        persistKey="health.clients"
        emptyTitle="No clients in this category"
        emptyDescription="Adjust the filters or recalculate scores to populate this list."
        onRowClick={(c) => router.push(`/health/${c.client_id}`)}
        rowActions={(c) => (
          <a
            href={`/health/${c.client_id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-[#182350] hover:text-[#182350]/70"
          >
            View →
          </a>
        )}
      />
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, Plus, X } from "lucide-react";
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

interface ClientHealthDetail {
  client_id: string;
  client_name: string;
  overall_score: number;
  grade: Grade;
  dimensions: HealthDimensions;
  last_calculated: string | null;
}

interface HealthHistoryRecord {
  id: string;
  overall_score: number;
  grade: Grade;
  calculated_at: string;
}

interface HealthAlert {
  id: string;
  alert_type: string;
  severity: "low" | "medium" | "high" | "critical";
  message: string;
  dimension: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface HealthOverride {
  id: string;
  dimension: string;
  override_score: number;
  reason: string;
  created_by: string;
  expires_at: string | null;
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const DIMENSION_LABELS: Record<keyof HealthDimensions, string> = {
  compliance:        "Compliance",
  accounting:        "Accounting",
  documents:         "Documents",
  responsiveness:    "Responsiveness",
  relationship_risk: "Relationship Risk",
  financial_risk:    "Financial Risk",
  engagement_health: "Engagement Health",
};

const DIMENSION_KEYS = Object.keys(DIMENSION_LABELS) as (keyof HealthDimensions)[];

const SEVERITY_COLORS: Record<HealthAlert["severity"], string> = {
  low:      "bg-blue-800 text-blue-300",
  medium:   "bg-yellow-800 text-yellow-300",
  high:     "bg-orange-800 text-orange-300",
  critical: "bg-red-800 text-red-300",
};

const EMPTY_OVERRIDE_FORM = {
  dimension: "compliance",
  override_score: "",
  reason: "",
  expires_at: "",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

function gradeBadgeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: "bg-green-800 text-green-300",
    B: "bg-blue-800 text-blue-300",
    C: "bg-yellow-800 text-yellow-300",
    D: "bg-orange-800 text-orange-300",
    F: "bg-red-800 text-red-300",
  };
  return map[grade];
}

function gradeLargeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: "text-green-400",
    B: "text-blue-400",
    C: "text-yellow-400",
    D: "text-orange-400",
    F: "text-red-400",
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

// ─── Component ───────────────────────────────────────────────────────────────

export default function ClientHealthDetailPage() {
  const params = useParams();
  const clientId = params.client_id as string;

  const [health, setHealth] = useState<ClientHealthDetail | null>(null);
  const [history, setHistory] = useState<HealthHistoryRecord[]>([]);
  const [alerts, setAlerts] = useState<HealthAlert[]>([]);
  const [overrides, setOverrides] = useState<HealthOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overrideModalOpen, setOverrideModalOpen] = useState(false);
  const [overrideForm, setOverrideForm] = useState(EMPTY_OVERRIDE_FORM);
  const [savingOverride, setSavingOverride] = useState(false);
  const [overrideSaveError, setOverrideSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (clientId) loadAll();
  }, [clientId]);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [healthRes, historyRes, alertsRes, overridesRes] = await Promise.all([
        fetch(`/api/health/scores/${clientId}`),
        fetch(`/api/health/scores/${clientId}/history`),
        fetch(`/api/health/alerts?client_id=${clientId}`),
        fetch(`/api/health/overrides?client_id=${clientId}`),
      ]);
      const [healthJson, historyJson, alertsJson, overridesJson]: [
        ApiResponse<ClientHealthDetail>,
        ApiResponse<HealthHistoryRecord[]>,
        ApiResponse<HealthAlert[]>,
        ApiResponse<HealthOverride[]>
      ] = await Promise.all([
        healthRes.json(),
        historyRes.json(),
        alertsRes.json(),
        overridesRes.json(),
      ]);
      if (!healthJson.success) throw new Error(healthJson.error ?? "Failed to load health data");
      setHealth(healthJson.data);
      setHistory(historyJson.success ? historyJson.data : []);
      setAlerts(alertsJson.success ? alertsJson.data.filter((a) => !a.resolved_at) : []);
      setOverrides(overridesJson.success ? overridesJson.data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleAddOverride() {
    if (!overrideForm.dimension || !overrideForm.reason.trim() || !overrideForm.override_score) return;
    setSavingOverride(true);
    setOverrideSaveError(null);
    try {
      const res = await fetch("/api/health/overrides", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          dimension: overrideForm.dimension,
          override_score: parseInt(overrideForm.override_score, 10),
          reason: overrideForm.reason.trim(),
          expires_at: overrideForm.expires_at || null,
        }),
      });
      const json: ApiResponse<HealthOverride> = await res.json();
      if (!json.success) throw new Error(json.error ?? "Failed to save override");
      setOverrides((prev) => [json.data, ...prev]);
      setOverrideModalOpen(false);
      setOverrideForm(EMPTY_OVERRIDE_FORM);
    } catch (e) {
      setOverrideSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSavingOverride(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 bg-white/[0.08] rounded w-24" />
        <div className="h-40 bg-white/[0.05] rounded-xl" />
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="h-20 bg-white/[0.05] rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="p-6">
        <Link href="/health" className="flex items-center gap-1 text-xs text-slate-400 hover:text-white mb-4">
          <ChevronLeft size={14} /> Back
        </Link>
        <div className="bg-red-900/30 text-red-400 rounded-lg px-5 py-4 text-sm border border-red-800">
          {error ?? "Client not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Back nav */}
      <Link href="/health" className="flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ChevronLeft size={14} /> Health Monitor
      </Link>

      {/* Hero — overall score */}
      <Card className="bg-gray-800 border-gray-700">
        <CardContent className="p-6">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className={`text-6xl font-black ${scoreColor(health.overall_score)}`}>
                {health.overall_score}
              </p>
              <p className="text-xs text-slate-500 mt-1">/ 100</p>
            </div>
            <div className="w-px h-16 bg-gray-700" />
            <div>
              <p className="text-xs text-slate-400 mb-1">Grade</p>
              <span className={`text-4xl font-black ${gradeLargeColor(health.grade)}`}>
                {health.grade}
              </span>
            </div>
            <div className="w-px h-16 bg-gray-700" />
            <div>
              <h2 className="text-lg font-semibold text-white">{health.client_name}</h2>
              <p className="text-xs text-slate-400 mt-1">
                Last calculated: {formatDate(health.last_calculated)}
              </p>
              <Badge className={`mt-2 text-xs ${gradeBadgeColor(health.grade)}`}>
                {health.grade === "A" ? "Excellent" :
                 health.grade === "B" ? "Good" :
                 health.grade === "C" ? "Fair" :
                 health.grade === "D" ? "Poor" : "Critical"}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 7 dimension cards */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3">Dimension Scores</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {DIMENSION_KEYS.map((key) => {
            const score = health.dimensions[key];
            return (
              <Card key={key} className="bg-gray-800 border-gray-700">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-slate-400 font-medium">{DIMENSION_LABELS[key]}</p>
                    <span className={`text-sm font-bold ${scoreColor(score)}`}>{score}</span>
                  </div>
                  <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${scoreBarColor(score)}`}
                      style={{ width: `${score}%` }}
                    />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Score history */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3">Score History</h3>
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {history.length === 0 ? (
              <div className="text-center py-10">
                <p className="text-sm text-slate-500">No history records</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Calculated At</th>
                    <th className="px-3 py-3 text-left font-medium">Overall Score</th>
                    <th className="px-3 py-3 text-left font-medium">Grade</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {history.slice(0, 10).map((record) => (
                    <tr key={record.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3 text-slate-400 text-xs">{formatDate(record.calculated_at)}</td>
                      <td className="px-3 py-3">
                        <span className={`font-bold ${scoreColor(record.overall_score)}`}>
                          {record.overall_score}
                        </span>
                        <span className="text-xs text-slate-500">/100</span>
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[11px] ${gradeBadgeColor(record.grade)}`}>
                          {record.grade}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Active alerts */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3">
          Active Alerts{" "}
          {alerts.length > 0 && (
            <span className="text-xs text-red-400 font-normal">({alerts.length})</span>
          )}
        </h3>
        <div className="space-y-2">
          {alerts.length === 0 ? (
            <p className="text-sm text-slate-500 py-4 text-center">No active alerts</p>
          ) : (
            alerts.map((alert) => (
              <Card key={alert.id} className="bg-gray-800 border-gray-700">
                <CardContent className="p-4 flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={`text-[10px] ${SEVERITY_COLORS[alert.severity]}`}>
                        {alert.severity.toUpperCase()}
                      </Badge>
                      {alert.dimension && (
                        <span className="text-[10px] text-slate-500">{alert.dimension}</span>
                      )}
                    </div>
                    <p className="text-sm text-white">{alert.message}</p>
                    <p className="text-xs text-slate-500 mt-1">{formatDate(alert.created_at)}</p>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>

      {/* Active overrides */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Active Overrides</h3>
          <button
            onClick={() => {
              setOverrideForm(EMPTY_OVERRIDE_FORM);
              setOverrideSaveError(null);
              setOverrideModalOpen(true);
            }}
            className="flex items-center gap-1 text-xs text-emerald-400 border border-emerald-700 px-2.5 py-1 rounded hover:bg-emerald-900/30"
          >
            <Plus size={12} /> Add Override
          </button>
        </div>
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {overrides.length === 0 ? (
              <div className="text-center py-10">
                <p className="text-sm text-slate-500">No active overrides</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Dimension</th>
                    <th className="px-3 py-3 text-left font-medium">Override Score</th>
                    <th className="px-3 py-3 text-left font-medium">Reason</th>
                    <th className="px-3 py-3 text-left font-medium">Expires</th>
                    <th className="px-3 py-3 text-left font-medium">Created By</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {overrides.map((override) => (
                    <tr key={override.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3">
                        <Badge className="bg-emerald-800 text-emerald-300 text-[11px]">
                          {DIMENSION_LABELS[override.dimension as keyof HealthDimensions] ?? override.dimension}
                        </Badge>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`font-bold ${scoreColor(override.override_score)}`}>
                          {override.override_score}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-slate-300 text-xs max-w-xs truncate">
                        {override.reason}
                      </td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{formatDate(override.expires_at)}</td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{override.created_by}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add Override Modal */}
      {overrideModalOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-white">Add Score Override</h2>
              <button
                onClick={() => setOverrideModalOpen(false)}
                className="text-slate-500 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400 font-medium">Dimension *</label>
                <select
                  value={overrideForm.dimension}
                  onChange={(e) => setOverrideForm({ ...overrideForm, dimension: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                >
                  {DIMENSION_KEYS.map((key) => (
                    <option key={key} value={key}>
                      {DIMENSION_LABELS[key]}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 font-medium">Override Score (0–100) *</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={overrideForm.override_score}
                  onChange={(e) => setOverrideForm({ ...overrideForm, override_score: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. 75"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 font-medium">Reason *</label>
                <textarea
                  rows={3}
                  value={overrideForm.reason}
                  onChange={(e) => setOverrideForm({ ...overrideForm, reason: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 resize-none"
                  placeholder="Explain why this score is being overridden…"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 font-medium">Expires At (optional)</label>
                <input
                  type="date"
                  value={overrideForm.expires_at}
                  onChange={(e) => setOverrideForm({ ...overrideForm, expires_at: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>
            {overrideSaveError && (
              <p className="mt-3 text-xs text-red-400 bg-red-900/30 px-3 py-2 rounded-md border border-red-800">
                {overrideSaveError}
              </p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setOverrideModalOpen(false)}
                className="flex-1 text-sm text-slate-400 border border-gray-700 py-2 rounded-md hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleAddOverride}
                disabled={
                  savingOverride ||
                  !overrideForm.dimension ||
                  !overrideForm.reason.trim() ||
                  !overrideForm.override_score
                }
                className="flex-1 text-sm bg-emerald-600 text-white py-2 rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {savingOverride ? "Saving…" : "Add Override"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

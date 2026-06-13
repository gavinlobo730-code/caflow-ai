"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, Plus, X, ChevronDown, AlertTriangle } from "lucide-react";
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

// ─── Types ───────────────────────────────────────────────────────────────────

// Product Bible Chapter 16 — 7 dimensions
type DimensionKey =
  | "compliance_health"
  | "accounting_quality"
  | "work_progress"
  | "document_health"
  | "ai_risk_signals"
  | "open_notices"
  | "client_responsiveness";

interface DimensionValue {
  score: number;
  weight: number;    // basis points (e.g. 2500 = 25%)
  weighted: number;  // integer contribution
}

type Grade = "Healthy" | "Good" | "Needs Attention" | "At Risk" | "Critical";

interface ClientHealthDetail {
  client_id: string;
  client_name: string;
  overall_score: number;
  grade: Grade;
  trend: string;
  dimensions: Record<DimensionKey, DimensionValue>;
  hard_override: string | null;
  hard_override_reason: string | null;
  is_critical: boolean;
  is_at_risk: boolean;
  last_calculated_at: string | null;
}

interface DimensionFactor {
  label: string;
  impact: number;
  action_label: string;
  action_url: string;
}

interface HealthHistoryRecord {
  id: string;
  overall_score: number;
  health_grade: string;
  recorded_at: string;
}

interface HealthAlert {
  id: string;
  alert_type: string;
  severity: "info" | "warning" | "critical";
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

// Product Bible Chapter 16 — dimension display labels and weights
const DIMENSION_META: Record<DimensionKey, { label: string; weightLabel: string; description: string }> = {
  compliance_health:     { label: "Compliance Health",     weightLabel: "25%", description: "Overdue returns, late filings, pending notices" },
  accounting_quality:    { label: "Accounting Quality",    weightLabel: "20%", description: "Bank reconciliation age, unclosed periods" },
  work_progress:         { label: "Work Progress",         weightLabel: "15%", description: "Overdue and at-risk work items" },
  document_health:       { label: "Document Health",       weightLabel: "15%", description: "Outstanding requests, missing required docs" },
  ai_risk_signals:       { label: "AI Risk Signals",       weightLabel: "10%", description: "Open critical insights and warnings" },
  open_notices:          { label: "Open Notices",          weightLabel: "10%", description: "Government notices by age and deadline" },
  client_responsiveness: { label: "Client Responsiveness", weightLabel: "5%",  description: "Portal login recency, upload delay" },
};

const DIMENSION_KEYS = Object.keys(DIMENSION_META) as DimensionKey[];

// Legacy override form dimension keys mapped to new names
const OVERRIDE_DIMENSION_OPTIONS = DIMENSION_KEYS;

const SEVERITY_COLORS: Record<HealthAlert["severity"], string> = {
  info:     "bg-blue-100 text-blue-700",
  warning:  "bg-yellow-100 text-yellow-700",
  critical: "bg-red-100 text-red-700",
};

const EMPTY_OVERRIDE_FORM = {
  dimension: "compliance_health" as DimensionKey,
  override_score: "",
  reason: "",
  expires_at: "",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-600";
  if (score >= 65) return "text-blue-600";
  if (score >= 50) return "text-amber-600";
  if (score >= 35) return "text-orange-600";
  return "text-red-600";
}

function scoreBarColor(score: number): string {
  if (score >= 80) return "bg-green-500";
  if (score >= 65) return "bg-blue-500";
  if (score >= 50) return "bg-yellow-500";
  if (score >= 35) return "bg-orange-500";
  return "bg-red-500";
}

function gradeBadgeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    "Healthy":          "bg-green-100 text-green-700",
    "Good":             "bg-blue-100 text-blue-700",
    "Needs Attention":  "bg-yellow-100 text-yellow-700",
    "At Risk":          "bg-orange-100 text-orange-700",
    "Critical":         "bg-red-100 text-red-700",
  };
  return map[grade] ?? "bg-gray-100 text-gray-700";
}

function gradeLargeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    "Healthy":          "text-green-600",
    "Good":             "text-blue-600",
    "Needs Attention":  "text-amber-600",
    "At Risk":          "text-orange-600",
    "Critical":         "text-red-600",
  };
  return map[grade] ?? "text-gray-600";
}

function formatDate(dateStr: string | null | undefined): string {
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

function weightBpToLabel(bp: number): string {
  // basis points → "25%" string
  return `${bp / 100}%`;
}

// ─── Dimension Card ───────────────────────────────────────────────────────────

interface DimensionCardProps {
  dimKey: DimensionKey;
  value: DimensionValue;
  clientId: string;
}

function DimensionCard({ dimKey, value, clientId }: DimensionCardProps) {
  const meta = DIMENSION_META[dimKey];
  const [expanded, setExpanded] = useState(false);
  const [factors, setFactors] = useState<DimensionFactor[] | null>(null);
  const [loadingFactors, setLoadingFactors] = useState(false);

  async function handleExpand() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (factors !== null) return; // already loaded
    setLoadingFactors(true);
    try {
      const json: ApiResponse<{ factors: DimensionFactor[] }> = await apiFetch(
        `/api/health/clients/${clientId}/dimension-detail?dimension=${dimKey}`
      );
      setFactors(json.success ? (json.data?.factors ?? []) : []);
    } catch {
      setFactors([]);
    } finally {
      setLoadingFactors(false);
    }
  }

  const weightLabel = meta.weightLabel ?? weightBpToLabel(value.weight ?? 0);

  return (
    <Card className="bg-white border border-gray-200">
      <CardContent className="p-4">
        <button
          onClick={handleExpand}
          className="w-full text-left"
          aria-expanded={expanded}
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <p className="text-xs text-gray-700 font-medium">{meta.label}</p>
              <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                {weightLabel}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-sm font-bold ${scoreColor(value.score)}`}>
                {value.score}
              </span>
              <ChevronDown
                size={13}
                className={`text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}
              />
            </div>
          </div>
          <p className="text-[10px] text-gray-400 mb-2">{meta.description}</p>
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${scoreBarColor(value.score)}`}
              style={{ width: `${value.score}%` }}
            />
          </div>
          <p className="text-[10px] text-gray-400 mt-1">
            Weighted contribution: {value.weighted} pts
          </p>
        </button>

        {/* Factors drawer */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            {loadingFactors ? (
              <p className="text-xs text-gray-400 animate-pulse">Loading factors…</p>
            ) : !factors || factors.length === 0 ? (
              <p className="text-xs text-gray-500">No dragging factors — this dimension is healthy.</p>
            ) : (
              <ul className="space-y-2">
                {factors.map((f, i) => (
                  <li key={i} className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <p className="text-xs text-gray-700">{f.label}</p>
                      <span className="text-[10px] text-red-600 font-medium">{f.impact} pts</span>
                    </div>
                    <a
                      href={f.action_url}
                      className="text-[10px] text-[#182350] border border-[#182350]/30 px-2 py-0.5 rounded hover:bg-[#AFD2FA]/20 whitespace-nowrap"
                    >
                      {f.action_label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

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

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [healthJson, historyJson, alertsJson, overridesJson]: [
        ApiResponse<ClientHealthDetail>,
        ApiResponse<HealthHistoryRecord[]>,
        ApiResponse<HealthAlert[]>,
        ApiResponse<HealthOverride[]>
      ] = await Promise.all([
        apiFetch(`/api/health/clients/${clientId}`),
        apiFetch(`/api/health/scores/${clientId}/history`),
        apiFetch(`/api/health/alerts?client_id=${clientId}`),
        apiFetch(`/api/health/overrides?client_id=${clientId}`),
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
  }, [clientId]);

  useEffect(() => {
    if (clientId) loadAll();
  }, [clientId, loadAll]);

  async function handleAddOverride() {
    if (!overrideForm.dimension || !overrideForm.reason.trim() || !overrideForm.override_score) return;
    setSavingOverride(true);
    setOverrideSaveError(null);
    try {
      const json: ApiResponse<HealthOverride> = await apiFetch(
        `/api/health/scores/${clientId}/override`,
        {
          method: "POST",
          body: JSON.stringify({
            dimension: overrideForm.dimension,
            override_score: parseInt(overrideForm.override_score, 10),
            reason: overrideForm.reason.trim(),
            expires_at: overrideForm.expires_at || null,
          }),
        }
      );
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
        <div className="h-5 bg-gray-100 rounded w-24" />
        <div className="h-40 bg-gray-100 rounded-xl" />
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="p-6">
        <Link href="/health" className="flex items-center gap-1 text-xs text-gray-500 hover:text-[#182350] mb-4">
          <ChevronLeft size={14} /> Back
        </Link>
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm border border-red-200">
          {error ?? "Client not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Back nav */}
      <Link href="/health" className="flex items-center gap-1 text-xs text-gray-500 hover:text-[#182350]">
        <ChevronLeft size={14} /> Health Monitor
      </Link>

      {/* Hard override banner */}
      {health.hard_override && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-300 rounded-lg px-5 py-3">
          <AlertTriangle size={16} className="text-red-600 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-700">Critical Override Active</p>
            <p className="text-xs text-red-600 mt-0.5">
              {health.hard_override_reason ?? "Hard override forcing Critical status regardless of score."}
            </p>
          </div>
        </div>
      )}

      {/* Hero — overall score */}
      <Card className="bg-white border border-gray-200">
        <CardContent className="p-6">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className={`text-6xl font-black ${scoreColor(health.overall_score)}`}>
                {health.overall_score}
              </p>
              <p className="text-xs text-gray-500 mt-1">/ 100</p>
              {health.trend && health.trend !== "+0" && (
                <p className={`text-xs font-medium mt-1 ${health.trend.startsWith("+") ? "text-green-600" : "text-red-600"}`}>
                  {health.trend} trend
                </p>
              )}
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div>
              <p className="text-xs text-gray-500 mb-1">Score Band</p>
              <Badge className={`text-sm px-3 py-1 font-semibold ${gradeBadgeColor(health.grade)}`}>
                {health.grade}
              </Badge>
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div>
              <h2 className="text-lg font-semibold text-[#182350]">{health.client_name}</h2>
              <p className="text-xs text-gray-500 mt-1">
                Last calculated: {formatDate(health.last_calculated_at)}
              </p>
              {health.is_critical && !health.hard_override && (
                <Badge className="mt-2 text-xs bg-red-100 text-red-700">Critical</Badge>
              )}
              {health.is_at_risk && !health.is_critical && (
                <Badge className="mt-2 text-xs bg-orange-100 text-orange-700">At Risk</Badge>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 7 dimension cards — Product Bible Chapter 16 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-[#182350]">Health Dimensions</h3>
          <p className="text-xs text-gray-400">Click a dimension to see dragging factors</p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {DIMENSION_KEYS.map((key) => {
            const value = health.dimensions?.[key] ?? { score: 100, weight: 0, weighted: 0 };
            return (
              <DimensionCard
                key={key}
                dimKey={key}
                value={value}
                clientId={clientId}
              />
            );
          })}
        </div>
      </div>

      {/* Score history */}
      <div>
        <h3 className="text-sm font-semibold text-[#182350] mb-3">Score History</h3>
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {history.length === 0 ? (
              <div className="text-center py-10">
                <p className="text-sm text-gray-500">No history records</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Calculated At</th>
                    <th className="px-3 py-3 text-left font-medium">Overall Score</th>
                    <th className="px-3 py-3 text-left font-medium">Band</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {history.slice(0, 10).map((record) => (
                    <tr key={record.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 text-gray-500 text-xs">{formatDate(record.recorded_at)}</td>
                      <td className="px-3 py-3">
                        <span className={`font-bold ${scoreColor(record.overall_score)}`}>
                          {record.overall_score}
                        </span>
                        <span className="text-xs text-gray-400">/100</span>
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[11px] ${gradeBadgeColor((record.health_grade ?? "Critical") as Grade)}`}>
                          {record.health_grade ?? "—"}
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
        <h3 className="text-sm font-semibold text-[#182350] mb-3">
          Active Alerts{" "}
          {alerts.length > 0 && (
            <span className="text-xs text-red-600 font-normal">({alerts.length})</span>
          )}
        </h3>
        <div className="space-y-2">
          {alerts.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">No active alerts</p>
          ) : (
            alerts.map((alert) => (
              <Card key={alert.id} className="bg-white border border-gray-200">
                <CardContent className="p-4 flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={`text-[10px] ${SEVERITY_COLORS[alert.severity]}`}>
                        {alert.severity.toUpperCase()}
                      </Badge>
                      {alert.dimension && (
                        <span className="text-[10px] text-gray-500">
                          {DIMENSION_META[alert.dimension as DimensionKey]?.label ?? alert.dimension}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-800">{alert.message}</p>
                    <p className="text-xs text-gray-500 mt-1">{formatDate(alert.created_at)}</p>
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
          <h3 className="text-sm font-semibold text-[#182350]">Active Overrides</h3>
          <button
            onClick={() => {
              setOverrideForm(EMPTY_OVERRIDE_FORM);
              setOverrideSaveError(null);
              setOverrideModalOpen(true);
            }}
            className="flex items-center gap-1 text-xs text-[#182350] border border-[#182350] px-2.5 py-1 rounded hover:bg-[#AFD2FA]/20"
          >
            <Plus size={12} /> Add Override
          </button>
        </div>
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {overrides.length === 0 ? (
              <div className="text-center py-10">
                <p className="text-sm text-gray-500">No active overrides</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Dimension</th>
                    <th className="px-3 py-3 text-left font-medium">Override Score</th>
                    <th className="px-3 py-3 text-left font-medium">Reason</th>
                    <th className="px-3 py-3 text-left font-medium">Expires</th>
                    <th className="px-3 py-3 text-left font-medium">Created By</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {overrides.map((override) => (
                    <tr key={override.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Badge className="bg-emerald-100 text-emerald-700 text-[11px]">
                          {DIMENSION_META[override.dimension as DimensionKey]?.label ?? override.dimension}
                        </Badge>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`font-bold ${scoreColor(override.override_score)}`}>
                          {override.override_score}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-gray-700 text-xs max-w-xs truncate">
                        {override.reason}
                      </td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(override.expires_at)}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{override.created_by}</td>
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
        <div className="fixed inset-0 bg-gray-900/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">Add Score Override</h2>
              <button
                onClick={() => setOverrideModalOpen(false)}
                className="text-gray-400 hover:text-gray-700"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600 font-medium">Dimension *</label>
                <select
                  value={overrideForm.dimension}
                  onChange={(e) => setOverrideForm({ ...overrideForm, dimension: e.target.value as DimensionKey })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                >
                  {OVERRIDE_DIMENSION_OPTIONS.map((key) => (
                    <option key={key} value={key}>
                      {DIMENSION_META[key].label} ({DIMENSION_META[key].weightLabel})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Override Score (0–100) *</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={overrideForm.override_score}
                  onChange={(e) => setOverrideForm({ ...overrideForm, override_score: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="e.g. 75"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Reason *</label>
                <textarea
                  rows={3}
                  value={overrideForm.reason}
                  onChange={(e) => setOverrideForm({ ...overrideForm, reason: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350] resize-none"
                  placeholder="Explain why this score is being overridden…"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Expires At (optional)</label>
                <input
                  type="date"
                  value={overrideForm.expires_at}
                  onChange={(e) => setOverrideForm({ ...overrideForm, expires_at: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                />
              </div>
            </div>
            {overrideSaveError && (
              <p className="mt-3 text-xs text-red-700 bg-red-50 px-3 py-2 rounded-md border border-red-200">
                {overrideSaveError}
              </p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setOverrideModalOpen(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50"
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
                className="flex-1 text-sm bg-[#182350] text-white py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
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

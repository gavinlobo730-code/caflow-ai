"use client";

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Plus, X, Activity } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
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

type Grade = "A" | "B" | "C" | "D" | "F";

interface HealthScore {
  client_id: string;
  overall_score: number;
  health_grade: Grade;
  compliance_score: number;
  accounting_score: number;
  documents_score: number;
  responsiveness_score: number;
  relationship_risk_score: number;
  financial_risk_score: number;
  engagement_health_score: number;
  last_calculated_at: string;
  is_critical: boolean;
  is_at_risk: boolean;
}

interface HistoryRecord {
  id: string;
  overall_score: number;
  health_grade: Grade;
  recorded_at: string;
}

interface HealthAlert {
  id: string;
  alert_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  is_resolved: boolean;
  created_at: string;
}

interface HealthOverride {
  id: string;
  dimension?: string;
  override_score: number;
  reason: string;
  expires_at?: string;
  is_active: boolean;
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

const DIMENSION_LABELS: Record<string, string> = {
  compliance_score:        "Compliance",
  accounting_score:        "Accounting",
  documents_score:         "Documents",
  responsiveness_score:    "Responsiveness",
  relationship_risk_score: "Relationship Risk",
  financial_risk_score:    "Financial Risk",
  engagement_health_score: "Engagement Health",
};

const DIMENSION_KEYS = Object.keys(DIMENSION_LABELS);

const SEVERITY_COLORS: Record<string, string> = {
  info:     "bg-blue-100 text-blue-700",
  warning:  "bg-yellow-100 text-yellow-700",
  critical: "bg-red-100 text-red-700",
};

function scoreColor(s: number) {
  if (s >= 70) return "text-green-600";
  if (s >= 40) return "text-amber-600";
  return "text-red-600";
}

function scoreBarColor(s: number) {
  if (s >= 70) return "bg-green-500";
  if (s >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

function gradeBadge(g: Grade) {
  const map: Record<Grade, string> = {
    A: "bg-green-100 text-green-700",
    B: "bg-blue-100 text-blue-700",
    C: "bg-yellow-100 text-yellow-700",
    D: "bg-orange-100 text-orange-700",
    F: "bg-red-100 text-red-700",
  };
  return map[g] ?? "bg-gray-100 text-gray-600";
}

function formatDate(d?: string | null) {
  if (!d) return "—";
  try { return formatDateShared(d); }
  catch { return d; }
}

const EMPTY_OVERRIDE = { dimension: "compliance_score", override_score: "", reason: "", expires_at: "" };

export default function ClientHealthPage() {
  const { clientId } = useClientNav();
  const [score, setScore] = useState<HealthScore | null>(null);
  const [history, setHistory] = useState<HistoryRecord[]>([]);
  const [alerts, setAlerts] = useState<HealthAlert[]>([]);
  const [overrides, setOverrides] = useState<HealthOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  const [overrideModal, setOverrideModal] = useState(false);
  const [overrideForm, setOverrideForm] = useState(EMPTY_OVERRIDE);
  const [savingOverride, setSavingOverride] = useState(false);

  // Plain filtered reads — routed directly to Supabase (RLS: health_scores,
  // health_score_history, health_overrides, health_alerts all scope on
  // firm_id = get_my_firm_id(), migration 154). The FastAPI backend cold-starts
  // on its hosting tier, so reads that are just `.eq(...)` selects skip it
  // entirely, matching the pattern already used by Sales/Inventory/etc.
  // The actual score COMPUTATION (POST .../calculate) stays backend-routed —
  // that's real business logic, not a plain read.
  const loadAll = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const supabase = getSupabaseClient();
      const [scoreRes, histRes, alertsRes, overridesRes] = await Promise.all([
        supabase.from("health_scores").select("*").eq("client_id", clientId).maybeSingle(),
        supabase
          .from("health_score_history")
          .select("id, overall_score, health_grade, recorded_at")
          .eq("client_id", clientId)
          .order("recorded_at", { ascending: false })
          .limit(20),
        supabase
          .from("health_alerts")
          .select("*")
          .eq("client_id", clientId)
          .eq("is_resolved", false)
          .order("created_at", { ascending: false }),
        supabase
          .from("health_overrides")
          .select("*")
          .eq("client_id", clientId)
          .eq("is_active", true)
          .order("created_at", { ascending: false }),
      ]);
      if (scoreRes.error) throw new Error(scoreRes.error.message);
      if (histRes.error) throw new Error(histRes.error.message);
      if (alertsRes.error) throw new Error(alertsRes.error.message);
      if (overridesRes.error) throw new Error(overridesRes.error.message);
      setScore((scoreRes.data as HealthScore | null) ?? null);
      setHistory((histRes.data as HistoryRecord[]) ?? []);
      setAlerts((alertsRes.data as HealthAlert[]) ?? []);
      setOverrides((overridesRes.data as HealthOverride[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleRecalculate() {
    setRecalculating(true);
    try {
      const json: ApiResponse<HealthScore> = await apiFetch(
        `/api/health/scores/${clientId}/calculate`, { method: "POST" }
      );
      if (json.success) setScore(json.data);
      await loadAll();
    } catch { /* non-fatal */ }
    finally { setRecalculating(false); }
  }

  async function handleAddOverride() {
    if (!overrideForm.reason.trim() || !overrideForm.override_score) return;
    setSavingOverride(true);
    try {
      const json: ApiResponse<HealthOverride> = await apiFetch(
        `/api/health/scores/${clientId}/override`,
        {
          method: "POST",
          body: JSON.stringify({
            dimension: overrideForm.dimension || null,
            override_score: parseInt(overrideForm.override_score, 10),
            reason: overrideForm.reason.trim(),
            expires_at: overrideForm.expires_at || null,
          }),
        }
      );
      if (!json.success) throw new Error(json.error ?? "Failed");
      setOverrides((prev) => [json.data, ...prev]);
      setOverrideModal(false);
      setOverrideForm(EMPTY_OVERRIDE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save override");
    } finally {
      setSavingOverride(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        {/* Score hero */}
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="flex items-center gap-6">
            <div className="text-center space-y-2">
              <Skeleton className="h-10 w-16 mx-auto" />
              <Skeleton className="h-2.5 w-8 mx-auto" />
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div className="space-y-2">
              <Skeleton className="h-2.5 w-12" />
              <Skeleton className="h-6 w-9 rounded" />
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div className="space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-2.5 w-24" />
            </div>
          </div>
        </div>

        {/* Dimension scores */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
              <div className="flex items-center justify-between">
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="h-3.5 w-6" />
              </div>
              <Skeleton className="h-2 w-full rounded-full" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!score) {
    return (
      <div className="p-6 space-y-4">
        {error && (
          <div className="bg-red-50 text-red-700 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>
        )}
        <Card className="bg-white border border-gray-200">
          <CardContent className="py-12 text-center">
            <Activity size={32} className="text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500 mb-4">No health score calculated yet</p>
            <button
              onClick={handleRecalculate}
              disabled={recalculating}
              className="inline-flex items-center gap-2 text-sm bg-[#182350] text-white px-4 py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
            >
              <RefreshCw size={14} className={recalculating ? "animate-spin" : ""} />
              {recalculating ? "Calculating…" : "Calculate Now"}
            </button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold text-[#182350]">Client Health</h1>
        <button
          onClick={handleRecalculate}
          disabled={recalculating}
          className="flex items-center gap-1.5 text-xs text-gray-600 border border-gray-200 px-3 py-1.5 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={recalculating ? "animate-spin" : ""} />
          Recalculate
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Score hero */}
      <Card className="bg-white border border-gray-200">
        <CardContent className="p-6">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className={`text-6xl font-black ${scoreColor(score.overall_score)}`}>{score.overall_score}</p>
              <p className="text-xs text-gray-500 mt-1">/ 100</p>
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div>
              <p className="text-xs text-gray-500 mb-1">Grade</p>
              <Badge className={`text-lg px-3 py-1 ${gradeBadge(score.health_grade)}`}>{score.health_grade}</Badge>
            </div>
            <div className="w-px h-16 bg-gray-200" />
            <div className="space-y-1">
              {score.is_critical && <Badge className="bg-red-100 text-red-700 text-[10px]">CRITICAL</Badge>}
              {score.is_at_risk && !score.is_critical && <Badge className="bg-amber-100 text-amber-700 text-[10px]">AT RISK</Badge>}
              <p className="text-[11px] text-gray-500">Last: {formatDate(score.last_calculated_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Dimensions */}
      <div>
        <h2 className="text-sm font-semibold text-[#182350] mb-3">Dimension Scores</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {DIMENSION_KEYS.map((key) => {
            const val = (score as unknown as Record<string, number>)[key] ?? 0;
            return (
              <Card key={key} className="bg-white border border-gray-200">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-gray-500">{DIMENSION_LABELS[key]}</p>
                    <span className={`text-sm font-bold ${scoreColor(val)}`}>{val}</span>
                  </div>
                  <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${scoreBarColor(val)}`} style={{ width: `${val}%` }} />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Active alerts */}
      {alerts.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-[#182350] mb-3">Active Alerts ({alerts.length})</h2>
          <div className="space-y-2">
            {alerts.map((a) => (
              <Card key={a.id} className="bg-white border border-gray-200">
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={`text-[10px] ${SEVERITY_COLORS[a.severity] ?? "bg-gray-100 text-gray-600"}`}>
                      {a.severity.toUpperCase()}
                    </Badge>
                    <span className="text-[10px] text-gray-500">{a.alert_type}</span>
                  </div>
                  <p className="text-sm text-gray-800">{a.message}</p>
                  <p className="text-xs text-gray-500 mt-1">{formatDate(a.created_at)}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Score history */}
      {history.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-[#182350] mb-3">Score History</h2>
          <Card className="bg-white border border-gray-200">
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Calculated At</th>
                    <th className="px-3 py-3 text-left font-medium">Score</th>
                    <th className="px-3 py-3 text-left font-medium">Grade</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {history.slice(0, 10).map((h) => (
                    <tr key={h.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 text-gray-500 text-xs">{formatDate(h.recorded_at)}</td>
                      <td className="px-3 py-3">
                        <span className={`font-bold ${scoreColor(h.overall_score)}`}>{h.overall_score}</span>
                        <span className="text-xs text-gray-400">/100</span>
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[11px] ${gradeBadge(h.health_grade)}`}>{h.health_grade}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Overrides */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-[#182350]">Active Overrides ({overrides.length})</h2>
          <button
            onClick={() => { setOverrideForm(EMPTY_OVERRIDE); setOverrideModal(true); }}
            className="flex items-center gap-1 text-xs text-[#182350] border border-[#182350] px-2.5 py-1 rounded hover:bg-[#AFD2FA]/20"
          >
            <Plus size={12} /> Add Override
          </button>
        </div>
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {overrides.length === 0 ? (
              <div className="py-8 text-center"><p className="text-sm text-gray-500">No active overrides</p></div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Dimension</th>
                    <th className="px-3 py-3 text-left font-medium">Score</th>
                    <th className="px-3 py-3 text-left font-medium">Reason</th>
                    <th className="px-3 py-3 text-left font-medium">Expires</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {overrides.map((o) => (
                    <tr key={o.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Badge className="bg-emerald-100 text-emerald-700 text-[10px]">
                          {DIMENSION_LABELS[o.dimension ?? ""] ?? o.dimension ?? "Overall"}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 font-bold text-xs">
                        <span className={scoreColor(o.override_score)}>{o.override_score}</span>
                      </td>
                      <td className="px-3 py-3 text-gray-700 text-xs max-w-xs truncate">{o.reason}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(o.expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Override Modal */}
      {overrideModal && (
        <div className="fixed inset-0 bg-gray-900/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">Add Override</h2>
              <button onClick={() => setOverrideModal(false)} className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600">Dimension</label>
                <select
                  value={overrideForm.dimension}
                  onChange={(e) => setOverrideForm({ ...overrideForm, dimension: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                >
                  {DIMENSION_KEYS.map((k) => <option key={k} value={k}>{DIMENSION_LABELS[k]}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600">Override Score (0–100) *</label>
                <input
                  type="number" min="0" max="100"
                  value={overrideForm.override_score}
                  onChange={(e) => setOverrideForm({ ...overrideForm, override_score: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="0–100"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Reason *</label>
                <textarea
                  rows={3}
                  value={overrideForm.reason}
                  onChange={(e) => setOverrideForm({ ...overrideForm, reason: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 resize-none focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="Explain why…"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Expires At (optional)</label>
                <input
                  type="date"
                  value={overrideForm.expires_at}
                  onChange={(e) => setOverrideForm({ ...overrideForm, expires_at: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setOverrideModal(false)} className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50">Cancel</button>
              <button
                onClick={handleAddOverride}
                disabled={savingOverride || !overrideForm.reason.trim() || !overrideForm.override_score}
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

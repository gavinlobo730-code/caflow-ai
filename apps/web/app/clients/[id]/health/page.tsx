"use client";

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Plus, X, Activity } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatDate as formatDateShared } from "@/lib/services/formatting";
import { Callout } from "@/components/ui/callout";
import { arrayOrEmpty } from "@/lib/api/shape";

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
  // Answered by GET /api/health/overrides — see the firm health screen's
  // copy of this note. Whether an override is in force is the rule the
  // CALCULATION applies, so it is served rather than re-derived here.
  in_force?: boolean;
  not_in_force_because?: string | null;
  explanation?: string | null;
  computed_score?: number | null;
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

// ⚠️ AN OVERRIDE NAMES A DIMENSION OF THE MODEL, AND `DIMENSION_LABELS` ABOVE
// IS NOT THAT LIST. Those seven are the legacy FLAT COLUMNS on `health_scores`
// (`compliance_score`, `relationship_risk_score`, …), kept because the cards
// below read them straight off the score row. Product Bible Chapter 16's model
// has seven DIFFERENT dimensions, which is what `health_overrides.dimension`
// is matched against — so this picker used to offer "Relationship Risk", the
// CA chose it, the row was stored, and it could not replace anything because
// the engine has no such dimension. Now that overrides actually apply, an
// unknown one comes back NAMED as not in force; offering it at all would be
// inviting a CA to record something the server will not honour.
const OVERRIDE_DIMENSIONS: Record<string, string> = {
  compliance_health:     "Compliance Health",
  accounting_quality:    "Accounting Quality",
  work_progress:         "Work Progress",
  document_health:       "Document Health",
  ai_risk_signals:       "AI Risk Signals",
  open_notices:          "Open Notices",
  client_responsiveness: "Client Responsiveness",
};
const OVERRIDE_DIMENSION_KEYS = Object.keys(OVERRIDE_DIMENSIONS);

const SEVERITY_COLORS: Record<string, string> = {
  info:     "bg-sev-low-surface text-sev-low",
  warning:  "bg-sev-medium-surface text-sev-medium",
  critical: "bg-sev-critical-surface text-sev-critical",
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
    A: "bg-sev-ok-surface text-sev-ok",
    B: "bg-sev-low-surface text-sev-low",
    C: "bg-sev-medium-surface text-sev-medium",
    D: "bg-sev-high-surface text-sev-high",
    F: "bg-sev-critical-surface text-sev-critical",
  };
  return map[g] ?? "bg-gray-100 text-gray-600";
}

function formatDate(d?: string | null) {
  if (!d) return "—";
  try { return formatDateShared(d); }
  catch { return d; }
}

const EMPTY_OVERRIDE = { dimension: "compliance_health", override_score: "", reason: "", expires_at: "" };

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
  const [removingOverride, setRemovingOverride] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [savingOverride, setSavingOverride] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = recalculating || savingOverride;

  // Plain filtered reads — routed directly to Supabase (RLS: health_scores,
  // health_score_history, health_alerts all scope on
  // firm_id = get_my_firm_id(), migration 154). The FastAPI backend cold-starts
  // on its hosting tier, so reads that are just `.eq(...)` selects skip it
  // entirely, matching the pattern already used by Sales/Inventory/etc.
  // The actual score COMPUTATION (POST .../calculate) stays backend-routed —
  // that's real business logic, not a plain read.
  const loadOverrides = useCallback(async () => {
    // Not a plain read any more: which recorded overrides are actually in
    // force is a rule (expiry in IST, an unknown dimension, a later one
    // superseding it), and the score calculation applies the same one.
    const json: ApiResponse<HealthOverride[]> = await apiFetch(
      `/api/health/overrides?client_id=${encodeURIComponent(clientId)}`
    );
    if (!json.success) throw new Error(json.error ?? "Failed to load overrides");
    setOverrides(arrayOrEmpty<HealthOverride>(json.data));
  }, [clientId]);

  const loadAll = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const supabase = getSupabaseClient();
      const [scoreRes, histRes, alertsRes] = await Promise.all([
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
      ]);
      if (scoreRes.error) throw new Error(scoreRes.error.message);
      if (histRes.error) throw new Error(histRes.error.message);
      if (alertsRes.error) throw new Error(alertsRes.error.message);
      setScore((scoreRes.data as HealthScore | null) ?? null);
      setHistory((histRes.data as HistoryRecord[]) ?? []);
      setAlerts((alertsRes.data as HealthAlert[]) ?? []);
      await loadOverrides();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId, loadOverrides]);

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
      // Re-read rather than unshifting the create response: it is the stored
      // row and carries no `in_force`, so the CA would not learn whether the
      // override they just recorded is actually replacing anything.
      await loadOverrides();
      setOverrideModal(false);
      setOverrideForm(EMPTY_OVERRIDE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save override");
    } finally {
      setSavingOverride(false);
    }
  }

  async function handleRemoveOverride(overrideId: string) {
    // `DELETE /api/health/overrides/{id}` has been written and guarded since
    // migration 059 with no caller, so an override with no end date could
    // never be withdrawn.
    setRemovingOverride(overrideId);
    setRemoveError(null);
    try {
      const json: ApiResponse<unknown> = await apiFetch(
        `/api/health/overrides/${overrideId}`, { method: "DELETE" }
      );
      if (!json.success) throw new Error(json.error ?? "Failed to remove override");
      await loadOverrides();
    } catch (e) {
      setRemoveError(e instanceof Error ? e.message : "Failed to remove override");
    } finally {
      setRemovingOverride(null);
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
        {error && <Callout tone="problem">{error}</Callout>}
        <Card className="bg-white border border-gray-200">
          <CardContent className="py-12 text-center">
            <Activity size={32} className="text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500 mb-4">No health score calculated yet</p>
            <button
              onClick={handleRecalculate}
              disabled={actionInFlight}
              className="inline-flex items-center gap-2 text-sm bg-brand text-white px-4 py-2 rounded-md hover:bg-brand-dark disabled:opacity-50"
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
        <h1 className="text-base font-semibold text-brand">Client Health</h1>
        <button
          onClick={handleRecalculate}
          disabled={actionInFlight}
          className="flex items-center gap-1.5 text-xs text-gray-600 border border-gray-200 px-3 py-1.5 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={recalculating ? "animate-spin" : ""} />
          Recalculate
        </button>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

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
              {score.is_critical && <Badge className="bg-state-problem-surface text-state-problem text-3xs">CRITICAL</Badge>}
              {score.is_at_risk && !score.is_critical && <Badge className="bg-state-attention-surface text-state-attention text-3xs">AT RISK</Badge>}
              <p className="text-2xs text-gray-500">Last: {formatDate(score.last_calculated_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Dimensions */}
      <div>
        <h2 className="text-sm font-semibold text-brand mb-3">Dimension Scores</h2>
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
          <h2 className="text-sm font-semibold text-brand mb-3">Active Alerts ({alerts.length})</h2>
          <div className="space-y-2">
            {alerts.map((a) => (
              <Card key={a.id} className="bg-white border border-gray-200">
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={`text-3xs ${SEVERITY_COLORS[a.severity] ?? "bg-gray-100 text-gray-600"}`}>
                      {a.severity.toUpperCase()}
                    </Badge>
                    <span className="text-3xs text-gray-500">{a.alert_type}</span>
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
          <h2 className="text-sm font-semibold text-brand mb-3">Score History</h2>
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
                        <Badge className={`text-2xs ${gradeBadge(h.health_grade)}`}>{h.health_grade}</Badge>
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
          <h2 className="text-sm font-semibold text-brand">Overrides ({overrides.length})</h2>
          <button
            onClick={() => { setOverrideForm(EMPTY_OVERRIDE); setOverrideModal(true); }}
            className="flex items-center gap-1 text-xs text-brand border border-brand px-2.5 py-1 rounded hover:bg-brand-light/20"
          >
            <Plus size={12} /> Add Override
          </button>
        </div>
        {removeError && <div className="mb-2"><Callout tone="problem">{removeError}</Callout></div>}
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {overrides.length === 0 ? (
              <div className="py-8 text-center"><p className="text-sm text-gray-500">No overrides recorded</p></div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Dimension</th>
                    <th className="px-3 py-3 text-left font-medium">Score</th>
                    <th className="px-3 py-3 text-left font-medium">Reason</th>
                    <th className="px-3 py-3 text-left font-medium">Expires</th>
                    <th className="px-3 py-3 text-right font-medium">&nbsp;</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {overrides.map((o) => {
                    // The SERVER's answer. An absent key reads as in force, so
                    // a browser deployed ahead of its backend renders exactly
                    // as it did before.
                    const live = o.in_force !== false;
                    return (
                    <tr key={o.id} className={live ? "hover:bg-ps-hover" : "bg-ps-muted"}>
                      <td className="px-5 py-3">
                        <Badge className={live
                          ? "bg-state-ready-surface text-state-ready text-3xs"
                          : "bg-ps-muted text-ps-hint text-3xs"}>
                          {OVERRIDE_DIMENSIONS[o.dimension ?? ""] ?? o.dimension ?? "Overall"}
                        </Badge>
                        {!live && (
                          <p className="text-3xs text-ps-hint mt-1 max-w-xs">
                            {o.explanation ?? "Not in force."}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-3 font-bold text-xs">
                        {live ? (
                          <span className="whitespace-nowrap">
                            {o.computed_score != null && (
                              <span className="text-ps-hint line-through mr-1.5 font-normal">
                                {o.computed_score}
                              </span>
                            )}
                            <span className={scoreColor(o.override_score)}>{o.override_score}</span>
                          </span>
                        ) : (
                          <span className="text-ps-hint line-through">{o.override_score}</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-gray-700 text-xs max-w-xs truncate">{o.reason}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(o.expires_at)}</td>
                      <td className="px-3 py-3 text-right">
                        <button
                          onClick={() => handleRemoveOverride(o.id)}
                          disabled={removingOverride === o.id}
                          className="text-xs text-state-problem hover:underline disabled:opacity-50"
                        >
                          {removingOverride === o.id ? "Removing…" : "Remove"}
                        </button>
                      </td>
                    </tr>
                    );
                  })}
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
              <h2 className="text-sm font-semibold text-brand">Add Override</h2>
              <button onClick={() => setOverrideModal(false)} className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600">Dimension</label>
                <select
                  value={overrideForm.dimension}
                  onChange={(e) => setOverrideForm({ ...overrideForm, dimension: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                >
                  {OVERRIDE_DIMENSION_KEYS.map((k) => (
                    <option key={k} value={k}>{OVERRIDE_DIMENSIONS[k]}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600">Override Score (0–100) *</label>
                <input
                  type="number" min="0" max="100"
                  value={overrideForm.override_score}
                  onChange={(e) => setOverrideForm({ ...overrideForm, override_score: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                  placeholder="0–100"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Reason *</label>
                <textarea
                  rows={3}
                  value={overrideForm.reason}
                  onChange={(e) => setOverrideForm({ ...overrideForm, reason: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 resize-none focus:outline-none focus:ring-2 focus:ring-brand"
                  placeholder="Explain why…"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Expires At (optional)</label>
                <input
                  type="date"
                  value={overrideForm.expires_at}
                  onChange={(e) => setOverrideForm({ ...overrideForm, expires_at: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setOverrideModal(false)} className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50">Cancel</button>
              <button
                onClick={handleAddOverride}
                disabled={actionInFlight || !overrideForm.reason.trim() || !overrideForm.override_score}
                className="flex-1 text-sm bg-brand text-white py-2 rounded-md hover:bg-brand-dark disabled:opacity-50"
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

"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, X, CheckCircle, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
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

interface OnboardingTask {
  id: string;
  title: string;
  status: "Pending" | "In Progress" | "Done" | "Skipped";
  sort_order: number;
  notes?: string;
}

interface OnboardingWorkflow {
  id: string;
  client_id: string;
  status: "In Progress" | "Completed";
  notes?: string;
  created_at: string;
  completed_at?: string;
  tasks?: OnboardingTask[];
}

interface Renewal {
  id: string;
  financial_year: string;
  service_type: string;
  renewal_date?: string;
  value_paise: number;
  status: string;
  assigned_to?: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

const TASK_STATUS_COLORS: Record<OnboardingTask["status"], string> = {
  Pending:      "bg-slate-700 text-slate-300",
  "In Progress":"bg-blue-800 text-blue-300",
  Done:         "bg-green-800 text-green-300",
  Skipped:      "bg-gray-700 text-gray-400",
};

const RENEWAL_STATUS_COLORS: Record<string, string> = {
  Pending:   "bg-amber-800 text-amber-300",
  Completed: "bg-green-800 text-green-300",
  Overdue:   "bg-red-800 text-red-300",
  Cancelled: "bg-gray-700 text-gray-400",
};

function formatDate(d?: string | null) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return d; }
}

function paiseToCurrency(p: number) {
  return `₹${(p / 100).toLocaleString("en-IN")}`;
}

export default function ClientLifecyclePage() {
  const { clientId } = useClientNav();
  const [workflows, setWorkflows] = useState<OnboardingWorkflow[]>([]);
  const [renewals, setRenewals] = useState<Renewal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingWorkflow, setCreatingWorkflow] = useState(false);
  const [renewalModal, setRenewalModal] = useState(false);
  const [renewalForm, setRenewalForm] = useState({
    financial_year: "", service_type: "", renewal_date: "", value_paise: "", notes: "",
  });
  const [savingRenewal, setSavingRenewal] = useState(false);

  const loadAll = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const [wfJson, rnJson]: [
        ApiResponse<OnboardingWorkflow[]>,
        ApiResponse<Renewal[]>
      ] = await Promise.all([
        apiFetch(`/api/lifecycle/onboarding?client_id=${clientId}`),
        apiFetch(`/api/lifecycle/renewals?limit=50`),
      ]);
      setWorkflows(wfJson.success ? wfJson.data : []);
      const clientRenewals = rnJson.success
        ? rnJson.data.filter((r: Renewal & { client_id?: string }) => r.client_id === clientId)
        : [];
      setRenewals(clientRenewals);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleCreateWorkflow() {
    setCreatingWorkflow(true);
    try {
      const json: ApiResponse<OnboardingWorkflow> = await apiFetch("/api/lifecycle/onboarding", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to create workflow");
      setWorkflows((prev) => [json.data, ...prev]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create workflow");
    } finally {
      setCreatingWorkflow(false);
    }
  }

  async function handleUpdateTask(workflowId: string, taskId: string, status: OnboardingTask["status"]) {
    try {
      const json: ApiResponse<OnboardingTask> = await apiFetch(
        `/api/lifecycle/onboarding/${workflowId}/tasks/${taskId}`,
        { method: "PATCH", body: JSON.stringify({ status }) }
      );
      if (!json.success) return;
      setWorkflows((prev) =>
        prev.map((wf) =>
          wf.id === workflowId
            ? { ...wf, tasks: (wf.tasks ?? []).map((t) => (t.id === taskId ? { ...t, status } : t)) }
            : wf
        )
      );
    } catch { /* non-fatal */ }
  }

  async function handleSaveRenewal() {
    if (!renewalForm.financial_year || !renewalForm.service_type) return;
    setSavingRenewal(true);
    try {
      const json: ApiResponse<Renewal> = await apiFetch("/api/lifecycle/renewals", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: renewalForm.financial_year,
          service_type: renewalForm.service_type,
          renewal_date: renewalForm.renewal_date || null,
          value_paise: parseInt(renewalForm.value_paise || "0", 10) * 100,
          notes: renewalForm.notes || null,
        }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to save");
      setRenewals((prev) => [json.data, ...prev]);
      setRenewalModal(false);
      setRenewalForm({ financial_year: "", service_type: "", renewal_date: "", value_paise: "", notes: "" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save renewal");
    } finally {
      setSavingRenewal(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        {[1, 2].map((i) => <div key={i} className="h-32 bg-white/[0.05] rounded-xl" />)}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-white">Lifecycle</h1>
          <p className="text-xs text-slate-400 mt-0.5">Onboarding workflows and renewals</p>
        </div>
        <button
          onClick={handleCreateWorkflow}
          disabled={creatingWorkflow}
          className="flex items-center gap-1.5 text-xs bg-emerald-600 text-white px-3 py-1.5 rounded-md hover:bg-emerald-700 disabled:opacity-50"
        >
          <Plus size={12} /> New Onboarding
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 text-red-400 border border-red-800 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Onboarding Workflows */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">
          Onboarding Workflows
          <span className="ml-2 text-xs text-slate-500 font-normal">({workflows.length})</span>
        </h2>
        {workflows.length === 0 ? (
          <Card className="bg-gray-800 border-gray-700">
            <CardContent className="py-10 text-center">
              <p className="text-sm text-slate-500">No onboarding workflows yet</p>
              <button
                onClick={handleCreateWorkflow}
                className="mt-3 text-xs text-emerald-400 hover:text-emerald-300 underline"
              >
                Create one now
              </button>
            </CardContent>
          </Card>
        ) : (
          workflows.map((wf) => {
            const tasks = wf.tasks ?? [];
            const done = tasks.filter((t) => t.status === "Done" || t.status === "Skipped").length;
            const pct = tasks.length > 0 ? Math.round((done / tasks.length) * 100) : 0;
            return (
              <Card key={wf.id} className="bg-gray-800 border-gray-700 mb-3">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {wf.status === "Completed"
                        ? <CheckCircle size={16} className="text-green-400" />
                        : <Clock size={16} className="text-amber-400" />}
                      <span className="text-sm font-medium text-white">
                        {wf.status === "Completed" ? "Onboarding Completed" : "Onboarding In Progress"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-400">{done}/{tasks.length} tasks</span>
                      <div className="w-24 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  </div>
                  {tasks.length > 0 && (
                    <div className="space-y-1.5 mt-3">
                      {tasks
                        .sort((a, b) => a.sort_order - b.sort_order)
                        .map((task) => (
                          <div key={task.id} className="flex items-center justify-between px-3 py-2 rounded-md bg-gray-700/50">
                            <span className={`text-xs ${task.status === "Done" || task.status === "Skipped" ? "text-slate-500 line-through" : "text-slate-300"}`}>
                              {task.title}
                            </span>
                            {task.status !== "Done" && task.status !== "Skipped" ? (
                              <button
                                onClick={() => handleUpdateTask(wf.id, task.id, "Done")}
                                className="text-[10px] text-emerald-400 hover:text-emerald-300 ml-2 shrink-0"
                              >
                                Mark Done
                              </button>
                            ) : (
                              <Badge className={`text-[10px] ${TASK_STATUS_COLORS[task.status]}`}>
                                {task.status}
                              </Badge>
                            )}
                          </div>
                        ))}
                    </div>
                  )}
                  <p className="text-[11px] text-slate-500 mt-3">Started {formatDate(wf.created_at)}</p>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* Renewals */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white">
            Renewals
            <span className="ml-2 text-xs text-slate-500 font-normal">({renewals.length})</span>
          </h2>
          <button
            onClick={() => setRenewalModal(true)}
            className="flex items-center gap-1 text-xs text-emerald-400 border border-emerald-700 px-2.5 py-1 rounded hover:bg-emerald-900/30"
          >
            <Plus size={12} /> Add Renewal
          </button>
        </div>
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {renewals.length === 0 ? (
              <div className="py-10 text-center">
                <p className="text-sm text-slate-500">No renewals tracked</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Service</th>
                    <th className="px-3 py-3 text-left font-medium">FY</th>
                    <th className="px-3 py-3 text-left font-medium">Renewal Date</th>
                    <th className="px-3 py-3 text-left font-medium">Value</th>
                    <th className="px-3 py-3 text-left font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {renewals.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3 text-white text-xs font-medium">{r.service_type}</td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{r.financial_year}</td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{formatDate(r.renewal_date)}</td>
                      <td className="px-3 py-3 text-slate-300 text-xs">{paiseToCurrency(r.value_paise)}</td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[10px] ${RENEWAL_STATUS_COLORS[r.status] ?? "bg-slate-700 text-slate-300"}`}>
                          {r.status}
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

      {/* Renewal Modal */}
      {renewalModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-white">Add Renewal</h2>
              <button onClick={() => setRenewalModal(false)} className="text-slate-500 hover:text-white"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400">Service Type *</label>
                <input
                  value={renewalForm.service_type}
                  onChange={(e) => setRenewalForm({ ...renewalForm, service_type: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. GST Filing, ITR, Audit"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400">Financial Year *</label>
                <input
                  value={renewalForm.financial_year}
                  onChange={(e) => setRenewalForm({ ...renewalForm, financial_year: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. 2025-26"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400">Renewal Date</label>
                <input
                  type="date"
                  value={renewalForm.renewal_date}
                  onChange={(e) => setRenewalForm({ ...renewalForm, renewal_date: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400">Value (₹)</label>
                <input
                  type="number"
                  value={renewalForm.value_paise}
                  onChange={(e) => setRenewalForm({ ...renewalForm, value_paise: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-gray-800 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. 15000"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setRenewalModal(false)} className="flex-1 text-sm text-slate-400 border border-gray-700 py-2 rounded-md hover:bg-gray-800">Cancel</button>
              <button
                onClick={handleSaveRenewal}
                disabled={savingRenewal || !renewalForm.service_type || !renewalForm.financial_year}
                className="flex-1 text-sm bg-emerald-600 text-white py-2 rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {savingRenewal ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

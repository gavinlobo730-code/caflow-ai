"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, X, CheckCircle, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

interface OnboardingTask {
  id: string;
  task_name: string;
  status: "pending" | "in_progress" | "done" | "skipped";
  sort_order: number;
  description?: string;
}

interface OnboardingWorkflow {
  id: string;
  client_id: string;
  status: "in_progress" | "completed" | "pending" | "cancelled";
  created_at: string;
  completed_at?: string;
  tasks?: OnboardingTask[];
}

interface Renewal {
  id: string;
  financial_year: string;
  service_type?: string;
  renewal_date?: string;
  fee_paise: number;
  status: string;
  assigned_to?: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

const TASK_STATUS_COLORS: Record<string, string> = {
  pending:     "bg-gray-100 text-gray-600",
  in_progress: "bg-blue-100 text-blue-700",
  done:        "bg-green-100 text-green-700",
  skipped:     "bg-gray-100 text-gray-500",
};

const RENEWAL_STATUS_COLORS: Record<string, string> = {
  pending:  "bg-amber-100 text-amber-700",
  accepted: "bg-green-100 text-green-700",
  expired:  "bg-red-100 text-red-700",
  rejected: "bg-gray-100 text-gray-500",
  sent:     "bg-blue-100 text-blue-700",
};

function formatDate(d?: string | null) {
  if (!d) return "—";
  try {
    return formatDateShared(d);
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

  async function handleUpdateTask(workflowId: string, taskId: string, status: string) {
    try {
      const json: ApiResponse<OnboardingTask> = await apiFetch(
        `/api/lifecycle/onboarding/${workflowId}/tasks/${taskId}`,
        { method: "PATCH", body: JSON.stringify({ status }) }
      );
      if (!json.success) return;
      setWorkflows((prev) =>
        prev.map((wf) =>
          wf.id === workflowId
            ? { ...wf, tasks: (wf.tasks ?? []).map((t) => (t.id === taskId ? { ...t, status: status as OnboardingTask["status"] } : t)) }
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
        {[1, 2].map((i) => <div key={i} className="h-32 bg-gray-100 rounded-xl" />)}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-[#182350]">Lifecycle</h1>
          <p className="text-xs text-gray-500 mt-0.5">Onboarding workflows and renewals</p>
        </div>
        <button
          onClick={handleCreateWorkflow}
          disabled={creatingWorkflow}
          className="flex items-center gap-1.5 text-xs bg-[#182350] text-white px-3 py-1.5 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
        >
          <Plus size={12} /> New Onboarding
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Onboarding Workflows */}
      <div>
        <h2 className="text-sm font-semibold text-[#182350] mb-3">
          Onboarding Workflows
          <span className="ml-2 text-xs text-gray-500 font-normal">({workflows.length})</span>
        </h2>
        {workflows.length === 0 ? (
          <Card className="bg-white border border-gray-200">
            <CardContent className="py-10 text-center">
              <p className="text-sm text-gray-500">No onboarding workflows yet</p>
              <button
                onClick={handleCreateWorkflow}
                className="mt-3 text-xs text-[#182350] hover:text-[#0D1635] underline"
              >
                Create one now
              </button>
            </CardContent>
          </Card>
        ) : (
          workflows.map((wf) => {
            const tasks = wf.tasks ?? [];
            const done = tasks.filter((t) => t.status === "done" || t.status === "skipped").length;
            const pct = tasks.length > 0 ? Math.round((done / tasks.length) * 100) : 0;
            return (
              <Card key={wf.id} className="bg-white border border-gray-200 mb-3">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {wf.status === "completed"
                        ? <CheckCircle size={16} className="text-green-400" />
                        : <Clock size={16} className="text-amber-400" />}
                      <span className="text-sm font-medium text-gray-800">
                        {wf.status === "completed" ? "Onboarding Completed" : "Onboarding In Progress"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-gray-500">{done}/{tasks.length} tasks</span>
                      <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  </div>
                  {tasks.length > 0 && (
                    <div className="space-y-1.5 mt-3">
                      {tasks
                        .sort((a, b) => a.sort_order - b.sort_order)
                        .map((task) => (
                          <div key={task.id} className="flex items-center justify-between px-3 py-2 rounded-md bg-gray-50">
                            <span className={`text-xs ${task.status === "done" || task.status === "skipped" ? "text-gray-400 line-through" : "text-gray-700"}`}>
                              {task.task_name}
                            </span>
                            {task.status !== "done" && task.status !== "skipped" ? (
                              <button
                                onClick={() => handleUpdateTask(wf.id, task.id, "done")}
                                className="text-[10px] text-[#182350] hover:text-[#0D1635] ml-2 shrink-0"
                              >
                                Mark Done
                              </button>
                            ) : (
                              <Badge className={`text-[10px] ${TASK_STATUS_COLORS[task.status] ?? "bg-gray-100 text-gray-600"}`}>
                                {task.status}
                              </Badge>
                            )}
                          </div>
                        ))}
                    </div>
                  )}
                  <p className="text-[11px] text-gray-500 mt-3">Started {formatDate(wf.created_at)}</p>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* Renewals */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-[#182350]">
            Renewals
            <span className="ml-2 text-xs text-gray-500 font-normal">({renewals.length})</span>
          </h2>
          <button
            onClick={() => setRenewalModal(true)}
            className="flex items-center gap-1 text-xs text-[#182350] border border-[#182350] px-2.5 py-1 rounded hover:bg-[#AFD2FA]/20"
          >
            <Plus size={12} /> Add Renewal
          </button>
        </div>
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {renewals.length === 0 ? (
              <div className="py-10 text-center">
                <p className="text-sm text-gray-500">No renewals tracked</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Service</th>
                    <th className="px-3 py-3 text-left font-medium">FY</th>
                    <th className="px-3 py-3 text-left font-medium">Renewal Date</th>
                    <th className="px-3 py-3 text-left font-medium">Value</th>
                    <th className="px-3 py-3 text-left font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {renewals.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 text-gray-800 text-xs font-medium">{r.service_type ?? "—"}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{r.financial_year}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(r.renewal_date)}</td>
                      <td className="px-3 py-3 text-gray-700 text-xs">{paiseToCurrency(r.fee_paise ?? 0)}</td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[10px] ${RENEWAL_STATUS_COLORS[r.status] ?? "bg-gray-100 text-gray-600"}`}>
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
        <div className="fixed inset-0 bg-gray-900/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">Add Renewal</h2>
              <button onClick={() => setRenewalModal(false)} className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600">Service Type *</label>
                <input
                  value={renewalForm.service_type}
                  onChange={(e) => setRenewalForm({ ...renewalForm, service_type: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="e.g. GST Filing, ITR, Audit"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Financial Year *</label>
                <input
                  value={renewalForm.financial_year}
                  onChange={(e) => setRenewalForm({ ...renewalForm, financial_year: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="e.g. 2025-26"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Renewal Date</label>
                <input
                  type="date"
                  value={renewalForm.renewal_date}
                  onChange={(e) => setRenewalForm({ ...renewalForm, renewal_date: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Value (₹)</label>
                <input
                  type="number"
                  value={renewalForm.value_paise}
                  onChange={(e) => setRenewalForm({ ...renewalForm, value_paise: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="e.g. 15000"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setRenewalModal(false)} className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50">Cancel</button>
              <button
                onClick={handleSaveRenewal}
                disabled={savingRenewal || !renewalForm.service_type || !renewalForm.financial_year}
                className="flex-1 text-sm bg-[#182350] text-white py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
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

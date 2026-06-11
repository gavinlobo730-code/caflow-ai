"use client";

/**
 * Scheduled Report Delivery — PracticeSync AI
 * Firm staff can schedule automatic report emails to clients.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft, Plus, Trash2, Mail, Calendar, ToggleLeft, ToggleRight,
  AlertCircle, Loader2, X,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ─── Types ────────────────────────────────────────────────────────────────────

type ReportType = "pl" | "balance_sheet" | "gst_summary" | "tds_summary" | "payroll_summary";
type Frequency = "monthly" | "quarterly" | "yearly";

interface ScheduledReport {
  id: string;
  client_id: string | null;
  report_type: ReportType;
  frequency: Frequency;
  recipients: string[];
  day_of_month: number;
  is_active: boolean;
  last_sent_at: string | null;
  created_at: string;
  // joined
  client_name?: string | null;
}

interface Client {
  id: string;
  name: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  pl: "P&L Statement",
  balance_sheet: "Balance Sheet",
  gst_summary: "GST Summary",
  tds_summary: "TDS Summary",
  payroll_summary: "Payroll Summary",
};

const FREQUENCY_LABELS: Record<Frequency, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className={`fixed bottom-4 right-4 z-50 text-white text-sm px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-3 ${
      type === "success" ? "bg-green-700" : "bg-red-700"
    }`}>
      <span>{message}</span>
      <button onClick={onClose} className="text-white/70 hover:text-white">×</button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ScheduledReportsPage() {
  const [schedules, setSchedules] = useState<ScheduledReport[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  // Modal form state
  const [form, setForm] = useState({
    report_type: "pl" as ReportType,
    client_id: "",
    frequency: "monthly" as Frequency,
    recipients: "",
    day_of_month: "5",
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();

      const [{ data: srRaw }, { data: cl }] = await Promise.all([
        supabase
          .from("scheduled_reports")
          .select("id, client_id, report_type, frequency, recipients, day_of_month, is_active, last_sent_at, created_at")
          .eq("firm_id", firmId)
          .order("created_at", { ascending: false }),
        supabase
          .from("clients")
          .select("id, name")
          .eq("firm_id", firmId)
          .order("name"),
      ]);

      // Build client lookup
      const clientMap: Record<string, string> = {};
      for (const c of (cl ?? [])) { clientMap[c.id] = c.name; }

      const mapped = (srRaw ?? []).map((r: Record<string, unknown>) => ({
        id: r.id as string,
        client_id: (r.client_id as string | null) ?? null,
        report_type: r.report_type as ReportType,
        frequency: r.frequency as Frequency,
        recipients: r.recipients as string[],
        day_of_month: r.day_of_month as number,
        is_active: r.is_active as boolean,
        last_sent_at: (r.last_sent_at as string | null) ?? null,
        created_at: r.created_at as string,
        client_name: r.client_id ? (clientMap[r.client_id as string] ?? null) : null,
      }));

      setSchedules(mapped);
      setClients(cl ?? []);
    } catch (e) {
      console.error("loadData:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  async function handleCreate() {
    setFormError(null);
    const emails = form.recipients.split(",").map(e => e.trim()).filter(Boolean);
    if (emails.length === 0) {
      setFormError("At least one recipient email is required");
      return;
    }
    const day = parseInt(form.day_of_month, 10);
    if (isNaN(day) || day < 1 || day > 28) {
      setFormError("Day of month must be 1–28");
      return;
    }
    setSaving(true);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { error } = await supabase.from("scheduled_reports").insert({
        firm_id: firmId,
        client_id: form.client_id || null,
        report_type: form.report_type,
        frequency: form.frequency,
        recipients: emails,
        day_of_month: day,
        is_active: true,
      });
      if (error) throw new Error(error.message);
      setShowModal(false);
      setForm({ report_type: "pl", client_id: "", frequency: "monthly", recipients: "", day_of_month: "5" });
      setToast({ message: "Schedule created", type: "success" });
      await loadData();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(id: string, current: boolean) {
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase
        .from("scheduled_reports")
        .update({ is_active: !current })
        .eq("id", id);
      if (error) throw new Error(error.message);
      setSchedules(prev => prev.map(s => s.id === id ? { ...s, is_active: !current } : s));
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Update failed", type: "error" });
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this schedule?")) return;
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase.from("scheduled_reports").delete().eq("id", id);
      if (error) throw new Error(error.message);
      setSchedules(prev => prev.filter(s => s.id !== id));
      setToast({ message: "Schedule deleted", type: "success" });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Delete failed", type: "error" });
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/settings" className="text-white/30 hover:text-white/55">
            <ArrowLeft size={16} />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-white/85">Scheduled Reports</h1>
            <p className="text-sm text-white/30 mt-0.5">Automatically email reports to clients on a schedule</p>
          </div>
        </div>
        <button
          onClick={() => { setShowModal(true); setFormError(null); }}
          className="flex items-center gap-1.5 text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
        >
          <Plus size={14} /> New Schedule
        </button>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-100 rounded-xl px-4 py-3">
        <AlertCircle size={15} className="text-blue-500 mt-0.5 shrink-0" />
        <p className="text-xs text-blue-700 leading-relaxed">
          Reports are generated and emailed automatically on the scheduled day. Ensure client email is set.
        </p>
      </div>

      {/* List */}
      {loading ? (
        <div className="text-center py-12 flex items-center justify-center gap-2 text-white/30">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading schedules…</span>
        </div>
      ) : schedules.length === 0 ? (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] px-5 py-14 text-center">
          <Calendar className="w-8 h-8 text-gray-200 mx-auto mb-2" />
          <p className="text-sm text-white/30">No schedules yet</p>
          <p className="text-xs text-white/20 mt-1">Create your first scheduled report to get started</p>
        </div>
      ) : (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.05] text-xs text-white/30">
                <th className="px-5 py-3 text-left font-semibold">Report Type</th>
                <th className="px-4 py-3 text-left font-semibold">Client</th>
                <th className="px-4 py-3 text-left font-semibold">Frequency</th>
                <th className="px-4 py-3 text-left font-semibold">Day</th>
                <th className="px-4 py-3 text-left font-semibold">Recipients</th>
                <th className="px-4 py-3 text-left font-semibold">Status</th>
                <th className="px-5 py-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {schedules.map(s => (
                <tr key={s.id} className="hover:bg-[#0e1017]">
                  <td className="px-5 py-3 font-medium text-white/85 text-xs">
                    {REPORT_TYPE_LABELS[s.report_type]}
                  </td>
                  <td className="px-4 py-3 text-xs text-white/40">
                    {s.client_name ?? <span className="text-white/20 italic">All clients</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-white/55">
                    {FREQUENCY_LABELS[s.frequency]}
                  </td>
                  <td className="px-4 py-3 text-xs text-white/55">{s.day_of_month}</td>
                  <td className="px-4 py-3 text-xs text-white/40 max-w-[160px]">
                    <div className="flex items-center gap-1 truncate">
                      <Mail size={11} className="shrink-0 text-white/20" />
                      <span className="truncate">{s.recipients.join(", ")}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggle(s.id, s.is_active)}
                      className={`flex items-center gap-1 text-xs font-medium ${
                        s.is_active ? "text-green-600" : "text-white/30"
                      }`}
                    >
                      {s.is_active
                        ? <ToggleRight size={16} className="text-green-500" />
                        : <ToggleLeft size={16} />
                      }
                      {s.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>
                  <td className="px-5 py-3">
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="flex items-center gap-1 text-xs text-red-500 hover:underline"
                    >
                      <Trash2 size={12} /> Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* New Schedule Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-[#131620] rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white/85">New Schedule</h3>
              <button onClick={() => setShowModal(false)} className="text-white/30 hover:text-white/55">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Report Type *</label>
                <select
                  value={form.report_type}
                  onChange={e => setForm(f => ({ ...f, report_type: e.target.value as ReportType }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {(Object.entries(REPORT_TYPE_LABELS) as [ReportType, string][]).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Client (optional — leave blank for all)</label>
                <select
                  value={form.client_id}
                  onChange={e => setForm(f => ({ ...f, client_id: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All clients</option>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Frequency *</label>
                <select
                  value={form.frequency}
                  onChange={e => setForm(f => ({ ...f, frequency: e.target.value as Frequency }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {(Object.entries(FREQUENCY_LABELS) as [Frequency, string][]).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Recipients (comma-separated emails) *</label>
                <input
                  type="text"
                  value={form.recipients}
                  onChange={e => setForm(f => ({ ...f, recipients: e.target.value }))}
                  placeholder="e.g. client@example.com, partner@firm.com"
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Day of month (1–28) *</label>
                <input
                  type="number"
                  min={1}
                  max={28}
                  value={form.day_of_month}
                  onChange={e => setForm(f => ({ ...f, day_of_month: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {formError && (
                <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{formError}</p>
              )}
            </div>

            <div className="flex gap-3 justify-end pt-1">
              <button
                onClick={() => setShowModal(false)}
                className="text-xs px-4 py-2 border border-white/[0.07] rounded-lg hover:bg-[#0e1017]"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={saving}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 flex items-center gap-1.5"
              >
                {saving && <Loader2 size={12} className="animate-spin" />}
                {saving ? "Creating…" : "Create Schedule"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

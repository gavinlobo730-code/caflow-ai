"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Play, Pause, Trash2, AlertCircle, CheckCircle2, Download } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { api } from "@/lib/api";
import { todayLocalISO } from "@/lib/dateMath";
import type { Account, Client } from "@/lib/types";

// ─── Types ─────────────────────────────────────────────────────────────────

type Frequency = "Monthly" | "Quarterly" | "Yearly";
type RecurringStatus = "Active" | "Paused";

interface RecurringTemplate {
  id: string;
  client_id: string;            // journal_entries.client_id is a required FK
  name: string;
  frequency: Frequency;
  day_of_month: number;        // 1–28
  debit_account_id: string;
  credit_account_id: string;
  amount_paise: number;        // integer paise — no floating point
  narration: string;
  start_date: string;          // YYYY-MM-DD
  end_date: string;            // YYYY-MM-DD or ""
  status: RecurringStatus;
  last_posted_date: string;    // YYYY-MM-DD or ""
}

// ─── Helpers ───────────────────────────────────────────────────────────────

const LS_KEY = "practicesync_recurring_templates";

function loadTemplates(): RecurringTemplate[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) ?? "[]") as RecurringTemplate[];
  } catch {
    return [];
  }
}

function saveTemplates(tpls: RecurringTemplate[]): void {
  localStorage.setItem(LS_KEY, JSON.stringify(tpls));
}

function todayISO(): string {
  return todayLocalISO();
}

/** Compute next due date for a template from today's perspective */
function nextDueDate(tpl: RecurringTemplate): string {
  const today = todayISO();
  const last = tpl.last_posted_date || tpl.start_date;

  const d = new Date(last);
  switch (tpl.frequency) {
    case "Monthly":
      d.setMonth(d.getMonth() + 1);
      break;
    case "Quarterly":
      d.setMonth(d.getMonth() + 3);
      break;
    case "Yearly":
      d.setFullYear(d.getFullYear() + 1);
      break;
  }
  d.setDate(Math.min(tpl.day_of_month, 28));
  const iso = d.toISOString().slice(0, 10);
  // If we haven't posted yet and start_date is today or past, it's due now
  if (!tpl.last_posted_date && tpl.start_date <= today) return tpl.start_date;
  return iso;
}

function isDueToday(tpl: RecurringTemplate): boolean {
  if (tpl.status !== "Active") return false;
  const due = nextDueDate(tpl);
  return due <= todayISO();
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

// ─── Empty form ────────────────────────────────────────────────────────────

interface TemplateForm {
  client_id: string;
  name: string;
  frequency: Frequency;
  day_of_month: number;
  debit_account_id: string;
  credit_account_id: string;
  amount_rupees: string;   // user types rupees, we convert to paise on save
  narration: string;
  start_date: string;
  end_date: string;
}

const EMPTY_FORM: TemplateForm = {
  client_id: "",
  name: "",
  frequency: "Monthly",
  day_of_month: 1,
  debit_account_id: "",
  credit_account_id: "",
  amount_rupees: "",
  narration: "",
  start_date: todayISO(),
  end_date: "",
};

// ─── Component ─────────────────────────────────────────────────────────────

export default function RecurringPage() {
  const [templates, setTemplates] = useState<RecurringTemplate[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<TemplateForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [postingId, setPostingId] = useState<string | null>(null);
  const [postSuccess, setPostSuccess] = useState<string | null>(null);

  // Load accounts + clients from Supabase. A recurring template posts a real
  // journal_entries row, which requires a client_id (NOT NULL FK) — so every
  // template must be associated with the client it belongs to.
  const loadAccounts = useCallback(async () => {
    setLoadingAccounts(true);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const { data } = await sb
        // chart_of_accounts — there is no "accounts" table and never was.
        .from("chart_of_accounts")
        .select("*")
        .eq("firm_id", fid)
        .eq("is_active", true)
        .order("account_name");
      setAccounts((data ?? []) as Account[]);
    } catch {
      // silently degrade — accounts just won't populate dropdowns
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  const loadClients = useCallback(async () => {
    try {
      setClients(await getClients());
    } catch {
      // silently degrade — client dropdown just won't populate
    }
  }, []);

  useEffect(() => {
    setTemplates(loadTemplates());
    loadAccounts();
    loadClients();
  }, [loadAccounts, loadClients]);

  // ── Modal open/close ───────────────────────────────────────────────────

  function openModal() {
    setForm({ ...EMPTY_FORM, start_date: todayISO() });
    setFormError(null);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  // ── Save template ──────────────────────────────────────────────────────

  function handleSave() {
    if (!form.client_id) { setFormError("Client is required"); return; }
    if (!form.name.trim()) { setFormError("Name is required"); return; }
    if (!form.debit_account_id) { setFormError("Debit account is required"); return; }
    if (!form.credit_account_id) { setFormError("Credit account is required"); return; }
    if (form.debit_account_id === form.credit_account_id) { setFormError("Debit and credit accounts must differ"); return; }
    const rupees = parseFloat(form.amount_rupees);
    if (isNaN(rupees) || rupees <= 0) { setFormError("Enter a valid amount"); return; }
    if (!form.start_date) { setFormError("Start date is required"); return; }

    // All money stored as integer paise — no floating point
    const amount_paise = Math.round(rupees * 100);

    const newTpl: RecurringTemplate = {
      id: crypto.randomUUID(),
      client_id: form.client_id,
      name: form.name.trim(),
      frequency: form.frequency,
      day_of_month: form.day_of_month,
      debit_account_id: form.debit_account_id,
      credit_account_id: form.credit_account_id,
      amount_paise,
      narration: form.narration.trim(),
      start_date: form.start_date,
      end_date: form.end_date,
      status: "Active",
      last_posted_date: "",
    };

    const updated = [...templates, newTpl];
    setTemplates(updated);
    saveTemplates(updated);
    closeModal();
  }

  // ── Toggle status ──────────────────────────────────────────────────────

  function toggleStatus(id: string) {
    const updated = templates.map(t =>
      t.id === id ? { ...t, status: t.status === "Active" ? "Paused" as RecurringStatus : "Active" as RecurringStatus } : t
    );
    setTemplates(updated);
    saveTemplates(updated);
  }

  // ── Delete template ────────────────────────────────────────────────────

  function deleteTemplate(id: string) {
    if (!confirm("Delete this recurring template?")) return;
    const updated = templates.filter(t => t.id !== id);
    setTemplates(updated);
    saveTemplates(updated);
  }

  // ── Post Now ───────────────────────────────────────────────────────────

  async function postNow(tpl: RecurringTemplate) {
    if (!firmId) return;
    setPostingId(tpl.id);
    setPostSuccess(null);
    const today = todayISO();
    try {
      // Posts through the backend's single posting kernel (manual_journal_service
      // → phase2_journal_service._create_journal — the same atomic-transaction
      // engine every other journal-posting flow uses), instead of writing
      // journal_entries/journal_entry_lines directly: journal_entry_lines is a
      // read-only JOIN view (not a real, writable table), so a direct insert
      // here always failed, and total_debit_paise/total_credit_paise are
      // computed response fields, not real journal_entries columns.
      await api.accounting.createJournalEntry({
        client_id: tpl.client_id,
        entry_date: today,
        reference_no: `REC-${tpl.id.slice(0, 8).toUpperCase()}`,
        narration: tpl.narration || tpl.name,
        entry_type: "Journal",
        status: "posted",
        lines: [
          { account_id: tpl.debit_account_id, debit_paise: tpl.amount_paise, credit_paise: 0, narration: tpl.narration || tpl.name },
          { account_id: tpl.credit_account_id, debit_paise: 0, credit_paise: tpl.amount_paise, narration: tpl.narration || tpl.name },
        ],
      });

      // Update last posted date
      const updated = templates.map(t =>
        t.id === tpl.id ? { ...t, last_posted_date: today } : t
      );
      setTemplates(updated);
      saveTemplates(updated);
      setPostSuccess(`"${tpl.name}" posted to Journal Entries for ${today}`);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to post");
    } finally {
      setPostingId(null);
    }
  }

  // ── Computed ───────────────────────────────────────────────────────────

  const dueTemplates = templates.filter(isDueToday);

  function accountName(id: string): string {
    return accounts.find(a => a.id === id)?.account_name ?? id;
  }

  const exportColumns: { key: string; header: string; accessor: (row: RecurringTemplate) => unknown }[] = [
    { key: "name", header: "Name", accessor: (tpl) => tpl.name },
    { key: "frequency", header: "Frequency", accessor: (tpl) => tpl.frequency },
    { key: "next_due", header: "Next Due", accessor: (tpl) => nextDueDate(tpl) },
    { key: "debit_account", header: "Debit Account", accessor: (tpl) => accountName(tpl.debit_account_id) },
    { key: "credit_account", header: "Credit Account", accessor: (tpl) => accountName(tpl.credit_account_id) },
    { key: "amount", header: "Amount (₹)", accessor: (tpl) => (tpl.amount_paise / 100).toFixed(2) },
    { key: "narration", header: "Narration", accessor: (tpl) => tpl.narration },
    { key: "start_date", header: "Start Date", accessor: (tpl) => tpl.start_date },
    { key: "end_date", header: "End Date", accessor: (tpl) => tpl.end_date },
    { key: "status", header: "Status", accessor: (tpl) => tpl.status },
  ];

  const freqBadge: Record<Frequency, string> = {
    Monthly: "bg-blue-100 text-blue-700",
    Quarterly: "bg-purple-100 text-purple-700",
    Yearly: "bg-orange-100 text-orange-700",
  };

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Recurring Transactions</h1>
          <p className="text-sm text-[#64748B] mt-0.5">{templates.filter(t => t.status === "Active").length} active templates</p>
        </div>
        <button
          onClick={() => downloadCsv("recurring-templates.csv", toCsv(templates, exportColumns))}
          disabled={templates.length === 0}
          className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC] disabled:opacity-50"
        >
          <Download size={13} /> Export
        </button>
        <button
          onClick={openModal}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          <Plus size={13} /> New Template
        </button>
      </div>

      {/* Due Today Banner */}
      {dueTemplates.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-start gap-3">
          <AlertCircle size={16} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-amber-800">
              {dueTemplates.length} recurring {dueTemplates.length === 1 ? "entry" : "entries"} due today or overdue
            </p>
            <p className="text-xs text-amber-700 mt-0.5">
              {dueTemplates.map(t => t.name).join(", ")}
            </p>
          </div>
        </div>
      )}

      {/* Post success */}
      {postSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 flex items-center gap-2">
          <CheckCircle2 size={14} className="text-green-600 shrink-0" />
          <p className="text-sm text-green-800">{postSuccess}</p>
          <button onClick={() => setPostSuccess(null)} className="ml-auto text-xs text-green-600 hover:underline">Dismiss</button>
        </div>
      )}

      {/* Templates table */}
      {templates.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-sm text-[#64748B] mb-3">No recurring templates yet</p>
          <button onClick={openModal} className="text-sm bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700">
            Add First Template
          </button>
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#94A3B8] border-b border-[#F1F5F9]">
                  <th className="px-5 py-2.5 text-left font-medium">Name</th>
                  <th className="px-3 py-2.5 text-left font-medium">Frequency</th>
                  <th className="px-3 py-2.5 text-left font-medium">Next Due</th>
                  <th className="px-3 py-2.5 text-left font-medium">Debit</th>
                  <th className="px-3 py-2.5 text-left font-medium">Credit</th>
                  <th className="px-3 py-2.5 text-right font-medium">Amount</th>
                  <th className="px-3 py-2.5 text-left font-medium">Status</th>
                  <th className="px-5 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {templates.map(tpl => {
                  const due = nextDueDate(tpl);
                  const overdue = tpl.status === "Active" && due <= todayISO();
                  return (
                    <tr key={tpl.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 font-medium text-[#0F172A] max-w-[160px] truncate">{tpl.name}</td>
                      <td className="px-3 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${freqBadge[tpl.frequency]}`}>
                          {tpl.frequency}
                        </span>
                      </td>
                      <td className={`px-3 py-3 text-xs tabular-nums ${overdue ? "text-red-600 font-semibold" : "text-[#475569]"}`}>
                        {due}
                        {overdue && " (overdue)"}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#64748B] max-w-[120px] truncate">{accountName(tpl.debit_account_id)}</td>
                      <td className="px-3 py-3 text-xs text-[#64748B] max-w-[120px] truncate">{accountName(tpl.credit_account_id)}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-[#0F172A] font-medium">
                        {formatPaise(tpl.amount_paise)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={tpl.status === "Active" ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}>
                          {tpl.status}
                        </Badge>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => postNow(tpl)}
                            disabled={postingId === tpl.id || tpl.status === "Paused"}
                            className="flex items-center gap-1 text-xs bg-blue-50 text-blue-700 px-2 py-1 rounded hover:bg-blue-100 disabled:opacity-40"
                            title="Post Now"
                          >
                            <Play size={11} />
                            {postingId === tpl.id ? "Posting…" : "Post Now"}
                          </button>
                          <button
                            onClick={() => toggleStatus(tpl.id)}
                            className="p-1.5 rounded hover:bg-[#F1F5F9] text-[#94A3B8] hover:text-[#334155]"
                            title={tpl.status === "Active" ? "Pause" : "Resume"}
                          >
                            <Pause size={12} />
                          </button>
                          <button
                            onClick={() => deleteTemplate(tpl.id)}
                            className="p-1.5 rounded hover:bg-red-50 text-[#94A3B8] hover:text-red-600"
                            title="Delete"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Add Template Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-sm font-semibold text-[#0F172A] mb-4">New Recurring Template</h2>
            <div className="space-y-3">

              {/* Client */}
              <div>
                <label className="text-xs text-[#64748B] font-medium">Client *</label>
                <div className="mt-1">
                  <ClientLookup
                    clients={clients}
                    value={form.client_id}
                    onChange={(id) => setForm({ ...form, client_id: id })}
                    ariaLabel="Client"
                    placeholder="Select client…"
                  />
                </div>
              </div>

              {/* Name */}
              <div>
                <label className="text-xs text-[#64748B] font-medium">Name *</label>
                <input
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder='e.g. "Monthly Office Rent"'
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Frequency + Day */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Frequency *</label>
                  <select
                    value={form.frequency}
                    onChange={e => setForm({ ...form, frequency: e.target.value as Frequency })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option>Monthly</option>
                    <option>Quarterly</option>
                    <option>Yearly</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Day of Month (1–28) *</label>
                  <input
                    type="number"
                    min={1}
                    max={28}
                    value={form.day_of_month}
                    onChange={e => setForm({ ...form, day_of_month: Math.min(28, Math.max(1, parseInt(e.target.value) || 1)) })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              {/* Accounts */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Debit Account *</label>
                  <select
                    value={form.debit_account_id}
                    onChange={e => setForm({ ...form, debit_account_id: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={loadingAccounts}
                  >
                    <option value="">— Select account —</option>
                    {accounts.map(a => (
                      <option key={a.id} value={a.id}>{a.account_code} · {a.account_name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Credit Account *</label>
                  <select
                    value={form.credit_account_id}
                    onChange={e => setForm({ ...form, credit_account_id: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={loadingAccounts}
                  >
                    <option value="">— Select account —</option>
                    {accounts.map(a => (
                      <option key={a.id} value={a.id}>{a.account_code} · {a.account_name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Amount */}
              <div>
                <label className="text-xs text-[#64748B] font-medium">Amount (₹) *</label>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={form.amount_rupees}
                  onChange={e => setForm({ ...form, amount_rupees: e.target.value })}
                  placeholder="e.g. 25000"
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-[#94A3B8] mt-0.5">Stored as integer paise internally</p>
              </div>

              {/* Narration */}
              <div>
                <label className="text-xs text-[#64748B] font-medium">Narration</label>
                <input
                  value={form.narration}
                  onChange={e => setForm({ ...form, narration: e.target.value })}
                  placeholder="e.g. Office rent for the month"
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Dates */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Start Date *</label>
                  <input
                    type="date"
                    value={form.start_date}
                    onChange={e => setForm({ ...form, start_date: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">End Date (optional)</label>
                  <input
                    type="date"
                    value={form.end_date}
                    onChange={e => setForm({ ...form, end_date: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

            </div>

            {formError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md">{formError}</p>
            )}

            <div className="flex gap-2 mt-5">
              <button
                onClick={closeModal}
                className="flex-1 text-sm text-[#475569] border border-[#E2E8F0] py-2 rounded-md hover:bg-[#F8FAFC]"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="flex-1 text-sm bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700"
              >
                Add Template
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

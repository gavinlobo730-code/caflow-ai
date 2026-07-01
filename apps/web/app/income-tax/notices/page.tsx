"use client";

/**
 * IT Notices Tracker
 * IT Act Sections 143(1), 143(2), 148, 271, 276 — Income Tax Notices
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * Never transmit notice responses to government portals without explicit CA confirmation.
 *
 * All amounts in integer paise arithmetic.
 */

import { useState, useEffect, useCallback, useRef, ChangeEvent } from "react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { Combobox } from "@/components/ui/combobox";
import Link from "next/link";
import { ChevronLeft, Plus, X, Upload, Download, Trash2, FileText, AlertTriangle, CheckCircle, Clock, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

type NoticeStatus = "pending" | "responded" | "closed" | "appeal";

interface ITNotice {
  id: string;
  firm_id: string;
  client_id: string;
  notice_type: string;
  assessment_year: string;
  date_received: string;
  amount_demanded_paise: number;
  response_due_date: string | null;
  status: NoticeStatus;
  notice_storage_path: string | null;
  response_storage_path: string | null;
  notes: string | null;
  created_at: string;
}

const NOTICE_TYPES = ["143(1)", "143(2)", "144", "148", "148A", "156", "245", "271", "271A", "272A", "276"] as const;
const STATUS_OPTIONS: NoticeStatus[] = ["pending", "responded", "closed", "appeal"];
const ASSESSMENT_YEARS = ["2026-27", "2025-26", "2024-25", "2023-24", "2022-23", "2021-22"];
const STORAGE_BUCKET = "Documents";

function statusBadge(status: NoticeStatus) {
  switch (status) {
    case "pending": return { cls: "text-red-700 bg-red-50", icon: AlertTriangle, label: "Pending" };
    case "responded": return { cls: "text-amber-700 bg-amber-50", icon: Clock, label: "Responded" };
    case "closed": return { cls: "text-green-700 bg-green-50", icon: CheckCircle, label: "Closed" };
    case "appeal": return { cls: "text-blue-700 bg-blue-50", icon: AlertTriangle, label: "In Appeal" };
  }
}

const TODAY = new Date().toISOString().slice(0, 10);
function isOverdue(notice: ITNotice) {
  return notice.status === "pending" && notice.response_due_date && notice.response_due_date < TODAY;
}

// ─── Add Notice Modal ─────────────────────────────────────────────────────────

interface AddFormState {
  clientId: string;
  noticeType: string;
  assessmentYear: string;
  dateReceived: string;
  responseDueDate: string;
  amountDemandedRs: string;
  status: NoticeStatus;
  notes: string;
}

const BLANK: AddFormState = {
  clientId: "",
  noticeType: "143(1)",
  assessmentYear: "2025-26",
  dateReceived: TODAY,
  responseDueDate: "",
  amountDemandedRs: "",
  status: "pending",
  notes: "",
};

function AddModal({ clients, onClose, onAdded }: {
  clients: Client[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [form, setForm] = useState<AddFormState>({ ...BLANK, clientId: clients[0]?.id ?? "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function upd(patch: Partial<AddFormState>) { setForm(f => ({ ...f, ...patch })); }
  const inputCls = "w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500";
  const lbl = "text-xs font-medium text-[#334155] block mb-1";

  async function handleSave() {
    if (!form.clientId || !form.dateReceived) { setError("Client and date received are required"); return; }
    // All money in integer paise — no floating point
    const amountPaise = form.amountDemandedRs ? Math.round(parseFloat(form.amountDemandedRs) * 100) : 0;
    setSaving(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { error: err } = await sb.from("it_notices").insert({
        firm_id: firmId,
        client_id: form.clientId,
        notice_type: form.noticeType,
        assessment_year: form.assessmentYear,
        date_received: form.dateReceived,
        amount_demanded_paise: amountPaise,
        response_due_date: form.responseDueDate || null,
        status: form.status,
        notes: form.notes || null,
      });
      if (err) throw new Error(err.message);
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add IT Notice</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-3">
          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
          <div>
            <label className={lbl}>Client *</label>
            <ClientLookup
              clients={clients}
              value={form.clientId}
              onChange={id => upd({ clientId: id })}
              placeholder="Select client…"
              ariaLabel="Client"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Notice Type</label>
              <Combobox<string>
                options={[...NOTICE_TYPES]}
                value={form.noticeType || null}
                onChange={v => upd({ noticeType: (v as string | null) ?? "" })}
                getOptionId={t => t}
                getLabel={t => `Section ${t}`}
                getSearchFields={t => [t]}
                placeholder="Select notice type…"
                searchPlaceholder="Search section…"
                ariaLabel="Notice type"
              />
            </div>
            <div>
              <label className={lbl}>Assessment Year</label>
              <select value={form.assessmentYear} onChange={e => upd({ assessmentYear: e.target.value })} className={inputCls}>
                {ASSESSMENT_YEARS.map(ay => <option key={ay} value={ay}>{ay}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Date Received *</label>
              <input type="date" value={form.dateReceived} onChange={e => upd({ dateReceived: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className={lbl}>Response Due Date</label>
              <input type="date" value={form.responseDueDate} onChange={e => upd({ responseDueDate: e.target.value })} className={inputCls} />
            </div>
          </div>
          <div>
            <label className={lbl}>Amount Demanded (₹)</label>
            <input type="number" min="0" step="0.01" value={form.amountDemandedRs} onChange={e => upd({ amountDemandedRs: e.target.value })} className={inputCls} placeholder="0.00" />
          </div>
          <div>
            <label className={lbl}>Status</label>
            <select value={form.status} onChange={e => upd({ status: e.target.value as NoticeStatus })} className={inputCls}>
              {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label className={lbl}>Notes</label>
            <textarea rows={2} value={form.notes} onChange={e => upd({ notes: e.target.value })}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
              placeholder="Additional details…" />
          </div>
        </div>
        <div className="sticky bottom-0 bg-white px-6 py-4 border-t border-[#F1F5F9] flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-60">
            {saving ? "Saving…" : "Add Notice"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Upload Document Button ───────────────────────────────────────────────────

function UploadDocButton({ noticeId, firmId, clientId, field, label, currentPath, onUploaded }: {
  noticeId: string;
  firmId: string;
  clientId: string;
  field: "notice_storage_path" | "response_storage_path";
  label: string;
  currentPath: string | null;
  onUploaded: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const sb = getSupabaseClient();

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const safeName = file.name.replace(/[^a-zA-Z0-9._\-]/g, "_");
      // Storage path: {firm_id}/{client_id}/notices/{notice_id}/{filename}
      const path = `${firmId}/${clientId}/notices/${noticeId}/${safeName}`;
      const { error: upErr } = await sb.storage.from(STORAGE_BUCKET).upload(path, file, { upsert: true });
      if (upErr) throw new Error(upErr.message);
      const { error: dbErr } = await sb.from("it_notices").update({ [field]: path }).eq("id", noticeId);
      if (dbErr) throw new Error(dbErr.message);
      onUploaded();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleDownload() {
    if (!currentPath) return;
    const { data, error } = await sb.storage.from(STORAGE_BUCKET).createSignedUrl(currentPath, 60);
    if (error) { alert(error.message); return; }
    window.open(data.signedUrl, "_blank");
  }

  return (
    <div className="flex items-center gap-1">
      {currentPath ? (
        <button onClick={handleDownload} className="flex items-center gap-1 text-xs text-blue-600 hover:underline">
          <Download size={11} /> {label}
        </button>
      ) : (
        <>
          <input ref={fileRef} type="file" className="hidden" onChange={handleFile} accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" />
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            className="flex items-center gap-1 text-xs text-[#64748B] hover:text-blue-600 disabled:opacity-40">
            {uploading ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
            {uploading ? "Uploading…" : label}
          </button>
        </>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ITNoticesPage() {
  const [notices, setNotices] = useState<ITNotice[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [firmId, setFirmIdState] = useState("");
  const [clientFilter, setClientFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<NoticeStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cls, fid] = await Promise.all([getClients(), getFirmId()]);
      setClients(cls);
      setFirmIdState(fid);
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("it_notices")
        .select("*")
        .eq("firm_id", fid)
        .order("date_received", { ascending: false });
      if (err) throw new Error(err.message);
      setNotices((data ?? []) as ITNotice[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  async function updateStatus(id: string, status: NoticeStatus) {
    const sb = getSupabaseClient();
    await sb.from("it_notices").update({ status }).eq("id", id);
    loadData();
  }

  async function deleteNotice(id: string) {
    if (!confirm("Delete this notice?")) return;
    const sb = getSupabaseClient();
    await sb.from("it_notices").delete().eq("id", id);
    loadData();
  }

  const clientName = (id: string) => clients.find(c => c.id === id)?.client_name ?? id;

  const filtered = notices.filter(n => {
    if (clientFilter !== "all" && n.client_id !== clientFilter) return false;
    if (statusFilter !== "all" && n.status !== statusFilter) return false;
    return true;
  });

  const urgentCount = notices.filter(n => isOverdue(n)).length;
  const totalDemand = filtered.reduce((s, n) => s + n.amount_demanded_paise, 0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">IT Notices Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Sections 143(1), 148, 271 — Income Tax notices with document upload</p>
        </div>
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus size={14} className="mr-1" /> Add Notice
        </Button>
      </div>

      {urgentCount > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-3 flex items-center gap-3">
          <AlertTriangle size={16} className="text-red-600 shrink-0" />
          <p className="text-sm text-red-800 font-medium">{urgentCount} notice{urgentCount !== 1 ? "s" : ""} overdue — response date has passed</p>
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total Notices", value: notices.length },
          { label: "Pending", value: notices.filter(n => n.status === "pending").length },
          { label: "Responded", value: notices.filter(n => n.status === "responded").length },
          { label: "Closed / Appeal", value: notices.filter(n => n.status === "closed" || n.status === "appeal").length },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className="text-2xl font-bold text-[#0F172A]">{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select value={clientFilter} onChange={e => setClientFilter(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          <option value="all">All Clients</option>
          {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as NoticeStatus | "all")}
          className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          <option value="all">All Statuses</option>
          {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
        </select>
        {filtered.length > 0 && (
          <div className="ml-auto flex items-center text-sm text-[#475569]">
            Total demand: <span className="font-semibold ml-1 text-red-600">{formatPaise(totalDemand)}</span>
          </div>
        )}
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}

      {/* Table */}
      <Card>
        {loading ? (
          <div className="p-8 text-center text-[#94A3B8] text-sm animate-pulse">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-[#94A3B8] text-sm">
            <FileText className="w-10 h-10 text-gray-200 mx-auto mb-3" />
            {notices.length === 0 ? "No notices tracked yet. Add your first notice." : "No notices match filters."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[1000px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                  <th className="px-5 py-3 text-left">Client</th>
                  <th className="px-3 py-3 text-left">Notice Type</th>
                  <th className="px-3 py-3 text-left">AY</th>
                  <th className="px-3 py-3 text-left">Date Received</th>
                  <th className="px-3 py-3 text-left">Due Date</th>
                  <th className="px-3 py-3 text-right">Amount Demanded</th>
                  <th className="px-3 py-3 text-left">Documents</th>
                  <th className="px-3 py-3 text-left">Status</th>
                  <th className="px-5 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {filtered.map(n => {
                  const badge = statusBadge(n.status);
                  const Icon = badge.icon;
                  const overdue = isOverdue(n);
                  return (
                    <tr key={n.id} className={`hover:bg-[#F8FAFC] ${overdue ? "bg-red-50/40" : ""}`}>
                      <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">{clientName(n.client_id)}</td>
                      <td className="px-3 py-3 text-sm">Sec. {n.notice_type}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{n.assessment_year}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{n.date_received}</td>
                      <td className={`px-3 py-3 text-xs ${overdue ? "text-red-600 font-semibold" : "text-[#475569]"}`}>
                        {n.response_due_date ?? "—"}
                        {overdue && " ⚠"}
                      </td>
                      <td className="px-3 py-3 text-sm tabular-nums text-right font-medium text-red-700">
                        {n.amount_demanded_paise > 0 ? formatPaise(n.amount_demanded_paise) : "—"}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-col gap-1">
                          <UploadDocButton
                            noticeId={n.id} firmId={firmId} clientId={n.client_id}
                            field="notice_storage_path" label="Notice doc"
                            currentPath={n.notice_storage_path} onUploaded={loadData}
                          />
                          <UploadDocButton
                            noticeId={n.id} firmId={firmId} clientId={n.client_id}
                            field="response_storage_path" label="Response doc"
                            currentPath={n.response_storage_path} onUploaded={loadData}
                          />
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${badge.cls}`}>
                          <Icon size={11} /> {badge.label}
                        </span>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-1.5">
                          {n.status === "pending" && (
                            <button onClick={() => updateStatus(n.id, "responded")}
                              className="text-xs px-2 py-1 bg-amber-50 text-amber-700 rounded hover:bg-amber-100">
                              Responded
                            </button>
                          )}
                          {n.status === "responded" && (
                            <button onClick={() => updateStatus(n.id, "closed")}
                              className="text-xs px-2 py-1 bg-green-50 text-green-700 rounded hover:bg-green-100">
                              Close
                            </button>
                          )}
                          {(n.status === "pending" || n.status === "responded") && (
                            <button onClick={() => updateStatus(n.id, "appeal")}
                              className="text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded hover:bg-blue-100">
                              Appeal
                            </button>
                          )}
                          <button onClick={() => deleteNotice(n.id)}
                            className="p-1 text-[#CBD5E1] hover:text-red-500">
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showAdd && clients.length > 0 && (
        <AddModal clients={clients} onClose={() => setShowAdd(false)} onAdded={loadData} />
      )}
    </div>
  );
}

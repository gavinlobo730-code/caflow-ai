"use client";

import { useState } from "react";
import { Plus, Loader2, AlertTriangle, Zap } from "lucide-react";
import { TransactionListSkeleton } from "@/components/ui/skeleton";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  generated: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-700",
};

interface EInvoice {
  id: string;
  client_id: string;
  invoice_number: string;
  invoice_date: string;
  irn: string | null;
  ack_number: string | null;
  status: string;
  created_at: string;
}

export default function EInvoicePage() {
  const [clientId, setClientId] = useState("");
  const [records, setRecords] = useState<EInvoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showIRN, setShowIRN] = useState<string | null>(null);

  // Create form
  const [invNo, setInvNo] = useState("");
  const [invDate, setInvDate] = useState("");
  const [creating, setCreating] = useState(false);

  // IRN form
  const [irn, setIrn] = useState("");
  const [ackNo, setAckNo] = useState("");
  const [ackDate, setAckDate] = useState("");
  const [savingIRN, setSavingIRN] = useState(false);

  async function load(cid: string) {
    setLoading(true);
    const res = await apiFetch(`/api/einvoice/records?client_id=${cid}`);
    setRecords(res.data ?? []);
    setLoading(false);
  }

  async function handleCreate() {
    setCreating(true);
    const res = await apiFetch("/api/einvoice/records", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, invoice_number: invNo, invoice_date: invDate }),
    });
    if (res.success) {
      setShowCreate(false);
      setInvNo(""); setInvDate("");
      await load(clientId);
    }
    setCreating(false);
  }

  async function handleRecordIRN(recordId: string) {
    setSavingIRN(true);
    const res = await apiFetch(`/api/einvoice/records/${recordId}/irn-generated`, {
      method: "POST",
      body: JSON.stringify({ irn, ack_number: ackNo, ack_date: ackDate }),
    });
    if (res.success) {
      setShowIRN(null);
      setIrn(""); setAckNo(""); setAckDate("");
      await load(clientId);
    }
    setSavingIRN(false);
  }

  return (
    <div className="p-6 max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">E-Invoice Integration</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">CGST Act §31B, Rule 48(4) — IRN management</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
          <Plus size={12} /> New E-Invoice
        </button>
      </div>

      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-red-500 flex-shrink-0" />
        <p className="text-xs font-medium text-red-800">
          CA REVIEW REQUIRED — Generate IRN on IRP portal (einvoice1.gst.gov.in) first, then record here.
          DO NOT AUTO-SUBMIT.
        </p>
      </div>

      <div className="flex gap-3 items-center">
        <input
          value={clientId}
          onChange={e => setClientId(e.target.value)}
          placeholder="Client ID to load records"
          className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg flex-1 max-w-xs"
        />
        <button onClick={() => clientId && load(clientId)} disabled={!clientId || loading}
          className="text-xs px-3 py-1.5 bg-[#F1F5F9] rounded-lg disabled:opacity-50">
          Load
        </button>
      </div>

      {showCreate && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">New E-Invoice Record</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Invoice Number</label>
              <input value={invNo} onChange={e => setInvNo(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Invoice Date</label>
              <input type="date" value={invDate} onChange={e => setInvDate(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button onClick={handleCreate} disabled={creating || !invNo || !invDate || !clientId}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1">
              {creating && <Loader2 size={10} className="animate-spin" />} Create
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <TransactionListSkeleton rows={3} />
      ) : (
        <div className="space-y-2">
          {records.map(r => (
            <div key={r.id} className="bg-white border border-[#F1F5F9] rounded-xl px-4 py-3 flex items-center gap-3">
              <Zap size={16} className={r.status === "generated" ? "text-green-500" : r.status === "cancelled" ? "text-red-400" : "text-[#94A3B8]"} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#1E293B]">{r.invoice_number} — {r.invoice_date}</p>
                <p className="text-[10px] text-[#94A3B8]">
                  {r.irn ? `IRN: ${r.irn.slice(0, 20)}...` : "No IRN recorded"}
                  {r.ack_number && ` · Ack: ${r.ack_number}`}
                </p>
              </div>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[r.status]}`}>
                {r.status}
              </span>
              {r.status === "draft" && (
                <button onClick={() => setShowIRN(r.id)}
                  className="text-[10px] text-blue-600 hover:underline flex-shrink-0">Record IRN</button>
              )}
            </div>
          ))}
        </div>
      )}

      {showIRN && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">Record IRN from IRP Portal</p>
          <p className="text-[11px] text-amber-700 bg-amber-50 p-2 rounded">
            CA REVIEW REQUIRED — Generate IRN on IRP portal first, then enter details below
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-[10px] text-[#64748B] mb-1 block">IRN (64-char hash)</label>
              <input value={irn} onChange={e => setIrn(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg font-mono" />
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Ack Number</label>
              <input value={ackNo} onChange={e => setAckNo(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Ack Date</label>
              <input type="datetime-local" value={ackDate} onChange={e => setAckDate(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowIRN(null)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button onClick={() => handleRecordIRN(showIRN)} disabled={savingIRN || !irn || !ackNo}
              className="text-xs px-3 py-1.5 bg-green-600 text-white rounded disabled:opacity-50 flex items-center gap-1">
              {savingIRN && <Loader2 size={10} className="animate-spin" />} Record IRN
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

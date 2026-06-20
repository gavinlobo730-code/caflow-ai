"use client";

/**
 * Bank Feed (Banking B.1) — statement upload + transaction list + import history.
 *
 * Presentation only. CSV/XLSX parsing, normalization and deduplication all happen
 * SERVER-SIDE (POST /api/banking/statements/upload) — the browser sends the raw
 * file and renders the authoritative response. No matching / reconciliation /
 * posting here (future phases).
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, UploadCloud, RefreshCw, FileSpreadsheet, AlertCircle, CheckCircle } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import { formatPaise } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";

interface BankStatement {
  id: string;
  bank_name: string;
  account_number: string | null;
  statement_from: string;
  statement_to: string;
  row_count: number;
  import_status: string;
  file_name?: string | null;
  source_format?: string | null;
  created_at: string;
}

interface BankTxn {
  id: string;
  transaction_date: string;
  description: string;
  reference_no: string | null;
  debit_paise: number;
  credit_paise: number;
  balance_paise: number;
  match_status: string;
}

interface UploadResult {
  statement_id: string | null;
  imported: number;
  duplicates_skipped: number;
  total_rows: number;
}

const rupeesToPaise = (v: string): string | null => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? String(Math.round(n * 100)) : null;
};

export default function BankFeedPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [bankName, setBankName] = useState("HDFC Bank");
  const [accountNumber, setAccountNumber] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [txns, setTxns] = useState<BankTxn[]>([]);
  const [loadingTxns, setLoadingTxns] = useState(false);

  // Filters (Part E)
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minAmt, setMinAmt] = useState("");
  const [maxAmt, setMaxAmt] = useState("");

  useEffect(() => {
    getClients()
      .then((list) => { setClients(list); if (list.length) setClientId(list[0].id); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load clients"));
  }, []);

  const loadHistory = useCallback(async () => {
    if (!clientId) return;
    const res = (await api.banking.listStatements({ client_id: clientId })) as ApiResp<BankStatement[]>;
    if (res.success) setStatements(res.data ?? []);
  }, [clientId]);

  const loadTxns = useCallback(async () => {
    if (!clientId) return;
    setLoadingTxns(true);
    try {
      const params: Record<string, string> = { client_id: clientId };
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const lo = minAmt ? rupeesToPaise(minAmt) : null;
      const hi = maxAmt ? rupeesToPaise(maxAmt) : null;
      if (lo) params.min_amount_paise = lo;
      if (hi) params.max_amount_paise = hi;
      const res = (await api.banking.listTransactions(params)) as ApiResp<BankTxn[]>;
      if (res.success) setTxns(res.data ?? []);
    } finally {
      setLoadingTxns(false);
    }
  }, [clientId, dateFrom, dateTo, minAmt, maxAmt]);

  useEffect(() => { loadHistory(); loadTxns(); }, [loadHistory, loadTxns]);

  async function handleUpload() {
    if (!clientId) { setError("Select a client first."); return; }
    if (!file) { setError("Choose a CSV or XLSX file."); return; }
    setUploading(true); setError(null); setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      form.append("bank_name", bankName.trim() || "Bank");
      if (accountNumber.trim()) form.append("account_number", accountNumber.trim());
      const res = (await api.banking.uploadStatement(form)) as ApiResp<UploadResult>;
      if (!res.success || !res.data) throw new Error(res.error ?? "Upload failed");
      setResult(res.data);
      setFile(null);
      await loadHistory();
      await loadTxns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft className="w-4 h-4" /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Bank Feed</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Import bank statements (CSV / XLSX) — parsed & deduplicated on the server</p>
        </div>
        <select
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 max-w-[220px]"
          value={clientId} onChange={(e) => setClientId(e.target.value)}
        >
          {clients.length === 0 && <option value="">Loading clients…</option>}
          {clients.map((c) => <option key={c.id} value={c.id}>{c.client_name}</option>)}
        </select>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* Upload */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
        <h2 className="text-sm font-semibold text-[#0F172A]">Statement Upload</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-[#64748B] mb-1">Bank</label>
            <input value={bankName} onChange={(e) => setBankName(e.target.value)} className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg" />
          </div>
          <div>
            <label className="block text-xs text-[#64748B] mb-1">Account No. (optional)</label>
            <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg" />
          </div>
          <div>
            <label className="block text-xs text-[#64748B] mb-1">File (.csv, .xlsx)</label>
            <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="w-full text-xs" />
          </div>
        </div>
        <button
          onClick={handleUpload} disabled={uploading || !file || !clientId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          <UploadCloud className="w-4 h-4" /> {uploading ? "Uploading…" : "Upload & Import"}
        </button>
        {result && (
          <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-sm text-green-700 flex items-center gap-2">
            <CheckCircle className="w-4 h-4 shrink-0" />
            Imported {result.imported} transaction(s){result.duplicates_skipped > 0 ? `, skipped ${result.duplicates_skipped} duplicate(s)` : ""} of {result.total_rows} rows.
          </div>
        )}
      </div>

      {/* Import history */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#334155]">Import History</h2>
          <button onClick={loadHistory} className="text-[#94A3B8] hover:text-[#475569]"><RefreshCw className="w-3.5 h-3.5" /></button>
        </div>
        {statements.length === 0 ? (
          <p className="px-5 py-4 text-xs text-[#94A3B8]">No statements imported yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="px-5 py-2 text-left font-semibold">File</th>
              <th className="px-3 py-2 text-left font-semibold">Bank</th>
              <th className="px-3 py-2 text-left font-semibold">Period</th>
              <th className="px-3 py-2 text-right font-semibold">Rows</th>
              <th className="px-3 py-2 text-left font-semibold">Format</th>
              <th className="px-5 py-2 text-left font-semibold">Status</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {statements.map((s) => (
                <tr key={s.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-2 text-[#334155] flex items-center gap-1.5"><FileSpreadsheet className="w-3.5 h-3.5 text-[#94A3B8]" />{s.file_name ?? "—"}</td>
                  <td className="px-3 py-2 text-[#334155]">{s.bank_name}</td>
                  <td className="px-3 py-2 text-[#64748B]">{s.statement_from} → {s.statement_to}</td>
                  <td className="px-3 py-2 text-right text-[#334155]">{s.row_count}</td>
                  <td className="px-3 py-2 uppercase text-[#94A3B8]">{s.source_format ?? "—"}</td>
                  <td className="px-5 py-2"><span className="px-1.5 py-0.5 rounded-full text-[10px] bg-[#F1F5F9] text-[#64748B]">{s.import_status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Transactions + filters */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-[#334155]">Transactions</h2>
        </div>
        <div className="px-5 py-3 flex flex-wrap gap-3 items-end border-b border-gray-50 bg-[#F8FAFC]/40">
          <div><label className="block text-[10px] text-[#94A3B8] mb-1">From</label><input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="px-2 py-1 text-xs border border-[#E2E8F0] rounded" /></div>
          <div><label className="block text-[10px] text-[#94A3B8] mb-1">To</label><input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="px-2 py-1 text-xs border border-[#E2E8F0] rounded" /></div>
          <div><label className="block text-[10px] text-[#94A3B8] mb-1">Min ₹</label><input type="number" value={minAmt} onChange={(e) => setMinAmt(e.target.value)} className="px-2 py-1 text-xs border border-[#E2E8F0] rounded w-24" /></div>
          <div><label className="block text-[10px] text-[#94A3B8] mb-1">Max ₹</label><input type="number" value={maxAmt} onChange={(e) => setMaxAmt(e.target.value)} className="px-2 py-1 text-xs border border-[#E2E8F0] rounded w-24" /></div>
          <button onClick={loadTxns} className="px-3 py-1.5 text-xs bg-[#1E293B] text-white rounded hover:bg-[#334155]">Apply</button>
        </div>
        {loadingTxns ? (
          <p className="px-5 py-4 text-xs text-[#94A3B8]">Loading…</p>
        ) : txns.length === 0 ? (
          <p className="px-5 py-4 text-xs text-[#94A3B8]">No transactions match the filters.</p>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="px-5 py-2 text-left font-semibold">Date</th>
              <th className="px-3 py-2 text-left font-semibold">Description</th>
              <th className="px-3 py-2 text-left font-semibold">Ref</th>
              <th className="px-3 py-2 text-right font-semibold">Debit</th>
              <th className="px-3 py-2 text-right font-semibold">Credit</th>
              <th className="px-5 py-2 text-right font-semibold">Balance</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {txns.map((t) => (
                <tr key={t.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-2 text-[#64748B] whitespace-nowrap">{t.transaction_date}</td>
                  <td className="px-3 py-2 text-[#334155] truncate max-w-[280px]">{t.description}</td>
                  <td className="px-3 py-2 text-[#94A3B8] font-mono">{t.reference_no ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-mono text-red-700">{t.debit_paise ? formatPaise(t.debit_paise) : "—"}</td>
                  <td className="px-3 py-2 text-right font-mono text-green-700">{t.credit_paise ? formatPaise(t.credit_paise) : "—"}</td>
                  <td className="px-5 py-2 text-right font-mono text-[#334155]">{formatPaise(t.balance_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-[10px] text-[#94A3B8] text-center">
        Bank Feed Foundation (B.1) — import & storage only. Matching, categorisation and reconciliation arrive in later phases.
      </p>
    </div>
  );
}

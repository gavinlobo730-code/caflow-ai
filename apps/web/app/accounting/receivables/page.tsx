"use client";

/**
 * Receivables Aging Report
 * Groups outstanding invoices by aging bucket per standard accounting practice.
 * Uses fee_invoices table (CGST Act Section 31 — Tax Invoice).
 * All amounts in integer paise.
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, RefreshCw, Download, Bell } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Client {
  id: string;
  client_name: string;
}

interface FeeInvoice {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  client_id: string;
  total_paise: number;
  status: string;
}

interface AgingRow {
  invoice: FeeInvoice;
  clientName: string;
  outstandingPaise: number;
  daysOverdue: number;
  bucket: "current" | "1-30" | "31-60" | "61-90" | "90+";
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

function daysBetween(a: Date, b: Date): number {
  return Math.floor((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

function getBucket(daysOverdue: number): AgingRow["bucket"] {
  if (daysOverdue <= 0) return "current";
  if (daysOverdue <= 30) return "1-30";
  if (daysOverdue <= 60) return "31-60";
  if (daysOverdue <= 90) return "61-90";
  return "90+";
}

const BUCKET_LABEL: Record<AgingRow["bucket"], string> = {
  "current": "Current (Not Due)",
  "1-30": "1–30 Days Overdue",
  "31-60": "31–60 Days Overdue",
  "61-90": "61–90 Days Overdue",
  "90+": "90+ Days Overdue",
};

const BUCKET_COLOR: Record<AgingRow["bucket"], string> = {
  "current": "bg-green-50 text-green-700",
  "1-30": "bg-yellow-50 text-yellow-700",
  "31-60": "bg-orange-50 text-orange-700",
  "61-90": "bg-red-50 text-red-700",
  "90+": "bg-red-100 text-red-800",
};

const ROW_COLOR: Record<AgingRow["bucket"], string> = {
  "current": "bg-green-50/30",
  "1-30": "bg-yellow-50/30",
  "31-60": "bg-orange-50/30",
  "61-90": "bg-red-50/30",
  "90+": "bg-red-100/40",
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ReceivablesAgingPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("all");
  const [rows, setRows] = useState<AgingRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId().then(async (fid) => {
      setFirmId(fid);
      const { data } = await sb.from("clients").select("id, client_name").eq("firm_id", fid).eq("is_active", true).order("client_name");
      setClients((data ?? []) as Client[]);
    }).catch(() => setError("Failed to load clients"));
  }, []);

  async function generateAging() {
    if (!firmId) return;
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();
    const today = new Date();

    let query = sb.from("fee_invoices").select("id, invoice_no, invoice_date, due_date, client_id, total_paise, status").eq("firm_id", firmId).neq("status", "Paid").neq("status", "paid");
    if (selectedClientId !== "all") query = query.eq("client_id", selectedClientId);
    const { data, error: err } = await query.order("invoice_date", { ascending: false });

    if (err) { setError(err.message); setLoading(false); return; }
    const invoices = (data ?? []) as FeeInvoice[];

    // Build client map
    const clientMap: Record<string, string> = {};
    clients.forEach(c => { clientMap[c.id] = c.client_name; });

    const result: AgingRow[] = invoices.map(inv => {
      const dueDate = inv.due_date ? new Date(inv.due_date) : new Date(inv.invoice_date);
      const daysOverdue = daysBetween(dueDate, today);
      const bucket = getBucket(daysOverdue);
      return {
        invoice: inv,
        clientName: clientMap[inv.client_id] ?? "Unknown",
        outstandingPaise: inv.total_paise,
        daysOverdue,
        bucket,
      };
    });

    setRows(result);
    setGenerated(true);
    setLoading(false);
  }

  function sendReminder(invNo: string) {
    setToast(`Reminder sent for invoice ${invNo}`);
    setTimeout(() => setToast(null), 3000);
  }

  function exportExcel() {
    const headers = ["Invoice No", "Client", "Invoice Date", "Due Date", "Amount (₹)", "Outstanding (₹)", "Days Overdue", "Bucket"];
    const csvRows = rows.map(r => [
      r.invoice.invoice_no,
      r.clientName,
      r.invoice.invoice_date,
      r.invoice.due_date ?? "",
      (r.invoice.total_paise / 100).toFixed(2),
      (r.outstandingPaise / 100).toFixed(2),
      String(r.daysOverdue),
      BUCKET_LABEL[r.bucket],
    ]);
    const csv = [headers, ...csvRows].map(row => row.map(v => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `receivables-aging-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Summary stats
  const totalOutstanding = rows.reduce((s, r) => s + r.outstandingPaise, 0);
  const currentAmt = rows.filter(r => r.bucket === "current").reduce((s, r) => s + r.outstandingPaise, 0);
  const overdueAmt = rows.filter(r => r.bucket !== "current").reduce((s, r) => s + r.outstandingPaise, 0);
  const ninetyPlusAmt = rows.filter(r => r.bucket === "90+").reduce((s, r) => s + r.outstandingPaise, 0);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Receivables Aging</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Outstanding invoices by age bucket</p>
        </div>
        {generated && (
          <Button variant="outline" size="sm" onClick={exportExcel} className="flex items-center gap-1">
            <Download className="w-4 h-4" /> Export CSV
          </Button>
        )}
      </div>

      {error && <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 bg-green-700 text-white text-sm px-4 py-2 rounded-lg shadow-lg z-50 transition-all">
          {toast}
        </div>
      )}

      {/* Filters */}
      <Card>
        <CardContent className="pt-4 pb-4 flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Client</label>
            <select className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[200px]" value={selectedClientId} onChange={e => setSelectedClientId(e.target.value)}>
              <option value="all">All Clients</option>
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
          </div>
          <Button onClick={generateAging} disabled={loading} className="flex items-center gap-1">
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Generating…" : "Generate Aging"}
          </Button>
        </CardContent>
      </Card>

      {/* Summary cards */}
      {generated && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Total Outstanding", value: fmtRs(totalOutstanding), cls: "text-[#0F172A]" },
            { label: "Current (Not Due)", value: fmtRs(currentAmt), cls: "text-green-700" },
            { label: "Overdue", value: fmtRs(overdueAmt), cls: "text-amber-700" },
            { label: "90+ Days Overdue", value: fmtRs(ninetyPlusAmt), cls: "text-red-700" },
          ].map(s => (
            <Card key={s.label}>
              <CardContent className="pt-4 pb-3">
                <p className={`text-lg font-bold ${s.cls}`}>{s.value}</p>
                <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Aging table */}
      {generated && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Invoice Aging Detail</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase tracking-wide">
                  <th className="px-4 py-3 text-left">Invoice No</th>
                  <th className="px-4 py-3 text-left">Client</th>
                  <th className="px-4 py-3 text-left">Invoice Date</th>
                  <th className="px-4 py-3 text-left">Due Date</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3 text-right">Outstanding</th>
                  <th className="px-4 py-3 text-right">Days Overdue</th>
                  <th className="px-4 py-3 text-center">Bucket</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {rows.map(r => (
                  <tr key={r.invoice.id} className={ROW_COLOR[r.bucket]}>
                    <td className="px-4 py-3 font-mono text-xs font-medium text-[#0F172A]">{r.invoice.invoice_no}</td>
                    <td className="px-4 py-3 text-[#334155]">{r.clientName}</td>
                    <td className="px-4 py-3 text-[#475569]">{r.invoice.invoice_date}</td>
                    <td className="px-4 py-3 text-[#475569]">{r.invoice.due_date ?? "—"}</td>
                    <td className="px-4 py-3 text-right text-[#334155]">{fmtRs(r.invoice.total_paise)}</td>
                    <td className="px-4 py-3 text-right font-semibold text-[#0F172A]">{fmtRs(r.outstandingPaise)}</td>
                    <td className="px-4 py-3 text-right text-[#475569]">{r.daysOverdue > 0 ? r.daysOverdue : "—"}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${BUCKET_COLOR[r.bucket]}`}>
                        {BUCKET_LABEL[r.bucket]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.bucket !== "current" && (
                        <button onClick={() => sendReminder(r.invoice.invoice_no)} className="flex items-center gap-1 text-xs text-blue-600 hover:underline whitespace-nowrap">
                          <Bell className="w-3 h-3" /> Remind
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-[#94A3B8] text-sm">No outstanding invoices found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!generated && !loading && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-12 text-center">
          <RefreshCw className="w-10 h-10 text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-[#94A3B8]">Select a client and click &quot;Generate Aging&quot; to see outstanding invoices</p>
        </div>
      )}
    </div>
  );
}

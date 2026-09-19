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
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { todayLocalISO, daysBetweenLocalISO } from "@/lib/dateMath";
import { Callout } from "@/components/ui/callout";
import { downloadCsv, toCsvRows } from "@/lib/export/csv";

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
      // clients has no is_active column; its lifecycle field is `status`
      // (CHECK: active | inactive | archived).
      const { data } = await selectAll(() => sb.from("clients")
        .select("id, client_name").eq("firm_id", fid).eq("status", "active")
        .order("client_name").order("id"));
      setClients((data ?? []) as Client[]);
    }).catch(() => setError("Failed to load clients"));
  }, []);

  async function generateAging() {
    if (!firmId) return;
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();
    const today = todayLocalISO();

    try {
      // The ageing this builds is downloaded as a CSV, so the read must return
      // every open invoice rather than PostgREST's first thousand — the cap is
      // silent, and a receivables ageing short by a year of invoices is worse
      // than no ageing, because somebody foots it. fee_invoices passes 1000 in
      // under two years on a 50-client book.
      //
      // `.order("id")` after invoice_date is the unique TIEBREAKER selectAll's
      // OFFSET paging needs: invoice_date is not unique, so without it two
      // invoices sharing a date can shift across a page boundary and be
      // duplicated or dropped. It does not change the displayed order — rows
      // sharing a date had no defined order before either.
      const { data, error: err } = await selectAll(() => {
        let query = sb.from("fee_invoices")
          .select("id, invoice_no, invoice_date, due_date, client_id, total_paise, status")
          .eq("firm_id", firmId).neq("status", "Paid").neq("status", "paid");
        if (selectedClientId !== "all") query = query.eq("client_id", selectedClientId);
        return query.order("invoice_date", { ascending: false }).order("id");
      });

      if (err) throw new Error(err.message);
      const invoices = (data ?? []) as FeeInvoice[];

      // Build client map
      const clientMap: Record<string, string> = {};
      clients.forEach(c => { clientMap[c.id] = c.client_name; });

      const result: AgingRow[] = invoices.map(inv => {
        const dueDateStr = inv.due_date ?? inv.invoice_date;
        const daysOverdue = daysBetweenLocalISO(dueDateStr, today) ?? 0;
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
    } catch (e) {
      // A rejected query used to escape here, leaving setLoading(true) set and
      // the button spinning with nothing to click. The report is not marked
      // generated, so the screen keeps its prompt instead of claiming an empty
      // ageing report.
      setError(e instanceof Error ? e.message : "Couldn't build the ageing report.");
    } finally {
      setLoading(false);
    }
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
    // Every field used to be wrapped in quotes WITHOUT doubling the ones
    // inside it, so a customer name or narration carrying a quote ended its
    // field early and every parser disagreed about where the row ended.
    downloadCsv(`receivables-aging-${todayLocalISO()}.csv`,
                toCsvRows([headers, ...csvRows]));
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
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink">Receivables Aging</h1>
          <p className="text-sm text-ps-label mt-0.5">Outstanding invoices by age bucket</p>
        </div>
        {generated && (
          <Button variant="outline" size="sm" onClick={exportExcel} className="flex items-center gap-1">
            <Download className="w-4 h-4" /> Export CSV
          </Button>
        )}
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

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
            <label className="text-xs font-medium text-ps-body block mb-1">Client</label>
            <div className="min-w-[200px]">
              <ClientLookup
                clients={clients}
                value={selectedClientId === "all" ? "" : selectedClientId}
                onChange={(id) => setSelectedClientId(id || "all")}
                clearable
                ariaLabel="Client"
                placeholder="All Clients"
              />
            </div>
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
            { label: "Total Outstanding", value: fmtRs(totalOutstanding), cls: "text-ps-ink" },
            { label: "Current (Not Due)", value: fmtRs(currentAmt), cls: "text-green-700" },
            { label: "Overdue", value: fmtRs(overdueAmt), cls: "text-amber-700" },
            { label: "90+ Days Overdue", value: fmtRs(ninetyPlusAmt), cls: "text-red-700" },
          ].map(s => (
            <Card key={s.label}>
              <CardContent className="pt-4 pb-3">
                <p className={`text-lg font-bold ${s.cls}`}>{s.value}</p>
                <p className="text-xs text-ps-label mt-0.5">{s.label}</p>
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
                <tr className="bg-ps-bg text-xs text-ps-label uppercase tracking-wide">
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
              <tbody className="divide-y divide-ps-bg">
                {rows.map(r => (
                  <tr key={r.invoice.id} className={ROW_COLOR[r.bucket]}>
                    <td className="px-4 py-3 font-mono text-xs font-medium text-ps-ink">{r.invoice.invoice_no}</td>
                    <td className="px-4 py-3 text-ps-body">{r.clientName}</td>
                    <td className="px-4 py-3 text-ps-label">{r.invoice.invoice_date}</td>
                    <td className="px-4 py-3 text-ps-label">{r.invoice.due_date ?? "—"}</td>
                    <td className="px-4 py-3 text-right text-ps-body">{fmtRs(r.invoice.total_paise)}</td>
                    <td className="px-4 py-3 text-right font-semibold text-ps-ink">{fmtRs(r.outstandingPaise)}</td>
                    <td className="px-4 py-3 text-right text-ps-label">{r.daysOverdue > 0 ? r.daysOverdue : "—"}</td>
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
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-ps-hint text-sm">No outstanding invoices found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!generated && !loading && (
        <div className="bg-white rounded-xl border border-ps-muted p-12 text-center">
          <RefreshCw className="w-10 h-10 text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-ps-hint">Select a client and click &quot;Generate Aging&quot; to see outstanding invoices</p>
        </div>
      )}
    </div>
  );
}

"use client";

/**
 * Reports Hub — PracticeSync AI
 * Inline report viewer with print/export via window.print()
 */

import { useState, useCallback } from "react";
import Link from "next/link";
import {
  FileText,
  TrendingUp,
  CheckSquare,
  AlertCircle,
  Printer,
  ChevronDown,
  ChevronUp,
  Loader2,
  X,
  BarChart3,
} from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getClients } from "@/lib/data/clients";
import { getTransactions } from "@/lib/data/transactions";
import { getGSTSummary } from "@/lib/data/transactions";
import { getComplianceCalendar } from "@/lib/data/compliance";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";

// ─── Types ───────────────────────────────────────────────────────────────────

type ReportId = "gst_summary" | "pl_statement" | "compliance_status" | "outstanding_invoices";

interface GSTSummaryData {
  client: Client;
  month: string;
  gstr1: {
    taxable: number;
    cgst: number;
    sgst: number;
    igst: number;
    total: number;
  };
  gstr3b: {
    output_cgst: number;
    output_sgst: number;
    output_igst: number;
    itc_cgst: number;
    itc_sgst: number;
    itc_igst: number;
    net_cgst: number;
    net_sgst: number;
    net_igst: number;
  };
  tds_deducted: number;
}

interface PLData {
  clientName: string;
  fromDate: string;
  toDate: string;
  revenue: { account: string; total: number }[];
  expenses: { account: string; total: number }[];
  totalRevenue: number;
  totalExpenses: number;
  netPL: number;
}

interface ComplianceRow {
  clientId: string;
  clientName: string;
  gstr1Filed: number;
  gstr1Pending: number;
  gstr3bFiled: number;
  gstr3bPending: number;
  gstr9Filed: number;
  gstr9Pending: number;
  overdue: boolean;
}

interface OutstandingRow {
  id: string;
  clientId: string;
  clientName?: string;
  transactionDate: string;
  partyName: string;
  totalPaise: number;
  daysOutstanding: number;
}

type ReportData = GSTSummaryData | PLData | ComplianceRow[] | OutstandingRow[];

// ─── Report card definitions ─────────────────────────────────────────────────

const REPORTS = [
  {
    id: "gst_summary" as ReportId,
    name: "GST Summary Report",
    description: "GSTR-1 outward supplies, GSTR-3B net liability, and ITC available for a client/month",
    icon: FileText,
  },
  {
    id: "pl_statement" as ReportId,
    name: "P&L Statement",
    description: "Revenue and expense breakdown by account with net profit/loss",
    icon: TrendingUp,
  },
  {
    id: "compliance_status" as ReportId,
    name: "Compliance Status Report",
    description: "All clients' GSTR-1, GSTR-3B, and ITR filing status for the current FY",
    icon: CheckSquare,
  },
  {
    id: "outstanding_invoices" as ReportId,
    name: "Outstanding Invoices Report",
    description: "All draft/unpaid invoices across clients with days outstanding",
    icon: AlertCircle,
  },
];

// ─── Utility ─────────────────────────────────────────────────────────────────

function daysBetween(dateStr: string): number {
  const d = new Date(dateStr);
  const now = new Date();
  return Math.floor((now.getTime() - d.getTime()) / 86400000);
}

function currentMonthStr(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function currentFYStart(): string {
  const now = new Date();
  const fyYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${fyYear}-04-01`;
}

// ─── Sub-report components ────────────────────────────────────────────────────

function GSTSummaryReport({ data }: { data: GSTSummaryData }) {
  const totalITC = data.gstr3b.itc_cgst + data.gstr3b.itc_sgst + data.gstr3b.itc_igst;
  const totalNetLiability = data.gstr3b.net_cgst + data.gstr3b.net_sgst + data.gstr3b.net_igst;

  return (
    <div className="report-content space-y-6">
      <div className="border-b pb-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">GST Summary Report</h2>
        <p className="text-sm text-[#64748B]">
          {data.client.client_name} — {data.month}
        </p>
      </div>

      {/* GSTR-1 Outward Supplies */}
      <section>
        <h3 className="text-sm font-semibold text-[#334155] mb-3 uppercase tracking-wide">
          GSTR-1 — Outward Supplies
        </h3>
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <tbody className="divide-y divide-[#F1F5F9]">
            <tr className="bg-[#F8FAFC]">
              <td className="px-4 py-2.5 text-[#475569]">Taxable Value</td>
              <td className="px-4 py-2.5 text-right font-medium text-[#0F172A]">
                {formatPaise(data.gstr1.taxable)}
              </td>
            </tr>
            <tr>
              <td className="px-4 py-2.5 text-[#475569]">CGST</td>
              <td className="px-4 py-2.5 text-right font-medium text-[#0F172A]">
                {formatPaise(data.gstr1.cgst)}
              </td>
            </tr>
            <tr className="bg-[#F8FAFC]">
              <td className="px-4 py-2.5 text-[#475569]">SGST</td>
              <td className="px-4 py-2.5 text-right font-medium text-[#0F172A]">
                {formatPaise(data.gstr1.sgst)}
              </td>
            </tr>
            <tr>
              <td className="px-4 py-2.5 text-[#475569]">IGST</td>
              <td className="px-4 py-2.5 text-right font-medium text-[#0F172A]">
                {formatPaise(data.gstr1.igst)}
              </td>
            </tr>
            <tr className="bg-blue-50 font-semibold">
              <td className="px-4 py-2.5 text-blue-800">Total Invoice Value</td>
              <td className="px-4 py-2.5 text-right text-blue-900">
                {formatPaise(data.gstr1.total)}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* GSTR-3B Net Liability */}
      <section>
        <h3 className="text-sm font-semibold text-[#334155] mb-3 uppercase tracking-wide">
          GSTR-3B — Net Tax Liability
        </h3>
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <thead className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Tax Head</th>
              <th className="px-4 py-2 text-right">Output</th>
              <th className="px-4 py-2 text-right">ITC</th>
              <th className="px-4 py-2 text-right">Net Payable</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            <tr>
              <td className="px-4 py-2.5 text-[#475569]">CGST</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(data.gstr3b.output_cgst)}</td>
              <td className="px-4 py-2.5 text-right text-green-700">{formatPaise(data.gstr3b.itc_cgst)}</td>
              <td className="px-4 py-2.5 text-right font-medium">
                {formatPaise(Math.max(0, data.gstr3b.net_cgst))}
              </td>
            </tr>
            <tr className="bg-[#F8FAFC]">
              <td className="px-4 py-2.5 text-[#475569]">SGST</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(data.gstr3b.output_sgst)}</td>
              <td className="px-4 py-2.5 text-right text-green-700">{formatPaise(data.gstr3b.itc_sgst)}</td>
              <td className="px-4 py-2.5 text-right font-medium">
                {formatPaise(Math.max(0, data.gstr3b.net_sgst))}
              </td>
            </tr>
            <tr>
              <td className="px-4 py-2.5 text-[#475569]">IGST</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(data.gstr3b.output_igst)}</td>
              <td className="px-4 py-2.5 text-right text-green-700">{formatPaise(data.gstr3b.itc_igst)}</td>
              <td className="px-4 py-2.5 text-right font-medium">
                {formatPaise(Math.max(0, data.gstr3b.net_igst))}
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr className="bg-orange-50 font-semibold text-orange-900">
              <td className="px-4 py-2.5">Total</td>
              <td className="px-4 py-2.5 text-right">
                {formatPaise(data.gstr3b.output_cgst + data.gstr3b.output_sgst + data.gstr3b.output_igst)}
              </td>
              <td className="px-4 py-2.5 text-right text-green-800">{formatPaise(totalITC)}</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(Math.max(0, totalNetLiability))}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      {/* TDS */}
      {data.tds_deducted > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-[#334155] mb-2 uppercase tracking-wide">TDS</h3>
          <div className="flex justify-between px-4 py-3 bg-[#F8FAFC] rounded-lg text-sm">
            <span className="text-[#475569]">TDS Deducted (Purchase Invoices)</span>
            <span className="font-medium text-[#0F172A]">{formatPaise(data.tds_deducted)}</span>
          </div>
        </section>
      )}
    </div>
  );
}

function PLStatementReport({ data }: { data: PLData }) {
  const isProfit = data.netPL >= 0;

  return (
    <div className="report-content space-y-6">
      <div className="border-b pb-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">P&L Statement</h2>
        <p className="text-sm text-[#64748B]">
          {data.clientName} — {formatDate(data.fromDate)} to {formatDate(data.toDate)}
        </p>
      </div>

      {/* Revenue */}
      <section>
        <h3 className="text-sm font-semibold text-[#334155] mb-3 uppercase tracking-wide">Revenue</h3>
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <thead className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Account / Party</th>
              <th className="px-4 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {data.revenue.length === 0 ? (
              <tr>
                <td colSpan={2} className="px-4 py-4 text-center text-[#94A3B8] text-xs">
                  No revenue transactions in this period
                </td>
              </tr>
            ) : (
              data.revenue.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2.5 text-[#475569]">{r.account}</td>
                  <td className="px-4 py-2.5 text-right text-[#0F172A]">{formatPaise(r.total)}</td>
                </tr>
              ))
            )}
          </tbody>
          <tfoot>
            <tr className="bg-green-50 font-semibold text-green-900">
              <td className="px-4 py-2.5">Total Revenue</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(data.totalRevenue)}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      {/* Expenses */}
      <section>
        <h3 className="text-sm font-semibold text-[#334155] mb-3 uppercase tracking-wide">Expenses</h3>
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <thead className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Account / Party</th>
              <th className="px-4 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {data.expenses.length === 0 ? (
              <tr>
                <td colSpan={2} className="px-4 py-4 text-center text-[#94A3B8] text-xs">
                  No expense transactions in this period
                </td>
              </tr>
            ) : (
              data.expenses.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2.5 text-[#475569]">{r.account}</td>
                  <td className="px-4 py-2.5 text-right text-[#0F172A]">{formatPaise(r.total)}</td>
                </tr>
              ))
            )}
          </tbody>
          <tfoot>
            <tr className="bg-red-50 font-semibold text-red-900">
              <td className="px-4 py-2.5">Total Expenses</td>
              <td className="px-4 py-2.5 text-right">{formatPaise(data.totalExpenses)}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      {/* Net P&L */}
      <div
        className={`flex justify-between items-center px-5 py-4 rounded-xl font-bold text-base border-2 ${
          isProfit
            ? "bg-green-50 border-green-200 text-green-900"
            : "bg-red-50 border-red-200 text-red-900"
        }`}
      >
        <span>{isProfit ? "Net Profit" : "Net Loss"}</span>
        <span>{formatPaise(Math.abs(data.netPL))}</span>
      </div>
    </div>
  );
}

function ComplianceStatusReport({ data }: { data: ComplianceRow[] }) {
  function trafficLight(filed: number, pending: number, overdue: boolean) {
    if (overdue) return "bg-red-100 text-red-700";
    if (pending === 0) return "bg-green-100 text-green-700";
    return "bg-amber-100 text-amber-700";
  }

  function label(filed: number, pending: number) {
    if (pending === 0) return `${filed} filed`;
    return `${filed} filed / ${pending} pending`;
  }

  return (
    <div className="report-content space-y-4">
      <div className="border-b pb-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">Compliance Status Report</h2>
        <p className="text-sm text-[#64748B]">Current Financial Year — all clients</p>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-[#64748B]">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-green-400 inline-block" /> All filed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-amber-400 inline-block" /> Some pending
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-red-400 inline-block" /> Overdue
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <thead className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Client</th>
              <th className="px-4 py-2 text-center">GSTR-1</th>
              <th className="px-4 py-2 text-center">GSTR-3B</th>
              <th className="px-4 py-2 text-center">GSTR-9</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {data.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-[#94A3B8] text-xs">
                  No compliance data found
                </td>
              </tr>
            ) : (
              data.map((row) => (
                <tr key={row.clientId}>
                  <td className="px-4 py-3 font-medium text-[#0F172A]">{row.clientName}</td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${trafficLight(
                        row.gstr1Filed,
                        row.gstr1Pending,
                        row.overdue
                      )}`}
                    >
                      {label(row.gstr1Filed, row.gstr1Pending)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${trafficLight(
                        row.gstr3bFiled,
                        row.gstr3bPending,
                        row.overdue
                      )}`}
                    >
                      {label(row.gstr3bFiled, row.gstr3bPending)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${trafficLight(
                        row.gstr9Filed,
                        row.gstr9Pending,
                        false
                      )}`}
                    >
                      {label(row.gstr9Filed, row.gstr9Pending)}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OutstandingInvoicesReport({ data }: { data: OutstandingRow[] }) {
  const totalPaise = data.reduce((s, r) => s + r.totalPaise, 0);

  return (
    <div className="report-content space-y-4">
      <div className="border-b pb-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">Outstanding Invoices Report</h2>
        <p className="text-sm text-[#64748B]">All draft/unpaid invoices — all clients</p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border border-[#E2E8F0] rounded-lg overflow-hidden">
          <thead className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Client</th>
              <th className="px-4 py-2 text-left">Invoice Date</th>
              <th className="px-4 py-2 text-left">Party</th>
              <th className="px-4 py-2 text-right">Amount</th>
              <th className="px-4 py-2 text-right">Days O/S</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {data.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-[#94A3B8] text-xs">
                  No outstanding invoices
                </td>
              </tr>
            ) : (
              data.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-2.5 text-[#475569]">{row.clientName ?? row.clientId}</td>
                  <td className="px-4 py-2.5 text-[#475569]">{formatDate(row.transactionDate)}</td>
                  <td className="px-4 py-2.5 font-medium text-[#0F172A]">{row.partyName}</td>
                  <td className="px-4 py-2.5 text-right text-[#0F172A]">{formatPaise(row.totalPaise)}</td>
                  <td className="px-4 py-2.5 text-right">
                    <span
                      className={`font-medium ${
                        row.daysOutstanding > 30
                          ? "text-red-600"
                          : row.daysOutstanding > 15
                          ? "text-amber-600"
                          : "text-[#475569]"
                      }`}
                    >
                      {row.daysOutstanding}d
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
          {data.length > 0 && (
            <tfoot>
              <tr className="bg-[#F8FAFC] font-semibold text-[#0F172A]">
                <td colSpan={3} className="px-4 py-2.5">
                  Total Outstanding ({data.length} invoices)
                </td>
                <td className="px-4 py-2.5 text-right">{formatPaise(totalPaise)}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

// ─── Report Viewer (expanded card) ───────────────────────────────────────────

interface ReportViewerProps {
  reportId: ReportId;
  onClose: () => void;
}

function ReportViewer({ reportId, onClose }: ReportViewerProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ReportData | null>(null);

  // Form state
  const [clients, setClients] = useState<Client[]>([]);
  const [clientsLoaded, setClientsLoaded] = useState(false);
  const [selectedClientId, setSelectedClientId] = useState<string>("all");
  const [selectedMonth, setSelectedMonth] = useState(currentMonthStr());
  const [fromDate, setFromDate] = useState(currentFYStart());
  const [toDate, setToDate] = useState(new Date().toISOString().split("T")[0]);

  // Load clients once
  const ensureClients = useCallback(async () => {
    if (clientsLoaded) return;
    try {
      const list = await getClients();
      setClients(list);
      if (list.length > 0 && reportId === "gst_summary") {
        setSelectedClientId(list[0].id);
      }
      setClientsLoaded(true);
    } catch {
      // non-fatal
    }
  }, [clientsLoaded, reportId]);

  // Load clients on mount for reports that need them
  useState(() => {
    if (reportId === "gst_summary" || reportId === "pl_statement") {
      ensureClients();
    }
  });

  // Generate report
  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setData(null);

    try {
      if (reportId === "gst_summary") {
        if (!selectedClientId || selectedClientId === "all") {
          setError("Please select a client.");
          setLoading(false);
          return;
        }
        const client = clients.find((c) => c.id === selectedClientId);
        if (!client) {
          setError("Client not found.");
          setLoading(false);
          return;
        }
        const summary = await getGSTSummary(selectedClientId, selectedMonth);
        setData({ client, month: selectedMonth, ...summary } as GSTSummaryData);
      } else if (reportId === "pl_statement") {
        const txns = await getTransactions(
          selectedClientId === "all" ? undefined : selectedClientId
        );
        const filtered = txns.filter(
          (t) => t.transaction_date >= fromDate && t.transaction_date <= toDate
        );
        const sales = filtered.filter((t) => t.transaction_type === "sales_invoice");
        const purchases = filtered.filter((t) => t.transaction_type === "purchase_invoice");

        // Group revenue by party_name (account proxy)
        const revenueMap = new Map<string, number>();
        for (const t of sales) {
          revenueMap.set(t.party_name, (revenueMap.get(t.party_name) ?? 0) + t.taxable_amount_paise);
        }
        const expenseMap = new Map<string, number>();
        for (const t of purchases) {
          expenseMap.set(t.party_name, (expenseMap.get(t.party_name) ?? 0) + t.taxable_amount_paise);
        }

        const totalRevenue = sales.reduce((s, t) => s + t.taxable_amount_paise, 0);
        const totalExpenses = purchases.reduce((s, t) => s + t.taxable_amount_paise, 0);

        const clientName =
          selectedClientId === "all"
            ? "All Clients"
            : clients.find((c) => c.id === selectedClientId)?.client_name ?? selectedClientId;

        setData({
          clientName,
          fromDate,
          toDate,
          revenue: Array.from(revenueMap.entries()).map(([account, total]) => ({ account, total })),
          expenses: Array.from(expenseMap.entries()).map(([account, total]) => ({ account, total })),
          totalRevenue,
          totalExpenses,
          netPL: totalRevenue - totalExpenses,
        } as PLData);
      } else if (reportId === "compliance_status") {
        const entries = await getComplianceCalendar();
        const today = new Date().toISOString().split("T")[0];

        // Group by client
        const map = new Map<string, { name: string; entries: ComplianceEntry[] }>();
        for (const e of entries) {
          const name =
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (e as any).clients?.client_name ?? e.client_id;
          if (!map.has(e.client_id)) map.set(e.client_id, { name, entries: [] });
          map.get(e.client_id)!.entries.push(e);
        }

        const rows: ComplianceRow[] = [];
        Array.from(map.entries()).forEach(([clientId, { name, entries: es }]) => {
          const of_type = (type: string) => es.filter((e: ComplianceEntry) => e.compliance_type === type);
          const filed = (type: string) =>
            of_type(type).filter((e: ComplianceEntry) => e.filing_status === "filed").length;
          const pending = (type: string) =>
            of_type(type).filter((e: ComplianceEntry) => e.filing_status !== "filed").length;
          const hasOverdue = es.some(
            (e: ComplianceEntry) => e.filing_status !== "filed" && e.due_date < today
          );
          rows.push({
            clientId,
            clientName: name,
            gstr1Filed: filed("GSTR1"),
            gstr1Pending: pending("GSTR1"),
            gstr3bFiled: filed("GSTR3B"),
            gstr3bPending: pending("GSTR3B"),
            gstr9Filed: filed("GSTR9"),
            gstr9Pending: pending("GSTR9"),
            overdue: hasOverdue,
          });
        });

        setData(rows);
      } else if (reportId === "outstanding_invoices") {
        const allClients = await getClients();
        const clientMap = new Map(allClients.map((c) => [c.id, c.client_name]));
        const txns = await getTransactions();
        const draft = txns.filter((t) => t.status === "draft");
        const rows: OutstandingRow[] = draft.map((t) => ({
          id: t.id,
          clientId: t.client_id,
          clientName: clientMap.get(t.client_id),
          transactionDate: t.transaction_date,
          partyName: t.party_name,
          totalPaise: t.total_paise,
          daysOutstanding: daysBetween(t.transaction_date),
        }));
        // Sort by days outstanding desc
        rows.sort((a, b) => b.daysOutstanding - a.daysOutstanding);
        setData(rows);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate report");
    } finally {
      setLoading(false);
    }
  }, [reportId, selectedClientId, selectedMonth, fromDate, toDate, clients]);

  const reportDef = REPORTS.find((r) => r.id === reportId)!;
  const Icon = reportDef.icon;

  return (
    <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#F1F5F9] bg-[#F8FAFC] print:hidden">
        <Icon size={16} className="text-[#64748B] shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-[#0F172A]">{reportDef.name}</p>
          <p className="text-xs text-[#94A3B8]">{reportDef.description}</p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-[#94A3B8] hover:text-[#475569] hover:bg-[#F1F5F9] transition-colors"
          aria-label="Close"
        >
          <X size={14} />
        </button>
      </div>

      {/* Controls */}
      <div className="px-5 py-4 border-b border-[#F1F5F9] print:hidden">
        <div className="flex flex-wrap gap-3 items-end">
          {/* Client selector */}
          {(reportId === "gst_summary" || reportId === "pl_statement") && (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-[#64748B] font-medium">Client</label>
              <div className="min-w-[180px]">
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
          )}

          {/* Month selector */}
          {reportId === "gst_summary" && (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-[#64748B] font-medium">Month</label>
              <input
                type="month"
                value={selectedMonth}
                onChange={(e) => setSelectedMonth(e.target.value)}
                className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
            </div>
          )}

          {/* Date range */}
          {reportId === "pl_statement" && (
            <>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-[#64748B] font-medium">From</label>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-[#64748B] font-medium">To</label>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              </div>
            </>
          )}

          <button
            onClick={generate}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : null}
            {loading ? "Generating…" : "Generate Report"}
          </button>

          {data && (
            <button
              onClick={() => window.print()}
              className="flex items-center gap-2 px-4 py-2 border border-[#E2E8F0] text-[#475569] text-sm font-medium rounded-lg hover:bg-[#F8FAFC] transition-colors"
            >
              <Printer size={14} />
              Print / Export
            </button>
          )}
        </div>
      </div>

      {/* Report output */}
      <div className="p-5">
        {error && (
          <div className="flex items-center gap-2 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
            <AlertCircle size={14} className="shrink-0" />
            {error}
          </div>
        )}

        {!data && !loading && !error && (
          <p className="text-sm text-[#94A3B8] text-center py-8">
            Configure the options above and click &quot;Generate Report&quot; to view results.
          </p>
        )}

        {loading && (
          <div className="flex items-center justify-center py-12 gap-3 text-[#94A3B8]">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm">Loading report data…</span>
          </div>
        )}

        {data && reportId === "gst_summary" && (
          <GSTSummaryReport data={data as GSTSummaryData} />
        )}
        {data && reportId === "pl_statement" && (
          <PLStatementReport data={data as PLData} />
        )}
        {data && reportId === "compliance_status" && (
          <ComplianceStatusReport data={data as ComplianceRow[]} />
        )}
        {data && reportId === "outstanding_invoices" && (
          <OutstandingInvoicesReport data={data as OutstandingRow[]} />
        )}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const [activeReport, setActiveReport] = useState<ReportId | null>(null);

  return (
    <>
      {/* Print styles */}
      <style jsx global>{`
        @media print {
          /* Hide everything except the report content */
          body > * { display: none !important; }
          .report-print-root { display: block !important; }
          .report-content { display: block !important; }
          nav, aside, header, footer, [data-sidebar] { display: none !important; }
          .print\\:hidden { display: none !important; }
        }
      `}</style>

      <div className="p-6 max-w-5xl mx-auto space-y-6 report-print-root">
        <div className="print:hidden">
          <h1 className="text-xl font-semibold text-[#0F172A]">Reports</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Generate and export practice reports</p>
        </div>

        {/* Cash Flow Forecast link card */}
        {!activeReport && (
          <div className="print:hidden">
            <Link
              href="/reports/cash-flow"
              className="group flex items-start gap-4 p-5 bg-white rounded-xl border border-[#F1F5F9] hover:border-blue-200 hover:shadow-sm transition-all text-left w-full"
            >
              <div className="p-2.5 bg-[#F8FAFC] rounded-lg group-hover:bg-blue-50 transition-colors shrink-0">
                <TrendingUp size={18} className="text-[#64748B] group-hover:text-blue-600 transition-colors" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-[#0F172A] group-hover:text-blue-700 transition-colors">
                  Cash Flow Forecast
                </p>
                <p className="text-xs text-[#94A3B8] mt-0.5 leading-relaxed">
                  6-month projection based on unpaid invoices, loan EMIs, and GST dues
                </p>
              </div>
              <ChevronDown
                size={14}
                className="text-[#CBD5E1] group-hover:text-blue-600 transition-colors mt-1 shrink-0 -rotate-90"
              />
            </Link>
          </div>
        )}

        {/* Financial Statements link card */}
        {!activeReport && (
          <div className="print:hidden">
            <Link
              href="/reports/financial-statements"
              className="group flex items-start gap-4 p-5 bg-white rounded-xl border border-[#F1F5F9] hover:border-blue-200 hover:shadow-sm transition-all text-left w-full"
            >
              <div className="p-2.5 bg-[#F8FAFC] rounded-lg group-hover:bg-blue-50 transition-colors shrink-0">
                <BarChart3 size={18} className="text-[#64748B] group-hover:text-blue-600 transition-colors" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-[#0F172A] group-hover:text-blue-700 transition-colors">
                  Financial Statements
                </p>
                <p className="text-xs text-[#94A3B8] mt-0.5 leading-relaxed">
                  Year-on-year P&L and Balance Sheet comparison with variance analysis and Excel export
                </p>
              </div>
              <ChevronDown
                size={14}
                className="text-[#CBD5E1] group-hover:text-blue-600 transition-colors mt-1 shrink-0 -rotate-90"
              />
            </Link>
          </div>
        )}

        {/* Report cards grid */}
        {!activeReport && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 print:hidden">
            {REPORTS.map((report) => {
              const Icon = report.icon;
              return (
                <button
                  key={report.id}
                  onClick={() => setActiveReport(report.id)}
                  className="group flex items-start gap-4 p-5 bg-white rounded-xl border border-[#F1F5F9] hover:border-blue-200 hover:shadow-sm transition-all text-left"
                >
                  <div className="p-2.5 bg-[#F8FAFC] rounded-lg group-hover:bg-blue-50 transition-colors shrink-0">
                    <Icon size={18} className="text-[#64748B] group-hover:text-blue-600 transition-colors" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-[#0F172A] group-hover:text-blue-700 transition-colors">
                      {report.name}
                    </p>
                    <p className="text-xs text-[#94A3B8] mt-0.5 leading-relaxed">
                      {report.description}
                    </p>
                  </div>
                  <ChevronDown
                    size={14}
                    className="text-[#CBD5E1] group-hover:text-blue-600 transition-colors mt-1 shrink-0"
                  />
                </button>
              );
            })}
          </div>
        )}

        {/* Back button when a report is active */}
        {activeReport && (
          <button
            onClick={() => setActiveReport(null)}
            className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#0F172A] transition-colors print:hidden"
          >
            <ChevronUp size={14} />
            All Reports
          </button>
        )}

        {/* Inline report viewer */}
        {activeReport && (
          <ReportViewer
            key={activeReport}
            reportId={activeReport}
            onClose={() => setActiveReport(null)}
          />
        )}
      </div>
    </>
  );
}

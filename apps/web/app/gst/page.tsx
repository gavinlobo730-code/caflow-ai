"use client";

/**
 * GST Module — Outward/Inward supplies, GSTR-1, GSTR-3B, TDS summary
 * CGST Act Section 37 (GSTR-1 — Outward Supplies)
 * CGST Act Section 39 (GSTR-3B — Monthly Return)
 * IT Act Section 194 (TDS deduction)
 * All amounts stored and computed in paise (integer arithmetic only).
 */

import { useState, useEffect, useCallback } from "react";
import {
  FileText,
  Plus,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InvoiceFormModal } from "@/components/InvoiceFormModal";
import { getClients } from "@/lib/data/clients";
import {
  getTransactions,
  getGSTSummary,
  type Transaction,
} from "@/lib/data/transactions";
import type { Client } from "@/lib/types";
import { formatPaise, formatDate } from "@/lib/services/formatting";

type GSTSummary = Awaited<ReturnType<typeof getGSTSummary>>;

// Indian financial year months (April → March)
const MONTHS = [
  "April", "May", "June", "July", "August", "September",
  "October", "November", "December", "January", "February", "March",
];

function getDefaultMonth() {
  const now = new Date();
  const m = now.getMonth() + 1;
  const y = now.getFullYear();
  return `${y}-${String(m).padStart(2, "0")}`;
}

/** Compute GSTR-1 due date (11th of following month) — CGST Act Section 37 */
function gstr1DueDate(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const next = new Date(y, m, 11); // month is 1-based; Date uses 0-based, so m = next month index
  return next.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** Compute GSTR-3B due date (20th of following month) — CGST Act Section 39 */
function gstr3bDueDate(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const next = new Date(y, m, 20);
  return next.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const TABS = ["GSTR-1", "GSTR-3B", "Invoices", "Purchases"] as const;

export default function GSTPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [month, setMonth] = useState(getDefaultMonth());
  const [activeTab, setActiveTab] = useState<0 | 1 | 2 | 3>(0);
  const [gstSummary, setGstSummary] = useState<GSTSummary | null>(null);
  const [invoices, setInvoices] = useState<Transaction[]>([]);
  const [purchases, setPurchases] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [invoiceType, setInvoiceType] = useState<"sales_invoice" | "purchase_invoice">("sales_invoice");

  useEffect(() => {
    getClients()
      .then((list) => {
        setClients(list);
        if (list.length > 0) setClientId(list[0].id);
      })
      .catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const [summary, inv, pur] = await Promise.all([
        getGSTSummary(clientId, month),
        getTransactions(clientId, "sales_invoice"),
        getTransactions(clientId, "purchase_invoice"),
      ]);
      setGstSummary(summary);
      // Filter invoices/purchases to the selected month
      const [y, m] = month.split("-");
      const prefix = `${y}-${m}`;
      setInvoices(inv.filter((t) => t.transaction_date.startsWith(prefix)));
      setPurchases(pur.filter((t) => t.transaction_date.startsWith(prefix)));
    } catch {
      // degrade silently
    } finally {
      setLoading(false);
    }
  }, [clientId, month]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function openModal(type: "sales_invoice" | "purchase_invoice") {
    setInvoiceType(type);
    setShowInvoiceModal(true);
  }

  const selectedClient = clients.find((c) => c.id === clientId);

  // Build month options for the current Indian financial year
  const now = new Date();
  const fyStart = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const monthOptions: { value: string; label: string }[] = [];
  for (let i = 0; i < 12; i++) {
    const mIdx = (i + 3) % 12; // April=3 → index 0
    const yr = i < 9 ? fyStart : fyStart + 1;
    const val = `${yr}-${String(mIdx + 1).padStart(2, "0")}`;
    monthOptions.push({ value: val, label: `${MONTHS[i]} ${yr}` });
  }

  const selectedMonthLabel = monthOptions.find((o) => o.value === month)?.label ?? month;
  const hasData = gstSummary !== null;
  const hasInvoices = invoices.length > 0;
  const hasPurchases = purchases.length > 0;

  // GSTR-3B net totals
  const netCGST = gstSummary ? gstSummary.gstr3b.net_cgst : 0;
  const netSGST = gstSummary ? gstSummary.gstr3b.net_sgst : 0;
  const netIGST = gstSummary ? gstSummary.gstr3b.net_igst : 0;
  const netTotal = netCGST + netSGST + netIGST;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">GST</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Returns &amp; transactions — FY {fyStart}-{String(fyStart + 1).slice(2)}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => openModal("purchase_invoice")}
            className="flex items-center gap-1.5 text-xs border border-gray-300 text-gray-700 px-3 py-1.5 rounded-md hover:bg-gray-50"
          >
            <Plus size={13} /> Purchase
          </button>
          <button
            onClick={() => openModal("sales_invoice")}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
          >
            <Plus size={13} /> Sales Invoice
          </button>
        </div>
      </div>

      {/* ── Client + Month selectors ── */}
      <div className="flex gap-3 flex-wrap items-center">
        <select
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 min-w-[200px]"
        >
          <option value="">— Select client —</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.client_name}
            </option>
          ))}
        </select>

        <select
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          {monthOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-2 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>

        {selectedClient && (
          <span className="text-xs text-gray-400 ml-1">
            GSTIN: <span className="font-mono">{selectedClient.gstin ?? "—"}</span>
          </span>
        )}
      </div>

      {/* ── Summary stat cards ── */}
      {hasData && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card className="border-gray-100">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp size={14} className="text-green-600" />
                <p className="text-xs text-gray-500">Output Tax</p>
              </div>
              <p className="text-lg font-bold text-gray-900">
                {formatPaise(
                  gstSummary!.gstr3b.output_cgst +
                  gstSummary!.gstr3b.output_sgst +
                  gstSummary!.gstr3b.output_igst
                )}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                on {formatPaise(gstSummary!.gstr1.taxable)} taxable
              </p>
            </CardContent>
          </Card>

          <Card className="border-gray-100">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingDown size={14} className="text-blue-600" />
                <p className="text-xs text-gray-500">Input Tax Credit</p>
              </div>
              <p className="text-lg font-bold text-gray-900">
                {formatPaise(
                  gstSummary!.gstr3b.itc_cgst +
                  gstSummary!.gstr3b.itc_sgst +
                  gstSummary!.gstr3b.itc_igst
                )}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                {purchases.length} purchase invoice{purchases.length !== 1 ? "s" : ""}
              </p>
            </CardContent>
          </Card>

          <Card className="border-gray-100">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Minus size={14} className="text-amber-600" />
                <p className="text-xs text-gray-500">Net GST Payable</p>
              </div>
              <p className={`text-lg font-bold ${netTotal > 0 ? "text-red-600" : "text-green-600"}`}>
                {formatPaise(netTotal)}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                {netTotal > 0 ? "payable" : "credit balance"}
              </p>
            </CardContent>
          </Card>

          <Card className="border-gray-100">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <FileText size={14} className="text-purple-600" />
                <p className="text-xs text-gray-500">TDS Deducted</p>
              </div>
              {/* IT Act Section 194 */}
              <p className="text-lg font-bold text-gray-900">
                {formatPaise(gstSummary!.tds_deducted)}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                {invoices.length} sales invoice{invoices.length !== 1 ? "s" : ""}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i as 0 | 1 | 2 | 3)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === i
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ══════════════════════════════════════════════════════════
          GSTR-1 TAB — Outward Supplies (CGST Act Section 37)
          Due: 11th of the following month
          CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
         ══════════════════════════════════════════════════════════ */}
      {activeTab === 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="text-sm font-semibold text-gray-900">
                  GSTR-1 — Outward Supplies
                </CardTitle>
                {/* CGST Act Section 37 */}
                <p className="text-xs text-gray-400 mt-0.5">
                  {selectedClient?.client_name} · {selectedMonthLabel}
                  {" · "}Due by {gstr1DueDate(month)}
                </p>
              </div>
              {/* CA REVIEW NOTE — filing must be done manually on GST portal */}
              <div className="flex items-center gap-1.5 bg-amber-50 border border-amber-200 text-amber-700 text-xs px-3 py-1.5 rounded-lg">
                <AlertTriangle size={12} />
                CA REVIEW REQUIRED — file manually on GST portal
              </div>
            </div>
          </CardHeader>

          <CardContent className="p-0">
            {loading ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400 animate-pulse">
                Loading…
              </div>
            ) : !clientId ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">
                Select a client to view GSTR-1 data.
              </div>
            ) : !hasData || invoices.length === 0 ? (
              <div className="px-5 py-10 text-center space-y-1">
                <FileText size={28} className="mx-auto text-gray-200" />
                <p className="text-sm text-gray-400">No outward supply transactions for {selectedMonthLabel}.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                {/* Per-invoice table — CGST Act Section 37 */}
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 text-xs text-gray-500 font-medium">
                      <th className="text-left px-4 py-3">Date</th>
                      <th className="text-left px-4 py-3">Party Name</th>
                      <th className="text-left px-4 py-3 font-mono">GSTIN</th>
                      <th className="text-right px-4 py-3">Taxable Amt</th>
                      <th className="text-right px-4 py-3">CGST</th>
                      <th className="text-right px-4 py-3">SGST</th>
                      <th className="text-right px-4 py-3">IGST</th>
                      <th className="text-right px-4 py-3">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {invoices.map((inv) => (
                      <tr key={inv.id} className="hover:bg-gray-50/60">
                        <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                          {formatDate(inv.transaction_date)}
                        </td>
                        <td className="px-4 py-3 text-gray-900">{inv.party_name}</td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-500">
                          {inv.party_gstin ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(inv.taxable_amount_paise)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(inv.cgst_paise)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(inv.sgst_paise)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(inv.igst_paise)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums font-semibold text-gray-900">
                          {formatPaise(inv.total_paise)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {/* Summary row */}
                  <tfoot>
                    <tr className="bg-gray-50 font-semibold text-gray-900 border-t border-gray-200">
                      <td colSpan={3} className="px-4 py-3 text-xs uppercase tracking-wide text-gray-600">
                        Total ({invoices.length} invoices)
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatPaise(gstSummary!.gstr1.taxable)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatPaise(gstSummary!.gstr1.cgst)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatPaise(gstSummary!.gstr1.sgst)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatPaise(gstSummary!.gstr1.igst)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-blue-700">
                        {formatPaise(gstSummary!.gstr1.total)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ══════════════════════════════════════════════════════════
          GSTR-3B TAB — Net Tax Liability (CGST Act Section 39)
          Due: 20th of the following month
          CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
         ══════════════════════════════════════════════════════════ */}
      {activeTab === 1 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="text-sm font-semibold text-gray-900">
                  GSTR-3B — Summary Return
                </CardTitle>
                {/* CGST Act Section 39 */}
                <p className="text-xs text-gray-400 mt-0.5">
                  {selectedClient?.client_name} · {selectedMonthLabel}
                  {" · "}Due by {gstr3bDueDate(month)}
                </p>
              </div>
              {/* CA REVIEW NOTE — filing must be done manually on GST portal */}
              <div className="flex items-center gap-1.5 bg-amber-50 border border-amber-200 text-amber-700 text-xs px-3 py-1.5 rounded-lg">
                <AlertTriangle size={12} />
                CA REVIEW REQUIRED — file manually on GST portal
              </div>
            </div>
          </CardHeader>

          <CardContent>
            {loading ? (
              <div className="py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
            ) : !clientId ? (
              <div className="py-8 text-center text-sm text-gray-400">Select a client to view GSTR-3B data.</div>
            ) : !hasData ? (
              <div className="py-8 text-center space-y-1">
                <FileText size={28} className="mx-auto text-gray-200" />
                <p className="text-sm text-gray-400">No transactions for {selectedMonthLabel}.</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* 3-column grid — CGST Act Section 39 */}
                <div className="grid grid-cols-3 gap-1 text-sm">
                  {/* Header row */}
                  <div className="bg-gray-50 px-4 py-2 text-xs font-medium text-gray-500 rounded-tl-lg" />
                  <div className="bg-gray-50 px-4 py-2 text-xs font-medium text-gray-500 text-right">CGST</div>
                  <div className="bg-gray-50 px-4 py-2 text-xs font-medium text-gray-500 text-right rounded-tr-lg">SGST / IGST</div>

                  {/* Output Tax */}
                  <div className="bg-green-50 px-4 py-3 font-medium text-gray-700 flex items-center gap-2">
                    <TrendingUp size={13} className="text-green-600 shrink-0" />
                    Output Tax
                  </div>
                  <div className="bg-green-50 px-4 py-3 text-right tabular-nums text-gray-900 font-medium">
                    {formatPaise(gstSummary!.gstr3b.output_cgst)}
                  </div>
                  <div className="bg-green-50 px-4 py-3 text-right tabular-nums text-gray-900 font-medium">
                    {formatPaise(gstSummary!.gstr3b.output_sgst + gstSummary!.gstr3b.output_igst)}
                  </div>

                  {/* ITC */}
                  <div className="bg-blue-50 px-4 py-3 font-medium text-gray-700 flex items-center gap-2">
                    <TrendingDown size={13} className="text-blue-600 shrink-0" />
                    Input Tax Credit
                  </div>
                  <div className="bg-blue-50 px-4 py-3 text-right tabular-nums text-green-700 font-medium">
                    − {formatPaise(gstSummary!.gstr3b.itc_cgst)}
                  </div>
                  <div className="bg-blue-50 px-4 py-3 text-right tabular-nums text-green-700 font-medium">
                    − {formatPaise(gstSummary!.gstr3b.itc_sgst + gstSummary!.gstr3b.itc_igst)}
                  </div>

                  {/* Net Payable */}
                  <div className="bg-gray-100 px-4 py-3 font-semibold text-gray-800 flex items-center gap-2 rounded-bl-lg">
                    <Minus size={13} className="text-amber-600 shrink-0" />
                    Net Payable
                  </div>
                  <div className={`bg-gray-100 px-4 py-3 text-right tabular-nums font-bold ${netCGST > 0 ? "text-red-600" : "text-green-600"}`}>
                    {formatPaise(netCGST)}
                  </div>
                  <div className={`bg-gray-100 px-4 py-3 text-right tabular-nums font-bold rounded-br-lg ${(netSGST + netIGST) > 0 ? "text-red-600" : "text-green-600"}`}>
                    {formatPaise(netSGST + netIGST)}
                  </div>
                </div>

                {/* Grand total banner */}
                <div className={`flex items-center justify-between rounded-xl px-5 py-4 ${netTotal > 0 ? "bg-red-50 border border-red-100" : "bg-green-50 border border-green-100"}`}>
                  <div>
                    <p className="text-xs text-gray-500 mb-0.5">Grand Total Net GST Payable</p>
                    <p className={`text-xl font-bold ${netTotal > 0 ? "text-red-700" : "text-green-700"}`}>
                      {formatPaise(netTotal)}
                    </p>
                  </div>
                  <p className="text-xs text-gray-400 text-right max-w-[200px]">
                    {netTotal > 0
                      ? `Payable by ${gstr3bDueDate(month)}`
                      : "Credit balance — carry forward"}
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ══════════════════════════════════════════════════════════
          INVOICES TAB — Sales invoices list
         ══════════════════════════════════════════════════════════ */}
      {activeTab === 2 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-gray-900">
                Sales Invoices — {selectedMonthLabel}
              </CardTitle>
              <button
                onClick={() => openModal("sales_invoice")}
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
              >
                <Plus size={12} /> New Invoice
              </button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
            ) : !hasInvoices ? (
              <div className="px-5 py-10 text-center space-y-1">
                <FileText size={28} className="mx-auto text-gray-200" />
                <p className="text-sm text-gray-400">No sales invoices for {selectedMonthLabel}.</p>
                <button
                  onClick={() => openModal("sales_invoice")}
                  className="mt-2 text-xs text-blue-600 hover:underline"
                >
                  Add sales invoice
                </button>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {invoices.map((inv) => (
                  <div key={inv.id} className="flex items-center gap-4 px-5 py-3.5">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900">{inv.party_name}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {formatDate(inv.transaction_date)}
                        {inv.reference_no ? ` · ${inv.reference_no}` : ""}
                        {inv.party_gstin ? ` · ${inv.party_gstin}` : ""}
                      </p>
                    </div>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
                        inv.status === "posted"
                          ? "bg-green-100 text-green-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {inv.status}
                    </span>
                    <p className="text-sm font-semibold tabular-nums text-gray-700 shrink-0">
                      {formatPaise(inv.total_paise)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ══════════════════════════════════════════════════════════
          PURCHASES TAB — Purchase invoices list
         ══════════════════════════════════════════════════════════ */}
      {activeTab === 3 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-gray-900">
                Purchase Invoices — {selectedMonthLabel}
              </CardTitle>
              <button
                onClick={() => openModal("purchase_invoice")}
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
              >
                <Plus size={12} /> New Purchase
              </button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
            ) : !hasPurchases ? (
              <div className="px-5 py-10 text-center space-y-1">
                <FileText size={28} className="mx-auto text-gray-200" />
                <p className="text-sm text-gray-400">No purchase invoices for {selectedMonthLabel}.</p>
                <button
                  onClick={() => openModal("purchase_invoice")}
                  className="mt-2 text-xs text-blue-600 hover:underline"
                >
                  Add purchase invoice
                </button>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {purchases.map((pur) => (
                  <div key={pur.id} className="flex items-center gap-4 px-5 py-3.5">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900">{pur.party_name}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {formatDate(pur.transaction_date)}
                        {pur.reference_no ? ` · ${pur.reference_no}` : ""}
                        {pur.party_gstin ? ` · ${pur.party_gstin}` : ""}
                      </p>
                    </div>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
                        pur.status === "posted"
                          ? "bg-green-100 text-green-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {pur.status}
                    </span>
                    <p className="text-sm font-semibold tabular-nums text-gray-700 shrink-0">
                      {formatPaise(pur.total_paise)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── TDS Deducted card (IT Act Section 194) ── always visible when data loaded */}
      {hasData && (
        <Card className="border-purple-100">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <FileText size={14} className="text-purple-600" />
              TDS Deducted — {selectedMonthLabel}
            </CardTitle>
            {/* IT Act Section 194 */}
            <p className="text-xs text-gray-400">IT Act Section 194 — deducted on purchase invoices</p>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-purple-700">
                  {formatPaise(gstSummary!.tds_deducted)}
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Across {purchases.length} purchase invoice{purchases.length !== 1 ? "s" : ""}
                </p>
              </div>
              <div className="text-xs text-gray-400 text-right max-w-[240px]">
                TDS return (26Q) due 31st of month following quarter end.
                {" "}Verify deductions before filing.
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Invoice modal */}
      {showInvoiceModal && (
        <InvoiceFormModal
          open={showInvoiceModal}
          clients={clients}
          type={invoiceType}
          onClose={() => setShowInvoiceModal(false)}
          onSaved={() => {
            setShowInvoiceModal(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

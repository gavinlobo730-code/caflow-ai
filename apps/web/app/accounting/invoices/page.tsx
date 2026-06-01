"use client";

/**
 * Invoices / GST Transactions page
 * All amounts stored and computed in paise (integer arithmetic only).
 * CGST Act Section 31: Tax Invoice requirements
 * CGST Act Section 37: Outward Supplies (GSTR-1)
 * CGST Act Section 39: Monthly Return (GSTR-3B)
 * IT Act Section 194: TDS deduction
 */

import { useState, useEffect, useCallback } from "react";
import {
  Plus,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  FileText,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { InvoiceFormModal } from "@/components/InvoiceFormModal";
import { getClients } from "@/lib/data/clients";
import { getTransactions, type Transaction } from "@/lib/data/transactions";
import type { Client } from "@/lib/types";
import { formatPaise, formatDate } from "@/lib/services/formatting";

// ─── Filter types ────────────────────────────────────────────────────────────
type FilterType = "all" | "sales_invoice" | "purchase_invoice" | "this_month" | "this_quarter";

const FILTER_LABELS: Record<FilterType, string> = {
  all: "All",
  sales_invoice: "Sales Invoices",
  purchase_invoice: "Purchase Invoices",
  this_month: "This Month",
  this_quarter: "This Quarter",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
/** Returns YYYY-MM-DD prefix for current month */
function thisMonthPrefix(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Returns start and end YYYY-MM-DD for the current Indian financial quarter.
 * Quarters: Apr–Jun, Jul–Sep, Oct–Dec, Jan–Mar
 */
function thisQuarterRange(): { from: string; to: string } {
  const now = new Date();
  const m = now.getMonth() + 1; // 1-based
  const y = now.getFullYear();
  let qStart: number, qEnd: number, qYear: number;
  if (m >= 4 && m <= 6) { qStart = 4; qEnd = 6; qYear = y; }
  else if (m >= 7 && m <= 9) { qStart = 7; qEnd = 9; qYear = y; }
  else if (m >= 10 && m <= 12) { qStart = 10; qEnd = 12; qYear = y; }
  else { qStart = 1; qEnd = 3; qYear = y; }
  return {
    from: `${qYear}-${String(qStart).padStart(2, "0")}-01`,
    to:   `${qYear}-${String(qEnd).padStart(2, "0")}-31`,
  };
}

/** Compute GST total (CGST + SGST + IGST) for a transaction */
function gstTotal(t: Transaction): number {
  return t.cgst_paise + t.sgst_paise + t.igst_paise;
}

// ─── Main component ────────────────────────────────────────────────────────────
export default function InvoicesPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState<"sales_invoice" | "purchase_invoice">("sales_invoice");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Load clients on mount
  useEffect(() => {
    getClients().catch(() => {}).then((list) => {
      if (list) setClients(list);
    });
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const txns = await getTransactions(); // all clients, all types
      setAllTransactions(txns);
    } catch {
      // degrade silently
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function openModal(type: "sales_invoice" | "purchase_invoice") {
    setModalType(type);
    setShowModal(true);
  }

  // ─── Filtering ──────────────────────────────────────────────────────────────
  const filtered: Transaction[] = allTransactions.filter((t) => {
    switch (filter) {
      case "sales_invoice":
        return t.transaction_type === "sales_invoice";
      case "purchase_invoice":
        return t.transaction_type === "purchase_invoice";
      case "this_month":
        return t.transaction_date.startsWith(thisMonthPrefix());
      case "this_quarter": {
        const { from, to } = thisQuarterRange();
        return t.transaction_date >= from && t.transaction_date <= to;
      }
      default:
        return true;
    }
  });

  // ─── Summary bar (always based on this month across all transactions) ────────
  // CGST Act Section 37 — outward supplies; Section 49 — net GST liability
  const monthPrefix = thisMonthPrefix();
  const monthTxns = allTransactions.filter((t) => t.transaction_date.startsWith(monthPrefix));
  const monthSales = monthTxns.filter((t) => t.transaction_type === "sales_invoice");
  const monthPurchases = monthTxns.filter((t) => t.transaction_type === "purchase_invoice");

  const totalSalesPaise    = monthSales.reduce((s, t) => s + t.total_paise, 0);
  const totalPurchasesPaise = monthPurchases.reduce((s, t) => s + t.total_paise, 0);

  // Net GST liability = output GST − ITC (integer paise arithmetic — CGST Act Section 49)
  const outputGST = monthSales.reduce((s, t) => s + gstTotal(t), 0);
  const itcGST    = monthPurchases.reduce((s, t) => s + gstTotal(t), 0);
  const netGST    = outputGST - itcGST;

  const now = new Date();
  const monthLabel = now.toLocaleDateString("en-IN", { month: "long", year: "numeric" });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Invoices</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            GST transactions — sales &amp; purchase invoices
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => openModal("purchase_invoice")}
            className="flex items-center gap-1.5 text-xs border border-gray-300 text-gray-700 px-3 py-1.5 rounded-md hover:bg-gray-50 transition-colors"
          >
            <Plus size={13} /> New Purchase
          </button>
          <button
            onClick={() => openModal("sales_invoice")}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700 transition-colors"
          >
            <Plus size={13} /> New Invoice
          </button>
        </div>
      </div>

      {/* ── Summary bar — This Month ── */}
      {/* CGST Act Section 37 (output), Section 49 (net liability) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Card className="border-green-100">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp size={14} className="text-green-600" />
              <p className="text-xs text-gray-500">Total Sales — {monthLabel}</p>
            </div>
            <p className="text-xl font-bold text-gray-900">{formatPaise(totalSalesPaise)}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {monthSales.length} invoice{monthSales.length !== 1 ? "s" : ""}
            </p>
          </CardContent>
        </Card>

        <Card className="border-blue-100">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingDown size={14} className="text-blue-600" />
              <p className="text-xs text-gray-500">Total Purchases — {monthLabel}</p>
            </div>
            <p className="text-xl font-bold text-gray-900">{formatPaise(totalPurchasesPaise)}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {monthPurchases.length} invoice{monthPurchases.length !== 1 ? "s" : ""}
            </p>
          </CardContent>
        </Card>

        <Card className={netGST > 0 ? "border-red-100" : "border-green-100"}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Minus size={14} className="text-amber-600" />
              <p className="text-xs text-gray-500">Net GST Liability — {monthLabel}</p>
            </div>
            {/* CGST Act Section 49 — net GST = output tax − ITC */}
            <p className={`text-xl font-bold ${netGST > 0 ? "text-red-600" : "text-green-600"}`}>
              {formatPaise(netGST)}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              {netGST > 0 ? "payable" : "credit balance"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── Filter bar ── */}
      <div className="flex items-center gap-1 flex-wrap">
        {(Object.keys(FILTER_LABELS) as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
        <button
          onClick={refresh}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* ── Transactions table ── */}
      <Card>
        <div className="overflow-x-auto">
          {loading ? (
            <div className="px-5 py-12 text-center text-sm text-gray-400 animate-pulse">
              Loading transactions…
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-5 py-12 text-center space-y-2">
              <FileText size={32} className="mx-auto text-gray-200" />
              <p className="text-sm text-gray-400">No transactions found.</p>
              <div className="flex items-center justify-center gap-2 mt-2">
                <button
                  onClick={() => openModal("sales_invoice")}
                  className="text-xs text-blue-600 hover:underline"
                >
                  + New Invoice
                </button>
                <span className="text-gray-300">·</span>
                <button
                  onClick={() => openModal("purchase_invoice")}
                  className="text-xs text-blue-600 hover:underline"
                >
                  + New Purchase
                </button>
              </div>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs text-gray-500 font-medium border-b border-gray-100">
                  <th className="w-8" />
                  <th className="text-left px-4 py-3">Date</th>
                  <th className="text-left px-4 py-3">Type</th>
                  <th className="text-left px-4 py-3">Party Name</th>
                  <th className="text-left px-4 py-3 font-mono">GSTIN</th>
                  <th className="text-left px-4 py-3">Ref No</th>
                  <th className="text-right px-4 py-3">Taxable Amt</th>
                  <th className="text-right px-4 py-3">GST</th>
                  <th className="text-right px-4 py-3">Total</th>
                  <th className="text-left px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((txn) => {
                  const isExpanded = expandedId === txn.id;
                  const isSales = txn.transaction_type === "sales_invoice";
                  return (
                    <>
                      <tr
                        key={txn.id}
                        onClick={() => setExpandedId(isExpanded ? null : txn.id)}
                        className="hover:bg-gray-50/60 cursor-pointer transition-colors"
                      >
                        {/* Expand toggle */}
                        <td className="pl-3 pr-1 py-3 text-gray-400">
                          {isExpanded
                            ? <ChevronDown size={14} />
                            : <ChevronRight size={14} />}
                        </td>
                        <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                          {formatDate(txn.transaction_date)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${
                              isSales
                                ? "bg-green-100 text-green-700"
                                : "bg-blue-100 text-blue-700"
                            }`}
                          >
                            {isSales ? "Sales" : "Purchase"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-900 font-medium">
                          {txn.party_name}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-500">
                          {txn.party_gstin ?? "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-500">
                          {txn.reference_no ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(txn.taxable_amount_paise)}
                        </td>
                        {/* GST = CGST + SGST + IGST (all integer paise — CGST Act Section 31) */}
                        <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                          {formatPaise(gstTotal(txn))}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums font-semibold text-gray-900">
                          {formatPaise(txn.total_paise)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`text-xs px-2 py-0.5 rounded-full ${
                              txn.status === "posted"
                                ? "bg-green-100 text-green-700"
                                : "bg-amber-100 text-amber-700"
                            }`}
                          >
                            {txn.status}
                          </span>
                        </td>
                      </tr>

                      {/* ── Expanded detail row ── */}
                      {isExpanded && (
                        <tr key={`${txn.id}-detail`} className="bg-blue-50/40">
                          <td colSpan={10} className="px-8 py-4">
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                              <div>
                                <p className="text-gray-500 mb-0.5">Type</p>
                                <p className="font-medium text-gray-900">
                                  {isSales ? "Sales Invoice" : "Purchase Invoice"}
                                </p>
                              </div>
                              <div>
                                <p className="text-gray-500 mb-0.5">Place of Supply</p>
                                <p className="font-medium text-gray-900">
                                  {txn.place_of_supply ?? "—"}
                                  {txn.is_interstate && (
                                    <span className="ml-1 text-orange-600">(Interstate)</span>
                                  )}
                                </p>
                              </div>
                              <div>
                                <p className="text-gray-500 mb-0.5">CGST</p>
                                <p className="font-mono text-gray-900">{formatPaise(txn.cgst_paise)}</p>
                              </div>
                              <div>
                                <p className="text-gray-500 mb-0.5">SGST</p>
                                <p className="font-mono text-gray-900">{formatPaise(txn.sgst_paise)}</p>
                              </div>
                              <div>
                                <p className="text-gray-500 mb-0.5">IGST</p>
                                <p className="font-mono text-gray-900">{formatPaise(txn.igst_paise)}</p>
                              </div>
                              {/* TDS — IT Act Section 194 */}
                              {txn.tds_paise > 0 && (
                                <div>
                                  <p className="text-gray-500 mb-0.5">TDS ({txn.tds_section})</p>
                                  <p className="font-mono text-gray-900">{formatPaise(txn.tds_paise)}</p>
                                </div>
                              )}
                              {txn.notes && (
                                <div className="col-span-2">
                                  <p className="text-gray-500 mb-0.5">Notes</p>
                                  <p className="text-gray-700">{txn.notes}</p>
                                </div>
                              )}
                              <div>
                                <p className="text-gray-500 mb-0.5">Created</p>
                                <p className="text-gray-700">{formatDate(txn.created_at)}</p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Row count footer */}
        {!loading && filtered.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-50 text-xs text-gray-400 flex items-center justify-between">
            <span>
              {filtered.length} transaction{filtered.length !== 1 ? "s" : ""}
            </span>
            <span className="tabular-nums">
              Total: {formatPaise(filtered.reduce((s, t) => s + t.total_paise, 0))}
            </span>
          </div>
        )}
      </Card>

      {/* ── Invoice modal ── */}
      {showModal && (
        <InvoiceFormModal
          open={showModal}
          clients={clients}
          type={modalType}
          onClose={() => setShowModal(false)}
          onSaved={() => {
            setShowModal(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

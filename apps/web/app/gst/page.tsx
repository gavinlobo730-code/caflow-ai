"use client";

import { useState, useEffect, useCallback } from "react";
import { FileText, Plus, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { InvoiceFormModal } from "@/components/InvoiceFormModal";
import { getClients } from "@/lib/data/clients";
import { getTransactions, getGSTSummary, type Transaction } from "@/lib/data/transactions";
import type { Client } from "@/lib/types";
import { formatPaise, formatDate } from "@/lib/services/formatting";

type GSTSummary = Awaited<ReturnType<typeof getGSTSummary>>;

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

const TABS = ["GSTR-1", "GSTR-3B", "Invoices", "Purchases"];

export default function GSTPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [month, setMonth] = useState(getDefaultMonth());
  const [activeTab, setActiveTab] = useState(0);
  const [gstSummary, setGstSummary] = useState<GSTSummary | null>(null);
  const [invoices, setInvoices] = useState<Transaction[]>([]);
  const [purchases, setPurchases] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [invoiceType, setInvoiceType] = useState<"sales_invoice" | "purchase_invoice">("sales_invoice");

  useEffect(() => {
    getClients().then((list) => {
      setClients(list);
      if (list.length > 0) setClientId(list[0].id);
    }).catch(() => {});
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
      setInvoices(inv);
      setPurchases(pur);
    } catch {
      // degrade silently
    } finally {
      setLoading(false);
    }
  }, [clientId, month]);

  useEffect(() => { refresh(); }, [refresh]);

  function openModal(type: "sales_invoice" | "purchase_invoice") {
    setInvoiceType(type);
    setShowInvoiceModal(true);
  }

  const selectedClient = clients.find(c => c.id === clientId);

  // Build month selector options for current FY
  const now = new Date();
  const fyStart = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const monthOptions: { value: string; label: string }[] = [];
  for (let i = 0; i < 12; i++) {
    const mIdx = (i + 3) % 12;
    const yr = i < 9 ? fyStart : fyStart + 1;
    const val = `${yr}-${String(mIdx + 1).padStart(2, "0")}`;
    monthOptions.push({ value: val, label: `${MONTHS[i]} ${yr}` });
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">GST</h1>
          <p className="text-sm text-gray-500 mt-0.5">Returns & transactions — FY {fyStart}-{String(fyStart + 1).slice(2)}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => openModal("purchase_invoice")}
            className="flex items-center gap-1.5 text-xs border border-gray-300 text-gray-700 px-3 py-1.5 rounded-md hover:bg-gray-50">
            <Plus size={13} /> Purchase
          </button>
          <button onClick={() => openModal("sales_invoice")}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700">
            <Plus size={13} /> Sales Invoice
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <select value={clientId} onChange={e => setClientId(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 min-w-[180px]">
          <option value="">All clients</option>
          {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
        </select>
        <select value={month} onChange={e => setMonth(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
          {monthOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button onClick={refresh} disabled={loading}
          className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-2 rounded-lg hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {/* Summary cards */}
      {gstSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp size={14} className="text-green-600" />
              <p className="text-xs text-gray-500">Output Tax</p>
            </div>
            <p className="text-lg font-bold text-gray-900">{formatPaise(gstSummary.gstr3b.output_cgst + gstSummary.gstr3b.output_sgst + gstSummary.gstr3b.output_igst)}</p>
            <p className="text-xs text-gray-400 mt-0.5">on {formatPaise(gstSummary.gstr1.taxable)} taxable</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingDown size={14} className="text-blue-600" />
              <p className="text-xs text-gray-500">Input Tax Credit</p>
            </div>
            <p className="text-lg font-bold text-gray-900">{formatPaise(gstSummary.gstr3b.itc_cgst + gstSummary.gstr3b.itc_sgst + gstSummary.gstr3b.itc_igst)}</p>
            <p className="text-xs text-gray-400 mt-0.5">{purchases.length} purchase invoices</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Minus size={14} className="text-amber-600" />
              <p className="text-xs text-gray-500">Net GST Payable</p>
            </div>
            {(() => {
              const net = gstSummary.gstr3b.net_cgst + gstSummary.gstr3b.net_sgst + gstSummary.gstr3b.net_igst;
              return <>
                <p className={`text-lg font-bold ${net > 0 ? "text-red-600" : "text-green-600"}`}>{formatPaise(net)}</p>
                <p className="text-xs text-gray-400 mt-0.5">{net > 0 ? "payable" : "credit balance"}</p>
              </>;
            })()}
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText size={14} className="text-purple-600" />
              <p className="text-xs text-gray-500">TDS Deducted</p>
            </div>
            <p className="text-lg font-bold text-gray-900">{formatPaise(gstSummary.tds_deducted)}</p>
            <p className="text-xs text-gray-400 mt-0.5">{invoices.length} sales invoices</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* GSTR-1 tab */}
      {activeTab === 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">GSTR-1 — Outward Supplies</h2>
            {selectedClient && <p className="text-xs text-gray-400 mt-0.5">{selectedClient.client_name} · {monthOptions.find(o => o.value === month)?.label}</p>}
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
          ) : gstSummary ? (
            <div className="divide-y divide-gray-50">
              <div className="grid grid-cols-3 gap-4 px-5 py-4 bg-gray-50 text-xs font-medium text-gray-500">
                <span>Description</span><span className="text-right">Taxable Value</span><span className="text-right">Tax Amount</span>
              </div>
              <div className="grid grid-cols-3 gap-4 px-5 py-3 text-sm">
                <span className="text-gray-700">Intrastate Supplies (CGST + SGST)</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.taxable - gstSummary.gstr1.igst)}</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.cgst + gstSummary.gstr1.sgst)}</span>
              </div>
              <div className="grid grid-cols-3 gap-4 px-5 py-3 text-sm">
                <span className="text-gray-700">Interstate Supplies (IGST)</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.igst > 0 ? gstSummary.gstr1.taxable : 0)}</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.igst)}</span>
              </div>
              <div className="grid grid-cols-3 gap-4 px-5 py-3 text-sm font-semibold bg-gray-50">
                <span>Total</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.taxable)}</span>
                <span className="text-right tabular-nums">{formatPaise(gstSummary.gstr1.total - gstSummary.gstr1.taxable)}</span>
              </div>
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-sm text-gray-400">Select a client to view GSTR-1 data</div>
          )}
        </div>
      )}

      {/* GSTR-3B tab */}
      {activeTab === 1 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">GSTR-3B — Summary Return</h2>
            {selectedClient && <p className="text-xs text-gray-400 mt-0.5">{selectedClient.client_name} · {monthOptions.find(o => o.value === month)?.label}</p>}
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
          ) : gstSummary ? (
            <div className="divide-y divide-gray-50">
              <div className="px-5 py-3.5 flex justify-between text-sm"><span className="text-gray-600">3.1 Outward taxable supplies</span><span className="tabular-nums font-medium">{formatPaise(gstSummary.gstr1.taxable)}</span></div>
              <div className="px-5 py-3.5 flex justify-between text-sm"><span className="text-gray-600">3.1 Output tax (CGST+SGST+IGST)</span><span className="tabular-nums font-medium">{formatPaise(gstSummary.gstr3b.output_cgst + gstSummary.gstr3b.output_sgst + gstSummary.gstr3b.output_igst)}</span></div>
              <div className="px-5 py-3.5 flex justify-between text-sm"><span className="text-gray-600">4 Input Tax Credit (ITC)</span><span className="tabular-nums font-medium text-green-600">- {formatPaise(gstSummary.gstr3b.itc_cgst + gstSummary.gstr3b.itc_sgst + gstSummary.gstr3b.itc_igst)}</span></div>
              {(() => {
                const net = gstSummary.gstr3b.net_cgst + gstSummary.gstr3b.net_sgst + gstSummary.gstr3b.net_igst;
                return (
                  <div className="px-5 py-3.5 flex justify-between text-sm font-semibold bg-gray-50">
                    <span>Net GST Payable</span>
                    <span className={`tabular-nums ${net > 0 ? "text-red-600" : "text-green-600"}`}>{formatPaise(net)}</span>
                  </div>
                );
              })()}
              <div className="px-5 py-4 text-xs text-gray-400 bg-amber-50 border-t border-amber-100">
                ⚠ Review figures before filing. CGST Act Section 39 — GSTR-3B due 20th of following month.
                {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
              </div>
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-sm text-gray-400">Select a client to view GSTR-3B data</div>
          )}
        </div>
      )}

      {/* Invoices tab */}
      {activeTab === 2 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Sales Invoices</h2>
            <button onClick={() => openModal("sales_invoice")}
              className="flex items-center gap-1 text-xs text-blue-600 hover:underline">
              <Plus size={12} /> New Invoice
            </button>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
          ) : invoices.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No sales invoices yet</div>
          ) : (
            <div className="divide-y divide-gray-50">
              {invoices.map(inv => (
                <div key={inv.id} className="flex items-center gap-4 px-5 py-3.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900">{inv.party_name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{formatDate(inv.transaction_date)} · {inv.reference_no}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${inv.status === "posted" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                    {inv.status}
                  </span>
                  <p className="text-sm font-semibold tabular-nums text-gray-700 shrink-0">{formatPaise(inv.total_paise)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Purchases tab */}
      {activeTab === 3 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Purchase Invoices</h2>
            <button onClick={() => openModal("purchase_invoice")}
              className="flex items-center gap-1 text-xs text-blue-600 hover:underline">
              <Plus size={12} /> New Purchase
            </button>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
          ) : purchases.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No purchase invoices yet</div>
          ) : (
            <div className="divide-y divide-gray-50">
              {purchases.map(pur => (
                <div key={pur.id} className="flex items-center gap-4 px-5 py-3.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900">{pur.party_name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{formatDate(pur.transaction_date)} · {pur.reference_no}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${pur.status === "posted" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                    {pur.status}
                  </span>
                  <p className="text-sm font-semibold tabular-nums text-gray-700 shrink-0">{formatPaise(pur.total_paise)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showInvoiceModal && (
        <InvoiceFormModal
          open={showInvoiceModal}
          clients={clients}
          type={invoiceType}
          onClose={() => setShowInvoiceModal(false)}
          onSaved={() => { setShowInvoiceModal(false); refresh(); }}
        />
      )}
    </div>
  );
}

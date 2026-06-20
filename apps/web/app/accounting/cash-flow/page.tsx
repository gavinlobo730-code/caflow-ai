"use client";

/**
 * Cash Flow Statement — Indirect Method (AS-3, Companies Act 2013 Schedule III).
 *
 * Presentation layer ONLY. All classification (operating / investing / financing)
 * and money arithmetic happen server-side in the reporting engine — this page
 * fetches GET /api/accounting/cash-flow and renders the response. Zero business
 * logic in the frontend (CLAUDE.md).
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, TrendingUp, TrendingDown, Minus, Download, AlertTriangle } from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ─── Types (mirror the backend response) ──────────────────────────────────────

interface CashFlowLine {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  account_subtype: string | null;
  amount_paise: number;
}

interface CashFlowSection {
  label: string;
  lines: CashFlowLine[];
  total_paise: number;
}

interface CashFlowStatement {
  start_date: string;
  end_date: string;
  basis?: string;
  operating: CashFlowSection;
  investing: CashFlowSection;
  financing: CashFlowSection;
  net_change_paise: number;
  opening_cash_paise: number;
  closing_cash_paise: number;
  reconciles: boolean;
}

type CashFlowResponse = { success: boolean; data: CashFlowStatement | null; error: string | null };

interface Client { id: string; client_name: string }

// Indian Financial Year selector — April 1 to March 31
const FY_LIST = [
  { label: "FY 2025-26", start: "2025-04-01", end: "2026-03-31" },
  { label: "FY 2024-25", start: "2024-04-01", end: "2025-03-31" },
  { label: "FY 2023-24", start: "2023-04-01", end: "2024-03-31" },
];

const SECTION_TITLES: Record<keyof Pick<CashFlowStatement, "operating" | "investing" | "financing">, string> = {
  operating: "A. Cash from Operating Activities",
  investing: "B. Cash from Investing Activities",
  financing: "C. Cash from Financing Activities",
};

// ─── Section Component ────────────────────────────────────────────────────────

function CashFlowSectionBlock({ title, section }: { title: string; section: CashFlowSection }) {
  const isPositive = section.total_paise >= 0;
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className={`px-5 py-3 border-b border-gray-50 flex items-center justify-between ${isPositive ? "bg-green-50/50" : "bg-red-50/50"}`}>
        <h3 className="text-sm font-semibold text-[#0F172A]">{title}</h3>
        <div className="flex items-center gap-1.5">
          {isPositive ? <TrendingUp className="w-4 h-4 text-green-600" /> : <TrendingDown className="w-4 h-4 text-red-600" />}
          <span className={`text-sm font-bold ${isPositive ? "text-green-700" : "text-red-700"}`}>
            {formatPaise(Math.abs(section.total_paise))}
          </span>
        </div>
      </div>
      {section.lines.length === 0 ? (
        <div className="px-5 py-4 text-xs text-[#94A3B8]">No transactions in this category for selected period</div>
      ) : (
        <table className="w-full text-sm">
          <tbody className="divide-y divide-[#F8FAFC]">
            {section.lines.map((item) => (
              <tr key={item.account_id} className="hover:bg-[#F8FAFC]/30">
                <td className="px-5 py-2.5 text-xs text-[#334155]">{item.account_name}</td>
                <td className={`px-5 py-2.5 text-xs font-medium text-right ${item.amount_paise >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {item.amount_paise >= 0 ? "+" : ""}{formatPaise(item.amount_paise)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-[#E2E8F0] bg-[#F8FAFC]">
              <td className="px-5 py-2.5 text-xs font-semibold text-[#334155]">Net Cash</td>
              <td className={`px-5 py-2.5 text-sm font-bold text-right ${isPositive ? "text-green-700" : "text-red-700"}`}>
                {formatPaise(section.total_paise)}
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CashFlowPage() {
  const [selectedFY, setSelectedFY] = useState(0);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [cf, setCf] = useState<CashFlowStatement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fy = FY_LIST[selectedFY];

  // A cash flow statement is per-entity. Each client — including the practice
  // itself, which is modelled as a client record — keeps its own books, so this
  // page requires an explicit client selection and NEVER aggregates across the
  // firm. (Per-client cash flow also lives in the client workspace, under
  // Accounting → Cash Flow; this firm-level page is a convenience entry point.)
  useEffect(() => {
    let cancelled = false;
    async function loadClients() {
      try {
        const sb = getSupabaseClient();
        const firmId = await getFirmId();
        const { data } = await sb.from("clients").select("id, client_name").eq("firm_id", firmId).order("client_name");
        if (cancelled) return;
        const list = (data ?? []) as Client[];
        setClients(list);
        if (list.length > 0) setSelectedClientId((prev) => prev || list[0].id);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load clients");
      }
    }
    loadClients();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedClientId) { setCf(null); return; }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        // AS-3 cash flow is computed entirely server-side (CLAUDE.md): the page
        // passes the period + client and renders the authoritative response.
        const res = (await api.accounting.cashFlow({
          start_date: fy.start,
          end_date: fy.end,
          client_id: selectedClientId,
          basis: "accrual",
        })) as CashFlowResponse;
        if (!res.success || !res.data) throw new Error(res.error ?? "Failed to load cash flow statement");
        if (!cancelled) setCf(res.data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load data");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [fy.start, fy.end, selectedClientId]);

  function exportCsv() {
    if (!cf) return;
    const sectionRows = (key: "operating" | "investing" | "financing") => {
      const s = cf[key];
      return [
        ...s.lines.map((l) => [SECTION_TITLES[key], l.account_name, String(Math.round(l.amount_paise / 100))]),
        [SECTION_TITLES[key], `Net ${s.label}`, String(Math.round(s.total_paise / 100))],
      ];
    };
    const rows = [
      ["Section", "Item", "Amount (₹)"],
      ...sectionRows("operating"),
      ...sectionRows("investing"),
      ...sectionRows("financing"),
      ["Summary", "Opening Cash", String(Math.round(cf.opening_cash_paise / 100))],
      ["Summary", "Net Change in Cash", String(Math.round(cf.net_change_paise / 100))],
      ["Summary", "Closing Cash", String(Math.round(cf.closing_cash_paise / 100))],
    ];
    const csv = rows.map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
    const clientName = clients.find((c) => c.id === selectedClientId)?.client_name ?? "client";
    const a = document.createElement("a");
    a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    a.download = `cash-flow-${clientName.replace(/\s/g, "-")}-${fy.label.replace(/\s/g, "-")}.csv`;
    a.click();
  }

  const netChange = cf?.net_change_paise ?? 0;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Cash Flow Statement</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Per client · Indirect method — AS-3, Companies Act 2013 Schedule III</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 max-w-[200px]"
            value={selectedClientId}
            onChange={e => setSelectedClientId(e.target.value)}
          >
            {clients.length === 0 && <option value="">Loading clients…</option>}
            {clients.map((c) => <option key={c.id} value={c.id}>{c.client_name}</option>)}
          </select>
          <select
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={selectedFY}
            onChange={e => setSelectedFY(Number(e.target.value))}
          >
            {FY_LIST.map((f, i) => <option key={f.label} value={i}>{f.label}</option>)}
          </select>
          <button
            onClick={exportCsv}
            disabled={!cf}
            className="flex items-center gap-1.5 border border-[#E2E8F0] text-[#475569] text-sm px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" /> Export
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {!loading && !selectedClientId ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">
          Select a client to view its cash flow statement. Each entity&apos;s books are reported separately — figures are never aggregated across the firm.
        </div>
      ) : loading || !cf ? (
        <div className="space-y-4">
          {[1, 2, 3].map(i => <div key={i} className="h-32 bg-[#F1F5F9] rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {/* Summary bar */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Operating Activities", paise: cf.operating.total_paise, color: "text-blue-700" },
                { label: "Investing Activities", paise: cf.investing.total_paise, color: "text-purple-700" },
                { label: "Financing Activities", paise: cf.financing.total_paise, color: "text-orange-700" },
                { label: "Net Cash Change", paise: netChange, color: netChange >= 0 ? "text-green-700" : "text-red-700" },
              ].map(s => (
                <div key={s.label} className="text-center">
                  <p className="text-xs text-[#94A3B8] mb-1">{s.label}</p>
                  <p className={`text-sm font-bold ${s.color}`}>{formatPaise(s.paise)}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Opening / Closing Cash */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div>
                <p className="text-xs text-[#94A3B8]">Opening Cash Balance</p>
                <p className="text-sm font-semibold text-[#0F172A]">{formatPaise(cf.opening_cash_paise)}</p>
              </div>
              <Minus className="w-4 h-4 text-[#CBD5E1]" />
              <div>
                <p className="text-xs text-[#94A3B8]">Net Change</p>
                <p className={`text-sm font-semibold ${netChange >= 0 ? "text-green-700" : "text-red-700"}`}>{netChange >= 0 ? "+" : ""}{formatPaise(netChange)}</p>
              </div>
              <Minus className="w-4 h-4 text-[#CBD5E1]" />
              <div>
                <p className="text-xs text-[#94A3B8]">Closing Cash Balance</p>
                <p className="text-sm font-semibold text-[#0F172A]">{formatPaise(cf.closing_cash_paise)}</p>
              </div>
            </div>
            <p className="text-[10px] text-[#94A3B8]">FY: Apr {fy.start.slice(0, 4)} — Mar {fy.end.slice(0, 4)}</p>
          </div>

          {!cf.reconciles && (
            <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 text-xs text-amber-700 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              Cash flow does not reconcile to the change in cash balances for this period. Please review the ledger.
            </div>
          )}

          {/* Three sections */}
          <CashFlowSectionBlock title={SECTION_TITLES.operating} section={cf.operating} />
          <CashFlowSectionBlock title={SECTION_TITLES.investing} section={cf.investing} />
          <CashFlowSectionBlock title={SECTION_TITLES.financing} section={cf.financing} />

          <p className="text-[10px] text-[#94A3B8] text-center">
            Prepared using indirect method per AS-3 (Accounting Standard on Cash Flow Statements) and Companies Act 2013 Schedule III.
          </p>
        </>
      )}
    </div>
  );
}

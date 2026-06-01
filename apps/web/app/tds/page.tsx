"use client";

/**
 * TDS Module — Tax Deducted at Source tracking
 * IT Act Section 200: TDS deposit and return filing obligations
 * IT Act Section 194: TDS deduction thresholds and rates
 */

import { useState, useEffect } from "react";
import { IndianRupee, Calendar, Users, AlertCircle, CheckCircle, Clock, X } from "lucide-react";
import { getTransactions, type Transaction } from "@/lib/data/transactions";
import { getClients } from "@/lib/data/clients";
import { formatPaise } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";

// TDS section descriptions — IT Act Chapter XVII-B
const TDS_SECTIONS: Record<string, { label: string; rates: string }> = {
  "194C": { label: "Contractor Payments", rates: "1%/2%" },
  "194J": { label: "Professional/Technical Fees", rates: "10%" },
  "194I": { label: "Rent", rates: "10%" },
  "194H": { label: "Commission", rates: "5%" },
  "194A": { label: "Interest", rates: "10%" },
};

// Quarter definitions — Indian Financial Year (April to March)
const QUARTERS = [
  { label: "Q1", period: "Apr–Jun", months: [3, 4, 5], dueDay: 31, dueMonth: "Jul" },
  { label: "Q2", period: "Jul–Sep", months: [6, 7, 8], dueDay: 31, dueMonth: "Oct" },
  { label: "Q3", period: "Oct–Dec", months: [9, 10, 11], dueDay: 31, dueMonth: "Jan" },
  { label: "Q4", period: "Jan–Mar", months: [0, 1, 2], dueDay: 31, dueMonth: "May" },
];

/** Determine which quarter a date belongs to — IT Act Section 200 */
function getQuarterForDate(date: Date): number {
  const m = date.getMonth(); // 0=Jan ... 11=Dec
  if (m >= 3 && m <= 5) return 0; // Q1: Apr-Jun
  if (m >= 6 && m <= 8) return 1; // Q2: Jul-Sep
  if (m >= 9 && m <= 11) return 2; // Q3: Oct-Dec
  return 3;                         // Q4: Jan-Mar
}

/** Get financial year label for a date */
function getFYForDate(date: Date): string {
  const y = date.getFullYear();
  const m = date.getMonth();
  if (m >= 3) return `${y}-${String(y + 1).slice(2)}`; // Apr onwards = current FY
  return `${y - 1}-${String(y).slice(2)}`;
}

// Static challan tracker data (UI only — no backend yet)
interface ChallanRow {
  id: string;
  quarter: string;
  period: string;
  fy: string;
  amountPaise: number;
  challanNo: string | null;
  dateDeposited: string | null;
  status: "Pending" | "Deposited" | "Overdue";
  dueDate: string;
}

const TODAY = new Date("2026-06-01");

function buildChallanRows(tdsTransactions: Transaction[]): ChallanRow[] {
  // Group by FY + quarter
  const map = new Map<string, number>();
  for (const t of tdsTransactions) {
    const d = new Date(t.transaction_date);
    const fy = getFYForDate(d);
    const qi = getQuarterForDate(d);
    const key = `${fy}-Q${qi + 1}`;
    map.set(key, (map.get(key) ?? 0) + t.tds_paise);
  }

  const rows: ChallanRow[] = [];
  const fys = ["2024-25", "2025-26"];
  for (const fy of fys) {
    QUARTERS.forEach((q, qi) => {
      const key = `${fy}-${q.label}`;
      const amount = map.get(key) ?? 0;
      if (amount === 0) return; // skip quarters with no TDS

      // Calculate due date for deposit — IT Act Section 200(1)
      const [fyStart] = fy.split("-");
      const fyStartYear = parseInt(fyStart);
      let dueYear = fyStartYear + (qi >= 3 ? 1 : 0);
      if (qi === 3) dueYear = fyStartYear + 1; // Q4 due in May of next year
      const dueDate = `${q.dueDay} ${q.dueMonth} ${dueYear}`;
      const dueDateObj = new Date(`${dueYear}-${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].indexOf(q.dueMonth) + 1}-${q.dueDay}`);

      rows.push({
        id: key,
        quarter: q.label,
        period: q.period,
        fy,
        amountPaise: amount,
        challanNo: null,
        dateDeposited: null,
        status: TODAY > dueDateObj ? "Overdue" : "Pending",
        dueDate,
      });
    });
  }

  return rows;
}

interface ChallanModalProps {
  row: ChallanRow;
  onClose: () => void;
  onSave: (id: string, challanNo: string) => void;
}

function ChallanModal({ row, onClose, onSave }: ChallanModalProps) {
  const [challan, setChallan] = useState("");
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Mark as Deposited</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-xs text-gray-500">
          {row.quarter} FY {row.fy} — {row.period} · {formatPaise(row.amountPaise)}
        </p>
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Challan Number (BSR/OLTAS)</label>
          <input
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. OLTAS/2026/001234"
            value={challan}
            onChange={e => setChallan(e.target.value)}
          />
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50">Cancel</button>
          <button
            disabled={!challan.trim()}
            onClick={() => { onSave(row.id, challan.trim()); onClose(); }}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            Save
          </button>
        </div>
        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          Verify challan on TRACES portal before marking deposited.
        </p>
      </div>
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  Pending: "bg-amber-100 text-amber-700",
  Deposited: "bg-green-100 text-green-700",
  Overdue: "bg-red-100 text-red-700",
  Filed: "bg-green-100 text-green-700",
  Draft: "bg-gray-100 text-gray-600",
};

const TABS = ["TDS Deductions", "Challan Tracker", "26Q Return Status"];

export default function TDSPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [challanRows, setChallanRows] = useState<ChallanRow[]>([]);
  const [modalRow, setModalRow] = useState<ChallanRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [txns, cls] = await Promise.all([getTransactions(), getClients()]);
        // Filter to TDS transactions only
        const tdsTxns = txns.filter(t => t.tds_paise > 0);
        setTransactions(tdsTxns);
        setClients(cls);
        setChallanRows(buildChallanRows(tdsTxns));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load TDS data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Summary calculations — current quarter (Q1 FY 2025-26: Apr-Jun 2025)
  // IT Act Section 200: deposit TDS by 7th of following month (or 30 Apr for March)
  const currentQi = getQuarterForDate(TODAY);
  const currentQ = QUARTERS[currentQi];
  const currentFY = getFYForDate(TODAY);

  const thisQuarterTxns = transactions.filter(t => {
    const d = new Date(t.transaction_date);
    return getQuarterForDate(d) === currentQi && getFYForDate(d) === currentFY;
  });

  const tdsThisQuarterPaise = thisQuarterTxns.reduce((s, t) => s + t.tds_paise, 0);
  const tdsDepositedPaise = challanRows
    .filter(r => r.status === "Deposited" && r.quarter === currentQ.label && r.fy === currentFY)
    .reduce((s, r) => s + r.amountPaise, 0);
  const tdsPayablePaise = Math.max(0, tdsThisQuarterPaise - tdsDepositedPaise);

  const clientsWithTDS = new Set(thisQuarterTxns.map(t => t.client_id)).size;

  // Next due date — IT Act Section 200
  const nextDueDate = `31 ${currentQ.dueMonth}`;

  function handleMarkDeposited(id: string, challanNo: string) {
    setChallanRows(rows => rows.map(r =>
      r.id === id ? { ...r, challanNo, dateDeposited: TODAY.toISOString().slice(0, 10), status: "Deposited" as const } : r
    ));
  }

  // Build 26Q return status rows
  const returnRows = [
    { fy: "2024-25", quarter: "Q1", period: "Apr–Jun 2024", dueDate: "31 Jul 2024", status: "Filed" as const },
    { fy: "2024-25", quarter: "Q2", period: "Jul–Sep 2024", dueDate: "31 Oct 2024", status: "Filed" as const },
    { fy: "2024-25", quarter: "Q3", period: "Oct–Dec 2024", dueDate: "31 Jan 2025", status: "Filed" as const },
    { fy: "2024-25", quarter: "Q4", period: "Jan–Mar 2025", dueDate: "31 May 2025", status: "Filed" as const },
    { fy: "2025-26", quarter: "Q1", period: "Apr–Jun 2025", dueDate: "31 Jul 2025", status: "Filed" as const },
    { fy: "2025-26", quarter: "Q2", period: "Jul–Sep 2025", dueDate: "31 Oct 2025", status: "Filed" as const },
    { fy: "2025-26", quarter: "Q3", period: "Oct–Dec 2025", dueDate: "31 Jan 2026", status: "Filed" as const },
    { fy: "2025-26", quarter: "Q4", period: "Jan–Mar 2026", dueDate: "31 May 2026", status: "Pending" as const },
    { fy: "2026-27", quarter: "Q1", period: "Apr–Jun 2026", dueDate: "31 Jul 2026", status: "Pending" as const },
  ];

  const clientMap = new Map(clients.map(c => [c.id, c]));

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">TDS</h1>
        <p className="text-sm text-gray-500 mt-0.5">Tax Deducted at Source — IT Act Chapter XVII-B</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <IndianRupee className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-gray-500">TDS Deducted This Quarter</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : formatPaise(tdsThisQuarterPaise)}</p>
          <p className="text-xs text-gray-400 mt-0.5">{currentQ.label} {currentQ.period} · FY {currentFY}</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-gray-500">TDS Payable</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : formatPaise(tdsPayablePaise)}</p>
          <p className="text-xs text-gray-400 mt-0.5">Not yet deposited</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
              <Calendar className="w-4 h-4 text-purple-600" />
            </div>
            <span className="text-xs text-gray-500">Next Due Date</span>
          </div>
          {/* IT Act Section 200 — TDS deposit due date */}
          <p className="text-lg font-semibold text-gray-900">{nextDueDate}</p>
          <p className="text-xs text-gray-400 mt-0.5">IT Act Section 200</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <Users className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-gray-500">Clients with TDS</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : clientsWithTDS}</p>
          <p className="text-xs text-gray-400 mt-0.5">This quarter</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab: TDS Deductions */}
      {activeTab === 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">TDS Deductions</h2>
            <p className="text-xs text-gray-400 mt-0.5">Transactions where TDS was deducted — IT Act Section 194</p>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">Loading...</div>
          ) : transactions.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No TDS transactions found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Date</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Client</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Party Name</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Section</th>
                    <th className="text-right text-xs font-medium text-gray-400 px-3 py-3">Taxable Amt</th>
                    <th className="text-right text-xs font-medium text-gray-400 px-3 py-3">TDS Rate</th>
                    <th className="text-right text-xs font-medium text-gray-400 px-3 py-3">TDS Amount</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {transactions.map(t => {
                    const client = clientMap.get(t.client_id);
                    const section = t.tds_section ?? "—";
                    const sectionInfo = TDS_SECTIONS[section];
                    // TDS rate derived: tds_paise / taxable * 100
                    const tdsRate = t.taxable_amount_paise > 0
                      ? ((t.tds_paise / t.taxable_amount_paise) * 100).toFixed(1) + "%"
                      : sectionInfo?.rates ?? "—";
                    return (
                      <tr key={t.id} className="hover:bg-gray-50/50">
                        <td className="px-5 py-3 text-xs text-gray-500 whitespace-nowrap">
                          {new Date(t.transaction_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                        </td>
                        <td className="px-3 py-3">
                          <p className="text-sm font-medium text-gray-900">{client?.client_name ?? "—"}</p>
                          {client?.pan && <p className="text-[10px] font-mono text-gray-400">{client.pan}</p>}
                        </td>
                        <td className="px-3 py-3 text-sm text-gray-600 max-w-[180px] truncate">{t.party_name}</td>
                        <td className="px-3 py-3">
                          {section !== "—" ? (
                            <div>
                              <span className="text-xs font-mono font-medium text-blue-700">{section}</span>
                              {sectionInfo && <p className="text-[10px] text-gray-400">{sectionInfo.label}</p>}
                            </div>
                          ) : <span className="text-gray-400">—</span>}
                        </td>
                        <td className="px-3 py-3 text-right text-sm text-gray-900">{formatPaise(t.taxable_amount_paise)}</td>
                        <td className="px-3 py-3 text-right text-xs text-gray-600">{tdsRate}</td>
                        <td className="px-3 py-3 text-right text-sm font-medium text-gray-900">{formatPaise(t.tds_paise)}</td>
                        <td className="px-5 py-3">
                          <span className={`status-pill ${STATUS_STYLE[t.status] ?? "bg-gray-100 text-gray-600"}`}>
                            {t.status}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-gray-100 bg-gray-50/50">
                    <td colSpan={4} className="px-5 py-3 text-xs font-medium text-gray-500">Total</td>
                    <td className="px-3 py-3 text-right text-sm font-semibold text-gray-900">
                      {formatPaise(transactions.reduce((s, t) => s + t.taxable_amount_paise, 0))}
                    </td>
                    <td></td>
                    <td className="px-3 py-3 text-right text-sm font-semibold text-gray-900">
                      {formatPaise(transactions.reduce((s, t) => s + t.tds_paise, 0))}
                    </td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab: Challan Tracker */}
      {activeTab === 1 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">Challan Tracker</h2>
            <p className="text-xs text-gray-400 mt-0.5">Track TDS deposit challans — IT Act Section 200(1)</p>
          </div>
          {challanRows.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No challan data — add transactions with TDS to see challans</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Quarter</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Period</th>
                    <th className="text-right text-xs font-medium text-gray-400 px-3 py-3">Amount</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Challan No</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Date Deposited</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Due Date</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Status</th>
                    <th className="px-3 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {challanRows.map(row => (
                    <tr key={row.id} className="hover:bg-gray-50/50">
                      <td className="px-5 py-3">
                        <span className="text-sm font-medium text-gray-900">{row.quarter}</span>
                        <span className="text-xs text-gray-400 ml-1">FY {row.fy}</span>
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-600">{row.period}</td>
                      <td className="px-3 py-3 text-right text-sm font-medium text-gray-900">{formatPaise(row.amountPaise)}</td>
                      <td className="px-3 py-3 text-xs font-mono text-gray-600">{row.challanNo ?? <span className="text-gray-300">—</span>}</td>
                      <td className="px-3 py-3 text-xs text-gray-600">{row.dateDeposited ?? <span className="text-gray-300">—</span>}</td>
                      <td className="px-3 py-3 text-xs text-gray-600">{row.dueDate}</td>
                      <td className="px-5 py-3">
                        <span className={`status-pill ${STATUS_STYLE[row.status]}`}>{row.status}</span>
                      </td>
                      <td className="px-3 py-3">
                        {row.status !== "Deposited" && (
                          <button
                            onClick={() => setModalRow(row)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
                          >
                            Mark Deposited
                          </button>
                        )}
                        {row.status === "Deposited" && (
                          <CheckCircle className="w-4 h-4 text-green-500" />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
            <p className="text-[10px] text-gray-400">
              Quarters: Q1 (Apr–Jun) due 31 Jul · Q2 (Jul–Sep) due 31 Oct · Q3 (Oct–Dec) due 31 Jan · Q4 (Jan–Mar) due 31 May — IT Act Section 200
            </p>
          </div>
        </div>
      )}

      {/* Tab: 26Q Return Status */}
      {activeTab === 2 && (
        <div className="space-y-4">
          {/* CA Review notice */}
          <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 flex gap-2">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800">CA Review Required</p>
              <p className="text-xs text-amber-700 mt-0.5">
                File 26Q returns manually on the TRACES portal (traces.gov.in). CAflow does not auto-submit to any government portal.
              </p>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">26Q Return Status</h2>
              <p className="text-xs text-gray-400 mt-0.5">Quarterly TDS returns for non-salary payments — IT Act Section 200(3)</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">FY</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Quarter</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Period</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Due Date</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {returnRows.map((r, i) => {
                    const dueDateObj = new Date(r.dueDate.replace(/(\d+) (\w+) (\d+)/, "$2 $1, $3"));
                    const isOverdue = TODAY > dueDateObj && r.status === "Pending";
                    const displayStatus = isOverdue ? "Overdue" : r.status;
                    return (
                      <tr key={i} className="hover:bg-gray-50/50">
                        <td className="px-5 py-3 text-xs font-medium text-gray-600">FY {r.fy}</td>
                        <td className="px-3 py-3 text-sm font-medium text-gray-900">{r.quarter}</td>
                        <td className="px-3 py-3 text-xs text-gray-600">{r.period}</td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-1.5">
                            <Clock className="w-3 h-3 text-gray-300" />
                            <span className="text-xs text-gray-600">{r.dueDate}</span>
                          </div>
                        </td>
                        <td className="px-5 py-3">
                          <span className={`status-pill ${STATUS_STYLE[displayStatus] ?? "bg-gray-100 text-gray-600"}`}>
                            {displayStatus}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
              <p className="text-[10px] text-gray-400">
                26Q due date: 31st of month following quarter end — IT Act Section 200(3). File on TRACES portal after CA review.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Challan Modal */}
      {modalRow && (
        <ChallanModal
          row={modalRow}
          onClose={() => setModalRow(null)}
          onSave={handleMarkDeposited}
        />
      )}
    </div>
  );
}

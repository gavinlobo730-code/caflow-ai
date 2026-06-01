"use client";
export const runtime = "edge";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Trash2, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { JournalEntry, EntryType, AccountType } from "@/lib/types";

const ENTRY_TYPES: EntryType[] = ["Sales", "Purchase", "Payment", "Receipt", "Journal", "Contra", "Opening"];

const ACCOUNTS: { id: string; name: string; type: AccountType }[] = [
  { id: "acc-001", name: "Cash in Hand", type: "Asset" },
  { id: "acc-002", name: "Bank — HDFC Current Account", type: "Asset" },
  { id: "acc-003", name: "Trade Receivables", type: "Asset" },
  { id: "acc-004", name: "GST Input Tax Credit", type: "Asset" },
  { id: "acc-008", name: "Trade Payables", type: "Liability" },
  { id: "acc-009", name: "GST Output Tax Payable", type: "Liability" },
  { id: "acc-010", name: "TDS Payable", type: "Liability" },
  { id: "acc-013", name: "Capital Account", type: "Equity" },
  { id: "acc-015", name: "Professional Fees — GST Clients", type: "Income" },
  { id: "acc-016", name: "Professional Fees — ITR Clients", type: "Income" },
  { id: "acc-017", name: "Audit Fees", type: "Income" },
  { id: "acc-018", name: "Salary Expense", type: "Expense" },
  { id: "acc-019", name: "Office Rent", type: "Expense" },
  { id: "acc-020", name: "Software Subscriptions", type: "Expense" },
  { id: "acc-021", name: "Bank Charges", type: "Expense" },
];

const MOCK_ENTRIES: JournalEntry[] = [
  { id: "je-001", client_id: "c-001", entry_date: "2025-04-01", reference_no: "OB/2025-26/001", narration: "Opening balance — capital introduced by partner", entry_type: "Opening", status: "posted", lines: [], total_debit_paise: 50000000, total_credit_paise: 50000000, created_at: "2025-04-01T09:00:00+05:30" },
  { id: "je-002", client_id: "c-001", entry_date: "2025-04-05", reference_no: "INV/2025-26/001", narration: "Professional fees — GST filing for Sharma Enterprises", entry_type: "Receipt", status: "posted", lines: [], total_debit_paise: 1180000, total_credit_paise: 1180000, created_at: "2025-04-05T10:00:00+05:30" },
  { id: "je-003", client_id: "c-001", entry_date: "2025-04-05", reference_no: "EXP/2025-26/001", narration: "Office rent — MG Road, April 2025", entry_type: "Payment", status: "posted", lines: [], total_debit_paise: 3500000, total_credit_paise: 3500000, created_at: "2025-04-05T11:00:00+05:30" },
  { id: "je-004", client_id: "c-001", entry_date: "2025-04-30", reference_no: "SAL/2025-26/001", narration: "Salary payment — April 2025", entry_type: "Payment", status: "posted", lines: [], total_debit_paise: 5000000, total_credit_paise: 5000000, created_at: "2025-04-30T17:00:00+05:30" },
  { id: "je-005", client_id: "c-005", entry_date: "2025-05-10", reference_no: "INV/2025-26/002", narration: "ITR filing fees — Joshi Textiles", entry_type: "Sales", status: "posted", lines: [], total_debit_paise: 2360000, total_credit_paise: 2360000, created_at: "2025-05-10T10:00:00+05:30" },
  { id: "je-006", client_id: "c-005", entry_date: "2025-05-15", reference_no: "REC/2025-26/001", narration: "Receipt from Joshi Textiles — ITR fees", entry_type: "Receipt", status: "posted", lines: [], total_debit_paise: 2360000, total_credit_paise: 2360000, created_at: "2025-05-15T12:00:00+05:30" },
  { id: "je-007", client_id: "c-001", entry_date: "2025-05-20", reference_no: "GST/2025-26/001", narration: "GST payment — April 2025 GSTR-3B", entry_type: "Payment", status: "posted", lines: [], total_debit_paise: 540000, total_credit_paise: 540000, created_at: "2025-05-20T14:00:00+05:30" },
  { id: "je-008", client_id: "c-001", entry_date: "2025-05-01", reference_no: "EXP/2025-26/002", narration: "Software subscription — Winman, Tally", entry_type: "Payment", status: "posted", lines: [], total_debit_paise: 500000, total_credit_paise: 500000, created_at: "2025-05-01T09:00:00+05:30" },
  { id: "je-009", client_id: "c-002", entry_date: "2025-05-25", reference_no: "INV/2025-26/003", narration: "Audit fees — Patel & Sons FY 2024-25", entry_type: "Sales", status: "draft", lines: [], total_debit_paise: 3540000, total_credit_paise: 3540000, created_at: "2025-05-25T10:00:00+05:30" },
  { id: "je-010", client_id: "c-001", entry_date: "2025-05-31", reference_no: "BNK/2025-26/001", narration: "Bank charges — HDFC May 2025", entry_type: "Journal", status: "posted", lines: [], total_debit_paise: 50000, total_credit_paise: 50000, created_at: "2025-05-31T18:00:00+05:30" },
];

const statusBadge: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  draft: "bg-amber-100 text-amber-700",
};

type NewLine = { account_id: string; debit_paise: number; credit_paise: number; narration: string };

function emptyLine(): NewLine {
  return { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" };
}

export default function JournalPage() {
  const [showForm, setShowForm] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [lines, setLines] = useState<NewLine[]>([emptyLine(), emptyLine()]);
  const [formData, setFormData] = useState({ entry_date: "", reference_no: "", narration: "", entry_type: "Journal" as EntryType });

  const totalDebit: number = lines.reduce((sum, l) => sum + (Number(l.debit_paise) || 0), 0);
  const totalCredit: number = lines.reduce((sum, l) => sum + (Number(l.credit_paise) || 0), 0);
  const isBalanced = totalDebit === totalCredit && totalDebit > 0;
  const diff: number = totalDebit - totalCredit;

  const filtered = MOCK_ENTRIES.filter((e) => {
    if (startDate && e.entry_date < startDate) return false;
    if (endDate && e.entry_date > endDate) return false;
    return true;
  });

  function addLine() {
    setLines([...lines, emptyLine()]);
  }

  function removeLine(idx: number) {
    setLines(lines.filter((_, i) => i !== idx));
  }

  function updateLine(idx: number, field: keyof NewLine, value: string | number) {
    setLines(lines.map((l, i) => i === idx ? { ...l, [field]: value } : l));
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Journal Entries</h1>
          <p className="text-sm text-gray-500 mt-0.5">{MOCK_ENTRIES.length} entries</p>
        </div>
        <button
          onClick={() => { setShowForm(true); setSelectedEntry(null); }}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          <Plus size={13} /> New Entry
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div>
          <label className="text-xs text-gray-500">From</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-gray-500">To</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Entry list */}
      <Card>
        <div className="divide-y divide-gray-50">
          <div className="grid grid-cols-12 gap-2 px-5 py-2 text-xs font-semibold text-gray-400 border-b border-gray-100">
            <span className="col-span-2">Date</span>
            <span className="col-span-2">Reference</span>
            <span className="col-span-4">Narration</span>
            <span className="col-span-1">Type</span>
            <span className="col-span-1">Status</span>
            <span className="col-span-2 text-right">Debit</span>
          </div>
          {filtered.map((entry) => (
            <button key={entry.id} onClick={() => { setSelectedEntry(entry); setShowForm(false); }}
              className="w-full grid grid-cols-12 gap-2 px-5 py-3 text-left hover:bg-gray-50 transition-colors">
              <span className="col-span-2 text-xs text-gray-600">{formatDate(entry.entry_date)}</span>
              <span className="col-span-2 text-xs font-mono text-gray-500 truncate">{entry.reference_no}</span>
              <span className="col-span-4 text-sm text-gray-900 truncate">{entry.narration}</span>
              <span className="col-span-1 text-xs text-gray-500">{entry.entry_type}</span>
              <span className="col-span-1">
                <Badge className={`text-xs ${statusBadge[entry.status]}`}>{entry.status}</Badge>
              </span>
              <span className="col-span-2 text-sm font-semibold tabular-nums text-right text-gray-700">
                {formatPaise(entry.total_debit_paise)}
              </span>
            </button>
          ))}
        </div>
      </Card>

      {/* Entry detail panel */}
      {selectedEntry && !showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between">
              <span>{selectedEntry.narration}</span>
              <button onClick={() => setSelectedEntry(null)} className="text-xs text-gray-400 hover:text-gray-600">Close</button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-3 text-xs text-gray-500 mb-4">
              <div><span className="block font-medium text-gray-700">Date</span>{formatDate(selectedEntry.entry_date)}</div>
              <div><span className="block font-medium text-gray-700">Reference</span>{selectedEntry.reference_no || "—"}</div>
              <div><span className="block font-medium text-gray-700">Type</span>{selectedEntry.entry_type}</div>
              <div><span className="block font-medium text-gray-700">Status</span>
                <span className={`px-2 py-0.5 rounded-full ${statusBadge[selectedEntry.status]}`}>{selectedEntry.status}</span>
              </div>
            </div>
            <p className="text-xs text-gray-500 mb-3">Lines (mock — fetched from API in production)</p>
            <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3">
              Total Debit: <span className="font-semibold text-gray-900">{formatPaise(selectedEntry.total_debit_paise)}</span>
              {" | "}
              Total Credit: <span className="font-semibold text-gray-900">{formatPaise(selectedEntry.total_credit_paise)}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* New Entry Form */}
      {showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">New Journal Entry</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="text-xs text-gray-500">Date *</label>
                <input type="date" value={formData.entry_date}
                  onChange={(e) => setFormData({ ...formData, entry_date: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="text-xs text-gray-500">Reference No.</label>
                <input value={formData.reference_no}
                  onChange={(e) => setFormData({ ...formData, reference_no: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. INV/2025-26/004" />
              </div>
              <div>
                <label className="text-xs text-gray-500">Entry Type</label>
                <select value={formData.entry_type}
                  onChange={(e) => setFormData({ ...formData, entry_type: e.target.value as EntryType })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {ENTRY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="md:col-span-1 col-span-2">
                <label className="text-xs text-gray-500">Narration *</label>
                <input value={formData.narration}
                  onChange={(e) => setFormData({ ...formData, narration: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Description of entry" />
              </div>
            </div>

            {/* Lines */}
            <div>
              <div className="grid grid-cols-12 gap-2 text-xs font-semibold text-gray-400 mb-1">
                <span className="col-span-4">Account</span>
                <span className="col-span-3">Debit (₹)</span>
                <span className="col-span-3">Credit (₹)</span>
                <span className="col-span-1">Narration</span>
                <span className="col-span-1"></span>
              </div>
              {lines.map((line, idx) => (
                <div key={idx} className="grid grid-cols-12 gap-2 mb-2 items-center">
                  <div className="col-span-4">
                    <select value={line.account_id}
                      onChange={(e) => updateLine(idx, "account_id", e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500">
                      <option value="">Select account…</option>
                      {ACCOUNTS.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                  </div>
                  <div className="col-span-3">
                    <input type="number" min={0} value={line.debit_paise || ""}
                      onChange={(e) => updateLine(idx, "debit_paise", parseInt(e.target.value) || 0)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="0" />
                  </div>
                  <div className="col-span-3">
                    <input type="number" min={0} value={line.credit_paise || ""}
                      onChange={(e) => updateLine(idx, "credit_paise", parseInt(e.target.value) || 0)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="0" />
                  </div>
                  <div className="col-span-1">
                    <input value={line.narration}
                      onChange={(e) => updateLine(idx, "narration", e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="Note" />
                  </div>
                  <div className="col-span-1 flex justify-center">
                    {lines.length > 2 && (
                      <button onClick={() => removeLine(idx)} className="text-red-400 hover:text-red-600">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
              <button onClick={addLine} className="text-xs text-blue-600 hover:underline mt-1">+ Add line</button>
            </div>

            {/* Balance indicator */}
            <div className={`flex items-center gap-2 text-sm px-3 py-2 rounded-lg ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
              {isBalanced
                ? <><CheckCircle size={15} /> Balanced ✓ — {formatPaise(totalDebit)}</>
                : <><XCircle size={15} /> Unbalanced ✗ (Diff: {formatPaise(Math.abs(diff))})</>
              }
            </div>

            <div className="flex gap-2">
              <button onClick={() => setShowForm(false)} className="text-sm text-gray-600 border border-gray-200 px-4 py-1.5 rounded-md hover:bg-gray-50">
                Cancel
              </button>
              <button className="text-sm border border-blue-300 text-blue-700 px-4 py-1.5 rounded-md hover:bg-blue-50">
                Save as Draft
              </button>
              <button
                disabled={!isBalanced}
                className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Post Entry
              </button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Trash2, CheckCircle, XCircle, Info, Upload } from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";

const JOURNAL_IMPORT_COLUMNS = [
  { key: "entry_date",    label: "Entry Date",    required: true,  hint: "YYYY-MM-DD e.g. 2025-04-01" },
  { key: "narration",     label: "Narration",     required: true,  hint: "Description of the transaction" },
  { key: "reference_no",  label: "Reference No",  required: false, hint: "e.g. INV-001 or Bill-22" },
  { key: "entry_type",    label: "Entry Type",    required: false, hint: "Sales | Purchase | Payment | Receipt | Journal | Contra | Opening" },
  { key: "account_code",  label: "Account Code",  required: true,  hint: "From Chart of Accounts e.g. 1001" },
  { key: "debit_rs",      label: "Debit (₹)",     required: false, hint: "Amount in rupees e.g. 10000" },
  { key: "credit_rs",     label: "Credit (₹)",    required: false, hint: "Amount in rupees e.g. 10000" },
];
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { JournalEntry, EntryType, Account } from "@/lib/types";

const ENTRY_TYPES: EntryType[] = ["Sales", "Purchase", "Payment", "Receipt", "Journal", "Contra", "Opening"];

// Supported foreign currencies (ISO 4217 codes)
const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY"] as const;
type Currency = (typeof CURRENCIES)[number];

const CURRENCY_SYMBOLS: Record<Currency, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
  AED: "د.إ",
  SGD: "S$",
  JPY: "¥",
};

const statusBadge: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  draft: "bg-amber-100 text-amber-700",
};

type NewLine = { account_id: string; debit_paise: number; credit_paise: number; narration: string };

function emptyLine(): NewLine {
  return { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" };
}

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-100 rounded w-48" />
      <div className="h-64 bg-[#F1F5F9] rounded-xl" />
    </div>
  );
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

/**
 * Format a forex display string for the journal entry list.
 * e.g. "USD 1,000 @ 83.50 = ₹83,500"
 */
function formatForexDisplay(
  currency: string,
  foreignAmount: number,
  exchangeRate: number,
  inrPaise: number,
): string {
  const sym = CURRENCY_SYMBOLS[currency as Currency] ?? currency;
  const fmtForeign = foreignAmount.toLocaleString("en-IN");
  const fmtRate = exchangeRate.toFixed(2);
  const inrRupees = Math.round(inrPaise / 100).toLocaleString("en-IN");
  return `${sym}${fmtForeign} @ ${fmtRate} = ₹${inrRupees}`;
}

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [lines, setLines] = useState<NewLine[]>([emptyLine(), emptyLine()]);
  const [formData, setFormData] = useState({
    entry_date: "",
    reference_no: "",
    narration: "",
    entry_type: "Journal" as EntryType,
    // Multi-currency fields
    currency: "INR" as Currency,
    exchange_rate: "",          // string for controlled input; rate per 1 foreign unit in INR
    foreign_amount: "",         // string for controlled input
  });
  const [submitting, setSubmitting] = useState(false);
  const [firmId, setFirmId] = useState<string | null>(null);

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        setFirmId(fid);
        const [{ data: je }, { data: acc }] = await Promise.all([
          sb.from("journal_entries").select("*").eq("firm_id", fid).order("entry_date", { ascending: false }),
          sb.from("accounts").select("*").eq("firm_id", fid).order("account_name"),
        ]);
        setEntries((je ?? []) as JournalEntry[]);
        setAccounts((acc ?? []) as Account[]);
      })
      .catch((e) => setError(e.message ?? "Failed to load data"))
      .finally(() => setLoading(false));
  }, []);

  // ── Derived forex conversion ─────────────────────────────────────────────
  // Integer paise arithmetic — no floating point (per CGST Act best-practice).
  // Formula: foreign_amount × exchange_rate × 100 (converted to integer paise)
  const isForex = formData.currency !== "INR";
  const parsedForeignAmount = parseFloat(formData.foreign_amount) || 0;
  const parsedExchangeRate = parseFloat(formData.exchange_rate) || 0;
  // Multiply then round to integer paise — never store fractional paise
  const convertedInrPaise = isForex
    ? Math.round(parsedForeignAmount * parsedExchangeRate * 100)
    : 0;

  const totalDebit: number = lines.reduce((sum, l) => sum + (Number(l.debit_paise) || 0), 0);
  const totalCredit: number = lines.reduce((sum, l) => sum + (Number(l.credit_paise) || 0), 0);
  const isBalanced = totalDebit === totalCredit && totalDebit > 0;
  const diff: number = totalDebit - totalCredit;

  const filtered = entries.filter((e) => {
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

  async function handlePost(entryId: string) {
    const sb = getSupabaseClient();
    const { data, error: err } = await sb
      .from("journal_entries")
      .update({ status: "posted" })
      .eq("id", entryId)
      .select()
      .single();
    if (!err && data) {
      setEntries((prev) => prev.map((e) => e.id === entryId ? data as JournalEntry : e));
      if (selectedEntry?.id === entryId) setSelectedEntry(data as JournalEntry);
    }
  }

  async function handleSubmit(asDraft: boolean) {
    if (!isBalanced && !asDraft) return;
    if (!firmId) return;
    setSubmitting(true);
    const sb = getSupabaseClient();
    // Check if the selected entry date falls in a locked financial year
    if (formData.entry_date) {
      const { data: firm } = await sb.from("firms").select("locked_financial_years").eq("id", firmId).single();
      const locked: string[] = firm?.locked_financial_years ?? [];
      if (locked.length > 0) {
        const d = new Date(formData.entry_date);
        const month = d.getMonth() + 1; // 1-based
        const year = d.getFullYear();
        const fyLabel = month >= 4
          ? `${year}-${String(year + 1).slice(2)}`
          : `${year - 1}-${String(year).slice(2)}`;
        if (locked.includes(fyLabel)) {
          setError(`FY ${fyLabel} is locked. Unlock it from Accounting → Lock Financial Year before making entries.`);
          setSubmitting(false);
          return;
        }
      }
    }
    try {
      // All money uses integer paise — no floating point
      const totalDebitPaise = lines.reduce((s, l) => s + (Number(l.debit_paise) || 0), 0);
      const totalCreditPaise = lines.reduce((s, l) => s + (Number(l.credit_paise) || 0), 0);

      // Build metadata for forex entries (stored in narration suffix if non-INR)
      const forexMeta = isForex && parsedForeignAmount > 0 && parsedExchangeRate > 0
        ? ` [${formData.currency} ${parsedForeignAmount} @ ${parsedExchangeRate}]`
        : "";

      const { data: newEntry, error: entryErr } = await sb
        .from("journal_entries")
        .insert({
          firm_id: firmId,
          entry_date: formData.entry_date,
          reference_no: formData.reference_no,
          narration: formData.narration + forexMeta,
          entry_type: formData.entry_type,
          status: asDraft ? "draft" : "posted",
          total_debit_paise: totalDebitPaise,
          total_credit_paise: totalCreditPaise,
        })
        .select()
        .single();
      if (entryErr) throw new Error(entryErr.message);
      if (newEntry) {
        const linePayload = lines
          .filter((l) => l.account_id)
          .map((l) => ({
            journal_entry_id: (newEntry as { id: string }).id,
            account_id: l.account_id,
            debit_paise: Number(l.debit_paise) || 0,
            credit_paise: Number(l.credit_paise) || 0,
            narration: l.narration,
          }));
        if (linePayload.length > 0) {
          await sb.from("journal_entry_lines").insert(linePayload);
        }
        setEntries((prev) => [newEntry as JournalEntry, ...prev]);
        setShowForm(false);
        setLines([emptyLine(), emptyLine()]);
        setFormData({
          entry_date: "",
          reference_no: "",
          narration: "",
          entry_type: "Journal",
          currency: "INR",
          exchange_rate: "",
          foreign_amount: "",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-6xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Journal Entries</h1>
          <p className="text-sm text-[#64748B] mt-0.5">{entries.length} entries</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC]"
          >
            <Upload size={13} /> Import CSV
          </button>
          <button
            onClick={() => { setShowForm(true); setSelectedEntry(null); }}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
          >
            <Plus size={13} /> New Entry
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div>
          <label className="text-xs text-[#64748B]">From</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-[#64748B]">To</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Entry list */}
      <Card>
        <div className="divide-y divide-[#F8FAFC]">
          <div className="grid grid-cols-12 gap-2 px-5 py-2 text-xs font-semibold text-[#94A3B8] border-b border-[#F1F5F9]">
            <span className="col-span-2">Date</span>
            <span className="col-span-2">Reference</span>
            <span className="col-span-3">Narration</span>
            <span className="col-span-1">Type</span>
            <span className="col-span-1">Status</span>
            <span className="col-span-2 text-right">Debit</span>
            <span className="col-span-1"></span>
          </div>
          {filtered.length === 0 && (
            <div className="px-5 py-8 text-center text-sm text-[#94A3B8]">No entries yet. Create your first journal entry.</div>
          )}
          {filtered.map((entry) => {
            // Parse forex metadata from narration if present: "[USD 1000 @ 83.5]"
            const forexMatch = entry.narration?.match(/\[([A-Z]{3}) ([\d.]+) @ ([\d.]+)\]$/);
            const forexCurrency = forexMatch?.[1];
            const forexForeignAmt = forexMatch ? parseFloat(forexMatch[2]) : 0;
            const forexRate = forexMatch ? parseFloat(forexMatch[3]) : 0;
            const showForex = forexCurrency && forexCurrency !== "INR" && forexForeignAmt > 0;
            return (
              <div key={entry.id} className="grid grid-cols-12 gap-2 px-5 py-3 hover:bg-[#F8FAFC] transition-colors items-center">
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-2 text-xs text-[#475569] text-left">{formatDate(entry.entry_date)}</button>
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-2 text-xs font-mono text-[#64748B] truncate text-left">{entry.reference_no}</button>
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-3 text-sm text-[#0F172A] truncate text-left">
                  {entry.narration?.replace(/\[[A-Z]{3} [\d.]+ @ [\d.]+\]$/, "").trim()}
                </button>
                <span className="col-span-1 text-xs text-[#64748B]">{entry.entry_type}</span>
                <span className="col-span-1">
                  <Badge className={`text-xs ${statusBadge[entry.status]}`}>{entry.status}</Badge>
                </span>
                <span className="col-span-2 text-sm font-semibold tabular-nums text-right text-[#334155]">
                  {showForex
                    ? formatForexDisplay(forexCurrency, forexForeignAmt, forexRate, entry.total_debit_paise ?? 0)
                    : formatPaise(entry.total_debit_paise ?? 0)}
                </span>
                <span className="col-span-1 text-right">
                  {entry.status === "draft" && (
                    <button onClick={() => handlePost(entry.id)} className="text-xs text-blue-600 hover:underline">Post</button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Entry detail panel */}
      {selectedEntry && !showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between">
              <span>{selectedEntry.narration?.replace(/\[[A-Z]{3} [\d.]+ @ [\d.]+\]$/, "").trim()}</span>
              <button onClick={() => setSelectedEntry(null)} className="text-xs text-[#94A3B8] hover:text-[#475569]">Close</button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-3 text-xs text-[#64748B] mb-4">
              <div><span className="block font-medium text-[#334155]">Date</span>{formatDate(selectedEntry.entry_date)}</div>
              <div><span className="block font-medium text-[#334155]">Reference</span>{selectedEntry.reference_no || "—"}</div>
              <div><span className="block font-medium text-[#334155]">Type</span>{selectedEntry.entry_type}</div>
              <div><span className="block font-medium text-[#334155]">Status</span>
                <span className={`px-2 py-0.5 rounded-full ${statusBadge[selectedEntry.status]}`}>{selectedEntry.status}</span>
              </div>
            </div>
            <div className="text-xs text-[#64748B] bg-[#F8FAFC] rounded-lg p-3">
              Total Debit: <span className="font-semibold text-[#0F172A]">{formatPaise(selectedEntry.total_debit_paise ?? 0)}</span>
              {" | "}
              Total Credit: <span className="font-semibold text-[#0F172A]">{formatPaise(selectedEntry.total_credit_paise ?? 0)}</span>
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
                <label className="text-xs text-[#64748B]">Date *</label>
                <input type="date" value={formData.entry_date}
                  onChange={(e) => setFormData({ ...formData, entry_date: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="text-xs text-[#64748B]">Reference No.</label>
                <input value={formData.reference_no}
                  onChange={(e) => setFormData({ ...formData, reference_no: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. INV/2025-26/004" />
              </div>
              <div>
                <label className="text-xs text-[#64748B]">Entry Type</label>
                <select value={formData.entry_type}
                  onChange={(e) => setFormData({ ...formData, entry_type: e.target.value as EntryType })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {ENTRY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="md:col-span-1 col-span-2">
                <label className="text-xs text-[#64748B]">Narration *</label>
                <input value={formData.narration}
                  onChange={(e) => setFormData({ ...formData, narration: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Description of entry" />
              </div>
            </div>

            {/* ── Multi-currency fields ─────────────────────────────────── */}
            <div className="border border-[#F1F5F9] rounded-lg p-3 bg-[#F8FAFC] space-y-3">
              <p className="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Currency</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <label className="text-xs text-[#64748B]">Currency</label>
                  <select
                    value={formData.currency}
                    onChange={(e) => setFormData({ ...formData, currency: e.target.value as Currency, exchange_rate: "", foreign_amount: "" })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>{c}{c === "INR" ? " (default)" : ""}</option>
                    ))}
                  </select>
                </div>

                {isForex && (
                  <>
                    <div>
                      <label className="text-xs text-[#64748B]">
                        Exchange Rate <span className="text-[#94A3B8]">(1 {formData.currency} = ? INR)</span>
                      </label>
                      <input
                        type="number"
                        min={0}
                        step="0.0001"
                        value={formData.exchange_rate}
                        onChange={(e) => setFormData({ ...formData, exchange_rate: e.target.value })}
                        className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                        placeholder="e.g. 83.50"
                      />
                    </div>

                    <div>
                      <label className="text-xs text-[#64748B]">
                        Foreign Amount <span className="text-[#94A3B8]">({formData.currency})</span>
                      </label>
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={formData.foreign_amount}
                        onChange={(e) => setFormData({ ...formData, foreign_amount: e.target.value })}
                        className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                        placeholder="e.g. 1000"
                      />
                    </div>

                    <div>
                      <label className="text-xs text-[#64748B]">INR Equivalent (paise)</label>
                      <div className="w-full mt-1 px-3 py-1.5 text-sm border border-[#F1F5F9] rounded-md bg-white text-[#334155] font-mono tabular-nums">
                        {convertedInrPaise > 0 ? formatPaise(convertedInrPaise) : "—"}
                      </div>
                      <p className="text-xs text-[#94A3B8] mt-0.5">
                        {parsedForeignAmount > 0 && parsedExchangeRate > 0
                          ? `${parsedForeignAmount} × ${parsedExchangeRate} × 100 = ${convertedInrPaise} paise`
                          : "Enter rate and amount above"}
                      </p>
                    </div>
                  </>
                )}
              </div>

              {/* Forex gain/loss notice */}
              {isForex && (
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-100 text-amber-700 text-xs rounded-md px-3 py-2">
                  <Info size={13} className="mt-0.5 shrink-0" />
                  <span>
                    Forex difference will be posted to <strong>Forex Gain/Loss account</strong> at the time of settlement.
                    Exchange rate entered here is the transaction-date rate (manual entry — no live API).
                  </span>
                </div>
              )}
            </div>

            {/* Lines */}
            <div>
              <div className="grid grid-cols-12 gap-2 text-xs font-semibold text-[#94A3B8] mb-1">
                <span className="col-span-4">Account</span>
                <span className="col-span-3">Debit (paise)</span>
                <span className="col-span-3">Credit (paise)</span>
                <span className="col-span-1">Narration</span>
                <span className="col-span-1"></span>
              </div>
              {lines.map((line, idx) => (
                <div key={idx} className="grid grid-cols-12 gap-2 mb-2 items-center">
                  <div className="col-span-4">
                    <select value={line.account_id}
                      onChange={(e) => updateLine(idx, "account_id", e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500">
                      <option value="">Select account…</option>
                      {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                    </select>
                  </div>
                  <div className="col-span-3">
                    <input type="number" min={0} value={line.debit_paise || ""}
                      onChange={(e) => updateLine(idx, "debit_paise", parseInt(e.target.value) || 0)}
                      className="w-full px-2 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="0" />
                  </div>
                  <div className="col-span-3">
                    <input type="number" min={0} value={line.credit_paise || ""}
                      onChange={(e) => updateLine(idx, "credit_paise", parseInt(e.target.value) || 0)}
                      className="w-full px-2 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="0" />
                  </div>
                  <div className="col-span-1">
                    <input value={line.narration}
                      onChange={(e) => updateLine(idx, "narration", e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="Note" />
                  </div>
                  <div className="col-span-1 flex justify-center">
                    {lines.length > 2 && (
                      <button onClick={() => removeLine(idx)} className="text-red-600 hover:text-red-600">
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
                ? <><CheckCircle size={15} /> Balanced — {formatPaise(totalDebit)}</>
                : <><XCircle size={15} /> Unbalanced (Diff: {formatPaise(Math.abs(diff))})</>
              }
            </div>

            <div className="flex gap-2">
              <button onClick={() => setShowForm(false)} className="text-sm text-[#475569] border border-[#E2E8F0] px-4 py-1.5 rounded-md hover:bg-[#F8FAFC]">
                Cancel
              </button>
              <button
                onClick={() => handleSubmit(true)}
                disabled={submitting}
                className="text-sm border border-blue-300 text-blue-700 px-4 py-1.5 rounded-md hover:bg-blue-50 disabled:opacity-50"
              >
                Save as Draft
              </button>
              <button
                onClick={() => handleSubmit(false)}
                disabled={!isBalanced || submitting}
                className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Post Entry
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {showImport && firmId && (
        <CsvImportModal
          title="Import Journal Entries from CSV"
          columns={JOURNAL_IMPORT_COLUMNS}
          templateFilename="practicesync-journal-template.xlsx"
          onClose={() => setShowImport(false)}
          onImport={async (rows: ImportRow[]) => {
            // Group rows by narration+date+reference to merge multi-line entries
            const sb = getSupabaseClient();
            type EntryGroup = { entry_date: string; narration: string; reference_no: string; entry_type: string; lines: { account_code: string; debit_rs: string; credit_rs: string }[] };
            const groups = new Map<string, EntryGroup>();
            for (const row of rows) {
              const key = `${row.entry_date}||${row.narration}||${row.reference_no ?? ""}`;
              if (!groups.has(key)) {
                groups.set(key, { entry_date: row.entry_date, narration: row.narration, reference_no: row.reference_no ?? "", entry_type: row.entry_type || "Journal", lines: [] });
              }
              groups.get(key)!.lines.push({ account_code: row.account_code, debit_rs: row.debit_rs, credit_rs: row.credit_rs });
            }
            let imported = 0;
            const errors: string[] = [];
            for (const group of Array.from(groups.values())) {
              const totalDebit = group.lines.reduce((s: number, l: EntryGroup["lines"][0]) => s + Math.round(parseFloat(l.debit_rs ?? "0") * 100), 0);
              const totalCredit = group.lines.reduce((s: number, l: EntryGroup["lines"][0]) => s + Math.round(parseFloat(l.credit_rs ?? "0") * 100), 0);
              const { data: je, error: jeErr } = await sb.from("journal_entries").insert({
                firm_id: firmId,
                client_id: (accounts[0] as unknown as { client_id?: string })?.client_id ?? null,
                entry_date: group.entry_date,
                narration: group.narration,
                reference_no: group.reference_no || null,
                entry_type: group.entry_type,
                status: "draft",
                total_debit_paise: totalDebit,
                total_credit_paise: totalCredit,
              }).select().single();
              if (jeErr) { errors.push(`${group.narration}: ${jeErr.message}`); continue; }
              const linePayload = group.lines.map((l: EntryGroup["lines"][0]) => {
                const acct = accounts.find(a => a.account_code === l.account_code);
                return {
                  journal_entry_id: (je as { id: string }).id,
                  account_id: acct?.id ?? null,
                  debit_paise: Math.round(parseFloat(l.debit_rs ?? "0") * 100),
                  credit_paise: Math.round(parseFloat(l.credit_rs ?? "0") * 100),
                  narration: group.narration,
                };
              }).filter((l: { account_id: string | null | undefined }) => l.account_id);
              if (linePayload.length > 0) await sb.from("journal_lines").insert(linePayload);
              imported++;
            }
            if (imported > 0) {
              const { data } = await sb.from("journal_entries").select("*").eq("firm_id", firmId).order("entry_date", { ascending: false });
              if (data) setEntries(data as JournalEntry[]);
            }
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            if (row.entry_date && !/^\d{4}-\d{2}-\d{2}$/.test(row.entry_date)) errs.push("entry_date must be YYYY-MM-DD");
            if (!row.debit_rs && !row.credit_rs) errs.push("Either debit_rs or credit_rs must be provided");
            return errs;
          }}
        />
      )}
    </div>
  );
}

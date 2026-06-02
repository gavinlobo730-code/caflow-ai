"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Trash2, CheckCircle, XCircle, Info } from "lucide-react";
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
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-64 bg-gray-100 rounded-xl" />
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
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Journal Entries</h1>
          <p className="text-sm text-gray-500 mt-0.5">{entries.length} entries</p>
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
            <span className="col-span-3">Narration</span>
            <span className="col-span-1">Type</span>
            <span className="col-span-1">Status</span>
            <span className="col-span-2 text-right">Debit</span>
            <span className="col-span-1"></span>
          </div>
          {filtered.length === 0 && (
            <div className="px-5 py-8 text-center text-sm text-gray-400">No entries yet. Create your first journal entry.</div>
          )}
          {filtered.map((entry) => {
            // Parse forex metadata from narration if present: "[USD 1000 @ 83.5]"
            const forexMatch = entry.narration?.match(/\[([A-Z]{3}) ([\d.]+) @ ([\d.]+)\]$/);
            const forexCurrency = forexMatch?.[1];
            const forexForeignAmt = forexMatch ? parseFloat(forexMatch[2]) : 0;
            const forexRate = forexMatch ? parseFloat(forexMatch[3]) : 0;
            const showForex = forexCurrency && forexCurrency !== "INR" && forexForeignAmt > 0;
            return (
              <div key={entry.id} className="grid grid-cols-12 gap-2 px-5 py-3 hover:bg-gray-50 transition-colors items-center">
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-2 text-xs text-gray-600 text-left">{formatDate(entry.entry_date)}</button>
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-2 text-xs font-mono text-gray-500 truncate text-left">{entry.reference_no}</button>
                <button onClick={() => { setSelectedEntry(entry); setShowForm(false); }} className="col-span-3 text-sm text-gray-900 truncate text-left">
                  {entry.narration?.replace(/\[[A-Z]{3} [\d.]+ @ [\d.]+\]$/, "").trim()}
                </button>
                <span className="col-span-1 text-xs text-gray-500">{entry.entry_type}</span>
                <span className="col-span-1">
                  <Badge className={`text-xs ${statusBadge[entry.status]}`}>{entry.status}</Badge>
                </span>
                <span className="col-span-2 text-sm font-semibold tabular-nums text-right text-gray-700">
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
            <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3">
              Total Debit: <span className="font-semibold text-gray-900">{formatPaise(selectedEntry.total_debit_paise ?? 0)}</span>
              {" | "}
              Total Credit: <span className="font-semibold text-gray-900">{formatPaise(selectedEntry.total_credit_paise ?? 0)}</span>
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

            {/* ── Multi-currency fields ─────────────────────────────────── */}
            <div className="border border-gray-100 rounded-lg p-3 bg-gray-50 space-y-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Currency</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <label className="text-xs text-gray-500">Currency</label>
                  <select
                    value={formData.currency}
                    onChange={(e) => setFormData({ ...formData, currency: e.target.value as Currency, exchange_rate: "", foreign_amount: "" })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>{c}{c === "INR" ? " (default)" : ""}</option>
                    ))}
                  </select>
                </div>

                {isForex && (
                  <>
                    <div>
                      <label className="text-xs text-gray-500">
                        Exchange Rate <span className="text-gray-400">(1 {formData.currency} = ? INR)</span>
                      </label>
                      <input
                        type="number"
                        min={0}
                        step="0.0001"
                        value={formData.exchange_rate}
                        onChange={(e) => setFormData({ ...formData, exchange_rate: e.target.value })}
                        className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                        placeholder="e.g. 83.50"
                      />
                    </div>

                    <div>
                      <label className="text-xs text-gray-500">
                        Foreign Amount <span className="text-gray-400">({formData.currency})</span>
                      </label>
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={formData.foreign_amount}
                        onChange={(e) => setFormData({ ...formData, foreign_amount: e.target.value })}
                        className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                        placeholder="e.g. 1000"
                      />
                    </div>

                    <div>
                      <label className="text-xs text-gray-500">INR Equivalent (paise)</label>
                      <div className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-100 rounded-md bg-white text-gray-700 font-mono tabular-nums">
                        {convertedInrPaise > 0 ? formatPaise(convertedInrPaise) : "—"}
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5">
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
              <div className="grid grid-cols-12 gap-2 text-xs font-semibold text-gray-400 mb-1">
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
                      className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500">
                      <option value="">Select account…</option>
                      {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
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
                ? <><CheckCircle size={15} /> Balanced — {formatPaise(totalDebit)}</>
                : <><XCircle size={15} /> Unbalanced (Diff: {formatPaise(Math.abs(diff))})</>
              }
            </div>

            <div className="flex gap-2">
              <button onClick={() => setShowForm(false)} className="text-sm text-gray-600 border border-gray-200 px-4 py-1.5 rounded-md hover:bg-gray-50">
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
    </div>
  );
}

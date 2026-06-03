"use client";

/**
 * Bank Reconciliation — matches bank statement transactions with journal ledger entries.
 * All amounts in integer paise (BIGINT). Never use floating point for money.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

/* ─── Helpers ─────────────────────────────────────────────────────────────── */

/** Format integer paise as ₹ with en-IN locale. Never use floating point. */
function fmtRs(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  // Integer division: paise → rupees + remainder
  const rupees = Math.trunc(abs / 100);
  const paiseRem = abs % 100;
  const paiseStr = paiseRem < 10 ? `0${paiseRem}` : `${paiseRem}`;
  return `${sign}₹${rupees.toLocaleString("en-IN")}.${paiseStr}`;
}

/** Parse a rupee string like "1234.56" to integer paise. */
function rsToPaise(rs: string): number {
  const cleaned = rs.replace(/[^0-9.]/g, "");
  if (!cleaned) return 0;
  const parts = cleaned.split(".");
  const rupees = parseInt(parts[0] || "0", 10);
  const paiseStr = (parts[1] ?? "00").padEnd(2, "0").slice(0, 2);
  const paise = parseInt(paiseStr, 10);
  // Integer paise arithmetic — never float
  return rupees * 100 + paise;
}

/* ─── Types ───────────────────────────────────────────────────────────────── */

type Client = { id: string; client_name: string };

type BankTx = {
  id: string;
  date: string;
  description: string;
  debit_paise: number;
  credit_paise: number;
  balance_paise: number;
  reconciled: boolean;
  reconciled_journal_id: string | null;
};

type JournalEntry = {
  id: string;
  entry_date: string;
  narration: string;
  // Sum of all credit lines (used as display amount)
  total_credit_paise: number;
  total_debit_paise: number;
};

/* ─── Step indicator ──────────────────────────────────────────────────────── */
type Step = "setup" | "reconcile";

/* ─── Page ────────────────────────────────────────────────────────────────── */

export default function BankReconciliationPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — setup fields
  const [clientId, setClientId] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [periodStart, setPeriodStart] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().split("T")[0];
  });
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().split("T")[0]);
  const [openingBalanceInput, setOpeningBalanceInput] = useState("0");
  const [closingBalanceInput, setClosingBalanceInput] = useState("0");

  // Step 2 — reconciliation data
  const [step, setStep] = useState<Step>("setup");
  const [bankTxs, setBankTxs] = useState<BankTx[]>([]);
  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [closingPeriod, setClosingPeriod] = useState(false);

  // Selection state
  const [selectedBankId, setSelectedBankId] = useState<string | null>(null);
  const [selectedJournalId, setSelectedJournalId] = useState<string | null>(null);

  /* ── Bootstrap ──────────────────────────────────────────────────────────── */
  useEffect(() => {
    getFirmId()
      .then(async (fid) => {
        setFirmId(fid);
        const sb = getSupabaseClient();
        const { data } = await sb
          .from("clients")
          .select("id, client_name")
          .eq("firm_id", fid)
          .order("client_name");
        const list = (data ?? []) as Client[];
        setClients(list);
        if (list.length > 0) setClientId(list[0].id);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  /* ── Load transactions ──────────────────────────────────────────────────── */
  const loadData = useCallback(async () => {
    if (!firmId || !clientId) return;
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();

    const [bankRes, journalRes] = await Promise.all([
      sb
        .from("bank_transactions")
        .select("id, date, description, debit_paise, credit_paise, balance_paise, reconciled, reconciled_journal_id")
        .eq("firm_id", firmId)
        .eq("client_id", clientId)
        .gte("date", periodStart)
        .lte("date", periodEnd)
        .order("date"),
      sb
        .from("journal_entries")
        .select("id, entry_date, narration, journal_lines(debit_paise, credit_paise)")
        .eq("firm_id", firmId)
        .eq("client_id", clientId)
        .gte("entry_date", periodStart)
        .lte("entry_date", periodEnd)
        .order("entry_date"),
    ]);

    if (bankRes.error) {
      setError(bankRes.error.message);
      setLoading(false);
      return;
    }

    const txs = (bankRes.data ?? []) as BankTx[];
    setBankTxs(txs);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const entries: JournalEntry[] = (journalRes.data ?? []).map((row: any) => {
      const lines: { debit_paise: number; credit_paise: number }[] = row.journal_lines ?? [];
      const totalDebit = lines.reduce((s: number, l: { debit_paise: number; credit_paise: number }) => s + (l.debit_paise ?? 0), 0);
      const totalCredit = lines.reduce((s: number, l: { debit_paise: number; credit_paise: number }) => s + (l.credit_paise ?? 0), 0);
      return {
        id: row.id as string,
        entry_date: row.entry_date as string,
        narration: row.narration as string,
        total_debit_paise: totalDebit,
        total_credit_paise: totalCredit,
      };
    });
    setJournalEntries(entries);
    setLoading(false);
  }, [firmId, clientId, periodStart, periodEnd]);

  /* ── Start reconciliation ───────────────────────────────────────────────── */
  async function startReconciliation() {
    await loadData();
    setStep("reconcile");
  }

  /* ── Match selected ─────────────────────────────────────────────────────── */
  async function matchSelected() {
    if (!selectedBankId || !selectedJournalId) return;
    setPosting(true);
    const sb = getSupabaseClient();
    const { error: err } = await sb
      .from("bank_transactions")
      .update({
        reconciled: true,
        reconciled_journal_id: selectedJournalId,
        reconciled_at: new Date().toISOString(),
      })
      .eq("id", selectedBankId);

    if (err) {
      setError(err.message);
    } else {
      setBankTxs((prev) =>
        prev.map((t) =>
          t.id === selectedBankId
            ? { ...t, reconciled: true, reconciled_journal_id: selectedJournalId }
            : t
        )
      );
      setSelectedBankId(null);
      setSelectedJournalId(null);
    }
    setPosting(false);
  }

  /* ── Mark reconciled no match ───────────────────────────────────────────── */
  async function markNoMatch() {
    if (!selectedBankId) return;
    setPosting(true);
    const sb = getSupabaseClient();
    const { error: err } = await sb
      .from("bank_transactions")
      .update({
        reconciled: true,
        reconciled_journal_id: null,
        reconciled_at: new Date().toISOString(),
      })
      .eq("id", selectedBankId);

    if (err) {
      setError(err.message);
    } else {
      setBankTxs((prev) =>
        prev.map((t) =>
          t.id === selectedBankId ? { ...t, reconciled: true, reconciled_journal_id: null } : t
        )
      );
      setSelectedBankId(null);
    }
    setPosting(false);
  }

  /* ── Close period ───────────────────────────────────────────────────────── */
  async function closePeriod() {
    if (!firmId || !clientId) return;
    setClosingPeriod(true);
    const sb = getSupabaseClient();

    // Integer paise — never float
    const openingPaise = rsToPaise(openingBalanceInput);
    const closingPaise = rsToPaise(closingBalanceInput);

    const { error: err } = await sb.from("bank_reconciliations").insert({
      firm_id: firmId,
      client_id: clientId,
      account_no: accountNo || null,
      period_start: periodStart,
      period_end: periodEnd,
      opening_balance_paise: openingPaise,
      closing_balance_paise: closingPaise,
      status: "closed",
    });

    if (err) {
      setError(err.message);
    } else {
      setStep("setup");
      setBankTxs([]);
      setJournalEntries([]);
    }
    setClosingPeriod(false);
  }

  /* ── Derived summary values (integer paise arithmetic) ─────────────────── */
  const openingPaise = rsToPaise(openingBalanceInput);
  const statementClosingPaise = rsToPaise(closingBalanceInput);

  const totalCreditPaise = bankTxs.reduce((s, t) => s + (t.credit_paise ?? 0), 0);
  const totalDebitPaise = bankTxs.reduce((s, t) => s + (t.debit_paise ?? 0), 0);
  // Integer arithmetic: opening + credits - debits
  const calculatedClosingPaise = openingPaise + totalCreditPaise - totalDebitPaise;
  const differencePaise = calculatedClosingPaise - statementClosingPaise;

  const reconciledCount = bankTxs.filter((t) => t.reconciled).length;
  const totalCount = bankTxs.length;
  const canClose = differencePaise === 0 && totalCount > 0;

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto space-y-5">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
            <ArrowLeft size={18} />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Bank Reconciliation</h1>
            <p className="text-sm text-gray-500 mt-0.5">Match bank statement transactions to journal entries</p>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            <AlertCircle size={15} className="shrink-0" />
            {error}
          </div>
        )}

        {/* ── STEP 1: Setup ── */}
        {step === "setup" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Step 1 — Setup</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Client *</label>
                  <select
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                  >
                    {clients.length === 0 && <option value="">No clients found</option>}
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.client_name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Account Number (optional)</label>
                  <input
                    type="text"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    placeholder="e.g. XX1234"
                    value={accountNo}
                    onChange={(e) => setAccountNo(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Period Start *</label>
                  <input
                    type="date"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    value={periodStart}
                    onChange={(e) => setPeriodStart(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Period End *</label>
                  <input
                    type="date"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    value={periodEnd}
                    onChange={(e) => setPeriodEnd(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Opening Balance (₹)</label>
                  <input
                    type="text"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    placeholder="0.00"
                    value={openingBalanceInput}
                    onChange={(e) => setOpeningBalanceInput(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Statement Closing Balance (₹)</label>
                  <input
                    type="text"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    placeholder="0.00"
                    value={closingBalanceInput}
                    onChange={(e) => setClosingBalanceInput(e.target.value)}
                  />
                </div>
              </div>
              <Button onClick={startReconciliation} disabled={!clientId || loading}>
                {loading ? "Loading…" : "Start Reconciliation →"}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* ── STEP 2: Reconciliation view ── */}
        {step === "reconcile" && (
          <>
            {/* Back to setup */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setStep("setup"); setBankTxs([]); setJournalEntries([]); }}
                className="text-sm text-blue-600 hover:underline"
              >
                ← Back to Setup
              </button>
              <span className="text-gray-300">|</span>
              <span className="text-sm text-gray-500">
                Period: {periodStart} to {periodEnd}
                {accountNo ? ` · Account: ${accountNo}` : ""}
              </span>
            </div>

            {/* Action buttons */}
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={matchSelected}
                disabled={!selectedBankId || !selectedJournalId || posting}
                size="sm"
              >
                <CheckCircle size={13} className="mr-1.5" />
                Match Selected
              </Button>
              <Button
                variant="outline"
                onClick={markNoMatch}
                disabled={!selectedBankId || posting}
                size="sm"
              >
                Mark as Reconciled (No Match)
              </Button>
            </div>

            {loading ? (
              <div className="text-center py-12 text-gray-400 animate-pulse">Loading transactions…</div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {/* Left: Bank Statement Transactions */}
                <div>
                  <h2 className="text-sm font-semibold text-gray-700 mb-2">
                    Bank Statement Transactions
                    <span className="ml-2 font-normal text-gray-400">
                      ({bankTxs.filter((t) => !t.reconciled).length} unreconciled)
                    </span>
                  </h2>
                  <div className="space-y-1.5">
                    {bankTxs.length === 0 && (
                      <p className="text-sm text-gray-400 py-6 text-center">No bank transactions found for this period.</p>
                    )}
                    {bankTxs.map((tx) => {
                      const isSelected = selectedBankId === tx.id;
                      const bg = tx.reconciled
                        ? "bg-green-50 border-green-200"
                        : isSelected
                        ? "bg-indigo-50 border-indigo-400"
                        : "bg-white border-gray-200 hover:bg-gray-50";
                      return (
                        <div
                          key={tx.id}
                          onClick={() => !tx.reconciled && setSelectedBankId((s) => s === tx.id ? null : tx.id)}
                          className={`border rounded-lg px-3 py-2.5 transition-colors ${bg} ${!tx.reconciled ? "cursor-pointer" : ""}`}
                        >
                          <div className="flex justify-between items-start gap-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900 truncate">{tx.description}</p>
                              <p className="text-xs text-gray-400 mt-0.5">{tx.date}</p>
                            </div>
                            <div className="shrink-0 text-right">
                              {tx.debit_paise > 0 && (
                                <p className="text-sm font-mono font-semibold text-red-600">
                                  Dr {fmtRs(tx.debit_paise)}
                                </p>
                              )}
                              {tx.credit_paise > 0 && (
                                <p className="text-sm font-mono font-semibold text-green-700">
                                  Cr {fmtRs(tx.credit_paise)}
                                </p>
                              )}
                            </div>
                          </div>
                          {tx.reconciled && (
                            <span className="inline-block mt-1 text-[10px] bg-green-100 text-green-700 rounded px-1.5 py-0.5">
                              ✓ Reconciled{tx.reconciled_journal_id ? "" : " (no match)"}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Right: Journal Entries */}
                <div>
                  <h2 className="text-sm font-semibold text-gray-700 mb-2">
                    Journal Entries
                    <span className="ml-2 font-normal text-gray-400">
                      ({journalEntries.length} entries)
                    </span>
                  </h2>
                  <div className="space-y-1.5">
                    {journalEntries.length === 0 && (
                      <p className="text-sm text-gray-400 py-6 text-center">No journal entries found for this period.</p>
                    )}
                    {journalEntries.map((je) => {
                      const isSelected = selectedJournalId === je.id;
                      const alreadyMatched = bankTxs.some((t) => t.reconciled_journal_id === je.id);
                      const bg = alreadyMatched
                        ? "bg-green-50 border-green-200"
                        : isSelected
                        ? "bg-indigo-50 border-indigo-400"
                        : "bg-white border-gray-200 hover:bg-gray-50";
                      const displayPaise = je.total_credit_paise > 0 ? je.total_credit_paise : je.total_debit_paise;
                      return (
                        <div
                          key={je.id}
                          onClick={() => !alreadyMatched && setSelectedJournalId((s) => s === je.id ? null : je.id)}
                          className={`border rounded-lg px-3 py-2.5 transition-colors ${bg} ${!alreadyMatched ? "cursor-pointer" : ""}`}
                        >
                          <div className="flex justify-between items-start gap-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900 truncate">{je.narration}</p>
                              <p className="text-xs text-gray-400 mt-0.5">{je.entry_date}</p>
                            </div>
                            <span className="shrink-0 text-sm font-mono font-semibold text-gray-700">
                              {fmtRs(displayPaise)}
                            </span>
                          </div>
                          {alreadyMatched && (
                            <span className="inline-block mt-1 text-[10px] bg-green-100 text-green-700 rounded px-1.5 py-0.5">
                              ✓ Matched
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Summary panel */}
            <Card className={differencePaise !== 0 ? "border-red-200" : "border-green-200"}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Reconciliation Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 text-sm mb-4">
                  <div>
                    <p className="text-xs text-gray-500">Opening Balance</p>
                    <p className="font-semibold text-gray-900">{fmtRs(openingPaise)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Add: Total Credits</p>
                    <p className="font-semibold text-green-700">{fmtRs(totalCreditPaise)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Less: Total Debits</p>
                    <p className="font-semibold text-red-600">{fmtRs(totalDebitPaise)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">= Closing Balance</p>
                    <p className="font-semibold text-gray-900">{fmtRs(calculatedClosingPaise)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Statement Closing</p>
                    <p className="font-semibold text-gray-900">{fmtRs(statementClosingPaise)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Difference</p>
                    <p className={`font-bold ${differencePaise === 0 ? "text-green-700" : "text-red-600"}`}>
                      {fmtRs(differencePaise)}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-gray-500">
                    Reconciled: <span className="font-semibold text-gray-800">{reconciledCount}</span> / {totalCount} transactions
                  </p>
                  {differencePaise !== 0 && (
                    <p className="text-xs text-red-600 flex items-center gap-1">
                      <AlertCircle size={12} />
                      Difference must be zero before closing the period.
                    </p>
                  )}
                  <Button
                    onClick={closePeriod}
                    disabled={!canClose || closingPeriod}
                    className="bg-green-600 hover:bg-green-700"
                    size="sm"
                  >
                    {closingPeriod ? "Closing…" : "Close Period"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

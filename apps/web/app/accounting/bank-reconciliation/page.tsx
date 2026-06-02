"use client";

/**
 * Bank Reconciliation — matches bank statement transactions with journal ledger entries.
 * All amounts in integer paise.
 */

import { useState, useEffect, useCallback } from "react";
import { AlertCircle, RefreshCw, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

function fmtRs(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  return `${sign}₹${(abs / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

type BankTx = {
  id: string;
  transaction_date: string;
  description: string;
  amount_paise: number;
  transaction_type: string; // DR or CR
};

type LedgerLine = {
  id: string;
  entry_date: string;
  narration: string;
  account_name: string;
  debit_paise: number;
  credit_paise: number;
};

type Match = {
  bank_transaction_id: string;
  journal_line_id: string;
};

const INSTALL_SQL = `-- Run in Supabase SQL editor:
CREATE TABLE IF NOT EXISTS bank_reconciliation_matches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  bank_transaction_id UUID NOT NULL,
  journal_line_id UUID NOT NULL,
  matched_at TIMESTAMPTZ DEFAULT now(),
  matched_by TEXT
);`;

export default function BankReconciliationPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<{ id: string; client_name: string }[]>([]);
  const [clientId, setClientId] = useState("");
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().split("T")[0];
  });
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().split("T")[0]);

  const [bankTxs, setBankTxs] = useState<BankTx[]>([]);
  const [ledgerLines, setLedgerLines] = useState<LedgerLine[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [savedMatches, setSavedMatches] = useState<Match[]>([]);

  const [selectedBank, setSelectedBank] = useState<string | null>(null);
  const [selectedLedger, setSelectedLedger] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [tablesError, setTablesError] = useState(false);
  const [posting, setPosting] = useState(false);

  const loadData = useCallback(async () => {
    if (!firmId || !clientId) return;
    setLoading(true);
    const sb = getSupabaseClient();

    const [bankRes, journalRes, matchRes] = await Promise.all([
      sb.from("bank_transactions")
        .select("id, transaction_date, description, amount_paise, transaction_type")
        .eq("firm_id", firmId)
        .gte("transaction_date", dateFrom)
        .lte("transaction_date", dateTo)
        .order("transaction_date"),
      sb.from("journal_lines")
        .select("id, debit_paise, credit_paise, journal_entries(entry_date, narration, client_id), accounts(account_name)")
        .eq("journal_entries.firm_id", firmId)
        .eq("journal_entries.client_id", clientId),
      sb.from("bank_reconciliation_matches")
        .select("bank_transaction_id, journal_line_id")
        .eq("firm_id", firmId),
    ]);

    if (matchRes.error?.message?.includes("does not exist")) {
      setTablesError(true);
    }

    setBankTxs(bankRes.data ?? []);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const lines: LedgerLine[] = (journalRes.data ?? []).map((row: any) => ({
      id: row.id,
      entry_date: row.journal_entries?.entry_date ?? "",
      narration: row.journal_entries?.narration ?? "",
      account_name: row.accounts?.account_name ?? "",
      debit_paise: row.debit_paise,
      credit_paise: row.credit_paise,
    }));
    setLedgerLines(lines);
    setSavedMatches(matchRes.data ?? []);
    setLoading(false);
  }, [firmId, clientId, dateFrom, dateTo]);

  useEffect(() => {
    getFirmId().then(fid => {
      setFirmId(fid);
      const sb = getSupabaseClient();
      sb.from("clients").select("id, client_name").eq("firm_id", fid).then(r => {
        setClients(r.data ?? []);
        if (r.data && r.data.length > 0) setClientId(r.data[0].id);
      });
    }).catch(() => {});
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  function autoMatch() {
    const newMatches: Match[] = [];
    const usedBank = new Set(savedMatches.map(m => m.bank_transaction_id));
    const usedLedger = new Set(savedMatches.map(m => m.journal_line_id));

    for (const btx of bankTxs) {
      if (usedBank.has(btx.id)) continue;
      const txDate = new Date(btx.transaction_date).getTime();
      const txAmount = Math.abs(btx.amount_paise);

      for (const ll of ledgerLines) {
        if (usedLedger.has(ll.id)) continue;
        const llDate = new Date(ll.entry_date).getTime();
        const dateDiff = Math.abs(txDate - llDate) / (1000 * 60 * 60 * 24);
        const llAmount = Math.max(ll.debit_paise, ll.credit_paise);

        // Match: same amount +/- 0 paise AND date within 3 days
        if (dateDiff <= 3 && txAmount === llAmount) {
          newMatches.push({ bank_transaction_id: btx.id, journal_line_id: ll.id });
          usedBank.add(btx.id);
          usedLedger.add(ll.id);
          break;
        }
      }
    }
    setMatches(m => [...m, ...newMatches]);
  }

  function manualMatch() {
    if (!selectedBank || !selectedLedger) return;
    setMatches(m => [...m, { bank_transaction_id: selectedBank, journal_line_id: selectedLedger }]);
    setSelectedBank(null);
    setSelectedLedger(null);
  }

  function unmatch(bankId: string) {
    setMatches(m => m.filter(x => x.bank_transaction_id !== bankId));
  }

  async function postReconciliation() {
    if (!firmId) return;
    setPosting(true);
    const sb = getSupabaseClient();
    await sb.from("bank_reconciliation_matches").insert(
      matches.map(m => ({ ...m, firm_id: firmId }))
    );
    setSavedMatches(prev => [...prev, ...matches]);
    setMatches([]);
    setPosting(false);
    loadData();
  }

  const allMatches = [...savedMatches, ...matches];
  const matchedBankIds = new Set(allMatches.map(m => m.bank_transaction_id));
  const matchedLedgerIds = new Set(allMatches.map(m => m.journal_line_id));

  const unmatchedBank = bankTxs.filter(t => !matchedBankIds.has(t.id));
  const unmatchedLedger = ledgerLines.filter(l => !matchedLedgerIds.has(l.id));

  const bankBalance = bankTxs.reduce((sum, t) => {
    return sum + (t.transaction_type === "CR" ? t.amount_paise : -t.amount_paise);
  }, 0);
  const bookBalance = ledgerLines.reduce((sum, l) => sum + l.credit_paise - l.debit_paise, 0);

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Bank Reconciliation</h1>
        <p className="text-sm text-gray-500 mb-6">Match bank statement transactions with journal ledger entries.</p>

        {tablesError && (
          <Card className="mb-4 border-amber-200 bg-amber-50">
            <CardContent className="pt-4">
              <div className="flex items-start gap-2">
                <AlertCircle size={16} className="text-amber-600 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-amber-800">Reconciliation matches table not found.</p>
                  <pre className="mt-2 bg-gray-900 text-green-400 p-3 rounded text-xs overflow-auto">{INSTALL_SQL}</pre>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Filters */}
        <Card className="mb-4">
          <CardContent className="pt-5">
            <div className="flex flex-wrap gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
                <select className="border rounded-lg px-3 py-2 text-sm" value={clientId} onChange={e => setClientId(e.target.value)}>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">From</label>
                <input type="date" className="border rounded-lg px-3 py-2 text-sm" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">To</label>
                <input type="date" className="border rounded-lg px-3 py-2 text-sm" value={dateTo} onChange={e => setDateTo(e.target.value)} />
              </div>
              <Button variant="outline" size="sm" onClick={loadData} className="flex items-center gap-1.5">
                <RefreshCw size={13} />Refresh
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Summary cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-gray-500 mb-1">Bank Balance</p>
              <p className="text-lg font-bold text-gray-900">{fmtRs(bankBalance)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-gray-500 mb-1">Book Balance</p>
              <p className="text-lg font-bold text-gray-900">{fmtRs(bookBalance)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-gray-500 mb-1">Difference</p>
              <p className={`text-lg font-bold ${Math.abs(bankBalance - bookBalance) < 100 ? "text-green-700" : "text-red-600"}`}>{fmtRs(bankBalance - bookBalance)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-gray-500 mb-1">Unmatched Items</p>
              <p className="text-lg font-bold text-amber-600">{unmatchedBank.length + unmatchedLedger.length}</p>
            </CardContent>
          </Card>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 mb-4">
          <Button onClick={autoMatch} className="flex items-center gap-1.5">
            <CheckCircle size={14} />Auto Match
          </Button>
          <Button
            variant="outline"
            onClick={manualMatch}
            disabled={!selectedBank || !selectedLedger}
          >
            Match Selected
          </Button>
          {matches.length > 0 && (
            <Button onClick={postReconciliation} disabled={posting} className="ml-auto bg-green-600 hover:bg-green-700">
              {posting ? "Posting..." : `Post Reconciliation (${matches.length} matches)`}
            </Button>
          )}
        </div>

        {loading ? (
          <div className="text-center py-12 text-gray-400">Loading transactions...</div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Bank Statement column */}
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">Bank Statement ({unmatchedBank.length} unmatched)</h2>
              <div className="space-y-2">
                {unmatchedBank.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">All transactions matched.</p>}
                {unmatchedBank.map(tx => (
                  <div
                    key={tx.id}
                    onClick={() => setSelectedBank(s => s === tx.id ? null : tx.id)}
                    className={`border rounded-lg p-3 cursor-pointer transition-colors ${
                      selectedBank === tx.id
                        ? "border-indigo-500 bg-indigo-50"
                        : "border-amber-200 bg-amber-50 hover:bg-amber-100"
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{tx.description}</p>
                        <p className="text-xs text-gray-500">{tx.transaction_date}</p>
                      </div>
                      <span className={`text-sm font-mono font-semibold ${tx.transaction_type === "CR" ? "text-green-700" : "text-red-600"}`}>
                        {tx.transaction_type === "CR" ? "+" : "-"}{fmtRs(Math.abs(tx.amount_paise))}
                      </span>
                    </div>
                  </div>
                ))}
                {/* Matched bank items */}
                {[...matches, ...savedMatches].map(m => {
                  const tx = bankTxs.find(t => t.id === m.bank_transaction_id);
                  if (!tx) return null;
                  const isSaved = savedMatches.find(sm => sm.bank_transaction_id === m.bank_transaction_id);
                  return (
                    <div key={tx.id} className="border rounded-lg p-3 border-green-200 bg-green-50">
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{tx.description}</p>
                          <p className="text-xs text-gray-500">{tx.transaction_date}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-mono font-semibold text-green-700">{fmtRs(tx.amount_paise)}</span>
                          {!isSaved && (
                            <button onClick={() => unmatch(tx.id)} className="text-gray-400 hover:text-red-500">
                              <XCircle size={14} />
                            </button>
                          )}
                        </div>
                      </div>
                      <span className="inline-block text-[10px] bg-green-100 text-green-700 rounded px-1.5 py-0.5 mt-1">Matched</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Ledger column */}
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">Ledger Entries ({unmatchedLedger.length} unmatched)</h2>
              <div className="space-y-2">
                {unmatchedLedger.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">All entries matched.</p>}
                {unmatchedLedger.map(ll => (
                  <div
                    key={ll.id}
                    onClick={() => setSelectedLedger(s => s === ll.id ? null : ll.id)}
                    className={`border rounded-lg p-3 cursor-pointer transition-colors ${
                      selectedLedger === ll.id
                        ? "border-indigo-500 bg-indigo-50"
                        : "border-amber-200 bg-amber-50 hover:bg-amber-100"
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{ll.narration}</p>
                        <p className="text-xs text-gray-500">{ll.entry_date} {ll.account_name ? `• ${ll.account_name}` : ""}</p>
                      </div>
                      <span className="text-sm font-mono font-semibold text-gray-700">
                        {ll.debit_paise > 0 ? fmtRs(ll.debit_paise) : fmtRs(ll.credit_paise)}
                      </span>
                    </div>
                  </div>
                ))}
                {/* Matched ledger items */}
                {[...matches, ...savedMatches].map(m => {
                  const ll = ledgerLines.find(l => l.id === m.journal_line_id);
                  if (!ll) return null;
                  return (
                    <div key={ll.id} className="border rounded-lg p-3 border-green-200 bg-green-50">
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{ll.narration}</p>
                          <p className="text-xs text-gray-500">{ll.entry_date} {ll.account_name ? `• ${ll.account_name}` : ""}</p>
                        </div>
                        <span className="text-sm font-mono font-semibold text-green-700">
                          {ll.debit_paise > 0 ? fmtRs(ll.debit_paise) : fmtRs(ll.credit_paise)}
                        </span>
                      </div>
                      <span className="inline-block text-[10px] bg-green-100 text-green-700 rounded px-1.5 py-0.5 mt-1">Matched</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

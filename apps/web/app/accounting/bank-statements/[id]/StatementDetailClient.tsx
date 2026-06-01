"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPaise } from "@/lib/services/formatting";
import { getBankTransactions, updateTransactionAccount, postBankTransaction } from "@/lib/data/bankStatements";
import type { BankTransaction } from "@/lib/data/bankStatements";

import { getSupabaseClient } from "@/lib/supabase/client";

const MATCH_STATUS_COLORS: Record<string, string> = {
  unmatched: "bg-amber-100 text-amber-700",
  matched: "bg-blue-100 text-blue-700",
  posted: "bg-green-100 text-green-700",
  ignored: "bg-gray-100 text-gray-500",
};

interface Account {
  id: string;
  account_name: string;
  account_code: string;
  account_type: string;
}

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="h-96 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function StatementDetailClient() {
  const params = useParams();
  const statementId = Array.isArray(params.id) ? params.id[0] : params.id;

  const [transactions, setTransactions] = useState<BankTransaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccounts, setSelectedAccounts] = useState<Record<string, string>>({});
  const [posting, setPosting] = useState<Record<string, boolean>>({});
  const [bankGLAccountId, setBankGLAccountId] = useState<string>("");

  const load = useCallback(async () => {
    if (!statementId || statementId === "_placeholder") return;
    setLoading(true);
    setError(null);
    try {
      const sb = getSupabaseClient();
      // Get firm_id for the current session
      const { data: { session } } = await sb.auth.getSession();
      let firmId: string | null = null;
      if (session) {
        const { data: userData } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
        firmId = userData?.firm_id ?? null;
      }

      const txns = await getBankTransactions(statementId as string);
      setTransactions(txns);

      if (firmId) {
        const { data: accData } = await sb
          .from("accounts")
          .select("id, account_code, account_name, account_type")
          .eq("firm_id", firmId);
        const accs = (accData ?? []) as Account[];
        setAccounts(accs);
        const bankAcc = accs.find(
          a => a.account_type === "Asset" &&
            (a.account_name.toLowerCase().includes("bank") || a.account_name.toLowerCase().includes("cash"))
        );
        if (bankAcc) setBankGLAccountId(bankAcc.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load transactions");
    } finally {
      setLoading(false);
    }
  }, [statementId]);

  useEffect(() => { load(); }, [load]);

  async function handlePost(txn: BankTransaction) {
    const accountId = selectedAccounts[txn.id] ?? txn.account_id;
    if (!accountId) { alert("Please select an account first"); return; }
    if (!bankGLAccountId) { alert("No bank GL account found. Please set up Chart of Accounts."); return; }
    setPosting(prev => ({ ...prev, [txn.id]: true }));
    try {
      await updateTransactionAccount(txn.id, accountId);
      await postBankTransaction(txn.id, accountId, bankGLAccountId, txn.statement_id);
      const updated = await getBankTransactions(statementId as string);
      setTransactions(updated);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to post transaction");
    } finally {
      setPosting(prev => ({ ...prev, [txn.id]: false }));
    }
  }

  async function handleAccountChange(txnId: string, accountId: string) {
    setSelectedAccounts(prev => ({ ...prev, [txnId]: accountId }));
    if (accountId) await updateTransactionAccount(txnId, accountId).catch(() => undefined);
  }

  if (!statementId || statementId === "_placeholder") {
    return <div className="p-6 max-w-7xl mx-auto"><p className="text-gray-500 text-sm">Loading…</p></div>;
  }
  if (loading) return <LoadingSkeleton />;
  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  const unmatched = transactions.filter(t => t.match_status === "unmatched").length;
  const posted = transactions.filter(t => t.match_status === "posted").length;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
          <Link href="/accounting" className="hover:text-gray-700">Accounting</Link>
          <ChevronRight size={14} />
          <Link href="/accounting/bank-statements" className="hover:text-gray-700">Bank Statements</Link>
          <ChevronRight size={14} />
          <span className="text-gray-900 font-medium">Allocate</span>
        </div>
        <h1 className="text-xl font-semibold text-gray-900">Allocate Bank Transactions</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {transactions.length} total · {unmatched} unmatched · {posted} posted
        </p>
      </div>

      {!bankGLAccountId && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-4 py-3 text-sm">
          No bank GL account found in Chart of Accounts. Posting will fail until a bank/cash account is set up.
        </div>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Transactions</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Date</th>
                <th className="px-3 py-3 text-left font-semibold">Description</th>
                <th className="px-3 py-3 text-right font-semibold">Debit</th>
                <th className="px-3 py-3 text-right font-semibold">Credit</th>
                <th className="px-3 py-3 text-right font-semibold">Balance</th>
                <th className="px-3 py-3 text-left font-semibold">Account</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-5 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {transactions.map(txn => (
                <tr key={txn.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-xs text-gray-600 whitespace-nowrap">{formatDate(txn.transaction_date)}</td>
                  <td className="px-3 py-3 text-sm text-gray-800 max-w-xs truncate" title={txn.description}>{txn.description}</td>
                  <td className="px-3 py-3 text-sm text-right tabular-nums text-red-600">
                    {txn.debit_paise > 0 ? formatPaise(txn.debit_paise) : ""}
                  </td>
                  <td className="px-3 py-3 text-sm text-right tabular-nums text-green-600">
                    {txn.credit_paise > 0 ? formatPaise(txn.credit_paise) : ""}
                  </td>
                  <td className="px-3 py-3 text-sm text-right tabular-nums text-gray-500">
                    {txn.balance_paise != null ? formatPaise(txn.balance_paise) : ""}
                  </td>
                  <td className="px-3 py-3">
                    {txn.match_status === "posted" ? (
                      <span className="text-xs text-gray-500 font-mono">
                        {accounts.find(a => a.id === txn.account_id)?.account_name ?? txn.account_id?.slice(0, 8) ?? "—"}
                      </span>
                    ) : (
                      <select
                        value={selectedAccounts[txn.id] ?? txn.account_id ?? ""}
                        onChange={e => handleAccountChange(txn.id, e.target.value)}
                        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 w-44"
                      >
                        <option value="">— Select account —</option>
                        {accounts.map(a => (
                          <option key={a.id} value={a.id}>
                            {a.account_code} {a.account_name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <Badge className={`text-xs ${MATCH_STATUS_COLORS[txn.match_status] ?? "bg-gray-100 text-gray-600"}`}>
                      {txn.match_status}
                    </Badge>
                  </td>
                  <td className="px-5 py-3">
                    {txn.match_status !== "posted" && txn.match_status !== "ignored" && (
                      <button
                        onClick={() => handlePost(txn)}
                        disabled={posting[txn.id] ?? false}
                        className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                      >
                        {posting[txn.id] ? "Posting…" : "Post"}
                      </button>
                    )}
                    {txn.match_status === "posted" && (
                      <span className="text-xs text-green-600">Posted</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {transactions.length === 0 && (
            <div className="text-center py-12 text-sm text-gray-400">No transactions in this statement</div>
          )}
        </div>
      </Card>
    </div>
  );
}

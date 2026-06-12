"use client";

import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Search, Building2, ExternalLink, Info } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Account, AccountType } from "@/lib/types";

const TYPE_COLORS: Record<AccountType, string> = {
  Asset:     "bg-blue-100 text-blue-700",
  Liability: "bg-red-100 text-red-700",
  Equity:    "bg-purple-100 text-purple-700",
  Revenue:   "bg-green-100 text-green-700",
  Expense:   "bg-orange-100 text-orange-700",
};

const ACCOUNT_TYPES: AccountType[] = ["Asset", "Liability", "Equity", "Revenue", "Expense"];

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

export default function ClientCoaPage() {
  useParams<{ id: string }>();

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<AccountType | "All">("All");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fid = await getFirmId();
      const sb = getSupabaseClient();
      // Firm master COA only — client_id IS NULL per approved architecture
      const { data, error: err } = await sb
        .from("chart_of_accounts")
        .select("*")
        .eq("firm_id", fid)
        .is("client_id", null)
        .eq("is_active", true)
        .order("account_code");
      if (err) throw new Error(err.message);
      setAccounts((data ?? []) as Account[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="p-6 max-w-5xl space-y-4 animate-pulse">
        {[1, 2, 3].map((i) => <div key={i} className="h-32 bg-[#F1F5F9] rounded-xl" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-5xl">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  const visibleAccounts = accounts.filter((a) => {
    if (activeTab !== "All" && a.account_type !== activeTab) return false;
    if (search) {
      const q = search.toLowerCase();
      return a.account_name.toLowerCase().includes(q) || a.account_code.includes(q);
    }
    return true;
  });

  const grouped = ACCOUNT_TYPES.reduce<Record<AccountType, Account[]>>((acc, type) => {
    acc[type] = visibleAccounts.filter((a) => a.account_type === type);
    return acc;
  }, { Asset: [], Liability: [], Equity: [], Revenue: [], Expense: [] });

  const tabs: (AccountType | "All")[] = ["All", ...ACCOUNT_TYPES];
  const counts: Record<string, number> = { All: accounts.length };
  for (const t of ACCOUNT_TYPES) counts[t] = accounts.filter((a) => a.account_type === t).length;

  return (
    <div className="p-6 max-w-5xl space-y-5">
      {/* Architecture banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
        <Info size={15} className="text-blue-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-blue-800">Shared Firm Chart of Accounts</p>
          <p className="text-xs text-blue-700 mt-0.5">
            All clients share the firm&apos;s master Chart of Accounts. Balances are isolated per client.
            Account management is done at the firm level.
          </p>
        </div>
        <Link
          href="/accounting/chart-of-accounts"
          className="flex items-center gap-1 text-xs text-blue-600 font-medium whitespace-nowrap hover:underline shrink-0"
        >
          Manage Accounts <ExternalLink size={11} />
        </Link>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-[#1E293B]">Chart of Accounts</h1>
          <p className="text-xs text-[#94A3B8] mt-0.5 flex items-center gap-1">
            <Building2 size={10} /> {accounts.length} firm accounts (read-only view)
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by account name or code…"
          className="w-full pl-8 pr-4 py-2 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {tab} <span className="ml-1 text-[#94A3B8]">({counts[tab] ?? 0})</span>
          </button>
        ))}
      </div>

      {/* Account groups */}
      {accounts.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#64748B] mb-2">No accounts in master COA yet</p>
          <Link href="/accounting/chart-of-accounts" className="text-xs text-blue-600 hover:underline">
            Go to Chart of Accounts to add accounts →
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {ACCOUNT_TYPES.map((type) => {
            const accs = grouped[type];
            if (activeTab !== "All" && activeTab !== type) return null;
            if (accs.length === 0) return null;
            return (
              <div key={type} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <div className="px-5 py-3 border-b border-[#F8FAFC] flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type]}`}>{type}</span>
                  <span className="text-xs text-[#94A3B8]">{accs.length} accounts</span>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] text-[#94A3B8] border-b border-[#F8FAFC]">
                      <th className="px-5 py-2 text-left font-semibold w-20">Code</th>
                      <th className="px-3 py-2 text-left font-semibold">Name</th>
                      <th className="px-3 py-2 text-left font-semibold">Sub-type</th>
                      <th className="px-3 py-2 text-left font-semibold">Schedule III</th>
                      <th className="px-3 py-2 text-left font-semibold">Tax Category</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {accs.map((acc) => (
                      <tr key={acc.id} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-2.5 font-mono text-[#94A3B8]">{acc.account_code}</td>
                        <td className="px-3 py-2.5 font-medium text-[#0F172A]">{acc.account_name}</td>
                        <td className="px-3 py-2.5 text-[#64748B]">{acc.account_subtype ?? "—"}</td>
                        <td className="px-3 py-2.5 text-[#64748B]">
                          {(acc as Account & { schedule_iii_mapping?: string }).schedule_iii_mapping ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 text-[#64748B]">
                          {(acc as Account & { tax_category?: string }).tax_category ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, GitBranch } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

interface CoaRow {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  tax_category: string | null;
  schedule_iii_mapping: string | null;
  is_active: boolean;
}

const SCHEDULE_III_SECTIONS = [
  { heading: "Balance Sheet — Assets", items: ["Fixed Assets", "Capital Work in Progress", "Goodwill & Intangibles", "Long-term Investments", "Deferred Tax Asset", "Inventories", "Trade Receivables", "Cash & Cash Equivalents", "Short-term Loans & Advances", "Other Current Assets"] },
  { heading: "Balance Sheet — Equity & Liabilities", items: ["Share Capital", "Reserves & Surplus", "Long-term Borrowings", "Deferred Tax Liability", "Long-term Provisions", "Short-term Borrowings", "Trade Payables", "Other Current Liabilities", "Short-term Provisions"] },
  { heading: "Profit & Loss", items: ["Revenue from Operations", "Other Income", "Cost of Materials Consumed", "Employee Benefits Expense", "Finance Costs", "Depreciation & Amortisation", "Other Expenses"] },
];

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

export default function ScheduleIIIMappingPage() {
  const [accounts, setAccounts] = useState<CoaRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const fid = await getFirmId();
        const sb = getSupabaseClient();
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .select("id, account_code, account_name, account_type, tax_category, schedule_iii_mapping, is_active")
          .eq("firm_id", fid)
          .is("client_id", null)
          .order("account_code");
        if (err) throw new Error(err.message);
        setAccounts((data ?? []) as CoaRow[]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const unmapped = accounts.filter(a => a.is_active && !a.schedule_iii_mapping);

  if (loading) return <div className="p-6 animate-pulse space-y-4">{[1,2,3].map(i => <div key={i} className="h-24 bg-[#F1F5F9] rounded-xl" />)}</div>;
  if (error) return <div className="p-6"><div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div></div>;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting/chart-of-accounts" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2">
            <GitBranch size={18} className="text-blue-600" /> Schedule III Mapping
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            {accounts.filter(a => a.is_active && a.schedule_iii_mapping).length} of {accounts.filter(a => a.is_active).length} active accounts mapped
          </p>
        </div>
        <Link href="/accounting/chart-of-accounts" className="text-xs text-blue-600 hover:underline">
          Edit mappings in COA →
        </Link>
      </div>

      {unmapped.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <p className="text-xs font-medium text-amber-800">{unmapped.length} active accounts have no Schedule III mapping</p>
          <p className="text-xs text-amber-700 mt-0.5">Edit each account in Chart of Accounts to assign a mapping.</p>
        </div>
      )}

      <div className="space-y-6">
        {SCHEDULE_III_SECTIONS.map(({ heading, items }) => (
          <div key={heading}>
            <h2 className="text-xs font-semibold text-[#475569] uppercase tracking-wider mb-3">{heading}</h2>
            <div className="space-y-2">
              {items.map(mapping => {
                const mapped = accounts.filter(a => a.schedule_iii_mapping === mapping && a.is_active);
                return (
                  <div key={mapping} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-[#F8FAFC] flex items-center justify-between">
                      <span className="text-xs font-semibold text-[#334155]">{mapping}</span>
                      <span className="text-[10px] text-[#94A3B8]">{mapped.length} account{mapped.length !== 1 ? "s" : ""}</span>
                    </div>
                    {mapped.length === 0 ? (
                      <div className="px-4 py-2 text-[10px] text-[#94A3B8] italic">No accounts mapped</div>
                    ) : (
                      <table className="w-full text-xs">
                        <tbody className="divide-y divide-[#F8FAFC]">
                          {mapped.map(acc => (
                            <tr key={acc.id} className="hover:bg-[#F8FAFC]">
                              <td className="px-4 py-2 font-mono text-[10px] text-[#94A3B8] w-16">{acc.account_code}</td>
                              <td className="px-3 py-2 font-medium text-[#0F172A]">{acc.account_name}</td>
                              <td className="px-3 py-2 text-[#64748B]">{acc.account_type}</td>
                              <td className="px-4 py-2 text-[#64748B]">{acc.tax_category ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {unmapped.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-amber-700 uppercase tracking-wider mb-3">Unmapped Accounts</h2>
            <div className="bg-white rounded-xl border border-amber-200 overflow-hidden">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-[#F8FAFC]">
                  {unmapped.map(acc => (
                    <tr key={acc.id} className="hover:bg-amber-50">
                      <td className="px-4 py-2 font-mono text-[10px] text-[#94A3B8] w-16">{acc.account_code}</td>
                      <td className="px-3 py-2 font-medium text-[#0F172A]">{acc.account_name}</td>
                      <td className="px-3 py-2 text-[#64748B]">{acc.account_type}</td>
                      <td className="px-4 py-2">
                        <Link href="/accounting/chart-of-accounts" className="text-blue-600 hover:underline text-[10px]">Add mapping →</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

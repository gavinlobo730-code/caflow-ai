"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Layers } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TableSkeleton } from "@/components/ui/skeleton";

interface CoaRow {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  account_subtype: string | null;
  parent_group: string | null;
  sub_group: string | null;
  is_active: boolean;
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

export default function AccountGroupsPage() {
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
          .select("id, account_code, account_name, account_type, account_subtype, parent_group, sub_group, is_active")
          .eq("firm_id", fid)
          .is("client_id", null)
          .eq("is_active", true)
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

  if (loading) return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
    </div>
  );
  if (error) return <div className="p-6"><div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div></div>;

  // Group by parent_group → sub_group
  const grouped: Record<string, Record<string, CoaRow[]>> = {};
  for (const acc of accounts) {
    const pg = acc.parent_group ?? "Ungrouped";
    const sg = acc.sub_group ?? "General";
    if (!grouped[pg]) grouped[pg] = {};
    if (!grouped[pg][sg]) grouped[pg][sg] = [];
    grouped[pg][sg].push(acc);
  }
  const parentGroups = Object.keys(grouped).sort();

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2">
            <Layers size={18} className="text-blue-600" /> Account Groups
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            {parentGroups.length} parent groups · {accounts.length} active accounts
          </p>
        </div>
      </div>

      <div className="space-y-5">
        {parentGroups.map(pg => {
          const subGroups = Object.keys(grouped[pg]).sort();
          const total = subGroups.reduce((n, sg) => n + grouped[pg][sg].length, 0);
          return (
            <div key={pg} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9] flex items-center justify-between">
                <span className="text-sm font-semibold text-[#334155]">{pg}</span>
                <span className="text-xs text-[#94A3B8]">{total} accounts</span>
              </div>
              {subGroups.map(sg => (
                <div key={sg}>
                  <div className="px-5 py-2 border-b border-[#F8FAFC] flex items-center justify-between bg-[#FAFAFA]">
                    <span className="text-xs font-medium text-[#475569]">{sg}</span>
                    <span className="text-[10px] text-[#94A3B8]">{grouped[pg][sg].length}</span>
                  </div>
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {grouped[pg][sg].map(acc => (
                        <tr key={acc.id} className="hover:bg-[#F8FAFC]">
                          <td className="px-5 py-2 font-mono text-[10px] text-[#94A3B8] w-16">{acc.account_code}</td>
                          <td className="px-3 py-2 font-medium text-[#0F172A]">{acc.account_name}</td>
                          <td className="px-3 py-2 text-[#64748B]">{acc.account_type}</td>
                          <td className="px-5 py-2 text-[#94A3B8]">{acc.account_subtype ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

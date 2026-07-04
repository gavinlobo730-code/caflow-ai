"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, Download, FileText } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

interface CoaRow {
  account_code: string;
  account_name: string;
  account_type: string;
  account_subtype: string | null;
  parent_group: string | null;
  sub_group: string | null;
  tax_category: string | null;
  schedule_iii_mapping: string | null;
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

function toCSV(rows: CoaRow[]): string {
  const headers = ["account_code", "account_name", "account_type", "account_subtype", "parent_group", "sub_group", "tax_category", "schedule_iii_mapping", "is_active"];
  const escape = (v: string | boolean | null) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push([
      r.account_code, r.account_name, r.account_type,
      r.account_subtype, r.parent_group, r.sub_group,
      r.tax_category, r.schedule_iii_mapping, r.is_active,
    ].map(escape).join(","));
  }
  return lines.join("\n");
}

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CoaExportPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  async function doExport(format: "csv") {
    setLoading(true);
    setError(null);
    try {
      const fid = await getFirmId();
      const sb = getSupabaseClient();
      let query = sb
        .from("chart_of_accounts")
        .select("account_code, account_name, account_type, account_subtype, parent_group, sub_group, tax_category, schedule_iii_mapping, is_active")
        .eq("firm_id", fid)
        .is("client_id", null)
        .order("account_code");
      if (!includeArchived) query = query.eq("is_active", true);
      const { data, error: err } = await query;
      if (err) throw new Error(err.message);
      const rows = (data ?? []) as CoaRow[];
      setCount(rows.length);
      const today = new Date().toISOString().slice(0, 10);
      if (format === "csv") {
        downloadFile(toCSV(rows), `chart-of-accounts-${today}.csv`, "text/csv");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Export Chart of Accounts</h1>
          <p className="text-xs text-[#64748B] mt-0.5">Download your firm&apos;s master COA as CSV</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-[#F1F5F9] p-6 space-y-5">
        <div className="flex items-center gap-3 p-4 bg-[#F8FAFC] rounded-lg">
          <FileText size={20} className="text-blue-600" />
          <div>
            <p className="text-sm font-medium text-[#334155]">chart-of-accounts.csv</p>
            <p className="text-xs text-[#64748B] mt-0.5">
              Includes: Code, Name, Type, Sub-type, Parent Group, Sub Group, Tax Category, Schedule III Mapping, Status
            </p>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={e => setIncludeArchived(e.target.checked)}
            className="rounded border-[#CBD5E1]"
          />
          <span className="text-sm text-[#475569]">Include archived accounts</span>
        </label>

        {error && <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md">{error}</p>}

        {count !== null && !loading && (
          <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded-md flex items-center gap-1.5">
            ✅ Exported {count} accounts successfully
          </p>
        )}

        <button
          onClick={() => doExport("csv")}
          disabled={loading}
          className="flex items-center gap-2 text-sm bg-blue-600 text-white px-5 py-2.5 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          <Download size={14} />
          {loading ? "Preparing…" : "Download CSV"}
        </button>
      </div>

      <p className="text-xs text-[#94A3B8]">
        The exported file is compatible with the Import COA tool — useful for backup or migrating to another firm.
      </p>
    </div>
  );
}

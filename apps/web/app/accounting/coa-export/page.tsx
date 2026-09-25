"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, Download, FileText } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { todayLocalISO } from "@/lib/dateMath";
import { Callout } from "@/components/ui/callout";
import { downloadCsv, toCsvRows } from "@/lib/export/csv";

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


function toCSV(rows: CoaRow[]): string {
  const headers = ["account_code", "account_name", "account_type", "account_subtype", "parent_group", "sub_group", "tax_category", "schedule_iii_mapping", "is_active"];
  return toCsvRows([headers, ...rows.map((r) => [
    r.account_code, r.account_name, r.account_type,
    r.account_subtype, r.parent_group, r.sub_group,
    r.tax_category, r.schedule_iii_mapping, r.is_active,
  ])]);
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
      // This read IS the export: one CSV line per account, downloaded and
      // opened in a spreadsheet. PostgREST caps a response at ~1000 rows and
      // reports nothing when it does, so an unpaged read hands the CA a chart
      // of accounts missing however many rows the cap removed — and the count
      // shown beside the button would agree with the short file. A firm-level
      // chart with per-client sub-ledgers reaches 1000 accounts.
      //
      // `.order("id")` is the unique tiebreaker selectAll's OFFSET paging needs
      // for a stable total ordering; it does not have to be in the projection
      // and is not exported, so the CSV's columns are unchanged.
      const { data, error: err } = await selectAll(() => {
        let query = sb
          .from("chart_of_accounts")
          .select("account_code, account_name, account_type, account_subtype, parent_group, sub_group, tax_category, schedule_iii_mapping, is_active")
          .eq("firm_id", fid)
          .is("client_id", null);
        if (!includeArchived) query = query.eq("is_active", true);
        return query.order("account_code").order("id");
      });
      if (err) throw new Error(err.message);
      const rows = (data ?? []) as CoaRow[];
      setCount(rows.length);
      const today = todayLocalISO();
      if (format === "csv") {
        downloadCsv(`chart-of-accounts-${today}.csv`, toCSV(rows));
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
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Export Chart of Accounts</h1>
          <p className="text-xs text-ps-label mt-0.5">Download your firm&apos;s master COA as CSV</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-ps-border p-6 space-y-5">
        <div className="flex items-center gap-3 p-4 bg-ps-bg rounded-lg">
          <FileText size={20} className="text-blue-600" />
          <div>
            <p className="text-sm font-medium text-ps-body">chart-of-accounts.csv</p>
            <p className="text-xs text-ps-label mt-0.5">
              Includes: Code, Name, Type, Sub-type, Parent Group, Sub Group, Tax Category, Schedule III Mapping, Status
            </p>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={e => setIncludeArchived(e.target.checked)}
            className="rounded border-ps-border-strong"
          />
          <span className="text-sm text-ps-label">Include archived accounts</span>
        </label>

        {error && <Callout tone="problem">{error}</Callout>}

        {count !== null && !loading && (
          <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded-md flex items-center gap-1.5">
            ✅ Exported {count} accounts successfully
          </p>
        )}

        <button
          onClick={() => doExport("csv")}
          disabled={loading}
          className="flex items-center gap-2 text-sm bg-brand text-white px-5 py-2.5 rounded-md hover:bg-brand-dark disabled:opacity-50"
        >
          <Download size={14} />
          {loading ? "Preparing…" : "Download CSV"}
        </button>
      </div>

      <p className="text-xs text-ps-hint">
        The exported file is compatible with the Import COA tool — useful for backup or migrating to another firm.
      </p>
    </div>
  );
}

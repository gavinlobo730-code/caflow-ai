"use client";

import { useState, useEffect, useCallback } from "react";
import { ClipboardList, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

type Bucket = { paise: number; count: number };
interface Aging {
  buckets: Record<string, Bucket>;
  total_outstanding_paise: number;
  overdue_paise: number;
  overdue_count: number;
}

const ORDER: { key: string; label: string }[] = [
  { key: "not_due", label: "Current / Not due" },
  { key: "0-30", label: "0–30 days" },
  { key: "31-60", label: "31–60 days" },
  { key: "61-90", label: "61–90 days" },
  { key: "90+", label: "90+ days" },
];

function ARDashboard() {
  const [aging, setAging] = useState<Aging | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.billing.arAging() as ApiResp<Aging>;
      setAging(r.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load AR aging");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading AR aging…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  const buckets = aging?.buckets ?? {};
  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <ClipboardList size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">AR Aging</h1>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-[12px] text-gray-500 hover:text-[#182350]">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-gray-500 border-b border-gray-200">
              <th className="px-4 py-2.5 font-medium">Bucket</th>
              <th className="px-4 py-2.5 font-medium text-right">Outstanding</th>
              <th className="px-4 py-2.5 font-medium text-right">Invoices</th>
            </tr>
          </thead>
          <tbody>
            {ORDER.map(({ key, label }) => (
              <tr key={key} className="border-b border-gray-100 last:border-0">
                <td className="px-4 py-2.5 text-[#182350]">{label}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(buckets[key]?.paise ?? 0)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-gray-500">{buckets[key]?.count ?? 0}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-[#F8FAFC] font-semibold">
              <td className="px-4 py-2.5 text-[#182350]">Total outstanding</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(aging?.total_outstanding_paise ?? 0)}</td>
              <td className="px-4 py-2.5"></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-[12px] text-gray-500 mt-3">
        Overdue: <span className="font-medium text-red-600">{formatPaise(aging?.overdue_paise ?? 0)}</span>
        {" "}across {aging?.overdue_count ?? 0} invoice(s). Aging is due-date based, computed server-side.
      </p>
    </div>
  );
}

export default function ARPage() {
  return <PartnerGuard><ARDashboard /></PartnerGuard>;
}

"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { yearEndApi } from "@/lib/api/yearEnd";

/** Format paise → ₹ Indian number format */
function fmt(paise: number): string {
  if (paise === 0) return "—";
  return (
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Math.abs(paise) / 100)
  );
}

type ScheduleType = "cash_bank" | "receivables" | "payables" | "fixed_assets" | "gst" | "tds" | "loans";

const SCHEDULE_TABS: { id: ScheduleType; label: string }[] = [
  { id: "cash_bank", label: "Cash & Bank" },
  { id: "receivables", label: "Receivables" },
  { id: "payables", label: "Payables" },
  { id: "fixed_assets", label: "Fixed Assets" },
  { id: "gst", label: "GST" },
  { id: "tds", label: "TDS" },
  { id: "loans", label: "Loans" },
];

interface ScheduleRow {
  [key: string]: string | number | null;
}

interface ScheduleData {
  columns: { key: string; label: string; type?: "amount" | "text" | "date" }[];
  rows: ScheduleRow[];
  totals?: Record<string, number>;
}

// GET /api/year-end/{id}/schedules/{type}
async function fetchSchedule(engagementId: string, type: ScheduleType): Promise<ScheduleData> {
  // Use the shared yearEndApi request pattern
  const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${BASE_URL}/api/year-end/engagements/${engagementId}/schedules/${type}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "Failed to load schedule");
  return json.data;
}

export default function SchedulesPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [tab, setTab] = useState<ScheduleType>("cash_bank");
  const [scheduleData, setScheduleData] = useState<Record<ScheduleType, ScheduleData | null>>({
    cash_bank: null,
    receivables: null,
    payables: null,
    fixed_assets: null,
    gst: null,
    tds: null,
    loans: null,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTab = useCallback(async (type: ScheduleType) => {
    // Don't reload if already loaded
    if (scheduleData[type]) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSchedule(engagementId, type);
      setScheduleData((prev) => ({ ...prev, [type]: data }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  }, [engagementId, scheduleData]);

  useEffect(() => {
    loadTab(tab);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, engagementId]);

  function forceReload() {
    setScheduleData((prev) => ({ ...prev, [tab]: null }));
    setError(null);
    setLoading(false);
    // Trigger reload by clearing then re-fetching
    setTimeout(() => loadTab(tab), 0);
  }

  const currentData = scheduleData[tab];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {SCHEDULE_TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        <div className="max-w-5xl space-y-3">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-[#334155]">
                {SCHEDULE_TABS.find((t) => t.id === tab)?.label} Schedule
              </p>
              <p className="text-[10px] text-[#94A3B8] mt-0.5">
                All values derived from the General Ledger.
              </p>
            </div>
            <button
              onClick={forceReload}
              className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
              title="Refresh"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>

          {/* Content */}
          {loading && !currentData ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />
              ))}
            </div>
          ) : error ? (
            <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
              {error}
              <button onClick={forceReload} className="ml-3 underline text-xs">Retry</button>
            </div>
          ) : currentData ? (
            <ScheduleTable data={currentData} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Schedule Table ─────────────────────────────────────────────────────────

function ScheduleTable({ data }: { data: ScheduleData }) {
  const { columns, rows, totals } = data;

  if (!rows.length) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
        <p className="text-sm text-[#64748B]">No data for this schedule.</p>
        <p className="text-xs text-[#94A3B8] mt-1">
          Data will appear when transactions are posted to the General Ledger.
        </p>
      </div>
    );
  }

  function renderCell(value: string | number | null, colType?: string): string {
    if (value === null || value === undefined) return "—";
    if (colType === "amount" && typeof value === "number") return fmt(value);
    return String(value);
  }

  function isTotalAmount(colType?: string, v?: number | null): boolean {
    return colType === "amount" && typeof v === "number";
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-3 font-semibold ${col.type === "amount" ? "text-right" : "text-left"}`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {rows.map((row, ri) => (
              <tr key={ri} className="hover:bg-[#F8FAFC]">
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-4 py-2.5 ${
                      col.type === "amount"
                        ? "text-right font-mono text-[#334155]"
                        : "text-[#334155]"
                    }`}
                  >
                    {renderCell(row[col.key] as string | number | null, col.type)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {totals && Object.keys(totals).length > 0 && (
            <tfoot>
              <tr className="border-t-2 border-[#E2E8F0] font-semibold bg-[#F8FAFC]">
                {columns.map((col, ci) => (
                  <td
                    key={col.key}
                    className={`px-4 py-2.5 ${col.type === "amount" ? "text-right font-mono text-[#0F172A]" : "text-[#334155]"}`}
                  >
                    {ci === 0
                      ? "Total"
                      : isTotalAmount(col.type, totals[col.key])
                      ? fmt(totals[col.key] as number)
                      : ""}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

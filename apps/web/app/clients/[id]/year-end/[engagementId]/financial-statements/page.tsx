"use client";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { RefreshCw, Camera, ChevronDown, ChevronRight } from "lucide-react";
import { yearEndApi, type FinancialStatementVersion } from "@/lib/api/yearEnd";

/** Format paise → ₹ Indian number format (Companies Act §128: accounts in INR) */
function fmt(paise: number): string {
  if (paise === 0) return "—";
  const abs = Math.abs(paise);
  return (
    (paise < 0 ? "(" : "") +
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(abs / 100) +
    (paise < 0 ? ")" : "")
  );
}

type FinTab = "balance_sheet" | "profit_loss";

// Schedule III BS group type
interface BSGroup {
  label: string;
  items: { name: string; amount_paise: number }[];
  total_paise: number;
}

interface PLLine {
  label: string;
  amount_paise: number;
  is_subtotal?: boolean;
  is_total?: boolean;
  is_negative?: boolean;
}

export default function FinancialStatementsPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [tab, setTab] = useState<FinTab>("balance_sheet");
  const [liveData, setLiveData] = useState<{
    balance_sheet: Record<string, unknown>;
    profit_loss: Record<string, unknown>;
    is_balanced: boolean;
  } | null>(null);
  const [versions, setVersions] = useState<FinancialStatementVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("live");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [snapshotting, setSnapshotting] = useState(false);
  const [snapshotMsg, setSnapshotMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [liveRes, verRes] = await Promise.all([
        yearEndApi.financialStatements.getLive(engagementId),
        yearEndApi.financialStatements.versions(engagementId),
      ]);
      if (!liveRes.success) throw new Error(liveRes.error ?? "Failed to load statements");
      setLiveData(liveRes.data);
      setVersions(verRes.data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  async function handleSnapshot() {
    setSnapshotting(true);
    setSnapshotMsg(null);
    try {
      const res = await yearEndApi.financialStatements.createSnapshot(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to create snapshot");
      setVersions((prev) => [res.data, ...prev]);
      setSelectedVersionId(res.data.id);
      setSnapshotMsg(`Version ${res.data.version_number} snapshot created.`);
    } catch (err) {
      setSnapshotMsg(err instanceof Error ? err.message : "Snapshot failed");
    } finally {
      setSnapshotting(false);
    }
  }

  // Determine which data to display
  const activeVersion = selectedVersionId === "live"
    ? null
    : versions.find((v) => v.id === selectedVersionId) ?? null;

  const bs = activeVersion
    ? activeVersion.balance_sheet
    : liveData?.balance_sheet ?? {};

  const pl = activeVersion
    ? activeVersion.profit_loss
    : liveData?.profit_loss ?? {};

  const isBalanced = activeVersion ? activeVersion.is_balanced : (liveData?.is_balanced ?? false);

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-32 rounded-xl bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl">
      {/* Top bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]"
        >
          <RefreshCw size={12} /> Refresh from Ledger
        </button>
        <button
          onClick={handleSnapshot}
          disabled={snapshotting}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {snapshotting ? <RefreshCw size={12} className="animate-spin" /> : <Camera size={12} />}
          Create Snapshot
        </button>

        {/* Version selector */}
        {versions.length > 0 && (
          <select
            value={selectedVersionId}
            onChange={(e) => setSelectedVersionId(e.target.value)}
            className="text-xs border border-[#E2E8F0] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="live">Live (Current)</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number} — {new Date(v.generated_at).toLocaleDateString("en-IN")}
              </option>
            ))}
          </select>
        )}

        {/* Balance indicator */}
        <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${isBalanced ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
          {isBalanced ? "✓ Balanced" : "✗ Not Balanced"}
        </span>
      </div>

      {snapshotMsg && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-xs text-blue-700">
          {snapshotMsg}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
        {(["balance_sheet", "profit_loss"] as FinTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === t ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {t === "balance_sheet" ? "Balance Sheet" : "Profit & Loss"}
          </button>
        ))}
      </div>

      {tab === "balance_sheet" && <BalanceSheetView data={bs} />}
      {tab === "profit_loss" && <ProfitLossView data={pl} />}

      <p className="text-[10px] text-[#94A3B8]">
        All values derived from the General Ledger. Companies Act 2013, Schedule III.
      </p>
    </div>
  );
}

// ── Balance Sheet (Schedule III, Part I) ──────────────────────────────────

function BalanceSheetView({ data }: { data: Record<string, unknown> }) {
  // The backend sends structured groups; we render them generically
  const equityLiabilities = (data.equity_liabilities as BSGroup[]) ?? [];
  const assets = (data.assets as BSGroup[]) ?? [];

  const totalEL = (data.total_equity_liabilities_paise as number) ?? 0;
  const totalAssets = (data.total_assets_paise as number) ?? 0;

  if (!equityLiabilities.length && !assets.length) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
        <p className="text-sm text-[#64748B]">No data available. Refresh from ledger.</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Equity & Liabilities */}
      <StatementCard title="I. Equity & Liabilities" groups={equityLiabilities} grandTotal={totalEL} />
      {/* Assets */}
      <StatementCard title="II. Assets" groups={assets} grandTotal={totalAssets} />
    </div>
  );
}

function StatementCard({
  title,
  groups,
  grandTotal,
}: {
  title: string;
  groups: BSGroup[];
  grandTotal: number;
}) {
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-4 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
        <p className="text-[10px] font-bold text-[#475569] uppercase tracking-wide">{title}</p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
            <th className="px-4 py-2 text-left font-semibold">Particulars</th>
            <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group, gi) => (
            <GroupRows key={gi} group={group} />
          ))}
          <tr className="border-t-2 border-[#E2E8F0] font-bold bg-[#F8FAFC]">
            <td className="px-4 py-2.5 text-[#0F172A] text-sm">Total</td>
            <td className="px-4 py-2.5 text-right font-mono text-[#0F172A] text-sm">{fmt(grandTotal)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ group }: { group: BSGroup }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <tr
        className="cursor-pointer hover:bg-[#F8FAFC] border-t border-[#F8FAFC]"
        onClick={() => setOpen((o) => !o)}
      >
        <td className="px-4 py-2 font-semibold text-[#334155] flex items-center gap-1">
          {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          {group.label}
        </td>
        <td className="px-4 py-2 text-right font-mono font-semibold text-[#334155]">
          {fmt(group.total_paise)}
        </td>
      </tr>
      {open && group.items.map((item, i) => (
        <tr key={i} className="text-[#94A3B8]">
          <td className="px-4 py-1.5 pl-8">{item.name}</td>
          <td className="px-4 py-1.5 text-right font-mono">{fmt(item.amount_paise)}</td>
        </tr>
      ))}
    </>
  );
}

// ── Profit & Loss (Schedule III, Part II) ─────────────────────────────────

function ProfitLossView({ data }: { data: Record<string, unknown> }) {
  const lines = (data.lines as PLLine[]) ?? [];

  if (!lines.length) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
        <p className="text-sm text-[#64748B]">No data available. Refresh from ledger.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
        <p className="text-[10px] font-bold text-[#475569] uppercase tracking-wide">
          Statement of Profit &amp; Loss
        </p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
            <th className="px-5 py-2 text-left font-semibold">Particulars</th>
            <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, i) => {
            if (line.is_total) {
              return (
                <tr key={i} className={`border-t-2 border-[#E2E8F0] font-bold ${(line.amount_paise ?? 0) >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                  <td className="px-5 py-2.5 text-[#0F172A] text-sm">{line.label}</td>
                  <td className={`px-4 py-2.5 text-right font-mono text-sm ${(line.amount_paise ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>
                    {fmt(line.amount_paise ?? 0)}
                  </td>
                </tr>
              );
            }
            if (line.is_subtotal) {
              return (
                <tr key={i} className="border-t border-[#E2E8F0] font-semibold">
                  <td className="px-5 py-2 text-[#1E293B]">{line.label}</td>
                  <td className="px-4 py-2 text-right font-mono text-[#0F172A]">{fmt(line.amount_paise ?? 0)}</td>
                </tr>
              );
            }
            if (!line.amount_paise && line.label.startsWith("I.")) {
              // Section header
              return (
                <tr key={i} className="bg-[#F8FAFC]">
                  <td colSpan={2} className="px-5 py-2 text-[10px] font-semibold uppercase tracking-wide text-[#334155]">
                    {line.label}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={i} className="hover:bg-[#F8FAFC]">
                <td className="px-5 py-2 text-[#475569] pl-8">{line.label}</td>
                <td className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(line.amount_paise ?? 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

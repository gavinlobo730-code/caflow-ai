"use client";

import { useState, useEffect, useCallback } from "react";
import { Building2, RefreshCw, IndianRupee, AlertTriangle, Wallet, ReceiptText } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

interface DashboardData {
  total_receivable_paise: number;
  overdue_paise: number;
  overdue_count: number;
  tds_receivable_paise: number;
  collected_cash_paise: number;
}

function KpiCard({ label, value, icon: Icon, tone }: {
  label: string; value: string; icon: typeof IndianRupee; tone?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <Icon size={15} className={tone ?? "text-gray-400"} />
      </div>
      <p className="text-xl font-semibold text-[#182350] mt-2 tabular-nums">{value}</p>
    </div>
  );
}

function PracticeOverview() {
  const [provisioned, setProvisioned] = useState<boolean | null>(null);
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provisioning, setProvisioning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const p = await api.practice.get() as ApiResp<{ provisioned: boolean }>;
      setProvisioned(p.data?.provisioned ?? false);
      if (p.data?.provisioned) {
        const d = await api.billing.dashboard() as ApiResp<DashboardData>;
        setDash(d.data);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Practice");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function provision() {
    setProvisioning(true);
    try { await api.practice.provision(); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Provisioning failed"); }
    finally { setProvisioning(false); }
  }

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading Practice…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  if (provisioned === false) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-12 text-center">
        <div className="w-12 h-12 rounded-full bg-[#182350]/10 flex items-center justify-center mb-4">
          <Building2 size={20} className="text-[#182350]" />
        </div>
        <h2 className="text-base font-semibold text-[#182350]">Set up your Practice</h2>
        <p className="text-sm text-gray-500 mt-1 max-w-sm">
          Provision the firm-as-internal-client to start Revenue Operations
          (billing, collections, AR) for your own firm.
        </p>
        <button onClick={provision} disabled={provisioning}
          className="mt-4 px-4 py-2 rounded-lg bg-[#182350] text-white text-sm font-medium disabled:opacity-50">
          {provisioning ? "Setting up…" : "Set up Practice"}
        </button>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Building2 size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Practice — Revenue Overview</h1>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-[12px] text-gray-500 hover:text-[#182350]">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <KpiCard label="Total Receivable" value={formatPaise(dash?.total_receivable_paise ?? 0)} icon={IndianRupee} tone="text-blue-500" />
        <KpiCard label="Overdue" value={`${formatPaise(dash?.overdue_paise ?? 0)} (${dash?.overdue_count ?? 0})`} icon={AlertTriangle} tone="text-red-500" />
        <KpiCard label="TDS Receivable" value={formatPaise(dash?.tds_receivable_paise ?? 0)} icon={ReceiptText} tone="text-amber-500" />
        <KpiCard label="Collected (cash)" value={formatPaise(dash?.collected_cash_paise ?? 0)} icon={Wallet} tone="text-green-600" />
      </div>
      <p className="text-[11px] text-gray-400 mt-4">
        All figures computed server-side from the internal client&apos;s books. Partner-only.
      </p>
    </div>
  );
}

export default function PracticePage() {
  return <PartnerGuard><PracticeOverview /></PartnerGuard>;
}

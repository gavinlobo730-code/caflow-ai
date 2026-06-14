"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { IndianRupee, RefreshCw, Receipt, Wallet, ClipboardList } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

interface DashboardData {
  total_receivable_paise: number; overdue_paise: number; overdue_count: number;
  tds_receivable_paise: number; collected_cash_paise: number;
}

function Revenue() {
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [activeSchedules, setActiveSchedules] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const d = await api.billing.dashboard() as ApiResp<DashboardData>;
      setDash(d.data);
      const s = await api.billing.listSchedules(true) as ApiResp<unknown[]>;
      setActiveSchedules((s.data ?? []).length);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load revenue"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading revenue…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  const cards = [
    { label: "Total Receivable", value: formatPaise(dash?.total_receivable_paise ?? 0) },
    { label: "Overdue", value: `${formatPaise(dash?.overdue_paise ?? 0)} (${dash?.overdue_count ?? 0})` },
    { label: "TDS Receivable", value: formatPaise(dash?.tds_receivable_paise ?? 0) },
    { label: "Collected (cash)", value: formatPaise(dash?.collected_cash_paise ?? 0) },
    { label: "Active Schedules", value: String(activeSchedules) },
  ];
  const links = [
    { href: "/practice/billing", label: "Billing", icon: Receipt },
    { href: "/practice/collections", label: "Collections", icon: Wallet },
    { href: "/practice/ar", label: "AR Aging", icon: ClipboardList },
  ];

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <IndianRupee size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Revenue Dashboard</h1>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-[12px] text-gray-500 hover:text-[#182350]">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
        {cards.map((c) => (
          <div key={c.label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-[11px] text-gray-500 uppercase tracking-wide">{c.label}</p>
            <p className="text-base font-semibold text-[#182350] tabular-nums mt-1.5">{c.value}</p>
          </div>
        ))}
      </div>
      <div className="flex gap-3">
        {links.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-200 text-sm text-[#182350] hover:bg-[#F8FAFC]">
            <Icon size={14} /> {label}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function RevenuePage() {
  return <PartnerGuard><Revenue /></PartnerGuard>;
}

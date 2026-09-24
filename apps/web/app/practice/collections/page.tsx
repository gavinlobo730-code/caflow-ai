"use client";

import { useState, useEffect, useCallback } from "react";
import { Wallet, RefreshCw, Bell, Activity } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

interface DashboardData {
  total_receivable_paise: number; overdue_paise: number; overdue_count: number;
  tds_receivable_paise: number; collected_cash_paise: number;
}

function Collections() {
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const d = await api.billing.dashboard() as ApiResp<DashboardData>;
      setDash(d.data);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load collections"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // "Flag for follow-up" is NOT a send, and the wording is the fix. The button
  // read "Send reminders" and the toast read "N reminder(s) sent" over an
  // endpoint that emails nobody — it writes a Timeline note and a counter. A CA
  // could press it, read that, and believe their clients had been chased.
  // The customer-facing reminder lives on the client's own Sales tab.
  async function run(action: "sweep" | "followups") {
    setBusy(true); setMsg(null);
    try {
      if (action === "sweep") {
        const r = await api.billing.sweep() as ApiResp<{ swept: number }>;
        setMsg(`Overdue sweep complete (${r.data?.swept ?? 0} invoices assessed).`);
      } else {
        const r = await api.billing.flagOverdueForFollowup() as
          ApiResp<{ invoices_flagged_for_followup: number }>;
        const n = r.data?.invoices_flagged_for_followup ?? 0;
        setMsg(`${n} invoice${n === 1 ? "" : "s"} flagged for follow-up. Nothing was sent.`);
      }
      await load();
    } catch (e) { setMsg(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading collections…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Wallet size={18} className="text-brand" />
          <h1 className="text-lg font-semibold text-brand">Collections</h1>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {msg && <div className="mb-3 text-xs px-3 py-2 rounded-lg bg-blue-50 text-blue-700">{msg}</div>}

      <div className="grid grid-cols-3 gap-3 mb-5">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-2xs text-gray-500 uppercase">Overdue</p>
          <p className="text-lg font-semibold text-red-600 tabular-nums mt-1">{formatPaise(dash?.overdue_paise ?? 0)}</p>
          <p className="text-2xs text-gray-400">{dash?.overdue_count ?? 0} invoice(s)</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-2xs text-gray-500 uppercase">Total receivable</p>
          <p className="text-lg font-semibold text-brand tabular-nums mt-1">{formatPaise(dash?.total_receivable_paise ?? 0)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-2xs text-gray-500 uppercase">Collected (cash)</p>
          <p className="text-lg font-semibold text-green-600 tabular-nums mt-1">{formatPaise(dash?.collected_cash_paise ?? 0)}</p>
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={() => run("sweep")} disabled={busy}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-200 text-sm text-brand hover:bg-ps-bg disabled:opacity-50">
          <Activity size={14} /> Run overdue sweep
        </button>
        <button onClick={() => run("followups")} disabled={busy}
          title="Writes a Timeline note against each overdue fee invoice. No email is sent."
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-brand text-white text-sm disabled:opacity-50">
          <Bell size={14} /> Flag for follow-up
        </button>
      </div>
      <p className="text-2xs text-gray-400 mt-4">
        Both actions are on the practice&apos;s own fee invoices only. Flagging is cadence-gated
        and recorded to the internal client&apos;s Timeline &mdash; <strong>nothing is emailed</strong>.
        To email a customer, open that client&apos;s Sales tab and use Remind. Overdue is derived
        server-side.
      </p>
    </div>
  );
}

export default function CollectionsPage() {
  return <PartnerGuard><Collections /></PartnerGuard>;
}

"use client";

// Phase 4.5.1 — Customer Portal dashboard SHELL (foundation only).
// Renders the section scaffold returned by the server (no invoice / statement /
// compliance data yet — those arrive in Phase 4.5.2+). Auth is the client's own
// Supabase session, resolved server-side via get_current_portal_client.

import { useState, useEffect } from "react";
import { FileText, FolderOpen, MessageSquare, Receipt, ScrollText, BellRing, ShieldCheck, Lock, type LucideIcon } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";

interface Section { key: string; label: string; available: boolean }
interface Dashboard { client_id: string; contact: { email: string | null; name: string | null }; sections: Section[] }
interface Membership { client_id: string; name: string | null }

const ICONS: Record<string, LucideIcon> = {
  documents: FolderOpen, requests: FileText, messages: MessageSquare,
  invoices: Receipt, statements: ScrollText, reminders: BellRing, compliance: ShieldCheck,
};

export default function PortalDashboardPage() {
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeClient, setActiveClient] = useState<string | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // 1. Resolve the identity's client memberships (one identity → many clients).
  useEffect(() => {
    (async () => {
      try {
        const res = await api.portalSelf.memberships() as ApiResp<{ memberships: Membership[] }>;
        const ms = res.data?.memberships ?? [];
        setMemberships(ms);
        if (ms.length === 1) setActiveClient(ms[0].client_id);   // single → auto; multiple → user picks
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to load your portal");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // 2. Load the dashboard for the explicitly-selected client (never implicit).
  useEffect(() => {
    if (!activeClient) return;
    (async () => {
      try {
        const res = await api.portalSelf.dashboard(activeClient) as ApiResp<Dashboard>;
        setDash(res.data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to load your portal");
      }
    })();
  }, [activeClient]);

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading your portal…</div>;
  if (error) {
    return (
      <div className="p-8 max-w-md">
        <p className="text-sm text-red-600">{error}</p>
        <p className="text-xs text-gray-400 mt-2">If you believe you should have access, ask your accountant to invite you.</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-[#182350]">Your Portal</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Welcome{dash?.contact.name ? `, ${dash.contact.name}` : ""}. Your secure workspace with your accountant.
          </p>
        </div>
        {memberships.length > 1 && (
          <label className="text-xs text-gray-600">
            <span className="block text-[11px] text-gray-400 mb-0.5">Client</span>
            <select
              value={activeClient ?? ""}
              onChange={(e) => { setDash(null); setActiveClient(e.target.value || null); }}
              className="border border-gray-200 rounded-lg px-2 py-1 text-xs text-[#182350]">
              <option value="">Select a client…</option>
              {memberships.map((m) => <option key={m.client_id} value={m.client_id}>{m.name ?? m.client_id}</option>)}
            </select>
          </label>
        )}
      </div>

      {memberships.length > 1 && !activeClient ? (
        <div className="bg-[#F8FAFC] border border-dashed border-gray-200 rounded-xl p-8 text-center text-sm text-gray-500">
          You have access to {memberships.length} clients. Choose one above to continue.
        </div>
      ) : !dash ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {(dash?.sections ?? []).map((s) => {
          const Icon = ICONS[s.key] ?? FileText;
          return (
            <div key={s.key}
              className={`rounded-xl border p-4 ${s.available
                ? "bg-white border-gray-200"
                : "bg-[#F8FAFC] border-dashed border-gray-200"}`}>
              <div className="flex items-center justify-between">
                <Icon size={18} className={s.available ? "text-[#182350]" : "text-gray-300"} />
                {!s.available && <Lock size={12} className="text-gray-300" />}
              </div>
              <p className={`mt-2 text-sm font-medium ${s.available ? "text-[#182350]" : "text-gray-400"}`}>{s.label}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{s.available ? "Available" : "Coming soon"}</p>
            </div>
          );
        })}
      </div>
      )}

      <p className="text-[11px] text-gray-400 mt-5">
        This is your portal home. Invoice, statement, payment-reminder, and compliance views are being rolled out.
      </p>
    </div>
  );
}

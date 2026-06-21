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

const ICONS: Record<string, LucideIcon> = {
  documents: FolderOpen, requests: FileText, messages: MessageSquare,
  invoices: Receipt, statements: ScrollText, reminders: BellRing, compliance: ShieldCheck,
};

export default function PortalDashboardPage() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.portalSelf.dashboard() as ApiResp<Dashboard>;
        setDash(res.data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to load your portal");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

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
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-[#182350]">Your Portal</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Welcome{dash?.contact.name ? `, ${dash.contact.name}` : ""}. Your secure workspace with your accountant.
        </p>
      </div>

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

      <p className="text-[11px] text-gray-400 mt-5">
        This is your portal home. Invoice, statement, payment-reminder, and compliance views are being rolled out.
      </p>
    </div>
  );
}

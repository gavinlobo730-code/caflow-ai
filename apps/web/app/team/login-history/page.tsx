"use client";

import { useState, useEffect, useCallback } from "react";
import { History, LogOut, Loader2, ShieldAlert } from "lucide-react";
import { api, type LoginEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";

// M6 — administrative login history + global force-logout (Partner oversight).
const EVENT_STYLE: Record<string, string> = {
  login: "bg-emerald-50 text-emerald-700",
  logout: "bg-gray-100 text-gray-500",
  failed_login: "bg-red-50 text-red-700",
  forced_logout: "bg-amber-50 text-amber-700",
  suspended: "bg-red-50 text-red-700",
};

export default function LoginHistoryPage() {
  const { userRole } = useAuth();
  const isPartner = userRole === "Partner";
  const [events, setEvents] = useState<LoginEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.identity.loginHistory();
      setEvents(r.data?.events ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load login history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function forceLogoutAll() {
    if (!isPartner) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api.identity.forceLogoutAll() as { data?: { users_affected?: number } };
      setNotice(`Signed out ${r.data?.users_affected ?? 0} user(s). They must sign in again.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <History size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Login History</h1>
        </div>
        {isPartner && (
          <button onClick={forceLogoutAll} disabled={busy}
            className="flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-60">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <LogOut size={13} />} Sign out all users
          </button>
        )}
      </div>
      <p className="text-[12px] text-gray-500 mb-4">Login, logout, and forced-logout events for your firm (audited).</p>

      {!isPartner && (
        <div className="flex items-center gap-2 text-[12px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
          <ShieldAlert size={14} /> Login history is visible to Partners only.
        </div>
      )}
      {error && <div className="text-[12px] text-red-600 mb-2">{error}</div>}
      {notice && <div className="text-[12px] text-emerald-700 mb-2">{notice}</div>}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : events.length === 0 ? (
        <div className="py-12 text-center text-[12px] text-gray-400">No login events recorded yet.</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {events.map((e) => (
            <div key={e.id} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-50 text-[12px]">
              <div className="min-w-0">
                <span className="text-[#182350] font-medium">{e.email || e.user_id || "—"}</span>
                {e.ip ? <span className="text-gray-400"> · {e.ip}</span> : null}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className={`px-2 py-0.5 rounded-full font-medium ${EVENT_STYLE[e.event] ?? "bg-gray-100 text-gray-500"}`}>
                  {e.event}
                </span>
                <span className="text-gray-400">{e.created_at ? new Date(e.created_at).toLocaleString("en-IN") : ""}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

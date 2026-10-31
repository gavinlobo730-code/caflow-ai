"use client";

import { useState, useEffect, useCallback } from "react";
import { History, LogOut, Loader2, ShieldAlert } from "lucide-react";
import { api, type LoginEvent } from "@/lib/api";
import { formatDateTime } from "@/lib/dates/format";
import { usePermissions } from "@/lib/auth/AuthContext";
import { PageLoader } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { readWindow } from "@/lib/lists/readWindow";
import { windowDescription } from "@/lib/lists/window";

// M6 — administrative login history + global force-logout (Partner oversight).
// The server answers a window and says whether older events exist (POST-A-262); the first window is the size it defaults
// to, and "Show more" widens it up to the ceiling the server serves.
const FIRST_WINDOW = 200;

const EVENT_STYLE: Record<string, string> = {
  login: "bg-state-ready-surface text-state-ready",
  logout: "bg-state-done-surface text-state-done",
  failed_login: "bg-state-problem-surface text-state-problem",
  forced_logout: "bg-state-attention-surface text-state-attention",
  suspended: "bg-state-problem-surface text-state-problem",
};

export default function LoginHistoryPage() {
  // Two different permissions, previously conflated into one `isPartner` flag:
  //   team:read  (Manager+) — identity.login_history, i.e. seeing this page
  //   team:write (Partner)  — identity.force_logout_all, the button below
  // The old flag hid the button correctly but ALSO told every Manager the page
  // was Partner-only, while the list they were reading loaded fine.
  const { can } = usePermissions();
  const canViewHistory = can("team", "read");
  const canForceLogout = can("team", "write");
  const [events, setEvents] = useState<LoginEvent[]>([]);
  const [win, setWin] = useState<{ hasMore: boolean; limit: number; maxLimit: number } | null>(null);
  const [limit, setLimit] = useState(FIRST_WINDOW);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.identity.loginHistory(limit);
      const w = r.success ? readWindow<LoginEvent>(r.data, "events", limit) : null;
      if (!w) throw new Error("Login history could not be read");
      setEvents(w.rows);
      setWin({ hasMore: w.hasMore, limit: w.limit, maxLimit: w.maxLimit });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load login history");
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  async function forceLogoutAll() {
    if (!canForceLogout) return;
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
      <PageHeader
        icon={<History size={18} className="text-brand" />}
        title="Login History"
        meta={
          !loading ? (
            <span className="text-xs text-ps-hint">
              {events.length}{win?.hasMore ? "+" : ""} event{events.length === 1 ? "" : "s"}
            </span>
          ) : undefined
        }
        subtitle={
          <>
            Login, logout, and forced-logout events for your firm (audited).
          </>
        }
        actions={
          canForceLogout ? (
            <Button variant="plain" size="none" onClick={forceLogoutAll} disabled={busy}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-state-problem-hover disabled:opacity-60">
              {busy ? <Loader2 size={13} className="animate-spin" /> : <LogOut size={13} />} Sign out all users
            </Button>
          ) : undefined
        }
        className="mb-4"
      />

      {!canViewHistory && (
        <div className="flex items-center gap-2 text-xs text-state-attention bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2 mb-3">
          <ShieldAlert size={14} /> Login history is visible to Managers and Partners only.
        </div>
      )}
      {error && <div className="text-xs text-red-600 mb-2">{error}</div>}
      {win && !loading && (
        <ListWindowNotice
          hasMore={win.hasMore}
          what={windowDescription(events.length, "login events", "latest")}
          limit={win.limit}
          maxLimit={win.maxLimit}
          onShowMore={setLimit}
        />
      )}
      {notice && <div className="text-xs text-emerald-700 mb-2">{notice}</div>}

      {loading ? (
        <PageLoader onRetry={() => { void load(); }} />
      ) : events.length === 0 ? (
        <div className="py-12 text-center text-xs text-ps-hint">No login events recorded yet.</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {events.map((e) => (
            <div key={e.id} className="flex items-center justify-between px-4 py-2.5 border-b border-ps-border text-xs">
              <div className="min-w-0">
                <span className="text-brand font-medium">{e.email || e.user_id || "—"}</span>
                {e.ip ? <span className="text-ps-hint"> · {e.ip}</span> : null}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className={`px-2 py-0.5 rounded-full font-medium ${EVENT_STYLE[e.event] ?? "bg-gray-100 text-gray-500"}`}>
                  {e.event}
                </span>
                <span className="text-ps-hint">{formatDateTime(e.created_at, "")}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

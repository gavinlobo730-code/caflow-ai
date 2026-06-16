"use client";

/**
 * Platform Admin (Super Admin) console — /platform.
 *
 * Sits ABOVE firms; gated by the platform_admins allowlist (server-side). NOT in
 * the firm sidebar. Self-gates: requires a session AND platform-admin status,
 * else redirects away. Visibility + control only (no firm data editing).
 */
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Building2, Users, ShieldCheck, Ban, RotateCcw, Trash2, X, Loader2, AlertCircle } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { api } from "@/lib/api";

interface FirmRow { id: string; name: string; created_at: string; users: number; clients: number; status: string }
interface Stats { total_firms: number; active_firms: number; suspended_firms: number; total_users: number; total_clients: number }
interface FirmUser { name: string; email: string; role: string; status: string }

const STATUS_BADGE: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  suspended: "bg-amber-100 text-amber-700",
  deleted: "bg-red-100 text-red-600",
};

export default function PlatformAdminPage() {
  const { session, loading: authLoading } = useAuth();
  const router = useRouter();
  const [gate, setGate] = useState<"checking" | "denied" | "ok">("checking");
  const [stats, setStats] = useState<Stats | null>(null);
  const [firms, setFirms] = useState<FirmRow[]>([]);
  const [detail, setDetail] = useState<{ firm: FirmRow; users: FirmUser[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    const [s, f] = await Promise.all([api.platform.stats(), api.platform.firms()]);
    setStats(s.data);
    setFirms(f.data);
  }, []);

  // Gate: must be signed in AND a platform admin.
  useEffect(() => {
    if (authLoading) return;
    if (!session) { router.replace("/login"); return; }
    (async () => {
      try {
        const me = await api.platform.me();
        if (!me.data?.is_platform_admin) { setGate("denied"); router.replace("/"); return; }
        setGate("ok");
        await load();
      } catch {
        setGate("denied"); router.replace("/");
      }
    })();
  }, [authLoading, session, router, load]);

  function notify(msg: string, ok: boolean) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 5000);
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      notify(ok, true);
      await load();
      setDetail(null);
    } catch (e) {
      notify(e instanceof Error ? e.message.replace(/^API error \d+:\s*/, "") : "Action failed", false);
    } finally {
      setBusy(false);
    }
  }

  async function suspend(f: FirmRow) {
    const reason = window.prompt(`Suspend "${f.name}"? This blocks all its users.\n\nReason (required):`);
    if (!reason || !reason.trim()) return;
    await act(() => api.platform.suspend(f.id, reason.trim()), `Suspended ${f.name}`);
  }
  async function unsuspend(f: FirmRow) { await act(() => api.platform.unsuspend(f.id), `Reactivated ${f.name}`); }
  async function softDelete(f: FirmRow) {
    if (!window.confirm(`Soft-delete "${f.name}"? Records are preserved but all access is blocked.`)) return;
    await act(() => api.platform.softDelete(f.id), `Deleted ${f.name}`);
  }
  async function view(f: FirmRow) {
    const u = await api.platform.firmUsers(f.id);
    setDetail({ firm: f, users: u.data });
  }

  if (gate !== "ok") {
    return (
      <div className="flex h-screen items-center justify-center text-[#64748B]">
        {gate === "checking" ? <span className="flex items-center gap-2"><Loader2 className="animate-spin" size={16} /> Verifying access…</span> : "Redirecting…"}
      </div>
    );
  }

  const KPIS = stats ? [
    { label: "Total Firms", value: stats.total_firms, icon: Building2 },
    { label: "Active", value: stats.active_firms, icon: ShieldCheck },
    { label: "Suspended", value: stats.suspended_firms, icon: Ban },
    { label: "Total Users", value: stats.total_users, icon: Users },
    { label: "Total Clients", value: stats.total_clients, icon: Building2 },
  ] : [];

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-6 lg:p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-[#0F172A] flex items-center justify-center"><ShieldCheck size={16} className="text-white" /></div>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Platform Admin</h1>
          <p className="text-sm text-[#64748B]">Manage firms using PracticeSync</p>
        </div>
      </div>

      {toast && (
        <div className={`rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2 ${toast.ok ? "bg-green-50 text-green-700 border border-green-100" : "bg-red-50 text-red-700 border border-red-100"}`}>
          <AlertCircle size={14} /> {toast.msg}
        </div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {KPIS.map((k) => (
          <div key={k.label} className="bg-white rounded-xl border border-[#F1F5F9] p-4">
            <div className="w-8 h-8 rounded-lg bg-[#F8FAFC] flex items-center justify-center mb-2"><k.icon size={15} className="text-[#475569]" /></div>
            <p className="text-2xl font-bold text-[#0F172A]">{k.value}</p>
            <p className="text-xs text-[#64748B] mt-0.5">{k.label}</p>
          </div>
        ))}
      </div>

      {/* Firms table */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-3 border-b border-[#F1F5F9]"><h2 className="text-sm font-semibold text-[#0F172A]">{firms.length} firms</h2></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
              <th className="px-5 py-3 text-left font-semibold">Firm</th>
              <th className="px-3 py-3 text-left font-semibold">Created</th>
              <th className="px-3 py-3 text-right font-semibold">Users</th>
              <th className="px-3 py-3 text-right font-semibold">Clients</th>
              <th className="px-3 py-3 text-left font-semibold">Status</th>
              <th className="px-5 py-3 text-left font-semibold">Actions</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {firms.map((f) => (
                <tr key={f.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 font-medium text-[#1E293B]">{f.name}</td>
                  <td className="px-3 py-3 text-[#64748B] whitespace-nowrap">{f.created_at?.slice(0, 10)}</td>
                  <td className="px-3 py-3 text-right text-[#334155]">{f.users}</td>
                  <td className="px-3 py-3 text-right text-[#334155]">{f.clients}</td>
                  <td className="px-3 py-3"><span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[f.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>{f.status}</span></td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3 flex-wrap text-xs">
                      <button onClick={() => view(f)} className="text-blue-600 hover:underline">View</button>
                      {f.status === "active" && <button onClick={() => suspend(f)} disabled={busy} className="text-amber-700 hover:underline flex items-center gap-1"><Ban size={11} /> Suspend</button>}
                      {f.status === "suspended" && <button onClick={() => unsuspend(f)} disabled={busy} className="text-green-700 hover:underline flex items-center gap-1"><RotateCcw size={11} /> Unsuspend</button>}
                      {f.status !== "deleted" && <button onClick={() => softDelete(f)} disabled={busy} className="text-red-600 hover:underline flex items-center gap-1"><Trash2 size={11} /> Delete</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {firms.length === 0 && <div className="text-center py-8 text-sm text-[#94A3B8]">No firms yet</div>}
        </div>
      </div>

      {/* Firm detail (read-only) */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
              <h2 className="text-base font-semibold text-[#0F172A]">{detail.firm.name}</h2>
              <button onClick={() => setDetail(null)} className="text-[#94A3B8] hover:text-[#475569]"><X size={18} /></button>
            </div>
            <div className="px-6 py-4 space-y-4 overflow-y-auto">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><p className="text-xs text-[#94A3B8]">Created</p><p className="text-[#0F172A]">{detail.firm.created_at?.slice(0, 10)}</p></div>
                <div><p className="text-xs text-[#94A3B8]">Status</p><p className="text-[#0F172A]">{detail.firm.status}</p></div>
                <div><p className="text-xs text-[#94A3B8]">Users</p><p className="text-[#0F172A]">{detail.firm.users}</p></div>
                <div><p className="text-xs text-[#94A3B8]">Clients</p><p className="text-[#0F172A]">{detail.firm.clients}</p></div>
              </div>
              <div>
                <p className="text-xs font-semibold text-[#64748B] uppercase tracking-wide mb-2">Users (read-only)</p>
                <div className="rounded-lg border border-[#F1F5F9] divide-y divide-[#F8FAFC]">
                  {detail.users.map((u, i) => (
                    <div key={i} className="flex items-center justify-between px-3 py-2 text-sm">
                      <div><p className="text-[#0F172A]">{u.name || u.email}</p><p className="text-xs text-[#94A3B8]">{u.email}</p></div>
                      <span className="text-xs text-[#475569]">{u.role}</span>
                    </div>
                  ))}
                  {detail.users.length === 0 && <div className="px-3 py-3 text-xs text-[#94A3B8]">No users</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

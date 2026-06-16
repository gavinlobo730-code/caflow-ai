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
import { Building2, Users, ShieldCheck, Ban, RotateCcw, Trash2, X, Loader2, AlertCircle, RefreshCw, AlertTriangle, KeyRound } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { getSupabaseClient } from "@/lib/supabase/client";
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
  // "error" is distinct from "denied": denied = the server authoritatively said
  // "not a platform admin" (→ redirect); error = we could NOT get an answer
  // (network/timeout/backend/config failure) and must NOT silently bounce a
  // legitimate admin. We surface the real error + a Retry instead.
  const [gate, setGate] = useState<"checking" | "denied" | "error" | "ok">("checking");
  const [gateErr, setGateErr] = useState<string>("");
  const [dataErr, setDataErr] = useState<string>("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [firms, setFirms] = useState<FirmRow[]>([]);
  const [detail, setDetail] = useState<{ firm: FirmRow; users: FirmUser[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  // Permanent (hard) delete — MFA step-up + typed confirmation.
  const [purgeTarget, setPurgeTarget] = useState<FirmRow | null>(null);
  const [purgeCode, setPurgeCode] = useState("");
  const [purgeName, setPurgeName] = useState("");
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [purgeErr, setPurgeErr] = useState("");

  const cleanErr = (e: unknown, fallback: string) =>
    e instanceof Error ? e.message.replace(/^API error \d+:\s*/, "") : fallback;

  const load = useCallback(async () => {
    const [s, f] = await Promise.all([api.platform.stats(), api.platform.firms()]);
    setStats(s.data);
    setFirms(f.data);
  }, []);

  // Gate: must be signed in AND a platform admin. Authorization (is_platform_admin)
  // is decided ONLY by a SUCCESSFUL /me response; any request failure is treated
  // as "couldn't verify" (error state), never as "denied".
  const verify = useCallback(async () => {
    setGate("checking");
    setGateErr("");
    // Authoritative session check. /platform is a PUBLIC, self-gating route, so
    // (unlike AuthGuard-protected pages) its body runs even while the context
    // session is transiently null — e.g. a slow token refresh trips AuthContext's
    // 5s safety timeout, or a one-off getSession error. Trusting the context
    // `session` here would bounce a signed-in admin to /login. Read the session
    // straight from the Supabase store (the same source the api client uses), so
    // only a CONFIRMED-null session means "not signed in".
    let live;
    try {
      ({ data: { session: live } } = await getSupabaseClient().auth.getSession());
    } catch {
      ({ data: { session: live } } = await getSupabaseClient().auth.getSession());
    }
    if (!live) { router.replace("/login"); return; }
    try {
      // Cold-start tolerance: the free-tier backend may be asleep and the first
      // call can exceed the client abort. Retry once before giving up so a
      // legitimate admin isn't bounced by a 50s wake-up.
      let me;
      try {
        me = await api.platform.me();
      } catch {
        me = await api.platform.me();
      }
      if (me.data?.is_platform_admin !== true) {
        setGate("denied");
        router.replace("/");
        return;
      }
      setGate("ok");
    } catch (e) {
      setGateErr(cleanErr(e, "Could not verify platform access."));
      setGate("error");
    }
  }, [router]);

  // Wait for the initial auth resolution to settle, then verify authoritatively.
  // We intentionally do NOT branch on the context `session` here — verify() reads
  // the live session itself, which is race-proof against the 5s safety timeout.
  useEffect(() => {
    if (authLoading) return;
    verify();
  }, [authLoading, session, verify]);

  // Load firm data only AFTER the gate opens, in a separate effect. A failure
  // here shows an inline banner — it must never re-enter the auth gate and
  // redirect a verified admin away (the original bug).
  useEffect(() => {
    if (gate !== "ok") return;
    setDataErr("");
    load().catch((e) => setDataErr(cleanErr(e, "Could not load platform data.")));
  }, [gate, load]);

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

  function openPurge(f: FirmRow) {
    setPurgeTarget(f); setPurgeCode(""); setPurgeName(""); setPurgeErr("");
  }

  // Irreversible hard delete. Re-verifies the authenticator code (TOTP step-up to
  // aal2) right before purging, so a destructive action always requires a fresh
  // MFA proof — the backend (require_platform_admin_mfa) rejects anything less.
  async function confirmPurge() {
    if (!purgeTarget) return;
    if (purgeName.trim() !== purgeTarget.name) { setPurgeErr("Firm name does not match."); return; }
    const code = purgeCode.replace(/\s/g, "");
    if (!/^\d{6}$/.test(code)) { setPurgeErr("Enter the 6-digit code from your authenticator app."); return; }
    setPurgeBusy(true); setPurgeErr("");
    try {
      const sb = getSupabaseClient();
      const { data: factors, error: fErr } = await sb.auth.mfa.listFactors();
      if (fErr) throw new Error(fErr.message);
      const totp = factors?.totp?.find((f) => f.status === "verified") ?? factors?.totp?.[0];
      if (!totp) throw new Error("No authenticator is set up on this account. Enrol one at Settings → Security first.");
      const { data: ch, error: cErr } = await sb.auth.mfa.challenge({ factorId: totp.id });
      if (cErr || !ch) throw new Error(cErr?.message ?? "Could not start the MFA challenge.");
      const { error: vErr } = await sb.auth.mfa.verify({ factorId: totp.id, challengeId: ch.id, code });
      if (vErr) throw new Error("Invalid authenticator code. Please try again.");
      // Session is now aal2 — the purge request carries the elevated token.
      await api.platform.purge(purgeTarget.id);
      notify(`Permanently deleted ${purgeTarget.name}`, true);
      setPurgeTarget(null);
      await load();
      setDetail(null);
    } catch (e) {
      setPurgeErr(e instanceof Error ? e.message.replace(/^API error \d+:\s*/, "") : "Permanent delete failed.");
    } finally {
      setPurgeBusy(false);
    }
  }

  if (gate !== "ok") {
    if (gate === "error") {
      return (
        <div className="flex h-screen items-center justify-center bg-[#F8FAFC] p-6">
          <div className="bg-white rounded-2xl border border-[#F1F5F9] shadow-sm max-w-md w-full p-6 text-center space-y-4">
            <div className="w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center mx-auto"><AlertCircle size={18} className="text-amber-600" /></div>
            <div>
              <h2 className="text-base font-semibold text-[#0F172A]">Couldn’t verify access</h2>
              <p className="text-sm text-[#64748B] mt-1">We couldn’t reach the platform service to confirm your access. This is not a denial — it’s a connection problem.</p>
              {gateErr && <p className="text-xs text-[#94A3B8] mt-2 break-words font-mono bg-[#F8FAFC] rounded-md px-2 py-1">{gateErr}</p>}
            </div>
            <button onClick={() => verify()} className="inline-flex items-center gap-2 rounded-lg bg-[#0F172A] text-white text-sm font-medium px-4 py-2 hover:bg-[#1E293B]">
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        </div>
      );
    }
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

      {dataErr && (
        <div className="rounded-lg px-4 py-3 text-sm font-medium flex items-center justify-between gap-2 bg-amber-50 text-amber-700 border border-amber-100">
          <span className="flex items-center gap-2"><AlertCircle size={14} /> {dataErr}</span>
          <button onClick={() => { setDataErr(""); load().catch((e) => setDataErr(cleanErr(e, "Could not load platform data."))); }} className="inline-flex items-center gap-1 text-amber-800 hover:underline">
            <RefreshCw size={12} /> Retry
          </button>
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
                      <button onClick={() => openPurge(f)} disabled={busy} className="text-red-700 hover:underline flex items-center gap-1 font-medium"><AlertTriangle size={11} /> Delete permanently</button>
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

      {/* Permanent delete — MFA step-up + typed confirmation */}
      {purgeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => !purgeBusy && setPurgeTarget(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
              <h2 className="text-base font-semibold text-red-700 flex items-center gap-2"><AlertTriangle size={16} /> Permanently delete firm</h2>
              <button onClick={() => !purgeBusy && setPurgeTarget(null)} className="text-[#94A3B8] hover:text-[#475569]"><X size={18} /></button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <p className="text-sm text-[#475569]">
                This <span className="font-semibold text-red-700">irreversibly</span> deletes <span className="font-semibold">{purgeTarget.name}</span> and all of its data — {purgeTarget.users} user(s), {purgeTarget.clients} client(s), and every related record. This cannot be undone.
              </p>
              <p className="text-xs text-[#94A3B8]">Login accounts in authentication are not removed — only the firm and its data.</p>
              <div>
                <label className="text-xs font-medium text-[#64748B]">Type the firm name to confirm</label>
                <input value={purgeName} onChange={(e) => setPurgeName(e.target.value)} placeholder={purgeTarget.name}
                  className="mt-1 w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-200" />
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] flex items-center gap-1"><KeyRound size={12} /> Authenticator code</label>
                <input value={purgeCode} onChange={(e) => setPurgeCode(e.target.value)} inputMode="numeric" maxLength={6} placeholder="6-digit code"
                  className="mt-1 w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm tracking-[0.3em] focus:outline-none focus:ring-2 focus:ring-red-200" />
                <p className="text-[11px] text-[#94A3B8] mt-1">From the authenticator app you enrolled for this account.</p>
              </div>
              {purgeErr && <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-md px-3 py-2">{purgeErr}</p>}
            </div>
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[#F1F5F9]">
              <button onClick={() => setPurgeTarget(null)} disabled={purgeBusy} className="text-sm text-[#64748B] px-3 py-2 hover:underline disabled:opacity-50">Cancel</button>
              <button onClick={confirmPurge}
                disabled={purgeBusy || purgeName.trim() !== purgeTarget.name || purgeCode.replace(/\s/g, "").length !== 6}
                className="inline-flex items-center gap-2 rounded-lg bg-red-600 text-white text-sm font-medium px-4 py-2 hover:bg-red-700 disabled:opacity-50">
                {purgeBusy ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />} Delete permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

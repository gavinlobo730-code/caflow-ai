"use client";

/**
 * Security settings — Multi-Factor Authentication (TOTP) enrollment.
 *
 * Lets any signed-in user enrol an authenticator app (Google Authenticator,
 * Authy, 1Password, …) as a TOTP second factor, scan a QR code, and verify a
 * 6-digit code. Required before REQUIRE_MFA is enabled for MFA-required roles
 * (default: Partner) — otherwise those users would be locked out.
 *
 * Uses Supabase Auth MFA: enroll → challenge → verify. The verified factor lets
 * the user elevate to aal2 at login (see app/login).
 */
import { useState, useEffect, useCallback } from "react";
import { ShieldCheck, Smartphone, Trash2, CheckCircle2, Loader2, AlertCircle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

interface Factor {
  id: string;
  friendly_name?: string | null;
  status: string; // 'verified' | 'unverified'
  factor_type: string;
}

interface Enrolling {
  factorId: string;
  qr: string;      // SVG data-URI
  secret: string;  // manual-entry secret
}

export default function SecuritySettingsPage() {
  const supabase = getSupabaseClient();
  const [factors, setFactors] = useState<Factor[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState<Enrolling | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const verified = factors.filter((f) => f.status === "verified");
  const mfaEnabled = verified.length > 0;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, error } = await supabase.auth.mfa.listFactors();
      if (error) throw error;
      // `all` includes unverified factors; show verified TOTP factors as active.
      const all = ((data as { all?: Factor[] } | null)?.all ?? []) as Factor[];
      setFactors(all.filter((f) => f.factor_type === "totp"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load MFA status.");
    } finally {
      setLoading(false);
    }
  }, [supabase]);

  useEffect(() => { load(); }, [load]);

  /** Begin TOTP enrolment: clears any stale unverified factor, then enrols. */
  async function startEnroll() {
    setBusy(true); setError(null); setNotice(null);
    try {
      // Remove any leftover unverified factors so enroll() doesn't conflict.
      for (const f of factors.filter((f) => f.status === "unverified")) {
        await supabase.auth.mfa.unenroll({ factorId: f.id }).catch(() => {});
      }
      const { data, error } = await supabase.auth.mfa.enroll({
        factorType: "totp",
        friendlyName: `Authenticator ${new Date().toISOString().slice(0, 10)}`,
      });
      if (error) throw error;
      const d = data as { id: string; totp: { qr_code: string; secret: string } };
      setEnrolling({ factorId: d.id, qr: d.totp.qr_code, secret: d.totp.secret });
      setCode("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start enrolment.");
    } finally {
      setBusy(false);
    }
  }

  /** Verify the 6-digit code to activate the factor (challenge + verify). */
  async function verifyEnroll() {
    if (!enrolling || code.trim().length < 6) return;
    setBusy(true); setError(null);
    try {
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId: enrolling.factorId,
        code: code.trim(),
      });
      if (error) throw error;
      setEnrolling(null);
      setCode("");
      setNotice("Multi-factor authentication is now enabled for your account.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid code — check your authenticator app and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function removeFactor(factorId: string) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const { error } = await supabase.auth.mfa.unenroll({ factorId });
      if (error) throw error;
      setNotice("Authenticator removed.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the authenticator.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-[#0F172A]">Security</h1>
        <p className="text-sm text-[#64748B] mt-0.5">Protect your account with two-factor authentication</p>
      </div>

      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <ShieldCheck size={15} className="text-blue-600" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Two-Factor Authentication (TOTP)</h2>
          {mfaEnabled && (
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
              <CheckCircle2 size={11} /> Enabled
            </span>
          )}
        </div>

        <div className="px-5 py-4 space-y-4">
          {error && (
            <p className="text-xs text-red-600 flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}</p>
          )}
          {notice && (
            <p className="text-xs text-green-700 flex items-start gap-1.5"><CheckCircle2 size={13} className="mt-0.5 shrink-0" /> {notice}</p>
          )}

          {loading ? (
            <p className="text-sm text-[#94A3B8] flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
          ) : enrolling ? (
            /* ── Enrolment in progress: QR + verify ── */
            <div className="space-y-4">
              <p className="text-sm text-[#334155]">
                1. Scan this QR code with your authenticator app (Google Authenticator, Authy, 1Password…).
              </p>
              <div className="flex flex-col sm:flex-row gap-4 items-start">
                {/* qr_code is an SVG data-URI returned by Supabase */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={enrolling.qr} alt="MFA QR code" className="w-44 h-44 border border-[#E2E8F0] rounded-lg bg-white" />
                <div className="space-y-2">
                  <p className="text-xs text-[#64748B]">Can&apos;t scan? Enter this key manually:</p>
                  <code className="block text-xs font-mono bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2 break-all">{enrolling.secret}</code>
                </div>
              </div>
              <div className="space-y-1.5">
                <p className="text-sm text-[#334155]">2. Enter the 6-digit code from the app:</p>
                <div className="flex gap-2">
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="123456"
                    className="w-36 text-center tracking-widest font-mono text-base border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    onClick={verifyEnroll}
                    disabled={busy || code.length < 6}
                    className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
                  >
                    {busy ? "Verifying…" : "Verify & enable"}
                  </button>
                  <button
                    onClick={() => { setEnrolling(null); setCode(""); load(); }}
                    className="px-4 py-2 text-sm text-[#64748B] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          ) : mfaEnabled ? (
            /* ── Already enrolled: list + remove ── */
            <div className="space-y-3">
              <p className="text-sm text-[#334155]">Your account is protected by an authenticator app.</p>
              {verified.map((f) => (
                <div key={f.id} className="flex items-center justify-between bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <Smartphone size={15} className="text-[#64748B]" />
                    <span className="text-sm text-[#0F172A]">{f.friendly_name || "Authenticator app"}</span>
                  </div>
                  <button
                    onClick={() => removeFactor(f.id)}
                    disabled={busy}
                    className="flex items-center gap-1 text-xs text-red-600 hover:text-red-700 disabled:opacity-50"
                  >
                    <Trash2 size={12} /> Remove
                  </button>
                </div>
              ))}
              <button
                onClick={startEnroll}
                disabled={busy}
                className="text-xs text-blue-600 hover:underline disabled:opacity-50"
              >
                + Add another authenticator
              </button>
            </div>
          ) : (
            /* ── Not enrolled ── */
            <div className="space-y-3">
              <p className="text-sm text-[#334155]">
                Add an authenticator app to require a 6-digit code at sign-in. This is required for Partner accounts.
              </p>
              <button
                onClick={startEnroll}
                disabled={busy}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                <Smartphone size={15} /> {busy ? "Starting…" : "Set up authenticator app"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

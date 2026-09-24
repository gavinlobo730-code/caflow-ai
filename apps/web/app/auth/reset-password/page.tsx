"use client";

/**
 * Reset Password — landing page for the link emailed by
 * login/forgot-password's resetPasswordForEmail(). Public route (see
 * lib/auth/public-paths.ts, "/auth" prefix already covers this).
 *
 * Supabase's password-recovery link authenticates the browser into a fresh
 * session when it's opened (detectSessionInUrl, on by default in
 * lib/supabase/client.ts) and fires a PASSWORD_RECOVERY auth event — this
 * page waits for that (or an already-established session, in case the event
 * fired before the listener attached) before showing the new-password form.
 * A link with no valid recovery token lands with no session and no event, so
 * after a short grace period it shows an "invalid or expired" state instead
 * of hanging on the loading spinner forever.
 *
 * Same reauthentication fallback as onboarding's "set your password" step
 * (lib/auth/reauth.ts): if "Secure password change" is enabled and Supabase
 * still asks for reauthentication on this fresh session, email a nonce and
 * finish with updateUser({ password, nonce }) instead of failing outright.
 */
import { useState, useEffect, useRef, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api, type ApiResp } from "@/lib/api";
import { setPasswordWithReauthNonce, isInvalidNonceError } from "@/lib/auth/reauth";
import { ArrowRight, Eye, EyeOff, ShieldCheck, AlertCircle } from "lucide-react";

const MIN_LENGTH = 10;
const LINK_WAIT_MS = 4000;

type Stage = "verifying" | "invalid" | "form" | "reauth" | "done";

// This page is shared by firm staff (via /login/forgot-password) AND client
// portal contacts (via /login/forgot-password?portal=1) — one Supabase auth
// system, one reset flow. Which dashboard to land on afterward depends on
// which kind of identity actually reset the password, not which link they
// clicked (a portal contact could still have this page bookmarked, etc.), so
// ask the backend: an identity with an active portal membership goes to the
// portal, everyone else goes to the firm dashboard. A failed check (network
// blip, or simply "not a portal user" — that endpoint 403s in that case) just
// falls through to the firm dashboard, same as today's unconditional default.
async function resolveRedirectPath(): Promise<string> {
  try {
    const res = await api.portalSelf.memberships() as ApiResp<{ memberships: unknown[] }>;
    if ((res.data?.memberships?.length ?? 0) > 0) return "/portal/dashboard";
  } catch { /* not a portal identity, or the check failed — fall through */ }
  return "/";
}

export default function ResetPasswordPage() {
  const supabase = getSupabaseClient();
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("verifying");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reauthOtp, setReauthOtp] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  const pwRef = useRef(""); // mirrors `pw` so verifyReauth() reads the value typed before the nonce round-trip

  useEffect(() => {
    let settled = false;
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" && !settled) {
        settled = true;
        setStage("form");
      }
    });
    // The event may have already fired before this listener attached — an
    // active session at mount is just as valid a signal to proceed.
    supabase.auth.getSession().then(({ data }) => {
      if (!settled && data.session) { settled = true; setStage("form"); }
    });
    const timeout = setTimeout(() => {
      if (!settled) { settled = true; setStage("invalid"); }
    }, LINK_WAIT_MS);
    return () => { sub.subscription.unsubscribe(); clearTimeout(timeout); };
  }, [supabase]);

  function validate(): string | null {
    if (pw.length < MIN_LENGTH) return `Use at least ${MIN_LENGTH} characters.`;
    if (pw !== pw2) return "Passwords do not match.";
    return null;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const v = validate();
    if (v) { setError(v); return; }
    setError(null);
    setSaving(true);
    pwRef.current = pw;
    try {
      const { error: upErr } = await supabase.auth.updateUser({ password: pw });
      if (upErr) {
        if (upErr.message.toLowerCase().includes("reauthentication")) {
          const { error: raErr } = await supabase.auth.reauthenticate();
          if (raErr) throw new Error("Could not send a verification code. Please try again.");
          setStage("reauth");
          return;
        }
        throw new Error(upErr.message);
      }
      setStage("done");
      setPw(""); setPw2("");
      const dest = await resolveRedirectPath();
      setTimeout(() => router.push(dest), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update your password. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function verifyReauth(e: FormEvent) {
    e.preventDefault();
    setReauthError(null);
    setSaving(true);
    try {
      const { error: upErr } = await setPasswordWithReauthNonce(supabase.auth, pwRef.current, reauthOtp);
      if (upErr) {
        throw new Error(
          isInvalidNonceError(upErr)
            ? "That code is incorrect or has expired. Request a new reset link and try again."
            : upErr.message,
        );
      }
      setStage("done");
      setPw(""); setPw2(""); setReauthOtp("");
      const dest = await resolveRedirectPath();
      setTimeout(() => router.push(dest), 1200);
    } catch (err) {
      setReauthError(err instanceof Error ? err.message : "Verification failed. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12 bg-ps-bg">
      <div className="w-full max-w-[380px]">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-8 h-8 rounded-xl bg-brand flex items-center justify-center text-sm font-bold text-white">P</div>
          <span className="text-base font-bold text-ps-ink">PracticeSync AI</span>
        </div>

        {stage === "verifying" && (
          <div className="text-center py-8">
            <span className="inline-block w-6 h-6 border-2 border-ps-border border-t-blue-600 rounded-full animate-spin" />
            <p className="text-sm text-ps-label mt-4">Verifying your reset link…</p>
          </div>
        )}

        {stage === "invalid" && (
          <div className="text-center">
            <div className="w-12 h-12 rounded-full bg-state-problem-surface flex items-center justify-center mx-auto mb-4">
              <AlertCircle size={22} className="text-red-500" />
            </div>
            <h2 className="text-xl font-bold text-ps-ink tracking-tight">Link invalid or expired</h2>
            <p className="text-sm text-ps-label mt-2 leading-relaxed">
              This password reset link no longer works. Request a new one to continue.
            </p>
            <Link
              href="/login/forgot-password"
              className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700 font-medium mt-6"
            >
              Request a new link <ArrowRight size={14} />
            </Link>
          </div>
        )}

        {stage === "form" && (
          <>
            <div className="mb-8">
              <h2 className="text-2xl font-bold text-ps-ink tracking-tight">Set a new password</h2>
              <p className="text-sm text-ps-label mt-1">Choose a new password for your account.</p>
            </div>
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label className="block text-sm font-semibold text-ps-ink">New password</label>
                <div className="relative">
                  <input
                    autoFocus type={showPw ? "text" : "password"} required value={pw}
                    onChange={(e) => setPw(e.target.value)} autoComplete="new-password"
                    placeholder={`At least ${MIN_LENGTH} characters`}
                    className="w-full bg-white border border-ps-border rounded-lg px-4 py-3 pr-11 text-sm text-ps-ink placeholder:text-ps-disabled outline-none focus:border-brand focus:ring-4 focus:ring-brand/[0.08] transition-all"
                  />
                  <button type="button" onClick={() => setShowPw((s) => !s)} aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-ps-hint hover:text-ps-label">
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="block text-sm font-semibold text-ps-ink">Confirm password</label>
                <input
                  type={showPw ? "text" : "password"} required value={pw2}
                  onChange={(e) => setPw2(e.target.value)} autoComplete="new-password"
                  placeholder="Re-enter your password"
                  className="w-full bg-white border border-ps-border rounded-lg px-4 py-3 text-sm text-ps-ink placeholder:text-ps-disabled outline-none focus:border-brand focus:ring-4 focus:ring-brand/[0.08] transition-all"
                />
              </div>

              {error && (
                <div role="alert" className="flex items-start gap-2.5 p-3.5 rounded-lg bg-state-problem-surface border border-state-problem-border">
                  <div className="w-4 h-4 rounded-full bg-state-problem-surface flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-state-problem text-3xs font-bold leading-none">!</span>
                  </div>
                  <p className="text-sm text-red-600 leading-snug">{error}</p>
                </div>
              )}

              <button
                type="submit" disabled={saving}
                className="w-full flex items-center justify-center gap-2 bg-brand hover:bg-brand-dark disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm"
              >
                {saving ? (
                  <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Updating…</>
                ) : (
                  <>Update password <ArrowRight size={15} /></>
                )}
              </button>
            </form>
          </>
        )}

        {stage === "reauth" && (
          <>
            <div className="mb-8">
              <h2 className="text-2xl font-bold text-ps-ink tracking-tight">Confirm it&apos;s you</h2>
              <p className="text-sm text-ps-label mt-1">
                For your security, we sent a verification code to your email. Enter it below to finish resetting your password.
              </p>
            </div>
            <form onSubmit={verifyReauth} className="space-y-5">
              <div className="space-y-1.5">
                <label className="block text-sm font-semibold text-ps-ink">Verification code</label>
                <input
                  autoFocus inputMode="numeric" value={reauthOtp} maxLength={8}
                  onChange={(e) => setReauthOtp(e.target.value.replace(/\D/g, "").slice(0, 8))}
                  placeholder="123456"
                  className="w-full bg-white border border-ps-border rounded-lg px-4 py-3 text-lg tracking-[0.3em] text-center font-mono text-ps-ink placeholder:text-ps-disabled outline-none focus:border-brand focus:ring-4 focus:ring-brand/[0.08] transition-all"
                />
              </div>
              {reauthError && (
                <div role="alert" className="flex items-start gap-2.5 p-3.5 rounded-lg bg-state-problem-surface border border-state-problem-border">
                  <div className="w-4 h-4 rounded-full bg-state-problem-surface flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-state-problem text-3xs font-bold leading-none">!</span>
                  </div>
                  <p className="text-sm text-red-600 leading-snug">{reauthError}</p>
                </div>
              )}
              <button
                type="submit" disabled={saving || reauthOtp.length < 6}
                className="w-full flex items-center justify-center gap-2 bg-brand hover:bg-brand-dark disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm"
              >
                {saving ? (
                  <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Verifying…</>
                ) : (
                  <>Verify <ArrowRight size={15} /></>
                )}
              </button>
            </form>
          </>
        )}

        {stage === "done" && (
          <div className="text-center">
            <div className="w-12 h-12 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-4">
              <ShieldCheck size={22} className="text-emerald-600" />
            </div>
            <h2 className="text-xl font-bold text-ps-ink tracking-tight">Password updated</h2>
            <p className="text-sm text-ps-label mt-2">Taking you to your workspace…</p>
          </div>
        )}
      </div>
    </div>
  );
}

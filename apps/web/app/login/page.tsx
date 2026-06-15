"use client";

import { useState, useEffect, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Shield, Zap, TrendingUp, ArrowRight } from "lucide-react";

const FEATURES = [
  { icon: Shield, label: "GST · ITR · TDS · MCA", desc: "All compliance in one place" },
  { icon: Zap,    label: "AI-powered automation",  desc: "Reminders, drafts, insights" },
  { icon: TrendingUp, label: "Practice analytics", desc: "Client health, deadlines, revenue" },
];

export default function LoginPage() {
  const { signIn, mfaPending } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);
  const [mfaFactorId, setMfaFactorId] = useState("");
  const [mfaCode, setMfaCode]   = useState("");

  // The challenge is driven by the global auth state (mfaPending) so it survives
  // the post-sign-in redirect race and page refreshes. When pending, fetch the
  // verified TOTP factor to challenge against.
  const mfaStep = mfaPending === true;
  useEffect(() => {
    if (mfaStep && !mfaFactorId) {
      supabase.auth.mfa.listFactors().then(({ data }) => {
        const totp = ((data as { totp?: { id: string }[] } | null)?.totp ?? [])[0];
        if (totp) setMfaFactorId(totp.id);
      }).catch(() => {});
    }
  }, [mfaStep, mfaFactorId, supabase]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error } = await signIn(email, password);
      if (error) { setError(error); setLoading(false); return; }
      // Do NOT navigate here. AuthContext recomputes MFA assurance: if a challenge
      // is owed, mfaPending flips true and the challenge form renders below; if not,
      // AuthGuard moves the user off /login. This avoids racing the redirect.
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection error. Please try again.");
      setLoading(false);
    }
  }

  async function handleMfaSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId: mfaFactorId,
        code: mfaCode.trim(),
      });
      if (error) { setError("Invalid code — check your authenticator app and try again."); setLoading(false); return; }
      // Session is now aal2; onAuthStateChange clears mfaPending and AuthGuard
      // routes onward. Push as well for immediacy.
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex">

      {/* Left dark navy brand panel */}
      <div className="hidden lg:flex flex-col justify-between w-[420px] shrink-0 relative overflow-hidden bg-[#0F172A]">
        {/* Subtle grid pattern */}
        <div className="absolute inset-0 opacity-[0.04]"
          style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "28px 28px" }} />
        {/* Blue glow accent bottom-right */}
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-blue-600/20 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 flex items-center gap-3 px-10 py-10">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-[14px] font-bold text-white shadow-[0_0_20px_rgba(37,99,235,0.5)]">P</div>
          <span className="text-[16px] font-bold text-white tracking-tight">PracticeSync AI</span>
        </div>

        <div className="relative z-10 px-10 pb-4 space-y-8">
          <div>
            <h1 className="text-[32px] font-bold text-white leading-tight tracking-tight">
              The operating system<br />for modern CA firms
            </h1>
            <p className="text-[14px] text-slate-400 mt-3 leading-relaxed">
              Manage clients, compliance, accounting, payroll and documents from one workspace.
            </p>
          </div>
          <div className="space-y-4">
            {FEATURES.map(({ icon: Icon, label, desc }) => (
              <div key={label} className="flex items-center gap-3.5">
                <div className="w-9 h-9 rounded-xl bg-white/[0.06] border border-white/10 flex items-center justify-center shrink-0">
                  <Icon size={16} className="text-blue-400" />
                </div>
                <div>
                  <p className="text-[13px] font-semibold text-slate-200">{label}</p>
                  <p className="text-[12px] text-slate-500">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 px-10 pb-8 text-[11px] text-slate-600">
          © 2026 PracticeSync AI — Trusted by accounting firms across India
        </p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-[#F8FAFC]">
        <div className="w-full max-w-[380px]">

          <div className="lg:hidden flex items-center gap-2.5 justify-center mb-8">
            <div className="w-8 h-8 rounded-xl bg-blue-600 flex items-center justify-center text-[13px] font-bold text-white">P</div>
            <span className="text-[16px] font-bold text-[#0F172A]">PracticeSync AI</span>
          </div>

          <div className="mb-8">
            <h2 className="text-[26px] font-bold text-[#0F172A] tracking-tight">
              {mfaStep ? "Two-factor authentication" : "Sign in"}
            </h2>
            <p className="text-[14px] text-[#64748B] mt-1">
              {mfaStep ? "Enter the 6-digit code from your authenticator app" : "Enter your credentials to continue"}
            </p>
          </div>

          {mfaStep ? (
            <form onSubmit={handleMfaSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label className="block text-[13px] font-semibold text-[#0F172A]">Authentication code</label>
                <input
                  autoFocus inputMode="numeric" value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="123456"
                  className="w-full bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 text-[18px] tracking-[0.3em] text-center font-mono text-[#0F172A] placeholder:text-[#CBD5E1] outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/[0.08] transition-all"
                />
              </div>
              {error && (
                <div className="flex items-start gap-2.5 p-3.5 rounded-lg bg-red-50 border border-red-100">
                  <div className="w-4 h-4 rounded-full bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-red-500 text-[10px] font-bold leading-none">!</span>
                  </div>
                  <p className="text-[13px] text-red-600 leading-snug">{error}</p>
                </div>
              )}
              <button
                type="submit" disabled={loading || mfaCode.length < 6}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm"
              >
                {loading ? (
                  <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Verifying…</>
                ) : (
                  <>Verify <ArrowRight size={15} /></>
                )}
              </button>
            </form>
          ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-[13px] font-semibold text-[#0F172A]">Email address</label>
              <input
                type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="ca@yourfirm.com"
                className="w-full bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 text-[14px] text-[#0F172A] placeholder:text-[#CBD5E1] outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/[0.08] transition-all"
              />
            </div>
            <div className="space-y-1.5">
              <label className="block text-[13px] font-semibold text-[#0F172A]">Password</label>
              <input
                type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 text-[14px] text-[#0F172A] placeholder:text-[#CBD5E1] outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/[0.08] transition-all"
              />
            </div>

            {error && (
              <div className="flex items-start gap-2.5 p-3.5 rounded-lg bg-red-50 border border-red-100">
                <div className="w-4 h-4 rounded-full bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                  <span className="text-red-500 text-[10px] font-bold leading-none">!</span>
                </div>
                <p className="text-[13px] text-red-600 leading-snug">{error}</p>
              </div>
            )}

            <button
              type="submit" disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm"
            >
              {loading ? (
                <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Signing in…</>
              ) : (
                <>Sign in <ArrowRight size={15} /></>
              )}
            </button>
          </form>
          )}

          <p className="text-center text-[13px] text-[#94A3B8] mt-6">
            New to PracticeSync?{" "}
            <Link href="/signup" className="text-blue-600 hover:text-blue-700 font-medium transition-colors">
              Create your account →
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

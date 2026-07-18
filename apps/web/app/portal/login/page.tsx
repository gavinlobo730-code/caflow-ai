"use client";

/**
 * Client Portal sign-in — email + password, provisioned entirely by the CA
 * (invite → apps/web/app/portal/activate sets the password). There is no
 * self-signup here: a client who has never been invited has no account to
 * sign into, so the error is the same generic "check your credentials"
 * message Supabase itself returns — this page never reveals whether an
 * email is registered.
 *
 * No MFA step here (unlike /login): core/portal_auth.get_current_portal_client
 * never calls require_mfa — that's a firm-staff-only concept.
 */
import { useState, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { ArrowRight } from "lucide-react";

export default function PortalLoginPage() {
  const router = useRouter();
  const supabase = getSupabaseClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error: signInErr } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signInErr) {
        setError("Incorrect email or password. If your accountant just invited you, use the link in that email to set your password first.");
        setLoading(false);
        return;
      }
      router.push("/portal/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection error. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12 bg-[#F8FAFC]">
      <div className="w-full max-w-[380px]">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-8 h-8 rounded-xl bg-blue-600 flex items-center justify-center text-[13px] font-bold text-white">P</div>
          <span className="text-[16px] font-bold text-[#0F172A]">PracticeSync</span>
        </div>

        <div className="mb-8 text-center">
          <h2 className="text-[26px] font-bold text-[#0F172A] tracking-tight">Client portal</h2>
          <p className="text-[14px] text-[#64748B] mt-1">Sign in to view your documents, invoices and statements.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className="block text-[13px] font-semibold text-[#0F172A]">Email address</label>
            <input
              autoFocus type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="w-full bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 text-[14px] text-[#0F172A] placeholder:text-[#CBD5E1] outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/[0.08] transition-all"
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-[13px] font-semibold text-[#0F172A]">Password</label>
              <Link href="/login/forgot-password?portal=1" className="text-[12px] text-blue-600 hover:text-blue-700 font-medium transition-colors">
                Forgot password?
              </Link>
            </div>
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

        <p className="text-center text-[13px] text-[#94A3B8] mt-6">
          New here? Access is set up by your accountant — ask them to send you an invite.
        </p>
        <p className="text-center text-[12px] text-[#CBD5E1] mt-4">
          <Link href="/login" className="hover:text-[#94A3B8] transition-colors">
            Are you a Chartered Accountant? Sign in here →
          </Link>
        </p>
      </div>
    </div>
  );
}

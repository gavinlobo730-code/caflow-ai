"use client";

/**
 * Forgot Password — request a reset link. Public route (see lib/auth/public-paths.ts,
 * "/login" prefix already covers this nested path).
 *
 * Security: the confirmation message is IDENTICAL whether or not the email is
 * registered — never reveal account existence via this form (a classic account-
 * enumeration leak). Supabase Auth's resetPasswordForEmail() itself does not
 * error on an unknown email either, so this is consistent end-to-end. Supabase
 * also rate-limits this endpoint server-side (per-project email quota + a
 * per-address cooldown between sends), so no extra client-side throttling is
 * needed beyond disabling the button once a request is in flight.
 */
import { useState, FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { ArrowRight, ArrowLeft, MailCheck } from "lucide-react";

export default function ForgotPasswordPage() {
  const supabase = getSupabaseClient();
  // Shared by firm staff (/login/forgot-password) and client portal contacts
  // (/login/forgot-password?portal=1) — one Supabase reset flow either way;
  // this only changes the copy/back-link so a client isn't shown a CA-flavored
  // placeholder or sent back to the wrong sign-in page.
  const isPortal = useSearchParams().get("portal") === "1";
  const backHref = isPortal ? "/portal/login" : "/login";
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const redirectTo = `${window.location.origin}/auth/reset-password/`;
      await supabase.auth.resetPasswordForEmail(email.trim(), { redirectTo });
      // Always show success — do not branch on the result, so this form never
      // discloses whether the email belongs to an account.
      setSent(true);
    } catch {
      // Even a network/client error shouldn't leak account state; ask the user
      // to retry rather than surfacing the underlying error.
      setError("Something went wrong sending the reset link. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12 bg-[#F8FAFC]">
      <div className="w-full max-w-[380px]">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-8 h-8 rounded-xl bg-blue-600 flex items-center justify-center text-[13px] font-bold text-white">P</div>
          <span className="text-[16px] font-bold text-[#0F172A]">PracticeSync AI</span>
        </div>

        {sent ? (
          <div className="text-center">
            <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
              <MailCheck size={22} className="text-blue-600" />
            </div>
            <h2 className="text-[22px] font-bold text-[#0F172A] tracking-tight">Check your email</h2>
            <p className="text-[14px] text-[#64748B] mt-2 leading-relaxed">
              If an account exists for <span className="font-medium text-[#334155]">{email.trim()}</span>,
              we&apos;ve sent a link to reset your password. It expires shortly, so use it soon.
            </p>
            <Link
              href={backHref}
              className="inline-flex items-center gap-1.5 text-[13px] text-blue-600 hover:text-blue-700 font-medium mt-6"
            >
              <ArrowLeft size={14} /> Back to sign in
            </Link>
          </div>
        ) : (
          <>
            <div className="mb-8">
              <h2 className="text-[26px] font-bold text-[#0F172A] tracking-tight">Forgot your password?</h2>
              <p className="text-[14px] text-[#64748B] mt-1">
                Enter the email on your account and we&apos;ll send you a link to reset it.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label className="block text-[13px] font-semibold text-[#0F172A]">Email address</label>
                <input
                  autoFocus type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder={isPortal ? "you@company.com" : "ca@yourfirm.com"}
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
                  <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Sending…</>
                ) : (
                  <>Send reset link <ArrowRight size={15} /></>
                )}
              </button>
            </form>

            <p className="text-center text-[13px] text-[#94A3B8] mt-6">
              <Link href={backHref} className="inline-flex items-center gap-1.5 text-blue-600 hover:text-blue-700 font-medium transition-colors">
                <ArrowLeft size={14} /> Back to sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}

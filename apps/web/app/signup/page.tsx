"use client";

import { useState } from "react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { ArrowRight, Mail } from "lucide-react";

export default function SignupPage() {
  const [firmName, setFirmName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!firmName.trim() || !fullName.trim() || !email.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (typeof window !== "undefined") {
        localStorage.setItem(
          "practicesync_signup",
          JSON.stringify({ firmName: firmName.trim(), fullName: fullName.trim() })
        );
      }
      const supabase = getSupabaseClient();
      const { error: otpErr } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          emailRedirectTo:
            (typeof window !== "undefined" ? window.location.origin : "") + "/onboarding",
        },
      });
      if (otpErr) throw new Error(otpErr.message);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] px-6 py-12">
      <div className="w-full max-w-[420px]">

        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-[13px] font-bold text-white">P</div>
          <span className="text-[16px] font-bold text-[#0F172A]">PracticeSync AI</span>
        </div>

        <div className="bg-white rounded-2xl border border-[#E2E8F0] shadow-sm p-8">
          {sent ? (
            <div className="text-center space-y-4 py-4">
              <div className="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mx-auto">
                <Mail size={22} className="text-emerald-600" />
              </div>
              <div>
                <h2 className="text-[18px] font-bold text-[#0F172A]">Check your inbox</h2>
                <p className="text-[14px] text-[#64748B] mt-2 leading-relaxed">
                  We sent a magic link to <span className="text-[#0F172A] font-medium">{email}</span>. Click it to finish setting up your firm.
                </p>
                <p className="text-[12px] text-[#94A3B8] mt-3">Didn&apos;t receive it? Check your spam folder.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="mb-6">
                <h2 className="text-[22px] font-bold text-[#0F172A] tracking-tight">Create your firm</h2>
                <p className="text-[14px] text-[#64748B] mt-1">Get started in minutes — no credit card required</p>
              </div>

              {error && (
                <div className="flex items-start gap-2.5 p-3.5 rounded-lg bg-red-50 border border-red-100 mb-5">
                  <div className="w-4 h-4 rounded-full bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-red-500 text-[10px] font-bold leading-none">!</span>
                  </div>
                  <p className="text-[13px] text-red-600 leading-snug">{error}</p>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {[
                  { label: "Firm Name", value: firmName, setter: setFirmName, placeholder: "e.g. Sharma & Associates", type: "text" },
                  { label: "Your Full Name", value: fullName, setter: setFullName, placeholder: "e.g. CA Ravi Sharma", type: "text" },
                  { label: "Email Address", value: email, setter: setEmail, placeholder: "you@example.com", type: "email" },
                ].map(({ label, value, setter, placeholder, type }) => (
                  <div key={label} className="space-y-1.5">
                    <label className="block text-[13px] font-semibold text-[#0F172A]">{label}</label>
                    <input
                      type={type} value={value} onChange={(e) => setter(e.target.value)}
                      placeholder={placeholder} required
                      className="w-full bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 text-[14px] text-[#0F172A] placeholder:text-[#CBD5E1] outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/[0.08] transition-all"
                    />
                  </div>
                ))}
                <button
                  type="submit" disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm mt-2"
                >
                  {loading ? (
                    <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Sending…</>
                  ) : (
                    <>Get started <ArrowRight size={15} /></>
                  )}
                </button>
              </form>

              <p className="text-center text-[13px] text-[#94A3B8] mt-5">
                Already have an account?{" "}
                <Link href="/login" className="text-blue-600 hover:text-blue-700 font-medium transition-colors">
                  Sign in →
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

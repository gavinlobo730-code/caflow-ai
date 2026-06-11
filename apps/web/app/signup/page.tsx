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
            (typeof window !== "undefined" ? window.location.origin : "") +
            "/onboarding",
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
    <div className="min-h-screen flex items-center justify-center bg-[#080B12] px-6 py-12">
      <div className="w-full max-w-[380px]">

        {/* Logo */}
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-8 h-8 rounded-[9px] bg-blue-500 flex items-center justify-center text-[13px] font-bold text-white shadow-[0_0_20px_rgba(59,130,246,0.4)]">P</div>
          <span className="text-[15px] font-semibold text-white/90 tracking-tight">PracticeSync AI</span>
        </div>

        <div className="bg-[#0F1219] border border-white/[0.08] rounded-xl shadow-[0_24px_48px_rgba(0,0,0,0.4)]">
          {sent ? (
            <div className="p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mx-auto">
                <Mail size={20} className="text-emerald-400" />
              </div>
              <div>
                <h2 className="text-[17px] font-semibold text-white/90">Check your inbox</h2>
                <p className="text-[13px] text-white/40 mt-2 leading-relaxed">
                  We sent a magic link to <span className="text-white/65 font-medium">{email}</span>. Click it to finish setting up your firm.
                </p>
                <p className="text-[12px] text-white/25 mt-3">Didn&apos;t receive it? Check your spam folder.</p>
              </div>
            </div>
          ) : (
            <div className="p-8">
              <div className="mb-6">
                <h2 className="text-[20px] font-semibold text-white/90 tracking-tight">Create your firm</h2>
                <p className="text-[13px] text-white/40 mt-1">Get started in minutes — no credit card required</p>
              </div>

              {error && (
                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-red-500/[0.08] border border-red-500/20 mb-4">
                  <div className="w-4 h-4 rounded-full bg-red-500/20 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-red-400 text-[10px] font-bold leading-none">!</span>
                  </div>
                  <p className="text-[12.5px] text-red-400 leading-snug">{error}</p>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {[
                  { label: "Firm Name", value: firmName, setter: setFirmName, placeholder: "e.g. Sharma & Associates", type: "text" },
                  { label: "Your Full Name", value: fullName, setter: setFullName, placeholder: "e.g. CA Ravi Sharma", type: "text" },
                  { label: "Email Address", value: email, setter: setEmail, placeholder: "you@example.com", type: "email" },
                ].map(({ label, value, setter, placeholder, type }) => (
                  <div key={label} className="space-y-1.5">
                    <label className="block text-[11.5px] font-medium text-white/50 uppercase tracking-wider">{label}</label>
                    <input
                      type={type}
                      value={value}
                      onChange={(e) => setter(e.target.value)}
                      placeholder={placeholder}
                      required
                      className="w-full bg-[#141820] border border-white/[0.09] rounded-lg px-3.5 py-2.5 text-[13.5px] text-white/85 placeholder:text-white/20 outline-none focus:border-blue-500/60 focus:ring-2 focus:ring-blue-500/15 transition-all"
                    />
                  </div>
                ))}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13.5px] font-semibold px-4 py-2.5 rounded-lg transition-colors mt-2 shadow-[0_4px_12px_rgba(59,130,246,0.25)]"
                >
                  {loading ? (
                    <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />Sending…</>
                  ) : (
                    <>Get started <ArrowRight size={14} /></>
                  )}
                </button>
              </form>

              <p className="text-center text-[12px] text-white/30 mt-5">
                Already have an account?{" "}
                <Link href="/login" className="text-blue-400 hover:text-blue-300 transition-colors">
                  Sign in →
                </Link>
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

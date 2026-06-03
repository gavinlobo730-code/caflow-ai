"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth/AuthContext";
import { Sparkles, Shield, Zap, TrendingUp } from "lucide-react";

const FEATURES = [
  { icon: Shield, text: "GST, ITR & TDS all in one place" },
  { icon: Zap, text: "AI-powered compliance reminders" },
  { icon: TrendingUp, text: "Real-time practice analytics" },
];

export default function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await signIn(email, password);
    if (error) { setError(error); setLoading(false); }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left panel — brand */}
      <div className="hidden lg:flex flex-col justify-between w-[480px] shrink-0 bg-gradient-to-br from-indigo-900 via-indigo-800 to-violet-900 p-12 relative overflow-hidden">
        {/* Background decoration */}
        <div className="absolute top-0 right-0 w-64 h-64 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/2" />
        <div className="absolute bottom-0 left-0 w-96 h-96 bg-white/5 rounded-full translate-y-1/2 -translate-x-1/4" />

        {/* Logo */}
        <div className="relative z-10 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm">
            <span className="text-white font-bold text-sm">CA</span>
          </div>
          <div>
            <span className="text-white font-bold text-xl tracking-tight">CAflow</span>
            <span className="text-indigo-300 font-bold text-xl ml-1">AI</span>
          </div>
        </div>

        {/* Hero text */}
        <div className="relative z-10 space-y-8">
          <div>
            <h1 className="text-4xl font-bold text-white leading-tight">
              Practice management<br />
              <span className="text-indigo-300">built for Indian CAs</span>
            </h1>
            <p className="text-indigo-200 mt-4 text-base leading-relaxed">
              Replace Tally + ClearTax + Winman + WhatsApp with one AI-first platform.
            </p>
          </div>

          <div className="space-y-4">
            {FEATURES.map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/10 border border-white/10 flex items-center justify-center shrink-0">
                  <Icon size={15} className="text-indigo-300" />
                </div>
                <p className="text-indigo-100 text-sm font-medium">{text}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 text-indigo-400 text-xs">
          © 2026 CAflow AI. Trusted by CA firms across India.
        </p>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center bg-[hsl(220,20%,97%)] px-6 py-12">
        <div className="w-full max-w-sm">

          {/* Mobile logo */}
          <div className="lg:hidden flex items-center justify-center gap-2.5 mb-8">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-md">
              <span className="text-white font-bold text-sm">CA</span>
            </div>
            <span className="text-xl font-bold text-gray-900">
              CAflow<span className="text-indigo-600">AI</span>
            </span>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8">
            {/* Header */}
            <div className="mb-7">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center">
                  <Sparkles size={13} className="text-white" />
                </div>
                <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">Welcome back</span>
              </div>
              <h2 className="text-2xl font-bold text-gray-900">Sign in to your firm</h2>
              <p className="text-sm text-gray-500 mt-1">Enter your credentials to continue</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5 uppercase tracking-wide">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ca@yourfirm.com"
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 focus:bg-white transition-all placeholder:text-gray-400"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5 uppercase tracking-wide">
                  Password
                </label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 focus:bg-white transition-all placeholder:text-gray-400"
                />
              </div>

              {error && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-100">
                  <div className="w-4 h-4 rounded-full bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-red-600 text-[10px] font-bold">!</span>
                  </div>
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-sm font-semibold text-white hover:from-indigo-700 hover:to-violet-700 disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md hover:scale-[1.01] active:scale-100"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Signing in…
                  </span>
                ) : "Sign in →"}
              </button>
            </form>
          </div>

          <p className="text-center text-xs text-gray-400 mt-4">
            New firm?{" "}
            <Link href="/signup" className="text-indigo-600 hover:underline">
              Create your account →
            </Link>
          </p>
          <p className="text-center text-xs text-gray-400 mt-2">
            CAflow AI — AI-powered practice management for Indian CAs
          </p>
        </div>
      </div>
    </div>
  );
}

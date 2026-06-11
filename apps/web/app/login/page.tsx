"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthContext";
import { Shield, Zap, TrendingUp, ArrowRight } from "lucide-react";

const FEATURES = [
  { icon: Shield, label: "GST · ITR · TDS · MCA", desc: "All compliance in one place" },
  { icon: Zap,    label: "AI-powered automation",  desc: "Reminders, drafts, insights" },
  { icon: TrendingUp, label: "Practice analytics", desc: "Client health, deadlines, revenue" },
];

export default function LoginPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error } = await signIn(email, password);
      if (error) { setError(error); setLoading(false); }
      else { router.push("/"); }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection error. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex bg-[#080B12]">

      {/* ── Left brand panel ── */}
      <div className="hidden lg:flex flex-col justify-between w-[420px] shrink-0 bg-[#0A0D16] border-r border-white/[0.06] p-10 relative overflow-hidden">
        {/* Subtle grid */}
        <div className="absolute inset-0 opacity-[0.015]"
          style={{ backgroundImage: "linear-gradient(hsl(220 90% 60%) 1px, transparent 1px), linear-gradient(90deg, hsl(220 90% 60%) 1px, transparent 1px)", backgroundSize: "40px 40px" }} />
        {/* Glow */}
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 rounded-full bg-blue-500/[0.06] blur-3xl pointer-events-none" />

        {/* Logo */}
        <div className="relative z-10 flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-[9px] bg-blue-500 flex items-center justify-center text-[13px] font-bold text-white shadow-[0_0_20px_rgba(59,130,246,0.4)]">
            P
          </div>
          <span className="text-[15px] font-semibold text-white/90 tracking-tight">PracticeSync AI</span>
        </div>

        {/* Hero */}
        <div className="relative z-10 space-y-8">
          <div>
            <h1 className="text-3xl font-bold text-white leading-snug tracking-tight">
              The operating system<br />
              <span className="text-blue-400">for modern CA firms</span>
            </h1>
            <p className="text-[13.5px] text-white/45 mt-3 leading-relaxed">
              Manage clients, compliance, accounting,<br />payroll and documents from one workspace.
            </p>
          </div>

          <div className="space-y-3">
            {FEATURES.map(({ icon: Icon, label, desc }) => (
              <div key={label} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[#131620]/[0.05] border border-white/[0.07] flex items-center justify-center shrink-0">
                  <Icon size={14} className="text-blue-400" />
                </div>
                <div>
                  <p className="text-[12.5px] font-medium text-white/75">{label}</p>
                  <p className="text-[11px] text-white/35">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 text-[11px] text-white/25">
          © 2026 PracticeSync AI — Trusted by accounting firms across India
        </p>
      </div>

      {/* ── Right form panel ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-[360px]">

          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-2.5 justify-center mb-8">
            <div className="w-8 h-8 rounded-[9px] bg-blue-500 flex items-center justify-center text-[13px] font-bold text-white">P</div>
            <span className="text-[15px] font-semibold text-white/90">PracticeSync AI</span>
          </div>

          {/* Card */}
          <div className="bg-[#0F1219] border border-white/[0.08] rounded-xl p-8 shadow-[0_24px_48px_rgba(0,0,0,0.4)]">

            <div className="mb-6">
              <h2 className="text-[20px] font-semibold text-white/90 tracking-tight">Sign in</h2>
              <p className="text-[13px] text-white/40 mt-1">Enter your credentials to continue</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="block text-[11.5px] font-medium text-white/50 uppercase tracking-wider">
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ca@yourfirm.com"
                  className="w-full bg-[#141820] border border-white/[0.09] rounded-lg px-3.5 py-2.5 text-[13.5px] text-white/85 placeholder:text-white/20 outline-none focus:border-blue-500/60 focus:ring-2 focus:ring-blue-500/15 transition-all"
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-[11.5px] font-medium text-white/50 uppercase tracking-wider">
                  Password
                </label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-[#141820] border border-white/[0.09] rounded-lg px-3.5 py-2.5 text-[13.5px] text-white/85 placeholder:text-white/20 outline-none focus:border-blue-500/60 focus:ring-2 focus:ring-blue-500/15 transition-all"
                />
              </div>

              {error && (
                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-red-500/[0.08] border border-red-500/20">
                  <div className="w-4 h-4 rounded-full bg-red-500/20 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-red-400 text-[10px] font-bold leading-none">!</span>
                  </div>
                  <p className="text-[12.5px] text-red-400 leading-snug">{error}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13.5px] font-semibold px-4 py-2.5 rounded-lg transition-colors mt-2 shadow-[0_4px_12px_rgba(59,130,246,0.25)]"
              >
                {loading ? (
                  <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />Signing in…</>
                ) : (
                  <>Sign in <ArrowRight size={14} /></>
                )}
              </button>
            </form>
          </div>

          <p className="text-center text-[12px] text-white/30 mt-4">
            New to PracticeSync?{" "}
            <Link href="/signup" className="text-blue-400 hover:text-blue-300 transition-colors">
              Create your account →
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

import type { Metadata } from "next";
import type { CSSProperties } from "react";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Building, Users, ArrowRight, ArrowLeft, Check, Lock } from "@/components/icons";
import { instrumentSerif, manrope } from "@/lib/fonts";
import { appLinks } from "@/lib/site";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to PracticeSync — choose the firm workspace or the client portal.",
};

const VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 200px rgba(0,0,0,0.5)" };

const OPTIONS = [
  {
    key: "firm",
    icon: <Building size={24} />,
    title: "Chartered Accountant",
    tag: "Firm workspace",
    desc: "All modules — compliance, accounting, payroll, clients and practice analytics.",
    points: ["For CAs, partners & firm staff", "Email, password & 2-factor sign-in"],
    href: appLinks.firmLogin,
    primary: true,
  },
  {
    key: "client",
    icon: <Users size={24} />,
    title: "Client & SME",
    tag: "Client portal",
    desc: "View documents, approve invoices and access payslips shared by your CA.",
    points: ["For clients invited by their firm", "Secure magic-link sign-in"],
    href: appLinks.clientPortal,
    primary: false,
  },
];

export default function AccessPage() {
  return (
    <main
      className={`relative min-h-screen overflow-hidden bg-brand-dark text-white ${instrumentSerif.variable} ${manrope.variable} font-manrope`}
      style={VIGNETTE}
    >
      {/* soft brand wash from the top, echoing the homepage's dark panels */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-brand-light/[0.06] to-transparent" />

      <div className="relative z-[1] mx-auto flex min-h-screen max-w-4xl flex-col px-6 py-8">
        {/* Top bar */}
        <div className="flex items-center justify-between">
          <Logo theme="dark" />
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium text-white/60 transition-colors hover:bg-white/10 hover:text-white"
          >
            <ArrowLeft size={15} />
            Back to site
          </Link>
        </div>

        {/* Chooser */}
        <div className="flex flex-1 flex-col justify-center py-10">
          <div className="mx-auto max-w-xl text-center">
            <span className="block text-[12px] font-semibold uppercase tracking-[0.18em] text-gold">Welcome back</span>
            <h1 className="fade-up mt-5 font-display text-[clamp(34px,5vw,52px)] font-normal leading-[1.1] tracking-[-0.015em] text-white">
              Sign in to <span className="italic">PracticeSync.</span>
            </h1>
            <p className="fade-up mt-4 text-[16px] text-slate-300" style={{ animationDelay: "150ms" }}>
              Choose how you&apos;d like to continue.
            </p>
          </div>

          <div className="mt-12 grid gap-5 sm:grid-cols-2">
            {OPTIONS.map((opt, i) => (
              <a
                key={opt.key}
                href={opt.href}
                className={`fade-up group flex flex-col rounded-2xl border p-6 transition-colors ${
                  opt.primary
                    ? "border-brand-light/25 bg-white/[0.05] hover:bg-white/[0.08]"
                    : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                }`}
                style={{ animationDelay: `${300 + i * 130}ms` }}
              >
                <span
                  className={`grid h-14 w-14 place-items-center rounded-2xl ${
                    opt.primary
                      ? "bg-brand-light/15 text-brand-light ring-1 ring-white/10"
                      : "bg-white/[0.06] text-white/80 ring-1 ring-white/10"
                  }`}
                >
                  {opt.icon}
                </span>

                <p className="mt-5 text-[12px] font-semibold uppercase tracking-[0.14em] text-gold">{opt.tag}</p>
                <h2 className="mt-1.5 font-display text-[24px] italic text-white">{opt.title}</h2>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-300">{opt.desc}</p>

                <ul className="mt-4 space-y-2">
                  {opt.points.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-[13px] text-slate-400">
                      <Check size={15} className="mt-0.5 shrink-0 text-brand-light" />
                      {p}
                    </li>
                  ))}
                </ul>

                <span
                  className={`mt-6 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[14px] font-semibold transition-colors ${
                    opt.primary
                      ? "bg-brand-light text-brand-dark group-hover:bg-white"
                      : "border border-white/25 text-white group-hover:bg-white/10"
                  }`}
                >
                  Login
                  <ArrowRight size={15} />
                </span>
              </a>
            ))}
          </div>

          {/* Signup + trust */}
          <div className="fade-up mx-auto mt-10 max-w-lg text-center" style={{ animationDelay: "600ms" }}>
            <p className="text-[14px] text-slate-300">
              New firm?{" "}
              <a href={appLinks.signup} className="font-semibold text-brand-light underline-offset-4 hover:underline">
                Start a free trial →
              </a>
            </p>
            <p className="mt-6 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.04] px-3.5 py-1.5 text-[12px] text-white/50">
              <Lock size={13} />
              Protected with 2-factor authentication · Data hosted in India
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

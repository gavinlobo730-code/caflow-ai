import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { WordReveal } from "@/components/motion";
import { CustomCursor } from "@/components/Cursor";
import { Building, Users, ArrowRight, ArrowLeft, Check, Lock } from "@/components/icons";
import { appLinks } from "@/lib/site";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to PracticeSync — choose the firm workspace or the client portal.",
};

const OPTIONS = [
  {
    key: "firm",
    icon: <Building size={26} />,
    title: "Chartered Accountant",
    tag: "Firm workspace",
    desc: "All modules — compliance, accounting, payroll, clients and practice analytics.",
    points: ["For CAs, partners & firm staff", "Email, password & 2-factor sign-in"],
    href: appLinks.firmLogin,
    primary: true,
  },
  {
    key: "client",
    icon: <Users size={26} />,
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
    <main className="relative min-h-screen bg-ps-bg">
      <CustomCursor />
      {/* soft brand wash */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-gradient-to-b from-brand/[0.05] to-transparent" />

      <div className="relative mx-auto flex min-h-screen max-w-4xl flex-col px-6 py-8">
        {/* Top bar */}
        <div className="flex items-center justify-between">
          <Logo />
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium text-slate-500 transition-colors hover:bg-white hover:text-brand"
          >
            <ArrowLeft size={15} />
            Back to site
          </Link>
        </div>

        {/* Chooser */}
        <div className="flex flex-1 flex-col justify-center py-10">
          <div className="mx-auto max-w-lg text-center">
            <h1 className="text-[28px] font-bold tracking-tight text-brand-dark md:text-[32px]">
              <WordReveal text="Sign in to PracticeSync" startDelay={100} stagger={70} />
            </h1>
            <p className="fade-up mt-3 text-[15px] text-slate-500" style={{ animationDelay: "450ms" }}>
              Choose how you&apos;d like to continue.
            </p>
          </div>

          <div className="mt-10 grid gap-5 sm:grid-cols-2">
            {OPTIONS.map((opt, i) => (
              <a
                key={opt.key}
                href={opt.href}
                className="card-lift fade-up group flex flex-col rounded-2xl border border-ps-border bg-white p-6 shadow-card"
                style={{ animationDelay: `${550 + i * 140}ms` }}
              >
                <span
                  className={`grid h-14 w-14 place-items-center rounded-2xl ${
                    opt.primary
                      ? "bg-brand text-white"
                      : "bg-brand/[0.06] text-brand ring-1 ring-brand/10"
                  }`}
                >
                  {opt.icon}
                </span>

                <p className="mt-5 text-[12px] font-semibold uppercase tracking-wider text-gold">
                  {opt.tag}
                </p>
                <h2 className="mt-1 text-[20px] font-bold text-brand-dark">{opt.title}</h2>
                <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{opt.desc}</p>

                <ul className="mt-4 space-y-2">
                  {opt.points.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-[13px] text-slate-500">
                      <Check size={15} className="mt-0.5 shrink-0 text-emerald-500" />
                      {p}
                    </li>
                  ))}
                </ul>

                <span
                  className={`mt-6 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[14px] font-semibold transition-colors ${
                    opt.primary
                      ? "bg-brand text-white group-hover:bg-brand-hover"
                      : "border border-ps-border text-brand group-hover:bg-ps-muted"
                  }`}
                >
                  Login
                  <ArrowRight size={15} />
                </span>
              </a>
            ))}
          </div>

          {/* Signup + trust */}
          <div className="fade-up mx-auto mt-10 max-w-lg text-center" style={{ animationDelay: "900ms" }}>
            <p className="text-[14px] text-slate-500">
              New firm?{" "}
              <a
                href={appLinks.signup}
                className="font-semibold text-brand underline-offset-4 hover:underline"
              >
                Start a free trial →
              </a>
            </p>
            <p className="mt-6 inline-flex items-center gap-2 rounded-full border border-ps-border bg-white px-3.5 py-1.5 text-[12px] text-slate-400">
              <Lock size={13} />
              Protected with 2-factor authentication · Data hosted in India
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

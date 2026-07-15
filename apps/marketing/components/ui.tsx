import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight } from "./icons";
import { appLinks } from "@/lib/site";

// Shared presentational primitives for the marketing pages. Keeping these in one
// place is what makes Home / Products / Pricing / Support / Resources read as a
// single design system.

export function Section({
  id,
  className = "",
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`py-20 md:py-28 ${className}`}>
      <div className="container-ps">{children}</div>
    </section>
  );
}

export function Eyebrow({
  children,
  tone = "gold",
}: {
  children: ReactNode;
  tone?: "gold" | "light";
}) {
  const color = tone === "gold" ? "text-gold" : "text-brand-light";
  const rule = tone === "gold" ? "bg-gold/50" : "bg-brand-light/50";
  return (
    <span
      className={`inline-flex items-center gap-2.5 text-[12px] font-semibold uppercase tracking-[0.15em] ${color}`}
    >
      <span className={`h-px w-6 ${rule}`} />
      {children}
    </span>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = "center",
  tone = "light",
}: {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  align?: "center" | "left";
  tone?: "light" | "dark";
}) {
  const titleColor = tone === "dark" ? "text-white" : "text-brand-dark";
  const subColor = tone === "dark" ? "text-slate-300" : "text-slate-600";
  const alignment =
    align === "center" ? "mx-auto max-w-2xl text-center" : "max-w-2xl text-left";
  return (
    <div className={alignment}>
      {eyebrow ? (
        <div className={align === "center" ? "flex justify-center" : ""}>
          <Eyebrow tone={tone === "dark" ? "light" : "gold"}>{eyebrow}</Eyebrow>
        </div>
      ) : null}
      <h2
        className={`mt-4 text-[30px] font-bold leading-tight tracking-tight md:text-[40px] ${titleColor}`}
      >
        {title}
      </h2>
      {subtitle ? (
        <p className={`mt-4 text-[16px] leading-relaxed md:text-[17px] ${subColor}`}>
          {subtitle}
        </p>
      ) : null}
    </div>
  );
}

type ButtonProps = {
  href: string;
  external?: boolean;
  variant?: "primary" | "secondary" | "light" | "ghost-light";
  className?: string;
  children: ReactNode;
};

export function Button({
  href,
  external,
  variant = "primary",
  className = "",
  children,
}: ButtonProps) {
  const styles: Record<NonNullable<ButtonProps["variant"]>, string> = {
    primary: "bg-brand text-white hover:bg-brand-hover shadow-sm",
    secondary: "bg-white text-brand border border-ps-border hover:bg-ps-muted",
    light: "bg-white text-brand hover:bg-ps-muted shadow-sm",
    "ghost-light": "text-white border border-white/25 hover:bg-white/10",
  };
  const cls = `inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-[14px] font-semibold transition-colors ${styles[variant]} ${className}`;
  if (external) {
    return (
      <a href={href} className={cls}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`rounded-2xl border border-ps-border bg-white p-6 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-light/60 hover:shadow-card-hover ${className}`}
    >
      {children}
    </div>
  );
}

export function IconBadge({ children }: { children: ReactNode }) {
  return (
    <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand/[0.06] text-brand ring-1 ring-brand/10">
      {children}
    </span>
  );
}

export function FeatureCard({
  icon,
  title,
  desc,
}: {
  icon: ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <Card>
      <IconBadge>{icon}</IconBadge>
      <h3 className="mt-5 text-[17px] font-bold text-brand-dark">{title}</h3>
      <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{desc}</p>
    </Card>
  );
}

// Consistent dark page header used at the top of the inner marketing pages.
export function PageHero({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden bg-brand-dark text-white">
      <div className="bg-grid absolute inset-0" />
      <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-brand-light/15 blur-[110px]" />
      <div className="container-ps relative py-16 text-center md:py-24">
        {eyebrow ? (
          <div className="flex justify-center">
            <Eyebrow tone="light">{eyebrow}</Eyebrow>
          </div>
        ) : null}
        <h1 className="mx-auto mt-4 max-w-3xl text-[34px] font-bold leading-[1.12] tracking-tight md:text-[46px]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mx-auto mt-4 max-w-2xl text-[16px] leading-relaxed text-slate-300 md:text-[17px]">
            {subtitle}
          </p>
        ) : null}
      </div>
    </section>
  );
}

// Reusable closing call-to-action band. Shared across pages for consistency.
export function CTASection({
  title = "Bring your whole practice into one place",
  subtitle = "Start a free trial today, or talk to us about moving your firm across from Tally, ClearTax or Winman.",
}: {
  title?: string;
  subtitle?: string;
}) {
  return (
    <section className="relative overflow-hidden bg-brand text-white">
      <div className="bg-grid absolute inset-0" />
      <div className="container-ps relative py-20 text-center md:py-24">
        <h2 className="mx-auto max-w-2xl text-[28px] font-bold leading-tight tracking-tight md:text-[40px]">
          {title}
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
          {subtitle}
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button href={appLinks.signup} external variant="light" className="px-6 py-3.5">
            Start free trial
            <ArrowRight size={16} />
          </Button>
          <Button href="/support" variant="ghost-light" className="px-6 py-3.5">
            Talk to us
          </Button>
        </div>
      </div>
    </section>
  );
}

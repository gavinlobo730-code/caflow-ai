"use client";

// PageHero and CTASection call useCursorGlow() directly, which requires this
// module itself to be a Client Component (hooks can't run in Server
// Components). The still-server pages (Products/Pricing/Support/Resources)
// are unaffected — a server component can render an imported client
// component as a child with no changes on its end; only a component that
// calls a hook in its own body needs the boundary.
import Link from "next/link";
import { forwardRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { ArrowRight } from "./icons";
import { Reveal, WordReveal } from "./motion";
import { Magnetic, useCursorGlow } from "./Cursor";
import { appLinks } from "@/lib/site";

// Shared presentational primitives for the marketing pages. Keeping these in one
// place is what makes Home / Products / Pricing / Support / Resources read as a
// single design system.

// forwardRef so callers (currently just the home page's flowing background)
// can measure this section's own box — a plain function component can't
// accept a ref at all, and the vast majority of Section's callers don't need
// one, so this is additive rather than a behavior change for them.
export const Section = forwardRef<
  HTMLElement,
  { id?: string; className?: string; style?: CSSProperties; children: ReactNode }
>(function Section({ id, className = "", style, children }, ref) {
  return (
    <section ref={ref} id={id} className={`py-20 md:py-28 ${className}`} style={style}>
      <div className="container-ps">{children}</div>
    </section>
  );
});

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
  variant?: "primary" | "secondary" | "light" | "ghost-light" | "accent";
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
    primary: "btn-shine bg-brand text-white hover:bg-brand-hover shadow-sm hover:shadow-[0_8px_24px_rgba(24,35,80,0.25)]",
    secondary: "bg-white text-brand border border-ps-border hover:bg-ps-muted",
    light: "btn-shine bg-white text-brand hover:bg-ps-muted shadow-sm",
    "ghost-light": "text-white border border-white/25 hover:bg-white/10",
    // The homepage's own "Start free trial" treatment (oklch(58% 0.13 267),
    // its one accent color) — for the CTAs that are meant to read as the exact
    // same button as the homepage's, not the white/glass buttons elsewhere.
    accent: "btn-shine bg-[#5876c7] text-white hover:bg-[#4d68af] shadow-sm",
  };
  const cls = `inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-[14px] font-semibold transition-all duration-300 ${styles[variant]} ${className}`;
  const inner = external ? (
    <a href={href} className={cls}>
      {children}
    </a>
  ) : (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
  // Magnetic pull only on the solid, high-emphasis variants — the actual
  // primary CTAs. Applying it to every button/link everywhere would compete
  // with itself; this keeps the effect meaning something.
  if (variant === "primary" || variant === "light" || variant === "accent") {
    return <Magnetic>{inner}</Magnetic>;
  }
  return inner;
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
      className={`card-lift rounded-2xl border border-ps-border bg-white p-6 shadow-card ${className}`}
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
    <Card className="h-full">
      <span className="icon-pop inline-flex">
        <IconBadge>{icon}</IconBadge>
      </span>
      <h3 className="mt-5 text-[17px] font-bold text-brand-dark">{title}</h3>
      <p className="mt-2 text-[14px] leading-relaxed text-slate-600">{desc}</p>
    </Card>
  );
}

// Consistent dark page header used at the top of the inner marketing pages.
// String titles materialise word by word; the background carries the same
// living aurora as the home hero so every page opens with motion.
export function PageHero({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
}) {
  const glow = useCursorGlow();
  return (
    <section
      className="relative overflow-hidden bg-brand-dark text-white"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-40 -top-40 h-[420px] w-[420px]" />
      <div className="aurora aurora-2 -right-32 -bottom-48 h-[460px] w-[460px]" />
      <div className="bg-noise absolute inset-0" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
      <div className="container-ps relative py-16 text-center md:py-24">
        {eyebrow ? (
          <div className="fade-up flex justify-center" style={{ animationDelay: "60ms" }}>
            <Eyebrow tone="light">{eyebrow}</Eyebrow>
          </div>
        ) : null}
        <h1 className="mx-auto mt-4 max-w-3xl text-[34px] font-bold leading-[1.12] tracking-tight md:text-[46px]">
          {typeof title === "string" ? (
            <WordReveal text={title} startDelay={150} stagger={60} />
          ) : (
            title
          )}
        </h1>
        {subtitle ? (
          <p
            className="fade-up mx-auto mt-4 max-w-2xl text-[16px] leading-relaxed text-slate-300 md:text-[17px]"
            style={{ animationDelay: "650ms" }}
          >
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
  const glow = useCursorGlow();
  return (
    <section
      className="relative overflow-hidden bg-brand text-white"
      {...glow.handlers}
    >
      <div className="bg-grid absolute inset-0" />
      <div className="aurora aurora-1 -left-32 -top-32 h-[380px] w-[380px] opacity-70" />
      <div className="aurora aurora-3 -bottom-40 -right-28 h-[420px] w-[420px] opacity-70" />
      <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
      <div className="container-ps relative py-20 text-center md:py-24">
        <Reveal variant="blur">
          <h2 className="mx-auto max-w-2xl text-[28px] font-bold leading-tight tracking-tight md:text-[40px]">
            {title}
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-slate-300">
            {subtitle}
          </p>
        </Reveal>
        <Reveal delay={150}>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button href={appLinks.signup} external variant="light" className="px-6 py-3.5">
              Start free trial
              <ArrowRight size={16} />
            </Button>
            <Button href="/support" variant="ghost-light" className="px-6 py-3.5">
              Talk to us
            </Button>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

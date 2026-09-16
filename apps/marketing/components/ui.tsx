"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Magnetic } from "./Cursor";

/**
 * The button, and nothing else.
 *
 * THIS FILE USED TO BE A SECOND DESIGN SYSTEM. It exported nine things —
 * `Section`, `Eyebrow`, `SectionHeading`, `Card`, `IconBadge`, `FeatureCard`,
 * `PageHero`, `CTASection` and `Button` — and on 16 September 2026 a grep found
 * that exactly one of them, `Button`, was imported anywhere. The other eight
 * were the marketing site's PREVIOUS look, left behind when cinematic.tsx
 * replaced it, and they were not inert: `CTASection` carried its own closing
 * copy which had already drifted from `CineCTA`'s, `SectionHeading` had its own
 * heading scale, and `PageHero` its own page-top treatment. Three different
 * answers to "what does a section heading look like", two of them unreachable.
 *
 * CLAUDE.md says this in several places about several subsystems: two
 * implementations drift, and the dead one is what the next person reaches for
 * because it is shorter. So they are deleted rather than left for later, and
 * `tests/test_the_marketing_site_says_what_the_product_does.py` asserts this
 * module does not grow a heading, hero or CTA primitive back —
 * components/cinematic.tsx is where those live.
 *
 * `Button` stays here rather than moving into cinematic.tsx because
 * cinematic.tsx imports it, and the reverse would be a cycle.
 */

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
    primary:
      "btn-shine bg-brand text-white hover:bg-brand-hover shadow-sm hover:shadow-[0_8px_24px_rgba(24,35,80,0.25)]",
    secondary: "bg-white text-brand border border-ps-border hover:bg-ps-muted",
    light: "btn-shine bg-white text-brand hover:bg-ps-muted shadow-sm",
    "ghost-light": "text-white border border-white/25 hover:bg-white/10",
    // The one accent colour on the site — the same #5876c7 the header's "Book a
    // demo" and the hero's primary CTA use, so a filled accent button is the
    // same button wherever it appears.
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
  // primary CTAs. Applying it to every button everywhere would compete with
  // itself; this keeps the effect meaning something.
  if (variant === "primary" || variant === "light" || variant === "accent") {
    return <Magnetic>{inner}</Magnetic>;
  }
  return inner;
}

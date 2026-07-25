"use client";

import type { CSSProperties, ReactNode } from "react";
import { Reveal, WordReveal, useInView } from "./motion";
import { Button } from "./ui";
import { ArrowRight, Check } from "./icons";
import { appLinks } from "@/lib/site";

// Cinematic section primitives that carry the homepage's design language onto
// the inner marketing pages: alternating navy / light panels joined by the
// same diagonal seams, Instrument Serif headlines with italic emphasis lines,
// gold eyebrows, and an inset vignette on the dark panels. Kept separate from
// ui.tsx (the older light card system) so pages can be migrated one at a time.

const VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 160px rgba(0,0,0,0.45)" };

// Diagonal seam — a panel overlaps the previous by 64px and angle-cuts its top
// edge, exactly like the homepage. `seam` direction alternates down the page:
//   rising-right → a light panel following a dark one (edge rises left→right)
//   rising-left  → a dark panel following a light one (edge rises right→left)
//   none         → the first panel on the page (straight top edge)
const SEAM_CLIP: Record<string, string | undefined> = {
  "rising-right": "polygon(0 64px, 100% 0, 100% 100%, 0 100%)",
  "rising-left": "polygon(0 0, 100% 64px, 100% 100%, 0 100%)",
  none: undefined,
};

export function Panel({
  theme = "dark",
  seam = "none",
  id,
  numeral,
  numeralCorner = "top-right",
  className = "",
  innerClassName = "",
  children,
}: {
  theme?: "dark" | "light";
  seam?: "rising-left" | "rising-right" | "none";
  id?: string;
  numeral?: string;
  numeralCorner?: "top-right" | "bottom-left";
  className?: string;
  innerClassName?: string;
  children: ReactNode;
}) {
  const clip = SEAM_CLIP[seam];
  const base = theme === "dark" ? "bg-brand-dark text-white" : "bg-ps-bg text-brand-dark";
  // Matches the homepage exactly: a dark panel is full-bleed (it's the same
  // color as the page canvas behind it), but a light panel is a narrower
  // inset "card" — capped at the same width as its own content instead of
  // spanning the viewport — so the dark canvas shows through on its sides.
  const inset = theme === "light" ? "mx-auto max-w-content" : "";
  const style: CSSProperties = {
    ...(theme === "dark" ? VIGNETTE : {}),
    ...(clip ? { clipPath: clip, marginTop: "-64px" } : {}),
  };
  // Compensate the clipped sliver so content clears the diagonal.
  const padTop = clip
    ? "pt-[calc(clamp(80px,12vw,130px)+64px)]"
    : "pt-[clamp(96px,13vw,150px)]";

  const numeralColor = theme === "dark" ? "text-white/[0.05]" : "text-brand-dark/[0.05]";
  const numeralPos =
    numeralCorner === "top-right" ? "-top-[60px] -right-5" : "-bottom-10 -left-6";

  return (
    <section id={id} className={`relative overflow-hidden ${base} ${inset} ${className}`} style={style}>
      {numeral ? (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute z-0 select-none font-display leading-none ${numeralColor} ${numeralPos} text-[clamp(200px,28vw,400px)]`}
        >
          {numeral}
        </div>
      ) : null}
      <div
        className={`relative z-[1] mx-auto max-w-content px-[clamp(20px,6vw,72px)] ${padTop} pb-[clamp(80px,12vw,130px)] ${innerClassName}`}
      >
        {children}
      </div>
    </section>
  );
}

// Eyebrow + serif headline (with optional italic emphasis lines) + subtitle,
// in the homepage's type treatment. `lines` lets a headline mix upright and
// italic lines the way the homepage's kinetic headlines do.
//
// Owns its own scroll-triggered reveal (eyebrow/subtitle fade, headline words
// materialise in) rather than relying on a wrapping <CineReveal> — nesting
// this inside another opacity-fading wrapper would compound two concurrent
// opacity transitions on top of each other (parent × child, both ramping
// 0→1 at once), softening/slowing the reveal instead of a crisp one. Eyebrow
// and subtitle each get their own single-level fade off the same `inView`
// flag the headline's words use, so everything settles in sync without any
// element sitting inside a second, independently-animating opacity ancestor.
export function SerifHeading({
  eyebrow,
  lines,
  subtitle,
  theme = "dark",
  align = "left",
  className = "",
}: {
  eyebrow?: string;
  lines: { text: string; italic?: boolean }[];
  subtitle?: ReactNode;
  theme?: "dark" | "light";
  align?: "left" | "center";
  className?: string;
}) {
  const { ref, inView } = useInView<HTMLDivElement>();
  const titleColor = theme === "dark" ? "text-white" : "text-brand-dark";
  const subColor = theme === "dark" ? "text-slate-300" : "text-slate-600";
  // Matches the homepage exactly: the eyebrow is never an accent color, just
  // the section's own text color at ~50% opacity (the reference uses
  // 0.45-0.55 per section; a flat 50% reads the same everywhere).
  const eyebrowColor = theme === "dark" ? "text-white/50" : "text-brand-dark/50";
  const alignCls = align === "center" ? "mx-auto max-w-3xl text-center" : "max-w-2xl";
  return (
    <div ref={ref} className={`${alignCls} ${className}`}>
      {eyebrow ? (
        <span
          data-in={inView ? "true" : "false"}
          className={`rv rv-up block text-[12px] font-semibold uppercase tracking-[0.18em] ${eyebrowColor} ${align === "center" ? "text-center" : ""}`}
        >
          {eyebrow}
        </span>
      ) : null}
      <h2 className={`mt-6 font-display font-normal leading-[1.14] tracking-[-0.015em] ${titleColor}`}>
        {lines.map((l, i) => {
          const priorWords = lines.slice(0, i).reduce((n, prior) => n + prior.text.split(" ").length, 0);
          return (
            <span
              key={i}
              className={`block ${l.italic ? "italic" : ""} ${
                l.italic
                  ? "text-[clamp(30px,4.6vw,54px)]"
                  : "text-[clamp(28px,4vw,46px)]"
              }`}
            >
              <WordReveal text={l.text} startDelay={priorWords * 60} stagger={60} inView={inView} />
            </span>
          );
        })}
      </h2>
      {subtitle ? (
        <p
          data-in={inView ? "true" : "false"}
          className={`rv rv-up mt-7 max-w-[52ch] text-[17px] leading-[1.65] ${subColor} ${align === "center" ? "mx-auto" : ""}`}
          style={{ transitionDelay: "150ms" }}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  );
}

// Glass card for dark panels — the translucent bordered surface the homepage
// uses over navy, replacing ui.tsx's white Card on cinematic pages.
export function GlassCard({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-white/10 bg-white/[0.03] p-6 md:p-7 ${className}`}>
      {children}
    </div>
  );
}

// Convenience: a Reveal wrapper defaulting to the blur-in used across the
// homepage's focus reveals.
export function CineReveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <Reveal variant="blur" delay={delay} className={className}>
      {children}
    </Reveal>
  );
}

// Divider-ruled checklist that adapts to the panel it sits on — the homepage's
// clean typographic list treatment, used across every cinematic page.
export function Checklist({
  points,
  theme,
}: {
  points: string[];
  theme: "dark" | "light";
}) {
  const rowBorder = theme === "dark" ? "border-white/10" : "border-slate-900/10";
  const textColor = theme === "dark" ? "text-slate-200" : "text-slate-700";
  const chip =
    theme === "dark"
      ? "bg-brand-light/10 text-brand-light ring-white/15"
      : "bg-brand/[0.06] text-brand ring-brand/15";
  return (
    <ul className="flex flex-col">
      {points.map((p, i) => (
        <li
          key={p}
          className={`flex items-start gap-3.5 border-t ${rowBorder} py-4 text-[15px] leading-relaxed ${textColor} ${
            i === points.length - 1 ? `border-b ${rowBorder}` : ""
          }`}
        >
          <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1 ${chip}`}>
            <Check size={12} />
          </span>
          <span>{p}</span>
        </li>
      ))}
    </ul>
  );
}

// Shared closing call-to-action band — a dark panel with a serif headline and
// the two primary actions, mirroring the homepage's final CTA. Reused on every
// inner page so the close is identical everywhere.
export function CineCTA({
  titleLines = [
    { text: "Bring your whole practice", italic: true },
    { text: "into one place." },
  ],
  subtitle = "Start a free trial today, or talk to us about moving your firm across from Tally, ClearTax or Winman.",
  primary = { href: appLinks.signup, label: "Start free trial", external: true },
  secondary = { href: "/support", label: "Talk to us" },
}: {
  titleLines?: { text: string; italic?: boolean }[];
  subtitle?: string;
  primary?: { href: string; label: string; external?: boolean };
  secondary?: { href: string; label: string; external?: boolean };
}) {
  return (
    <Panel theme="dark" seam="rising-left" innerClassName="text-center">
      <SerifHeading align="center" lines={titleLines} subtitle={subtitle} />
      <CineReveal delay={120}>
        <div className="mt-10 flex flex-wrap justify-center gap-5">
          <Button href={primary.href} external={primary.external} variant="accent" className="px-7 py-[15px]">
            {primary.label}
            <ArrowRight size={16} />
          </Button>
          <Button href={secondary.href} external={secondary.external} variant="ghost-light" className="px-7 py-[15px]">
            {secondary.label}
          </Button>
        </div>
      </CineReveal>
    </Panel>
  );
}

"use client";

import type { CSSProperties, ReactNode } from "react";
import { Reveal, WordReveal, useInView } from "./motion";
import { Button } from "./ui";
import { ArrowRight, Check } from "./icons";
import { appLinks } from "@/lib/site";

/**
 * The section primitives every marketing page is built from.
 *
 * THE DIAGONAL SEAM IS GONE (owner review, 16-09-2026: "the diagonal cards dont
 * look good"). It was three `clip-path` polygons here, applied on 20 panels
 * across six pages, each panel pulled up 64px with `marginTop` and each panel's
 * top padding inflated by the same 64px to clear the wedge.
 *
 * It was doing a real job — telling the eye that a section had changed — and a
 * flat butt-join would simply lose that. What replaces it does the same job
 * differently: a light panel is a ROUNDED CARD floating on the navy canvas, and
 * a dark panel carries a soft top gradient. The boundary still reads; it reads
 * as an edge rather than a wedge.
 *
 * `seam` was REMOVED from the props rather than defaulted to "none", so every
 * call site had to be edited and none could quietly keep passing it.
 *
 * THE WATERMARK NUMERALS ARE GONE TOO, for the same reason ("the 01 and the
 * numbering in the big light … dont look asthetic"). They were
 * `clamp(200px, 28vw, 400px)` at 5% opacity in a corner. The wayfinding they
 * provided is kept as `SerifHeading`'s `index` — a 12px tabular figure and a
 * short gold rule beside the eyebrow. An editorial section marker rather than a
 * watermark.
 */

const VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 160px rgba(0,0,0,0.45)" };

export function Panel({
  theme = "dark",
  id,
  flush = false,
  className = "",
  innerClassName = "",
  children,
}: {
  theme?: "dark" | "light";
  id?: string;
  /** Sits directly under the header or another dark panel, so it takes no top
   *  gradient and no extra breathing room above it. */
  flush?: boolean;
  className?: string;
  innerClassName?: string;
  children: ReactNode;
}) {
  const dark = theme === "dark";

  // A light panel is a card: capped at the content width, inset from the
  // viewport edge on small screens so the navy canvas shows all the way round,
  // rounded, hairlined and lifted. A dark panel is the canvas itself, so it is
  // full-bleed and carries the vignette instead.
  const shell = dark
    ? "bg-brand-dark text-white"
    : [
        "mx-auto w-[calc(100%-clamp(16px,4vw,48px))] max-w-content",
        "rounded-[clamp(20px,3vw,40px)] bg-ps-bg text-brand-dark",
        "ring-1 ring-brand-dark/[0.06] shadow-[0_30px_80px_-40px_rgba(6,12,32,0.65)]",
        // The canvas behind a light card is navy, so the card needs air above
        // and below it or it reads as a band rather than a card.
        "my-[clamp(24px,5vw,72px)]",
      ].join(" ");

  return (
    <section
      id={id}
      className={`relative overflow-hidden ${shell} ${className}`}
      style={dark ? VIGNETTE : undefined}
    >
      {/* The section boundary, on a dark panel. A 1px hairline fading out from
          the centre plus a shallow wash below it — enough to say "this is a new
          section" at a glance and nothing like a wedge. Skipped on `flush`
          because the first panel of a page has nothing above it to divide from. */}
      {dark && !flush ? (
        <>
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-px"
            style={{
              background:
                "linear-gradient(90deg,transparent,rgba(175,210,250,0.22) 22%,rgba(175,210,250,0.22) 78%,transparent)",
            }}
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-40"
            style={{
              background:
                "linear-gradient(180deg,rgba(175,210,250,0.055),rgba(175,210,250,0) 100%)",
            }}
          />
        </>
      ) : null}

      {/* A light panel is a CARD and takes less vertical padding than a
          full-bleed dark one. With the seams gone the light panels became
          visible rectangles rather than bands running off both edges, and at a
          dark panel's padding a three-line heading sat inside 260px of empty
          white — which reads as a layout fault rather than as space. */}
      <div
        className={`relative z-[1] mx-auto max-w-content px-[clamp(20px,6vw,72px)] ${
          dark
            ? "pt-[clamp(80px,11vw,130px)] pb-[clamp(80px,11vw,130px)]"
            : "pt-[clamp(56px,7.5vw,96px)] pb-[clamp(56px,7.5vw,96px)]"
        } ${innerClassName}`}
      >
        {children}
      </div>
    </section>
  );
}

/**
 * Eyebrow + serif headline (with optional italic emphasis lines) + subtitle.
 *
 * `index` is the section number. It is a small tabular figure and a gold rule
 * in front of the eyebrow — the replacement for the 400px watermark numerals,
 * and the only place a section number now appears.
 *
 * `layout="split"` puts the headline and the standfirst in two columns. It
 * exists because removing the diagonal seams turned every light panel into a
 * visible CARD: a stacked heading occupies the left 55% of it and leaves the
 * rest blank, which a full-bleed band running off both edges of the viewport
 * had disguised. Two columns is also simply how a magazine sets a headline and
 * its standfirst, so it reads as composition rather than as filling a hole.
 *
 * IT IS A CONTAINER QUERY, NOT A BREAKPOINT, and that is the whole point — see
 * `.ps-split` in globals.css. The first version split at `lg:`, a VIEWPORT
 * width, and /demo puts a heading in a 372px column of a 1440px page: the
 * breakpoint matched, the split fired, and the headline wrapped to eight lines.
 * Asking about the heading's OWN box means no page has to remember where a
 * split is safe, and below the threshold the grid is one column, which is
 * exactly the stacked layout.
 *
 * Owns its own scroll-triggered reveal rather than relying on a wrapping
 * <CineReveal> — nesting this inside another opacity-fading wrapper would
 * compound two concurrent opacity transitions (parent x child, both ramping
 * 0 to 1 at once), softening the reveal instead of sharpening it. Eyebrow and
 * subtitle each get their own single-level fade off the same `inView` flag the
 * headline's words use, so everything settles in sync.
 */
export function SerifHeading({
  eyebrow,
  index,
  lines,
  subtitle,
  theme = "dark",
  align = "left",
  layout = "stack",
  className = "",
}: {
  eyebrow?: string;
  index?: string;
  lines: { text: string; italic?: boolean }[];
  subtitle?: ReactNode;
  theme?: "dark" | "light";
  align?: "left" | "center";
  layout?: "stack" | "split";
  className?: string;
}) {
  const { ref, inView } = useInView<HTMLDivElement>();
  const dark = theme === "dark";
  const titleColor = dark ? "text-white" : "text-brand-dark";
  const subColor = dark ? "text-slate-300" : "text-slate-600";
  // The eyebrow is never an accent colour, just the section's own text colour
  // at ~50%. The gold is reserved for the index rule, so it means one thing.
  const eyebrowColor = dark ? "text-white/50" : "text-brand-dark/50";
  // A split heading owns the full content width; a stacked one is capped so a
  // headline never runs to an unreadable measure.
  const split = layout === "split" && align !== "center";
  const alignCls = align === "center" ? "mx-auto max-w-3xl text-center" : split ? "" : "max-w-2xl";

  const head = (
    <>
      {eyebrow || index ? (
        <span
          data-in={inView ? "true" : "false"}
          className={`rv rv-up flex items-center gap-3 ${align === "center" ? "justify-center" : ""}`}
        >
          {index ? (
            <>
              <span
                // Gold on both themes deliberately: the index is the one
                // place the accent appears, so it means one thing.
                className="font-display text-[13px] leading-none tabular-nums text-gold"
              >
                {index}
              </span>
              <span aria-hidden="true" className="h-px w-7 bg-gold/45" />
            </>
          ) : null}
          {eyebrow ? (
            <span
              className={`text-[12px] font-semibold uppercase leading-none tracking-[0.18em] ${eyebrowColor}`}
            >
              {eyebrow}
            </span>
          ) : null}
        </span>
      ) : null}

      <h2 className={`mt-6 font-display font-normal leading-[1.14] tracking-[-0.015em] ${titleColor}`}>
        {lines.map((l, i) => {
          const priorWords = lines
            .slice(0, i)
            .reduce((n, prior) => n + prior.text.split(" ").length, 0);
          return (
            <span
              key={i}
              className={`block ${l.italic ? "italic" : ""} ${
                l.italic ? "text-[clamp(30px,4.6vw,54px)]" : "text-[clamp(28px,4vw,46px)]"
              }`}
            >
              <WordReveal text={l.text} startDelay={priorWords * 60} stagger={60} inView={inView} />
            </span>
          );
        })}
      </h2>
    </>
  );

  const standfirst = subtitle ? (
    <p
      data-in={inView ? "true" : "false"}
      className={`rv rv-up mt-7 max-w-[52ch] text-[17px] leading-[1.65] ${subColor} ${
        align === "center" ? "mx-auto" : ""
      }`}
      style={{ transitionDelay: "150ms" }}
    >
      {subtitle}
    </p>
  ) : null;

  if (split) {
    return (
      <div ref={ref} className={`ps-split ${className}`}>
        <div className="ps-split-grid">
          <div>{head}</div>
          <div className="ps-split-aside">{standfirst}</div>
        </div>
      </div>
    );
  }

  return (
    <div ref={ref} className={`${alignCls} ${className}`}>
      {head}
      {standfirst}
    </div>
  );
}

// Glass card for dark panels — the translucent bordered surface used over navy.
export function GlassCard({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-white/10 bg-white/[0.03] p-6 md:p-7 ${className}`}>
      {children}
    </div>
  );
}

// Convenience: a Reveal wrapper defaulting to the blur-in used across the site.
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

// Divider-ruled checklist that adapts to the panel it sits on.
export function Checklist({ points, theme }: { points: string[]; theme: "dark" | "light" }) {
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

/**
 * The closing call-to-action, identical on every page.
 *
 * Book a demo is the site's primary conversion goal (owner decision,
 * 16-09-2026), so it is the filled button here and the free trial is the
 * outlined one beside it. This component is the single place that order is set,
 * which is why changing the funnel was one edit rather than five.
 *
 * "Start free trial" is the canonical label, everywhere. The site carried both
 * that and "Start a free trial" until the consistency pass of 16-09-2026 —
 * along with "Book a demo" against "Book a demo", and a lone "Get started".
 */
export function CineCTA({
  titleLines = [
    { text: "Bring your whole practice" },
    { text: "into one place.", italic: true },
  ],
  subtitle = "Book a demo and we'll walk a real client's month end to end — or start a free trial and look around on your own.",
  primary = { href: "/demo", label: "Book a demo" },
  secondary = { href: appLinks.signup, label: "Start free trial", external: true },
}: {
  titleLines?: { text: string; italic?: boolean }[];
  subtitle?: string;
  primary?: { href: string; label: string; external?: boolean };
  secondary?: { href: string; label: string; external?: boolean };
}) {
  return (
    <Panel theme="dark" innerClassName="text-center">
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

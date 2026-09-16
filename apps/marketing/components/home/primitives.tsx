"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useInView, usePrefersReducedMotion } from "../motion";

/**
 * The homepage's own motion primitives, ported from the vanilla-JS engine that
 * used to live inline in public/practicesync-homepage.html.
 *
 * Everything the React pages already had — the `.rv` scroll reveals, the
 * `.word-in` headline entrance, `Tilt`, `Parallax` — is reused from
 * components/motion.tsx rather than re-implemented here. What is in this file
 * is the three effects the homepage had that the shared library did not.
 */

/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Film grain over the whole page — what keeps the large flat navy panels from
 * banding on 8-bit displays.
 *
 * THE FLICKER IS DELIBERATELY GONE. The original re-randomised this element's
 * opacity on a 110ms `setInterval`, i.e. nine full-viewport repaints a second
 * of a fixed layer with `mix-blend-mode: overlay` — one of the more expensive
 * things a page can ask a compositor to do, running forever, on every section
 * of the page including the ones where a WebGL scene is already competing for
 * frames. The grain's whole job is to break up banding, which a static texture
 * does exactly as well. This is the brief's §12 rule applied to something that
 * was already shipped: "Do not add visual effects merely because they are
 * technically possible."
 */
export function Grain() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[60] opacity-[0.045] mix-blend-overlay"
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E\")",
      }}
    />
  );
}

/* ────────────────────────────────────────────────────────────────────────── */

/**
 * The statutory ticker.
 *
 * Deliberately NOT components/motion.tsx's `Marquee`, which is a pure CSS
 * keyframe loop. This one DRIFTS ON ITS OWN and is also pushed by the reader's
 * scrolling, which is the effect the homepage had and the thing that makes it
 * read as part of the page rather than an ornament bolted onto it.
 *
 * Both halves must be identical and must render the same children, because the
 * seamless loop is "translate by exactly the width of the first half and wrap".
 * The second is aria-hidden so a screen reader gets the list once.
 */
export function ScrollMarquee({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const track = trackRef.current;
    if (!track) return;

    let raf = 0;
    let offset = 0;
    let halfWidth = 0;
    let lastScroll = window.scrollY;

    const onResize = () => {
      halfWidth = 0;
    };

    const frame = () => {
      raf = requestAnimationFrame(frame);
      if (!halfWidth) {
        const first = track.children[0] as HTMLElement | undefined;
        halfWidth = first ? first.getBoundingClientRect().width : 0;
        if (!halfWidth) return;
      }
      // Skip the work entirely when the ticker is nowhere near the viewport —
      // it is one strip on a long page and it was previously advancing every
      // frame for the whole scroll.
      const rect = track.getBoundingClientRect();
      if (rect.bottom < -80 || rect.top > window.innerHeight + 80) {
        lastScroll = window.scrollY;
        return;
      }
      const y = window.scrollY;
      const delta = y - lastScroll;
      lastScroll = y;
      offset += 0.6 + delta * 0.7;
      offset = ((offset % halfWidth) + halfWidth) % halfWidth;
      track.style.transform = `translate3d(${(-offset).toFixed(1)}px,0,0)`;
    };

    window.addEventListener("resize", onResize);
    raf = requestAnimationFrame(frame);
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(raf);
    };
  }, [reduced]);

  return (
    <div className={`overflow-hidden ${className}`}>
      <div ref={trackRef} className="flex w-max">
        <div className="flex shrink-0 items-center">{children}</div>
        <div className="flex shrink-0 items-center" aria-hidden="true">
          {children}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */

/**
 * A figure that counts up once, when it scrolls into view.
 *
 * Every number this is used for is a COUNTABLE FACT about the product — how
 * many modules there are, how many tools one login replaces — never a
 * performance statistic or a customer count, which §16 of the brief forbids
 * and which this product has no data for. The count-up is a flourish on a
 * number that would be true written plainly.
 *
 * Under reduced motion it renders the final value immediately: a number
 * spinning is precisely the kind of motion that setting exists to stop.
 */
export function CountUp({
  to,
  suffix = "",
  durationMs = 1200,
  className = "",
}: {
  to: number;
  suffix?: string;
  durationMs?: number;
  className?: string;
}) {
  const { ref, inView } = useInView<HTMLSpanElement>();
  const reduced = usePrefersReducedMotion();
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setValue(to);
      return;
    }
    let raf = 0;
    let start = 0;
    const step = (ts: number) => {
      if (!start) start = ts;
      const p = Math.min(1, (ts - start) / durationMs);
      setValue(Math.round(to * p));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [inView, reduced, to, durationMs]);

  return (
    <span ref={ref} className={className}>
      {value}
      {suffix}
    </span>
  );
}

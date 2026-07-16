"use client";

import { Children, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { usePrefersReducedMotion } from "./motion";
import { useScrollJackContentRef } from "./ScrollJack";

/**
 * Scroll-position-driven motion primitives for the cinematic home page
 * rebuild — distinct from motion.tsx's Reveal/CountUp family, which are
 * one-shot (IntersectionObserver, plays once and stays). Everything here is
 * continuously, bidirectionally driven by `getBoundingClientRect()` every
 * animation frame for the component's whole mounted lifetime: scroll back
 * up past a kinetic headline and it re-clips, matching the reference this
 * was built from exactly. That rect read is what makes these correct
 * whether ScrollJack.tsx is actively transforming an ancestor or sitting
 * inactive under native scroll (reduced-motion/mobile) — no special-casing
 * needed either way, same principle used throughout this app already.
 *
 * All reduced-motion here renders the fully-settled end state immediately
 * and skips the rAF loop entirely.
 *
 * Each effect below double-checks `matchMedia` directly (in addition to the
 * `reduced` prop from `usePrefersReducedMotion`) before starting its loop.
 * That hook's own correction from its default `false` to the real value
 * happens through a `useEffect` + `setState`, one render behind these
 * components' own effects — so on first mount, an effect here can still
 * capture a stale `reduced=false` in its closure and start its rAF loop
 * *before* the correcting re-render lands. Once started, a self-scheduling
 * rAF loop keeps mutating the DOM directly every frame regardless of later
 * prop changes, until its own cleanup runs — which can leave content
 * pinned at its dimmed/blurred starting style for a visible stretch (this
 * reproduced at up to several seconds under this sandbox's slower CPU,
 * though a real browser would typically settle far faster). Reading
 * matchMedia fresh, synchronously, inside the effect isn't subject to that
 * render-order race at all, so it closes the gap regardless of how long
 * the hook's own correction takes.
 */
const prefersReducedMotionNow = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Headline whose words individually sweep in left-to-right via clip-path
 * as their parent line crosses the vertical band [88vh, 50vh], with a small
 * per-word stagger. */
export function KineticLine({
  text,
  className = "",
  italic = false,
}: {
  text: string;
  className?: string;
  italic?: boolean;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = usePrefersReducedMotion();
  const words = text.split(" ");

  useEffect(() => {
    if (reduced || prefersReducedMotionNow()) return;
    const el = ref.current;
    if (!el) return;
    const kids = Array.from(el.children) as HTMLElement[];
    let raf = 0;

    const update = () => {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight;
      const kStart = vh * 0.88;
      const kEnd = vh * 0.5;
      let raw = (kStart - rect.top) / (kStart - kEnd);
      raw = Math.min(1, Math.max(0, raw));
      kids.forEach((word, i) => {
        const delay = i * 0.1;
        let p = (raw - delay) / Math.max(0.001, 1 - delay);
        p = Math.min(1, Math.max(0, p));
        word.style.clipPath = `inset(0 ${((1 - p) * 100).toFixed(1)}% 0 0)`;
        word.style.opacity = (0.2 + p * 0.8).toFixed(2);
      });
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, [reduced]);

  return (
    <span
      ref={ref}
      className={className}
      style={{ display: "block", ...(italic ? { fontStyle: "italic" } : undefined) }}
    >
      {words.map((w, i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            clipPath: reduced ? undefined : "inset(0 100% 0 0)",
          }}
        >
          {w}
          {i < words.length - 1 ? " " : ""}
        </span>
      ))}
    </span>
  );
}

/** Paragraph/text that starts dim + blurred + slightly scaled down, and
 * sharpens to full opacity/no-blur/1.0 scale as it crosses [90vh, 45vh]. */
export function FocusReveal({
  children,
  className = "",
  targetOpacity = 1,
}: {
  children: ReactNode;
  className?: string;
  targetOpacity?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced || prefersReducedMotionNow()) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const fStart = window.innerHeight * 0.9;
    const fEnd = window.innerHeight * 0.45;

    const update = () => {
      const rect = el.getBoundingClientRect();
      let p = (fStart - rect.top) / (fStart - fEnd);
      p = Math.min(1, Math.max(0, p));
      el.style.opacity = (targetOpacity * (0.15 + p * 0.85)).toFixed(2);
      el.style.filter = `blur(${((1 - p) * 10).toFixed(1)}px)`;
      el.style.transform = `scale(${(0.94 + p * 0.06).toFixed(3)})`;
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, [reduced, targetOpacity]);

  const style: CSSProperties = reduced
    ? { opacity: targetOpacity }
    : { opacity: 0.15 * targetOpacity, filter: "blur(10px)", transform: "scale(0.94)" };

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  );
}

/** Drifts an element vertically at `factor` × its distance from viewport
 * center — the same technique motion.tsx's Parallax uses, reimplemented
 * here as a plain always-on rAF loop (no scroll-event gating) to match the
 * rest of this file and stay correct under ScrollJack's transform. */
export function ParallaxLabel({
  children,
  factor,
  className = "",
}: {
  children: ReactNode;
  factor: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced || prefersReducedMotionNow()) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const update = () => {
      const rect = el.getBoundingClientRect();
      const center = rect.top + rect.height / 2 - window.innerHeight / 2;
      el.style.transform = `translate3d(0, ${(-center * factor).toFixed(2)}px, 0)`;
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => {
      cancelAnimationFrame(raf);
      el.style.transform = "";
    };
  }, [reduced, factor]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

/** Fades/slides a whole section up once, the first time it's scrolled into
 * view (unlike the other primitives here, this one-shot — matches the
 * reference's `attachReveal`, used for the stats band and final CTA). Calls
 * `onFirstReveal` exactly once, for triggering the stats count-up. */
export function SectionReveal({
  children,
  className = "",
  onFirstReveal,
}: {
  children: ReactNode;
  className?: string;
  onFirstReveal?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced || prefersReducedMotionNow()) {
      onFirstReveal?.();
      return;
    }
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          el.style.opacity = "1";
          el.style.transform = "none";
          onFirstReveal?.();
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -15% 0px", threshold: 0 }
    );
    io.observe(el);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced]);

  const style: CSSProperties = reduced
    ? {}
    : { opacity: 0, transform: "translateY(28px)", transition: "opacity 0.9s ease, transform 0.9s ease" };

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  );
}

/** Cross-fading word cycle for a headline's variable slot — e.g. "…for
 * compliance / accounting / payroll…". Reduced-motion visitors see the first
 * word only, statically (no interval ever starts). Screen readers get the
 * full word list as one static sr-only string instead of the animated,
 * constantly-changing spans (which are all `aria-hidden`). */
export function RotatingWord({
  words,
  className = "",
  interval = 2200,
  decorative = false,
}: {
  words: string[];
  className?: string;
  interval?: number;
  /** When true the whole element is aria-hidden with no sr-only fallback —
   * for the giant hero flourish, where the real heading text lives in a
   * sibling <h1> and reading the cycling word list too would be redundant
   * and confusing. Default false keeps the sr-only word list for inline
   * uses where the rotating word carries the meaning. */
  decorative?: boolean;
}) {
  const [i, setI] = useState(0);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced || words.length < 2) return;
    const id = setInterval(() => setI((v) => (v + 1) % words.length), interval);
    return () => clearInterval(id);
  }, [reduced, words.length, interval]);

  return (
    <span
      className={`relative inline-grid align-bottom ${className}`}
      aria-hidden={decorative ? "true" : undefined}
    >
      {!decorative && <span className="sr-only">{words.join(" / ")}</span>}
      {words.map((w, idx) => (
        <span
          key={w}
          aria-hidden="true"
          className="col-start-1 row-start-1 transition-all duration-500 ease-out"
          style={{
            opacity: idx === i ? 1 : 0,
            transform: idx === i ? "translateY(0)" : "translateY(-0.4em)",
          }}
        >
          {w}
        </span>
      ))}
    </span>
  );
}

/** Infinite horizontal ticker whose speed is a constant crawl PLUS a
 * multiple of the page's own scroll velocity (scrolling faster speeds it
 * up; scrolling up reverses its direction) — distinct from motion.tsx's
 * Marquee, which runs at a fixed CSS-animation speed. Content is duplicated
 * once and the offset wrapped modulo the first copy's measured width for a
 * seamless loop. Reduced-motion still shows the content, just static (no
 * scroll-reactive crawl, matching every other primitive in this file). */
export function ReactiveMarquee({ children, className = "" }: { children: ReactNode; className?: string }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();
  const contentRef = useScrollJackContentRef();
  const items = Children.toArray(children);

  useEffect(() => {
    if (reduced || prefersReducedMotionNow()) return;
    const track = trackRef.current;
    if (!track) return;
    const first = track.children[0] as HTMLElement | undefined;
    if (!first) return;

    let raf = 0;
    let offset = 0;
    let halfWidth = 0;
    let lastScroll: number | null = null;

    const currentScrollSignal = () =>
      contentRef?.current ? -contentRef.current.getBoundingClientRect().top : window.scrollY;

    const update = () => {
      if (!halfWidth) {
        halfWidth = first.getBoundingClientRect().width;
        if (!halfWidth) {
          raf = requestAnimationFrame(update);
          return;
        }
      }
      const scroll = currentScrollSignal();
      if (lastScroll === null) lastScroll = scroll;
      const delta = scroll - lastScroll;
      lastScroll = scroll;
      offset += 0.6 + delta * 0.7;
      offset = ((offset % halfWidth) + halfWidth) % halfWidth;
      track.style.transform = `translate3d(${(-offset).toFixed(1)}px, 0, 0)`;
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, [reduced, contentRef]);

  return (
    <div className={`overflow-hidden ${className}`} style={{ maskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)" }}>
      <div ref={trackRef} className="flex w-max">
        <div className="flex items-center whitespace-nowrap">{items}</div>
        <div className="flex items-center whitespace-nowrap" aria-hidden="true">{items}</div>
      </div>
    </div>
  );
}

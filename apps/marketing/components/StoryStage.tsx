"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePrefersReducedMotion } from "./motion";

/**
 * Home-page story mechanism: a scroll-pinned "convergence" — the scattered,
 * disconnected-tools chapter dissolving into the unified-platform hero — plus
 * a persistent rail that tracks which chapter is active. This file owns only
 * the scroll math, the pin/stack layout switch, and the rail; the actual
 * chapter content is authored by the caller (app/(site)/page.tsx) and passed
 * in as children/props, so this stays a mechanism, not a content template.
 *
 * Below the lg breakpoint, or under prefers-reduced-motion, the pin/morph
 * mechanism never activates — both chapters render as plain stacked sections
 * instead. `pinnedActive` starts false and is only flipped true inside a
 * client effect, so the server-rendered / no-JS view always gets the simple
 * stacked layout first — the richer pinned staging is a progressive upgrade,
 * never a requirement to see the content.
 */

const RAIL_LABELS = ["Scattered", "Synced", "Trusted"];

export function ChapterRail({
  active,
  visible,
}: {
  active: number;
  visible: boolean;
}) {
  return (
    <nav
      aria-label="Story progress"
      className={`fixed left-8 top-1/2 z-30 hidden -translate-y-1/2 flex-col gap-4 transition-opacity duration-700 lg:flex ${
        visible ? "opacity-100" : "pointer-events-none opacity-0"
      }`}
    >
      {RAIL_LABELS.map((label, i) => (
        <div key={label} className="flex items-center gap-3">
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-500 ${
              i === active ? "bg-brand-light" : "bg-white/25"
            }`}
          />
          <span
            className={`text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors duration-500 ${
              i === active ? "text-white" : "text-white/35"
            }`}
          >
            {label}
          </span>
        </div>
      ))}
    </nav>
  );
}

/** Sets `index` active (repeatedly, both scroll directions) whenever the
 * wrapped section crosses the vertical center band of the viewport — the
 * standard "scrollspy" technique, distinct from Reveal's one-shot useInView.
 * Takes the setState function + a plain index (both stable across renders)
 * rather than an inline callback, so the observer is attached once. */
export function useSectionActive<T extends HTMLElement>(
  setActive: (index: number) => void,
  index: number
) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setActive(index);
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [setActive, index]);
  return ref;
}

export function ProblemSolutionStory({
  scatter,
  children,
  onActiveChange,
}: {
  /** Chapter 1 ("Scattered") content. */
  scatter: ReactNode;
  /** Chapter 2 ("Synced") content — the settled hero. */
  children: ReactNode;
  onActiveChange: (index: 0 | 1) => void;
}) {
  const reduced = usePrefersReducedMotion();
  const [pinnedActive, setPinnedActive] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const scatterRef = useRef<HTMLDivElement>(null);
  const settledRef = useRef<HTMLDivElement>(null);
  const lastIndex = useRef<0 | 1>(0);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setPinnedActive(mq.matches && !reduced);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [reduced]);

  useEffect(() => {
    if (!pinnedActive) return;
    const wrap = wrapRef.current;
    if (!wrap) return;
    let raf = 0;

    const update = () => {
      raf = 0;
      const rect = wrap.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      const progress = total > 0 ? Math.min(1, Math.max(0, -rect.top / total)) : 0;

      const scatterOpacity = Math.max(0, 1 - progress / 0.55);
      const scatterScale = 1 - progress * 0.45;
      const settledOpacity = Math.min(1, Math.max(0, (progress - 0.4) / 0.45));
      const settledScale = 0.94 + settledOpacity * 0.06;

      const s = scatterRef.current;
      if (s) {
        s.style.opacity = String(scatterOpacity);
        s.style.transform = `scale(${scatterScale.toFixed(3)})`;
        s.style.visibility = scatterOpacity > 0.02 ? "visible" : "hidden";
      }
      const d = settledRef.current;
      if (d) {
        d.style.opacity = String(settledOpacity);
        d.style.transform = `scale(${settledScale.toFixed(3)})`;
        d.style.visibility = settledOpacity > 0.02 ? "visible" : "hidden";
      }

      const idx: 0 | 1 = progress < 0.5 ? 0 : 1;
      if (idx !== lastIndex.current) {
        lastIndex.current = idx;
        onActiveChange(idx);
      }
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [pinnedActive, onActiveChange]);

  if (!pinnedActive) {
    // Stacked fallback — mobile/tablet and prefers-reduced-motion. No pin, no
    // scroll math: both chapters render as plain sequential sections.
    return (
      <>
        <div className="relative overflow-hidden bg-brand-dark">{scatter}</div>
        {children}
      </>
    );
  }

  return (
    <div ref={wrapRef} className="relative h-[220vh]">
      <div className="sticky top-0 h-screen overflow-hidden">
        <div ref={scatterRef} className="absolute inset-0">
          {scatter}
        </div>
        <div ref={settledRef} className="absolute inset-0" style={{ opacity: 0 }}>
          {children}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Home-page story mechanism: a scroll-pinned "convergence" — the scattered,
 * disconnected-tools chapter dissolving into the unified-platform hero — plus
 * a persistent rail that tracks which chapter is active. This file owns only
 * the scroll math, the pin/stack layout switch, and the rail; the actual
 * chapter content is authored by the caller (app/(site)/page.tsx) and passed
 * in as children/props, so this stays a mechanism, not a content template.
 *
 * Below the lg breakpoint, or under prefers-reduced-motion, the pin/morph
 * mechanism never activates and the crossfade is inert — `scatter`/`children`
 * always render inside the SAME wrapper element tree either way (only the
 * wrapper's className/style differs), so toggling `pinnedActive` never
 * unmounts and remounts the chapter content. That matters for two reasons:
 * it's what a breakpoint-crossing resize or a mid-session reduced-motion
 * toggle needs to not restart the settled hero's entrance animations or lose
 * scroll position, and it's also what happens on every completely normal
 * desktop page load, since `pinnedActive` starts false (matching the
 * server-rendered / no-JS HTML) and only flips true after mount.
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
        <div
          key={label}
          className="flex items-center gap-3"
          aria-current={i === active ? "step" : undefined}
        >
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

/** Chapter 1 ("Scattered") crossfades into chapter 2 ("Synced") as the user
 * scrolls through a pinned stage on desktop with motion enabled. */
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
  const [pinnedActive, setPinnedActive] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const scatterLayerRef = useRef<HTMLDivElement>(null);
  const settledLayerRef = useRef<HTMLDivElement>(null);
  const lastIndex = useRef<0 | 1>(0);

  // Self-contained: reads both media queries directly rather than depending
  // on the separately-timed usePrefersReducedMotion hook. Two hooks each
  // starting from a stale default and correcting via their own effect can
  // race across the same passive-effect flush — an early version of this
  // depended on that hook and briefly computed pinnedActive=true even for a
  // reduced-motion visitor, on every desktop-width mount, before a follow-up
  // render corrected it. Reading both matchMedia results in one place at one
  // time removes that race entirely.
  useEffect(() => {
    const widthMq = window.matchMedia("(min-width: 1024px)");
    const motionMq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPinnedActive(widthMq.matches && !motionMq.matches);
    update();
    widthMq.addEventListener("change", update);
    motionMq.addEventListener("change", update);
    return () => {
      widthMq.removeEventListener("change", update);
      motionMq.removeEventListener("change", update);
    };
  }, []);

  // The crossfade itself. Deliberately does NOT touch `visibility`: an
  // earlier version hid the settled layer (the page's real <h1> and primary
  // CTAs) via visibility:hidden for the entire first ~40% of the pinned
  // range, which removes it from the tab order and the accessibility tree —
  // not just faded, actually unreachable — for any keyboard or
  // screen-reader user who hasn't happened to mouse-wheel/touch-scroll
  // first. `pointer-events` alone still prevents accidental clicks on a
  // barely-visible layer without making its real content unreachable.
  useEffect(() => {
    if (!pinnedActive) {
      // Clear any inline styles left over from a previous pinned session
      // (e.g. a breakpoint-crossing resize mid-scroll) so the stacked
      // fallback isn't stuck with a stale opacity/transform/pointer-events.
      const s = scatterLayerRef.current;
      const d = settledLayerRef.current;
      if (s) { s.style.opacity = ""; s.style.transform = ""; s.style.pointerEvents = ""; }
      if (d) { d.style.opacity = ""; d.style.transform = ""; d.style.pointerEvents = ""; }
      return;
    }
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

      const s = scatterLayerRef.current;
      if (s) {
        s.style.opacity = String(scatterOpacity);
        s.style.transform = `scale(${scatterScale.toFixed(3)})`;
        s.style.pointerEvents = scatterOpacity < 0.05 ? "none" : "auto";
      }
      const d = settledLayerRef.current;
      if (d) {
        d.style.opacity = String(settledOpacity);
        d.style.transform = `scale(${settledScale.toFixed(3)})`;
        d.style.pointerEvents = settledOpacity < 0.5 ? "none" : "auto";
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinnedActive]);

  // Rail tracking for the stacked fallback (narrow viewport or reduced
  // motion): the pinned effect above drives chapters 0/1 from scroll
  // *progress* through the crossfade, which only makes sense while both
  // layers are stacked at the same on-screen position. In the stacked
  // fallback they're in normal sequential flow instead, so plain scrollspy
  // (which chapter is centered in the viewport) is the correct signal there
  // — the same technique chapter 3 ("Trusted") already uses independently.
  // Only one of the two mechanisms is ever live at a time, gated by the same
  // pinnedActive flag, so they can't fight each other.
  useEffect(() => {
    if (pinnedActive) return;
    const scatterEl = scatterLayerRef.current;
    const settledEl = settledLayerRef.current;
    if (!scatterEl || !settledEl || typeof IntersectionObserver === "undefined") return;
    const make = (index: 0 | 1) =>
      new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) onActiveChange(index);
        },
        { rootMargin: "-45% 0px -45% 0px", threshold: 0 }
      );
    const scatterIo = make(0);
    const settledIo = make(1);
    scatterIo.observe(scatterEl);
    settledIo.observe(settledEl);
    return () => {
      scatterIo.disconnect();
      settledIo.disconnect();
    };
  }, [pinnedActive, onActiveChange]);

  // One stable tree in both modes — only the wrapper's className/style
  // differs — so scatter/children (and everything mounted inside them, e.g.
  // the settled hero's WordReveal/fade-up entrance) are never torn down and
  // rebuilt when pinnedActive flips. A Fragment-vs-div swap here previously
  // meant React fully unmounted and remounted this subtree on every flip —
  // including the flip that happens on every normal desktop page load
  // (pinnedActive starts false, then turns true right after mount) — which
  // replayed the settled hero's entrance animations a second time in front
  // of anyone who'd already seen them play once during that first commit.
  return (
    <div
      ref={wrapRef}
      className={pinnedActive ? "relative h-[220vh]" : "relative"}
    >
      <div className={pinnedActive ? "sticky top-0 h-screen overflow-hidden" : ""}>
        <div
          ref={scatterLayerRef}
          className={pinnedActive ? "absolute inset-0" : "relative"}
        >
          {scatter}
        </div>
        <div
          ref={settledLayerRef}
          className={pinnedActive ? "absolute inset-0" : "relative"}
          style={pinnedActive ? { opacity: 0 } : undefined}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

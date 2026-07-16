"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

/**
 * General-purpose scroll-pin primitive, factored out of the lessons learned
 * building StoryStage.tsx's chapter 1→2 convergence: desktop + motion-enabled
 * only (an `lg`-breakpoint + prefers-reduced-motion gate, computed in one
 * self-contained effect rather than depending on a separately-timed hook,
 * which avoids a stale-closure race at mount); never hides content via
 * `visibility` (stays in the accessibility tree/tab order — only opacity/
 * transform/pointer-events move).
 *
 * Deliberately does NOT compensate window.scrollY across a pin/stack swap
 * the way StoryStage.tsx does for its own single instance: a page can carry
 * several independent usePinnedStage sections at once (this component ships
 * two, alongside StoryStage's own mechanism), and each one's compensating
 * `window.scrollTo` call would race the others on the same breakpoint/
 * motion-preference change — confirmed by hand, the same test scenario
 * landed at two different scrollY values across runs depending purely on
 * effect-ordering. StoryStage keeps its own compensation because its two
 * layers show genuinely different visual content at the same scroll offset;
 * these sections don't have that problem — they resolve to progress = 1
 * (fully revealed) the instant the pin turns off, so a viewer who crosses
 * the breakpoint mid-build just sees the finished section land, not a jump
 * to unrelated content.
 *
 * Unlike StoryStage (which crossfades between two distinct layers), this
 * assumes ONE content tree whose pieces animate in via progress-driven inline
 * styles the caller computes — so the natural "settled" state (progress = 1)
 * is also exactly what stacked/reduced-motion visitors see immediately, with
 * no separate fallback markup to author.
 */
// `progress` is exposed as React state rather than driven via direct DOM
// mutation (the way StoryStage.tsx and Parallax do it): a build-sequence
// with a dozen independently-timed pieces is far simpler to author as plain
// JSX + inline styles than as hand-written imperative ref updates for every
// piece. The tradeoff is a re-render of the pinned subtree on every rAF tick
// while actively scrolling through it — acceptable for one modest section at
// a time (the single in-flight rAF already caps this at the repaint rate),
// but a reason NOT to reach for this hook for anything with heavy content.
export function usePinnedStage<T extends HTMLElement>(vh: number = 200) {
  const wrapRef = useRef<T | null>(null);
  const [pinnedActive, setPinnedActive] = useState(false);
  const [progress, setProgress] = useState(0);

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

  useEffect(() => {
    if (!pinnedActive) {
      // Stacked/reduced-motion fallback: no scroll-jacking, content renders
      // in its fully-settled state immediately.
      setProgress(1);
      return;
    }
    const wrap = wrapRef.current;
    if (!wrap) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const rect = wrap.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      setProgress(total > 0 ? Math.min(1, Math.max(0, -rect.top / total)) : 0);
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
  }, [pinnedActive]);

  return { wrapRef, pinnedActive, progress, vh };
}

/** Maps `progress` to a 0→1 ramp between `start` and `end`, clamped. */
export function stageIn(progress: number, start: number, end: number): number {
  if (end <= start) return progress >= end ? 1 : 0;
  return Math.min(1, Math.max(0, (progress - start) / (end - start)));
}

/** Standard "rise + fade in" inline style for a piece of a pinned build-up.
 * At t=1 this resolves to `{}` (no inline overrides at all), so a stacked/
 * reduced-motion render — which always calls this with progress=1 — never
 * carries a stray transform/opacity into a page that has no scroll-pin. */
export function riseIn(t: number, distance: number = 20): CSSProperties {
  if (t >= 1) return {};
  return {
    opacity: t,
    transform: `translateY(${(distance * (1 - t)).toFixed(1)}px)`,
  };
}

/** Same contract as `riseIn`, sliding in horizontally instead — positive
 * `distance` enters from the right, negative from the left. */
export function slideIn(t: number, distance: number = 40): CSSProperties {
  if (t >= 1) return {};
  return {
    opacity: t,
    transform: `translateX(${(distance * (1 - t)).toFixed(1)}px)`,
  };
}

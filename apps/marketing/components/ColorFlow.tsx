"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

export type FlowStop = {
  ref: RefObject<HTMLElement>;
  rgb: [number, number, number];
  /** Which edge of `ref`'s box marks this stop — defaults to "top". Use
   * "bottom" for a stop that means "still this section's color, right up
   * until it ends" (e.g. the tail end of a pinned stage, whose sticky inner
   * content can't be measured directly — sticky's rect.top stays pinned
   * mid-viewport while active, so the only useful anchor is the outer
   * wrapper's own top/bottom, which correctly reflects real document
   * position in both pinned and stacked layout modes). */
  edge?: "top" | "bottom";
  /** Nudges the measured edge by this many pixels (positive = further down
   * the page). Two back-to-back sections with no gap between them (e.g.
   * TrustedStage's bottom and StatsStage's top land at the exact same
   * document position) would otherwise interpolate over zero distance —
   * t snaps straight to 1, so the color still cuts abruptly right at that
   * one seam even though every other transition blends smoothly. Pulling
   * the "still old color" stop up and the "now new color" stop down by a
   * shared margin borrows a bit of each section's own top/bottom padding
   * as a real blend zone, with no visible gap introduced. */
  offsetPx?: number;
};

/**
 * Continuous background color as a function of scroll position, instead of
 * each section cutting to its own flat color at its boundary. `stops` marks
 * the top of each section with its target color; between two stops the
 * color linearly interpolates across that section's whole scroll range —
 * which means consecutive stops with the *same* color (e.g. three navy
 * sections in a row) naturally hold flat with zero visible drift, and only
 * the boundaries where color actually changes produce a visible blend.
 * Callers apply the returned value as `style={{ background: color ?? undefined }}`
 * alongside their existing Tailwind `bg-*` class, never removing it — the
 * class is what server-rendered/no-JS/reduced-motion/mobile visitors see
 * (this hook returns `null`, so the inline style is absent and the class
 * wins), and the inline style only overrides it once this is actually
 * live, same gating (desktop + motion-enabled) as the rest of this app's
 * scroll mechanisms.
 */
export function useFlowColor(stops: FlowStop[]): string | null {
  const [color, setColor] = useState<string | null>(null);
  const stopsRef = useRef(stops);
  stopsRef.current = stops;

  useEffect(() => {
    const widthMq = window.matchMedia("(min-width: 1024px)");
    const motionMq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;
    let active = false;

    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

    const update = () => {
      raf = 0;
      const positioned = stopsRef.current
        .map((s) => {
          if (!s.ref.current) return null;
          const rect = s.ref.current.getBoundingClientRect();
          const edgeY = s.edge === "bottom" ? rect.bottom : rect.top;
          return { y: edgeY + window.scrollY + (s.offsetPx ?? 0), rgb: s.rgb };
        })
        .filter((s): s is { y: number; rgb: [number, number, number] } => s !== null)
        .sort((a, b) => a.y - b.y);
      if (positioned.length < 2) return;

      const sample = window.scrollY + window.innerHeight * 0.4;
      let i = 0;
      while (i < positioned.length - 2 && sample > positioned[i + 1].y) i++;
      const a = positioned[i];
      const b = positioned[i + 1];
      const t = b.y > a.y ? Math.min(1, Math.max(0, (sample - a.y) / (b.y - a.y))) : 1;

      const r = Math.round(lerp(a.rgb[0], b.rgb[0], t));
      const g = Math.round(lerp(a.rgb[1], b.rgb[1], t));
      const bl = Math.round(lerp(a.rgb[2], b.rgb[2], t));
      setColor(`rgb(${r}, ${g}, ${bl})`);
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };

    const applyGate = () => {
      const enabled = widthMq.matches && !motionMq.matches;
      if (enabled === active) return;
      active = enabled;
      if (enabled) {
        update();
        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll);
      } else {
        window.removeEventListener("scroll", onScroll);
        window.removeEventListener("resize", onScroll);
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        setColor(null);
      }
    };

    applyGate();
    widthMq.addEventListener("change", applyGate);
    motionMq.addEventListener("change", applyGate);
    return () => {
      widthMq.removeEventListener("change", applyGate);
      motionMq.removeEventListener("change", applyGate);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return color;
}

"use client";

import { useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "./motion";

// Runtime-generated SVG turbulence — the grain texture. Set once as the
// overlay's background-image; only its opacity flickers each frame-ish.
const GRAIN_SVG =
  "<svg xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>";

/**
 * Full-viewport fixed film-grain overlay (mix-blend-mode: overlay), matching
 * the design reference: a static turbulence texture whose opacity is
 * re-randomized between 3.5% and 6.5% every 110ms for a living-grain shimmer.
 * Under prefers-reduced-motion the flicker is dropped and it holds a flat 5%
 * — the texture still reads, without the animation. Sits above the sticky
 * nav (z-50) but below the intro loader (z-100), matching the reference's
 * own z-index:9999 (well above its nav's z-index:50) — the grain texture
 * reads over the nav too, not just the page content below it. pointer-
 * events-none means this never blocks clicking through to the nav itself.
 */
export function FilmGrain() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent(GRAIN_SVG)}")`;
    if (reduced) {
      el.style.opacity = "0.05";
      return;
    }
    const id = setInterval(() => {
      el.style.opacity = (0.035 + Math.random() * 0.03).toFixed(3);
    }, 110);
    return () => clearInterval(id);
  }, [reduced]);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[60]"
      style={{ mixBlendMode: "overlay", opacity: 0.05 }}
    />
  );
}

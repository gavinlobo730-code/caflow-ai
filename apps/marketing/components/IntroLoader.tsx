"use client";

import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "./motion";

/**
 * Full-screen percentage-counter loader, ~1.5s, with a hard 3.2s fallback
 * in case something stalls. Calls `onExit` once, right as it starts fading
 * out, so the hero's own stagger-in can begin at the same moment the
 * reference triggers it from. Reduced-motion visitors skip the loader
 * entirely — straight to content, no percentage animation to sit through.
 */
export function IntroLoader({ onExit }: { onExit: () => void }) {
  const [pct, setPct] = useState(0);
  const [exiting, setExiting] = useState(false);
  const [hidden, setHidden] = useState(false);
  const reduced = usePrefersReducedMotion();
  const doneRef = useRef(false);

  useEffect(() => {
    if (reduced) {
      doneRef.current = true;
      onExit();
      setHidden(true);
      return;
    }
    const start = performance.now();
    const dur = 1500;
    let raf = 0;

    const finish = () => {
      if (doneRef.current) return;
      doneRef.current = true;
      setExiting(true);
      onExit();
      setTimeout(() => setHidden(true), 850);
    };

    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      setPct(Math.round(p * 100));
      if (p >= 1) {
        setTimeout(finish, 250);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const fallback = setTimeout(finish, 3200);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(fallback);
    };
  }, [reduced, onExit]);

  if (hidden) return null;

  return (
    <div
      aria-hidden="true"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-brand-dark transition duration-700 ease-out"
      style={exiting ? { opacity: 0, transform: "translateY(-100%)" } : undefined}
    >
      <div className="mb-[18px] font-display text-[15px] italic tracking-wide text-white/60">PracticeSync</div>
      <div className="font-display text-[clamp(56px,10vw,120px)] leading-none text-white">{pct}%</div>
      <div className="relative mt-[26px] h-px w-[180px] overflow-hidden bg-white/20">
        <div className="absolute inset-y-0 left-0 bg-white" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

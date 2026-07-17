"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePrefersReducedMotion } from "./motion";

/**
 * Cursor-driven polish for the marketing site: a custom trailing cursor, a
 * magnetic-pull wrapper for primary buttons, and a soft glow that follows the
 * pointer across dark sections. Everything here is gated on `(pointer: fine)`
 * — checked once via matchMedia, same idiom ScrollJack.tsx uses for its own
 * lg-breakpoint gate — so touch devices never attach a single listener or pay
 * for any of this; the desktop-only "delight" layer costs nothing on mobile,
 * which is most of this site's real traffic. Everything also no-ops under
 * prefers-reduced-motion.
 */

// Returns the ref object itself, NOT ref.current — Magnetic and useCursorGlow
// read .current live, inside their own event-handler bodies, at the moment
// the handler actually fires. That's the part that matters: returning
// ref.current here would hand back a snapshot taken *during this render*,
// which the caller's handler closure would then capture by value forever
// (updating a ref never triggers a re-render, so a component that mounts
// once and never re-renders — most of these — would be permanently stuck
// with whatever pointerFine was on its first render, i.e. always false,
// since the effect that flips it hasn't run yet at that point). Handing back
// the ref and reading .current fresh inside each handler call sidesteps that
// entirely. CustomCursor doesn't use this at all: it needs a render-time
// decision (render the dot/ring or don't), which a ref can never provide —
// see its own useState below instead.
function usePointerFine(reduced: boolean): React.RefObject<boolean> {
  const ref = useRef(false);
  useEffect(() => {
    ref.current = !reduced && window.matchMedia("(pointer: fine)").matches;
  }, [reduced]);
  return ref;
}

/** Two-part trailing cursor: a tight dot plus a lagging ring that grows over
 * interactive elements. Uses mix-blend-mode so one element reads correctly
 * against both the dark hero sections and the white content pages, instead
 * of needing to track which background is underneath. */
export function CustomCursor() {
  const reduced = usePrefersReducedMotion();
  // Unlike usePointerFine above, this gates whether the dot/ring render at
  // all — a render-time decision — so it needs useState: without it, a touch
  // device would still mount the divs (just never positioned, since the
  // effect below bails before attaching listeners), leaving them stuck at
  // their default CSS offset in the top-left corner of the screen.
  const [active, setActive] = useState(false);
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const target = useRef({ x: -100, y: -100 });
  const ring = useRef({ x: -100, y: -100 });

  useEffect(() => {
    setActive(!reduced && window.matchMedia("(pointer: fine)").matches);
  }, [reduced]);

  useEffect(() => {
    if (!active) return;

    document.documentElement.classList.add("cursor-none");

    let raf = 0;
    let hovering = false;

    const onMove = (e: MouseEvent) => {
      target.current.x = e.clientX;
      target.current.y = e.clientY;
      if (dotRef.current) {
        dotRef.current.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
      }
    };

    const onOver = (e: MouseEvent) => {
      const el = (e.target as HTMLElement)?.closest?.(
        'a, button, [role="button"], input, [data-cursor-hover]'
      );
      hovering = !!el;
      ringRef.current?.classList.toggle("cursor-ring-hover", hovering);
    };

    // Spring the ring toward the raw cursor position — the lag is what
    // reads as "alive" rather than a second cursor rigidly glued to the first.
    const tick = () => {
      ring.current.x += (target.current.x - ring.current.x) * 0.18;
      ring.current.y += (target.current.y - ring.current.y) * 0.18;
      if (ringRef.current) {
        ringRef.current.style.transform = `translate3d(${ring.current.x}px, ${ring.current.y}px, 0)`;
      }
      raf = requestAnimationFrame(tick);
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    document.addEventListener("mouseover", onOver, { passive: true });
    raf = requestAnimationFrame(tick);

    return () => {
      document.documentElement.classList.remove("cursor-none");
      window.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseover", onOver);
      cancelAnimationFrame(raf);
    };
  }, [active]);

  if (!active) return null;

  return (
    <>
      <div ref={dotRef} className="cursor-dot" aria-hidden="true" />
      <div ref={ringRef} className="cursor-ring" aria-hidden="true" />
    </>
  );
}

/** Wraps a button/link so it pulls gently toward a nearby cursor and springs
 * back on leave — same rAF + direct-style-mutation technique as motion.tsx's
 * Tilt, applied to translation instead of 3D rotation. */
export function Magnetic({
  children,
  strength = 0.35,
  max = 14,
  className = "",
}: {
  children: ReactNode;
  strength?: number;
  max?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();
  const frame = useRef(0);
  const pointerFine = usePointerFine(reduced);

  // One constant transition throughout — tracking and spring-back alike —
  // per the design reference's magnetic-button formula, rather than a
  // different duration/easing for move vs. leave.
  const MAGNETIC_TRANSITION = "transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)";

  function onMove(e: React.MouseEvent) {
    if (reduced || !pointerFine.current) return;
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const dx = e.clientX - (rect.left + rect.width / 2);
    const dy = e.clientY - (rect.top + rect.height / 2);
    const tx = Math.max(-max, Math.min(max, dx * strength));
    const ty = Math.max(-max, Math.min(max, dy * strength));
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      el.style.transition = MAGNETIC_TRANSITION;
      el.style.transform = `translate3d(${tx.toFixed(1)}px, ${ty.toFixed(1)}px, 0)`;
    });
  }

  function onLeave() {
    const el = ref.current;
    if (!el) return;
    cancelAnimationFrame(frame.current);
    el.style.transition = MAGNETIC_TRANSITION;
    el.style.transform = "translate3d(0, 0, 0)";
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={`inline-flex ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * Soft light that follows the pointer within a dark section. Deliberately a
 * hook, not a wrapper element: an absolutely-positioned div can't both listen
 * for mousemove AND stay pointer-events-none (the two are mutually
 * exclusive — an element with pointer-events:none never receives its own
 * mouse events either, since hit-testing skips it entirely). So instead the
 * *section itself* — which already needs normal pointer-events for its real
 * buttons/links — gets the move/leave handlers via spread, and only the
 * decorative glow div is pointer-events-none. Usage:
 *
 *   const glow = useCursorGlow();
 *   <section className="relative ..." {...glow.handlers}>
 *     <div ref={glow.ref} className="cursor-glow" aria-hidden="true" />
 *     ...real content...
 *   </section>
 */
export function useCursorGlow() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();
  const pointerFine = usePointerFine(reduced);

  function onMouseMove(e: React.MouseEvent<HTMLElement>) {
    if (reduced || !pointerFine.current) return;
    const el = ref.current;
    if (!el) return;
    const rect = e.currentTarget.getBoundingClientRect();
    el.style.opacity = "1";
    el.style.transform = `translate3d(${e.clientX - rect.left - 220}px, ${e.clientY - rect.top - 220}px, 0)`;
  }

  function onMouseLeave() {
    if (ref.current) ref.current.style.opacity = "0";
  }

  return { ref, handlers: { onMouseMove, onMouseLeave } };
}

"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type MutableRefObject,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * True scroll-jacking. Two pieces, split because the context needs to reach
 * further up the tree than the transform does:
 *
 * - `ScrollJackProvider` — mounted once in app/(site)/layout.tsx, wrapping
 *   the shared chrome (SiteHeader, main, footer). Owns the shared refs and
 *   provides context; applies no transform of its own.
 * - `ScrollJack` — mounted only by the home page, inside that provider.
 *   Attaches to the shared `contentRef` and runs the actual engine: wheel/
 *   touch/keyboard capture, accumulated into a target offset, eased toward
 *   (`current += (target-current)*0.09`) via a transform applied every
 *   animation frame. Native scroll is disabled outright (`overflow: hidden`
 *   on html/body) while active.
 *
 * Splitting them is what lets chrome OUTSIDE the page's own content — e.g.
 * SiteHeader's scroll-condense effect — read the same "how far scrolled"
 * signal as content inside it: `contentRef.current` stays null on every page
 * that never mounts `<ScrollJack>` below (i.e. every page but home), which is
 * exactly what makes a `contentRef?.current ?? window.scrollY`-style
 * fallback in a consumer resolve correctly without that consumer needing to
 * know which page it's rendering on.
 *
 * This is a different technique from the site-wide SmoothScroll attempt that
 * shipped and was reverted earlier: that one kept real native scroll as the
 * source of truth and faked the *visual* position with a transform, which
 * conflicted with `position: sticky` (used by this app's now-retired
 * chaptered-story pin mechanism). This design has no sticky anywhere — every
 * reveal effect here (KineticLine, FocusReveal, ParallaxLabel, the 3D scene)
 * reads its own element's `getBoundingClientRect()` each frame, which is
 * correct in BOTH modes below without any special-casing: it reflects the
 * transformed position while active, and the natively-scrolled position
 * while inactive, automatically.
 *
 * Inactive (native scroll) is the default, and is what SSR/no-JS,
 * `prefers-reduced-motion`, and non-desktop/coarse-pointer visitors get —
 * matching this codebase's established gating convention elsewhere
 * (Cursor.tsx). Scroll-jacking has real, documented accessibility costs
 * (breaks the scrollbar and native find-in-page); reduced-motion and mobile
 * visitors should never pay for it.
 */

const FALLBACK_SCROLL_TO = (id: string) => {
  document.getElementById(id.replace(/^#/, ""))?.scrollIntoView({ behavior: "smooth", block: "start" });
};

type ScrollJackCtx = {
  /** Stable identity across renders — safe to depend on in a hook's deps array. */
  scrollToId: (id: string) => void;
  /** Mutated by the ScrollJack engine on start/stop; scrollToId delegates here. */
  scrollToIdRef: MutableRefObject<(id: string) => void>;
  contentRef: RefObject<HTMLDivElement>;
};

const ScrollJackContext = createContext<ScrollJackCtx | null>(null);

/** Falls back to a plain smooth scrollIntoView when used outside a
 * ScrollJackProvider, or when ScrollJack itself is currently inactive
 * (reduced-motion/mobile) — same behavior either way from the caller's
 * perspective. */
export function useScrollToSection(): (id: string) => void {
  const ctx = useContext(ScrollJackContext);
  return ctx ? ctx.scrollToId : FALLBACK_SCROLL_TO;
}

/** For effects that need a continuously-updating "how far has the page
 * scrolled" signal that works identically whether ScrollJack is actively
 * transforming content or sitting inactive under native scroll (currently
 * SiteHeader's scroll-condense effect, and ReactiveMarquee's scroll-velocity-
 * driven speed). Reads the content wrapper's own `getBoundingClientRect().top`,
 * which moves correctly in both regimes for the same reason every other
 * reveal effect here does — transforms and native scroll both show up in it.
 * Returns null outside a ScrollJackProvider (there is no shared ref to hand
 * back); returns a ref whose `.current` is null on every page that doesn't
 * mount `<ScrollJack>` — callers should treat both the same way. */
export function useScrollJackContentRef(): RefObject<HTMLDivElement> | null {
  const ctx = useContext(ScrollJackContext);
  return ctx ? ctx.contentRef : null;
}

/** Mounted once, high in the tree (app/(site)/layout.tsx), so the context
 * reaches chrome that sits outside the page's own content. No DOM wrapper
 * and no transform — just the shared refs. */
export function ScrollJackProvider({ children }: { children: ReactNode }) {
  const contentRef = useRef<HTMLDivElement>(null);
  const scrollToIdRef = useRef<(id: string) => void>(FALLBACK_SCROLL_TO);
  // Stable identity across renders — created once, mutated via the ref
  // above, so context consumers never see it "change".
  const scrollToId = useRef((id: string) => scrollToIdRef.current(id)).current;

  return (
    <ScrollJackContext.Provider value={{ scrollToId, scrollToIdRef, contentRef }}>
      {children}
    </ScrollJackContext.Provider>
  );
}

const NAV_CLEARANCE = 90;

/** The actual scroll-jacking engine, scoped to wherever this wraps (the home
 * page only). Must render inside a `ScrollJackProvider` — falls back to
 * rendering children inert (no engine, no transform) if used without one,
 * rather than throwing, matching this app's general silent-degrade posture
 * (e.g. ThreeScene's WebGL-unavailable fallback). */
export function ScrollJack({ children }: { children: ReactNode }) {
  const ctx = useContext(ScrollJackContext);

  useEffect(() => {
    if (!ctx) return;
    const content = ctx.contentRef.current;
    if (!content) return;

    const motionMq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const widthMq = window.matchMedia("(min-width: 1024px)");
    const pointerMq = window.matchMedia("(pointer: fine)");

    let active = false;
    let raf = 0;
    let hashRaf = 0;
    let scrollTarget = 0;
    let scrollCurrent = 0;
    let maxScroll = 0;
    let touchY = 0;

    const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
    const computeMaxScroll = () => {
      maxScroll = Math.max(0, content.scrollHeight - window.innerHeight);
    };

    const tick = () => {
      computeMaxScroll();
      scrollCurrent += (scrollTarget - scrollCurrent) * 0.09;
      if (Math.abs(scrollTarget - scrollCurrent) < 0.05) scrollCurrent = scrollTarget;
      content.style.transform = `translate3d(0, ${(-scrollCurrent).toFixed(2)}px, 0)`;
      raf = requestAnimationFrame(tick);
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      computeMaxScroll();
      scrollTarget = clamp(scrollTarget + e.deltaY, 0, maxScroll);
    };
    const onTouchStart = (e: TouchEvent) => {
      touchY = e.touches[0].clientY;
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      const y = e.touches[0].clientY;
      const dy = touchY - y;
      touchY = y;
      computeMaxScroll();
      scrollTarget = clamp(scrollTarget + dy * 1.6, 0, maxScroll);
    };
    const isTypingTarget = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName.toLowerCase();
      return tag === "input" || tag === "textarea" || el.isContentEditable;
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget()) return;
      computeMaxScroll();
      const vh = window.innerHeight;
      if (e.key === "ArrowDown") { e.preventDefault(); scrollTarget = clamp(scrollTarget + 90, 0, maxScroll); }
      else if (e.key === "ArrowUp") { e.preventDefault(); scrollTarget = clamp(scrollTarget - 90, 0, maxScroll); }
      else if (e.key === "PageDown" || e.key === " ") { e.preventDefault(); scrollTarget = clamp(scrollTarget + vh * 0.85, 0, maxScroll); }
      else if (e.key === "PageUp") { e.preventDefault(); scrollTarget = clamp(scrollTarget - vh * 0.85, 0, maxScroll); }
      else if (e.key === "Home") { e.preventDefault(); scrollTarget = 0; }
      else if (e.key === "End") { e.preventDefault(); scrollTarget = maxScroll; }
    };
    const onResize = () => computeMaxScroll();

    const scrollToIdImpl = (id: string) => {
      const target = document.getElementById(id.replace(/^#/, ""));
      if (!target) return;
      computeMaxScroll();
      const rect = target.getBoundingClientRect();
      const dest = scrollCurrent + rect.top - NAV_CLEARANCE;
      scrollTarget = clamp(dest, 0, maxScroll);
    };

    const start = () => {
      if (active) return;
      active = true;
      // A URL that loads with a #hash gets natively scrolled to that anchor
      // by the browser before this effect ever runs — setting
      // overflow:hidden below freezes that offset in place rather than
      // clearing it, and our transform-based model otherwise assumes native
      // scroll is always exactly 0. Reset it explicitly so that's actually
      // true; the hash-jump immediately below re-derives the correct
      // position through our own transform instead.
      window.scrollTo(0, 0);
      document.documentElement.style.overflow = "hidden";
      document.body.style.overflow = "hidden";
      computeMaxScroll();
      scrollTarget = 0;
      scrollCurrent = 0;
      content.style.transform = "translate3d(0, 0, 0)";
      window.addEventListener("wheel", onWheel, { passive: false });
      window.addEventListener("touchstart", onTouchStart, { passive: true });
      window.addEventListener("touchmove", onTouchMove, { passive: false });
      window.addEventListener("keydown", onKeyDown);
      window.addEventListener("resize", onResize);
      raf = requestAnimationFrame(tick);
      ctx.scrollToIdRef.current = scrollToIdImpl;
      if (window.location.hash) {
        // Layout keeps growing for a while after this effect first runs —
        // web font swap-in (next/font's `display: "swap"` paints a fallback
        // first), the 3D hero sizing its canvas off its parent on its own
        // mount effect, hydration settling — so a fixed frame count either
        // measures too early (a section below the target hasn't reached its
        // final height yet, so `content.scrollHeight` under-reports and the
        // jump falls short) or wastes time waiting past when it was already
        // safe to measure. Poll until scrollHeight stops changing across two
        // consecutive frames instead, capped so a pathological case (nothing
        // here should continuously resize) can't spin forever. Tracked and
        // cancelled in stop() so a start/stop/start cycle (React Strict
        // Mode's dev double-invoke, or a real remount) can't leave a stale
        // callback to fire later against a fresh scroll position and jump to
        // the wrong place.
        let lastHeight = -1;
        let stableFrames = 0;
        let framesElapsed = 0;
        const MAX_FRAMES = 90;
        const settle = () => {
          const h = content.scrollHeight;
          if (h === lastHeight) stableFrames++;
          else stableFrames = 0;
          lastHeight = h;
          framesElapsed++;
          if (stableFrames < 3 && framesElapsed < MAX_FRAMES) {
            hashRaf = requestAnimationFrame(settle);
            return;
          }
          scrollToIdImpl(window.location.hash);
        };
        hashRaf = requestAnimationFrame(settle);
      }
    };

    const stop = () => {
      if (!active) return;
      active = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (hashRaf) cancelAnimationFrame(hashRaf);
      hashRaf = 0;
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
      content.style.transform = "";
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
      ctx.scrollToIdRef.current = FALLBACK_SCROLL_TO;
    };

    const update = () => {
      const enabled = widthMq.matches && pointerMq.matches && !motionMq.matches;
      if (enabled) start();
      else stop();
    };

    update();
    motionMq.addEventListener("change", update);
    widthMq.addEventListener("change", update);
    pointerMq.addEventListener("change", update);
    return () => {
      motionMq.removeEventListener("change", update);
      widthMq.removeEventListener("change", update);
      pointerMq.removeEventListener("change", update);
      stop();
    };
  }, [ctx]);

  if (!ctx) return <>{children}</>;

  return (
    <div ref={ctx.contentRef} style={{ position: "relative", willChange: "transform" }}>
      {children}
    </div>
  );
}

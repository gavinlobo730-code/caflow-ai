"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

// Motion primitives for the marketing site. Everything here degrades to plain
// static markup when the browser reports prefers-reduced-motion, and all
// entrance work is CSS-driven (see globals.css `.rv*` classes) — these
// components only decide WHEN to flip the switch, so the JS cost stays tiny
// and the static export never blocks on hydration to show content.

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Fires once when the element scrolls into view. */
function useInView<T extends HTMLElement>(margin = "0px 0px -12% 0px") {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: margin, threshold: 0.12 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [margin]);
  return { ref, inView };
}

type RevealVariant = "up" | "blur" | "scale" | "left" | "right";

/**
 * Scroll-triggered entrance. Children render immediately (SEO/no-JS safe);
 * the CSS transition plays when the element enters the viewport.
 */
export function Reveal({
  children,
  variant = "up",
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  variant?: RevealVariant;
  delay?: number;
  className?: string;
}) {
  const { ref, inView } = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      data-in={inView ? "true" : "false"}
      className={`rv rv-${variant} ${className}`}
      style={delay ? ({ transitionDelay: `${delay}ms` } as CSSProperties) : undefined}
    >
      {children}
    </div>
  );
}

/** Eases a number from 0 to `to` when scrolled into view. */
export function CountUp({
  to,
  duration = 1600,
  prefix = "",
  suffix = "",
  className = "",
}: {
  to: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
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
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutExpo — fast start, long soft landing
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      setValue(Math.round(to * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, to, duration, reduced]);

  return (
    <span ref={ref} className={`tabular-nums ${className}`}>
      {prefix}
      {value.toLocaleString("en-IN")}
      {suffix}
    </span>
  );
}

/** Pointer-tracking 3D tilt with a soft spring back on leave. */
export function Tilt({
  children,
  max = 7,
  className = "",
}: {
  children: ReactNode;
  max?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const reduced = usePrefersReducedMotion();
  const frame = useRef(0);

  function onMove(e: React.MouseEvent) {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      el.style.transition = "transform 120ms ease-out";
      el.style.transform = `perspective(1100px) rotateX(${(-py * max).toFixed(2)}deg) rotateY(${(px * max).toFixed(2)}deg) scale(1.012)`;
    });
  }

  function onLeave() {
    const el = ref.current;
    if (!el) return;
    cancelAnimationFrame(frame.current);
    el.style.transition = "transform 700ms cubic-bezier(0.16, 1, 0.3, 1)";
    el.style.transform = "perspective(1100px) rotateX(0deg) rotateY(0deg) scale(1)";
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={className}
      style={{ transformStyle: "preserve-3d" }}
    >
      {children}
    </div>
  );
}

/**
 * Card that keeps a fixed base transform (e.g. `rotate(-6deg)` or a centering
 * `translate(-50%,-50%) rotate(-2deg)`) and layers a cursor-driven 3D tilt
 * (±14° rotateX/rotateY from the pointer's position within the card) on top,
 * snapping back to the base on mouse-leave — the hero mockup-card effect from
 * the design reference's `attachCard`. Distinct from `Tilt`, which has no base
 * transform and applies its own perspective/scale. The parent must set
 * `perspective` for the 3D rotation to read. Inert (base transform only, no
 * listeners' effect) under reduced motion.
 */
export function TiltCard({
  base,
  className = "",
  style,
  children,
}: {
  base: string;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  function onMove(e: React.MouseEvent) {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.transition = "transform 0.05s linear";
    el.style.transform = `${base} rotateX(${(-py * 14).toFixed(2)}deg) rotateY(${(px * 14).toFixed(2)}deg)`;
  }

  function onLeave() {
    const el = ref.current;
    if (!el) return;
    el.style.transition = "transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)";
    el.style.transform = base;
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={className}
      style={{ transform: base, willChange: "transform", ...style }}
    >
      {children}
    </div>
  );
}

/** Gentle scroll parallax — shifts the element against scroll direction. */
export function Parallax({
  children,
  speed = 0.06,
  className = "",
}: {
  children: ReactNode;
  speed?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const update = () => {
      const rect = el.getBoundingClientRect();
      const mid = rect.top + rect.height / 2 - window.innerHeight / 2;
      el.style.transform = `translate3d(0, ${(-mid * speed).toFixed(1)}px, 0)`;
      raf = 0;
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
      cancelAnimationFrame(raf);
      // usePrefersReducedMotion starts at false and corrects itself one
      // effect-flush later, so on a reduced-motion visitor's first mount this
      // effect can still run once with a stale reduced=false before the
      // follow-up render disables it — applying one real transform in the
      // process. Resetting it here (rather than relying on the *next* run's
      // `if (reduced) return;`, which never reaches this element at all)
      // means that stray offset doesn't survive as a permanent, never-reset
      // static offset on the wrapped element for reduced-motion desktop
      // users, who should see this component be fully inert.
      el.style.transform = "";
    };
  }, [speed, reduced]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

/**
 * Headline that materialises word by word (blur → sharp, rising). Pure CSS
 * animation with per-word delays, so it plays on page load without JS timing.
 */
export function WordReveal({
  text,
  className = "",
  startDelay = 0,
  stagger = 70,
  accent = [],
}: {
  text: string;
  className?: string;
  /** ms before the first word starts */
  startDelay?: number;
  /** ms between words */
  stagger?: number;
  /** words (lowercased, punctuation stripped) to paint with the aurora gradient */
  accent?: string[];
}) {
  const words = text.split(" ");
  return (
    <span className={className} aria-label={text}>
      {words.map((word, i) => {
        const clean = word.toLowerCase().replace(/[^a-z0-9]/g, "");
        const isAccent = accent.includes(clean);
        return (
          <span key={`${word}-${i}`} className="inline-block overflow-visible" aria-hidden="true">
            <span
              className={`word-in inline-block ${isAccent ? "text-aurora" : ""}`}
              style={{ animationDelay: `${startDelay + i * stagger}ms` }}
            >
              {word}
            </span>
            {i < words.length - 1 ? " " : ""}
          </span>
        );
      })}
    </span>
  );
}

/** Infinite horizontal ticker. Content is duplicated for a seamless loop. */
export function Marquee({
  children,
  duration = 36,
  className = "",
}: {
  children: ReactNode;
  duration?: number;
  className?: string;
}) {
  return (
    <div className={`marquee ${className}`}>
      <div className="marquee-track" style={{ animationDuration: `${duration}s` }}>
        <div className="marquee-group">{children}</div>
        <div className="marquee-group" aria-hidden="true">
          {children}
        </div>
      </div>
    </div>
  );
}

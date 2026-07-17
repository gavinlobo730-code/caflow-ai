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
export function useInView<T extends HTMLElement>(margin = "0px 0px -12% 0px") {
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
 * Headline that materialises word by word (rising into place), staggered.
 * Fires once when it scrolls into view — same trigger-once mechanism as
 * `Reveal` above — so a headline below the fold stays hidden until the
 * reader actually reaches it instead of finishing its entrance unseen.
 */
export function WordReveal({
  text,
  className = "",
  startDelay = 0,
  stagger = 70,
  accent = [],
  inView: inViewProp,
}: {
  text: string;
  className?: string;
  /** ms before the first word starts */
  startDelay?: number;
  /** ms between words */
  stagger?: number;
  /** words (lowercased, punctuation stripped) to paint with the aurora gradient */
  accent?: string[];
  /**
   * Drive visibility from a parent's own scroll-trigger instead of observing
   * independently — pass this when already nested inside another element
   * that manages its own `inView` (e.g. SerifHeading), so the two don't end
   * up as separate concurrent opacity transitions on nested elements.
   */
  inView?: boolean;
}) {
  const { ref, inView: selfInView } = useInView<HTMLSpanElement>();
  const inView = inViewProp ?? selfInView;
  const words = text.split(" ");
  return (
    <span ref={ref} className={className} aria-label={text}>
      {words.map((word, i) => {
        const clean = word.toLowerCase().replace(/[^a-z0-9]/g, "");
        const isAccent = accent.includes(clean);
        return (
          <span key={`${word}-${i}`} className="inline-block overflow-visible" aria-hidden="true">
            <span
              data-in={inView ? "true" : "false"}
              className={`word-in inline-block ${isAccent ? "text-aurora" : ""}`}
              style={{ transitionDelay: `${startDelay + i * stagger}ms` }}
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

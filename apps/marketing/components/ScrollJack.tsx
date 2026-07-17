"use client";

import {
  createContext,
  useContext,
  useRef,
  type MutableRefObject,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * Shared scroll context for the marketing site's chrome (SiteHeader's
 * scroll-condense effect, anchor-link handling). This used to also host a
 * true scroll-jacking engine (`ScrollJack`) mounted by the home page — wheel/
 * touch/keyboard capture replacing native scroll entirely, for a cinematic
 * homepage rebuild that was later retired in favor of serving the design
 * reference verbatim (see app/page.tsx). No page mounts that engine anymore,
 * so `contentRef.current` is now always null and `scrollToId` always
 * delegates to the plain `scrollIntoView` fallback below — kept as a context
 * rather than inlined into SiteHeader because it's still the one shared
 * place a future page-level scroll effect would plug into.
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
 * ScrollJackProvider — currently always, since no page mounts the
 * (now-removed) scroll-jacking engine that used to populate this. */
export function useScrollToSection(): (id: string) => void {
  const ctx = useContext(ScrollJackContext);
  return ctx ? ctx.scrollToId : FALLBACK_SCROLL_TO;
}

/** For effects that need a continuously-updating "how far has the page
 * scrolled" signal (currently just SiteHeader's scroll-condense effect).
 * Returns null outside a ScrollJackProvider; returns a ref whose `.current`
 * is always null today, since no page populates it — callers should treat
 * both the same way (i.e. fall back to `window.scrollY`). */
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

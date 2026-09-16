/**
 * Lazy loader for the vendored Three.js build.
 *
 * Three.js is 603 KB of the 16 MB the homepage is allowed, and it is needed by
 * exactly one component on exactly one route. The static HTML homepage this
 * replaced pulled it in with a `<script defer>` in <head>, so every visitor
 * paid for it before the hero had painted — including the ones who would never
 * see the globe at all (reduced motion, a low-memory phone, a browser with no
 * WebGL). Loading it from inside the component's own effect means the decision
 * NOT to run the globe is also a decision not to download it.
 *
 * `next/script` is deliberately not used: its strategies are about when to
 * inject relative to hydration, and what this needs is a promise that resolves
 * when `window.THREE` exists, so the caller can await it and fall back if it
 * never does. A single module-level promise makes it load once however many
 * times the effect re-runs under React 18 StrictMode.
 *
 * The file is served from /vendor rather than a CDN on purpose — the rest of
 * the site self-hosts its fonts from the same directory, and a third-party
 * script tag is a third party that can see every visitor.
 */


let pending: Promise<any> | null = null;

export function loadThree(): Promise<any> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("three is browser-only"));
  }
  const existing = (window as any).THREE;
  if (existing) return Promise.resolve(existing);
  if (pending) return pending;

  pending = new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = "/vendor/three.min.js";
    el.async = true;
    el.onload = () => {
      const THREE = (window as any).THREE;
      if (THREE) resolve(THREE);
      else reject(new Error("three loaded but did not define window.THREE"));
    };
    el.onerror = () => {
      // Let a later mount try again rather than caching the failure for the
      // life of the page — a dropped request on a flaky connection is not a
      // permanent verdict on whether the globe can run.
      pending = null;
      reject(new Error("three failed to load"));
    };
    document.head.appendChild(el);
  });

  return pending;
}

/**
 * Should this visitor get the WebGL globe at all?
 *
 * Four independent reasons to say no, and the answer is the same in each case:
 * the static SVG globe, which is always rendered underneath and simply never
 * gets covered. Deliberately conservative — a wrong "yes" on a weak device is
 * the failure the hero cannot afford, because the hero is the first screenful
 * and therefore exactly where scrolling starts.
 */
export function canRunGlobe(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    // A phone shows the simplified globe below the headline (brief §14), and
    // the connector/card composition is hidden there anyway.
    if (window.matchMedia("(max-width: 900px)").matches) return false;
    // navigator.deviceMemory is Chromium-only and absent elsewhere; absent
    // means "unknown", which is not the same as "low" and must not block.
    const mem = (navigator as any).deviceMemory;
    if (typeof mem === "number" && mem > 0 && mem <= 4) return false;
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl");
    return Boolean(gl);
  } catch {
    return false;
  }
}

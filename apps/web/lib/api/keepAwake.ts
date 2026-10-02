/**
 * Warm the API up, and keep it warm while somebody is looking at the product (frontend_ux-05).
 *
 * THE DEFECT. The API runs on a free-tier instance that goes to sleep when nothing has called it for fifteen
 * minutes (`.github/workflows/wake-before-scheduler.yml` records the window, and a cold start measured at 56.55 s
 * on 2026-09-06), and the next call then waits that long. The only mitigation
 * was ONE `/health` ping when `AuthContext` mounted, so a CA who signed in, worked for twenty minutes on the
 * data already on screen and then opened another screen met the cold start in the middle of the day's work.
 *
 * WHAT THIS DOES.
 *   * `warmUp()` is the old ping, unchanged in meaning: one request, as early as possible, so a sleeping
 *     instance starts waking while the person is still typing a password. It runs whether or not anybody is
 *     signed in.
 *   * `start()` then repeats it about every ten minutes — well inside the idle window — but ONLY while the tab
 *     is visible and ONLY once started, and `AuthContext` starts it when somebody is signed in and stops it
 *     when they sign out or the provider unmounts. A hidden tab pings nothing (a background tab nobody is
 *     looking at has no reason to keep a server awake), and coming back to a tab that has been hidden for
 *     longer than the interval pings at once, because that is exactly the moment the next click would meet a
 *     cold server.
 *   * ONE REQUEST A WINDOW ACROSS TABS, where the browser allows it: the time of the last ping is kept in
 *     `localStorage` and a tab that sees a recent one skips its own. It is a per-viewer convenience — a
 *     missing, blocked or throwing store is ignored and the tab simply pings on its own timer — never a
 *     requirement, and nothing else is stored.
 *
 * WHAT IT NEVER DOES. It calls the one URL it was given and nothing else (`${apiBase}/health`), sends no
 * credentials and no identifier of any kind (`credentials: "omit"`, no headers, no body), reads nothing from
 * the answer, and fails silently: a failed ping is not a toast, not a `console.error` and not a retry. It
 * does not touch `window` or `document` until `start()` or `warmUp()` is called, which the caller does inside
 * an effect, so a static-export prerender never reaches either.
 *
 * Everything the browser provides is passed in, so a test can drive it with a fake clock, visibility and
 * store; `browserKeepAwake()` is the one place the real ones are read.
 */

/** About every ten minutes: well inside a free-tier idle window, and a handful of requests an hour. */
export const KEEP_AWAKE_INTERVAL_MS = 10 * 60 * 1000;

/** A tab whose last ping (its own or another tab's) is younger than this share of the interval skips its own,
 *  so jitter between tabs' timers does not turn one request per window into two. */
export const FRESH_SHARE = 0.9;

/** The only thing kept in the browser: when the API was last pinged, as epoch milliseconds. */
export const LAST_PING_KEY = "practicesync.keep-awake.last-ping";

export function healthUrl(apiBase: string | undefined | null): string | null {
  const base = (apiBase ?? "").trim().replace(/\/+$/, "");
  return base ? `${base}/health` : null;
}

export interface KeepAwakeDeps {
  /** The API's base URL (`NEXT_PUBLIC_API_URL`). Empty means there is nothing to ping. */
  apiBase: string | undefined | null;
  fetch: (url: string, init: RequestInit) => Promise<unknown>;
  now: () => number;
  /** Is the tab on screen? */
  isVisible: () => boolean;
  /** Be told when the tab is shown or hidden; returns the way to stop being told. */
  onVisibilityChange: (listener: () => void) => () => void;
  setInterval: (fn: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
  /** The last-ping store, or null where the browser gives none. Every call is guarded. */
  store: { get(): number | null; set(at: number): void } | null;
  intervalMs?: number;
}

export interface KeepAwake {
  /** One ping now, whatever the tab is doing. The old mount-time warm-up. */
  warmUp(): void;
  /** Begin pinging about every interval while the tab is visible. Starting twice does nothing. */
  start(): void;
  /** Stop the timer and the visibility listener. Safe to call when not started. */
  stop(): void;
  isRunning(): boolean;
}

export function createKeepAwake(deps: KeepAwakeDeps): KeepAwake {
  const interval = deps.intervalMs ?? KEEP_AWAKE_INTERVAL_MS;
  const url = healthUrl(deps.apiBase);
  let timer: unknown = null;
  let unlisten: (() => void) | null = null;
  let started = false;
  /** This tab's own memory of its last ping, for a browser with no usable store. */
  let lastOwn: number | null = null;

  function readLast(): number | null {
    let shared: number | null = null;
    try { shared = deps.store ? deps.store.get() : null; } catch { shared = null; }
    const times = [shared, lastOwn].filter((t): t is number => typeof t === "number" && Number.isFinite(t));
    return times.length ? Math.max(...times) : null;
  }

  function ping(): void {
    if (!url) return;
    const at = deps.now();
    lastOwn = at;
    try { deps.store?.set(at); } catch { /* a store that will not write is not a failure */ }
    try {
      // No credentials, no headers, no body: this is a knock on the door, and it must never carry who knocked.
      const sent = deps.fetch(url, { method: "GET", mode: "cors", credentials: "omit", cache: "no-store" });
      Promise.resolve(sent).catch(() => {});
    } catch { /* a ping that cannot even be sent is nobody's business */ }
  }

  function dueNow(): boolean {
    const last = readLast();
    return last === null || deps.now() - last >= interval * FRESH_SHARE;
  }

  function tick(): void {
    if (!deps.isVisible()) return;
    if (dueNow()) ping();
  }

  function arm(): void {
    if (timer !== null) return;
    timer = deps.setInterval(tick, interval);
  }

  function disarm(): void {
    if (timer === null) return;
    deps.clearInterval(timer);
    timer = null;
  }

  function onVisibility(): void {
    if (!started) return;
    if (deps.isVisible()) {
      // Back on screen: if it has been quiet for a window, wake the server before the next click needs it.
      if (dueNow()) ping();
      arm();
    } else {
      disarm();
    }
  }

  return {
    warmUp: ping,
    start() {
      if (started) return;
      started = true;
      unlisten = deps.onVisibilityChange(onVisibility);
      if (deps.isVisible()) arm();
    },
    stop() {
      started = false;
      disarm();
      if (unlisten) { unlisten(); unlisten = null; }
    },
    isRunning: () => started,
  };
}

/** The real browser's clock, visibility, timers and store. Read inside an effect, never during render. */
export function browserKeepAwake(apiBase: string | undefined | null): KeepAwake {
  return createKeepAwake({
    apiBase,
    fetch: (url, init) => fetch(url, init),
    now: () => Date.now(),
    isVisible: () => typeof document !== "undefined" && document.visibilityState === "visible",
    onVisibilityChange: (listener) => {
      document.addEventListener("visibilitychange", listener);
      return () => document.removeEventListener("visibilitychange", listener);
    },
    setInterval: (fn, ms) => window.setInterval(fn, ms),
    clearInterval: (handle) => window.clearInterval(handle as number),
    store: {
      get() {
        const raw = window.localStorage.getItem(LAST_PING_KEY);
        const n = raw === null ? NaN : Number(raw);
        return Number.isFinite(n) ? n : null;
      },
      set(at) { window.localStorage.setItem(LAST_PING_KEY, String(at)); },
    },
  });
}

/**
 * What a person is told while a screen waits on a server that may be asleep (frontend_ux-05).
 *
 * THE DEFECT. The API runs on a free-tier instance that sleeps when idle, and a cold start takes thirty to
 * sixty seconds (56.55 s was measured on 2026-09-06; `.github/workflows/wake-before-scheduler.yml` records it
 * and the 15-minute keep-alive window). The 29-09-2026 walk-through recorded skeletons of five to fifteen
 * seconds on nearly every non-trivial screen and some past thirty. The only words a CA ever got were AFTER a
 * failure ("it may be waking up"), so for the whole of a long wait a grey block gave no reason, no estimate and
 * no way out, and "nothing is happening" and "something is happening slowly" looked the same.
 *
 * THE RULES (each one has a test, `slowServer.test.ts`).
 *   * Quiet for the first three seconds. A warm server answers in well under that, and a sentence that flashes
 *     for half a second on every ordinary load teaches a reader to ignore it.
 *   * After three seconds one sentence, and the sentence does not change or repeat. After twenty seconds a
 *     region that has a way to read again OFFERS it. Nothing retries by itself, ever: `lib/api` does not retry
 *     a timeout on purpose (a second copy of the slowest query lands on an instance that is already struggling),
 *     and a notice that quietly re-sent a request would put that back.
 *   * It exists only while the region is pending. It is derived from the region being mounted in its loading
 *     state, so it cannot outlive the wait and cannot appear over data or over an error.
 *   * ONE NOTICE AT A TIME. A screen with a page loader, a table skeleton and a card grid all pending would say
 *     the same sentence three times, and a screen reader would read it three times. Each pending region keeps
 *     its OWN clock (a region that started a second ago has not been waiting twenty), and of the regions that
 *     have something to say, the one furthest along speaks, then the one that can offer a retry, then the
 *     oldest. The others stay quiet until it leaves.
 *   * A retry restarts that region's clock. Without it the button would stay on screen and each click would
 *     stack another request on the one still running.
 *
 * NO REACT, NO DOM, NO NETWORK. `useSlowServerNotice` adapts it and `components/ui/slow-server-notice.tsx`
 * renders it; this file is plain TypeScript so a test can drive it with a fake clock.
 */

/** Quiet until a wait is longer than a warm server ever takes. */
export const WAKING_NOTICE_AFTER_MS = 3_000;

/** A read still pending after this long has outlived most cold starts, so it may be offered again. */
export const RETRY_OFFERED_AFTER_MS = 20_000;

/** The sentence, word for word as the audit worded it. It is a claim about the common cause, not a diagnosis
 *  of this request, which is why it says "can take" and stops there. */
export const WAKING_SENTENCE =
  "The server is waking up. The first screen of the day can take up to a minute.";

export type SlowPhase = "quiet" | "waking" | "stalled";

const RANK: Record<SlowPhase, number> = { quiet: 0, waking: 1, stalled: 2 };

/** Which phase a wait of this length is in. A negative or non-finite wait is quiet. */
export function phaseAfter(elapsedMs: number): SlowPhase {
  if (!Number.isFinite(elapsedMs) || elapsedMs < WAKING_NOTICE_AFTER_MS) return "quiet";
  return elapsedMs < RETRY_OFFERED_AFTER_MS ? "waking" : "stalled";
}

/** The timer pair the watch uses, so a test can supply a clock it steps by hand. */
export interface Timers {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface WatchOptions {
  /** True when the region can read again on request. Decides who speaks when two regions are equally far along,
   *  because a notice with a Retry on it is worth more than one without. */
  canRetry?: boolean;
}

export interface Pending {
  stop(): void;
}

export interface SlowWatch {
  /** Start timing one pending region. `onChange` is called with what THIS region should show, now and each
   *  time it changes, and is never called after `stop`. */
  start(onChange: (phase: SlowPhase) => void, options?: WatchOptions): Pending;
  /** How many regions are being timed. For tests. */
  pendingCount(): number;
}

interface Entry {
  seq: number;
  canRetry: boolean;
  /** How long this region has been waiting, as a phase. */
  own: SlowPhase;
  /** What it was last told to show. */
  shown: SlowPhase;
  onChange: (phase: SlowPhase) => void;
  timers: unknown[];
}

export function createSlowWatch(timers: Timers = realTimers): SlowWatch {
  const entries = new Map<number, Entry>();
  let nextSeq = 1;

  /** Of the regions with something to say, the one that says it. */
  function speaker(): Entry | null {
    let best: Entry | null = null;
    // Array.from, not `for...of` over the map: the app compiles to a target with no iterator protocol.
    for (const e of Array.from(entries.values())) {
      if (e.own === "quiet") continue;
      if (!best) { best = e; continue; }
      if (RANK[e.own] !== RANK[best.own]) { if (RANK[e.own] > RANK[best.own]) best = e; continue; }
      if (e.canRetry !== best.canRetry) { if (e.canRetry) best = e; continue; }
      if (e.seq < best.seq) best = e;
    }
    return best;
  }

  function settle(): void {
    const talking = speaker();
    for (const e of Array.from(entries.values())) {
      const next: SlowPhase = e === talking ? e.own : "quiet";
      if (next === e.shown) continue;
      e.shown = next;
      e.onChange(next);
    }
  }

  return {
    start(onChange, options = {}) {
      const entry: Entry = {
        seq: nextSeq++, canRetry: Boolean(options.canRetry), own: "quiet", shown: "quiet", onChange, timers: [],
      };
      entries.set(entry.seq, entry);
      entry.timers.push(timers.set(() => { entry.own = "waking"; settle(); }, WAKING_NOTICE_AFTER_MS));
      entry.timers.push(timers.set(() => { entry.own = "stalled"; settle(); }, RETRY_OFFERED_AFTER_MS));
      return {
        stop() {
          if (!entries.delete(entry.seq)) return;
          for (const t of entry.timers) timers.clear(t);
          entry.timers = [];
          // A region that leaves silences itself without a call: its owner has already gone.
          settle();
        },
      };
    },
    pendingCount: () => entries.size,
  };
}

/** The one watch the whole page shares, which is what makes "one notice at a time" true across components. */
export const pageWatch: SlowWatch = createSlowWatch();

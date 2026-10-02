"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { WAKING_SENTENCE } from "@/lib/async/slowServer";
import { useSlowServerNotice } from "@/lib/async/useSlowServerNotice";

/**
 * The sentence a person reads while a grey block waits on a server that may be asleep (frontend_ux-05).
 * The rules and the reasons are in `lib/async/slowServer.ts`; this renders them.
 *
 * WHERE IT LIVES. Inside every loading primitive — `AsyncBoundary`, `PageLoader` and each skeleton in
 * `skeleton.tsx` that is a loading region — rather than beside them on each screen, so a screen that shows
 * a skeleton gets the notice without anyone remembering to ask for it.
 * `scripts/a-loading-region-says-when-the-server-is-slow.test.ts` fails a primitive that renders a loading
 * region without one.
 *
 * MOUNTED MEANS PENDING. Every one of those primitives is mounted only while its region loads, so this
 * component's lifetime IS the wait: it appears at three seconds, it is gone with the skeleton, and it can
 * never sit over data or over an error. Pass `pending` only where a screen keeps the region mounted and
 * has its own flag.
 *
 * THE LIVE REGION IS ALWAYS PRESENT AND EMPTY UNTIL IT HAS SOMETHING TO SAY. A screen reader announces a
 * change inside a region that was already on the page; a region inserted with its text already in it is
 * announced by some readers and not others. So the `role="status"` element mounts with the skeleton, takes
 * no space while empty (`!mt-0 h-0`, which also cancels a parent's `space-y`), and the sentence is written
 * into it once. It is never rewritten, so it is read once.
 *
 * RETRY IS OFFERED ONLY WHERE THE REGION CAN READ AGAIN, and a region says so by handing in `onRetry`.
 * Without one there is no button at all — a skeleton has nothing to call, and a button that does nothing is
 * worse than none. The prop belongs to READS: this component is rendered only inside a loading placeholder,
 * which is what a read shows, and never inside a button or a form that is saving, so a Retry here can
 * never send a write twice. Pressing it also restarts this notice's clock, so it does not sit on screen
 * inviting a second press while the request it started is still running. It never retries by itself.
 *
 * NESTED PLACEHOLDERS SAY IT ONCE. `AsyncBoundary` wraps the skeleton it was given in `SlowServerScope`, and
 * a notice inside that scope renders nothing and starts no clock: the boundary's own notice, which knows the
 * retry, is the one that speaks. Several unrelated regions on one screen are told apart by the shared watch
 * instead (one speaks at a time).
 */

const ScopeContext = React.createContext(false);

/** Marks everything inside as covered by a notice rendered by an ancestor. */
export function SlowServerScope({ children }: { children: React.ReactNode }) {
  return <ScopeContext.Provider value={true}>{children}</ScopeContext.Provider>;
}

export function SlowServerNotice({
  onRetry,
  pending = true,
  className,
}: {
  /** Read this region again. Omit it where there is nothing to call, and no button is drawn. */
  onRetry?: () => void;
  /** True while the region is waiting. Defaults to true because the component is mounted only while it is. */
  pending?: boolean;
  className?: string;
}) {
  const covered = React.useContext(ScopeContext);
  const { phase, restart } = useSlowServerNotice(pending && !covered, { canRetry: Boolean(onRetry) });
  if (covered) return null;
  const speaking = phase !== "quiet";
  return (
    <div
      role="status"
      aria-live="polite"
      data-slow-server-notice={phase}
      className={cn(
        speaking
          ? "flex flex-wrap items-center gap-x-3 gap-y-2 py-3 text-xs text-ps-hint"
          : "!mt-0 h-0 overflow-hidden",
        className,
      )}
    >
      {speaking && <p>{WAKING_SENTENCE}</p>}
      {phase === "stalled" && onRetry && (
        <button
          type="button"
          onClick={() => { restart(); onRetry(); }}
          className="inline-flex items-center rounded-lg border border-brand-light bg-white px-3 py-1.5 font-medium text-brand transition-colors hover:bg-ps-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          Retry
        </button>
      )}
    </div>
  );
}

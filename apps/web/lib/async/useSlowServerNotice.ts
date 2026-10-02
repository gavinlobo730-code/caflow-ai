"use client";

/**
 * React adapter for the slow-server watch (frontend_ux-05). Read `slowServer.ts` first for the rules.
 *
 *   const { phase, restart } = useSlowServerNotice(loading, { canRetry: Boolean(reload) });
 *
 * `phase` is `quiet` until the region has been pending three seconds, `waking` until twenty and `stalled` after,
 * and it is `quiet` again the moment `pending` goes false. That last part is read from `pending` in the render
 * itself, not from state an effect resets afterwards, because an effect runs after the paint: for one frame
 * over the data the sentence would still be there.
 *
 * `restart()` starts the region's clock again. A Retry button calls it, so the button goes away and the next
 * offer comes twenty seconds after the new request, not after the first one.
 *
 * Timers start in an effect, so a static-export prerender (no effects) and a server render both answer quiet,
 * and nothing here reads `window` while rendering.
 */
import { useCallback, useEffect, useState } from "react";
import { pageWatch, type SlowPhase } from "@/lib/async/slowServer";

export function useSlowServerNotice(
  pending: boolean,
  options: { canRetry?: boolean } = {},
): { phase: SlowPhase; restart: () => void } {
  const [phase, setPhase] = useState<SlowPhase>("quiet");
  const [round, setRound] = useState(0);
  const canRetry = Boolean(options.canRetry);

  useEffect(() => {
    if (!pending) return undefined;
    const watching = pageWatch.start(setPhase, { canRetry });
    return () => {
      watching.stop();
      setPhase("quiet");
    };
  }, [pending, canRetry, round]);

  const restart = useCallback(() => setRound((n) => n + 1), []);
  return { phase: pending ? phase : "quiet", restart };
}

"use client";

import { useEffect, useState } from "react";
import { STUCK_AFTER_MS, STUCK_SENTENCE } from "@/lib/async/stuckLoading";

/**
 * What a page that waits on the BROWSER says when it has waited too long (POST-A-491): the client workspace's entry page
 * and the not-found page's redirect branch, which drew a spinner and "Loading workspace…" for as long as the page stayed
 * open and offered no way out. After `after` milliseconds it says so and offers Reload (a full page load, which is what
 * cleared it for the person who reported it).
 *
 * It is NOT the shared slow-server notice (`SlowServerNotice`): that one speaks of a server that may be waking up and
 * offers a re-read, and these two screens read nothing. Mounted means waiting, as that notice is: it is drawn inside the
 * loading branch and is gone with it, so it can never sit over a screen that has loaded.
 */
export function StuckLoadingNotice({ after = STUCK_AFTER_MS }: { after?: number }) {
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setStuck(true), after);
    return () => window.clearTimeout(t);
  }, [after]);
  return (
    <div
      role="status"
      aria-live="polite"
      data-stuck-loading={stuck ? "stuck" : "quiet"}
      className={stuck ? "mt-1 flex flex-col items-center gap-2 text-center" : "!mt-0 h-0 overflow-hidden"}
    >
      {stuck && (
        <>
          <p className="max-w-xs text-xs text-ps-hint">{STUCK_SENTENCE}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center rounded-lg border border-brand-light bg-white px-3 py-1.5 text-xs font-medium text-brand transition-colors hover:bg-ps-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            Reload
          </button>
        </>
      )}
    </div>
  );
}

"use client";

/**
 * TELLS A SIGNED-IN TAB THAT A NEWER BUILD OF THE SITE IS LIVE, AND LOADS IT WHEN THE PERSON NEXT MOVES (POST-A-529).
 *
 * `lib/version/newVersion.ts` is the rule and says why. This component does the three things the rule needs a browser for:
 *
 *   * it LOOKS: a small file on the site's own origin, asked for a while after the tab opens, on a slow beat while the tab
 *     is in front and when the person comes back to it. A look that fails, or that is answered by anything but the file
 *     expected, changes nothing: an unknown is never drawn as news;
 *   * it SAYS SO, once, in a small card that takes nothing from the person: no dimming, no focus taken, no timer;
 *   * it LOADS the new build when the address changes to another screen (the person's own move, with nothing typed on
 *     the screen they arrive at) or when they press the button. One automatic load per new build: if a cache in between
 *     served the old build again, the tab does not reload at every move, and the card with its button stays.
 *
 * It is drawn by the signed-in shell only. The sign-in pages and the portals load fresh each visit and have no long-lived
 * tab to tell.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { fetchBounded } from "@/lib/api/failureSentence";
import {
  RELOADED_FOR_KEY, VERSION_PATH, cleanVersion, dueForLook, isNewer, mayLoadOnMove, readLiveVersion,
} from "@/lib/version/newVersion";

/** The build this tab is running. Inlined at build time; null when the build had no id. */
const BUILT = cleanVersion(process.env.NEXT_PUBLIC_BUILD_ID);

/** How often the tab asks itself whether a look is due. The look itself is far rarer (see the rule). */
const TICK_MS = 15_000;

function loadedFor(): string | null {
  try { return window.sessionStorage.getItem(RELOADED_FOR_KEY); } catch { return null; }
}

export function NewVersionNotice({ pathname }: { pathname: string }) {
  const [live, setLive] = useState<string | null>(null);
  const openedAt = useRef<number>(Date.now());
  const lastLookAt = useRef<number | null>(null);
  const looking = useRef(false);

  const look = useCallback(async (returning: boolean) => {
    if (BUILT === null || looking.current) return;
    const visible = document.visibilityState === "visible";
    if (!dueForLook(Date.now(), openedAt.current, lastLookAt.current, visible, returning)) return;
    looking.current = true;
    lastLookAt.current = Date.now();
    try {
      // The site's own origin and a file with no person in it: no credentials, and never from a cache. Through the
      // product's bounded request, so a look that is never answered ends; what it throws is not shown to anybody.
      const res = await fetchBounded(`${VERSION_PATH}?t=${lastLookAt.current}`, { cache: "no-store", credentials: "omit" }, "read");
      if (!res.ok) return;
      const answered = readLiveVersion(await res.json());
      if (isNewer(BUILT, answered)) setLive(answered);
    } catch {
      // Offline, a 503 from the service worker, a page that is not JSON: nothing is known, so nothing is said.
    } finally {
      looking.current = false;
    }
  }, []);

  useEffect(() => {
    if (BUILT === null || live !== null) return;
    const tick = window.setInterval(() => { void look(false); }, TICK_MS);
    const onVisible = () => { if (document.visibilityState === "visible") void look(true); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [look, live]);

  // The person moved to another screen: load the new build there, once for this build.
  const arrivedAt = useRef(pathname);
  useEffect(() => {
    if (arrivedAt.current === pathname) return;
    arrivedAt.current = pathname;
    if (live === null || !mayLoadOnMove(live, loadedFor())) return;
    // Recorded BEFORE the load, and no load if it cannot be recorded: a tab that cannot remember would reload at every move.
    try { window.sessionStorage.setItem(RELOADED_FOR_KEY, live); } catch { return; }
    window.location.reload();
  }, [pathname, live]);

  return (
    // The live region is on the page before it has anything to say, so the words are announced when they arrive.
    <div role="status" aria-live="polite" data-new-version={live === null ? "none" : "ready"} className="fixed bottom-4 left-4 z-[45] max-w-sm print:hidden">
      {live !== null && (
        <div className="rounded-xl border border-ps-border bg-white p-4 shadow-lg">
          <p className="text-sm font-semibold text-ps-ink">A newer version of PracticeSync is ready</p>
          <p className="mt-1 text-xs text-ps-body">
            It loads by itself the next time you move to another screen. To load it now, save what you are typing first.
          </p>
          <Button variant="plain" size="none" onClick={() => window.location.reload()}
            className="mt-3 rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">
            Load it now
          </Button>
        </div>
      )}
    </div>
  );
}

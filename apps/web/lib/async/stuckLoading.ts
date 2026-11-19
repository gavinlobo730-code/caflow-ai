// A page that waits on nothing it can read and never finishes (POST-A-491).
//
// Seen on 18-11-2026 at 19:16 IST: the Clients list address showed only a spinner and "Loading workspace…", with the
// browser's busy pointer, until a hard reload cleared it. Two screens draw that text, the client workspace's entry page
// while it works out which client the address names and the not-found page's redirect branch, and each waits on the
// BROWSER (a redirect), not on a server read, so the shared slow-server notice (lib/async/slowServer.ts) is not theirs
// to show and neither had any time limit or any way out. The cause was NOT reproduced (this build cannot reach the live
// site); the likeliest is a tab opened before a new version of the site was published, asking for page files that no
// longer exist. So this does the two honest things whatever the cause: after a limit it SAYS it is taking longer and
// offers a reload, and a page whose own files fail to load reloads once by itself and then says what happened.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** How long the entry screens wait before they say so (milliseconds). */
export const STUCK_AFTER_MS = 8000;

export const STUCK_SENTENCE = "This is taking longer than usual. Reloading the page usually clears it.";

/** What a page says when its own files could not be loaded and the one automatic reload did not help. */
export const PAGE_CODE_SENTENCE =
  "This page's files could not be loaded. The site was probably updated while this tab was open. Reload the page to get the new version.";

/**
 * Whether `reason` is a page's own code failing to load: webpack's `ChunkLoadError` or "Loading chunk N failed",
 * a dynamic import the browser could not fetch ("Failed to fetch dynamically imported module", Safari's
 * "Importing a module script failed"). A render error in the page's own logic is NOT one, and is never reloaded away.
 */
export function isPageCodeFailure(reason: unknown): boolean {
  if (!reason || typeof reason !== "object") return false;
  const r = reason as { name?: unknown; message?: unknown };
  const name = typeof r.name === "string" ? r.name : "";
  const message = typeof r.message === "string" ? r.message : "";
  if (name === "ChunkLoadError") return true;
  return /loading chunk [^\s]+ failed|loading css chunk|failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module/i.test(message);
}

export const PAGE_CODE_RELOAD_KEY = "practicesync_page_code_reload_at";
/** One automatic reload per this long (milliseconds), so a page that keeps failing is not reloaded in a loop. */
export const PAGE_CODE_RELOAD_WINDOW_MS = 60_000;

export interface ReloadMemory {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/**
 * Whether the page may reload itself now for a failed page-code load, and if so records that it did. False when it already
 * did within the window (the reload did not help: the screen says so instead), and false when the memory cannot be
 * used, because a reload that cannot be remembered could repeat for ever.
 */
export function mayReloadForPageCode(memory: ReloadMemory | null, nowMs: number): boolean {
  if (!memory) return false;
  try {
    const last = Number(memory.getItem(PAGE_CODE_RELOAD_KEY));
    if (Number.isFinite(last) && last > 0 && nowMs - last >= 0 && nowMs - last < PAGE_CODE_RELOAD_WINDOW_MS) return false;
    memory.setItem(PAGE_CODE_RELOAD_KEY, String(nowMs));
    return true;
  } catch {
    return false;
  }
}

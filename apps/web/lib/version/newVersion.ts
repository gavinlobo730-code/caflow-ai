// Whether a newer build of the site is live than the one this tab is running (POST-A-529). The rule, and nothing else.
//
// WHAT WAS WRONG. Every merge republishes the site. A tab opened before it keeps the pages it loaded, and the first sign
// was a screen that would not load (POST-A-491, POST-A-495): the old pages asked for files the new build no longer has.
// Those were made to recover; this makes the tab KNOW, so the person is told before anything fails.
//
// THE RULE.
//   * The tab's own build has an id (inlined at build time); the live site serves its id as a small file. They differ
//     only when a newer build has been published. An id that could not be read, on either side, is UNKNOWN, and unknown
//     is never "newer": a failed read, a build with no id, or a file that is not what was expected says nothing.
//   * The file is asked for rarely: a while after the tab opens, then on a slow beat while the tab is in front, and when
//     the person comes back to a tab that has been away. Never while it is hidden.
//   * A tab that knows is told once and stays told. It loads the new build when the person next MOVES TO ANOTHER SCREEN
//     (their own act, with nothing typed on the screen they arrive at) or presses the button, and never on a timer:
//     a reload in the middle of a form would lose what was typed.
//   * One automatic load per new build. If the load did not bring the new build (a cache in between), the tab does not
//     reload again at every move; the notice stays and the button is the way.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** How long after the tab opens the first look is taken, and the beat after that (milliseconds). */
export const FIRST_CHECK_AFTER_MS = 30_000;
export const CHECK_EVERY_MS = 5 * 60_000;
/** A tab brought back to the front looks again if its last look is older than this. */
export const RECHECK_ON_RETURN_MS = 60_000;

/** Where the live site says which build it is. Written by scripts/write-build-version.mjs. */
export const VERSION_PATH = "/version.json";
export const RELOADED_FOR_KEY = "practicesync_new_version_loaded_for";

const ID = /^[A-Za-z0-9._-]{1,80}$/;

/** A build id, or null when the value is not one. */
export function cleanVersion(value: unknown): string | null {
  return typeof value === "string" && ID.test(value) ? value : null;
}

/** The id the live site answered with, or null when the answer is not the file this module expects. */
export function readLiveVersion(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return cleanVersion((payload as { version?: unknown }).version);
}

/** True only when both ids are known and they differ. */
export function isNewer(built: unknown, live: unknown): boolean {
  const mine = cleanVersion(built);
  const theirs = cleanVersion(live);
  return mine !== null && theirs !== null && mine !== theirs;
}

/** Whether to look now. `lastLookAt` is null before the first look; `openedAt` is when the tab's shell mounted. */
export function dueForLook(now: number, openedAt: number, lastLookAt: number | null, visible: boolean, returning: boolean): boolean {
  if (!visible) return false;
  if (lastLookAt === null) return now - openedAt >= FIRST_CHECK_AFTER_MS;
  return now - lastLookAt >= (returning ? RECHECK_ON_RETURN_MS : CHECK_EVERY_MS);
}

/** Whether moving to another screen may load the new build by itself: once per new build, never twice for the same one. */
export function mayLoadOnMove(live: unknown, alreadyLoadedFor: unknown): boolean {
  const id = cleanVersion(live);
  return id !== null && id !== cleanVersion(alreadyLoadedFor);
}

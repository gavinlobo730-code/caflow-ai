// A signed-in tab somebody is using tells the server it is still there, so the server can say which devices a login is signed in
// on right now (POST-A-486).
//
// WHEN. Not on a timer alone: a tab left open overnight must not look like a person at a desk. A tab reports when it has not
// reported for SEEN_EVERY_MS AND somebody has touched it (a key, a pointer, a touch, a wheel, in any tab of this browser) within
// that same stretch. The server counts a session as live for the idle limit plus this interval (domain/identity/devices.py), and
// `apps/api/tests/test_devices_on_a_login.py` holds the two numbers equal to the ones written here and in `idleTimeout.ts`.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** How often a tab that is being used reports. Minutes * 60 * 1000 on purpose: a server test reads the number from this line. */
export const SEEN_EVERY_MS = 10 * 60 * 1000;

/**
 * Whether to tell the server now.
 * - `lastReport`: when this tab last did (epoch ms), or null if it has not.
 * - `newestActivity`: the newest key, pointer, touch or wheel in any tab (epoch ms), or null if none is known.
 * The first report of a tab goes at once (the sign-in itself counts as use); later ones wait the interval and need activity in it.
 */
export function shouldReportSeen(
  now: number,
  lastReport: number | null | undefined,
  newestActivity: number | null | undefined,
): boolean {
  if (typeof lastReport !== "number" || !Number.isFinite(lastReport)) return true;
  if (now < lastReport) return true; // a clock that moved back: report rather than go quiet
  if (now - lastReport < SEEN_EVERY_MS) return false;
  if (typeof newestActivity !== "number" || !Number.isFinite(newestActivity)) return false;
  return now - newestActivity < SEEN_EVERY_MS;
}

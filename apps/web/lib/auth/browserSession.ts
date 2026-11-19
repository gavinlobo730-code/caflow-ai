// A sign-in lasts until the browser is closed, unless the person asked to stay signed in (POST-A-483).
//
// THE LIMIT, STATED PLAINLY. No web page can detect that a browser has been closed: nothing runs at that moment. So
// this works the other way round. The sign-in service keeps its session in the browser's long-lived storage (so every
// tab shares one session, and its token renewal stays correct across tabs). When a page starts, it asks "is this
// browser session still the one the person signed in during?":
//
//   - the tab remembers it in session storage (cleared when the browser closes), or
//   - another tab of this browser holds the page's "alive" lock (Web Locks: held by a tab for as long as it exists, a
//     sleeping or frozen tab included, and released the moment the browser closes), or answers a ping, or
//   - a tab of this browser wrote its heartbeat a short while ago (a hidden tab's timer runs about once a minute, so
//     the window is two minutes; closing the browser and reopening it inside two minutes stays signed in), or
//   - the person ticked "Keep me signed in on this computer" (honoured for 14 days, never longer).
//
// Everything the decision reads is captured when the page's script first runs, BEFORE anything of this page writes a marker
// or a heartbeat of its own, and none of this page's writers acts until the decision is made: the sign-in service announces
// a session recovered from storage as a sign-in too, and a heartbeat written a moment before the decision reads it would
// make every start look like a continuation (found by the independent review, which ran the real library to prove it).
// A page that arrives from a sign-in link (the address carries the sign-in) is a fresh sign-in, not a restored session.
//
// If none holds, the browser was closed in between and the person is signed out, on this device only. A browser that
// restores its tabs on reopening ("continue where you left off") restores session storage with them, and nothing here
// can tell that from an unbroken session; the idle timeout (lib/auth/idleTimeout) is the second lock.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** Local storage: `{"until": <epoch ms>}`, written by the sign-in page when the box is ticked. */
export const KEEP_KEY = "practicesync_keep_signed_in";
/** Local storage: the newest heartbeat any tab of this browser wrote, epoch ms. */
export const ALIVE_KEY = "practicesync_alive";
/** Session storage: this tab belongs to the browser session the person signed in during. */
export const MARKER_KEY = "practicesync_session_marker";
/** The channel tabs of one browser ping each other on. */
export const CHANNEL_NAME = "practicesync-session";

export const KEEP_DAYS = 14;
const DAY_MS = 24 * 60 * 60 * 1000;
/** A tab writes its heartbeat this often while a person is signed in. */
export const HEARTBEAT_EVERY_MS = 10_000;
/** A heartbeat this recent says the browser was open a moment ago (see the header for why it is two minutes). */
export const HEARTBEAT_FRESH_MS = 120_000;
/** How long a starting tab waits for another tab to answer its ping. */
export const PING_WAIT_MS = 400;
/** The lock a tab holds for as long as it exists, so another tab can tell the browser is still open (Web Locks). */
export const ALIVE_LOCK_NAME = "practicesync-tab-alive";
/** How long a sign-out waits for the API to record the logout before it signs out anyway: the record is best-effort. */
export const LOGOUT_RECORD_WAIT_MS = 2_500;

/** The moment "keep me signed in" ends if ticked at `now`: never more than KEEP_DAYS. */
export function keepUntil(now: number): number {
  return now + KEEP_DAYS * DAY_MS;
}

/** The text the sign-in page stores when the box is ticked: the end, and WHO ticked it, because the next person to sign in on this
 *  computer by another door (an invitation, a portal) did not tick anything and must not inherit the last person's choice. */
export function keepFlag(now: number, userId: string): string {
  return JSON.stringify({ until: keepUntil(now), uid: userId });
}

/** Whether the stored keep flag is still good at `now` FOR THIS PERSON. An unreadable value, a missing one, a past one, one further
 *  away than KEEP_DAYS (somebody edited it) and one ticked by somebody else are all "no". */
export function keepIsActive(raw: string | null | undefined, now: number, userId: string | null | undefined): boolean {
  if (!raw || !userId) return false;
  try {
    const v: unknown = JSON.parse(raw);
    const o = v && typeof v === "object" ? (v as Record<string, unknown>) : {};
    const until = o.until;
    return o.uid === userId && typeof until === "number" && Number.isFinite(until) && until > now && until <= now + KEEP_DAYS * DAY_MS + 60_000;
  } catch {
    return false;
  }
}

/** Whether an address carries a sign-in the sign-in service is about to read (an emailed link, an invitation, a password reset): the
 *  person has just signed in, so what is stored is not a session left over from before. */
export function urlCarriesASignIn(hash: string, search: string): boolean {
  const text = `${hash}&${search}`;
  return /[#?&](access_token|refresh_token|token_hash|code)=/.test(text) || /[#?&]type=(recovery|magiclink|signup|invite|email_change|email)\b/.test(text);
}

export type StartDecision = "continue" | "end";

/** What a page that is starting does about a session it finds stored. */
export function startDecision(args: {
  keepActive: boolean;
  hasMarker: boolean;
  /** The page's address carries a sign-in (see `urlCarriesASignIn`). */
  freshSignIn?: boolean;
  /** Another tab of this browser holds the alive lock (Web Locks), where the browser has them. */
  otherTabHoldsLock?: boolean;
  otherTabAnswered: boolean;
  /** Milliseconds since a tab of this browser last wrote its heartbeat, or null when none ever did. */
  heartbeatAgeMs: number | null;
}): StartDecision {
  if (args.keepActive || args.hasMarker || args.freshSignIn || args.otherTabHoldsLock || args.otherTabAnswered) return "continue";
  const age = args.heartbeatAgeMs;
  if (age !== null && age >= -60_000 && age <= HEARTBEAT_FRESH_MS) return "continue";
  return "end";
}

/** The heartbeat's age at `now`, or null when `raw` is not a number. */
export function heartbeatAge(raw: string | null | undefined, now: number): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? now - n : null;
}

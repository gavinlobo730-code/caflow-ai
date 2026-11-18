// A signed-in screen left alone is signed out after thirty minutes, with a warning in the last minute (POST-A-483).
//
// "Left alone" means no key pressed, no pointer or touch moved, no wheel turned in ANY tab of this browser: the newest
// such moment is shared through local storage. An API call does not count by itself, because the app makes some on its
// own (a keep-awake ping, polling) and a timeout that those keep alive would never fire; a call a person causes follows
// a key or a click, which does count.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** Local storage: the newest activity in any tab, epoch ms. */
export const ACTIVITY_KEY = "practicesync_last_active";

export const IDLE_LIMIT_MS = 30 * 60 * 1000;
export const WARN_BEFORE_MS = 60 * 1000;
/** A tab writes its activity no more often than this, so a busy hand costs one write every few seconds. */
export const ACTIVITY_WRITE_EVERY_MS = 5_000;

export type IdleState = "active" | "warning" | "expired";

export interface IdleStatus {
  state: IdleState;
  /** Whole seconds until the sign-out, 0 once expired. */
  secondsLeft: number;
}

/** Where a session stands at `now`, given the newest activity. An unreadable or future stamp counts as "just now",
 *  never as "long ago": a clock that jumped must not sign anybody out. */
export function idleStatus(now: number, lastActive: number | null | undefined): IdleStatus {
  const last = typeof lastActive === "number" && Number.isFinite(lastActive) && lastActive <= now ? lastActive : now;
  const idleFor = now - last;
  const left = IDLE_LIMIT_MS - idleFor;
  if (left <= 0) return { state: "expired", secondsLeft: 0 };
  const secondsLeft = Math.ceil(left / 1000);
  return { state: left <= WARN_BEFORE_MS ? "warning" : "active", secondsLeft };
}

/** Whether a tab should write a new activity stamp now (it last wrote at `lastWrite`). */
export function shouldWriteActivity(now: number, lastWrite: number | null | undefined): boolean {
  if (typeof lastWrite !== "number" || !Number.isFinite(lastWrite)) return true;
  return now - lastWrite >= ACTIVITY_WRITE_EVERY_MS || now < lastWrite;
}

/** The activity stamp in local storage as a number, or null. */
export function parseActivity(raw: string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

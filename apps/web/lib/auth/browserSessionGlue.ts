// The browser half of lib/auth/browserSession: the storage, the channel, the lock and the sign-out that the pure decisions
// are applied with (POST-A-483). Everything here is guarded, because storage, BroadcastChannel and Web Locks can be blocked
// (private windows, a browser with site data off) and a convenience that cannot run must never stop the app.
//
// ORDER IS THE WHOLE DESIGN. What the decision reads is captured when this module first runs (`startFacts`, below), before any
// component of the page has rendered; and the two writers that would change what a LATER read finds (`markBrowserSession` and
// `beat`) do nothing until the decision has been made. The first version let the sign-in service's own announcement of a
// session recovered from storage ("SIGNED_IN") mark the tab, and let the heartbeat start, before the decision read them, so the
// decision always found a session that looked continuous and ended nothing (the independent review ran the real library to prove
// it, 19-11-2026).
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  ALIVE_KEY, ALIVE_LOCK_NAME, CHANNEL_NAME, HEARTBEAT_EVERY_MS, KEEP_KEY, LOGOUT_RECORD_WAIT_MS, MARKER_KEY, PING_WAIT_MS,
  heartbeatAge, keepFlag, keepIsActive, startDecision, urlCarriesASignIn,
} from "./browserSession.ts";

function local(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}
function session(): Storage | null {
  try { return typeof window === "undefined" ? null : window.sessionStorage; } catch { return null; }
}

/** What the page found when it started. Read once, before anything of this page writes. */
export interface StartFacts {
  hasMarker: boolean;
  keepRaw: string | null;
  heartbeatRaw: string | null;
  at: number;
  freshSignIn: boolean;
}

export function readStartFacts(): StartFacts | null {
  try {
    if (typeof window === "undefined") return null;
    return {
      hasMarker: !!session()?.getItem(MARKER_KEY),
      keepRaw: local()?.getItem(KEEP_KEY) ?? null,
      heartbeatRaw: local()?.getItem(ALIVE_KEY) ?? null,
      at: Date.now(),
      freshSignIn: urlCarriesASignIn(window.location.hash ?? "", window.location.search ?? ""),
    };
  } catch { return null; }
}

const startFacts: StartFacts | null = readStartFacts();

let decided = false;
/** True once the page has decided what to do about a stored session; until then nothing of this page marks or beats. */
export function browserSessionDecided(): boolean { return decided; }

/** This tab belongs to the browser session the person signed in during. A no-op until the start decision is made. */
export function markBrowserSession(): void {
  if (!decided) return;
  try { session()?.setItem(MARKER_KEY, "1"); } catch { /* a convenience */ }
}

/** The sign-in page's "Keep me signed in on this computer": on for fourteen days for THIS person, or off. */
export function rememberKeepSignedIn(keep: boolean, userId?: string | null): void {
  try {
    if (keep && userId) local()?.setItem(KEEP_KEY, keepFlag(Date.now(), userId));
    else local()?.removeItem(KEEP_KEY);
  } catch { /* a convenience */ }
}

export function forgetKeepSignedIn(): void { rememberKeepSignedIn(false); }

/** Write this tab's heartbeat now. A no-op until the start decision is made. */
export function beat(): void {
  if (!decided) return;
  try { local()?.setItem(ALIVE_KEY, String(Date.now())); } catch { /* a convenience */ }
}

export { HEARTBEAT_EVERY_MS };

let channel: BroadcastChannel | null = null;
/** Answer another tab's ping while this tab belongs to the browser session. Once per page. */
function startResponder(): void {
  if (channel || typeof BroadcastChannel === "undefined") return;
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (ev: MessageEvent) => {
      if (ev.data === "ping" && session()?.getItem(MARKER_KEY)) channel?.postMessage("pong");
    };
  } catch { channel = null; }
}

/** Ask the other tabs of this browser whether they are alive, waiting a moment for an answer. */
function askOtherTabs(): Promise<boolean> {
  if (typeof BroadcastChannel === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    let asker: BroadcastChannel;
    try { asker = new BroadcastChannel(CHANNEL_NAME); } catch { resolve(false); return; }
    const done = (answered: boolean) => { clearTimeout(timer); asker.close(); resolve(answered); };
    const timer = setTimeout(() => done(false), PING_WAIT_MS);
    asker.onmessage = (ev: MessageEvent) => { if (ev.data === "pong") done(true); };
    asker.postMessage("ping");
  });
}

let lockHeld = false;
/** Hold the alive lock for as long as this page exists, so another tab can tell the browser is open. Once per page. */
function holdAliveLock(): void {
  if (lockHeld) return;
  try {
    const locks = (typeof navigator === "undefined" ? undefined : navigator.locks);
    if (!locks) return;
    lockHeld = true;
    void locks.request(ALIVE_LOCK_NAME, { mode: "shared" }, () => new Promise<void>(() => { /* held until the page goes */ })).catch(() => { lockHeld = false; });
  } catch { lockHeld = false; }
}

/** Whether some OTHER tab holds the alive lock. A frozen or sleeping tab still holds it; a closed browser holds none. */
async function otherTabHoldsLock(): Promise<boolean> {
  try {
    const locks = (typeof navigator === "undefined" ? undefined : navigator.locks);
    if (!locks?.query) return false;
    const state = await locks.query();
    return !!state.held?.some((l) => l.name === ALIVE_LOCK_NAME);
  } catch { return false; }
}

/** Run `record` and wait for it, but never longer than `waitMs`: a cold server must not keep a sign-out waiting. Never throws. */
async function recordWithin(record: () => Promise<unknown>, waitMs: number): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      record().catch(() => undefined),
      new Promise<void>((resolve) => { timer = setTimeout(resolve, waitMs); }),
    ]);
  } catch { /* best-effort */ } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

/**
 * Run when a page starts, before the stored session is used. If the browser was closed since the person signed in and
 * they did not ask to stay signed in, the stored session is ended on THIS device only (scope "local": the person's
 * other devices are left alone). Returns what it did. The page's writers are released when the decision is made, whatever
 * it was (and whatever went wrong: a throw leaves the session kept).
 */
export async function enforceBrowserSession(
  client: SupabaseClient,
  facts: StartFacts | null = startFacts,
  /** Tells the server this session is over (the sign-out record), so a browser closed and reopened is not counted as a second
   *  device beside the session it left behind (POST-A-486). Best-effort and bounded: it never holds the sign-out. */
  recordEnd?: () => Promise<unknown>,
  waitMs: number = LOGOUT_RECORD_WAIT_MS,
): Promise<"kept" | "ended"> {
  startResponder();
  let outcome: "kept" | "ended" = "kept";
  try {
    const { data } = await client.auth.getSession();
    if (data.session && facts) {
      const now = facts.at;
      const keepActive = keepIsActive(facts.keepRaw, now, data.session.user?.id);
      const settled = keepActive || facts.hasMarker || facts.freshSignIn;
      const lock = settled ? false : await otherTabHoldsLock();
      const answered = settled || lock ? false : await askOtherTabs();
      const decision = startDecision({
        keepActive, hasMarker: facts.hasMarker, freshSignIn: facts.freshSignIn, otherTabHoldsLock: lock, otherTabAnswered: answered,
        heartbeatAgeMs: heartbeatAge(facts.heartbeatRaw, now),
      });
      if (decision === "end") outcome = "ended";
    }
  } finally {
    decided = true;
  }
  if (outcome === "ended") {
    if (recordEnd) await recordWithin(recordEnd, waitMs);
    await client.auth.signOut({ scope: "local" });
    return "ended";
  }
  markBrowserSession();
  holdAliveLock();
  return "kept";
}

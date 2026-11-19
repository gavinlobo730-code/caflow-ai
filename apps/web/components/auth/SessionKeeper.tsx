"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { closedAccountPath } from "@/lib/auth/closedAccount";
import {
  ACTIVITY_KEY, idleStatus, parseActivity, shouldWriteActivity,
} from "@/lib/auth/idleTimeout";
import { HEARTBEAT_EVERY_MS, beat } from "@/lib/auth/browserSessionGlue";

/**
 * Keeps a signed-in tab honest about two things (POST-A-483): that its browser is still open (a heartbeat the next
 * page start reads, lib/auth/browserSession) and that somebody is still there (thirty minutes without a key, a
 * pointer, a touch or a wheel in ANY tab signs the person out, with a warning in the last minute).
 *
 * Mounted once, inside the auth provider. It draws nothing until the last minute, and then a small banner, not a
 * full-screen overlay: the person can still see the page they are about to lose.
 */
const EVENTS = ["keydown", "pointerdown", "pointermove", "wheel", "touchstart", "scroll"] as const;

// Where the newest activity is kept: local storage, shared by every tab, and this tab's own memory when storage is blocked (a
// private window, site data off), so the clock still runs there instead of never expiring.
let memoryActivity: number | null = null;

function stamp(): void {
  memoryActivity = Date.now();
  try { window.localStorage.setItem(ACTIVITY_KEY, String(memoryActivity)); } catch { /* a convenience */ }
}

function newestActivity(): number | null {
  let stored: number | null = null;
  try { stored = parseActivity(window.localStorage.getItem(ACTIVITY_KEY)); } catch { /* blocked storage */ }
  return stored !== null && (memoryActivity === null || stored > memoryActivity) ? stored : memoryActivity;
}

export function SessionKeeper() {
  const { session, endSessionHere } = useAuth();
  const signedIn = !!session;
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const ending = useRef(false);

  // The heartbeat, and the signed-in moment counts as activity.
  useEffect(() => {
    if (!signedIn) return;
    beat();
    stamp();
    const timer = setInterval(beat, HEARTBEAT_EVERY_MS);
    const onVisible = () => { if (document.visibilityState === "visible") beat(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [signedIn]);

  // Activity in this tab, written (at most every few seconds) where every tab reads it.
  useEffect(() => {
    if (!signedIn) return;
    let lastWrite: number | null = null;
    const onActivity = () => {
      const now = Date.now();
      if (!shouldWriteActivity(now, lastWrite)) return;
      lastWrite = now;
      stamp();
    };
    EVENTS.forEach((e) => window.addEventListener(e, onActivity, { passive: true, capture: true }));
    return () => { EVENTS.forEach((e) => window.removeEventListener(e, onActivity, { capture: true })); };
  }, [signedIn]);

  // Once a second: where does the shared clock stand?
  useEffect(() => {
    if (!signedIn) { setSecondsLeft(null); return; }
    ending.current = false;
    const timer = setInterval(() => {
      const status = idleStatus(Date.now(), newestActivity());
      if (status.state === "expired") {
        if (ending.current) return;
        ending.current = true;
        void endSessionHere().finally(() => window.location.assign(closedAccountPath("idle")));
      } else {
        setSecondsLeft(status.state === "warning" ? status.secondsLeft : null);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [signedIn, endSessionHere]);

  if (!signedIn || secondsLeft === null) return null;
  return (
    <div
      role="alert"
      data-idle-warning=""
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 print:hidden flex items-center gap-3 rounded-lg border border-state-attention-border bg-state-attention-surface px-4 py-3 text-sm text-state-attention shadow-lg"
    >
      <span>You will be signed out in {secondsLeft} {secondsLeft === 1 ? "second" : "seconds"}: nothing has been touched for a while.</span>
      <Button variant="plain" size="none" onClick={stamp} className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">
        Stay signed in
      </Button>
    </div>
  );
}

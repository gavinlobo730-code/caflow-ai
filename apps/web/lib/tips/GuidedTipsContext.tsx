"use client";

/**
 * ONE PERSON'S GUIDED TIPS, HELD ONCE FOR THE WHOLE SHELL (POST-A-531).
 *
 * The pop-up (`components/tips/GuidedTip.tsx`) and the switch in Settings (`components/settings/GuidedTipsCard.tsx`) read the
 * same state, so turning the switch off removes the pop-up at once and "Turn off tips" on a pop-up is the switch in Settings.
 * The server keeps it (`/api/guided-tips`, the person's own row); this is the copy the open tab works from.
 *
 * AN UNKNOWN IS "NO TIPS". `state` is null until the server has answered and stays null when it could not: a tip is a prompt,
 * so nothing is drawn. The Settings card says in words that the setting could not be read, because there the person is
 * looking at a control and a blank would read as "off".
 *
 * CLOSING A TIP IS TOLD TO THE SERVER AND NOT WAITED FOR. The tip leaves the screen at once and stays gone for this tab; if
 * the write fails the tip is shown again the next time the product is opened, which is the truth (it was not recorded).
 * The SWITCH is waited for: the person is told it is off only when the server has said so.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { readTipsState } from "@/lib/tips/engine";

export interface TipsState { on: boolean; chosen: boolean; seen: string[] }

interface GuidedTipsValue {
  /** Null until read, and when it could not be read. */
  state: TipsState | null;
  /** True once the first read has ended, whichever way. */
  settled: boolean;
  /** Turn tips on or off. Resolves to null when the server kept it, or a sentence saying it did not. */
  setOn: (on: boolean) => Promise<string | null>;
  /** Close one tip for good. */
  close: (tipId: string) => void;
  /** Show every tip again. Resolves like `setOn`. */
  showAgain: () => Promise<string | null>;
}

const GuidedTipsContext = createContext<GuidedTipsValue | null>(null);

const NOT_SAVED = "That could not be saved just now, and nothing was changed. Try again.";

export function GuidedTipsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<TipsState | null>(null);
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    let live = true;
    api.guidedTips.get()
      .then((res) => { if (live) setState(res?.success ? readTipsState(res.data) : null); })
      .catch(() => { if (live) setState(null); })
      .finally(() => { if (live) setSettled(true); });
    return () => { live = false; };
  }, []);

  const keep = useCallback(async (call: () => Promise<{ success?: boolean; data?: unknown }>): Promise<string | null> => {
    try {
      const res = await call();
      const next = res?.success ? readTipsState(res.data) : null;
      if (!next) return NOT_SAVED;
      setState(next);
      return null;
    } catch {
      return NOT_SAVED;
    }
  }, []);

  const setOn = useCallback((on: boolean) => keep(() => api.guidedTips.set(on)), [keep]);
  const showAgain = useCallback(() => keep(() => api.guidedTips.showAgain()), [keep]);
  const close = useCallback((tipId: string) => {
    setState((s) => (s && !s.seen.includes(tipId) ? { ...s, seen: [...s.seen, tipId] } : s));
    api.guidedTips.seen(tipId).catch(() => { /* not recorded: the tip is shown again on the next visit, which is true */ });
  }, []);

  const value = useMemo(() => ({ state, settled, setOn, close, showAgain }), [state, settled, setOn, close, showAgain]);
  return <GuidedTipsContext.Provider value={value}>{children}</GuidedTipsContext.Provider>;
}

/** The person's tips. Outside the shell (a portal, a sign-in page) there is no provider and no tips: `state` is null. */
export function useGuidedTips(): GuidedTipsValue {
  return useContext(GuidedTipsContext) ?? {
    state: null, settled: true,
    setOn: async () => NOT_SAVED, close: () => {}, showAgain: async () => NOT_SAVED,
  };
}

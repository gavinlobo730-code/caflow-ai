"use client";

/**
 * A window of the firm's entity register, read from the server, with the answer to "are there more".
 *
 * Three screens list the register (the relationship explorer, the ownership map and the role form's entity picker) and each
 * took whatever came back as ALL of it: the explorer asked for 100, the map took the server's default 50, the picker 200.
 * A firm with more entities had the rest missing without a word, and the picker could not choose one of them at all
 * (POST-A-259). The server now says `has_more` (apps/api/routers/relationships.py), and this hook keeps it with the rows so
 * a screen can put `ListWindowNotice` under the list and widen the window with "Show more".
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { readWindow } from "@/lib/lists/readWindow";

export interface EntityRegisterWindow {
  hasMore: boolean;
  limit: number;
  maxLimit: number;
}

export function useEntityRegister<T>(initialLimit: number, enabled: boolean = true) {
  const [entities, setEntities] = useState<T[]>([]);
  const [window, setWindow] = useState<EntityRegisterWindow | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [moreBusy, setMoreBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The latest request wins: a slow answer to a smaller window must not replace a bigger one.
  const sequence = useRef(0);

  const read = useCallback(async (limit: number, widening: boolean) => {
    const mine = ++sequence.current;
    if (widening) setMoreBusy(true); else setLoading(true);
    setError(null);
    try {
      const res = await api.relatedParties.entities(undefined, limit);
      if (mine !== sequence.current) return;
      if (!res?.success) throw new Error(res?.error ?? "Failed to load the entity register");
      const win = readWindow<T>(res.data, "entities", limit);
      if (!win) throw new Error("The entity register came back in a form this screen cannot read.");
      setEntities(win.rows);
      setWindow({ hasMore: win.hasMore, limit: win.limit, maxLimit: win.maxLimit });
    } catch (e) {
      if (mine !== sequence.current) return;
      setError(e instanceof Error ? e.message : "Failed to load the entity register");
    } finally {
      if (mine === sequence.current) {
        setLoading(false);
        setMoreBusy(false);
      }
    }
  }, []);

  useEffect(() => {
    if (enabled) void read(initialLimit, false);
  }, [enabled, initialLimit, read]);

  // Nothing has been asked yet, nothing has come back and nothing has failed: that is still "loading", and a screen that
  // opens this on a click must not flash "no entity" for the frame before the effect has started the read.
  const pending = enabled && window === null && error === null;

  return {
    entities,
    window,
    loading: loading || pending,
    moreBusy,
    error,
    /** Ask for a bigger window (the limit `ListWindowNotice` offers). */
    showMore: (limit: number) => read(limit, true),
    reload: () => read(window?.limit ?? initialLimit, false),
  };
}

"use client";

/**
 * React adapter for `unsentDraft` (frontend_ux-23).
 *
 * An editor hands this the RAW fields it holds and whether they differ from a
 * freshly opened form; the hook keeps a debounced copy in this tab's
 * sessionStorage while they do, and — on the next visit to the same screen —
 * OFFERS what it kept. It never applies it: `offer` is data for a banner, and
 * the editor sets its own state only inside `restore()`'s caller, on a click.
 *
 * Order of events that matters:
 *   1. mount → read the stored draft (in an effect, not during render — the
 *      page is a static export and `window` does not exist on the server);
 *   2. only AFTER that read, start writing. Writing first would see a pristine
 *      form, "clear" the draft it had not read yet and leave the offer
 *      pointing at nothing on the second reload;
 *   3. while an offer is pending nothing is written, so typing over a form the
 *      person has not yet decided about cannot overwrite the draft on offer;
 *   4. `clear()` after a SUCCESSFUL save removes it and suppresses the write
 *      that a debounce timer queued a moment earlier — a draft left behind by a
 *      save would be offered back as work that was never sent.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import {
  browserSessionStorage, clearDraft, draftKey, readDraft, saveDraft,
  type DraftKind, type ReadDraft,
} from "@/lib/drafts/unsentDraft";

/** Long enough that typing is not a write per keystroke, short enough that a
 *  reload a moment after the last character still finds it (and `pagehide`
 *  flushes anyway). */
const WRITE_DELAY_MS = 500;

export interface UseUnsentDraft<T> {
  /** A stored draft waiting for the person's answer, or null. */
  offer: ReadDraft<T> | null;
  /** Take the offered fields and stop offering. The caller applies them. */
  restore: () => T | null;
  /** Throw the offered draft away and carry on with the fresh form. */
  discard: () => void;
  /** Call once the document has been SAVED. */
  clear: () => void;
}

export function useUnsentDraft<T>(opts: {
  kind: DraftKind;
  clientId: string | null | undefined;
  /** The document's id, or "new". */
  entityId: string | null | undefined;
  /** The raw fields as typed or picked — nothing derived. */
  fields: T;
  /** Do they differ from a freshly opened form? */
  dirty: boolean;
  /** Rebuilds the fields from unknown JSON, or returns null. */
  validate: (raw: unknown) => T | null;
  /** False for a read-only screen: nothing to keep and nothing to offer. */
  enabled?: boolean;
}): UseUnsentDraft<T> {
  const { kind, clientId, entityId, fields, dirty, validate, enabled = true } = opts;
  const { user } = useAuth();
  const key = useMemo(
    () => (enabled ? draftKey({ userId: user?.id, kind, clientId, entityId }) : null),
    [enabled, user?.id, kind, clientId, entityId],
  );

  const [offer, setOffer] = useState<ReadDraft<T> | null>(null);
  const [loaded, setLoaded] = useState(false);
  const json = JSON.stringify(fields);
  // What the form holds RIGHT NOW, for `clear()`: it is called from a save
  // handler whose closure may be a render or two old.
  const jsonNow = useRef(json);
  jsonNow.current = json;

  // The newest `validate` without making it a dependency: editors define it at
  // module level, but a caller that does not would otherwise re-read on every
  // render and re-offer a draft the person had just discarded.
  const validateRef = useRef(validate);
  validateRef.current = validate;

  // 1. Read once per key.
  useEffect(() => {
    setOffer(null);
    setLoaded(false);
    if (!key) return;
    setOffer(readDraft(browserSessionStorage(), key, (raw) => validateRef.current(raw)));
    setLoaded(true);
  }, [key]);

  // 2–3. Keep a copy while dirty; remove it when the form is back to pristine.
  const pending = useRef<(() => void) | null>(null);
  const suppressed = useRef<string | null>(null);
  useEffect(() => {
    pending.current = null;
    if (!key || !loaded || offer) return;
    if (suppressed.current === json) return;
    suppressed.current = null;
    const storage = browserSessionStorage();
    if (!dirty) {
      clearDraft(storage, key);
      return;
    }
    const write = () => {
      pending.current = null;
      saveDraft(storage, key, JSON.parse(json) as T);
    };
    pending.current = write;
    const timer = setTimeout(write, WRITE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [key, loaded, offer, dirty, json]);

  // A reload or a closed tab inside the debounce window must not lose the last
  // few keystrokes. `pagehide` is the one that fires reliably, including on
  // mobile Safari; `visibilitychange` covers a tab switch followed by a kill.
  useEffect(() => {
    const flush = () => { pending.current?.(); };
    const onHidden = () => { if (document.visibilityState === "hidden") flush(); };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", onHidden);
    };
  }, []);

  const restore = useCallback((): T | null => {
    if (!offer) return null;
    const taken = offer.fields;
    setOffer(null);
    return taken;
  }, [offer]);

  const discard = useCallback(() => {
    clearDraft(browserSessionStorage(), key);
    setOffer(null);
  }, [key]);

  const clear = useCallback(() => {
    pending.current = null;
    suppressed.current = jsonNow.current;
    clearDraft(browserSessionStorage(), key);
    setOffer(null);
  }, [key]);

  return { offer, restore, discard, clear };
}

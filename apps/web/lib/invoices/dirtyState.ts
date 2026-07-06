"use client";

/**
 * Unsaved-changes protection for the invoice editor (Batch 2).
 *
 * `hasChanges` is a pure, unit-tested structural comparator (order-insensitive for
 * object keys) used to decide whether the editor is "dirty". `useUnsavedChanges`
 * wires that dirtiness to the browser: it warns on tab close / reload (beforeunload)
 * and exposes `confirmLeave()` for in-app navigation guards. Autosave is intentionally
 * NOT implemented here (deferred).
 */
import { useEffect, useCallback } from "react";

/** Deep structural equality via canonical JSON (stable key order). */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_k, v) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      return Object.keys(v as Record<string, unknown>)
        .sort()
        .reduce((acc, k) => {
          acc[k] = (v as Record<string, unknown>)[k];
          return acc;
        }, {} as Record<string, unknown>);
    }
    return v;
  });
}

/** True when `current` differs structurally from `initial`. */
export function hasChanges(initial: unknown, current: unknown): boolean {
  return canonical(initial) !== canonical(current);
}

const LEAVE_MESSAGE = "You have unsaved changes. Leave without saving?";

/**
 * Guard the editor while `dirty` is true. Installs a `beforeunload` warning and
 * returns `confirmLeave()` — call it before any in-app navigation and only proceed
 * when it returns true. `message` is customisable for testing/wording.
 */
export function useUnsavedChanges(dirty: boolean, message: string = LEAVE_MESSAGE) {
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      // Modern browsers show their own generic text; setting returnValue is required.
      e.returnValue = message;
      return message;
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, message]);

  const confirmLeave = useCallback((): boolean => {
    if (!dirty) return true;
    return typeof window === "undefined" ? true : window.confirm(message);
  }, [dirty, message]);

  return { confirmLeave, leaveMessage: message };
}

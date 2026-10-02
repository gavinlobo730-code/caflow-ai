"use client";

/**
 * "Has this form been typed into?" for a form that holds its fields in
 * component state (frontend_ux-23).
 *
 * `useUnsavedChanges` (lib/invoices/dirtyState.ts) takes a boolean. The six
 * document editors compute it by hand against a snapshot taken at mount; the
 * drawers and the onboarding wizard that gained the warning with this change
 * each hold ten to twenty `useState` fields and would each have grown their own
 * copy of that bookkeeping. This is the one copy.
 *
 * THE BASELINE IS WHAT THE FORM HELD WHEN IT OPENED, OR WHEN IT WAS LAST SAVED.
 * The second half is the part a snapshot-at-mount gets wrong: a Profile form
 * saved and left open still differs from what it opened with, and would warn
 * about changes that are safely on the server. `markSaved()` re-baselines — but
 * to what the form holds on the NEXT render, not the last one, because a save
 * handler usually clears some fields in the same tick (`setBasic("")`) and
 * adopting the pre-clear values would leave the freshly emptied form "dirty".
 *
 * Fields that something other than the person sets — a category list that
 * arrives from the server and pre-selects a row — do not belong in `fields`,
 * or the form is dirty the moment it loads. Pass what the person types or picks.
 */
import { useCallback, useEffect, useState } from "react";
import { hasChanges } from "@/lib/invoices/dirtyState";

export function useDirtyFields<T>(fields: T): { dirty: boolean; markSaved: () => void } {
  // `null` means "adopt whatever the next render holds".
  const [baseline, setBaseline] = useState<T | null>(fields);
  const dirty = baseline !== null && hasChanges(baseline, fields);
  useEffect(() => {
    if (baseline === null) setBaseline(fields);
  }, [baseline, fields]);
  const markSaved = useCallback(() => setBaseline(null), []);
  return { dirty, markSaved };
}

/**
 * `obj` without `keys` — for a form whose state also holds fields that something
 * OTHER than the person fills in (a category list that arrives from the server
 * and pre-selects a row). It names what to leave OUT rather than what to watch,
 * on purpose: a field added to the form later is watched by default, where an
 * explicit list of the watched ones would quietly leave the new field — and
 * whatever is typed into it — unguarded.
 */
export function omitKeys<T extends object, K extends keyof T>(obj: T, keys: readonly K[]): Omit<T, K> {
  const drop = new Set<PropertyKey>(keys);
  return Object.fromEntries(Object.entries(obj).filter(([k]) => !drop.has(k))) as Omit<T, K>;
}

/**
 * Tell a parent that owns the leave-guard (a drawer with several sections, only
 * one mounted at a time) whether the section on screen has unsaved typing. It
 * says "clean" when the section unmounts, so switching sections or closing
 * leaves nothing stuck on.
 */
export function useReportDirty(report: (dirty: boolean) => void, dirty: boolean): void {
  useEffect(() => { report(dirty); }, [report, dirty]);
  useEffect(() => () => report(false), [report]);
}

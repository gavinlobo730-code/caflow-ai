"use client";
import { useEffect, useRef, useState } from "react";
import type { FilterValue, SortState } from "./types";

/**
 * Persisted slice of table state (NOT page number or row selection — those are
 * ephemeral). Saved to localStorage under a stable key so a user's search,
 * filters, sort, page size and visible columns survive reloads.
 */
export interface TablePrefs {
  search: string;
  sort: SortState | null;
  filters: Record<string, FilterValue>;
  pageSize: number;
  hiddenColumns: string[];
}

const storageKey = (k: string) => `practicesync.table.${k}`;

export function useTablePreferences(
  persistKey: string | undefined,
  initial: TablePrefs,
): readonly [TablePrefs, React.Dispatch<React.SetStateAction<TablePrefs>>] {
  const [prefs, setPrefs] = useState<TablePrefs>(initial);
  const hydrated = useRef(false);

  // Hydrate once on the client (kept out of the initial render so SSR/CSR match).
  useEffect(() => {
    if (!persistKey || hydrated.current) return;
    hydrated.current = true;
    try {
      const raw = localStorage.getItem(storageKey(persistKey));
      if (raw) setPrefs((p) => ({ ...p, ...(JSON.parse(raw) as Partial<TablePrefs>) }));
    } catch {
      /* corrupted/unavailable storage — fall back to defaults */
    }
  }, [persistKey]);

  // Persist after hydration so we never clobber saved prefs with defaults.
  useEffect(() => {
    if (!persistKey || !hydrated.current) return;
    try {
      localStorage.setItem(storageKey(persistKey), JSON.stringify(prefs));
    } catch {
      /* ignore quota/unavailable */
    }
  }, [persistKey, prefs]);

  return [prefs, setPrefs] as const;
}

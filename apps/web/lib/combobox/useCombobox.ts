"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { filterAndRank, hasExactMatch, normalize } from "./match";
import type { ComboboxState, UseComboboxArgs } from "./types";

/**
 * Headless combobox engine: owns query, result set (sync filter OR debounced
 * async fetch), loading/error, highlighted index and the create-row flag. The
 * presentational <Combobox> owns open/focus/click-away and renders what this
 * returns. Mirrors the useDataTable split (engine here, chrome in the component).
 */
export function useCombobox<T>({
  options,
  fetchOptions,
  recent,
  getOptionId,
  getSearchFields,
  onCreate,
  debounceMs = 250,
  minChars = 1,
}: UseComboboxArgs<T>): ComboboxState<T> {
  const [query, setQueryRaw] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const isAsync = typeof fetchOptions === "function";

  // Search fields default to the label only (wrappers pass richer sets).
  const fieldsOf = getSearchFields ?? (() => [] as string[]);

  const dedupeById = useCallback(
    (rows: T[]): T[] => {
      const seen = new Set<string>();
      const out: T[] = [];
      for (const r of rows) {
        const id = getOptionId(r);
        if (seen.has(id)) continue;
        seen.add(id);
        out.push(r);
      }
      return out;
    },
    [getOptionId],
  );

  // ── Sync results (client-side filter/rank) ──────────────────────────────────
  const syncResults = useMemo(() => {
    if (isAsync) return [] as T[];
    const all = options ?? [];
    const q = normalize(query);
    if (!q) return dedupeById([...(recent ?? []), ...all]); // recent first, full list
    return filterAndRank(all, query, fieldsOf);
    // fieldsOf identity is stable per render set; options/query/recent drive it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAsync, options, query, recent, dedupeById]);

  // ── Async results (debounced server fetch) ──────────────────────────────────
  const [asyncResults, setAsyncResults] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef(0);

  const runFetch = useCallback(
    (q: string) => {
      if (!fetchOptions) return;
      const seq = ++seqRef.current;
      setLoading(true);
      setError(null);
      fetchOptions(q)
        .then((rows) => {
          if (seq !== seqRef.current) return; // a newer request superseded this one
          setAsyncResults(rows ?? []);
          setLoading(false);
        })
        .catch(() => {
          if (seq !== seqRef.current) return;
          setError("Search failed");
          setAsyncResults([]);
          setLoading(false);
        });
    },
    [fetchOptions],
  );

  useEffect(() => {
    if (!isAsync) return;
    const q = query.trim();
    if (q.length < minChars) {
      seqRef.current++; // cancel any in-flight request
      setAsyncResults([]);
      setLoading(false);
      setError(null);
      return;
    }
    const t = setTimeout(() => runFetch(q), debounceMs);
    return () => clearTimeout(t);
  }, [isAsync, query, minChars, debounceMs, runFetch]);

  const results = useMemo(() => {
    if (!isAsync) return syncResults;
    // Before typing (or below minChars) show recent; otherwise the fetched set.
    if (query.trim().length < minChars) return dedupeById(recent ?? []);
    return asyncResults;
  }, [isAsync, syncResults, asyncResults, query, minChars, recent, dedupeById]);

  // Auto-highlight the first result whenever the visible set changes.
  useEffect(() => {
    setHighlighted(0);
  }, [results]);

  const showCreate = useMemo(() => {
    if (!onCreate) return false;
    if (!normalize(query)) return false;
    // Suppress when an existing option exactly equals the query.
    const pool = isAsync ? asyncResults : options ?? [];
    return !hasExactMatch(pool, query, fieldsOf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onCreate, query, isAsync, asyncResults, options]);

  const setQuery = useCallback((q: string) => setQueryRaw(q), []);
  const retry = useCallback(() => runFetch(query.trim()), [runFetch, query]);

  return {
    query,
    setQuery,
    results,
    loading,
    error,
    highlighted,
    setHighlighted,
    showCreate,
    retry,
  };
}

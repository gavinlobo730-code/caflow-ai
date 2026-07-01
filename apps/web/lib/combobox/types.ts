/**
 * Shared Combobox types (platform-wide searchable-picker system).
 *
 * The engine is HEADLESS. It supports BOTH modes with an identical UI:
 *   • sync   — pass `options` (already-loaded array); search/rank runs in-browser.
 *   • async  — pass `fetchOptions(query)`; a debounced server search backs it.
 * Callers pick the mode by which prop they supply. Everything else (keyboard,
 * a11y, create row, recent-first, rich rows) is common.
 */

export interface ComboboxCore<T> {
  /** Stable identity for an option — used for selection + React keys. */
  getOptionId: (o: T) => string;
  /** Primary line shown for an option (and in the closed trigger). */
  getLabel: (o: T) => string;
  /** Optional secondary line (GSTIN / code / balance) for rich rows. */
  getSecondary?: (o: T) => string | undefined;
  /**
   * Fields included in client-side search (sync mode). Defaults to [getLabel].
   * In async mode the server decides matching, so this is ignored.
   */
  getSearchFields?: (o: T) => string[];
}

export interface UseComboboxArgs<T> extends ComboboxCore<T> {
  /** Sync data source — already-loaded rows (client-side search). */
  options?: T[];
  /** Async data source — debounced server search. Takes precedence when set. */
  fetchOptions?: (query: string) => Promise<T[]>;
  /** Shown at the top before the user types (recent / frequent / favourites). */
  recent?: T[];
  /** Debounce for async fetches, ms (default 250). */
  debounceMs?: number;
  /** Minimum characters before an async fetch fires (default 1). */
  minChars?: number;
  /** Enable the "+ Create …" affordance; called with the current query. */
  onCreate?: (label: string) => void | Promise<void>;
}

/** What the presentational component receives from the hook. */
export interface ComboboxState<T> {
  query: string;
  setQuery: (q: string) => void;
  results: T[];
  loading: boolean;
  error: string | null;
  /** Index of the highlighted option; results.length means the create row. */
  highlighted: number;
  setHighlighted: (i: number) => void;
  /** True when the create row should render (onCreate set, non-empty, no exact match). */
  showCreate: boolean;
  retry: () => void;
}

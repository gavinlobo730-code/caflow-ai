/**
 * Shared DataTable types (platform-wide Search/Sort/Filter system).
 *
 * The engine is HEADLESS and CLIENT-SIDE: a page fetches its full dataset
 * (typically via lib/supabase/selectAll.ts, which pages past PostgREST's row cap)
 * and hands it to the table; search/sort/filter/paginate all run in-browser. This
 * suits SMB-scale data and needs no backend change. Integer paise throughout —
 * amount filters compare in paise (money accessors return *_paise).
 */
import type * as React from "react";

export type SortDir = "asc" | "desc";

export interface Column<T> {
  /** Stable key — used for sort state, column visibility and persistence. */
  key: string;
  header: string;
  /** Raw value for sorting / global search / CSV export. */
  accessor: (row: T) => unknown;
  /** Custom cell renderer; falls back to String(accessor(row)). */
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
  /** Include this column's accessor in global search (default: false). */
  searchable?: boolean;
  /** Allow the user to hide this column (default: true). */
  hideable?: boolean;
  /** Hidden by default until the user enables it. */
  defaultHidden?: boolean;
  align?: "left" | "right" | "center";
  /** Tailwind width class or CSS width. */
  width?: string;
  /** Pin as the sticky first column on horizontal scroll. */
  sticky?: boolean;
  /** Override the CSV export value (default: String(accessor(row))). */
  exportValue?: (row: T) => string | number;
  className?: string;
  headerClassName?: string;
}

export type SelectOption = { value: string; label: string };

export type FilterDef<T> =
  | {
      key: string;
      label: string;
      type: "select";
      accessor: (row: T) => unknown;
      options: SelectOption[];
      /** Allow multiple selected values (OR). Default false (single select). */
      multi?: boolean;
    }
  | {
      key: string;
      label: string;
      type: "dateRange";
      /** Must return an ISO date string (YYYY-MM-DD…) or null. */
      accessor: (row: T) => string | null | undefined;
    }
  | {
      key: string;
      label: string;
      type: "amountRange";
      /** Return an integer amount in PAISE; UI inputs are rupees (×100 internally). */
      accessor: (row: T) => number | null | undefined;
    }
  | {
      key: string;
      label: string;
      type: "boolean";
      accessor: (row: T) => boolean;
      /** Labels for the tri-state select (any / true / false). */
      trueLabel?: string;
      falseLabel?: string;
    };

export type FilterValue =
  | string // select (single) — "" means all
  | string[] // select (multi)
  | { from?: string; to?: string } // dateRange
  | { min?: number; max?: number } // amountRange, in PAISE
  | boolean // boolean
  | null;

export interface SortState {
  key: string;
  dir: SortDir;
}

export interface TableState {
  search: string;
  sort: SortState | null;
  filters: Record<string, FilterValue>;
  page: number; // 1-based
  pageSize: number;
  hiddenColumns: string[];
}

export interface BulkAction<T> {
  id: string;
  label: string;
  icon?: React.ReactNode;
  /**
   * Return `false` (or resolve to it) to signal the action did NOT fully
   * succeed — DataTable keeps the current selection instead of clearing it,
   * so the user can see what's still selected and retry or investigate
   * (e.g. some rows were skipped/blocked and got reported in a toast).
   * Returning void/undefined/true, same as before, clears the selection —
   * existing callers that never return anything are unaffected. A thrown
   * error is caught by DataTable and also does NOT clear the selection.
   */
  run: (selected: T[]) => void | boolean | Promise<void | boolean>;
  /** Ask for confirmation before running. */
  confirm?: string;
  /** Visual emphasis (e.g. destructive delete). */
  variant?: "default" | "danger";
}

export interface PageInfo<T> {
  rows: T[]; // the current page's rows
  total: number; // rows after search+filter (before pagination)
  pageCount: number;
  page: number; // clamped, 1-based
}

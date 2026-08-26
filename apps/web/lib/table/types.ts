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
  columnWidths: Record<string, number>;
}

export interface BulkAction<T> {
  id: string;
  label: string;
  icon?: React.ReactNode;
  /**
   * Runs the action over the currently-selected rows. Once it COMPLETES,
   * DataTable clears the selection — the rows have been acted on, so leaving
   * them (especially the ones that succeeded) selected reads as "nothing
   * happened". The action itself is responsible for reporting per-row
   * skips/failures (typically via a toast), which is the real source of
   * truth — not a lingering selection. The return value is ignored for
   * selection purposes. Only a THROWN error keeps the selection intact
   * (the action crashed rather than completing, so a retry makes sense).
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

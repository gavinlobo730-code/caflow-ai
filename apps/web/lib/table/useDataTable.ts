"use client";
import { useCallback, useMemo, useState } from "react";
import { processRows } from "./process";
import { useTablePreferences } from "./useTablePreferences";
import type { Column, FilterDef, FilterValue, SortState, TableState } from "./types";

export interface UseDataTableArgs<T> {
  data: T[];
  columns: Column<T>[];
  filters?: FilterDef<T>[];
  getRowId: (row: T) => string;
  initialSort?: SortState | null;
  initialPageSize?: number;
  /** localStorage key; omit to disable persistence. */
  persistKey?: string;
}

/**
 * Headless table engine: owns search/sort/filter/pagination/column-visibility/
 * selection state and returns the processed page. Works for BOTH <table> and
 * card-list renderers (the DataTable component consumes this; card screens can too).
 */
export function useDataTable<T>({
  data,
  columns,
  filters = [],
  getRowId,
  initialSort = null,
  initialPageSize = 50,
  persistKey,
}: UseDataTableArgs<T>) {
  const defaultHidden = useMemo(
    () => columns.filter((c) => c.defaultHidden).map((c) => c.key),
    [columns],
  );

  const [prefs, setPrefs] = useTablePreferences(persistKey, {
    search: "",
    sort: initialSort,
    filters: {},
    pageSize: initialPageSize,
    hiddenColumns: defaultHidden,
  });
  const [page, setPageRaw] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const state: TableState = { ...prefs, page };

  const result = useMemo(
    () => processRows(data, state, columns, filters),
    // `state` is rebuilt each render; depend on its fields explicitly instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, columns, filters, prefs.search, prefs.sort, prefs.filters, prefs.pageSize, page],
  );

  // ── mutators (search/filter/sort reset to page 1) ──────────────────────────
  const setSearch = useCallback((search: string) => {
    setPrefs((p) => ({ ...p, search }));
    setPageRaw(1);
  }, [setPrefs]);

  const toggleSort = useCallback((key: string) => {
    setPrefs((p) => {
      const dir: "asc" | "desc" =
        p.sort?.key === key && p.sort.dir === "asc" ? "desc" : "asc";
      return { ...p, sort: { key, dir } };
    });
    setPageRaw(1);
  }, [setPrefs]);

  const setFilter = useCallback((key: string, value: FilterValue) => {
    setPrefs((p) => ({ ...p, filters: { ...p.filters, [key]: value } }));
    setPageRaw(1);
  }, [setPrefs]);

  const clearFilters = useCallback(() => {
    setPrefs((p) => ({ ...p, filters: {}, search: "" }));
    setPageRaw(1);
  }, [setPrefs]);

  const setPageSize = useCallback((pageSize: number) => {
    setPrefs((p) => ({ ...p, pageSize }));
    setPageRaw(1);
  }, [setPrefs]);

  const setPage = useCallback((p: number) => setPageRaw(p), []);

  const toggleColumn = useCallback((key: string) => {
    setPrefs((p) => ({
      ...p,
      hiddenColumns: p.hiddenColumns.includes(key)
        ? p.hiddenColumns.filter((k) => k !== key)
        : [...p.hiddenColumns, key],
    }));
  }, [setPrefs]);

  const visibleColumns = useMemo(
    () => columns.filter((c) => !prefs.hiddenColumns.includes(c.key)),
    [columns, prefs.hiddenColumns],
  );

  const activeFilterCount = useMemo(
    () =>
      Object.values(prefs.filters).filter(
        (v) => v != null && v !== "" && !(Array.isArray(v) && v.length === 0),
      ).length,
    [prefs.filters],
  );

  // ── selection ──────────────────────────────────────────────────────────────
  const isSelected = useCallback((row: T) => selected.has(getRowId(row)), [selected, getRowId]);

  const toggleRow = useCallback((row: T) => {
    const id = getRowId(row);
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [getRowId]);

  const pageRows = result.page.rows;
  const allOnPageSelected = pageRows.length > 0 && pageRows.every((r) => selected.has(getRowId(r)));

  const toggleAllOnPage = useCallback(() => {
    setSelected((s) => {
      const next = new Set(s);
      const ids = pageRows.map(getRowId);
      const allSel = ids.length > 0 && ids.every((id) => next.has(id));
      ids.forEach((id) => (allSel ? next.delete(id) : next.add(id)));
      return next;
    });
  }, [pageRows, getRowId]);

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  const selectedRows = useMemo(
    () => data.filter((r) => selected.has(getRowId(r))),
    [data, selected, getRowId],
  );

  return {
    state,
    prefs,
    page: result.page,
    filtered: result.filtered,
    visibleColumns,
    activeFilterCount,
    setSearch,
    toggleSort,
    setFilter,
    clearFilters,
    setPage,
    setPageSize,
    toggleColumn,
    // selection
    selected,
    selectedRows,
    isSelected,
    toggleRow,
    toggleAllOnPage,
    allOnPageSelected,
    clearSelection,
  };
}

"use client";
import * as React from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Columns3,
  Download,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { AsyncBoundary, EmptyState } from "@/components/ui/states";
import { TableSkeleton } from "@/components/ui/skeleton";
import { useDataTable } from "@/lib/table/useDataTable";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { toCsv } from "@/lib/table/process";
import type { BulkAction, Column, FilterDef, SortState } from "@/lib/table/types";

// 1000 matches lib/supabase/selectAll's own page size — the largest page a
// caller can pick still corresponds to exactly one fetched page of data, so
// picking it never requires more data than what's already loaded client-side.
const PAGE_SIZES = [25, 50, 100, 250, 1000];

export interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  getRowId: (row: T) => string;
  filters?: FilterDef<T>[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onRefresh?: () => void;
  searchPlaceholder?: string;
  initialSort?: SortState | null;
  initialPageSize?: number;
  /** Default filter values applied until the user changes them (then persisted). */
  initialFilters?: Record<string, import("@/lib/table/types").FilterValue>;
  pageSizes?: number[];
  bulkActions?: BulkAction<T>[];
  /** Enables "Export CSV" of the current filtered view (all matching rows). */
  exportFilename?: string;
  stickyHeader?: boolean;
  persistKey?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: React.ReactNode;
  /** Trailing per-row actions column. */
  rowActions?: (row: T) => React.ReactNode;
  onRowClick?: (row: T) => void;
  /** Extra toolbar controls (e.g. a financial-year selector). */
  toolbarExtra?: React.ReactNode;
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * A ready-made "Export selected" bulk action — reuses the same CSV export
 * the toolbar's own "Export" button uses (see `exportFilename`), just scoped
 * to the checked rows instead of the whole filtered view. Drop it straight
 * into `bulkActions`:
 *   bulkActions={[...myActions, exportSelectedAction("invoices.csv", columns)]}
 */
export function exportSelectedAction<T>(filename: string, columns: Column<T>[]): BulkAction<T> {
  return {
    id: "export-selected",
    label: "Export selected",
    icon: <Download size={13} />,
    run: (selected) => { downloadCsv(filename, toCsv(selected, columns)); },
  };
}

const btn =
  "inline-flex items-center gap-1.5 rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-xs font-medium text-[#475569] transition-colors hover:bg-[#F8FAFC] disabled:opacity-50";

export function DataTable<T>({
  data,
  columns,
  getRowId,
  filters = [],
  loading = false,
  error = null,
  onRetry,
  onRefresh,
  searchPlaceholder = "Search…",
  initialSort = null,
  initialPageSize = 50,
  initialFilters,
  pageSizes = PAGE_SIZES,
  bulkActions,
  exportFilename,
  stickyHeader = true,
  persistKey,
  emptyTitle = "No records",
  emptyDescription,
  emptyAction,
  rowActions,
  onRowClick,
  toolbarExtra,
}: DataTableProps<T>) {
  const t = useDataTable<T>({ data, columns, filters, getRowId, initialSort, initialPageSize, initialFilters, persistKey });
  const hasSearch = columns.some((c) => c.searchable);
  const hasBulk = Boolean(bulkActions && bulkActions.length);
  // Which bulk action (by id) is currently running — disables the whole bar
  // so a second click can't fire mid-run, and shows a spinner on that button.
  const [runningActionId, setRunningActionId] = React.useState<string | null>(null);

  // Debounced search box (kept in sync with persisted/cleared state).
  const [q, setQ] = React.useState(t.prefs.search);
  React.useEffect(() => setQ(t.prefs.search), [t.prefs.search]);
  React.useEffect(() => {
    const id = setTimeout(() => {
      if (q !== t.prefs.search) t.setSearch(q);
    }, 250);
    return () => clearTimeout(id);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const { page } = t;
  const colSpan = t.visibleColumns.length + (hasBulk ? 1 : 0) + (rowActions ? 1 : 0);
  const start = page.total === 0 ? 0 : (page.page - 1) * t.prefs.pageSize + 1;
  const end = t.prefs.pageSize <= 0 ? page.total : Math.min(page.page * t.prefs.pageSize, page.total);

  const align = (a?: string) => (a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left");

  return (
    <div className="space-y-3">
      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        {hasSearch && (
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={searchPlaceholder}
              aria-label="Search"
              className="w-56 rounded-lg border border-[#E2E8F0] bg-white py-1.5 pl-8 pr-7 text-xs text-[#334155] placeholder:text-[#94A3B8] focus:border-[#94A3B8] focus:outline-none"
            />
            {q && (
              <button aria-label="Clear search" onClick={() => setQ("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-[#94A3B8] hover:text-[#475569]">
                <X size={13} />
              </button>
            )}
          </div>
        )}

        {filters.map((f) => (
          <FilterControl key={f.key} def={f} value={t.prefs.filters[f.key]} onChange={(v) => t.setFilter(f.key, v)} />
        ))}

        {(t.activeFilterCount > 0 || t.prefs.search) && (
          <button onClick={t.clearFilters} className="text-xs font-medium text-[#64748B] underline-offset-2 hover:underline">
            Clear
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          {toolbarExtra}
          <ColumnVisibility columns={columns} hidden={t.prefs.hiddenColumns} onToggle={t.toggleColumn} />
          {exportFilename && (
            <button
              className={btn}
              onClick={() => downloadCsv(exportFilename, toCsv(t.filtered, t.visibleColumns))}
              disabled={page.total === 0}
              title="Export the current filtered view to CSV"
            >
              <Download size={13} /> Export
            </button>
          )}
          {onRefresh && (
            <button className={btn} onClick={onRefresh} aria-label="Refresh">
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          )}
        </div>
      </div>

      {/* ── Bulk action bar ─────────────────────────────────────────────── */}
      {hasBulk && t.selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[#C7D2FE] bg-[#EEF2FF] px-3 py-2 text-xs">
          <span className="font-semibold text-[#3730A3]">{t.selected.size} selected</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {bulkActions!.map((a) => (
              <button
                key={a.id}
                disabled={runningActionId !== null}
                onClick={async () => {
                  if (a.confirm && !(await confirmDialog({ message: a.confirm, danger: a.variant === "danger" }))) return;
                  setRunningActionId(a.id);
                  try {
                    // A thrown error, same as an explicit `return false`, leaves
                    // the selection intact — the action's own toast/report (if
                    // any) is the source of truth for what happened per row, not
                    // "the selection went away so it must have worked."
                    const result = await a.run(t.selectedRows);
                    if (result !== false) t.clearSelection();
                  } catch (e) {
                    console.error(`Bulk action "${a.id}" failed:`, e);
                  } finally {
                    setRunningActionId(null);
                  }
                }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  a.variant === "danger"
                    ? "border border-red-200 bg-white text-red-700 hover:bg-red-50"
                    : "border border-[#C7D2FE] bg-white text-[#4338CA] hover:bg-[#E0E7FF]",
                )}
              >
                {runningActionId === a.id ? <Loader2 size={13} className="animate-spin" /> : a.icon} {a.label}
              </button>
            ))}
            <button onClick={t.clearSelection} disabled={runningActionId !== null} className="text-[#6366F1] hover:text-[#4338CA] disabled:opacity-50" aria-label="Clear selection">
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={page.total === 0}
        onRetry={onRetry}
        skeleton={<TableSkeleton rows={8} cols={Math.min(colSpan || 4, 6)} />}
        empty={<div className="rounded-xl border border-[#F1F5F9] bg-white"><EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} /></div>}
      >
        <div className="overflow-x-auto rounded-xl border border-[#F1F5F9] bg-white">
          <table className="w-full text-xs">
            <thead className={cn(stickyHeader && "sticky top-0 z-10", "bg-[#F8FAFC]")}>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                {hasBulk && (
                  <th className="w-8 px-3 py-3">
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      checked={t.allOnPageSelected}
                      onChange={t.toggleAllOnPage}
                      className="cursor-pointer accent-[#4338CA]"
                    />
                  </th>
                )}
                {t.visibleColumns.map((c) => {
                  const active = t.state.sort?.key === c.key;
                  return (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={active ? (t.state.sort!.dir === "asc" ? "ascending" : "descending") : "none"}
                      style={c.width ? { width: c.width } : undefined}
                      className={cn(
                        "px-3 py-3 font-semibold", align(c.align),
                        c.sticky && "sticky left-0 bg-[#F8FAFC]",
                        c.sortable && "cursor-pointer select-none hover:text-[#475569]",
                        c.headerClassName,
                      )}
                      onClick={c.sortable ? () => t.toggleSort(c.key) : undefined}
                    >
                      <span className={cn("inline-flex items-center gap-1", c.align === "right" && "flex-row-reverse")}>
                        {c.header}
                        {c.sortable && (active
                          ? (t.state.sort!.dir === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)
                          : <ChevronsUpDown size={11} className="text-[#CBD5E1]" />)}
                      </span>
                    </th>
                  );
                })}
                {rowActions && <th className="px-3 py-3 text-right font-semibold">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {page.rows.map((row) => {
                const id = getRowId(row);
                const sel = t.isSelected(row);
                return (
                  <tr
                    key={id}
                    className={cn("hover:bg-[#F8FAFC]", sel && "bg-[#EEF2FF]", onRowClick && "cursor-pointer")}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {hasBulk && (
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label="Select row"
                          checked={sel}
                          onChange={() => t.toggleRow(row)}
                          className="cursor-pointer accent-[#4338CA]"
                        />
                      </td>
                    )}
                    {t.visibleColumns.map((c) => (
                      <td
                        key={c.key}
                        className={cn("px-3 py-2 text-[#334155]", align(c.align), c.sticky && "sticky left-0 bg-white", c.className)}
                      >
                        {c.render ? c.render(row) : String(c.accessor(row) ?? "")}
                      </td>
                    ))}
                    {rowActions && (
                      <td className="px-3 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                        {rowActions(row)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </AsyncBoundary>

      {/* ── Pagination footer ───────────────────────────────────────────── */}
      {page.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#64748B]">
          <div className="flex items-center gap-2">
            <span>Rows per page</span>
            <select
              value={t.prefs.pageSize}
              onChange={(e) => t.setPageSize(Number(e.target.value))}
              className="rounded-lg border border-[#E2E8F0] bg-white px-2 py-1 text-[#475569]"
              aria-label="Rows per page"
            >
              {pageSizes.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <span>{start}–{end} of {page.total}</span>
            <div className="flex items-center gap-1">
              <button className={btn} disabled={page.page <= 1} onClick={() => t.setPage(page.page - 1)}>Prev</button>
              <span className="px-1">Page {page.page} / {page.pageCount}</span>
              <button className={btn} disabled={page.page >= page.pageCount} onClick={() => t.setPage(page.page + 1)}>Next</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Filter controls ──────────────────────────────────────────────────────────
function FilterControl<T>({
  def,
  value,
  onChange,
}: {
  def: FilterDef<T>;
  value: unknown;
  onChange: (v: import("@/lib/table/types").FilterValue) => void;
}) {
  const sel = "rounded-lg border border-[#E2E8F0] bg-white px-2 py-1.5 text-xs text-[#475569] focus:border-[#94A3B8] focus:outline-none";
  const num = "w-24 rounded-lg border border-[#E2E8F0] bg-white px-2 py-1.5 text-xs text-[#475569] focus:border-[#94A3B8] focus:outline-none";

  if (def.type === "select") {
    return (
      <select aria-label={def.label} className={sel} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">{def.label}: All</option>
        {def.options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    );
  }
  if (def.type === "boolean") {
    const v = value == null ? "" : value ? "true" : "false";
    return (
      <select aria-label={def.label} className={sel} value={v} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}>
        <option value="">{def.label}: All</option>
        <option value="true">{def.trueLabel ?? "Yes"}</option>
        <option value="false">{def.falseLabel ?? "No"}</option>
      </select>
    );
  }
  if (def.type === "dateRange") {
    const v = (value as { from?: string; to?: string }) ?? {};
    return (
      <span className="inline-flex items-center gap-1" title={def.label}>
        <input type="date" aria-label={`${def.label} from`} className={sel} value={v.from ?? ""} onChange={(e) => onChange({ ...v, from: e.target.value })} />
        <span className="text-[#CBD5E1]">–</span>
        <input type="date" aria-label={`${def.label} to`} className={sel} value={v.to ?? ""} onChange={(e) => onChange({ ...v, to: e.target.value })} />
      </span>
    );
  }
  // amountRange — UI in rupees, stored in paise
  const v = (value as { min?: number; max?: number }) ?? {};
  const toPaise = (s: string) => (s === "" ? undefined : Math.round(Number(s) * 100));
  const toRupees = (p?: number) => (p == null ? "" : String(p / 100));
  return (
    <span className="inline-flex items-center gap-1" title={`${def.label} (₹)`}>
      <input type="number" inputMode="decimal" placeholder={`${def.label} min ₹`} aria-label={`${def.label} minimum`} className={num} value={toRupees(v.min)} onChange={(e) => onChange({ ...v, min: toPaise(e.target.value) })} />
      <span className="text-[#CBD5E1]">–</span>
      <input type="number" inputMode="decimal" placeholder="max ₹" aria-label={`${def.label} maximum`} className={num} value={toRupees(v.max)} onChange={(e) => onChange({ ...v, max: toPaise(e.target.value) })} />
    </span>
  );
}

// ── Column visibility menu ───────────────────────────────────────────────────
function ColumnVisibility<T>({
  columns,
  hidden,
  onToggle,
}: {
  columns: Column<T>[];
  hidden: string[];
  onToggle: (key: string) => void;
}) {
  const hideable = columns.filter((c) => c.hideable !== false);
  if (hideable.length === 0) return null;
  return (
    <details className="relative">
      <summary className={cn(btn, "cursor-pointer list-none")}>
        <Columns3 size={13} /> Columns
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-52 rounded-lg border border-[#E2E8F0] bg-white p-1.5 shadow-lg">
        {hideable.map((c) => (
          <label key={c.key} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-[#475569] hover:bg-[#F8FAFC]">
            <input type="checkbox" checked={!hidden.includes(c.key)} onChange={() => onToggle(c.key)} className="cursor-pointer accent-[#4338CA]" />
            {c.header}
          </label>
        ))}
      </div>
    </details>
  );
}

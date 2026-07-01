/**
 * Pure, dependency-free DataTable engine: search → filter → sort → paginate, plus
 * CSV export. No React here, so it is unit-tested with `node --test`. Deterministic
 * and stable (sort is stable; ties keep input order).
 */
import type {
  Column,
  FilterDef,
  FilterValue,
  PageInfo,
  SortState,
  TableState,
} from "./types";

const _s = (v: unknown): string => (v == null ? "" : String(v));

/** Global substring search across the columns' accessors marked `searchable`. */
export function applySearch<T>(rows: T[], query: string, columns: Column<T>[]): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  const cols = columns.filter((c) => c.searchable);
  if (cols.length === 0) return rows;
  return rows.filter((r) =>
    cols.some((c) => _s(c.accessor(r)).toLowerCase().includes(q)),
  );
}

function matchesFilter<T>(row: T, def: FilterDef<T>, value: FilterValue): boolean {
  if (value == null || value === "") return true;
  switch (def.type) {
    case "select": {
      const rv = _s(def.accessor(row));
      if (Array.isArray(value)) return value.length === 0 || value.includes(rv);
      return rv === _s(value);
    }
    case "boolean": {
      if (typeof value !== "boolean") return true;
      return Boolean(def.accessor(row)) === value;
    }
    case "dateRange": {
      const v = value as { from?: string; to?: string };
      const rv = _s(def.accessor(row)).slice(0, 10);
      if (!rv) return false;
      if (v.from && rv < v.from) return false;
      if (v.to && rv > v.to) return false;
      return true;
    }
    case "amountRange": {
      const v = value as { min?: number; max?: number };
      const rv = Number(def.accessor(row) ?? 0); // paise
      if (v.min != null && rv < v.min) return false;
      if (v.max != null && rv > v.max) return false;
      return true;
    }
    default:
      return true;
  }
}

export function applyFilters<T>(
  rows: T[],
  filters: Record<string, FilterValue>,
  defs: FilterDef<T>[],
): T[] {
  const active = defs.filter((d) => {
    const v = filters[d.key];
    return v != null && v !== "" && !(Array.isArray(v) && v.length === 0);
  });
  if (active.length === 0) return rows;
  return rows.filter((r) => active.every((d) => matchesFilter(r, d, filters[d.key])));
}

function compare(a: unknown, b: unknown): number {
  // Nullish sinks to the end regardless of direction caller applies afterwards.
  const an = a == null || a === "";
  const bn = b == null || b === "";
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return _s(a).localeCompare(_s(b), undefined, { numeric: true, sensitivity: "base" });
}

export function applySort<T>(rows: T[], sort: SortState | null, columns: Column<T>[]): T[] {
  if (!sort) return rows;
  const col = columns.find((c) => c.key === sort.key);
  if (!col) return rows;
  // Stable sort: decorate with index so equal keys keep input order.
  const decorated = rows.map((row, i) => ({ row, i }));
  const factor = sort.dir === "asc" ? 1 : -1;
  decorated.sort((x, y) => {
    const c = compare(col.accessor(x.row), col.accessor(y.row));
    return c !== 0 ? c * factor : x.i - y.i;
  });
  return decorated.map((d) => d.row);
}

export function paginate<T>(rows: T[], page: number, pageSize: number): PageInfo<T> {
  const total = rows.length;
  if (!pageSize || pageSize <= 0) {
    return { rows, total, pageCount: 1, page: 1 };
  }
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const clamped = Math.min(Math.max(1, page), pageCount);
  const start = (clamped - 1) * pageSize;
  return { rows: rows.slice(start, start + pageSize), total, pageCount, page: clamped };
}

export interface ProcessResult<T> {
  /** After search + filter + sort (all matching rows, not just the page). */
  filtered: T[];
  page: PageInfo<T>;
}

export function processRows<T>(
  rows: T[],
  state: TableState,
  columns: Column<T>[],
  filterDefs: FilterDef<T>[],
): ProcessResult<T> {
  const searched = applySearch(rows, state.search, columns);
  const filtered = applyFilters(searched, state.filters, filterDefs);
  const sorted = applySort(filtered, state.sort, columns);
  const page = paginate(sorted, state.page, state.pageSize);
  return { filtered: sorted, page };
}

function csvCell(v: string | number): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV of the given rows using visible, exportable columns (header row included). */
export function toCsv<T>(rows: T[], columns: Column<T>[]): string {
  const cols = columns.filter((c) => c.exportValue !== null);
  const header = cols.map((c) => csvCell(c.header)).join(",");
  const body = rows
    .map((r) =>
      cols
        .map((c) => csvCell(c.exportValue ? c.exportValue(r) : _s(c.accessor(r))))
        .join(","),
    )
    .join("\n");
  return `${header}\n${body}`;
}

// Tests for the pure DataTable engine. Run with:
//   node --experimental-strip-types --test lib/table/process.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  applySearch,
  applyFilters,
  applySort,
  paginate,
  processRows,
  toCsv,
} from "./process.ts";
import type { Column, FilterDef, TableState } from "./types.ts";

interface Row {
  no: string;
  customer: string;
  total_paise: number;
  date: string;
  status: string;
}

const ROWS: Row[] = [
  { no: "INV-3", customer: "Acme", total_paise: 500000, date: "2025-06-10", status: "paid" },
  { no: "INV-1", customer: "Beta", total_paise: 118000, date: "2025-04-01", status: "issued" },
  { no: "INV-2", customer: "acme corp", total_paise: 900000, date: "2025-05-15", status: "issued" },
];

const columns: Column<Row>[] = [
  { key: "no", header: "No", accessor: (r) => r.no, searchable: true, sortable: true },
  { key: "customer", header: "Customer", accessor: (r) => r.customer, searchable: true },
  { key: "total", header: "Total", accessor: (r) => r.total_paise, sortable: true, exportValue: (r) => r.total_paise / 100 },
  { key: "date", header: "Date", accessor: (r) => r.date, sortable: true },
];

const filters: FilterDef<Row>[] = [
  { key: "status", label: "Status", type: "select", accessor: (r) => r.status, options: [] },
  { key: "date", label: "Date", type: "dateRange", accessor: (r) => r.date },
  { key: "amount", label: "Amount", type: "amountRange", accessor: (r) => r.total_paise },
];

function state(over: Partial<TableState> = {}): TableState {
  return { search: "", sort: null, filters: {}, page: 1, pageSize: 0, hiddenColumns: [], ...over };
}

test("search is case-insensitive substring across searchable columns only", () => {
  assert.deepEqual(applySearch(ROWS, "acme", columns).map((r) => r.no), ["INV-3", "INV-2"]);
  // 'paid' is a status column that is NOT searchable → no match
  assert.equal(applySearch(ROWS, "paid", columns).length, 0);
  assert.equal(applySearch(ROWS, "", columns).length, 3);
});

test("select filter matches exact; multi is OR; empty = all", () => {
  assert.deepEqual(applyFilters(ROWS, { status: "issued" }, filters).map((r) => r.no), ["INV-1", "INV-2"]);
  assert.equal(applyFilters(ROWS, { status: "" }, filters).length, 3);
  assert.equal(applyFilters(ROWS, { status: ["paid", "issued"] }, filters).length, 3);
});

test("dateRange filter is inclusive", () => {
  const r = applyFilters(ROWS, { date: { from: "2025-05-01", to: "2025-06-30" } }, filters);
  assert.deepEqual(r.map((x) => x.no).sort(), ["INV-2", "INV-3"]);
});

test("amountRange filter compares in paise", () => {
  const r = applyFilters(ROWS, { amount: { min: 200000, max: 800000 } }, filters);
  assert.deepEqual(r.map((x) => x.no), ["INV-3"]);
});

test("sort is stable and numeric-aware; asc/desc", () => {
  assert.deepEqual(applySort(ROWS, { key: "total", dir: "asc" }, columns).map((r) => r.total_paise), [118000, 500000, 900000]);
  assert.deepEqual(applySort(ROWS, { key: "total", dir: "desc" }, columns).map((r) => r.total_paise), [900000, 500000, 118000]);
  // string/date sort
  assert.deepEqual(applySort(ROWS, { key: "date", dir: "asc" }, columns).map((r) => r.no), ["INV-1", "INV-2", "INV-3"]);
});

test("blanks/nulls always sort last, in both directions", () => {
  const rows = [
    { no: "A", customer: "", total_paise: 0, date: "", status: "" },
    { no: "B", customer: "", total_paise: 0, date: "2025-01-01", status: "" },
    { no: "C", customer: "", total_paise: 0, date: "2025-06-01", status: "" },
  ];
  const asc = applySort(rows, { key: "date", dir: "asc" }, columns).map((r) => r.no);
  const desc = applySort(rows, { key: "date", dir: "desc" }, columns).map((r) => r.no);
  assert.equal(asc[asc.length - 1], "A"); // blank date last on asc
  assert.equal(desc[desc.length - 1], "A"); // blank date STILL last on desc
  assert.deepEqual(asc, ["B", "C", "A"]);
  assert.deepEqual(desc, ["C", "B", "A"]);
});

test("paginate clamps page and slices", () => {
  const p = paginate(ROWS, 2, 2);
  assert.equal(p.pageCount, 2);
  assert.equal(p.page, 2);
  assert.deepEqual(p.rows.map((r) => r.no), ["INV-2"]);
  // out-of-range page clamps to last
  assert.equal(paginate(ROWS, 99, 2).page, 2);
  // pageSize 0 → all rows, one page
  assert.equal(paginate(ROWS, 1, 0).rows.length, 3);
});

test("processRows composes search+filter+sort+paginate", () => {
  const res = processRows(ROWS, state({ search: "acme", sort: { key: "total", dir: "desc" }, page: 1, pageSize: 1 }), columns, filters);
  assert.equal(res.filtered.length, 2); // Acme + acme corp
  assert.deepEqual(res.filtered.map((r) => r.total_paise), [900000, 500000]);
  assert.deepEqual(res.page.rows.map((r) => r.no), ["INV-2"]); // first page, biggest total
  assert.equal(res.page.total, 2);
});

test("toCsv escapes and uses exportValue", () => {
  const csv = toCsv([{ no: "A,1", customer: 'He said "hi"', total_paise: 12345, date: "2025-04-01", status: "x" }], columns);
  const [header, row] = csv.split("\n");
  assert.equal(header, "No,Customer,Total,Date");
  assert.equal(row, '"A,1","He said ""hi""",123.45,2025-04-01');
});

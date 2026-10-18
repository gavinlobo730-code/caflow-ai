// The DataTable toolbar's "Clear" clears a server-side search as well. Run with:
//   node --experimental-strip-types --test scripts/a-datatable-clear-clears-a-server-side-search.test.ts
//
// WHY THIS EXISTS (ledger POST-A-146)
//     The toolbar's Clear link called `t.clearFilters` only, and was shown only when a LOCAL preference was set. A
//     server-paged table keeps its search on the server's side of the line (`serverPaged.search`), so with a server search
//     in force and no column filter the link was not even shown; with a filter set it cleared the filter and left the
//     server still filtering by the search, while the page read as cleared. The "Nothing matches" empty-state button had
//     been fixed to clear everything the reader set; the toolbar link now does the same, through the same two calls.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { hostElements, loadModule, requireFromWeb, startRecording } from "./tsxHarness.ts";

const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const { DataTable } = loadModule<{ DataTable: React.ComponentType<Record<string, unknown>> }>("components/ui/data-table");

interface Row { id: string; name: string }
const ROWS: Row[] = [{ id: "a", name: "Alpha" }, { id: "b", name: "Bravo" }];
const COLUMNS = [{ key: "name", header: "Name", accessor: (r: Row) => r.name }];

function clearButtons(extra: Record<string, unknown>): { text: string }[] {
  startRecording();
  renderToStaticMarkup(React.createElement(DataTable, {
    data: ROWS, columns: COLUMNS, getRowId: (r: Row) => r.id, ...extra,
  }));
  return hostElements("button")
    .map((b) => ({ text: String((b.props as { children?: unknown }).children ?? "").trim() }))
    .filter((b) => b.text === "Clear");
}

const serverPaged = (search: string) => ({
  page: 1, pageSize: 25, total: 2, onPageChange: () => {}, onPageSizeChange: () => {},
  search, onSearchChange: () => {},
});

test("a server-side search in force shows the toolbar Clear link", () => {
  assert.equal(clearButtons({ serverPaged: serverPaged("gst") }).length, 1);
});

test("with no search in force there is no Clear link", () => {
  assert.equal(clearButtons({ serverPaged: serverPaged("") }).length, 0);
});

test("the toolbar link clears the local preferences AND the search box, which reaches the server through the debounce", () => {
  const src = fs.readFileSync(path.join(import.meta.dirname, "..", "components/ui/data-table.tsx"), "utf8");
  assert.match(src, /serverSearch \? serverPaged\?\.search : t\.prefs\.search/, "visibility asks the server's side for a server table");
  assert.match(src, /onClick=\{\(\) => \{ t\.clearFilters\(\); setQ\(""\); \}\}\s+className="text-xs font-medium text-ps-label/,
    "the toolbar link must do what the empty-state button does");
  assert.doesNotMatch(src, /<button onClick=\{t\.clearFilters\}/, "the bare clearFilters handler is the defect");
});

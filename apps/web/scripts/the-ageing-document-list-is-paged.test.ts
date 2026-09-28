// apex-accounting-reports-05.
//
// DocumentList rendered `rows.map` over EVERY open document — every one of
// them, with no paging, sort or search — and built a MarkToggle (one or two
// per row) for the whole array on every render. Confirmed live on one Apex
// client: 5,655 tbody rows for ar-aging, rows in server order with no pattern
// (147, 508, 506, 250… days overdue), and a single toggle click took 27.1s to
// even register because the main thread was busy re-rendering all 5,655.
//
// The fix routes the list through the shared DataTable
// (components/ui/data-table.tsx), whose own `page.rows.map`
// (lib/table/useDataTable.ts -> lib/table/process.ts) slices to ONE PAGE
// before building any cell — so a column's `render`, MarkToggle included, is
// only ever constructed for the rows actually on screen. What this file pins:
// DocumentList no longer walks `rows` itself, it hands DataTable a default
// sort by days-overdue DESCENDING, it keeps a search box, and the two marks
// (Disputed, Doubtful) are unchanged in what they send the server.
//
// Run with: node --experimental-strip-types --test scripts/the-ageing-document-list-is-paged.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "reports", "ageing", "page.tsx");
const raw = fs.readFileSync(PAGE, "utf8");
const code = stripComments(raw);

const start = code.indexOf("function DocumentList");
const end = code.indexOf("function MarkToggle", start);
assert.ok(start >= 0, "DocumentList must still exist in the ageing page");
assert.ok(end > start, "MarkToggle must still exist after DocumentList");
const body = code.slice(start, end);

test("DocumentList imports and renders the shared DataTable", () => {
  assert.match(code, /import \{ DataTable \} from "@\/components\/ui\/data-table"/,
    "the shared table component is not imported");
  assert.match(body, /<DataTable/, "DocumentList no longer delegates to DataTable");
});

test("DocumentList does not hand-roll its own row loop any more", () => {
  // The defect, in one token: `rows.map(` built a <tr> — and a MarkToggle —
  // for every open document, unpaged. With DataTable doing the paging, this
  // file must never iterate `rows` itself; it only ever hands the whole array
  // to DataTable as `data` and lets the table slice it.
  assert.doesNotMatch(body, /rows\.map\(/,
    "DocumentList is iterating `rows` directly again — that is the defect apex-accounting-reports-05 fixed");
  assert.doesNotMatch(body, /<tr\b/,
    "DocumentList is building its own <tr> again instead of DataTable's rows");
});

test("the default sort is by days overdue, descending", () => {
  assert.match(body, /initialSort=\{\{\s*key:\s*"days_overdue",\s*dir:\s*"desc"\s*\}\}/,
    "the list must open sorted by how long a document has been open, oldest first");
});

test("a search box is offered (at least one searchable column)", () => {
  assert.match(body, /searchable:\s*true/,
    "no column is marked searchable, so DataTable's search box will not render at all");
  assert.match(body, /searchPlaceholder=/,
    "no search placeholder is wired through to DataTable");
});

test("MarkToggle is still built per row, from a DataTable column render — not eagerly for the whole array", () => {
  assert.match(body, /<MarkToggle/, "the mark controls were dropped");
  // A `render` callback takes ONE row (`d`) — DataTable invokes it once per
  // row of the CURRENT PAGE only (see components/ui/data-table.tsx, which
  // maps over `page.rows`, not `data`). Asserting the two MarkToggle call
  // sites live inside such a `render:` closure, and not in a bare loop over
  // the whole `rows` array, is what keeps the fix from being undone by
  // reintroducing a manual map elsewhere in this function.
  const disputedIdx = body.indexOf("is_disputed");
  const doubtfulIdx = body.indexOf("considered_doubtful");
  assert.ok(disputedIdx >= 0 && doubtfulIdx >= 0, "both marks must still be wired up");
  const renderBefore = (idx: number) => body.lastIndexOf("render: (d) =>", idx);
  assert.ok(renderBefore(disputedIdx) >= 0 && renderBefore(disputedIdx) < disputedIdx,
    "the disputed toggle is not built inside a column's render(d) callback");
  assert.ok(renderBefore(doubtfulIdx) >= 0 && renderBefore(doubtfulIdx) < doubtfulIdx,
    "the doubtful toggle is not built inside a column's render(d) callback");
});

test("marking a document still sends the same request shape the server expects", () => {
  // classifyForAgeing's contract did not change — only how the row that calls
  // it is rendered. Both marks must still flip the boolean they name and
  // still carry client_id / target / target_id.
  assert.match(body, /is_disputed:\s*!d\.is_disputed/);
  assert.match(body, /considered_doubtful:\s*!d\.considered_doubtful/);
  assert.match(body, /target:\s*isAr\s*\?\s*"invoice"\s*:\s*"bill"/);
  assert.match(body, /target:\s*"invoice",/, "the doubtful mark must stay invoice-only — it has no row on the payables table");
});

test("pagination is DataTable's own client-side pager, not disabled", () => {
  // initialPageSize is only ever passed to switch OFF sub-pagination (0 means
  // "all rows, one page" — see components/ui/data-table.tsx). DocumentList
  // must not pass it, so the component's own default (50) applies.
  assert.doesNotMatch(body, /initialPageSize/,
    "DocumentList must not override DataTable's own page size — that is how a table quietly goes back to rendering everything at once");
});

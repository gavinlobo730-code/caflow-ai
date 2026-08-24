// A pagination control must do what it says. Run with:
//   node --experimental-strip-types --test scripts/pagination-controls-are-real.test.ts
//
// WHY THIS EXISTS
//     The account-ledger drill-down shipped with TWO pagers. The server sent one
//     page of 100 rows; DataTable then rendered its own "Rows per page" and
//     Prev/Next over those 100, beside the server pager saying "1–100 of 1278".
//     Choosing 1000 rows per page re-sliced 100 rows into one page of 100 and
//     the screen did not move. Reported as "I changed rows per page but nothing
//     happened", and it was exactly that: a control wired to nothing.
//
//     Nothing was broken in a way a test of behaviour would notice — every
//     button worked, the numbers were right, the data was right. The control
//     was simply inert, and only a reader trying to use it would ever find out.
//
// WHAT IS ASSERTED
//     1. No component renders BOTH a DataTable and its own Prev/Next pager.
//        That combination is the bug: DataTable always draws a footer, so a
//        second one means two, and the inner one can only see the slice it was
//        handed. A caller with server-side paging passes `serverPaged` instead,
//        which suppresses the inner pager and drives the server.
//     2. Any caller passing limit/offset to a fetch that feeds a DataTable
//        passes `serverPaged`. Without it the footer silently paginates a page.
//
//     Both are preceded by a check that the scan found anything, because a
//     selector matching nothing passes every assertion after it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const ROOTS = ["app", "components"].map((d) => path.join(ROOT, d));

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

const FILES = ROOTS.flatMap((d) => (fs.existsSync(d) ? walk(d) : []))
  .map((f) => ({ path: path.relative(ROOT, f), src: fs.readFileSync(f, "utf8") }));

const usesDataTable = (s: string) => /<DataTable\b/.test(s);
// Button text on its own line, which is how the pagers in this codebase are
// written. `>Prev<` on one line would not match, so both shapes are covered.
const hasOwnPager = (s: string) =>
  /^\s*(Previous|Prev|Next)\s*$/m.test(s) || />\s*(Previous|Prev|Next)\s*</.test(s);
const declaresServerPaged = (s: string) => /serverPaged\s*=?\s*[{:]/.test(s);
// A fetch that asks the server for a slice.
const sendsOffset = (s: string) =>
  /offset:\s*String\(|offset=\$\{|[?&]offset=/.test(s);

test("the scan finds the tables and pagers at all", () => {
  assert.ok(FILES.length > 100, `only ${FILES.length} source files scanned`);
  const tables = FILES.filter((f) => usesDataTable(f.src));
  assert.ok(tables.length >= 15,
    `expected the DataTable callers, found ${tables.length}`);
  const pagers = FILES.filter((f) => hasOwnPager(f.src));
  assert.ok(pagers.length >= 2,
    `expected the hand-rolled pagers, found ${pagers.length}`);
});

test("no screen renders a DataTable and its own pager as well", () => {
  const both = FILES
    .filter((f) => usesDataTable(f.src) && hasOwnPager(f.src))
    // data-table.tsx itself legitimately contains both: it IS the pager.
    .filter((f) => !f.path.endsWith(path.join("ui", "data-table.tsx")))
    .map((f) => f.path);

  assert.deepEqual(both, [],
    "these render two pagers. DataTable always draws a footer, so a second " +
    "Prev/Next means the reader sees both — and the inner one can only " +
    "re-slice the rows already fetched, which makes its \"Rows per page\" a " +
    "control that does nothing. Pass `serverPaged` to DataTable instead:\n  " +
    both.join("\n  "));
});

test("a server-paged fetch feeding a DataTable declares serverPaged", () => {
  const offenders = FILES
    .filter((f) => usesDataTable(f.src) && sendsOffset(f.src) && !declaresServerPaged(f.src))
    .map((f) => f.path);

  assert.deepEqual(offenders, [],
    "these ask the server for a slice and hand it to a DataTable without " +
    "telling it so, which leaves the footer paginating a page:\n  " +
    offenders.join("\n  "));
});

test("the serverPaged escape hatch exists and suppresses the inner pager", () => {
  const dt = FILES.find((f) => f.path.endsWith(path.join("ui", "data-table.tsx")));
  assert.ok(dt, "components/ui/data-table.tsx not found");
  assert.match(dt!.src, /serverPaged\?: ServerPaging/,
    "the prop the assertions above steer callers towards must exist");
  assert.match(dt!.src, /initialPageSize: serverPaged \? 0 : initialPageSize/,
    "with serverPaged the table must stop sub-paginating — pageSize 0 is " +
    "'all rows, one page' (lib/table/process.paginate). Without this the " +
    "inner pager would still slice the server's page.");
});

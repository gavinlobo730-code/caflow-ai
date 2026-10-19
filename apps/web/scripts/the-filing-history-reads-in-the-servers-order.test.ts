// The Filing History tab lists a client's filed GSTR-1 and GSTR-3B latest period first, in the order the SERVER ranks them.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-filing-history-reads-in-the-servers-order.test.ts
//
// WHAT WAS WRONG
//     The tab merged the two lists and sorted them by `created_at`, the instant each row was keyed in. For a return
//     recorded after the fact (every migrated client's first months, a year of returns recorded in one sitting) that
//     is the order somebody typed them, not the order of the periods, and the server's own list was unordered besides.
//     The server now answers latest period first and ranks every row with `period_order`; the tab merges on that
//     number and does no period arithmetic of its own.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join("app", "clients", "[id]", "compliance", "gst", "page.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

function tab(): string {
  const src = code(PAGE);
  const from = src.indexOf("function FilingHistoryTab");
  assert.ok(from > 0, "FilingHistoryTab is gone");
  return src.slice(from, src.indexOf("function completedFinancialYears", from));
}

test("the two filed lists are merged on the server's period_order and not on when each row was created", () => {
  const body = tab();
  assert.match(body, /period_order/, "the tab does not use the server's ranking");
  assert.doesNotMatch(body, /created_at/, "the tab sorts by when a row was keyed in");
});

test("the tab does no period arithmetic of its own", () => {
  const body = tab();
  assert.doesNotMatch(body, /slice\(2\)|substring|parseInt|\.padStart|new Date/,
    "a period is being parsed in the browser instead of ranked by the server");
});

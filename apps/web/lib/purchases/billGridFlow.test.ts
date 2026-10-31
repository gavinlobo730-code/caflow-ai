// POST-A-128 — Tab from the last cell of a bill line, as a pure rule.
//
// Run with: node --experimental-strip-types --test lib/purchases/billGridFlow.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { afterTab } from "./billGridFlow.ts";

const at = (over: Partial<Parameters<typeof afterTab>[0]> = {}) =>
  afterTab({ isLastDataCell: true, rowIndex: 0, rowCount: 3, lastLineHasContent: true, ...over });

test("Tab from a cell that is not the line's last data cell is the browser's", () => {
  assert.deepEqual(at({ isLastDataCell: false }), { kind: "default" });
  assert.deepEqual(at({ isLastDataCell: false, rowIndex: 2 }), { kind: "default" }, "not even on the last line");
});

test("Tab from the last data cell of any line but the last goes to the next line, whatever is on the last", () => {
  assert.deepEqual(at({ rowIndex: 0 }), { kind: "next" });
  assert.deepEqual(at({ rowIndex: 1, lastLineHasContent: false }), { kind: "next" });
});

test("on the last line it adds a line, but only when that line has something on it", () => {
  assert.deepEqual(at({ rowIndex: 2 }), { kind: "add" });
  assert.deepEqual(at({ rowIndex: 2, lastLineHasContent: false }), { kind: "default" },
    "Tab on an untouched blank last line is not a way to grow the bill");
});

test("a bill of one line behaves as the last line", () => {
  assert.deepEqual(at({ rowIndex: 0, rowCount: 1 }), { kind: "add" });
  assert.deepEqual(at({ rowIndex: 0, rowCount: 1, lastLineHasContent: false }), { kind: "default" });
});

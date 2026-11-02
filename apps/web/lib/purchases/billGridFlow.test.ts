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

// ── The copy (Ctrl+D) keeps what the document did not state ───────────────────────────────────────────
import { copyOfLine } from "./billGridFlow.ts";
import { lineFromExtraction } from "./extractedLine.ts";
import { isValidBillLine } from "./billEditor.ts";

test("a copy of an extracted line keeps its not-stated flags, so the copy still blocks the save until the CA states the rate", () => {
  const original = { ...lineFromExtraction({ description: "Freight", hsn_sac: "9965", quantity: 1, unit: "NOS", rate_paise: 100_000, gst_rate_bps: null }), _k: 1 };
  assert.deepEqual(original.unread, ["gst_rate"], "the fixture no longer leaves the GST rate unstated");
  assert.equal(isValidBillLine(original), false, "the original must block the save");
  const copy = copyOfLine(original, 2);
  assert.equal(copy._k, 2);
  assert.deepEqual(copy.unread, ["gst_rate"]);
  assert.equal(isValidBillLine(copy), false, "a copy that dropped the flag read a GST rate nobody chose as a chosen 0%");
});

test("the copy's flags are its own: clearing one line's does not clear the other's", () => {
  const original = { _k: 1, unread: ["gst_rate", "rate"] as string[] };
  const copy = copyOfLine(original, 2);
  copy.unread!.splice(0, 1);
  assert.deepEqual(original.unread, ["gst_rate", "rate"]);
  assert.deepEqual(copy.unread, ["rate"]);
});

test("a typed line has no flags and its copy has none", () => {
  assert.equal(copyOfLine({ _k: 1 }, 2).unread, undefined);
  assert.equal(copyOfLine({ _k: 1, unread: undefined }, 2).unread, undefined);
});

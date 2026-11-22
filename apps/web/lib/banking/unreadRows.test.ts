// Run with: node --experimental-strip-types --test lib/banking/unreadRows.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { unreadHeading, unreadRowsOf, whatStopped } from "./unreadRows.ts";

test("the unread rows of an answer are read in order, with a missing date as null", () => {
  const rows = unreadRowsOf({ unread_rows: [
    { column: "debit", cell: "12x4.00", date: "2026-04-03", description: "UPI to vendor" },
    { column: "date", cell: "3rd April", date: null, description: "Cheque" }] });
  assert.deepEqual(rows, [
    { column: "debit", cell: "12x4.00", date: "2026-04-03", description: "UPI to vendor" },
    { column: "date", cell: "3rd April", date: null, description: "Cheque" }]);
});

test("an answer without the key, or with a shape this screen does not know, shows nothing and invents nothing", () => {
  assert.deepEqual(unreadRowsOf({ imported: 3 }), []);
  assert.deepEqual(unreadRowsOf(null), []);
  assert.deepEqual(unreadRowsOf(undefined), []);
  assert.deepEqual(unreadRowsOf({ unread_rows: "3 rows" }), []);
  assert.deepEqual(unreadRowsOf({ unread_rows: [null, 4, { column: "debit" }, { cell: "x" }] }), []);
  assert.deepEqual(unreadRowsOf({ unread_rows: [{ column: "amount", cell: "1.2.3" }] }),
    [{ column: "amount", cell: "1.2.3", date: null, description: "" }]);
});

test("the heading counts in words that agree with the number, and a row says what stopped it", () => {
  assert.equal(unreadHeading(1), "1 row of the file could not be read and is not in these figures.");
  assert.equal(unreadHeading(4), "4 rows of the file could not be read and are not in these figures.");
  assert.equal(whatStopped({ column: "amount", cell: "1.2.3", date: null, description: "" }), 'the amount is printed as "1.2.3"');
});

test("the upload panel draws the unread rows in the preview and beside the import's result", () => {
  const src = readFileSync(new URL("../../components/banking/AccountsPanel.tsx", import.meta.url), "utf8");
  assert.match(src, /<UnreadRows rows=\{unreadRowsOf\(preview\)\}/, "the preview does not show the rows that were not read");
  assert.match(src, /<UnreadRows rows=\{unreadRowsOf\(result\)\}/, "the import's result does not show the rows that were not read");
});

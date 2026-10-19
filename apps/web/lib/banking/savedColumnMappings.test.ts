// The statement layouts the product has been taught: reading and describing them. Run with:
//   node --experimental-strip-types --test lib/banking/savedColumnMappings.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { describeMapping, MAPPING_FIELDS, readSavedMappings } from "./savedColumnMappings.ts";

const HEADERS = ["Txn Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Closing Balance"];

test("a mapping reads as field <- the label the CA saw, in reading order", () => {
  const out = describeMapping({ date: 0, desc: 1, ref: 2, debit: 3, credit: 4, balance: 5 }, HEADERS);
  assert.deepEqual(out, [
    { label: "Date", column: '"Txn Date"' },
    { label: "Description", column: '"Narration"' },
    { label: "Reference", column: '"Chq/Ref No"' },
    { label: "Debit", column: '"Withdrawal"' },
    { label: "Credit", column: '"Deposit"' },
    { label: "Balance", column: '"Closing Balance"' },
  ]);
});

test("a field that is not mapped is left out and nothing is invented for it", () => {
  const out = describeMapping({ date: 0, desc: 1, amount: 3, drcr: 4, debit: null, credit: null }, HEADERS);
  assert.deepEqual(out.map((f) => f.label), ["Date", "Description", "Amount", "Dr/Cr"]);
});

test("a position the saved header cannot name is shown as its position, counted from 1", () => {
  assert.deepEqual(describeMapping({ date: 0, desc: 9 }, HEADERS), [
    { label: "Date", column: '"Txn Date"' },
    { label: "Description", column: "column 10" },
  ]);
  assert.deepEqual(describeMapping({ date: 0, desc: 1 }, null), [
    { label: "Date", column: "column 1" },
    { label: "Description", column: "column 2" },
  ]);
  assert.deepEqual(describeMapping({ date: 0, desc: 1 }, ["", "  "]), [
    { label: "Date", column: "column 1" },
    { label: "Description", column: "column 2" },
  ]);
});

test("a value that is not a column position is not a mapped field", () => {
  assert.deepEqual(describeMapping({ date: "0", desc: -1, ref: 1.5, debit: true }, HEADERS), []);
});

test("the field list is the eight the server's mapping may carry", () => {
  assert.deepEqual(MAPPING_FIELDS.map((f) => f.key), ["date", "desc", "ref", "debit", "credit", "amount", "drcr", "balance"]);
});

const row = (id: string) => ({ id, client_id: "c1", bank_account_id: "a1", header_labels: HEADERS, mapping: { date: 0, desc: 1 },
  created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z" });

test("a window is read with the server's has_more and ceiling", () => {
  const w = readSavedMappings({ mappings: [row("a"), row("b")], returned: 2, has_more: true, limit: 100, max_limit: 500 }, 100);
  assert.ok(w);
  assert.equal(w.rows.length, 2);
  assert.equal(w.hasMore, true);
  assert.equal(w.maxLimit, 500);
});

test("an empty window is an empty list and a refusal is not a list", () => {
  const empty = readSavedMappings({ mappings: [], has_more: false, limit: 100, max_limit: 500 }, 100);
  assert.ok(empty);
  assert.deepEqual(empty.rows, []);
  for (const data of [null, undefined, "no", 7, {}, { detail: "forbidden" }]) {
    assert.equal(readSavedMappings(data, 100), null, JSON.stringify(data));
  }
});

test("a row without an id is dropped and a bare list from an older server is read as complete", () => {
  const w = readSavedMappings({ mappings: [row("a"), null, { mapping: {} }, row("b")], has_more: false, limit: 100, max_limit: 500 }, 100);
  assert.ok(w);
  assert.deepEqual(w.rows.map((r) => r.id), ["a", "b"]);
  const bare = readSavedMappings([row("a")], 100);
  assert.ok(bare);
  assert.equal(bare.hasMore, false);
});

// Run with: node --experimental-strip-types --test lib/loading/firstRead.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { FirstReadGate } from "./firstRead.ts";

test("the first read of a key blocks and a later read of the same key does not", () => {
  const g = new FirstReadGate();
  const first = g.begin("C1");
  assert.equal(first.blocks, true);
  g.landed(first.read, "C1");
  assert.equal(g.begin("C1").blocks, false);
});

test("a failed read is not a read: the next one blocks again", () => {
  const g = new FirstReadGate();
  const first = g.begin("C1");
  g.failed(first.read);
  assert.equal(g.begin("C1").blocks, true);
  const ok = g.begin("C1");
  g.landed(ok.read, "C1");
  const later = g.begin("C1");
  g.failed(later.read);
  assert.equal(g.begin("C1").blocks, true, "a later read that failed makes the next one a first read again");
});

test("another key blocks again", () => {
  const g = new FirstReadGate();
  const a = g.begin("C1");
  g.landed(a.read, "C1");
  assert.equal(g.begin("C2").blocks, true);
});

test("the latest question wins: a stale answer neither fills nor marks the key read", () => {
  const g = new FirstReadGate();
  const older = g.begin("C1");
  const newer = g.begin("C1");
  assert.equal(g.isLatest(older.read), false);
  assert.equal(g.isLatest(newer.read), true);
  g.landed(older.read, "C1");                 // the older answer arrives first and is ignored
  assert.equal(g.begin("C1").blocks, true);
  const third = g.begin("C1");
  g.landed(third.read, "C1");
  g.failed(older.read);                        // a stale failure changes nothing
  assert.equal(g.begin("C1").blocks, false);
});

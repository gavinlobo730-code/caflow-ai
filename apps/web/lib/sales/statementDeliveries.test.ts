// The delivery log of emailed statements: reading the server's window. Run with:
//   node --experimental-strip-types --test lib/sales/statementDeliveries.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { deliveryStatusLabel, readStatementDeliveries, STATEMENT_DELIVERY_NOTE } from "./statementDeliveries.ts";

const row = (id: string, over: Record<string, unknown> = {}) => ({
  id, period_start: "2026-04-01", period_end: "2026-04-30", sent_to: "ap@acme.test", sent_by_email: "ca@firm.test",
  status: "sent", error_message: null, sent_at: "2026-05-02T10:00:00Z", created_at: "2026-05-02T10:00:00Z", ...over,
});

test("a window is read with the server's has_more and ceiling", () => {
  const w = readStatementDeliveries({ deliveries: [row("a"), row("b")], returned: 2, has_more: true, limit: 50, max_limit: 500 }, 50);
  assert.ok(w);
  assert.equal(w.rows.length, 2);
  assert.equal(w.hasMore, true);
  assert.equal(w.limit, 50);
  assert.equal(w.maxLimit, 500);
});

test("a window that is the whole list says so, and an empty one is an empty list not a failure", () => {
  const w = readStatementDeliveries({ deliveries: [], returned: 0, has_more: false, limit: 50, max_limit: 500 }, 50);
  assert.ok(w);
  assert.deepEqual(w.rows, []);
  assert.equal(w.hasMore, false);
});

test("a refusal, a scalar and null are not a list and read as null so the screen can say it could not read the log", () => {
  for (const data of [null, undefined, "no", 7, {}, { detail: "forbidden" }]) {
    assert.equal(readStatementDeliveries(data, 50), null, JSON.stringify(data));
  }
});

test("a bare list from a server that predates the window is read as complete", () => {
  const w = readStatementDeliveries([row("a")], 50);
  assert.ok(w);
  assert.equal(w.rows.length, 1);
  assert.equal(w.hasMore, false);
});

test("a row that cannot be drawn is dropped, the rest kept", () => {
  const w = readStatementDeliveries({ deliveries: [row("a"), null, "x", { sent_to: "no id" }, row("b")], has_more: false, limit: 50, max_limit: 500 }, 50);
  assert.ok(w);
  assert.deepEqual(w.rows.map((r) => r.id), ["a", "b"]);
});

test("has_more is true only when the server said true, never inferred from the row count", () => {
  const rows = Array.from({ length: 50 }, (_, i) => row(`r${i}`));
  const w = readStatementDeliveries({ deliveries: rows, has_more: false, limit: 50, max_limit: 500 }, 50);
  assert.ok(w);
  assert.equal(w.rows.length, 50);
  assert.equal(w.hasMore, false);
});

test("a status is labelled, and one this build does not know is shown as it came", () => {
  assert.equal(deliveryStatusLabel("sent"), "Sent");
  assert.equal(deliveryStatusLabel("bounced"), "Bounced");
  assert.equal(deliveryStatusLabel("spam_trapped"), "spam_trapped");
});

test("the note does not let Sent read as received", () => {
  assert.match(STATEMENT_DELIVERY_NOTE, /accepted the message/);
  assert.match(STATEMENT_DELIVERY_NOTE, /does not say the customer opened it/);
});

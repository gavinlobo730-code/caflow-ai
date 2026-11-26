// The Delivery Challans form names the sales order a challan delivers against, and the order line of each line (POST-A-421). Run with:
//   node --experimental-strip-types --test scripts/a-delivery-challan-form-names-the-order-it-delivers-against.test.ts
//
// The API took `order_id` and a line's `order_line_id` from any client and the form sent neither, so the link was reachable only through the API. This holds the screen's half from the source:
// the order list is the server's own (orders open to delivery, `only_open`), what each line has undelivered is the server's position, the choice is sent, and the screen computes nothing about it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const src = fs.readFileSync(path.join(import.meta.dirname, "..", "components/sales/SalesCycleTab.tsx"), "utf8");

test("the form lists the orders the server says are open to delivery and reads each one's position from the server", () => {
  assert.match(src, /api\.salesCycle\.orders\(clientId, true\)/);
  assert.match(src, /api\.salesCycle\.orderPosition\(orderId, clientId\)/);
  assert.match(src, /Against a sales order \(optional\)/);
});

test("the choice is sent: order_id on the challan and order_line_id on a line only where an order is chosen", () => {
  assert.match(src, /order_id: form\.order_id \|\| null/);
  assert.match(src, /tab === "challans" && form\.order_id && l\.order_line_id \? \{ order_line_id: l\.order_line_id \} : \{\}/);
});

test("a line's order line is offered with the server's undelivered quantity, and the screen does no arithmetic on it", () => {
  assert.match(src, /\{ol\.description\} — \{ol\.undelivered_qty\} undelivered/);
  assert.doesNotMatch(src, /undelivered_qty\)\s*[-+*]/);
});

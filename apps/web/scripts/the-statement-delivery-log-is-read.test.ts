// The Sales tab shows whether an emailed statement went out. Run with:
//   node --experimental-strip-types --test scripts/the-statement-delivery-log-is-read.test.ts
//
// WHY THIS EXISTS
//     The send path wrote a delivery row for every statement email and no screen read it back, so a CA saw "sent" from the
//     modal and nothing after: a failed or bounced message was invisible. The log is read through the one window reader
//     (apps/api/core/list_window.py is the server's half), "could not be read" is a different statement from "nothing has
//     been sent", and the log is re-read after a send whether it worked or not, because a failed send is the row that matters.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}
const LOG = "components/sales/StatementDeliveryLog.tsx";
const SALES = "app/clients/[id]/sales/page.tsx";

test("the component asks for one customer's log in a window and reads it through the one reader", () => {
  const src = code(LOG);
  assert.match(src, /\/api\/customer-statements\/deliveries\?client_id=/);
  assert.match(src, /customer_id=\$\{encodeURIComponent\(customerId\)\}&limit=\$\{limit\}/);
  assert.match(src, /readStatementDeliveries\(res\.data, limit\)/, "the payload is a window, not a bare array");
  assert.doesNotMatch(src, /res\.data as/, "no cast stands in for reading the window");
});

test("a log that could not be read is not drawn as an empty one", () => {
  const src = code(LOG);
  assert.match(src, /kind: "unreadable"/);
  assert.match(src, /could not be loaded\. This is not the same as nothing having been sent/);
  assert.match(src, /title="No statement has been emailed to this customer yet"/);
  assert.match(src, /<EmptyState/, "the empty line says what to do next, through the shared empty state");
  // The two states are different branches: an error never falls through to the empty line.
  assert.match(src, /state\.kind === "ready" && state\.rows\.length === 0/);
});

test("Sent is not allowed to read as received, and the window notice is mounted", () => {
  const src = code(LOG);
  assert.match(src, /STATEMENT_DELIVERY_NOTE/);
  assert.match(src, /<ListWindowNotice/);
  assert.match(src, /onShowMore=\{\(next\) => setLimit\(next\)\}/);
});

test("the Sales tab mounts the log for the chosen customer and re-reads it after every send", () => {
  const src = code(SALES);
  assert.match(src, /import \{ StatementDeliveryLog \} from "@\/components\/sales\/StatementDeliveryLog";/);
  assert.match(src, /\{customerId && <StatementDeliveryLog clientId=\{clientId\} customerId=\{customerId\} refreshKey=\{deliveryRefresh\} \/>\}/);
  // success AND failure bump it: a failed send is the row a CA most needs to see
  const bumps = src.match(/setDeliveryRefresh\(\(k\) => k \+ 1\)/g) ?? [];
  assert.equal(bumps.length, 2, "both branches of sendEmail refresh the log");
});

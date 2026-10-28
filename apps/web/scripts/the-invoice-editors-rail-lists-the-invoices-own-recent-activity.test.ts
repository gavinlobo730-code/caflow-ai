// POST-A-150. The invoice editor's summary rail lists the invoice's own latest events, and the read is made by the component and not by the
// 1,500-line editor.
//
// WHAT WAS MISSING
//   F5 of the density audit: the edit-mode rail never got a short activity list, although the Hub drawer already draws the document's
//   timeline. A CA correcting an invoice could not see that it had been issued or emailed without leaving the page.
//
// WHAT IS HELD
//   * the component asks the server for THIS document's events through the shared reader (never the client's whole timeline, never a
//     filter in the browser) and draws a failed read with the words that say it failed;
//   * the editor renders it only for an invoice that exists (an edit), under the same `sales_invoice` kind the drawer reads, and makes
//     no timeline read of its own;
//   * which events show and when to say older ones exist is `miniActivity`, tested in lib/documents/activity.test.ts.
//
// Run with: node --experimental-strip-types --test scripts/the-invoice-editors-rail-lists-the-invoices-own-recent-activity.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const MINI = read("components/documents/ActivityMini.tsx");
const EDITOR = read("components/invoices/InvoiceEditor.tsx");

test("the files are where this guard thinks they are", () => {
  assert.ok(MINI.length > 1500, `ActivityMini read as ${MINI.length} chars`);
  assert.ok(EDITOR.length > 40000, `InvoiceEditor read as ${EDITOR.length} chars`);
});

test("the component reads the document's own events through the shared reader and never reads a failure as an empty history", () => {
  assert.match(MINI, /documentActivityUrl\(clientId, entityType, entityId\)/, "it does not ask for the document's own events");
  assert.doesNotMatch(MINI, /\/api\/timeline\?/, "it reads the client's whole timeline");
  assert.match(MINI, /readDocumentActivity\(tl, entityType, entityId\)/, "it does not read the window through the shared reader");
  assert.match(MINI, /emptyActivityLine\(status\)/, "a failed read is drawn as an empty history");
  assert.match(MINI, /miniActivity\(items, status\)/, "it decides what to show and what to say itself");
  assert.doesNotMatch(MINI, /\.filter\(\(e\) => e\.entity_type ===/, "it filters the client's events in the browser");
  assert.match(MINI, /setStatus\(\{ read: false \}\)/, "a thrown read is not said");
});

test("the editor shows it for an invoice that exists, and makes no timeline read of its own", () => {
  assert.match(EDITOR, /isEdit && existing\?\.id && <ActivityMini clientId=\{clientId\} entityType="sales_invoice" entityId=\{existing\.id\} \/>/,
    "the rail does not list the invoice's activity in edit mode");
  assert.doesNotMatch(EDITOR, /documentActivityUrl|readDocumentActivity|\/api\/timeline/, "the editor reads the timeline itself");
});

// POST-A-259. A document's activity is read for the document and says when it stopped.
//   node --experimental-strip-types --test lib/documents/activity.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  ACTIVITY_NOT_YET_ASKED, DOCUMENT_ACTIVITY_WINDOW, activityItems, activityStatusOf, documentActivityUrl,
  emptyActivityLine, readDocumentActivity,
} from "./activity.ts";

const DOC = "11111111-1111-4111-8111-111111111111";

test("the read names the client, the record's kind and its id, and asks for a window", () => {
  const url = documentActivityUrl("C 1", "purchase_bill", DOC);
  const u = new URL(url, "http://x");
  assert.equal(u.pathname, "/api/timeline");
  assert.equal(u.searchParams.get("client_id"), "C 1");
  assert.equal(u.searchParams.get("entity_type"), "purchase_bill");
  assert.equal(u.searchParams.get("entity_id"), DOC);
  assert.equal(u.searchParams.get("limit"), String(DOCUMENT_ACTIVITY_WINDOW));
});

test("a failed read is not an empty history", () => {
  assert.equal(readDocumentActivity({ success: false, data: null }, "sales_invoice", DOC), null);
  assert.equal(readDocumentActivity(null, "sales_invoice", DOC), null);
  assert.equal(readDocumentActivity({ success: true, data: "nope" }, "sales_invoice", DOC), null);
  const status = activityStatusOf(null);
  assert.equal(status.read, false);
  assert.equal(emptyActivityLine(status), "The activity could not be loaded.");
});

test("a window the server answered is taken as filtered by the server, and says if older entries exist", () => {
  const events = [{ entity_type: "sales_invoice", entity_id: DOC, created_at: "2026-01-02T00:00:00Z", title: "Issued" }];
  const win = readDocumentActivity({ success: true, data: { events, has_more: true, limit: 100, max_limit: 500 } }, "sales_invoice", DOC);
  assert.equal(win?.rows.length, 1);
  assert.equal(win?.hasMore, true);
  const status = activityStatusOf(win);
  assert.deepEqual(status, { read: true, hasMore: true, limit: 100, maxLimit: 500 });
  assert.equal(emptyActivityLine(status), "No activity recorded yet.");
});

test("a bare list from a server that predates the filter is matched on the record here, and only then", () => {
  const events = [
    { entity_type: "sales_invoice", entity_id: DOC, created_at: "2026-01-02T00:00:00Z", title: "mine" },
    { entity_type: "sales_invoice", entity_id: "other", created_at: "2026-01-03T00:00:00Z", title: "not mine" },
    { entity_type: "credit_note", entity_id: DOC, created_at: "2026-01-04T00:00:00Z", title: "other kind" },
  ];
  const win = readDocumentActivity({ success: true, data: events }, "sales_invoice", DOC);
  assert.deepEqual(win?.rows.map((e) => e.title), ["mine"]);
  assert.equal(win?.hasMore, false);
});

test("nothing is claimed to be cut short before anything has been asked", () => {
  assert.equal(ACTIVITY_NOT_YET_ASKED.read && ACTIVITY_NOT_YET_ASKED.hasMore, false);
});

test("entries list newest first, and an undated one is left out", () => {
  const items = activityItems([
    { title: "old", created_at: "2026-01-01T00:00:00Z" },
    { title: "new", created_at: "2026-01-03T00:00:00Z", description: "detail" },
    { title: "undated" },
    { event_type: "reversed", created_at: "2026-01-02T00:00:00Z" },
  ]);
  assert.deepEqual(items.map((i) => i.title), ["new", "reversed", "old"]);
  assert.equal(items[0].detail, "detail");
});

// POST-A-543, Request access: reading a person's own requests, and where one permission stands.
//   node --experimental-strip-types --test lib/access/accessRequest.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readMine, standingOf } from "./accessRequest.ts";

const row = (over: Record<string, unknown>) => ({ id: "a-1", resource: "payroll", action: "read", status: "pending", asked_at: "2026-11-21T10:00:00Z", decided_at: null, reason: null, ...over });

test("an answer that is not the list is not read as an empty one", () => {
  for (const bad of [null, undefined, "x", 3, [], {}, { requests: "none" }, { requests: null }]) assert.equal(readMine(bad), null);
  assert.deepEqual(readMine({ requests: [] }), []);
});

test("a row is read by kind, and a row without what identifies it is dropped", () => {
  const got = readMine({ requests: [row({}), row({ id: "" }), row({ resource: 7 }), "junk", null, row({ id: "a-2", status: "rejected", reason: "not now", decided_at: "2026-11-21T11:00:00Z" })] });
  assert.deepEqual(got?.map((r) => r.id), ["a-1", "a-2"]);
  assert.deepEqual(got?.[1], { id: "a-2", resource: "payroll", action: "read", status: "rejected", askedAt: "2026-11-21T10:00:00Z", decidedAt: "2026-11-21T11:00:00Z", reason: "not now" });
});

test("the newest request for a permission says where it stands", () => {
  const rows = readMine({ requests: [
    row({ id: "new", status: "pending" }),
    row({ id: "old", status: "rejected", reason: "earlier" }),
    row({ id: "other", resource: "risk", status: "rejected", reason: "no", decided_at: "2026-11-20T09:00:00Z" }),
    row({ id: "done", resource: "gst", status: "approved" }),
    row({ id: "gone", resource: "tds", status: "cancelled" }),
  ] })!;
  assert.deepEqual(standingOf(rows, "payroll", "read"), { kind: "waiting", askedAt: "2026-11-21T10:00:00Z" });
  assert.deepEqual(standingOf(rows, "risk", "read"), { kind: "declined", decidedAt: "2026-11-20T09:00:00Z", reason: "no" });
  // Approved once and refused now: the permission was taken away since, so they may ask again. So may somebody who cancelled.
  assert.deepEqual(standingOf(rows, "gst", "read"), { kind: "none" });
  assert.deepEqual(standingOf(rows, "tds", "read"), { kind: "none" });
  assert.deepEqual(standingOf(rows, "payroll", "write"), { kind: "none" }, "another action of the same resource was read as this one");
  assert.deepEqual(standingOf([], "payroll", "read"), { kind: "none" });
});

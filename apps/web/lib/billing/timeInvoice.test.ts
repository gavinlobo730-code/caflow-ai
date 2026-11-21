// POST-B-194, hourly billing: reading the server's answers by kind.
//   node --experimental-strip-types --test lib/billing/timeInvoice.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { GROUPINGS, GROUPING_LABELS, billableIds, gstPercentTyped, readMade, readPreview, readServices, readUnbilledEntries } from "./timeInvoice.ts";

const entry = (over: Record<string, unknown> = {}) => ({ id: "e-1", day: "2026-11-10", user_name: "Asha Rao", task_title: "GST returns",
  description: "GSTR-1", minutes: 60, rate_paise: 150000, value_paise: 150000, blocked: null, ...over });

test("the entries are read by kind, an unknown worth stays unknown, and an answer that is not the list is not an empty one", () => {
  for (const bad of [null, undefined, [], "x", {}, { entries: [] }, { entries: "none", billable_count: 0, billable_minutes: 0, billable_value_paise: 0 }]) {
    assert.equal(readUnbilledEntries(bad), null);
  }
  const got = readUnbilledEntries({ entries: [entry(), entry({ id: "e-2", rate_paise: null, value_paise: null, blocked: "It has no rate. Set its rate first." })],
    billable_count: 1, billable_minutes: 60, billable_value_paise: 150000 });
  assert.equal(got?.entries.length, 2);
  assert.equal(got?.entries[1].valuePaise, null, "an entry with no rate was given a worth");
  assert.equal(got?.entries[1].blocked, "It has no rate. Set its rate first.");
  assert.deepEqual(billableIds(got!.entries), ["e-1"]);
  // One row that cannot be read makes the list unreadable: a shorter list would bill less than was shown.
  assert.equal(readUnbilledEntries({ entries: [entry(), { id: "e-9" }], billable_count: 1, billable_minutes: 60, billable_value_paise: 150000 }), null);
});

test("a preview and a made draft are read whole or not at all", () => {
  const preview = readPreview({ lines: [{ description: "GST returns: 1 h", minutes: 60, value_paise: 150000 }], entries: 1, minutes: 60, value_paise: 150000 });
  assert.deepEqual(preview, { lines: [{ description: "GST returns: 1 h", minutes: 60, valuePaise: 150000 }], entries: 1, minutes: 60, valuePaise: 150000 });
  assert.equal(readPreview({ lines: [{ description: "x", minutes: 60 }], entries: 1, minutes: 60, value_paise: 1 }), null);
  assert.equal(readPreview({ lines: [], entries: 0, minutes: 0 }), null);
  assert.deepEqual(readMade({ invoice_id: "inv-1", practice_client_id: "c-p", entries_billed: 3, value_paise: 286666 }),
    { invoiceId: "inv-1", practiceClientId: "c-p", entriesBilled: 3, valuePaise: 286666 });
  assert.equal(readMade({ invoice_id: "", entries_billed: 3, value_paise: 1 }), null);
  assert.equal(readMade(null), null);
});

test("the practice's services carry the rate recorded against each, or none", () => {
  assert.equal(readServices({}), null);
  assert.deepEqual(readServices({ services: [{ id: "s-1", name: "Professional fees", gst_rate_bps: 1800 }, { id: "s-2", name: "Advice", gst_rate_bps: null }, { id: "", name: "x" }, "junk", { id: "s-3", name: "Old", gst_rate_bps: "500" }] }),
    [{ id: "s-1", name: "Professional fees", gstRateBps: 1800 }, { id: "s-2", name: "Advice", gstRateBps: null }, { id: "s-3", name: "Old", gstRateBps: 500 }]);
});

test("a rate of GST is a plain percentage between 0 and 100, and anything else is not sent", () => {
  assert.equal(gstPercentTyped("18"), 18);
  assert.equal(gstPercentTyped(" 7.5 "), 7.5);
  assert.equal(gstPercentTyped("0"), 0);
  for (const bad of ["", "18%", "1e1", "-5", "101", "abc", "1.234", "1,8"]) assert.equal(gstPercentTyped(bad), null, bad);
});

test("every way of laying the time out has words", () => {
  assert.deepEqual([...GROUPINGS].sort(), Object.keys(GROUPING_LABELS).sort());
});

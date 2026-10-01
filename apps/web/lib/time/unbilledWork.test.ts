// practice_management-11: the unbilled-work answer is always fully shaped, and
// "no rate" never leaks into the total.
//   node --experimental-strip-types --test lib/time/unbilledWork.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { nothingUnbilled, readUnbilledWork } from "./unbilledWork.ts";

const EMPTY = readUnbilledWork(null);

for (const [label, payload] of [
  ["null", null], ["undefined", undefined], ["an array", []], ["a string", "error"], ["{}", {}],
  ["a half-deployed backend", { by_client: [], no_rate: { entries: "nope", count: "3" } }],
] as const) {
  test(`${label} reads as nothing unbilled and cannot throw on a list or a record`, () => {
    const w = readUnbilledWork(payload);
    assert.deepEqual(w.no_rate.entries.map((e) => e.id), []);
    assert.deepEqual(Object.keys(w.by_client), []);
    assert.deepEqual(Object.keys(w.by_work_item), []);
    assert.equal(w.total_value_paise, 0);
    assert.equal(w.no_rate.count, 0, "a string count is not a count");
    assert.equal(nothingUnbilled(w), true);
  });
}

test("a real answer is carried through untouched", () => {
  const w = readUnbilledWork({
    by_client: { c1: { minutes: 90, value_paise: 375000, count: 2 } },
    by_work_item: { t1: { minutes: 90, value_paise: 375000, count: 2 } },
    total_value_paise: 375000, priced_minutes: 90, total_minutes: 140,
    no_rate: {
      count: 1, minutes: 50, by_client: { c1: { minutes: 50, count: 1 } },
      entries: [{ id: "e9", user_name: "Asha", client_id: "c1", duration_minutes: 50 }],
    },
  });
  assert.equal(w.total_value_paise, 375000);
  assert.equal(w.by_client.c1.count, 2);
  assert.equal(w.no_rate.count, 1);
  assert.equal(w.no_rate.entries[0].user_name, "Asha");
  assert.equal(nothingUnbilled(w), false);
});

test("the no-rate time is a section of its own and is not part of the value", () => {
  const w = readUnbilledWork({ total_value_paise: 0, total_minutes: 50, no_rate: { count: 1, minutes: 50 } });
  assert.equal(w.total_value_paise, 0, "50 minutes with no rate are worth NOTHING KNOWN, not a figure");
  assert.equal(w.no_rate.minutes, 50);
  assert.equal(nothingUnbilled(w), false, "work with no rate is still unbilled work");
});

test("a client with only a record in by_client is not confused with the empty answer", () => {
  assert.notDeepEqual(readUnbilledWork({ by_client: { c1: { minutes: 1, value_paise: 1, count: 1 } } }), EMPTY);
});
